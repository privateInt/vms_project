"""Exercise real Streamlit widgets with a synthetic API; wire tests are separate."""
import json
import logging
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from streamlit import logger as streamlit_logger
import camera_client as cc


class FakeCamera:
    def __init__(self):
        self.events = []
        self.ready = True
        self.auth = True
        self.fail = False
        self.status = 201
        self.code = ''
        self.replayed = 'false'
        self.version = 9007199254740993
        self.origin = 'http://127.0.0.1:18081'

    def factory(self, base, token, timeout):
        # Keep production input validation even though network calls are faked.
        real_client = REAL_CLIENT(base, token, timeout)
        self.origin = real_client.origin
        return self

    def connect(self):
        self.events.append(('connect', self.origin))
        return (cc.Reply(200, dict(ready=self.ready, scope='camera_registry', business_runtime_ready=False)),
                cc.Reply(200 if self.auth else 401, dict(platform='camera', version=cc.API_VERSION)))

    def list_items(self, kind, limit, cursor=None, device_id=''):
        self.events.append(('list', kind, limit, cursor, device_id))
        return cc.Reply(200, dict(items=[], next_cursor='opaque+cursor/=' if cursor is None else None))

    def get_item(self, kind, item_id):
        self.events.append(('get', kind, item_id))
        field = 'device' if kind == 'devices' else 'source'
        return cc.Reply(200, {field: {field + '_id': item_id, 'display_name': '조회한 이름', 'version': self.version}})

    def send(self, pending):
        op = pending.mutation
        self.events.append(('send', op))
        pending.uncertain = True
        if self.fail:
            raise cc.ClientError('API 연결 또는 응답 확인에 실패했습니다.')
        reply = cc.Reply(self.status, dict(error=dict(code=self.code)) if self.code else
                         dict(device=dict(device_id='device-1', version=1), runtime_verified=False),
                         request_id='synthetic-request', replayed=self.replayed)
        pending.reply = reply
        pending.uncertain = self.status >= 500
        return reply


REAL_CLIENT = cc.CameraClient


