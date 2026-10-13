# 소스 등록·조회·표시 이름 수정·논리 삭제

장치·소스 등록·조회·목록·표시 이름 수정은 운영 인수를 마쳤다. 현재 운영 camera는 `0.5.0-source-update`, 스키마는 5다. 09-B 삭제 저장소·스키마 6은 PostgreSQL 17.11 격리 검사를 통과했고, 09-C는 `0.6.0-source-delete` HTTP 코드·격리 검사 전달이다. DELETE 운영 전환은 후속 단계다.

## 경로와 응답

| 경로 | 동작 |
|---|---|
| POST /api/v1/sources | 부모 장치 확인 후 소스·프로필·멱등 응답을 함께 저장. 201 |
| GET /api/v1/sources/{source_id} | 활성 소스와 등록 순서대로 정렬된 프로필 조회. 200 또는 404 |
| GET /api/v1/sources | 활성 소스 목록·커서 페이지·선택적 device_id 필터. 200, 운영 활성화 완료 |
| PATCH /api/v1/sources/{source_id} | 소스 버전 조건으로 표시 이름만 수정. 전체 소스·프로필 응답 200, 운영 활성화 완료 |
| DELETE /api/v1/sources/{source_id} | 등록 전용 논리 삭제·최초 결과 재생 200, 코드 구현·운영 전환 전 |
| POST /api/v1/sources/validate | 기존 SourceSpec 계약 검증 유지. 자원 생성 없음 |

모든 등록·조회·수정 경로에 Bearer 인증을 요구한다. 생성 요청에는 application/json과 본문 64 KiB 제한을 유지한다. 생성 요청에는 Idempotency-Key가 필요하며 불필요한 query는 거부한다. 생성·단건 조회 응답은 `source`, `registration_state: REGISTERED`, `runtime_verified: false`, `request_id`를 포함한다. source에는 생성 입력과 version=1, 서버 UTC created_at/updated_at이 있다. 생성 응답에는 Location과 Idempotency-Replayed 헤더가 있다. 등록 성공이 영상 연결이나 수신 성공을 뜻하지 않는다.

계약 원본은 `src/platform/camera/api/openapi.json`의 SourceCreate/VideoSource/SourceResponse/SourceList다. 예제는 같은 api 폴더의 `examples/source-create-cctv.json`, `examples/source-create-xr.json`이다. 부모 device_id는 실제 등록된 활성 장치여야 한다.

## 목록 조회와 페이지 구분

`GET /api/v1/sources`는 `items`, `next_cursor`, `request_id`를 반환한다. items의 각 항목은 단건 조회의 source와 동일한 VideoSource이며 프로필을 등록 순서대로 포함한다. 소스 삭제 이력은 목록에서 제외한다. 빈 목록은 `items: []`, 마지막 페이지는 `next_cursor: null`이다.

| 쿼리 | 규칙 |
|---|---|
| limit | 생략 시 50, 1~200 |
| device_id | 선택적 부모 장치 ID 일치 필터. 없는 장치이면 빈 목록 |
| cursor | 직전 응답의 next_cursor를 그대로 전달. 없으면 처음부터 |

순서는 `source_id`의 ASCII 오름차순이다. cursor는 소스 목록과 정확한 device_id 필터에 결합한다. 다음 페이지도 동일한 필터를 전달해야 하며, 필터가 없는 목록의 cursor에 필터를 추가하는 것도 허용하지 않는다. limit은 페이지마다 변경할 수 있다. 장치 목록 cursor를 소스 목록에 사용할 수 없다.

잘못된 URL 쿼리, 알 수 없는/중복/빈 파라미터, 범위 밖 limit, 잘못된 ID 또는 cursor, 필터 불일치는 400 QUERY_INVALID다. cursor는 인증 자격 증명이 아니며 클라이언트가 내부 형식을 조립하는 계약을 제공하지 않는다.

