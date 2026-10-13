"""Camera-owned HTTP test client. No DB, environment, credentials or file IO."""
from dataclasses import dataclass, field
import hashlib
from http.client import HTTPException
import json
import math
import re
import socket
from urllib import error, parse, request
import uuid

API_VERSION = '0.7.0-device-delete'
# Exact reviewed published OpenAPI bytes; updated when a later API is adopted.
SPEC_SHA256 = 'fc0f84bd428e4915e7e308df492921a3ff266da83c77b0042b49c1061c4a1035'
MAX_RESPONSE = 4 * 1024 * 1024
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')


class ClientError(Exception):
    """Constant local diagnostic; never interpolate URLs, tokens or raw IO errors."""


def identifier(value, source=False):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or (source and value == 'validate'):
        raise ClientError('식별자는 영문·숫자로 시작하는 1~64자의 영문·숫자·점·밑줄·하이픈이어야 합니다.')
    return value


def display_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or '\x00' in value:
        raise ClientError('이름은 공백만으로 구성할 수 없으며 NUL 없이 128자 이하여야 합니다.')
    return value


def version(value):
    # Text input avoids JavaScript number precision loss above 2**53.
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value):
        raise ClientError('버전은 소수·지수 없이 양의 정수로 입력하세요.')
    result = int(value)
    if result > 9223372036854775807:
        raise ClientError('버전이 int64 범위를 벗어났습니다.')
    return result


def device_body(device_id, name, kind):
    if kind not in ('CCTV', 'SMART_GLASSES', 'TEST'):
        raise ClientError('지원하지 않는 장치 종류입니다.')
    return dict(schema_version='v1', device_id=identifier(device_id), display_name=display_name(name), device_kind=kind)


def source_body(source_id, device_id, channel, name, transport, motion, profiles):
    if transport not in ('RTSP', 'WEBRTC') or motion not in ('FIXED', 'MOVING', 'UNKNOWN'):
        raise ClientError('지원하지 않는 영상 소스 설정입니다.')
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 8:
        raise ClientError('프로필은 1~8개가 필요합니다.')
    checked, seen = [], set()
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != {'profile_id', 'codec', 'width', 'height', 'fps'}:
            raise ClientError('프로필 필드가 올바르지 않습니다.')
        pid = identifier(profile['profile_id'])
        if pid in seen or profile['codec'] not in ('AUTO', 'H264', 'H265', 'VP8', 'VP9', 'AV1'):
            raise ClientError('프로필 ID 중복 또는 지원하지 않는 코덱입니다.')
        seen.add(pid)
        for size in ('width', 'height'):
            if type(profile[size]) is not int or not 1 <= profile[size] <= 16384:
                raise ClientError('너비·높이는 1~16384의 정수여야 합니다.')
        fps = profile['fps']
        if type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 240:
            raise ClientError('FPS는 0 초과 240 이하의 유한한 수여야 합니다.')
        checked.append(dict(profile))
    return dict(schema_version='v1', source_id=identifier(source_id, True), device_id=identifier(device_id),
                channel_key=identifier(channel), display_name=display_name(name), transport=transport,
                input_mode='PULL' if transport == 'RTSP' else 'PUSH', motion_mode=motion, profiles=checked)


def change_body(expected_version, name=None):
    result = dict(schema_version='v1', expected_version=version(expected_version))
    if name is not None:
        result['display_name'] = display_name(name)
    return result


def origin(value):
    try:
        url = parse.urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username is not None or url.password is not None or url.path not in ('', '/') or url.query or url.fragment or any(c.isspace() for c in value):
            raise ValueError()
        port = url.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        host = url.hostname.lower()
        if any(ord(c) < 33 or ord(c) > 126 or c in '\\%' for c in host):
            raise ValueError()
        if ':' in host:
            host = '[' + host + ']'
        default = 80 if url.scheme == 'http' else 443
        return url.scheme + '://' + host + (':' + str(port) if port is not None and port != default else '')
    except (ValueError, TypeError, AttributeError):
        raise ClientError('API 주소는 사용자정보·경로·쿼리 없이 http(s)://호스트:포트로 입력하세요.') from None


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Reply:
    status: int
    data: dict
    request_id: str = ''
    replayed: str = ''

    @property
    def ok(self):
        return 200 <= self.status < 300

    @property
    def code(self):
        problem = self.data.get('error')
        return problem.get('code', '') if isinstance(problem, dict) else ''


@dataclass(frozen=True)
class Mutation:
    origin: str
    method: str
    path: str
    body: bytes
    key: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Pending:
    mutation: Mutation
    uncertain: bool = True
    reply: Reply | None = None


