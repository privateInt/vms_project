# 자격증명 버전 생성·교체 HTTP

상태: 11-C1 구성요소 구현·로컬/서버 격리 검증 인수 완료 · 현재 실행 API에는 미등록

## 작업 순서

2026-10-08 사용자 지시에 따라 백업의 추가 설계·검토를 현재 범위와 개발 선행 조건에서 제외한다. 이전 도구와 검증 기록의 완료 상태는 바꾸지 않는다. 자격증명 HTTP → 연결 설정 → 실제 카메라 연결 순으로 제품 기능을 진행한다.

## 경로와 입력

`POST /api/v1/credentials/{credential_id}/versions`는 불변 버전을 만든다. expected_version=0은 새 자격증명의 버전1을 만들고 양수는 정확한 현재 head에서 다음 버전을 만든다. 교체도 새 버전 생성이므로 최초 성공과 동일 요청 재생은 모두201이다. 기존 버전과 대상 정책은 바꾸지 않고 latest 참조를 만들지 않는다.

계약 원본은 [credential-write.openapi.json](../../src/platform/camera/api/planned/credential-write.openapi.json)이다. 현행 OpenAPI·main·0.7.0 capability에는 미등록이다. 명시적 통합 진입점 RegisterCredentialWrites에 concrete CredentialStore·trusted principal resolver·transactional authorizer를 모두 공급해야 경로를 설치한다. nil 구성은 거부한다. 개발 registry 주체에 비밀 관리 권한을 자동 부여하지 않는다.

| 입력 | 의미 |
|---|---|
| credential_id 경로 | 기존 형식의 1~64 ASCII ID |
| schema_version | 정확히 v1 |
| device_id | 부모 장치 ID |
| expected_version | 필수 signed int64 정수 토큰, 0 이상 |
| target | 정확한 RTSP protocol·host·port 정책 |
| secret | 쓰기 전용 username·password 객체 |
| Idempotency-Key | 필수 단일 헤더, 1~128 visible ASCII |

scope/principal은 trusted middleware context에서만 받는다. 본문에 넣으면 INVALID_JSON이며 X-Scope-ID/X-Principal-ID 헤더는 사용하지 않는다. resolver가 비밀 관리 권한을 확인하고 저장소 authorizer가 장치·자격증명 범위를 두 데이터 트랜잭션에서 다시 확인한다. 실제 IAM 정책과 운영 TLS 공급은 후속 통합 대상이다.

## 엄격한 검사와 비공개

Bearer → 실제 TLS1.2 이상 handshake → trusted 주체/관리 권한 → POST → 쿼리 → ID → 조건 헤더 → 멱등 키 → media/JSON → 의미 검사 → 저장소 순이다. X-Forwarded-Proto를 TLS 증거로 받지 않으며 프록시 신뢰 통합을 자동 추가하지 않는다. 쿼리와 If-* 조건 헤더는 거부한다.

application/json·64 KiB 제한, 각 객체의 exact field·unique key를 검사한다. escaped duplicate·case variant·unknown key·null/wrong type·trailing JSON·잘못된 UTF-8·짝 없는 UTF-16 surrogate는 거부한다. version/port를 float로 변환하지 않는다. JSON Schema의 integer 표기만으로 raw token 검증이 되지는 않는다.

username은 최대128 UTF-8 bytes이며 공백만으로 구성할 수 없다. password는 최대4096 UTF-8 bytes다. 둘 다 빈 문자열·C0·DEL을 거부하며 주변 공백·Unicode를 그대로 유지한다. DTO의 fmt/String/GoString은 가려진 값만 내고 JSON 직렬화를 거부한다. 요청 종료 시 참조를 비우되 Go 문자열 메모리의 강제 삭제를 보장하지 않는다.

