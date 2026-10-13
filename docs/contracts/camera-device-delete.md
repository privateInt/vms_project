# 장치 논리 삭제 계약 — 단위 10-A

상태: 10-B 서버 저장소 격리 인수 완료 · 10-C HTTP 구현/로컬 검증 완료 · 서버 HTTP 격리 인수/운영 활성화 전 · 2026-10-02

## 범위와 현재 상태

camera가 소유한 Device 등록을 논리 삭제한다. 미삭제 자식 VideoSource가 없어야 하며, 장치·삭제된 자식 소스·프로필·요청 이력은 보존한다. force·cascade·영구 삭제·복원·자격증명 또는 녹화 정리는 포함하지 않는다.

현재 운영은 `0.6.0-source-delete`·스키마 6이다. 장치/소스 등록·조회·표시 이름 수정과 소스 논리 삭제가 활성화됐으며, 장치 단건 DELETE는 아직 405/Allow: GET, PATCH다. 10-A 적용은 운영 API·DB·실행 OpenAPI를 바꾸지 않는다. 현재 인수 기준은 [09 완료 기록](../progress/20261001-step09-server-acceptance.md)이다.

기계 판독 계약은 `src/platform/camera/api/planned/device-delete.schema.json`이다. 루트는 DeviceDelete 요청이며 `$defs/DeviceDeleteResponse`는 별도의 삭제 결과다. 기존 Device 응답·등록 계약을 변경하지 않는다. 10-C 개발 코드의 실행 원본은 OpenAPI DeviceDelete/DeviceDeletion/DeviceDeleteResponse이며 planned 계약·예제는 설계 기준으로 보존한다. 새 코드 버전은 0.7.0-device-delete·스키마 7이다.

## 요청과 검증

| 항목 | 규칙 |
|---|---|
| 메서드·경로 | DELETE /api/v1/devices/{device_id} |
| 인증 | 기존 Bearer 인증과 안정된 개발용 공통 인증 주체 |
| 경로 ID | 기존 ASCII 1~64자 식별자. 첫 문자는 영문/숫자, 나머지는 영문/숫자/점/밑줄/하이픈 |
| 본문 | schema_version=v1, expected_version 두 필드 필수 |
| Content-Type / 크기 | application/json / 64 KiB 제한 |
| Idempotency-Key | 단일 필수 헤더, 1~128자 ASCII 표시 문자(0x21~0x7e) |
| 쿼리 | 빈 물음표만 붙인 경우도 허용하지 않음 |
| 조건 헤더 | If-Match·If-None-Match·If-Unmodified-Since는 400. 본문의 version 조건 사용 |

```json
{
  "schema_version": "v1",
  "expected_version": 2
}
```

expected_version은 장치 GET/목록의 version이다. 1~9223372036854775807 범위의 정확한 signed 64-bit JSON 정수 토큰을 요구한다. 실수 1.0·지수 1e0·문자열·bool·null·범위 초과는 INVALID_JSON, 0·음수 정수와 필수값 누락은 CONTRACT_INVALID다. 대소문자가 다른 필드·중복 키·미지원 필드·잘못된 UTF-8·최상위 비객체·후행 JSON을 거부한다.

장치 version은 자식 목록의 버전이 아니다. 소스 생성/삭제는 부모 version을 증가시키지 않으므로, expected_version이 같더라도 자식 존재 여부를 트랜잭션 안에서 다시 확인해야 한다.

DELETE도 JSON 본문을 요구한다. 본문 유실을 무조건 삭제로 해석하지 않으며 클라이언트·향후 프록시의 본문 전달을 HTTP 단계에서 검증한다. 장치 ID·삭제 시각·자식 목록·사용 여부·force/cascade 등을 클라이언트가 본문으로 지정할 수 없다.

