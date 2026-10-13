# 영상 소스 표시 이름 수정 계약 — 단위 08-A

상태: 08-B 서버 저장소 검증 완료 · 08-C HTTP 구현·로컬 검증 완료 · 새 HTTP 서버 격리 검사·운영 활성화 대기 · 2026-10-01

## 범위와 계약 원본

08의 첫 수정 범위는 VideoSource의 `display_name` 하나다. 소스가 제공하는 영상 채널의 표시 이름을 바꾸며, 부모 장치의 이름을 바꾸는 07 기능과 구분한다. 작은 작업 단위 원칙에 따라 스트림 선언이나 실제 연결에 영향을 줄 수 있는 프로필·전송 설정 변경은 별도 단위로 남긴다.

| 구분 | 이번 계약 |
|---|---|
| 변경 가능한 입력 | `display_name` |
| 생성 후 불변 식별·관계 | `source_id`, `device_id`, `channel_key` |
| 이번 수정에서 유지하는 선언 | `transport`, `input_mode`, `motion_mode`, `profiles` 전체 |
| 서버 관리 값 | `version`은 성공한 새 수정마다 1 증가, `updated_at` 갱신, `created_at` 유지 |
| 부모·다른 소스 | 장치 및 형제 소스의 값·버전·수정 시각을 변경하지 않음 |
| 연결·실제 영상 | 연결 URL·자격증명·SourceSession·영상 재연결을 다루지 않음 |

프로필의 ID·배열 순서·코덱·크기·FPS를 그대로 유지한다. 내부 `primary_profile_id`와 프로필의 position도 바꾸지 않는다. 프로필을 추가·삭제·재정렬하거나 선언과 실제 협상 결과를 혼합하지 않는다. `profiles`를 기존 값 그대로 보내더라도 이 요청의 허용 필드가 아니므로 거부한다.

기계 판독용 요청 계약은 `src/platform/camera/api/planned/source-update.schema.json`, 예제는 같은 폴더의 `source-update.examples.json`이다. 응답은 현재 실행 OpenAPI의 SourceResponse/VideoSource 구조를 재사용한다. 08-C에서 실행 OpenAPI에 소스 PATCH와 SourceUpdate를 추가했다. `api/planned`는 최초 설계 기준으로 보관한다.

현재 운영 API는 `0.4.0-device-update`, DB는 스키마 4다. 장치 PATCH는 운영 중이며 소스 PATCH는 08-C의 `0.5.0-source-update` 코드에 구현됐다. 아직 전환하지 않은 운영 0.4 이미지에서는 소스 PATCH가 405다. 파일 패치만으로 운영 이미지·DB를 바꾸지 않는다.

## 요청

| 항목 | 규칙 |
|---|---|
| 메서드·경로 | `PATCH /api/v1/sources/{source_id}` |
| 인증 | 기존 Bearer 인증과 안정된 개발용 공통 인증 주체 |
| Content-Type | `application/json`. 기존 장치 수정과 같은 전용 요청 형식 |
| 경로 ID | 기존 ASCII 1~64자 식별자 규칙. 본문에는 ID를 넣지 않음 |
| 쿼리 | 허용하지 않음 |
| Idempotency-Key | 단일 필수 헤더. 1~128자 ASCII 표시 문자(0x21~0x7e) |
| 본문 크기 | 기존 64 KiB 제한 |
| 동시 수정 조건 | 본문의 `expected_version`. 조건 헤더 If-Match·If-None-Match·If-Unmodified-Since는 400 |

```json
{
  "schema_version": "v1",
  "expected_version": 1,
  "display_name": "1층 출입구 영상"
}
```

세 필드 모두 필수다. display_name은 유효한 UTF-8 문자열이며 Unicode 코드 포인트 기준 1~128자, 공백만인 이름과 NUL은 거부한다. 기존 SourceCreate 및 장치 수정과 같은 이름 규칙을 적용한다. 앞뒤 공백을 임의로 제거하거나 Unicode 문자열을 정규화하지 않는다.

