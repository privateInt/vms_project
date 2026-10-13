# 카메라 저장소 기반

PostgreSQL 저장소·마이그레이션과 격리 검사 안내다. 현재 운영은 camera `0.6.0-source-delete`·스키마 6이며 소스 논리 삭제까지 인수를 마쳤다. 10-B는 장치 논리 삭제 저장소·스키마 7과 격리 검사를 추가한다. 10-B 서버 격리 인수를 완료했고 10-C는 장치 DELETE HTTP를 연결했다. 서버 HTTP 격리 인수와 운영 전환은 대기 중이다. [09 운영 인수](../progress/20261001-step09-server-acceptance.md), [10-B 기록](../progress/20261001-step10b-device-delete-storage.md), [10-C 기록](../progress/20261002-step10c-device-delete-http.md), [장치 삭제 계약](../contracts/camera-device-delete.md)을 따른다.

새 코드의 readiness는 스키마 7·device_delete_requests SELECT/INSERT·devices.deleted_at UPDATE를 요구한다. 파일 패치로 운영 DB를 변경하지 않는다. 스키마 6의 검증된 운영 이미지를 유지하고 이번 코드는 별도 격리 검사에만 사용한다.

## 구성

| 경로 | 역할 |
|---|---|
| src/platform/camera/internal/storage/store.go | 명시적 URL 접속, 풀, 트랜잭션, 안전한 오류 코드 |
| src/platform/camera/internal/storage/device_update.go | 장치 이름 수정·버전 조건·성공 응답 기록 |
| src/platform/camera/internal/storage/source_update.go | 소스 이름 수정·버전 조건·프로필을 포함한 성공 응답 기록 |
| src/platform/camera/internal/storage/source_delete.go | 소스 논리 삭제·사용 검사 경계·삭제 결과 재생 |
| src/platform/camera/internal/storage/device_delete.go | 장치별 잠금·활성 자식 검사·장치 논리 삭제·성공 결과 재생 |
| src/platform/camera/internal/storage/migrate.go | SQL 순서·해시·이력 확인과 트랜잭션 적용 |
| src/platform/camera/internal/storage/migrations | 변경 불가 SQL 0001~0007 |
| src/platform/camera/cmd/camera-migrate | 명시적 apply 옵션을 요구하는 일회성 마이그레이션 명령 |
| src/infra/postgresql/compose.test.yaml | 임시 PostgreSQL 17.11·Go 검사 컨테이너 |
| src/infra/tools/test_camera_storage.py | 고유한 검사 프로젝트 생성·실행·정리 |

## 수정 트랜잭션과 재생

`UpdateDevice`와 `UpdateSource`는 인증 주체·HTTP 메서드·정규 경로·멱등 키 범위별로 advisory lock을 사용한다. 기존 성공 기록이 있으면 요청 해시를 확인하고 최초 성공 스냅샷을 반환한다. 현재 행을 이전 상태로 되돌리거나 version을 다시 증가시키지 않는다. 장치 PATCH·소스 PATCH·소스 POST의 기록은 독립적이다.

새 소스 수정은 삭제되지 않은 video_sources 행을 FOR UPDATE로 잠그고 expected_version을 확인한다. display_name·version+1·역행하지 않는 updated_at과 성공 기록을 같은 트랜잭션으로 저장한다. 실패하면 이름 변경과 기록을 함께 취소한다. 같은 이름을 새 명령으로 수정해도 version은 증가한다. int64 최댓값에서는 변경하지 않고 고정 오류를 반환한다.

성공 스냅샷은 소스와 등록 순서의 프로필을 하나의 SQL 스냅샷으로 읽어 저장한다. 부모 장치·형제 소스·불변 필드·프로필·primary_profile_id는 수정하지 않는다. 향후 프로필 변경도 같은 소스 행 잠금을 사용해야 한다. 기존 POST 성공 재생은 최초 생성 당시 이름·version·프로필을 유지하며 목록의 ID 정렬·부모 필터·cursor 경계를 보존한다.

## 스키마와 최소 권한

`0006_source_delete.sql`은 camera.source_delete_requests를, `0007_device_delete.sql`은 camera.device_delete_requests를 추가한다. 기존 0001~0007의 SQL과 체크섬은 유지한다. 스키마 7 코드 기준으로 빈 임시 DB 적용은 applied=7/version=7, 스키마 6에서 업그레이드는 1/7, 정상 재적용은 0/7이다. 이력이나 체크섬을 임의로 변경하지 않는다.

runtime 역할에는 등록·조회 테이블과 성공 기록 테이블의 SELECT/INSERT를 부여한다. UPDATE는 devices의 display_name·version·updated_at·deleted_at, video_sources의 display_name·version·updated_at·deleted_at 열로 제한한다. 테이블 전체 UPDATE·불변 필드·프로필 변경·물리 DELETE·TRUNCATE·DDL은 허용하지 않는다. 권한 부여는 별도 명령이며 API 시작에서 자동 수행하지 않는다.

