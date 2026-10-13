import hashlib
from http import client as http_client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import unittest
from urllib import parse

import camera_client as cc

SPEC = (Path(__file__).resolve().parents[1] / 'api/openapi.json').read_bytes()
TOKEN = 'synthetic-ui-test-token-00000001'


class WireTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.mode = [], 'ok'

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                cls.events.append((self.command, self.path, dict(self.headers), body))
                status, data = 200, {'request_id': 'test-request'}
                path = parse.urlsplit(self.path).path
                if path == '/openapi.json':
                    content = SPEC if cls.mode != 'wrong-spec' else b'{}'
                else:
                    if cls.mode == 'partial-chunk':
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Transfer-Encoding', 'chunked')
                        self.end_headers()
                        self.wfile.write(b'5\r\nabc')
                        self.close_connection = True
                        return
                    if cls.mode == 'drop' and self.command != 'GET':
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    if cls.mode == 'redirect' and path == '/api/v1/devices':
                        self.send_response(302)
                        self.send_header('Location', self.server.redirect_target)
                        self.end_headers()
                        return
                    if path == '/health/ready':
                        data.update(ready=True, scope='camera_registry', business_runtime_ready=False)
                    elif path == '/api/v1/platform':
                        data.update(platform='camera', version=cc.API_VERSION)
                    elif self.command == 'GET' and path in ('/api/v1/devices', '/api/v1/sources'):
                        data.update(items=[], next_cursor=None)
                    elif self.command != 'GET':
                        status = 503 if cls.mode == '503' else 409 if cls.mode == '409' else 200 if self.command != 'POST' else 201
                        if status >= 400:
                            data['error'] = {'code': 'DEVICE_VERSION_CONFLICT' if status == 409 else 'DATABASE_UNAVAILABLE', 'message': 'synthetic'}
                        else:
                            data['device'] = json.loads(body)
                    content = json.dumps(data).encode()
                    if cls.mode == 'bad-json':
                        content = b'PRIVATE_NON_JSON_RESPONSE'
                    if cls.mode == 'large':
                        content = b' ' * (cc.MAX_RESPONSE + 1)
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('X-Request-ID', 'test-request')
                self.send_header('Idempotency-Replayed', 'false')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = handle_request
            do_POST = handle_request
            do_PATCH = handle_request
            do_DELETE = handle_request

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        type(self).events = []
        type(self).mode = 'ok'
        self.client = cc.CameraClient(self.base, TOKEN)

    def proposed(self, action='create', kind='devices'):
        body = cc.device_body('device-1', '테스트 카메라', 'TEST') if action == 'create' else cc.change_body('9223372036854775807', '수정' if action == 'update' else None)
        return cc.mutation(self.base, kind, action, 'device-1', body)

    def test_published_spec_digest_and_public_auth_boundaries(self):
        self.assertEqual(hashlib.sha256(SPEC).hexdigest(), cc.SPEC_SHA256)
        ready, platform = self.client.connect()
        self.assertTrue(ready.ok and platform.ok)
        self.assertNotIn('Authorization', self.events[0][2])
        self.assertNotIn('Authorization', self.events[1][2])
        self.assertEqual(self.events[2][2]['Authorization'], 'Bearer ' + TOKEN)
        self.assertNotIn(TOKEN, repr(self.client))

    def test_wrong_spec_prevents_any_mutation(self):
        type(self).mode = 'wrong-spec'
        pending = cc.Pending(self.proposed())
        with self.assertRaises(cc.ClientError):
            self.client.send(pending)
        self.assertEqual([x[0] for x in self.events], ['GET'])

    def test_delete_body_and_exact_int64_wire_token(self):
        pending = cc.Pending(self.proposed('delete'))
        self.assertTrue(self.client.send(pending).ok)
        method, path, headers, body = self.events[-1]
        self.assertEqual((method, path), ('DELETE', '/api/v1/devices/device-1'))
        self.assertEqual(json.loads(body)['expected_version'], 9223372036854775807)
        self.assertIn(b'9223372036854775807', body)
        self.assertEqual(headers['Idempotency-Key'], pending.mutation.key)

    def test_dropped_response_retries_identical_request(self):
        pending = cc.Pending(self.proposed('update'))
        type(self).mode = 'drop'
        with self.assertRaises(cc.ClientError):
            self.client.send(pending)
        self.assertTrue(pending.uncertain)
        first = self.events[-1]
        type(self).mode = 'ok'
        self.client.send(pending)
        second = self.events[-1]
        self.assertEqual(first[0:2], second[0:2])
        self.assertEqual(first[2]['Idempotency-Key'], second[2]['Idempotency-Key'])
        self.assertEqual(first[3], second[3])
        self.assertFalse(pending.uncertain)

    def test_503_remains_uncertain_and_409_is_resolved(self):
        pending = cc.Pending(self.proposed())
        for mode, uncertain in [('503', True), ('409', False)]:
            type(self).mode = mode
            result = self.client.send(pending)
            self.assertEqual(pending.uncertain, uncertain)
            self.assertFalse(result.ok)
            self.assertEqual(result.request_id, 'test-request')

    def test_no_redirect_sends_no_credentials_to_other_target(self):
        requests = []

        class Sink(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        sink = ThreadingHTTPServer(('127.0.0.1', 0), Sink)
        thread = threading.Thread(target=sink.serve_forever, daemon=True)
        thread.start()
        try:
            self.server.redirect_target = 'http://127.0.0.1:' + str(sink.server_port) + '/sink'
            type(self).mode = 'redirect'
            with self.assertRaises(cc.ClientError):
                self.client.list_items('devices')
            self.assertEqual(requests, [])
        finally:
            sink.shutdown()
            sink.server_close()
            thread.join(2)

    def test_invalid_response_and_bound_do_not_echo_raw_data(self):
        for mode in ('bad-json', 'large', 'partial-chunk'):
            type(self).mode = mode
            with self.assertRaises(cc.ClientError) as raised:
                self.client.list_items('devices')
            self.assertNotIn('PRIVATE', str(raised.exception))
            self.assertNotIn(TOKEN, str(raised.exception))

    def test_cursor_uses_same_filter_and_encodes_opaque_token(self):
        self.client.list_items('sources', 17, 'opaque+value/=', 'device-1')
        query = parse.parse_qs(parse.urlsplit(self.events[-1][1]).query)
        self.assertEqual(query, {'limit': ['17'], 'cursor': ['opaque+value/='], 'device_id': ['device-1']})
        self.client.list_items('devices', 1)
        self.assertEqual(parse.parse_qs(parse.urlsplit(self.events[-1][1]).query), {'limit': ['1']})

    def test_retry_origin_cannot_change(self):
        pending = cc.Pending(self.proposed())
        other = cc.CameraClient('http://127.0.0.1:1', TOKEN)
        with self.assertRaises(cc.ClientError):
            other.send(pending)
        self.assertEqual(self.events, [])


class RequestRulesTest(unittest.TestCase):
    def test_version_is_exact_int64_without_float_bool_exponents(self):
        self.assertEqual(cc.version('9223372036854775807'), 9223372036854775807)
        for value in ('0', '-1', '01', '1.0', '1e0', ' 1', '9223372036854775808', True, 1):
            with self.subTest(value=value), self.assertRaises(cc.ClientError):
                cc.version(value)

    def test_url_rejects_credentials_paths_queries_and_bad_ports(self):
        for value in ('rtsp://host', 'http://u:p@host', 'http://host/api', 'http://host?key=secret', 'http://host#fragment', 'http://host:0', 'http://host:99999', 'http://host\n', 'http://한글', 'http://host\\other', 'http://host%00'):
            with self.subTest(value=value), self.assertRaises(cc.ClientError):
                cc.origin(value)
        self.assertEqual(cc.origin('HTTP://LOCALHOST:80/'), 'http://localhost')
        self.assertEqual(cc.origin('http://[::1]:18081'), 'http://[::1]:18081')

    def test_create_fields_ids_names_and_profile_constraints(self):
        profile = dict(profile_id='main', codec='AUTO', width=1920, height=1080, fps=30.0)
        for transport, mode in [('RTSP', 'PULL'), ('WEBRTC', 'PUSH')]:
            body = cc.source_body('source-1', 'device-1', 'main', ' 영상 ', transport, 'FIXED', [profile])
            self.assertEqual(body['input_mode'], mode)
            self.assertEqual(body['display_name'], ' 영상 ')
            self.assertNotIn('device_kind', body)
        for profiles in ([], [profile] * 2, [{**profile, 'password': 'private'}], [{**profile, 'width': True}], [{**profile, 'width': 1.5}], [{**profile, 'fps': float('nan')}], [{**profile, 'fps': float('inf')}]):
            with self.assertRaises(cc.ClientError):
                cc.source_body('source-1', 'device-1', 'main', '영상', 'RTSP', 'FIXED', profiles)
        for value in ('validate', '../source', '한글', 'x/y'):
            with self.assertRaises(cc.ClientError):
                cc.identifier(value, True)
        self.assertEqual(cc.identifier('validate'), 'validate')
        with self.assertRaises(cc.ClientError):
            cc.device_body('device-1', ' \t', 'TEST')

    def test_same_request_keeps_key_and_uncertain_request_blocks_changes(self):
        op = cc.mutation('http://localhost', 'devices', 'create', 'device-1', cc.device_body('device-1', '카메라', 'TEST'))
        previous = cc.Pending(op)
        same = cc.mutation('http://localhost:80/', 'devices', 'create', 'device-1', cc.device_body('device-1', '카메라', 'TEST'))
        self.assertIs(cc.choose_pending(previous, same), previous)
        changed = cc.mutation('http://localhost', 'devices', 'create', 'device-1', cc.device_body('device-1', '수정', 'TEST'))
        with self.assertRaises(cc.ClientError):
            cc.choose_pending(previous, changed)
        previous.uncertain = False
        next_request = cc.choose_pending(previous, changed)
        self.assertNotEqual(next_request.mutation.key, op.key)

    def test_invalid_tokens_and_timeouts_never_echo_values(self):
        for token in ('private\r\nX-Header: injected', 'private 한글', ' private '):
            with self.assertRaises(cc.ClientError) as raised:
                cc.CameraClient('http://localhost', token)
            self.assertNotIn(token, str(raised.exception))
        for timeout in (0, 61, True, float('nan')):
            with self.assertRaises(cc.ClientError):
                cc.CameraClient('http://localhost', TOKEN, timeout)


if __name__ == '__main__':
    unittest.main()