expected_version은 **소스 GET/목록 응답의 version**이다. 부모 장치의 version을 사용하지 않는다. 1~9223372036854775807 범위의 정확한 signed 64-bit JSON 정수 토큰을 받는다. 문자열, 실수 표기 1.0, 지수 표기 1e0, null·bool과 범위 초과는 디코딩 단계에서 거부한다. 0·음수 정수는 의미 검증 오류다.

잘못된 필드 대소문자, 중복 JSON 키, 알 수 없는 필드, null·후행 JSON을 거부한다. 누락 또는 null인 이름을 ‘기존 값 유지’나 ‘삭제’로 해석하지 않는다. JSON Patch·Merge Patch는 지원하지 않는다.

정확한 소문자 ID `validate`는 기존 `POST /api/v1/sources/validate`의 예약 경로다. 이 경로를 일반 소스 수정으로 처리하지 않는다. 유효한 인증의 PATCH는 기존 검증 경로에서 405와 Allow: POST를 반환한다. URL에서 같은 예약 세그먼트로 해석되는 이스케이프 표기도 같은 원칙을 따른다. `Validate`, `validate-1`은 예약 값과 다르다.

## 성공 응답과 상태

최초 수정 성공은 200이다. 본문은 기존 SourceResponse와 같이 `source`, `registration_state: REGISTERED`, `runtime_verified: false`, `request_id`를 포함한다. source에는 수정 직후 VideoSource 전체 정보와 등록 순서의 profiles를 반환한다. 새 자원을 만들지 않으므로 201이나 Location 헤더를 사용하지 않는다.

Idempotency-Replayed는 최초 성공 false, 저장된 성공 재생 true다. request_id는 현재 HTTP 요청의 X-Request-ID와 일치하며 재시도마다 달라질 수 있다. 예제 파일에 프로필 2개를 포함한 전체 성공 응답을 둔다.

새 명령이 성공하면 소스 version은 정확히 1 증가한다. 현재와 같은 이름을 제출해도 새 키·일치한 expected_version을 사용하는 새 명령이면 증가한다. 같은 성공 요청 재생은 증가시키지 않는다. created_at은 보존하며 updated_at은 서버 UTC로 기록하되 이전 updated_at보다 과거로 내려가지 않는다. version이 최댓값이면 증가하지 않고 409 SOURCE_VERSION_EXHAUSTED다.

새 요청의 존재·삭제 여부는 대상 소스를 기준으로 판정한다. 부모의 표시 이름·version 변화는 소스 이름 수정 충돌이 아니다. 부모 재지정이나 신규 소스 생성이 아니므로 생성 API의 DEVICE_UNAVAILABLE 검사를 새 수정 조건으로 추가하지 않는다. 기존 부모 FK와 ‘자식 소스가 있으면 장치 삭제 거부’ 원칙은 유지한다. 소스/장치 삭제·복원 기능은 이번 범위 밖이다.

## 동시 수정과 재시도

처리 순서는 인증·요청 검증 → 성공한 멱등 요청 조회 → 활성 소스 확인 → 소스 expected_version 비교 → 버전 소진 확인 → 수정·전체 성공 스냅샷의 원자적 저장이다. 성공 재생은 현재 버전·삭제 상태를 다시 조건으로 삼지 않으며, 응답을 재생할 때 현재 데이터를 수정하거나 복원하지 않는다.

| 상황 | 결과 |
|---|---|
| 현재 소스 version과 expected_version이 일치 | 이름 변경과 version+1, 200 |
| 같은 소스·같은 version에 다른 키로 동시 수정 | 하나만 성공, 나머지는 409 SOURCE_VERSION_CONFLICT |
| 이름은 같지만 version이 다름 | 409 SOURCE_VERSION_CONFLICT |
| 같은 멱등 범위·같은 요청 재전송 | 최초 성공의 전체 source 스냅샷과 프로필을 200으로 재생 |
| 같은 범위의 키에 다른 이름 또는 expected_version | 409 IDEMPOTENCY_CONFLICT |
| 이후 다른 수정이 성공한 뒤 과거 키 재전송 | 과거 성공을 재생하며 최신 소스는 유지 |
| 수정 또는 응답 기록 저장 실패 | 이름·version·updated_at·성공 기록을 함께 롤백 |

