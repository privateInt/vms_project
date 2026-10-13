# 카메라 접속 설정·자격증명 참조 계약 v1

상태: 11-A 계획 계약 확정 · HTTP/DB/비밀 저장소/실제 연결 미구현 · 운영은 0.7.0-device-delete·스키마 7 유지

기계 판독 원본은 `src/platform/camera/api/planned/connection-config.schema.json`, 합성 예제는 같은 폴더의 `connection-config.examples.json`이다. 루트 스키마는 생성 요청이며 교체·삭제·공개 응답은 $defs로 구분한다. 실행 OpenAPI에는 이번 경로를 추가하지 않는다. 이 계약을 적용해도 접속 설정을 저장하거나 카메라에 접속하는 API가 생기지 않는다.

## 소유권과 첫 범위

| 자원 | 소유·역할 | 변경 기준 |
|---|---|---|
| Device | camera의 물리 장치 등록 | 기존 kind·ID와 삭제 계약 유지 |
| VideoSource / StreamProfile | camera의 논리 채널·선언 영상 프로필 | 기존 source_id·device_id·channel_key·profile_id와 계약 유지 |
| ConnectionConfig | 한 소스·프로필의 접속 파라미터·자격증명 참조 | 별도 ID·version·tombstone. 설정 저장과 연결 성공 구분 |
| CredentialVersion | camera 비밀 저장소의 불변 비밀 버전·소유 장치·허용 접속 대상 | 설정은 opaque ID와 정확한 버전만 참조. 비밀 원문은 별도 경로 |
| SourceSession / 사용 예약 | 이후 실제 수신·연결 준비·소비·정리 상태 | 설정 버전·자격증명 버전을 고정하고 실제 연결 시 생성 |

첫 어댑터 계약은 **RTSP_PULL·RTSP over TCP**다. 등록된 소스가 RTSP/PULL이어야 하고 해당 profile_id가 실제 등록 프로필이어야 한다. 장치 종류를 CCTV로 강제하지 않는다. 다만 이 선언은 코덱·해상도·FPS가 장비와 일치하거나 RTSP over TCP를 장비가 지원한다는 증거가 아니다.

ONVIF 탐색/인증/프로필 매핑/PTZ, RTSPS·UDP, XR/WebRTC 송출자 인증·시그널링은 별도 기술 검증과 어댑터 계약 후 확장한다. XR 장치를 ONVIF 장치로 취급하지 않는다. 이번 범위에는 자동 탐색·연결 시험·스트림 시작·녹화·분석·UI가 없다.

ConnectionConfig는 source_id+profile_id에 연결하며 device_id는 부모 소스에서 도출한다. 클라이언트가 부모 장치·채널을 중복 지정하거나 바꾸지 못한다. 한 source_id+profile_id에 미삭제 설정은 최대 1개다. 삭제 설정의 ID는 재사용하지 않으며, 사용/정리가 끝나고 설정을 논리 삭제한 뒤 같은 소스·프로필에 새 ID로 설정을 만들 수 있다. 소스/프로필은 설정 삭제로 변경하지 않는다.

## 입력 형태

| 생성 필드 | 기준 |
|---|---|
| schema_version | v1 |
| connection_config_id | ASCII 영숫자로 시작, 영숫자·점·밑줄·하이픈 1~64자 |
| source_id / profile_id | 기존 ID 규칙. source_id의 validate 예약 유지 |
| adapter | RTSP_PULL만 허용. 생성 후 불변 |
| endpoint | 아래 host·port·path·rtp_transport를 모두 명시 |
| auth | NONE 또는 CREDENTIAL_REF 객체를 명시. 생략·null·자동 선택 없음 |

endpoint는 문자열 URL 대신 host, port, path, rtp_transport의 엄격한 객체다. host는 정규 dotted-decimal IPv4, 괄호/zone 없는 IPv6 또는 ASCII 다중 label DNS 이름이다. DNS 후행 점·단일 label·Unicode 이름은 첫 버전에서 받지 않는다. port는 1~65535의 정수다. rtp_transport는 TCP이며 서버가 scheme=rtsp로 구성한다.

path는 /로 시작하는 최대 2048자의 ASCII 영숫자·점·밑줄·하이픈·물결표·슬래시만 받는다. 중복 슬래시·dot segment·percent escape·query·fragment·userinfo는 허용하지 않는다. 이는 RTSP 전체 문법을 지원한다는 뜻이 아니라 첫 어댑터의 제한된 제품 계약이다. 인코딩/쿼리 경로나 경로에 비밀 토큰을 넣어야 하는 장비는 이 버전의 지원 범위 밖이다. 경로를 임의 정규화해 다른 장치 경로로 바꾸지 않는다.

