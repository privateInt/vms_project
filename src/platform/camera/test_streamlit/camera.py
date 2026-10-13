"""Standalone Camera registry test page. All effects use the published HTTP API."""
import hashlib
from pathlib import Path
import sys
import uuid

import streamlit as st

# Both streamlit run and AppTest may start from a different working directory.
script_directory = str(Path(__file__).resolve().parent)
if script_directory not in sys.path:
    sys.path.insert(0, script_directory)
import camera_client as cc


def initial_state():
    defaults = {'ui_data': {}, 'ui_connected': False, 'ui_binding': None, 'ui_pending': None,
                'ui_reply': None, 'ui_error': '', 'recent_device': '', 'recent_source': ''}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_loaded():
    st.session_state['ui_data'] = {}
    for key in list(st.session_state):
        if key.startswith(('edit_', 'delete_')):
            del st.session_state[key]


def remember_reply(reply):
    st.session_state['ui_reply'] = reply
    st.session_state['ui_error'] = ''


def read_call(call):
    try:
        reply = call()
        remember_reply(reply)
        return reply
    except cc.ClientError as exc:
        st.session_state['ui_error'] = str(exc)
        return None


def change(client, kind, action, item_id, body):
    try:
        proposed = cc.mutation(client.origin, kind, action, item_id, body)
        pending = cc.choose_pending(st.session_state['ui_pending'], proposed)
        st.session_state['ui_pending'] = pending
        st.session_state['finish_checked'] = False
        reply = client.send(pending)
        remember_reply(reply)
        if reply.ok:
            # Replayed historical snapshots never become current-state cache.
            st.session_state['ui_data'] = {}
            id_field = 'device_id' if kind == 'devices' else 'source_id'
            st.session_state['recent_device' if kind == 'devices' else 'recent_source'] = body.get(id_field, item_id)
    except cc.ClientError as exc:
        st.session_state['ui_error'] = str(exc)


def connection():
    with st.sidebar.form('connection'):
        base = st.text_input('Camera API 주소', value='http://127.0.0.1:18081', key='api_address')
        token = st.text_input('VMS_API_TOKEN', type='password', key='api_token')
        timeout = st.number_input('응답 제한 시간(초)', min_value=1, max_value=60, value=10, key='http_timeout')
        clicked = st.form_submit_button('연결 확인')
    try:
        client = cc.CameraClient(base, token, int(timeout))
    except cc.ClientError as exc:
        st.sidebar.error(str(exc))
        st.session_state['ui_connected'] = False
        reset_loaded()
        return None
    binding = (client.origin, hashlib.sha256(token.encode('ascii')).hexdigest())
    if st.session_state['ui_binding'] != binding:
        reset_loaded()
        st.session_state['ui_connected'] = False
        st.session_state['ui_reply'] = None
        st.session_state['ui_error'] = ''
        st.session_state['ui_binding'] = binding
    if clicked:
        st.session_state['ui_connected'] = False
        reset_loaded()
        try:
            ready, platform = client.connect()
            remember_reply(platform if not platform.ok else ready)
            st.session_state['ui_connected'] = bool(ready.ok and ready.data.get('ready') is True and
                ready.data.get('scope') == 'camera_registry' and platform.ok and
                platform.data.get('platform') == 'camera' and platform.data.get('version') == cc.API_VERSION)
        except cc.ClientError as exc:
            st.session_state['ui_error'] = str(exc)
    if st.session_state['ui_connected']:
        st.sidebar.success('등록 API 연결 확인 완료')
    else:
        st.sidebar.info('API 주소와 토큰을 입력한 뒤 연결을 확인하세요. 등록 DB 준비 상태까지 검사합니다.')
    return client


def listing(client, kind, title):
    enabled = bool(client and st.session_state['ui_connected'])
    with st.form('list_' + kind):
        limit = st.number_input('페이지당 개수', min_value=1, max_value=200, value=50, key='limit_' + kind)
        parent = st.text_input('부모 장치 ID 필터(비우면 전체)', key='filter_sources') if kind == 'sources' else ''
        clicked = st.form_submit_button(title + ' 목록 조회', disabled=not enabled)
    key = 'list_' + kind
    if clicked:
        st.session_state['ui_data'].pop(key, None)
        reply = read_call(lambda: client.list_items(kind, int(limit), device_id=parent))
        if reply and reply.ok:
            st.session_state['ui_data'][key] = {'reply': reply, 'limit': int(limit), 'parent': parent, 'page': 1}
    page = st.session_state['ui_data'].get(key)
    if page:
        reply = page['reply']
        st.caption('조회 페이지: ' + str(page['page']) + ' · 부모 필터: ' + (page['parent'] or '전체'))
        items = reply.data.get('items', [])
        if items:
            st.dataframe([{k: v for k, v in item.items() if k != 'profiles'} for item in items], hide_index=True, use_container_width=True)
        else:
            st.info('등록된 항목이 없습니다.')
        cursor = reply.data.get('next_cursor')
        if st.button('다음 페이지', key='next_' + kind, disabled=not enabled or not cursor):
            result = read_call(lambda: client.list_items(kind, page['limit'], cursor, page['parent']))
            if result and result.ok:
                page['reply'] = result
                page['page'] += 1
                st.rerun()