class PageTest(unittest.TestCase):
    def setUp(self):
        streamlit_logger.set_log_level('error')
        for name in ('streamlit.runtime.scriptrunner_utils.script_run_context', 'streamlit.runtime.state.session_state_proxy'):
            logging.getLogger(name).setLevel(logging.ERROR)
        self.fake = FakeCamera()
        self.patch = patch.object(cc, 'CameraClient', self.fake.factory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name('camera.py')), default_timeout=10).run()
        self.clean()

    def clean(self):
        self.assertEqual(list(self.app.exception), [])

    def click(self, label):
        buttons = [button for button in self.app.button if button.label == label]
        self.assertEqual(len(buttons), 1, label)
        buttons[0].click().run()
        self.clean()

    def connect(self):
        self.app.text_input('api_token').input('synthetic-ui-test-token-00000001')
        self.click('연결 확인')
        self.assertTrue(self.app.session_state['ui_connected'])

    def lookup(self, title='장치', field='device'):
        self.app.text_input('lookup_' + field).input(field + '-1')
        self.click(title + ' 상세 조회')

    def sends(self):
        return [event[1] for event in self.fake.events if event[0] == 'send']

    def test_no_network_on_open_or_input_rerun_and_connect_checks_readiness(self):
        self.assertEqual(self.fake.events, [])
        self.app.text_input('new_device_name').input('입력만 변경').run()
        self.assertEqual(self.fake.events, [])
        self.fake.ready = False
        self.click('연결 확인')
        self.assertFalse(self.app.session_state['ui_connected'])
        self.assertTrue(next(b for b in self.app.button if b.label == '장치 등록').disabled)
        self.fake.ready = True
        self.fake.auth = False
        self.click('연결 확인')
        self.assertFalse(self.app.session_state['ui_connected'])
        self.fake.auth = True
        self.connect()
        self.assertEqual(self.sends(), [])

    def test_create_double_submit_reuses_key_and_clears_current_cache(self):
        self.connect()
        self.lookup()
        self.app.text_input('new_device_id').input('device-1')
        self.click('장치 등록')
        first = self.sends()[0]
        self.assertEqual(json.loads(first.body), dict(schema_version='v1', device_id='device-1', display_name='테스트 카메라', device_kind='TEST'))
        self.assertEqual(self.app.session_state['ui_data'], {})
        self.assertEqual(self.app.session_state['recent_device'], 'device-1')
        self.fake.replayed = 'true'
        self.click('장치 등록')
        self.assertEqual(self.sends()[1], first)
        self.assertEqual(self.app.session_state['ui_data'], {})
        self.assertEqual(self.app.session_state['ui_reply'].replayed, 'true')

    def test_uncertain_request_blocks_new_body_and_retry_uses_original(self):
        self.connect()
        self.fake.fail = True
        self.click('장치 등록')
        first = self.sends()[0]
        self.app.text_input('new_device_name').input('다른 이름')
        self.click('장치 등록')
        self.assertEqual(len(self.sends()), 1)
        self.assertTrue(self.app.session_state['ui_pending'].uncertain)
        self.fake.fail = False
        self.click('직전 요청 그대로 재시도')
        self.assertEqual(self.sends()[1], first)
        self.assertFalse(self.app.session_state['ui_pending'].uncertain)
        self.app.checkbox('finish_checked').check().run()
        self.click('직전 요청 종료')
        self.assertIsNone(self.app.session_state['ui_pending'])
        self.click('장치 등록')
        self.assertNotEqual(self.sends()[-1].key, first.key)

    def test_version_above_javascript_precision_and_stale_detail_invalidation(self):
        self.connect()
        self.lookup()
        self.assertEqual(self.app.text_input('edit_device_version').value, '9007199254740993')
        self.app.text_input('edit_device_name').input('수정 이름')
        self.click('이름 수정')
        op = self.sends()[0]
        self.assertEqual((op.method, op.path), ('PATCH', '/api/v1/devices/device-1'))
        self.assertEqual(json.loads(op.body)['expected_version'], 9007199254740993)
        self.assertTrue(next(b for b in self.app.button if b.label == '등록 삭제').disabled)

    def test_delete_requires_same_id_and_checkbox_and_reports_active_children(self):
        self.connect()
        self.lookup()
        self.app.text_input('delete_device_confirm').input('device-1')
        self.click('등록 삭제')
        self.assertEqual(self.sends(), [])
        self.app.checkbox('delete_device_accepted').check()
        self.app.text_input('delete_device_confirm').input('wrong-device')
        self.click('등록 삭제')
        self.assertEqual(self.sends(), [])
        self.app.text_input('delete_device_confirm').input('device-1')
        self.fake.status, self.fake.code = 409, 'DEVICE_HAS_ACTIVE_SOURCES'
        self.click('등록 삭제')
        op = self.sends()[0]
        self.assertEqual((op.method, op.path), ('DELETE', '/api/v1/devices/device-1'))
        self.assertEqual(json.loads(op.body), dict(schema_version='v1', expected_version=9007199254740993))
        self.assertIn('DEVICE_HAS_ACTIVE_SOURCES', ' '.join(error.value for error in self.app.error))
        self.assertFalse(self.app.session_state['ui_pending'].uncertain)

    def test_source_profile_form_and_transport_mapping(self):
        self.connect()
        self.app.radio('view').set_value('영상 소스').run()
        self.app.selectbox('profile_count').set_value(2).run()
        self.app.text_input('new_source_parent').input('device-1')
        self.app.selectbox('new_source_transport').set_value('WEBRTC')
        self.app.selectbox('codec_1').set_value('VP9')
        self.assertEqual(self.sends(), [])
        self.click('소스 등록')
        body = json.loads(self.sends()[0].body)
        self.assertEqual((body['transport'], body['input_mode']), ('WEBRTC', 'PUSH'))
        self.assertEqual(body['device_id'], 'device-1')
        self.assertEqual([p['profile_id'] for p in body['profiles']], ['main', 'profile-2'])
        self.assertEqual(body['profiles'][1]['codec'], 'VP9')
        self.assertEqual(self.app.session_state['recent_source'], body['source_id'])

    def test_source_pagination_keeps_original_filter_and_limit(self):
        self.connect()
        self.app.radio('view').set_value('영상 소스').run()
        self.app.number_input('limit_sources').set_value(17)
        self.app.text_input('filter_sources').input('device-1')
        self.click('소스 목록 조회')
        self.app.number_input('limit_sources').set_value(99)
        self.app.text_input('filter_sources').input('device-2')
        self.click('다음 페이지')
        reads = [event for event in self.fake.events if event[0] == 'list']
        self.assertEqual(reads, [('list', 'sources', 17, None, 'device-1'), ('list', 'sources', 17, 'opaque+cursor/=', 'device-1')])

    def test_origin_and_token_change_clear_loaded_state_and_fence_retry(self):
        self.connect()
        self.lookup()
        self.fake.fail = True
        self.click('장치 등록')
        first = self.sends()[0]
        self.app.text_input('api_token').input('synthetic-ui-test-other-token').run()
        self.assertFalse(self.app.session_state['ui_connected'])
        self.assertEqual(self.app.session_state['ui_data'], {})
        self.assertTrue(self.app.button('retry').disabled)
        self.app.text_input('api_address').input('http://127.0.0.1:18082')
        self.click('연결 확인')
        self.assertTrue(self.app.session_state['ui_connected'])
        self.assertTrue(self.app.button('retry').disabled)
        self.assertEqual(self.app.session_state['ui_pending'].mutation, first)
        self.assertEqual(len(self.sends()), 1)


if __name__ == '__main__':
    unittest.main()
