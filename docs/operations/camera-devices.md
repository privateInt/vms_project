# 장치 등록·조회·이름 수정·논리 삭제 API

현재 운영 camera는 09 인수 기준의 `0.6.0-source-delete`·스키마 6이다. 장치/소스 등록·조회·목록·이름 수정과 소스 논리 삭제의 운영 인수를 완료했다. 10-B 장치 삭제 저장소·스키마 7은 PostgreSQL 17.11 서버 격리 검사를 통과했다. 10-C 개발 코드 `0.7.0-device-delete`는 장치 DELETE HTTP를 추가하며 서버 HTTP 격리 인수와 운영 활성화는 대기 중이다. 실제 장치 연결·SourceSession·영상 입력은 미구현이다.

소스 API는 [별도 안내](camera-sources.md), 장치 수정은 [수정 계약](../contracts/camera-device-update.md), 삭제는 [장치 삭제 계약](../contracts/camera-device-delete.md), 최신 검증은 [10-C 기록](../progress/20261002-step10c-device-delete-http.md)을 따른다. 개발 인증은 공유 주체 토큰이며 사용자별 권한·테넌트 IAM이 아니다.

## 경로와 데이터

| 메서드·경로 | 결과 |
|---|---|
| POST /api/v1/devices | 새 장치 또는 동일 성공 요청의 최초 스냅샷. 201, Location, Idempotency-Replayed |
| GET /api/v1/devices/{device_id} | 활성 장치 200, 없음/삭제됨 404 |
| PATCH /api/v1/devices/{device_id} | expected_version 조건의 이름 수정 또는 최초 스냅샷 재생. 200, Idempotency-Replayed |
| DELETE /api/v1/devices/{device_id} | 미삭제 자식이 없는 장치의 논리 삭제 또는 최초 영수증 재생. 200, Idempotency-Replayed. 10-C 코드·운영 활성화 대기 |
| GET /api/v1/devices | 삭제 행을 제외한 items/next_cursor/request_id. limit 기본 50, 1~200 |

생성 입력은 schema_version=v1·device_id·display_name·device_kind 네 문자열이다. 종류는 CCTV/SMART_GLASSES/TEST다. 정확한 필드명·중복 키·미지원 필드·타입·null을 검사한다. 이름의 앞뒤 공백은 보존하되 공백만 있는 이름과 NUL은 거부한다. 본문은 64 KiB·application/json이며 Bearer 인증이 필요하다.

생성/조회/수정 응답은 device와 request_id다. 장치에는 생성 필드·version·UTC created_at/updated_at이 있다. 생성 version=1이고 새 수정 또는 삭제 성공마다 정확히 1 증가한다. 장치 ID validate는 일반 ID다. 단건 Allow는 GET, PATCH, DELETE다.

목록은 C 정렬의 ID 오름차순이다. 동시 삽입에 대한 스냅샷 일관성은 제공하지 않는다. 필터는 없고 알 수 없는/중복/빈 query는 400이다. 불투명 cursor는 목록 버전과 마지막 ID를 담으며 접근 권한을 부여하는 서명 토큰이 아니다. 후속 페이지가 없으면 next_cursor=null이고 삭제된 장치 ID의 cursor도 그 ID 이후부터 계속 조회한다.

실행 명세 원본은 camera api/openapi.json의 DeviceCreate/DeviceUpdate/DeviceDelete·Device/DeviceResponse/DeviceList·DeviceDeletion/DeviceDeleteResponse다. planned 계약·예제는 설계 기준으로 보존한다.

## 멱등 처리와 표시 이름 수정

POST/PATCH/DELETE는 단일 Idempotency-Key가 필요하다. 길이 1~128의 공백 없는 ASCII 표시 문자이며 범위는 인증 주체·메서드·정규 경로·키다. 고정 주체 development:shared-token은 토큰 교체 후에도 유지하며 클라이언트 사용자 식별 헤더를 신뢰하지 않는다. IAM 전환 시 기존 기록의 범위를 별도 결정한다.

키와 정규 요청의 SHA-256을 저장한다. 동등한 객체 순서·문자열/경로 escape는 같은 요청이며 의미 있는 값·공백은 보존한다. 같은 성공 키·본문은 최초 결과를 재생하고 다른 유효 본문은 IDEMPOTENCY_CONFLICT다. 과거 POST/PATCH 성공은 삭제 뒤에도 최초 스냅샷을 재생하며 행을 복원하지 않는다. 같은 ID를 새 키로 생성하면 삭제 이력이 있어도 DEVICE_EXISTS다. request_id는 매 요청 새로 생성한다.

PATCH 본문은 schema_version=v1·expected_version·display_name이다. expected_version은 정확한 signed int64 JSON 정수 토큰이며 실수·지수·문자열을 거부한다. 단건 수정/삭제에는 쿼리(빈 물음표 포함)와 If-Match·If-None-Match·If-Unmodified-Since를 받지 않는다. 새 수정은 같은 이름이어도 version을 증가시키고 생성 시각·종류·ID·자식/프로필은 보존한다. 성공 200이며 Location은 없다.