def lookup_and_changes(client, kind, title):
    enabled = bool(client and st.session_state['ui_connected'])
    field = 'device' if kind == 'devices' else 'source'
    recent = 'recent_' + field
    lookup_key = 'lookup_' + field
    if lookup_key not in st.session_state:
        st.session_state[lookup_key] = st.session_state[recent]
    if st.button('최근 ' + title + ' ID 사용', key='reuse_' + field, disabled=not st.session_state[recent]):
        st.session_state[lookup_key] = st.session_state[recent]
    with st.form('get_' + field):
        item_id = st.text_input(title + ' ID', key=lookup_key)
        clicked = st.form_submit_button(title + ' 상세 조회', disabled=not enabled)
    detail_key = 'detail_' + field
    if clicked:
        st.session_state['ui_data'].pop(detail_key, None)
        for key in list(st.session_state):
            if key.startswith(('edit_' + field, 'delete_' + field)):
                del st.session_state[key]
        reply = read_call(lambda: client.get_item(kind, item_id))
        if reply and reply.ok and isinstance(reply.data.get(field), dict):
            st.session_state['ui_data'][detail_key] = reply.data[field]
            st.session_state[recent] = item_id
    detail = st.session_state['ui_data'].get(detail_key)
    if detail:
        st.json(detail, expanded=False)
        st.caption('현재 조회 버전: ' + str(detail['version']) + ' · 등록 정보 조회 결과')
    st.subheader(title + ' 이름 수정')
    with st.form('update_' + field):
        name = st.text_input('새 표시 이름', value=detail.get('display_name', '') if detail else '', key='edit_' + field + '_name')
        expected = st.text_input('조회 버전', value=str(detail['version']) if detail else '1', key='edit_' + field + '_version')
        update = st.form_submit_button('이름 수정', disabled=not enabled or detail is None)
    if update:
        try:
            change(client, kind, 'update', detail[field + '_id'], cc.change_body(expected, name))
        except cc.ClientError as exc:
            st.session_state['ui_error'] = str(exc)
    # An update can invalidate the detail above; do not reuse its old version.
    detail = st.session_state['ui_data'].get(detail_key)
    st.subheader(title + ' 등록 삭제')
    st.caption('소스를 먼저 삭제한 뒤 부모 장치를 삭제합니다. 등록 삭제 영수증과 현재 상태는 별도로 확인합니다.')
    with st.form('delete_' + field):
        confirm_id = st.text_input('삭제할 ID를 한 번 더 입력', key='delete_' + field + '_confirm')
        accepted = st.checkbox('이 항목의 등록을 삭제합니다.', key='delete_' + field + '_accepted')
        delete = st.form_submit_button('등록 삭제', disabled=not enabled or detail is None)
    if delete:
        if not accepted or confirm_id != detail[field + '_id']:
            st.session_state['ui_error'] = '삭제 확인과 조회한 대상의 정확한 ID가 필요합니다.'
        else:
            change(client, kind, 'delete', confirm_id, cc.change_body(str(detail['version'])))


def create_device(client):
    if 'new_device_id' not in st.session_state:
        st.session_state['new_device_id'] = 'ui-device-' + uuid.uuid4().hex[:12]
    with st.form('create_device'):
        item_id = st.text_input('새 장치 ID', key='new_device_id')
        name = st.text_input('장치 표시 이름', value='테스트 카메라', key='new_device_name')
        kind = st.selectbox('장치 종류', ['TEST', 'CCTV', 'SMART_GLASSES'], key='new_device_kind')
        clicked = st.form_submit_button('장치 등록', disabled=not client or not st.session_state['ui_connected'])
    if clicked:
        try:
            change(client, 'devices', 'create', item_id, cc.device_body(item_id, name, kind))
        except cc.ClientError as exc:
            st.session_state['ui_error'] = str(exc)


