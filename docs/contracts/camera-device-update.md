# 장치 표시 이름 수정 계약 — 단위 07-A

상태: 계약 확정 · 07-B 저장소 native 검사 통과 · 07-C HTTP 코드 구현 · 운영 활성화 전 · 2026-09-30

## 범위와 계약 원본

장치 수정의 첫 범위는 `display_name` 하나다. 현재 Device에는 표시 이름 외에 이번에 수정할 사용자 메타데이터가 없다. `device_id`와 `device_kind`는 생성 후 불변이며 접속 설정·비밀·지원 기능·장치 삭제는 별도 기능이다. 자식 영상 소스가 있는 장치도 이름을 수정할 수 있으며 소스·프로필·각 자원의 version은 바꾸지 않는다.

07-A 설계 기준은 `src/platform/camera/api/planned/device-update.schema.json`과 같은 폴더의 `device-update.examples.json`에 보관한다. 07-C 실행 요청 계약은 `src/platform/camera/api/openapi.json`의 DeviceUpdate이며 실행 예제는 `api/examples/device-update.json`이다. 기존 Device 응답 구조는 현재 `src/platform/camera/api/openapi.json`을 재사용한다. 이 문서는 상태·동시성·재시도·오류 규칙을 정의한다.

07-A는 계약만 추가했고 07-B는 저장소를 구현·검증했다. 07-C의 `0.4.0-device-update` 코드와 실행 OpenAPI는 PATCH를 제공한다. 운영 중인 `0.3.1-source-list` 이미지와 스키마 3은 유지하므로 현재 운영 API의 PATCH는 여전히 405다.

## 요청

| 항목 | 확정한 규칙 |
|---|---|
| 메서드·경로 | `PATCH /api/v1/devices/{device_id}` |
| 인증 | 기존 Bearer 인증. 현재는 안정된 개발용 공통 인증 주체를 사용 |
| Content-Type | `application/json`. JSON Patch·Merge Patch 문서는 받지 않음 |
| 경로 ID | 기존 ASCII 1~64자 식별자 규칙. 본문에 device_id를 중복 제출하지 않음 |
| 쿼리 | 허용하지 않음 |
| Idempotency-Key | 필수, 단일 헤더, 1~128자의 ASCII 표시 문자(0x21~0x7e). 기존 등록 API와 동일 |
| 본문 크기 | 기존 64 KiB 제한 |
| 버전 조건 | 본문의 expected_version만 사용. If-Match·If-None-Match·If-Unmodified-Since를 보내면 400 `PRECONDITION_HEADER_UNSUPPORTED` |

```json
{
  "schema_version": "v1",
  "expected_version": 1,
  "display_name": "1층 출입구 CCTV"
}
```

세 필드 모두 필수다. `schema_version`은 `v1`, `expected_version`은 조회 응답에서 받은 version이다. `display_name`은 공백만으로 구성할 수 없고 Unicode 코드 포인트 기준 1~128자이며 NUL을 포함할 수 없다. 기존 생성 입력과 동일하게 앞뒤 공백을 임의로 제거하거나 문자열을 정규화하지 않는다.

`expected_version`은 1~9223372036854775807 범위의 정확한 정수다. HTTP 디코더에서는 부호 있는 64비트 정수로 표현되는 JSON 정수 토큰만 받는다. 문자열 `"1"`, 실수 표기 `1.0`, 지수 표기 `1e0`, null·bool은 받지 않는다. 정수 범위를 넘는 토큰도 디코딩 오류다. 부동소수점으로 version을 반올림해 제출하지 않는다.

중복 JSON 키, 잘못된 대소문자, 알 수 없는 필드와 null 값은 거부한다. 기존 값과 같은 device_kind·device_id를 보내더라도 허용하지 않는다. 요청은 지정한 이름으로 교체하는 명령이며 이름을 생략하거나 null로 지우는 동작은 없다.

## 성공과 버전 규칙

처음 성공한 수정은 200을 반환한다. `device`에는 수정 직후 Device 전체 스냅샷이 들어가고 `request_id`는 이번 HTTP 요청 ID다. 기존 생성과 같은 형식의 `Idempotency-Replayed` 응답 헤더를 사용하며 최초 성공은 false, 같은 성공 요청의 재전송은 true다. 새 자원을 생성하지 않으므로 201이나 Location 헤더는 사용하지 않는다.

```json
{
  "device": {
    "schema_version": "v1",
    "device_id": "camera-001",
    "display_name": "1층 출입구 CCTV",
    "device_kind": "CCTV",
    "version": 2,
    "created_at": "2026-09-30T05:00:00Z",
    "updated_at": "2026-09-30T05:45:00Z"
  },
  "request_id": "example-request-id"
}
```