**장치 ID `validate`는 유효하다.** 예약된 소스 경로 `/api/v1/sources/validate` 규칙을 장치에 적용하지 않는다. 장치 경로의 validate·Validate·URL 이스케이프로 해석된 같은 ID 모두 일반 장치 ID 규칙을 따른다. 기존 장치 ID를 새로 예약하거나 거부하지 않는다.

## 자식 소스와 사용 관계

| 장치/자식 상태 | 새로운 장치 DELETE 판단 |
|---|---|
| 장치 없음 또는 이미 삭제 | 404 DEVICE_NOT_FOUND |
| 미삭제 자식 소스가 한 개 이상 | 409 DEVICE_HAS_ACTIVE_SOURCES |
| 자식 없음 | 사용 관계 검사 후 허용 가능 |
| 모든 자식이 논리 삭제됨 | 삭제된 소스/프로필/이력을 보존하고 사용 관계 검사 후 허용 가능 |
| 관리 대상 장치 사용·세션·임대·정리 대기 존재 | 409 DEVICE_IN_USE |
| 사용 여부 또는 등록 전용 전제를 확인할 수 없음 | 503 DEVICE_USAGE_UNAVAILABLE |

여기서 미삭제/활성 자식은 `video_sources.deleted_at IS NULL`인 등록 행을 뜻한다. 영상 수신 중인 소스만 세는 것이 아니다. 부모와 연결된 미삭제 소스를 먼저 기존 소스 DELETE 절차로 각각 삭제해야 한다. 장치 DELETE가 자식 삭제를 대신하거나 자동 종료/정리 작업을 시작하지 않는다.

첫 구현·활성화는 SourceSession·consumer·ONVIF/PTZ 연결·입력 어댑터 등 관리되는 사용 관계를 만드는 기능이 없는 등록 전용 릴리스로 한정한다. 단순히 자식 수 0이나 business_runtime_ready=false라는 값만으로 미사용을 판단하지 않는다. 서버 코드·생성자·구성·capability 전체를 검토한 등록 전용 정책만 사용하며, 검사 누락·알 수 없는 모드·상태·오류는 허용하지 않는다. 클라이언트가 정책을 선택하거나 우회할 수 없다.

10-C는 device_delete capability와 장치/소스 삭제 공통의 정확한 등록 전용 허용 목록을 함께 추가했다. 기존 소스 DELETE와 새 장치 DELETE의 실제 로컬 HTTP 회귀 검사가 통과했다. 등록 저장소가 구성된 검토 릴리스에서만 두 삭제 guard가 미사용을 반환하고, capability 누락·추가·값 변경·알 수 없는 모드·취소는 거부한다. 이 정책은 서버 생성자에서 선택하며 클라이언트나 환경 설정으로 선택할 수 없다.

향후 실제 사용 관계를 도입하면 사용 시작도 장치 삭제와 같은 원자적 허용 경계에 참여해야 한다. 원격 사용 상태를 잠깐 조회한 뒤 삭제하는 방식만으로 경쟁을 막았다고 보지 않는다. 외부 장치의 미디어 사용을 감지하는 기능으로 이 계약을 설명하지 않으며, 다른 플랫폼 DB를 직접 조회·수정하지 않는다.

## 동시성·잠금 순서

현재 CreateSource는 성공 이력을 먼저 확인한 뒤, 새 등록에 대해 `pg_advisory_xact_lock(1447908164, hashtext(device_id))`를 잡고 미삭제 부모 존재를 확인한다. 장치 삭제도 이 **동일한 장치별 트랜잭션 잠금**을 사용한다. 부모 행 잠금만 새로 추가하고 기존 소스 등록 잠금과 분리하면 안 된다. 해시 충돌은 서로 다른 장치 작업을 더 직렬화할 수 있지만 삭제 허용 조건을 완화하지 않는다.

새 장치 DELETE의 저장소 처리 순서는 다음과 같다.