한 페이지는 한 SQL 스냅샷으로 소스·프로필을 읽는다. 여러 페이지 전체가 고정 스냅샷은 아니다. 페이지 사이에 추가된 ID가 현재 경계보다 뒤이면 다음 페이지에 나타날 수 있고, 앞이면 처음부터 다시 조회해야 보인다. cursor의 기준 소스가 삭제돼도 다음 ID부터 이어서 조회한다. 총건수·이름 검색·전송 방식 필터는 이번 범위에 포함하지 않는다.

## 입력과 기존 경로의 호환성

SourceCreate는 schema_version, source_id, device_id, channel_key, display_name, transport, input_mode, motion_mode, profiles를 받는다. 장치 종류·ONVIF/PTZ 능력·URL·계정·비밀 참조를 받지 않는다. RTSP/PULL과 WEBRTC/PUSH를 지원하며 장치 종류로 전송 방식을 강제하지 않는다. 프로필 1~8개의 배열 순서를 저장하고 첫 프로필을 내부 primary_profile_id로 사용한다.

기존 `/sources/validate` 경로를 유지하므로 source_id의 정확한 문자열 `validate`는 예약해 422로 거부한다. 이를 허용하면 생성한 소스의 조회 경로가 기존 검증 경로와 충돌한다. 나머지 ID와 channel_key는 기존 ASCII 1~64자 규칙이다. 이름은 비공백·최대 128자·NUL 금지다. 중복 프로필 ID와 범위 오류는 422다. JSON 객체의 중복 키·대소문자가 다른 필드·알 수 없는 필드·null·잘못된 타입은 프로필 내부까지 400으로 거부한다.

## 원자성·멱등·오류

소스 행, 모든 프로필, 성공 응답을 하나의 트랜잭션으로 커밋한다. 프로필 삽입이나 응답 기록이 실패하면 모두 롤백한다. 생성 성공 기록은 단위 05에서 추가한 `0003_source_idempotency.sql` 테이블에 저장하며 기존 0001/0002는 변경하지 않는다.

인증 주체·POST·경로·키를 기준으로 동시 요청을 직렬화한다. 장치 생성과 소스 생성은 같은 키를 사용해도 별개다. 객체 키 순서와 동등한 FPS 숫자 표기는 정규화하고 문자열 값·공백과 배열 순서는 보존한다. 배열 순서를 바꾸면 다른 요청이다. 같은 요청은 원래 source와 시각·버전을 재생하고 request_id만 새로 생성한다. 성공 기록은 자동 만료하지 않는다. 실패한 요청은 키를 소비하지 않으며 같은 키로 재시도할 수 있다.

| 상태 | 코드·의미 |
|---|---|
| 409 | DEVICE_UNAVAILABLE: 부모 없음 또는 삭제 상태 |
| 409 | SOURCE_EXISTS: source_id 중복, 삭제 이력 포함 |
| 409 | SOURCE_CHANNEL_EXISTS: 같은 장치의 channel_key 중복, 삭제 이력 포함 |
| 409 | IDEMPOTENCY_CONFLICT: 같은 주체·경로·키의 다른 요청 |
| 400 | QUERY_INVALID: 목록의 쿼리·cursor·필터 오류 |
| 404 | SOURCE_NOT_FOUND: 소스 없음 또는 삭제 상태 |
| 503 | REGISTRY_DISABLED 또는 DATABASE_UNAVAILABLE |

조회는 한 SQL 문으로 메타데이터와 정렬된 프로필을 같은 스냅샷에서 읽는다. 향후 부모 장치의 소프트 삭제 구현은 source 생성과 동일한 장치 단위 advisory lock `(1447908164, hashtext(device_id))`을 획득하고 자식 소스 유무를 확인해야 한다. 장치 삭제는 아직 구현하지 않았다.

## 표시 이름 수정