새 수정 명령이 성공하면 version은 정확히 1 증가한다. 현재 이름과 같은 값을 제출해도 버전 조건을 통과한 새 명령은 version을 1 증가시킨다. 클라이언트는 변경할 값이 없으면 수정 요청을 보내지 않을 수 있다. 같은 멱등 요청의 재전송은 추가 증가를 만들지 않는다.

created_at은 유지한다. updated_at은 서버의 UTC 수정 시각으로 기록하되 이전 updated_at보다 과거로 내려가지 않는다. 시각이 같은 경우도 가능하므로 동시 변경 판단에는 timestamp가 아닌 version을 사용한다. 현재 version이 signed bigint 최댓값이면 증가시키지 않고 409 `DEVICE_VERSION_EXHAUSTED`를 반환한다.

## 동시 수정과 재시도

처리 순서는 인증·요청 검증 → 성공한 멱등 요청 조회 → 활성 장치 확인 → expected_version 비교 → 수정과 성공 스냅샷의 원자적 저장이다. 성공 기록이 없는 요청에 대해서만 현재 장치 상태와 버전 조건을 평가한다.

| 상황 | 결과 |
|---|---|
| 현재 version과 expected_version이 같음 | 이름 변경, version+1, 200 |
| 같은 장치·같은 expected_version에 서로 다른 키로 동시 수정 | 한 요청만 성공, 나머지는 409 `DEVICE_VERSION_CONFLICT` |
| 같은 이름이지만 version이 다름 | 409. 값이 같다는 이유로 조건을 무시하지 않음 |
| 같은 주체·메서드·정규 경로·키와 같은 요청 재전송 | 최초 성공 스냅샷을 200으로 재생, 추가 수정 없음 |
| 같은 범위의 키로 다른 이름 또는 expected_version을 제출 | 409 `IDEMPOTENCY_CONFLICT` |
| 성공 이후 다른 요청이 장치를 다시 수정한 뒤 이전 키 재전송 | 이전 키의 최초 성공 스냅샷을 재생하며 현재 장치를 되돌리지 않음 |
| 저장 중 실패 | 장치 변경과 성공 기록을 함께 롤백. 응답이 불확실하면 같은 키·본문으로 재시도 |

멱등 범위는 인증 주체 + PATCH + `/api/v1/devices/`와 유효하게 해석된 device_id로 만든 정규 경로 + 키다. 생성 POST와 수정 PATCH, 서로 다른 장치 경로의 키는 독립이다. 개발 토큰 교체로 인증 주체가 달라지지 않으며 호출자가 헤더로 주체를 지정할 수 없다.

요청 비교는 schema_version·expected_version·display_name을 명시적으로 정규 직렬화해 수행한다. 객체 키 순서와 JSON 문자열의 동등한 이스케이프는 무시하지만 문자열 내용과 버전 값은 보존한다. 키 원문 대신 해시를 저장하고 성공 스냅샷은 자동 만료시키지 않는다. 실패 응답은 성공 기록으로 저장하지 않는다.

응답 유실·타임아웃·503이 발생했으면 먼저 **같은 키와 같은 본문**으로 재시도한다. 409 버전 충돌이면 GET으로 현재 장치를 다시 읽고 변경 내용을 검토한 뒤 새 expected_version과 새 키로 별도 요청한다. 서버가 자동으로 최신 버전에 맞춰 덮어쓰지 않는다.

멱등 재생은 과거 성공의 확인이다. 현재 장치 상태가 필요하면 GET을 사용한다. 기존 장치 생성 POST의 멱등 재생도 최초 생성 스냅샷을 유지하므로 이름 수정 후 예전 생성 키를 재전송해도 이름을 되돌리지 않으며 최신 이름을 반환한다고 가정하지 않는다.

## 오류 계약

기존 `error: {code, message, details}`와 request_id 응답 구조를 유지한다. 버전 충돌에 새로운 장치 스냅샷 필드를 추가하지 않으며 최신 버전은 GET으로 다시 조회한다.