1. 요청별 멱등 잠금 → 성공 이력 조회. 같은 성공 요청이면 최초 결과 재생, 내용이 다르면 키 충돌.
2. 위 장치별 잠금 → 미삭제 장치 행 FOR UPDATE.
3. 장치 version 일치 → 버전 소진 여부 → 미삭제 자식 존재 → 서버 사용 관계 검사.
4. 장치 tombstone·version·시각과 삭제 성공 기록을 한 트랜잭션으로 저장.

잠금은 트랜잭션 종료까지 유지한다. 자식 조회는 장치별 잠금을 획득한 **뒤 별도 문장**으로 수행해 앞선 소스 등록 커밋을 보아야 한다. 잠금 대기 전의 자식 목록·스냅샷을 재사용하지 않는다. 이 경로의 READ COMMITTED 실행 조건을 확인하고 실제 다중 연결 시험으로 이를 검증한다. 향후 여러 자원 잠금이 필요하면 장치별 잠금 → 장치 행 → 소스 행의 순서를 지키고 역순 획득을 도입하지 않는다.

| 경쟁 상황 | 허용 결과 |
|---|---|
| 새 소스 등록이 장치 잠금을 먼저 얻어 커밋 | 뒤따른 장치 삭제는 DEVICE_HAS_ACTIVE_SOURCES |
| 장치 삭제가 먼저 커밋 | 뒤따른 새 소스 등록은 기존 409 DEVICE_UNAVAILABLE. 새 소스/프로필/성공 이력을 남기지 않음 |
| 앞선 소스 등록 또는 장치 삭제가 롤백 | 잠금을 얻은 후 실제 커밋 상태로 다시 판단 |
| 장치 PATCH가 같은 version으로 먼저 성공 | 장치 DELETE는 409 DEVICE_VERSION_CONFLICT |
| 장치 DELETE가 먼저 성공 | 새로운 장치 PATCH는 404 DEVICE_NOT_FOUND |
| 다른 키의 동시 장치 DELETE | 한 번만 성공, 뒤 요청은 404 DEVICE_NOT_FOUND |
| 같은 키·본문의 동시 DELETE | 한 번만 변경, 나머지는 같은 성공 결과 재생 |
| 마지막 소스 DELETE와 장치 DELETE가 겹침 | 소스 삭제 커밋 전의 활성 자식이 보이면 거부 가능. 소스 삭제 완료 뒤 같은 실패 키로 재시도 가능 |

장치 이름 PATCH의 기존 장치 행 잠금과 DELETE의 행 잠금을 함께 사용한다. 소스 DELETE를 강제로 취소하거나 부모 삭제를 위해 자식 데이터를 고치지 않는다. 과거 소스 POST 성공 재생은 새 소스 생성이 아니므로 기존처럼 현재 부모 검사 전에 저장된 결과를 반환하며, 부모 삭제를 취소하거나 새 활성 자식을 만들지 않는다.

## 성공 응답과 보존

최초 성공과 동일 성공 재생은 모두 HTTP 200이다. 202·204·201을 사용하지 않으며 Location을 반환하지 않는다. Cache-Control은 no-store, Idempotency-Replayed는 최초 false/재생 true다. 매 요청에 새 request_id를 만들고 X-Request-ID와 일치시킨다.

```json
{
  "deletion": {
    "schema_version": "v1",
    "device_id": "camera-001",
    "version": 3,
    "deleted_at": "2026-10-01T11:20:00.123456Z"
  },
  "registration_state": "DELETED",
  "runtime_verified": false,
  "request_id": "example-device-delete-001"
}
```

최소 삭제 결과만 반환하며 장치 전체 스냅샷·자식 ID 목록·프로필·접속 비밀을 포함하지 않는다. 이 응답은 등록 삭제 확인이며 장비 전원 종료·미디어 수신 중단·영구 삭제 완료를 의미하지 않는다.

