"""Planned metadata shapes only; no DNS, HTTP, DB, credentials or camera IO."""
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'connection-config.schema.json').read_text())
EXAMPLES = json.loads((ROOT / 'connection-config.examples.json').read_text())
CURRENT = json.loads((ROOT.parent / 'openapi.json').read_text())
MAX_VERSION = 9223372036854775807
FORMATS = FormatChecker()


@FORMATS.checks('date-time', raises=ValueError)
def utc_calendar(value):
    if not isinstance(value, str):
        return True
    match = re.fullmatch(
        r'([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?Z', value)
    if match is None:
        return False
    datetime(*(int(n) for n in match.groups()))
    return True


def validator(name):
    return Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': SCHEMA['$defs']},
                               format_checker=FORMATS)


class ConnectionConfigContractTest(unittest.TestCase):
    def setUp(self):
        self.create = validator('ConnectionConfigCreate')
        self.body = copy.deepcopy(EXAMPLES['create_requests'][0]['body'])
        self.success = copy.deepcopy(EXAMPLES['first_success']['body'])

    def reject(self, name, values):
        check = validator(name)
        for value in values:
            with self.subTest(definition=name, value=value):
                self.assertFalse(check.is_valid(value))

    def test_schema_and_all_local_references(self):
        Draft202012Validator.check_schema(SCHEMA)
        def walk(node):
            if isinstance(node, dict):
                if '$ref' in node:
                    self.assertTrue(node['$ref'].startswith('#/$defs/'))
                    self.assertIn(node['$ref'].split('/')[-1], SCHEMA['$defs'])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(SCHEMA)
        self.assertEqual(SCHEMA['x-vms-contract-status'], 'planned')

    def test_create_examples_and_existing_source_profile_identifier_rules(self):
        root = Draft202012Validator(SCHEMA, format_checker=FORMATS)
        source_id = CURRENT['components']['schemas']['SourceCreate']['properties']['source_id']
        for example in EXAMPLES['create_requests']:
            root.validate(example['body'])
            Draft202012Validator(source_id).validate(example['body']['source_id'])
            self.assertEqual(example['method'], 'POST')
            self.assertEqual(example['path'], '/api/v1/connection-configs')
            self.assertTrue(1 <= len(example['idempotency_key']) <= 128)
            self.assertTrue(all(33 <= ord(c) <= 126 for c in example['idempotency_key']))

    def test_create_required_fields_and_wrong_envelope(self):
        for field in SCHEMA['$defs']['ConnectionConfigCreate']['required']:
            value = dict(self.body)
            del value[field]
            self.assertFalse(self.create.is_valid(value))
            self.assertFalse(self.create.is_valid({**self.body, field: None}))
        self.reject('ConnectionConfigCreate', [None, [], '', True, 1,
                    {**self.body, 'schema_version': 'v2'}])

    def test_identity_boundaries_and_source_validate_reservation(self):
        self.reject('ID', ['', '_id', 'a' * 65, 'a/b', '한글', 'a\n', 'a ', None])
        for value in ('a', 'a' * 64, 'cfg_1.a-b', 'validate'):
            validator('ID').validate(value)
        self.reject('SourceID', ['validate'])
        validator('SourceID').validate('Validate')

    def test_credentials_require_pinned_local_reference(self):
        auth = self.body['auth']
        for key in ('credential_id', 'credential_version', 'mode'):
            value = dict(auth)
            del value[key]
            self.reject('Authentication', [value])
        self.reject('Authentication', [{**auth, 'credential_version': v} for v in
                    ('latest', '1', None, True, 0, -1, 1.5, MAX_VERSION + 1)])
        self.reject('Authentication', [{**auth, 'credential_id': v} for v in
                    ('vault://camera/password', '/run/secrets/camera', '', 'a\n')])
        validator('Authentication').validate({**auth, 'credential_version': MAX_VERSION})

    def test_authentication_none_is_explicit_and_excludes_reference(self):
        validator('Authentication').validate({'mode': 'NONE'})
        self.reject('Authentication', [{}, None, 'NONE', {'mode': 'AUTO'},
                    {'mode': 'NONE', 'credential_id': 'c1'},
                    {'mode': 'NONE', 'credential_version': 1},
                    {'mode': 'CREDENTIAL_REF'}, {'mode': 'NONE', 'password': ''}])

    def test_private_secrets_and_authentication_bypass_are_not_input_fields(self):
        for auth in ({'mode': 'NONE'}, self.body['auth']):
            for field in ('username', 'password', 'token', 'secret', 'secret_value',
                          'provider_uri', 'secret_path', 'headers', 'authorization',
                          'latest', 'skip_auth', 'verify_tls'):
                self.reject('Authentication', [{**auth, field: 'fixture-only'}])

    def test_host_shape_accepts_ipv4_ipv6_and_ascii_dns_without_resolving(self):
        for value in ('192.168.0.10', '203.0.113.10', '2001:db8::10',
                      '::ffff:192.0.2.10', 'camera.example.invalid', 'CAMERA.example.invalid'):
            validator('Host').validate(value)
        # Syntactic validity does not authorize a future network connection.
        validator('Host').validate('127.0.0.1')

    def test_host_rejects_authority_urls_zone_escapes_and_rare_ipv4(self):
        self.reject('Host', ['', 'rtsp://camera.example.invalid', 'user@192.168.0.10',
                    '192.168.0.10:554', '[2001:db8::10]', 'fe80::1%eth0', 'fe80::1%25eth0',
                    'camera.example.invalid.', 'camera', 'localhost', '2130706433',
                    '0x7f000001', '127.1', '0177.0.0.1', '256.1.1.1', '1.2.3.4\n',
                    'camera.example.invalid\n', 'cam_1.example.invalid', '카메라.example.invalid',
                    'camera..example.invalid', 'a' * 64 + '.example.invalid', 'a' * 254])

    def test_path_subset_and_delimiter_or_normalization_bypass(self):
        for value in ('/', '/stream1', '/Streaming/Channels/101', '/cam_1/video.main', '/~main'):
            validator('Path').validate(value)
        self.reject('Path', ['', 'stream1', '//other/stream', '/stream//main',
                    '/./stream', '/../stream', '/stream/..', '/stream/.',
                    '/stream?token=fixture', '/stream#fragment', '/user:pass@camera',
                    '/%2e%2e/stream', '/%3ftoken', '/stream%00', '/stream\\main',
                    '/stream\n', '/stream main', '/한글', '/' + 'a' * 2048])

    def test_port_integer_bounds_and_tcp_only(self):
        endpoint = self.body['endpoint']
        self.reject('Endpoint', [{**endpoint, 'port': v} for v in
                    (0, -1, 65536, '554', True, 1.5, None)])
        for value in (1, 554, 65535):
            validator('Endpoint').validate({**endpoint, 'port': value})
        self.reject('Endpoint', [{**endpoint, 'rtp_transport': v} for v in
                    ('UDP', 'AUTO', None, True)])

    def test_adapter_scope_rejects_onvif_xr_and_runtime_choices(self):
        self.reject('ConnectionConfigCreate', [{**self.body, 'adapter': v} for v in
                    ('ONVIF', 'ONVIF_MEDIA', 'WEBRTC_PUSH', 'RTSPS_PULL', '', None)])
        for field in ('device_id', 'channel_key', 'transport', 'input_mode', 'profiles',
                      'publisher_id', 'source_session_id', 'network_policy', 'force',
                      'skip_usage_check', 'connected', 'runtime_verified', 'version'):
            self.reject('ConnectionConfigCreate', [{**self.body, field: 'fixture-only'}])

    def test_endpoint_has_no_url_secrets_tls_proxy_or_query_inputs(self):
        endpoint = self.body['endpoint']
        for field in ('url', 'rtsp_url', 'scheme', 'username', 'password', 'token',
                      'query', 'fragment', 'headers', 'proxy', 'ca_file', 'insecure',
                      'skip_network_check', 'onvif_service', 'credential_ref'):
            self.reject('Endpoint', [{**endpoint, field: 'fixture-only'}])

    def test_replacement_is_full_and_binding_cannot_change(self):
        value = EXAMPLES['replace_request']['body']
        check = validator('ConnectionConfigReplace')
        check.validate(value)
        self.assertEqual(EXAMPLES['replace_request']['method'], 'PUT')
        for field in ('endpoint', 'auth', 'expected_version', 'schema_version'):
            changed = dict(value)
            del changed[field]
            self.assertFalse(check.is_valid(changed))
        for field in ('connection_config_id', 'source_id', 'profile_id', 'adapter', 'force'):
            self.reject('ConnectionConfigReplace', [{**value, field: 'fixture-only'}])
        check.validate({**value, 'auth': {'mode': 'NONE'}})

    def test_version_bounds_are_exact_in_parsed_values(self):
        self.reject('Version', [0, -1, MAX_VERSION + 1, True, '1', 1.5, None])
        for value in (1, MAX_VERSION):
            validator('Version').validate(value)

    def test_create_and_replay_return_only_same_safe_metadata(self):
        first, replay = EXAMPLES['first_success'], EXAMPLES['same_key_replay']
        for example in (first, replay):
            validator('ConnectionConfigResponse').validate(example['body'])
            self.assertEqual(example['http_status'], 201)
            self.assertEqual(example['headers']['X-Request-ID'], example['body']['request_id'])
            self.assertEqual(example['headers']['Cache-Control'], 'no-store')
            self.assertEqual(example['headers']['Location'], '/api/v1/connection-configs/' +
                             example['body']['connection_config']['connection_config_id'])
            metadata = example['body']['connection_config']
            self.assertNotIn('endpoint', metadata)
            self.assertEqual(metadata['auth'], self.body['auth'])
            self.assertEqual(metadata['source_id'], self.body['source_id'])
            self.assertEqual(metadata['profile_id'], self.body['profile_id'])
        self.assertEqual(first['body']['connection_config'], replay['body']['connection_config'])
        self.assertNotEqual(first['body']['request_id'], replay['body']['request_id'])
        self.assertEqual(first['headers']['Idempotency-Replayed'], 'false')
        self.assertEqual(replay['headers']['Idempotency-Replayed'], 'true')

    def test_responses_do_not_allow_endpoint_or_secret_injection(self):
        for location in ((), ('connection_config',), ('connection_config', 'auth')):
            for field in ('endpoint', 'host', 'path', 'rtsp_url', 'username', 'password',
                          'token', 'secret_value', 'headers', 'resolved_credential'):
                value = copy.deepcopy(self.success)
                node = value
                for part in location:
                    node = node[part]
                node[field] = 'fixture-only'
                self.reject('ConnectionConfigResponse', [value])

    def test_configured_response_is_not_runtime_success(self):
        self.reject('ConnectionConfigResponse', [
            {**self.success, 'runtime_verified': True},
            {**self.success, 'configuration_state': 'CONNECTED'},
            {**self.success, 'configuration_state': 'DELETED'},
            {**self.success, 'request_id': ''}])
        for field in SCHEMA['$defs']['ConnectionConfigMetadata']['required']:
            value = copy.deepcopy(self.success)
            del value['connection_config'][field]
            self.reject('ConnectionConfigResponse', [value])

    def test_timestamp_calendar_and_utc_boundaries(self):
        for value in ('2026-10-02T02:30:00Z', '2026-10-02T02:30:00.123456789Z'):
            validator('UTC').validate(value)
        self.reject('UTC', ['2026-02-30T02:30:00Z', '2026-10-02',
                    '2026-10-02T02:30:00', '2026-10-02T02:30:00+09:00',
                    '2026-10-02T02:30:00.1234567890Z', '2026-10-02T02:30:00Z\n'])

    def test_delete_request_and_minimal_receipt(self):
        request, response = EXAMPLES['delete_request'], EXAMPLES['delete_success']
        validator('ConnectionConfigDelete').validate(request['body'])
        validator('ConnectionConfigDeleteResponse').validate(response['body'])
        self.assertEqual(request['method'], 'DELETE')
        self.assertEqual(response['http_status'], 200)
        self.assertEqual(response['headers']['X-Request-ID'], response['body']['request_id'])
        self.assertEqual(response['headers']['Cache-Control'], 'no-store')
        self.assertNotIn('Location', response['headers'])
        self.assertEqual(response['body']['deletion']['version'], request['body']['expected_version'] + 1)
        for field in ('force', 'purge', 'delete_credentials', 'delete_source', 'skip_usage_check'):
            self.reject('ConnectionConfigDelete', [{**request['body'], field: True}])
        for field in ('auth', 'endpoint', 'source_id', 'device_id', 'password'):
            value = copy.deepcopy(response['body'])
            value['deletion'][field] = 'fixture-only'
            self.reject('ConnectionConfigDeleteResponse', [value])

    def test_safe_response_envelope_is_required(self):
        for field in SCHEMA['$defs']['ConnectionConfigResponse']['required']:
            value = copy.deepcopy(self.success)
            del value[field]
            self.reject('ConnectionConfigResponse', [value])
            self.reject('ConnectionConfigResponse', [{**self.success, field: None}])
        for value in (None, [], 'CONFIGURED', True):
            self.reject('ConnectionConfigResponse', [value])


if __name__ == '__main__':
    unittest.main(verbosity=2)