PATCH 본문은 schema_version=v1, 소스의 expected_version, display_name 세 필드다. 부모 장치의 버전은 조건에 사용하지 않는다. 표시 이름만 바꾸며 부모·형제 소스·전송 선언·프로필 배열과 내부 primary_profile_id는 유지한다. 쿼리·조건 헤더·미지 필드·중복 키·null·실수/지수 버전 표기는 거부한다. display_name의 공백은 보존하며 Unicode 1~128자·비공백·NUL 금지 규칙을 적용한다.

Idempotency-Key는 단일 필수 헤더다. 성공은 200과 전체 SourceResponse이며 Location은 없다. Idempotency-Replayed는 최초 false, 재생 true다. 같은 이름을 새 명령으로 수정해도 version은 1 증가하지만 같은 성공 재생은 증가하지 않는다. 이후 변경이 있어도 과거 키는 최초 성공 스냅샷을 재생하며 현재 소스를 되돌리지 않는다. 기존 POST 성공 스냅샷과 장치 PATCH는 독립적으로 유지한다.

새 명령은 없는/삭제된 소스에 404 SOURCE_NOT_FOUND, 버전 불일치에 409 SOURCE_VERSION_CONFLICT, 같은 키의 다른 요청에 409 IDEMPOTENCY_CONFLICT, 버전 최댓값에 409 SOURCE_VERSION_EXHAUSTED를 반환한다. 저장소 실패는 503이며 같은 키·같은 본문으로 재시도한다. 버전 충돌이면 GET 후 새 버전·새 키로 요청한다. 전체 입력·오류 우선순위는 [소스 수정 계약](../contracts/camera-source-update.md)을 따른다.

새 코드의 일반 소스 단건 경로 지원 메서드는 GET, PATCH, DELETE다. 예약된 정확한 validate 경로와 동등한 URL 이스케이프는 기존 검증 API를 사용하며 PATCH·DELETE는 405/Allow: POST다.

## 논리 삭제

DELETE 본문은 schema_version=v1과 expected_version 두 필드이며 단일 Idempotency-Key가 필요하다. 등록 전용 릴리스의 서버 정책에서만 새 삭제를 허용한다. 소스의 version을 1 증가시키고 같은 UTC 시각을 deleted_at/updated_at에 남기며 프로필·부모·형제·과거 이력·ID/채널 예약은 유지한다. GET은 404, 새 목록은 해당 소스를 제외한다. 사용 상태·키·본문·오류 순서는 [삭제 계약](../contracts/camera-source-delete.md)을 따른다.

성공 응답은 SourceResponse 대신 deletion(schema_version, source_id, version, deleted_at), registration_state=DELETED, runtime_verified=false, request_id를 포함한다. 최초·재생 모두 200이고 Idempotency-Replayed는 false/true다. Location은 없으며 Cache-Control은 no-store다. 같은 DELETE 성공 키·본문은 재시작 후에도 동일 결과를 반환하고 새 요청 ID를 발급한다. 같은 키의 다른 본문은 409, 삭제 후 새 키는 404다. 과거 POST/PATCH 성공 응답을 재생해도 삭제된 소스는 되살아나지 않는다.

## 권한·반영 경계

새 코드의 readiness는 정확한 스키마 6과 등록·조회·수정·논리 삭제 최소 권한을 요구한다. 추가 삭제 권한은 video_sources.deleted_at 열 UPDATE와 source_delete_requests의 SELECT/INSERT다. 프로필 변경·물리 DELETE·DDL 권한은 부여하지 않는다. 자세한 기준은 [저장소 안내](camera-storage.md)를 따른다.

현재 운영 08 이미지는 스키마 5를 요구한다. 09-C 패치는 운영 DB·이미지를 전환하거나 서비스를 재시작하지 않는다. 서버 격리 검사 결과를 받은 뒤 09-D1 사전점검부터 진행한다. 운영 스키마 6 전환·복구는 후속 리허설을 통과해야 하며 자동 운영 DB 복원을 사용하지 않는다.