auth=NONE은 정확히 mode만 포함한다. auth=CREDENTIAL_REF는 mode, credential_id, credential_version을 모두 포함한다. 버전은 1~signed int64 최댓값의 정수다. latest·버전 생략·외부 secret URI·파일 경로를 받지 않는다. username·password·token·Authorization/header·원문 rtsp_url·프록시·임의 TLS/검사 우회 옵션은 설정 입력에 없다. NONE과 참조를 함께 보내지 못한다.

모든 객체의 미지원 필드를 거부한다. 본문은 기존 64 KiB·application/json 기준을 사용한다. HTTP 구현은 중복/이스케이프 중복 키·잘못된 UTF-8·후행 JSON·대소문자 필드 변형을 거부하며 port·expected_version·credential_version을 실수 변환 없이 정수 토큰으로 읽어야 한다. JSON Schema만으로 1과 1.0/1e0 원문 차이를 판정할 수 없다.

## 계획 API와 공개 응답

| 계획 경로 | 입력·성공 | 동작 |
|---|---|---|
| POST /api/v1/connection-configs | ConnectionConfigCreate / 201 | 등록 참조·권한 확인 후 설정 version=1 저장. 장비 연결 없음 |
| GET /api/v1/connection-configs/{connection_config_id} | 본문 없음 / 200 | 안전한 메타데이터만 반환. 미존재/삭제는 404 |
| PUT /api/v1/connection-configs/{connection_config_id} | ConnectionConfigReplace / 200 | expected_version과 endpoint/auth 전체 교체. 부분 병합·소스/프로필/어댑터 변경 없음 |
| DELETE /api/v1/connection-configs/{connection_config_id} | ConnectionConfigDelete / 200 | expected_version·사용 없음 확인 후 논리 삭제. 실제 세션 강제 종료 없음 |

이번 계약에 목록·probe/connect·restore·purge API는 없다. 후속 CRUD 구현 시에도 위 경로를 먼저 인수한다. 읽기/쓰기 모두 Bearer 인증과 해당 camera 자원·자격증명 참조 권한이 필요하다. 권한 없는 다른 장치의 자격증명 실존 여부를 오류 상세로 공개하지 않는다.

공개 ConnectionConfigResponse는 connection_config의 schema_version·ID·소스/프로필·어댑터·auth 참조·version·created_at/updated_at, configuration_state=CONFIGURED·runtime_verified=false·request_id만 반환한다. **endpoint 전체·해결된 자격증명·비밀·주소 원문은 일반 조회·변경·멱등 재생 응답에서 제외한다.** 편집은 사용자가 보관한 입력과 새 전체 값으로 수행하며, 비밀이나 주소를 다시 읽는 API를 암묵적으로 추가하지 않는다. 향후 편집용 주소 조회가 필요하면 별도 권한·응답/감사 계약을 먼저 정한다.

CONFIGURED는 접속 메타데이터 저장 상태이며 연결·프레임·runtime 준비 상태가 아니다. 생성/교체/조회는 SourceSession을 만들거나 DNS·장비 접속·비밀 원문 resolve를 하지 않는다. 자격증명의 안전한 메타데이터 조회만으로 참조 유효성을 확인한다.

DELETE는 최소 deletion(schema_version·connection_config_id·version·deleted_at), configuration_state=DELETED·runtime_verified=false·request_id를 반환한다. 성공 버전은 정확히 1 증가하고 updated_at/deleted_at은 같은 서버 UTC 시각이며 직전 시각보다 과거로 내려가지 않는다. ID·과거 성공 결과는 남기며 장치·소스·프로필·자격증명·녹화 데이터를 연쇄 삭제하지 않는다. 비밀/endpoint 원문의 보관·파기·백업 정책은 저장소 구현 단계에서 별도로 인수해야 한다.

모든 응답은 Cache-Control:no-store와 새 request_id/X-Request-ID를 사용한다. 생성만 정규 Location을 반환한다. PUT/DELETE는 Location을 반환하지 않는다. 실제 연결 결과는 이후 SourceSession 계약에서 다룬다.

## 자격증명 소유권·대상 제한·교체