version 불일치/소진은 각각 DEVICE_VERSION_CONFLICT/DEVICE_VERSION_EXHAUSTED다. DB/성공 기록 실패는 DATABASE_UNAVAILABLE이며 데이터 변경과 기록을 함께 롤백한다. 성공 기록만 저장하며 자동 만료시키지 않는다. 응답 유실·타임아웃·503에는 원래 키·본문으로 재시도한다. version 충돌에는 현재 정보를 읽고 새 version·새 키로 요청한다.

## 장치 논리 삭제 — 10-C

DELETE 본문은 schema_version=v1과 expected_version 두 필드다. 본문 누락은 INVALID_JSON이며 무조건 삭제로 해석하지 않는다. 중복/이스케이프 중복 키·타입·실수/지수·정수 범위 초과·무효 UTF-8·대소문자/미지원 필드·후행 JSON을 거부한다. 누락·0/음수·v1 이외 버전은 의미 오류다. force/cascade/purge/restore·장치/자식/사용 상태를 본문에서 받지 않는다.

새 요청은 성공 이력 확인 뒤 소스 생성과 같은 장치별 advisory 잠금·장치 행 잠금·version/소진·미삭제 자식·신뢰된 사용 관계 guard를 확인한다. 미삭제 자식이 하나라도 있으면 DEVICE_HAS_ACTIVE_SOURCES다. 각 소스를 소스 DELETE로 먼저 삭제해야 한다. 서버가 검토한 등록 전용 릴리스에서는 장치/소스 삭제 공통 capability 목록이 정확히 일치할 때만 미사용을 반환한다. 미확인 사용/정책은 DEVICE_USAGE_UNAVAILABLE, 관리 사용 중은 DEVICE_IN_USE다. 외부 장비 사용을 감지하는 정책은 아니다.

최초·재생 성공은 200이며 deletion의 schema_version/device_id/version/deleted_at과 DELETED/runtime_verified=false/request_id만 반환한다. no-store·X-Request-ID와 Idempotency-Replayed false/true를 사용하고 Location은 없다. 장치 tombstone·version+1·같은 deleted_at/updated_at·영수증은 한 트랜잭션이다. 자식/프로필/기존 기록·장치 종류/이름/생성 시각은 보존한다.

새 GET/PATCH/DELETE는 삭제 장치에 404다. 새 장치 목록에서는 제외하고 해당 부모의 새 소스 목록은 빈 결과다. 삭제 후 새 소스 생성은 DEVICE_UNAVAILABLE이며 소스/프로필/성공 기록을 남기지 않는다. 과거 장치/소스 POST/PATCH/DELETE는 최초 결과를 재생하며 장치/자식을 복원하지 않는다. 삭제는 등록 상태 변경이고 장비 전원 종료·미디어/녹화 종료·영구 삭제 완료가 아니다.

## DB 연결·계정·운영 활성화 경계

CAMERA_DATABASE_URL과 CAMERA_DATABASE_URL_FILE이 모두 없으면 등록 기능은 disabled이고 관련 API는 REGISTRY_DISABLED다. 기존 validate API는 동작한다. 설정이 비었거나 두 URL 설정이 같이 있거나 접속/이력/권한 검사에 실패하면 시작을 중단한다. 파일 비밀을 읽고 API 시작에서 DDL/GRANT를 자동 수행하지 않는다.

개발 코드가 요구하는 스키마는 7이다. SQL 0001~0007과 체크섬은 변경하지 않는다. 빈 시험 DB applied=7/version=7, 6→7은 1/7, 정상 재적용은 0/7이다. 검증된 운영은 스키마 6이므로 임의로 새 코드를 빌드·재시작하지 않는다.

runtime은 schema USAGE·마이그레이션 이력 SELECT·등록/성공 기록 테이블 SELECT/INSERT와 devices 및 video_sources의 display_name/version/updated_at/deleted_at 열 UPDATE만 사용한다. 식별자·종류·생성 시각·프로필 수정·테이블 전체 UPDATE·물리 DELETE·TRUNCATE·DDL을 허용하지 않는다. 장치 DELETE용 새 권한은 device_delete_requests SELECT/INSERT와 devices.deleted_at UPDATE다.

DB 모드 readiness는 camera_registry 범위로 정확한 이력/권한을 읽기 전용 확인하고 실패 시 503이다. 미설정 모드는 http_api_foundation이며 liveness는 프로세스 상태다. business_runtime_ready는 false다. device_registry/device_update/device_delete는 DB 구성에 따라 implemented/disabled다.

서버 격리 검사 scope는 camera_device_delete_http_native_postgresql이다. 임시 전용 DB에서 전체 race/vet와 실제 API/native 권한·롤백·재시도·응답 보존을 검사하고 운영 자원을 사용하지 않는다. 패치 적용은 서비스를 재시작하거나 운영 DB를 변경하지 않는다. 서버 HTTP 격리 인수 뒤 사전점검·리허설·운영 전환을 별도 단위로 진행한다. 실제 활성화 전에는 검증된 09 운영 이미지를 유지한다.