| 대상 | 새 성공 후 |
|---|---|
| 장치 version | 정확히 1 증가. 최댓값에서는 DEVICE_VERSION_EXHAUSTED |
| 장치 deleted_at / updated_at | 동일한 서버 UTC 시각. 직전 updated_at보다 과거로 내려가지 않음 |
| 장치 ID·종류·표시 이름·created_at | 보존 |
| 삭제된 자식 소스·프로필·식별자/채널 예약 | 모든 행·필드·순서·삭제 시각·version 보존 |
| 장치/소스의 POST·PATCH·DELETE 성공 이력 | 최초 스냅샷/삭제 결과 보존 |
| 다른 장치와 그 소스 | 변경하지 않음 |

장치 행을 남기므로 기존 자식 FK를 끊거나 물리 DELETE 권한을 부여하지 않는다. 삭제된 device_id를 새 생성 키로 다시 등록하면 기존 409 DEVICE_EXISTS다. 과거 장치 생성 성공 키는 원래 201 스냅샷을, 과거 장치 PATCH 성공 키는 원래 200 스냅샷을 재생한다. 장치/자식 소스를 복원하지 않는다. 삭제된 부모를 가진 과거 소스 POST/PATCH/DELETE 성공 이력도 기존 결과 그대로 재생한다.

새 장치 GET은 404, 장치 목록은 삭제 행을 제외한다. 이전 cursor가 삭제 장치를 가리켜도 그 ID 이후부터 탐색한다. 소스 목록의 필터·cursor 의미는 변경하지 않는다. 삭제 장치에는 미삭제 자식이 없으므로 해당 device_id의 새 소스 목록은 200·빈 items·next_cursor=null이다. include_deleted·복원·ID 재사용 API는 추가하지 않는다.

## 멱등성과 오류 순서

멱등 범위는 인증 주체 + DELETE + 해석된 유효 device_id의 정규 경로 + 키다. 장치 POST/PATCH, 소스 DELETE, 다른 장치의 DELETE와 독립이다. schema_version·expected_version을 정규 직렬화해 비교하며 객체 키 순서·동등한 문자열/경로 이스케이프만 무시한다. 키 원문 대신 해시를 저장한다. 기존 공통 인증 주체를 유지하는 토큰 교체 후에도 재생한다.

성공 기록만 저장하고 자동 만료시키지 않는다. 같은 성공 키·같은 유효 본문은 현재 장치 상태·version·자식/사용 상태 검사보다 먼저 결과를 재생한다. 같은 성공 키에 다른 본문이면 삭제 후에도 IDEMPOTENCY_CONFLICT다. 새 키의 이미 삭제된 장치 요청은 DEVICE_NOT_FOUND다. 인증과 요청 검증은 재생에도 항상 적용한다.

실패는 성공 기록을 남기지 않는다. 자식 삭제 또는 사용 종료 후 같은 키·본문으로 다시 판단할 수 있다. 응답 유실·타임아웃·503에는 같은 키·본문으로 재시도한다. version 충돌은 현재 장치를 조회한 뒤 새 version·새 키로 요청하며 서버가 자동 보정하지 않는다. 삭제 결과 기록 실패 시 장치의 deleted_at·version·updated_at도 함께 롤백한다.

HTTP 검사 순서는 인증 → 메서드 → 쿼리 → 해석된 경로 ID → 조건 헤더 → 키 → Content-Type/JSON → 의미 검사 → 저장소다. 저장소 우선순위는 성공 이력 → 활성 장치 → version → 소진 → 활성 자식 → 사용 관계 → 변경이다. 예를 들어 version 불일치와 활성 자식이 함께 있으면 DEVICE_VERSION_CONFLICT를 반환한다.