| HTTP | code | 조건 |
|---|---|---|
| 400 | `QUERY_INVALID` | 쿼리가 있거나 잘못 인코딩됨 |
| 400 | `PRECONDITION_HEADER_UNSUPPORTED` | 지원하지 않는 조건 헤더를 제출 |
| 400 | `IDEMPOTENCY_KEY_INVALID` | 키 누락·중복·형식 오류 |
| 400 | `INVALID_JSON` | JSON 구문·타입·정수 토큰/표현 범위 오류, 중복/알 수 없는 필드, null, 후행 JSON |
| 401 | `UNAUTHORIZED` | 인증 실패 |
| 404 | `DEVICE_NOT_FOUND` | 성공 재생이 아닌 새 요청에서 장치 없음 또는 삭제 상태 |
| 405 | `METHOD_NOT_ALLOWED` | 구현 후 장치 단건 경로의 GET/PATCH 외 메서드. Allow는 GET, PATCH |
| 409 | `DEVICE_VERSION_CONFLICT` | expected_version 불일치 |
| 409 | `IDEMPOTENCY_CONFLICT` | 같은 범위의 키에 다른 유효 요청 |
| 409 | `DEVICE_VERSION_EXHAUSTED` | 버전 최댓값에서 증가 불가 |
| 413 | `BODY_TOO_LARGE` | 64 KiB 초과 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | application/json이 아님 |
| 422 | `CONTRACT_INVALID` | 필수 필드 누락, 잘못된 schema_version/경로 ID, 0·음수 expected_version, 이름 길이·공백·NUL 오류 |
| 503 | `REGISTRY_DISABLED` / `DATABASE_UNAVAILABLE` | 저장소 미설정 / DB·트랜잭션 이용 실패 |

여러 요청 오류가 있으면 기존 인증 계층 다음에 메서드, 쿼리, 경로 ID, 조건 헤더, 멱등 키, Content-Type·JSON 디코딩, 필드 의미 순서로 검사한다. 저장소 사용 여부와 상태 검사는 유효한 요청 이후다. 성공 재생이 없으면 장치 없음/삭제 여부를 버전 충돌보다 먼저 판단하고, 일치한 버전이 최댓값인지 확인한다.

## 저장소 및 배포에 미치는 영향

현재 스키마 3의 devices에는 version·updated_at이 있지만 runtime 역할은 SELECT/INSERT만 허용한다. 또한 기존 device_create_requests는 POST 전용 제약이 있으므로 수정 요청의 기록으로 재사용하지 않는다.

07-B에서 별도의 `camera.device_update_requests`와 추가 마이그레이션으로 스키마 4를 구현했다. 과거 마이그레이션 파일은 수정하지 않는다. 장치 수정과 성공 응답 기록을 한 트랜잭션으로 확정하고, 같은 멱등 범위의 동시 요청을 직렬화한 뒤 장치 행의 버전 조건을 원자적으로 확인한다. 서로 다른 키의 동시 수정도 둘 다 성공하지 않도록 한다.

runtime 역할에는 장치 표시 이름·version·updated_at 갱신에 필요한 최소 UPDATE 권한과 새 요청 기록 테이블의 SELECT/INSERT 권한을 추가한다. device_id·device_kind·created_at·deleted_at 변경, 다른 테이블 UPDATE 및 DELETE/DDL 권한은 주지 않는다. 이 권한 구분은 07-B의 실제 PostgreSQL 17.11 검사에서 확인했다. 07-C 서버 격리 검사에서는 HTTP 응답과 함께 재확인한다.

기존 06 이미지의 readiness는 정확한 스키마 3 이력을 요구한다. 따라서 앞으로 스키마 4를 적용하면 **06 단계의 이미지 교체만으로 복귀하는 절차를 그대로 사용할 수 없다.** 실제 전환·호환성·실패 복구는 코드와 스키마 4가 준비된 뒤 별도 단계에서 검증한다. 새로 승인된 데이터를 잃는 자동 DB 복원은 허용하지 않는다. 07-A~07-C 파일 적용과 격리 검사는 운영 DB·권한·이미지를 변경하지 않는다.

## 후속 구현 완료 기준

저장소 구현에서는 동일 버전 동시 수정의 단일 성공, 동일 키 동시 재생, 다른 본문 충돌, 이름과 version/updated_at만 변경, 장치·자식 소스·기존 생성 멱등 응답 보존, 응답 기록 실패 시 전체 롤백을 확인한다. 재시작·토큰 교체 후에도 멱등 기록이 유지돼야 한다.

HTTP 구현에서는 요청 순서·오류 코드·정수 토큰·중복 키·미지원 필드·권한·본문 제한을 확인한다. JSON Schema 검사는 파싱된 값의 형태만 검증하며 중복 키와 `1.0`/`1e0` 같은 원문 표기, 요청 헤더·상태·동시성·트랜잭션을 검증하지 않는다. 이 제한을 계약 검사 통과와 구분한다.

현재 07-C의 HTTP 코드와 로컬 검증을 완료했고 서버 격리 검사 결과를 기다린다. 통과 후 **07-D1 운영 전환 사전점검**을 다음 작은 단위로 진행한다. 마이그레이션·이미지 전환·복구 검증은 이후 단계로 나눈다.