멱등 범위는 인증 주체 + PATCH + `/api/v1/sources/`와 해석된 유효 source_id로 만든 정규 경로 + 키다. 같은 ID를 나타내는 URL 이스케이프는 같은 범위다. 서로 다른 소스, 소스 생성 POST, 장치 PATCH의 키는 각각 독립이다. 개발 토큰 교체로 공통 인증 주체가 바뀌지 않으며 호출자가 주체를 임의 지정할 수 없다.

schema_version·expected_version·display_name을 명시적으로 정규 직렬화해 비교한다. 객체 키 순서·동등한 JSON 문자열 이스케이프는 무시하고 문자열 내용과 버전 값은 보존한다. 키 원문 대신 해시를 저장하며 성공 스냅샷은 자동 만료시키지 않는다. 실패 응답은 성공 기록으로 저장하지 않는다.

응답 유실·타임아웃·503에는 같은 키·같은 본문으로 재시도한다. 버전 충돌이면 GET으로 현재 소스를 읽고 변경을 검토한 뒤 새 expected_version·새 키로 요청한다. 서버는 최신 버전에 맞춰 자동으로 덮어쓰지 않는다.

생성 POST의 기존 멱등 응답은 최초 생성 당시 이름·프로필·version=1을 유지한다. 수정 후 생성 키를 재전송해도 최신 이름으로 응답 기록을 바꾸거나 소스 이름을 되돌리지 않는다. 최신 상태는 GET/목록으로 확인한다. 이름 수정은 ID 정렬·device_id 필터·cursor 경계를 바꾸지 않으며 페이지 간 스냅샷을 보장하지 않는 기존 목록 규칙도 유지한다.

## 오류 계약

기존 error: {code, message, details}와 request_id 구조를 사용한다. 버전 충돌 응답에 새 자원 스냅샷을 추가하지 않는다.

| HTTP | code | 조건 |
|---|---|---|
| 400 | QUERY_INVALID | 쿼리 제출·잘못된 쿼리 인코딩 |
| 400 | PRECONDITION_HEADER_UNSUPPORTED | 지원하지 않는 조건 헤더 |
| 400 | IDEMPOTENCY_KEY_INVALID | 키 누락·중복·형식 오류 |
| 400 | INVALID_JSON | 구문·타입·정수 토큰/범위 오류, 중복/알 수 없는 필드, null·후행 JSON |
| 401 | UNAUTHORIZED | 인증 실패 |
| 404 | SOURCE_NOT_FOUND | 성공 재생이 아닌 새 요청에서 소스 없음·삭제 상태 |
| 405 | METHOD_NOT_ALLOWED | 구현 후 일반 소스 단건 경로의 GET/PATCH 외 메서드. Allow: GET, PATCH |
| 409 | SOURCE_VERSION_CONFLICT | expected_version 불일치 |
| 409 | IDEMPOTENCY_CONFLICT | 같은 범위의 키에 다른 유효 요청 |
| 409 | SOURCE_VERSION_EXHAUSTED | 일치한 version이 최댓값이어서 증가 불가 |
| 413 | BODY_TOO_LARGE | 64 KiB 초과 |
| 415 | UNSUPPORTED_MEDIA_TYPE | application/json이 아님 |
| 422 | CONTRACT_INVALID | 필수 필드 누락, schema_version/경로 ID 오류, 0·음수 version, 이름 길이·공백·NUL 오류 |
| 503 | REGISTRY_DISABLED / DATABASE_UNAVAILABLE | 저장소 미설정 / DB·트랜잭션 이용 실패 |