CredentialVersion은 camera의 비밀 저장소가 관리한다. 일반 설정 DB/등록 DTO·공개 응답·멱등 성공 스냅샷·로그·오류·프로세스 명령행에 원문 비밀을 넣지 않는다. 원문 제출은 별도 권한과 보호된 전송을 갖춘 쓰기 전용 자격증명 경로로 분리한다. TLS/IAM·암호화 저장·키 공급·권한 분리·비밀 지문 관리를 인수한 뒤 실제 비밀 API와 연결을 활성화한다. 2026-10-08 사용자 지시에 따라 백업 추가 설계·검토를 현재 개발 선행 조건에서 제외했다. 암호화 저장·HMAC·admission 저장소는 격리 인수를 마쳤으며 생성·교체 HTTP 구성요소는 [11-C1 계약](camera-credential-write-http.md)을 따른다. 운영 HTTP는 아직 미활성이다.

참조는 같은 camera 권한 범위이며 부모 Device에 귀속된, 미폐기·타입 호환·정확한 버전을 요구한다. 비밀 저장소 장애는 사용 가능한 것으로 해석하지 않는다. 같은 Device라는 이유만으로 임의 주소에 비밀을 보내지 않는다. **각 불변 자격증명 버전의 허용 protocol·host·port 및 접속 대상 정책은 비밀 관리 권한으로 설정하며 일반 ConnectionConfig 쓰기에서 넓힐 수 없다.** 대상 정책 변경도 새 버전으로 관리한다. 설정 저장 시 대상 메타데이터를 확인하고 실제 resolve/접속 시 다시 확인한다. 사용자는 network_policy·허용 CIDR·secret 대상 우회를 요청 본문으로 지정하지 못한다.

비밀번호 교체는 새 불변 CredentialVersion을 생성한 뒤, 사용 중이 아닌 ConnectionConfig를 expected_version으로 새 credential_version에 교체한다. 기존 설정은 암묵적으로 latest를 따라가지 않는다. 단순 암호화 키 재포장은 비밀 값과 대상 정책이 바뀌지 않는다면 credential_version을 바꾸는 동작과 구분한다.

이전 버전 폐기는 현재 설정 참조·연결 준비 예약·세션/소비·정리 상태가 모두 해제된 뒤 수행한다. 과거 성공 응답에 남은 opaque 참조는 비밀을 다시 resolve할 권한이 아니다. 폐기된 참조가 든 과거 응답을 재생해도 설정/비밀/연결을 복원하지 않는다. 긴급 폐기·실행 중 세션 중단은 별도 운영 계약이며 이 단계의 force 옵션으로 만들지 않는다.

## version·멱등성과 실패

POST/PUT/DELETE는 기존 형식의 필수 Idempotency-Key를 사용한다. 범위는 인증 주체·메서드·해석된 정규 경로·키다. 요청 비교는 JSON 객체 키 순서를 무시하고 입력 값·배열 순서를 유지한다. 문자열을 trim·주소 정규화·latest 해석하지 않는다. endpoint/auth를 포함한 전체 의미를 비교하되 원문 요청을 성공 이력에 다시 저장하지 않는다. 공개 메타데이터 결과와 비교 지문만 저장한다.

비공개 endpoint를 낮은 엔트로피 평문 지문으로 노출하지 않도록 비교 지문은 별도 키를 사용하는 HMAC 기반으로 저장해야 한다. 키 버전·교체·옛 성공 요청 재생·복원·키 부재 시 실패 조건을 비밀 저장소와 함께 인수한다. Bearer 토큰·DB 비밀번호·비밀 암호화 키를 비교 키로 재사용하지 않는다. 이 요건은 아직 구현된 지문 기능을 뜻하지 않는다.

같은 성공 키·같은 유효 요청은 최초 상태/메타데이터를 같은 201 또는 200으로 재생하고 현재 참조/상태를 다시 적용하지 않는다. 같은 성공 키의 다른 본문은 409 IDEMPOTENCY_CONFLICT다. 인증·엄격한 요청 검사는 재생에도 적용한다. 성공 이력은 설정 변경과 같은 트랜잭션에 저장하고 자동 만료시키지 않는다.

실패는 성공 키를 예약하지 않는다. 같은 실패 키로 조건이 해소된 뒤 재시도할 수 있다. 버전 불일치는 현재 안전한 메타데이터를 조회한 뒤 새 version·새 키로 요청한다. 같은 값을 PUT해도 새 키의 성공 교체는 version을 1 증가시킨다. 성공 기록 실패는 설정 version·시각·tombstone도 롤백한다. 삭제 후 새 키의 PUT/DELETE는 404, ID 재사용 POST는 409다.