`DeleteSource`는 소스 행 잠금과 version 검사를 거쳐 같은 트랜잭션의 사용 확인 검사에서 명시적으로 미사용을 확인해야 변경한다. 저장소는 검사 누락·불확실한 상태를 거부하며 기본 미사용 정책을 제공하지 않는다. 10-C의 장치/소스 HTTP 호출자는 세션·소비·미디어 어댑터 생성 경로가 없는 등록 전용 릴리스를 명시하고, device_delete를 포함한 공통의 정확한 capability 목록이 일치할 때만 미사용으로 판단한다. 새 기능·누락·미확인 구성은 거부한다. 실제 사용 관계 도입 전에는 같은 소스 잠금 안에서 검사하는 입장 제어로 교체해야 한다. 삭제 시 version+1과 같은 deleted_at/updated_at, 삭제 성공 기록을 함께 저장한다. 행·프로필·기존 POST/PATCH 이력은 보존하고 GET/목록에서만 제외한다. 재생은 최초 성공을 반환하며 현재 데이터를 바꾸지 않는다.

새 코드의 readiness는 정확한 스키마 7 이력과 최소 권한을 읽기 전용으로 확인한다. 연결은 CAMERA_DATABASE_URL 또는 CAMERA_DATABASE_URL_FILE 중 하나를 명시한다. 운영 중인 09 이미지는 스키마 6을 요구하므로 새 코드와 즉시 교환하지 않는다. 이번 전달은 파일 반영과 격리 검사까지이며 과거 활성화 도구를 새 코드에서 재사용하지 않는다. 운영 전환·복구 검증은 후속 단계이며 운영 DB를 자동 복원하지 않는다.

## 대상 서버 격리 검사

검사 도구는 무작위 이름의 독립 Compose 프로젝트와 명시적 시험 Compose 파일을 사용한다. 환경 파일은 빈 파일로 지정하며 시험 비밀번호를 매번 생성한다. 운영 루트 Compose·환경 파일·DB를 사용하지 않는다. DB 포트는 호스트에 공개하지 않고 데이터는 tmpfs에 둔다. 프로젝트 소스는 읽기 전용으로 연결한 뒤 검사 컨테이너 안으로 복사한다.

검사 이미지는 `postgres:17.11-bookworm`, `golang:1.27.1-bookworm`이다. Docker Engine/Compose와 이미지·Go 모듈 다운로드 경로가 필요하며 최초 실행에는 다운로드 시간이 추가된다. 호스트에 Go나 PostgreSQL을 설치할 필요는 없다. 같은 임시 스키마를 사용하는 Go 패키지를 직렬 실행하며 race 검사와 vet를 수행한다.

검사 범위는 논리 삭제·과거 응답 재생·버전/키 충돌·사용 상태 거부·원자적 롤백·권한 상실 후 재시도, 스키마 6→7 및 이전 이력 보존, 실제 runtime 계정의 열 권한과 삭제/수정 동시성, 장치/소스 삭제 HTTP의 엄격한 입력·삭제 결과·과거 POST/PATCH/DELETE 재생·실제 API 재시작/토큰 교체와 기존 장치/소스 HTTP 회귀다. 성공 scope는 `camera_device_delete_http_native_postgresql`, status는 passed, production_services_modified는 false다. 종료 시 해당 시험 프로젝트만 정리하며 정리 실패도 실패로 보고한다.

직접 Go 통합 검사를 실행하려면 `CAMERA_TEST_DATABASE_URL`과 `CAMERA_TEST_ALLOW_SCHEMA_RESET=1`을 모두 지정해야 한다. camera 스키마를 삭제하는 검사이므로 이름이 `vms_camera_test`인 전용 임시 DB만 허용한다. PGlite 예외는 실제 엔진 식별까지 확인하며 역할 인증과 다중 연결 검사는 건너뛴다. DB 설정이 없는 일반 단위 검사의 skip을 DB 검증 통과로 기록하지 않는다.

10-C 패치 적용은 서비스 재시작·운영 마이그레이션·권한 변경을 하지 않는다. 로컬 PGlite 검증은 실제 PostgreSQL 계정 권한·동시 접속 검증을 대신하지 않는다. 10-B native 저장소 검사는 통과했고, 10-C HTTP 서버 격리 인수 뒤 10-D1 운영 사전점검을 진행한다. 적용 명령은 채팅으로만 제공한다.

## 장치 논리 삭제 저장소 — 10-B

DeleteDevice는 성공 이력을 먼저 재생하고, CreateSource와 같은 장치별 advisory transaction lock을 획득한 뒤 장치 행을 FOR UPDATE로 읽는다. expected_version·버전 소진·미삭제 자식·서버 사용 관계 순서로 판단한다. READ COMMITTED를 명시해 잠금 대기 전의 연결 기본 스냅샷을 재사용하지 않는다.

자식이 없거나 모두 논리 삭제됐을 때만 신뢰된 DeviceDeleteGuard를 실행한다. 기본 미사용 guard는 없으며 nil·unknown·오류는 거부한다. 새 성공은 장치 tombstone·version+1·동일하고 역행하지 않는 UTC 시각·device_delete_requests 결과를 한 트랜잭션으로 기록한다. 장치·삭제된 자식·프로필·과거 이력을 보존하며 실제 세션·입력 어댑터를 관리하지 않는다.

10-C의 장치/소스 guard는 같은 검토 허용 목록을 사용한다. 현재 등록 전용 생성자에서만 이 정책을 선택하고 클라이언트나 환경에서 정책을 지정할 수 없다. 실제 관리 사용 관계를 도입하면 장치 사용 시작은 장치 advisory/행 잠금과, 소스 사용 시작은 소스 행 잠금과 결합된 입장 제어로 교체한다. 외부 장비의 사용 여부 탐지를 구현한 것으로 표시하지 않는다.