예약 validate 경로의 메서드 처리는 앞의 예외 규칙을 따른다. 일반 경로의 여러 오류는 기존 인증 계층 다음에 메서드, 쿼리, 경로 ID, 조건 헤더, 멱등 키, Content-Type·JSON 디코딩, 필드 의미 순으로 검사한다. 저장소 검사는 유효한 요청 이후이며, 성공 기록이 없으면 소스 없음/삭제 → 버전 충돌 → 버전 소진 순으로 판단한다.

## 저장소·배포 영향과 후속 완료 기준

운영 스키마 4의 runtime 역할은 video_sources에 SELECT/INSERT만 가지며 장치에만 제한된 열 UPDATE가 있다. 08-B는 별도 `camera.source_update_requests`와 신규 마이그레이션 0005로 스키마 5를 구현했다. 운영 반영은 후속 단계다. 기존 POST 전용 source_create_requests와 장치 PATCH 기록을 재사용하거나 과거 마이그레이션을 수정하지 않는다.

필요한 추가 권한은 video_sources의 display_name·version·updated_at 열 UPDATE와 source_update_requests의 SELECT/INSERT다. 프로필 테이블·불변 소스 필드·삭제/DDL 권한을 추가하지 않으며 기존 장치 수정 권한은 유지한다. 소스 행의 버전 조건과 이름 변경, 프로필을 포함한 응답 스냅샷 저장은 같은 트랜잭션에서 확정해야 한다.

08-B 완료 기준은 동일 키/서로 다른 키의 동시성, 충돌·최댓값·tombstone, 실제 runtime 권한, 성공 기록 저장 실패 시 전체 롤백, 재시작·토큰 교체 후 재생, 부모/형제 소스·프로필/순서·primary_profile_id·기존 POST 스냅샷·장치 PATCH 보존이다. 소스 행을 읽은 뒤 수정하는 사이의 경쟁을 방지해야 한다.

08-C는 HTTP 요청 경계·상태 코드·헤더, 정확한 정수 토큰, 중복 키·미지원 필드, 예약 validate 경로와 기존 목록 cursor/필터 보존을 구현·로컬 검증했다. 소스 저장과 HTTP 연결을 마친 뒤 별도 격리 이미지 검증과 운영 전환으로 나눈다.

07 이미지의 readiness는 정확한 스키마 4 이력을 요구하므로 스키마 5 전환 후 이전 이미지만 되돌리는 복귀 절차를 가정하지 않는다. 후속 배포에서 백업·호환성·복구를 따로 검증하고 새 데이터를 잃는 자동 운영 DB 복원은 사용하지 않는다. 08-A에는 스키마 5 코드나 런타임 변경이 없다.

JSON Schema 검사는 파싱된 값과 예제의 정적 형태만 검증한다. 특히 1.0/1e0처럼 수학적으로 정수인 값의 원문 표기, 중복 키, HTTP 라우팅·헤더·인증·오류 우선순위·재생·동시성·DB 권한·원자성은 이 검사만으로 보장하지 않는다.


## 08-B/08-C 구현 상태

08-B의 저장소·스키마 5·실제 runtime 역할 권한·다중 연결 동시성은 사용자 서버 PostgreSQL 17.11에서 통과했다. [08-B 기록](../progress/20260930-step08b-source-update-storage.md)을 따른다.

08-C는 SourceUpdate의 엄격한 JSON 디코더와 소스 PATCH HTTP 처리를 연결했다. 기존 UpdateSource 트랜잭션·마이그레이션은 변경하지 않았다. 성공은 전체 SourceResponse·200·Idempotency-Replayed로, 실패는 계약의 오류 코드로 매핑한다. 새 HTTP 검증은 [08-C 기록](../progress/20261001-step08c-source-update-http.md)을 따른다. 실제 PostgreSQL의 HTTP 권한 상실 시나리오는 서버 격리 검사 대기이며 운영은 스키마 4를 유지한다.