def mutation(base, kind, action, item_id, body):
    if kind not in ('devices', 'sources') or action not in ('create', 'update', 'delete'):
        raise ClientError('지원하지 않는 변경 작업입니다.')
    method = {'create': 'POST', 'update': 'PATCH', 'delete': 'DELETE'}[action]
    path = '/api/v1/' + kind
    if action != 'create':
        path += '/' + identifier(item_id, kind == 'sources')
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return Mutation(origin(base), method, path, encoded)


def choose_pending(previous, proposed):
    if previous is not None:
        old = previous.mutation
        if (old.origin, old.method, old.path, old.body) == (proposed.origin, proposed.method, proposed.path, proposed.body):
            return previous
        if previous.uncertain:
            raise ClientError('직전 변경 결과가 불명확합니다. 같은 요청을 재시도하거나 현재 상태를 확인한 뒤 직전 요청을 종료하세요.')
    return Pending(proposed)


class CameraClient:
    def __init__(self, base, token='', timeout=10, opener=None):
        self.origin = origin(base)
        if not isinstance(token, str) or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ClientError('토큰은 공백·개행 없는 ASCII 문자열이어야 합니다.')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 60:
            raise ClientError('HTTP 제한 시간은 1~60초여야 합니다.')
        self._token, self._timeout = token, timeout
        # Do not send bearer credentials to environment-selected HTTP proxies.
        self._opener = opener or request.build_opener(request.ProxyHandler({}), NoRedirect())

    def __repr__(self):
        return '<CameraClient>'

    def _http(self, method, path, body=None, key=None, authenticated=True, raw=False):
        if authenticated and not self._token:
            raise ClientError('VMS_API_TOKEN을 입력하세요.')
        headers = {'Accept': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self._token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if key is not None:
            headers['Idempotency-Key'] = key
        req = request.Request(self.origin + path, data=body, headers=headers, method=method)
        try:
            try:
                response = self._opener.open(req, timeout=self._timeout)
            except error.HTTPError as exc:
                response = exc
            with response:
                content = response.read(MAX_RESPONSE + 1)
                status = response.code
                if len(content) > MAX_RESPONSE:
                    raise ClientError('API 응답이 허용 크기를 넘었습니다.')
                if raw:
                    return status, content
                if response.headers.get_content_type() != 'application/json':
                    raise ClientError('API가 JSON 응답을 반환하지 않았습니다.')
                try:
                    value = json.loads(content.decode('utf-8'))
                except (ValueError, UnicodeError):
                    raise ClientError('API JSON 응답을 해석할 수 없습니다.') from None
                if not isinstance(value, dict):
                    raise ClientError('API 응답 형식이 올바르지 않습니다.')
                return Reply(status, value, response.headers.get('X-Request-ID', ''), response.headers.get('Idempotency-Replayed', ''))
        except (error.URLError, OSError, HTTPException, socket.timeout, TimeoutError):
            raise ClientError('API 연결 또는 응답 확인에 실패했습니다. 변경 요청은 같은 키·본문으로 재시도하세요.') from None

    def check_spec(self):
        status, body = self._http('GET', '/openapi.json', authenticated=False, raw=True)
        if status != 200 or hashlib.sha256(body).hexdigest() != SPEC_SHA256:
            raise ClientError('검토된 camera 0.7.0 실행 명세와 다릅니다. API 주소·버전을 확인하세요.')

    def connect(self):
        self.check_spec()
        return self._http('GET', '/health/ready', authenticated=False), self._http('GET', '/api/v1/platform')

    def list_items(self, kind, limit=50, cursor=None, device_id=''):
        if kind not in ('devices', 'sources') or type(limit) is not int or not 1 <= limit <= 200:
            raise ClientError('목록 조건이 올바르지 않습니다.')
        query = {'limit': limit}
        if cursor is not None:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 512:
                raise ClientError('목록 cursor가 올바르지 않습니다.')
            query['cursor'] = cursor
        if device_id:
            if kind != 'sources':
                raise ClientError('장치 목록에는 부모 필터를 사용할 수 없습니다.')
            query['device_id'] = identifier(device_id)
        return self._http('GET', '/api/v1/' + kind + '?' + parse.urlencode(query))

    def get_item(self, kind, item_id):
        if kind not in ('devices', 'sources'):
            raise ClientError('지원하지 않는 조회입니다.')
        return self._http('GET', '/api/v1/' + kind + '/' + identifier(item_id, kind == 'sources'))

    def send(self, pending):
        op = pending.mutation
        if op.origin != self.origin:
            raise ClientError('직전 요청의 API 주소와 현재 주소가 다릅니다.')
        # Recheck the public spec immediately before sending bearer mutation.
        self.check_spec()
        pending.uncertain = True
        pending.reply = None
        result = self._http(op.method, op.path, op.body, op.key)
        pending.reply = result
        # All 5xx may have lost a committed response; no automatic new key.
        pending.uncertain = result.status >= 500
        return result