HTTP 순서는 인증/권한 → 메서드 → 쿼리 → 단건 경로 ID → 미지원 조건 헤더 → 단일 키 → media/JSON → 의미 검사 → 저장소다. 모든 계획 경로에서 쿼리는 허용하지 않는다. GET은 mutation용 키를 요구하지 않는다. 저장소 mutation 우선순위는 성공 이력 → 생성 ID/활성 설정 → version/소진 → 부모/프로필·비밀 참조/대상 → 사용 상태 → 원자적 변경이다.

| HTTP / code | 조건 |
|---|---|
| 400 QUERY_INVALID / PRECONDITION_HEADER_UNSUPPORTED / IDEMPOTENCY_KEY_INVALID / INVALID_JSON | 쿼리·미지원 조건 헤더·키·엄격한 파싱 오류 |
| 401 UNAUTHORIZED / 403 FORBIDDEN | 인증 실패 / 자원·참조 권한 부족 |
| 404 CONNECTION_CONFIG_NOT_FOUND | 새 조회/교체/삭제의 미존재·삭제 설정 |
| 405 METHOD_NOT_ALLOWED | 계획한 메서드 외 요청 |
| 409 CONNECTION_CONFIG_EXISTS / CONNECTION_PROFILE_CONFIGURED | 설정 ID 예약 / 미삭제 소스·프로필 설정 중복 |
| 409 CONNECTION_CONFIG_VERSION_CONFLICT / CONNECTION_CONFIG_VERSION_EXHAUSTED / IDEMPOTENCY_CONFLICT | version 불일치·소진 / 성공 키의 다른 본문 |
| 409 SOURCE_UNAVAILABLE / CREDENTIAL_UNAVAILABLE | 부모 소스/장치 미존재·삭제 / 미허용·부적합·폐기 비밀 참조 또는 대상 |
| 409 CONNECTION_CONFIG_IN_USE | 사용 예약·세션·소비·정리 중 교체/삭제 |
| 413 BODY_TOO_LARGE / 415 UNSUPPORTED_MEDIA_TYPE | 기존 본문/media 제한 |
| 422 CONTRACT_INVALID / PROFILE_NOT_REGISTERED | 입력 의미 오류 / 등록 소스에 없는 프로필 |
| 503 CONNECTION_USAGE_UNAVAILABLE / CREDENTIAL_STORE_UNAVAILABLE / DATABASE_UNAVAILABLE | 사용/정리·비밀 메타데이터·저장소 확인 불가 |

오류에는 기존 error/request_id 구조를 사용하며 입력 값·주소·사용자명·비밀·키·다른 자원·DB/SDK 상세를 넣지 않는다. 생성 ID 중복과 version 검사는 같은 요청에서 뒤 조건보다 우선한다. GET은 외부 비밀 저장소 장애와 무관하게 저장된 안전한 메타데이터를 조회할 수 있으며 참조를 READY로 표시하지 않는다.

## 삭제·사용 시작의 원자적 경계

설정 등록은 미삭제 부모·프로필을 같은 camera 트랜잭션에서 확인한다. 새 소스 생성/장치 삭제의 기존 장치 advisory 잠금과 호환되는 장치 잠금을 유지하고 장치 → 소스 → 설정 → 자격증명 메타데이터의 순서를 공유한다. 요청별 멱등 잠금이 앞선다. 잠금 획득 후 별도 조회로 최신 커밋된 부모/사용 상태를 확인하며 잠금 전 목록을 재사용하지 않는다. 고유 제약은 소스+프로필의 동시 생성을 보호한다. 기존 장치/소스 삭제의 잠금을 임의로 갈아끼우거나 반대 순서를 도입하지 않는다.

실제 사용 시작도 같은 원자적 경계에서 미삭제 설정·부모·버전/비밀 참조를 확인하고 **연결 준비 예약을 먼저 기록**해야 한다. DNS/비밀 resolve/연결 작업은 DB 잠금을 오래 잡은 채 수행하지 않고 예약된 정확한 설정/비밀 버전에 대해 진행한다. 예약·연결·소비·정리 중인 설정의 PUT/DELETE는 거부한다. 확인 불가·부분 정리·결과 불확실은 미사용으로 처리하지 않는다. 실제 소켓·워커 종료 확인 전 예약을 없애고 삭제를 허용하지 않는다.