def create_source(client):
    if 'new_source_id' not in st.session_state:
        st.session_state['new_source_id'] = 'ui-source-' + uuid.uuid4().hex[:12]
    count = st.selectbox('스트림 프로필 개수', list(range(1, 9)), key='profile_count')
    with st.form('create_source'):
        item_id = st.text_input('새 소스 ID', key='new_source_id')
        parent = st.text_input('부모 장치 ID', value=st.session_state['recent_device'], key='new_source_parent')
        channel = st.text_input('채널 ID', value='main', key='new_source_channel')
        name = st.text_input('소스 표시 이름', value='테스트 영상 소스', key='new_source_name')
        transport = st.selectbox('전송 방식', ['RTSP', 'WEBRTC'], key='new_source_transport')
        motion = st.selectbox('촬영 위치', ['FIXED', 'MOVING', 'UNKNOWN'], key='new_source_motion')
        st.caption('RTSP는 PULL, WEBRTC는 PUSH로 등록합니다.')
        profiles = []
        for index in range(count):
            suffix = str(index)
            st.markdown('**프로필 ' + str(index + 1) + '**')
            pid = st.text_input('프로필 ID', value='main' if index == 0 else 'profile-' + str(index + 1), key='profile_id_' + suffix)
            codec = st.selectbox('코덱', ['AUTO', 'H264', 'H265', 'VP8', 'VP9', 'AV1'], key='codec_' + suffix)
            width = st.number_input('너비', min_value=1, max_value=16384, value=1920, key='width_' + suffix)
            height = st.number_input('높이', min_value=1, max_value=16384, value=1080, key='height_' + suffix)
            fps = st.number_input('FPS', min_value=0.1, max_value=240.0, value=30.0, key='fps_' + suffix)
            profiles.append(dict(profile_id=pid, codec=codec, width=int(width), height=int(height), fps=float(fps)))
        clicked = st.form_submit_button('소스 등록', disabled=not client or not st.session_state['ui_connected'])
    if clicked:
        try:
            body = cc.source_body(item_id, parent, channel, name, transport, motion, profiles)
            change(client, 'sources', 'create', item_id, body)
        except cc.ClientError as exc:
            st.session_state['ui_error'] = str(exc)


def last_request(client):
    pending = st.session_state['ui_pending']
    if pending:
        st.subheader('직전 변경 요청')
        op = pending.mutation
        st.caption(op.method + ' ' + op.path + ' · 요청 키: ' + op.key)
        if pending.uncertain:
            st.warning('변경 결과가 불명확합니다. 재시도는 직전 요청의 같은 키·본문으로 전송합니다.')
        same_origin = bool(client and op.origin == client.origin)
        if st.button('직전 요청 그대로 재시도', key='retry', disabled=not same_origin or not st.session_state['ui_connected']):
            st.session_state['finish_checked'] = False
            try:
                reply = client.send(pending)
                remember_reply(reply)
                if reply.ok:
                    st.session_state['ui_data'] = {}
            except cc.ClientError as exc:
                st.session_state['ui_error'] = str(exc)
        with st.expander('요청 영수증 확인'):
            st.json({'api_origin': op.origin, 'method': op.method, 'path': op.path, 'idempotency_key': op.key, 'body': op.body.decode('utf-8')})
        checked = st.checkbox('필요한 현재 상태를 조회로 확인했습니다.', key='finish_checked')
        def finish():
            st.session_state['ui_pending'] = None
            st.session_state['finish_checked'] = False
        st.button('직전 요청 종료', key='finish_request', disabled=not checked, on_click=finish)
    if st.session_state['ui_error']:
        st.error(st.session_state['ui_error'])
    reply = st.session_state['ui_reply']
    if reply:
        label = 'HTTP ' + str(reply.status)
        if reply.code:
            label += ' · ' + reply.code
        if reply.ok:
            st.success(label)
        else:
            st.error(label)
            guidance = {
                'DEVICE_HAS_ACTIVE_SOURCES': '미삭제 소스를 먼저 조회·삭제한 뒤 부모 장치 삭제를 다시 제출하세요.',
                'DEVICE_VERSION_CONFLICT': '장치 상세를 다시 조회하고 최신 버전으로 수정·삭제하세요.',
                'SOURCE_VERSION_CONFLICT': '소스 상세를 다시 조회하고 최신 버전으로 수정·삭제하세요.',
                'SOURCE_IN_USE': '소스 사용 상태를 확인하세요. 화면에서 강제 삭제하지 않습니다.',
                'UNAUTHORIZED': '토큰을 확인하고 연결 확인을 다시 실행하세요.',
            }.get(reply.code)
            if guidance:
                st.info(guidance)
        st.caption('request_id: ' + (reply.request_id or reply.data.get('request_id', '')) + ' · 최초 요청 재생: ' + (reply.replayed or '해당 없음'))
        with st.expander('실제 API 응답'):
            st.json(reply.data)


def main():
    st.set_page_config(page_title='Camera 테스트', layout='wide')
    initial_state()
    st.title('Camera 플랫폼 테스트')
    st.info('현재 범위: 장치·영상 소스 등록 정보. 영상 연결·재생·자격증명 API는 후속 단계입니다.')
    client = connection()
    section = st.sidebar.radio('테스트 대상', ['장치', '영상 소스'], key='view')
    kind, title = ('devices', '장치') if section == '장치' else ('sources', '소스')
    st.header(title + ' 조회')
    listing(client, kind, title)
    lookup_and_changes(client, kind, title)
    st.header(title + ' 신규 등록')
    if section == '장치':
        create_device(client)
    else:
        create_source(client)
    last_request(client)


if __name__ == '__main__':
    main()