| HTTP | code | 조건 |
|---|---|---|
| 400 | QUERY_INVALID | 쿼리 또는 빈 물음표·잘못된 인코딩 |
| 400 | PRECONDITION_HEADER_UNSUPPORTED | 미지원 조건 헤더 |
| 400 | IDEMPOTENCY_KEY_INVALID | 키 누락·중복·형식 오류 |
| 400 | INVALID_JSON | JSON/타입/원문 정수/중복·미지원 필드/UTF-8/본문 오류 |
| 401 | UNAUTHORIZED | 인증 실패 |
| 404 | DEVICE_NOT_FOUND | 성공 이력 없는 새 요청에서 장치 없음·삭제됨 |
| 405 | METHOD_NOT_ALLOWED | 구현 후 장치 단건 GET/PATCH/DELETE 외 메서드. Allow: GET, PATCH, DELETE |
| 409 | DEVICE_VERSION_CONFLICT / DEVICE_VERSION_EXHAUSTED | version 불일치 / 일치한 version이 최댓값 |
| 409 | IDEMPOTENCY_CONFLICT | 같은 성공 키의 다른 유효 본문 |
| 409 | DEVICE_HAS_ACTIVE_SOURCES | 미삭제 자식 소스 존재 |
| 409 | DEVICE_IN_USE | 관리 대상 사용 관계·정리 대기 존재 |
| 413 | BODY_TOO_LARGE | 본문 64 KiB 초과 |
| 415 | UNSUPPORTED_MEDIA_TYPE | application/json이 아님 |
| 422 | CONTRACT_INVALID | 필수값 누락·schema_version/경로 ID·0/음수 version |
| 503 | DEVICE_USAGE_UNAVAILABLE | 사용/정책 확인 불가 |
| 503 | REGISTRY_DISABLED / DATABASE_UNAVAILABLE | 저장소 미설정 / DB·트랜잭션 이용 실패 |

오류에는 기존 error와 request_id 구조를 사용하고 성공용 Location·Idempotency-Replayed를 넣지 않는다. no-store·X-Request-ID는 유지한다. 자식 원문·토큰·키·세션·내부 DB 오류를 반환하지 않는다. 소스 POST의 부모 부재 오류는 기존 409 DEVICE_UNAVAILABLE을 유지하며 장치 DELETE의 404와 혼동하지 않는다.

## 저장소·HTTP·운영 완료 기준

10-B에서 구현하고 native 서버 검사를 마친 범위는 신규 마이그레이션 0007·스키마 7과 별도 `camera.device_delete_requests`다. 기존 마이그레이션 0001~0006과 성공 이력을 다시 쓰지 않는다. 삭제 성공 기록은 부모에 연쇄 삭제되는 FK를 갖지 않는다. 추가 runtime 권한은 devices.deleted_at 열 UPDATE와 새 성공 기록 SELECT/INSERT로 제한하고 기존 version·updated_at 권한을 사용한다. 물리 DELETE·소스/프로필 변경 권한을 장치 삭제에 추가하지 않는다.

기존 CreateSource 장치별 잠금과의 실제 동시 접속 시험이 필수다. 자식 없음/활성/전부 삭제·현재 사용/확인 불가, DELETE/POST 소스 생성·장치 PATCH 경쟁, 같은 키 동시 재생, version 최대·시간 역행 방지, 권한/성공 기록 실패의 원자적 롤백, 모든 과거 이력·삭제된 자식/프로필 보존과 API 재시작 후 지속성을 검증한다.

10-C는 HTTP 연결·실행 OpenAPI·capability와 공통 등록 전용 정책을 구현하고 기존 소스 DELETE 로컬 회귀를 확인했다. 대상 서버 HTTP/native 권한 인수는 대기 중이다. 이후 사전점검·이미지 업그레이드/별도 DB 복원 리허설·실제 운영 전환으로 나눈다. 이전 스키마 이미지로만 되돌리거나 운영 DB를 자동 복원하는 절차를 가정하지 않는다.

이번 정적 JSON Schema 검사는 요청/응답 형태와 예제만 확인한다. 파싱 후 값으로는 1과 1.0/1e0 원문을 구분할 수 없고, 중복 키·헤더·인증·DB 권한·자식/사용 판단·실제 잠금·원자성도 검증하지 못한다. 이 항목은 구현 단계의 완료 조건으로 남긴다.