HTTP와 저장소가 같은 대상 predicate를 사용한다. canonical IP는 bracket/zone을 허용하지 않고 DNS는 dotted ASCII label·alphabetic final label을 요구한다. 대소문자를 정규화하지 않는다. 형태 검사가 DNS·접속·비밀 전송 권한을 뜻하지 않는다.

store.WriteVersion의 전체 작업 admission lease·별도 커밋 암호화 budget·HMAC 멱등 비교·transactional authorizer를 유지한다. 성공 재생에도 새 권한/admission 검사를 수행한다. guard 없는 concrete 저장소는 DB IO 전에 CREDENTIAL_ADMISSION_UNAVAILABLE로 실패한다. production constructor는 synthetic writer를 받지 않는다.

성공 응답은 credential_id·device_id·credential_version·created_at과 request_id뿐이다. Idempotency-Replayed는 true/false다. 불일치 ID/device/version/time·폐기된 receipt는 반환하지 않고503으로 실패한다. Cache-Control:no-store·X-Request-ID·nosniff를 유지하며 주소·username·password·암호문·키·HMAC·DB 오류를 응답·로그에 넣지 않는다.

| HTTP | 주요 code |
|---|---|
| 400 | QUERY_INVALID, PRECONDITION_HEADER_UNSUPPORTED, IDEMPOTENCY_KEY_INVALID, INVALID_JSON |
| 401 / 403 | UNAUTHORIZED / FORBIDDEN, CREDENTIAL_TRANSPORT_REQUIRED |
| 405 / 413 / 415 / 422 | METHOD_NOT_ALLOWED / BODY_TOO_LARGE / UNSUPPORTED_MEDIA_TYPE / CONTRACT_INVALID |
| 409 | CREDENTIAL_EXISTS, CREDENTIAL_UNAVAILABLE, CREDENTIAL_VERSION_CONFLICT, CREDENTIAL_VERSION_EXHAUSTED, DEVICE_UNAVAILABLE, IDEMPOTENCY_CONFLICT |
| 503 | CREDENTIAL_AUTHORIZATION_UNAVAILABLE, CREDENTIAL_ADMISSION_UNAVAILABLE, CREDENTIAL_STORE_UNAVAILABLE |

미허용·미존재·다른 범위 자원은 저장소의 CREDENTIAL_UNAVAILABLE로 통합한다. 입력 값을 오류 message/details에 복사하지 않고 허용한 code만 응답한다.

## 검증과 다음 단위

HTTP 성공·재생·교체는 synthetic writer로 검사했다. 실제 TLS socket·concrete 미승인 저장소 거부·strict JSON·비밀 비공개는 직접 검사했다. 별도 native PostgreSQL에서 기존 저장소의 암호화·불변 버전·재생·권한·역할 검사를 재확인했다. 새로운 HTTP 성공과 실제 admitted store를 하나의 native 요청으로 연결한 검증은 아직 하지 않았다.

서버 도구는 disposable PostgreSQL의 전체 Go race/vet·필수 HTTP7개·계약5개·기존 native credential13개를 모두 요구한다. 사용자 제공 서버 출력에서 이 조건과 Go 상위170개·하위494개 PASS를 인수했다. 운영 Compose·DB·키·서비스에는 접근하지 않았다. native_admitted_store_http_writes_verified는 false이며 synthetic 성공을 native HTTP 통합 완료로 표시하지 않는다. [서버 인수 기록](../progress/20261008-step11c1-server-acceptance.md)을 따른다.

안전한 버전 메타데이터 조회·폐기 HTTP는 [11-C2](camera-credential-versions-http.md)에서 구현했다. 다음은 실제 권한 정책·admitted 저장소와 HTTP의 격리 통합이며, 이후 실제 IAM·TLS·키/역할 공급·schema9/admission 통합과 서버 검사를 완료해 운영 경로를 활성화한다. ConnectionConfig·실장비·영상·Streamlit 비밀 입력은 이번 범위에 없다. [진행 기록](../progress/20261008-step11c1-credential-write-http.md)을 따른다.