미삭제 설정은 부모 소스의 관리 종속 관계다. 소스 삭제는 설정 논리 삭제/사용 종료가 먼저 필요하며 기존 SOURCE_IN_USE 계약으로 거부한다. 장치 삭제는 기존 미삭제 자식 소스 검사·관리 사용 보호를 유지한다. 자격증명은 설정/부모 삭제로 자동 파기하지 않는다. 소스 삭제가 먼저 커밋되면 이후 설정 생성은 SOURCE_UNAVAILABLE, 설정 생성이 먼저 커밋되면 소스 삭제는 SOURCE_IN_USE여야 한다.

이번 운영 registry-only-v1의 정확한 capability/사용 guard는 보존한다. **후속 설정 API 배포에는 미삭제 설정·준비 예약·사용/정리 상태를 확인하는 새 guard와 검토 capability가 함께 필요하다.** 기존 등록 전용 guard를 그대로 둔 채 새 기능만 켜지 않는다. 실제 세션 도입 시에도 같은 경계를 확장하며 다른 플랫폼 DB를 조회해 판단하지 않는다.

## 실제 연결 전에 필요한 주소·비밀 검증

등록 API는 DNS/장비 요청 없이 형태와 저장된 참조만 확인한다. 주소 형태가 유효하거나 private IP라는 사실만으로 접속을 허가하지 않는다. 실제 연결 시에는 운영자가 별도로 승인한 장치망/CIDR·DNS 이름·protocol/port와 자격증명 버전의 대상 정책을 모두 통과해야 한다. 카메라용 사설망은 명시적으로 허용할 수 있지만 loopback·unspecified·multicast·link-local/metadata 등 보호 주소는 구분해 거부한다. IPv4-mapped IPv6도 동일 대상 정책으로 정규화해 확인한다.

DNS의 A/AAAA 대상 모두를 검사하고 허가한 주소로 실제 소켓을 고정한다. 검증 후 SDK가 다시 다른 주소를 resolve/dial하거나 redirect를 따라가는 우회를 허용하지 않는다. 재접속 시에도 주소·비밀 버전·대상 권한을 다시 확인한다. redirect 지원은 첫 어댑터에서 끈다. timeout·취소·최대 응답/시도·비밀 resolve 범위와 회수를 제한한다. 원문 인증 값을 URL·명령행·프로세스 출력으로 내보내는 연결 방식은 인수 기준을 충족하지 않는다.

RFC 3986은 URI userinfo의 user:password 사용을 권장하지 않으며 구성요소와 인코딩 해석의 보안 위험을 설명한다. OWASP의 SSRF 지침은 대상 허용 목록, DNS 주소 검사와 redirect 제한을 다룬다. 이를 참고해 위 제품 제한을 정했으며 이 스키마가 주소 권한·DNS/소켓·비밀 저장 보안을 구현했다고 보지 않는다.

- [RFC 3986 §3.2.1·§7](https://www.rfc-editor.org/rfc/rfc3986.html)
- [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)

## 후속 구현 인수 기준

1. 비밀 저장소의 장치/대상 범위·불변 버전·폐기·키 분리·보호된 원문 입력·암호화 저장·멱등 비교 키를 구현하고 인수한다. 백업 추가 설계는 2026-10-08 사용자 요청에 따라 제외한다.
2. 설정 저장소·고유 제약·엄격한 HTTP·메타데이터 응답·멱등/버전·tombstone 및 부모 삭제 guard를 함께 구현한다. 참조 부적합·비밀 저장소 장애·같은 프로필 경쟁·삭제/교체/소스 삭제 경쟁·성공 기록 실패 롤백을 native DB와 실제 HTTP로 검증한다.
3. 메타데이터 단계의 미지원 세션/사용 상태를 명시하고, 실제 어댑터 도입 전에는 준비 예약·접속 대상 고정·비밀 전달·단절/재접속/취소/정리 경쟁을 별도로 인수한다.
4. 검증된 코드/이미지의 사전점검·격리 리허설·운영 전환 후 해당 기능을 활성화한다. 실장비 연결/영상/프로필 관측 결과를 별도로 기록한다.

이번 정적 검사는 입력/응답 형태와 합성 예제만 확인한다. 부모·프로필·비밀 실존/권한·raw 정수/중복 JSON·HMAC/암호화·트랜잭션·네트워크 대상·실제 RTSP·동시성·운영 활성화는 아직 검증하지 않았다. 설계 판단은 [ADR 0005](../architecture/decisions/0005-camera-connection-config.md), 이번 적용·검증·남은 작업은 [11-A 기록](../progress/20261002-step11a-connection-config-contract.md)을 따른다.
