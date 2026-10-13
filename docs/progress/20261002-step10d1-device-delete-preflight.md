# 단위 10-D1 — 장치 삭제 운영 전환 사전점검

작성일: 2026-10-02 · 사전점검 도구·로컬 검증 완료 · 실제 서버 점검 결과 대기 · 운영 활성화 전

## 10-C 서버 격리 검사 인수

사용자 로그에서 10-C 패치 applied/written=29·pending=0을 확인했다. 백업은 `var/patch-backups/step10c-6ap6um9w`이며 서비스 재시작·운영 활성화·DB 스키마 변경은 수행하지 않았다.

임시 프로젝트 `vms-storage-test-f32384ce4e83`의 PostgreSQL 17.11에서 전체 Go race 검사와 vet가 통과했다. 실제 장치 DELETE HTTP의 활성 자식 거부·각 자식의 소스 DELETE 후 같은 실패 키로 부모 삭제 재시도·등록 전용 정책·최소 삭제 영수증·정규화·경로·오류·키/버전 충돌·버전 소진 검사를 확인했다. tombstone·장치/소스/프로필/과거 이력 보존, GET/목록 제외·삭제 전 cursor 사용·ID 예약, 삭제 부모의 소스 생성 거부가 통과했다.

장치 삭제 기록 및 tombstone 열 권한 회수 시 HTTP/readiness 503·원자적 롤백·권한 복원 후 같은 키 재시도가 native 역할에서 통과했다. 실제 API 재시작·토큰 교체 후 장치 DELETE와 과거 장치/소스 POST/PATCH/DELETE 결과 재생, 기존 소스 삭제 HTTP/native 권한 회귀, 저장소 다중 연결 경쟁·스키마/역할/최소 열 권한 검사도 통과했다. 로그에 FAIL·SKIP이 없고 시험 DB 컨테이너와 네트워크 제거를 확인했다.

최종 결과는 status=passed·scope=camera_device_delete_http_native_postgresql·production_services_modified=false다. [10-C 기록](20261002-step10c-device-delete-http.md)의 전달 당시 서버 검사 대기는 이 결과로 해소됐다. 이는 격리 검사 인수이며 운영 전환 결과가 아니다. 운영은 마지막으로 인수한 09의 `0.6.0-source-delete`·스키마 6을 유지한다.

## 이번 범위

새 `src/infra/tools/inspect_camera_device_delete.py`는 운영 전환 전제를 조회한다. 이번 패치는 도구·해당 Python 검사·이 문서의 3개 파일만 추가한다. 서버에서 검증한 10-C 프로젝트 명세와 기존 모든 파일의 해시를 보존하며 새 파일은 패치 명세로 검증한다. 기존 명세의 전달 당시 서버 검증 표시도 그대로 유지하고, 이후 서버 인수는 위 기록으로 구분한다. 개인 보고서에는 점검 도구 자체의 해시를 남긴다.

Docker는 프로젝트·컨테이너·볼륨 조회, 현재 Compose 구성 조회와 정확히 지정한 READ ONLY SQL만 허용한다. HTTP는 readiness·platform·실행 OpenAPI·장치/소스 목록 GET만 사용한다. 빌드·컨테이너 생성/정지/재시작·마이그레이션·권한 부여·백업/복원·API 변경 요청을 수행하지 않는다. 점검 도구는 적용 옵션을 받지 않는다.

로컬 쓰기는 기존 전환 도구와 공유하는 activation 잠금 및 `var/camera/device-delete-preflight.json` 보고서다. 기존 환경·비밀 파일을 생성하거나 고치지 않는다. 성공 보고서도 운영 활성화를 허가하지 않으며 후속 리허설·전환 단계에서 상태를 다시 점검해야 한다.

## 확인 항목

- 10-C 코드 버전 0.7.0-device-delete·스키마 7·10-B 저장소 리비전, 장치/소스 삭제 구현·registry-only-v1 정책·업무 런타임 미구현 표시와 명세에 기록된 모든 파일의 SHA-256. 삭제 핸들러·정책·0001~0007 마이그레이션이 필수 대상이다. 명세에 없는 플랫폼 Go/SQL 파일도 거부한다.
- 로컬 Unix Docker, vms-project의 실행 중인 camera API/DB, 기존 영속 볼륨의 소유권·실제 마운트와 DB health.
- 09 완료 기록 `source-delete-activation.json`의 activated/completed·스키마 6·source_delete_activated와 현재 API/DB 이미지 일치. 현재 Compose의 camera 이미지도 실행 중인 SHA-256 ID로 고정돼 있어야 한다.
- 기존 비밀 디렉터리/파일 소유권·권한·DSN 형식, 실제 camera 컨테이너의 읽기 전용 runtime DSN 마운트와 inline DB URL 부재.
- 운영 API 0.6.0-source-delete·P1_SOURCE_DELETE와 검토한 capability 목록 전체의 일치. 새 장치 삭제 기능·미디어/세션/소비 기능·알 수 없는 기능 추가, 기능 누락·상태 변경이면 중단한다. readiness·장치/소스 목록 GET도 확인한다.
- 실행 OpenAPI 3.1.0·버전 0.6.0, 기존 소스 DELETE와 장치 GET/PATCH·장치 DELETE 부재.
- PostgreSQL 17, 마이그레이션 0001~0006의 이름·순서·체크섬과 device_delete_requests 테이블 부재. 이미 스키마 7이거나 중간 상태이면 중단한다.
- migrator/runtime 역할의 superuser·DB/역할 생성·replication·RLS 우회 권한 부재와 runtime 외 동시 DB 클라이언트 부재.
- 스키마 6의 runtime 최소 권한: schema USAGE·마이그레이션 SELECT·등록/기록 8개 테이블 SELECT/INSERT·장치 이름/version/updated_at 열 UPDATE·소스 이름/version/updated_at/deleted_at 열 UPDATE. schema CREATE·장치 deleted_at UPDATE·테이블 전체 UPDATE/DELETE/TRUNCATE·장치/소스 불변 열 UPDATE는 없어야 한다. 권한 상실과 확장을 모두 거부한다. 이는 기존 스키마 6 권한 확인이며 스키마 7 권한을 부여하지 않는다.
- 장치·장치 생성 기록·소스·프로필·소스 생성 기록·장치 수정 기록·소스 수정 기록·소스 삭제 기록의 8개 건수와 DB 크기. 백업 경로의 최소 여유 공간은 DB 크기의 2배와 64 MiB 중 큰 값이다. 실제 덤프 크기나 복원 성공을 보장하지 않으며 이번에는 백업을 생성하지 않는다.
- 점검 전후 네 플랫폼 컨테이너 ID/이미지/시작 시각/재시작 횟수, 환경·비밀·09 완료 기록·10-C 명세·점검 도구의 해시 일치.

SQL은 BEGIN READ ONLY와 statement/lock timeout을 사용하며 등록 원문 대신 이력·권한·집계만 조회한다. 건수는 운영 요청이 가능한 상태에서 한 SELECT로 관측한 값이며 쓰기를 차단하거나 등록 소스를 수정/삭제하지 않는다. 표시 이름·프로필 원문·토큰·DSN·비밀번호를 보고서나 표준 출력에 남기지 않는다. 환경/비밀 해시·컨테이너/데몬 식별자는 0600 개인 보고서에만 저장한다.

잠금을 획득하면 이전 보고서를 running으로 바꾸고 실패·중단 시 failed로 무효화한다. 다른 작업이 잠금을 잡고 있으면 보고서를 덮어쓰지 않는다. 오류는 상세 Docker 출력 대신 고정 코드로 표시한다. 등록 전용 검사는 현재 코드와 구성의 일치 여부이며 외부 장비·미디어 사용을 탐지하는 검사가 아니다.

## 로컬 검증

- Python 검사 38개 통과. 허용된 Docker 조회/고정 SQL/HTTP GET만 실행하고 빌드·재시작·삭제·임의 SQL·적용 인자를 차단한다. 스키마 6 이력·체크섬·API/OpenAPI·완료 기록·이미지·마운트·역할·최소 권한·다른 DB 클라이언트·8개 건수·백업 공간 불일치 시 중단한다.
- 등록 전용 목표 정책·정책 코드 누락, 현재 API의 새 장치 삭제·미디어·세션/소비·미확인 capability와 기능 누락을 거부한다. 점검 중 환경·비밀·컨테이너·완료 기록·코드 변경, 명세에 없는 Go/SQL·심볼릭 링크, 공유 잠금 충돌과 과거 성공 보고서의 실패/중단 무효화, 0600 보고서·공개 출력/오류의 비밀 제외를 확인했다.
- 임시 PostgreSQL 18.3(PGlite 0.5.8)에 스키마 6·이력 6개·역할/최소 권한을 구성하고 고정 SQL을 실행했다. 정확한 이력·8개 집계·새 삭제 기록 테이블 부재·권한 bool 구조, 권한 회수/확장 탐지, READ ONLY 트랜잭션의 쓰기 거부(SQLSTATE 25006)와 데이터/이력 보존을 확인했다. PGlite를 native 역할 인증이나 운영 PostgreSQL 17 검사로 계산하지 않는다.
- 실제 10-C 프로젝트 명세·해시 확인과 새 Python 파일의 Python 3.10 문법 검사 통과. 패치 적용 도구 검사 8개, 전체 패키지 적용/재적용·기준 충돌 시 사전 중단, payload/압축본 경로·해시와 기존 코드·명세·환경·운영 기록 보존을 확인했다.

Go·HTTP·DB 마이그레이션 코드를 바꾸지 않았으므로 이미 서버에서 통과한 전체 Go/DB 검사와 smoke를 반복하지 않았다. 운영 이미지 빌드·서비스 전환도 수행하지 않았다. 실제 PostgreSQL 17/Docker의 운영 사전점검은 서버 실행 결과로 인수한다.

## 서버 결과와 다음 단위

성공 scope는 camera_device_delete_preflight다. running_api_version=0.6.0-source-delete·target_api_version=0.7.0-device-delete·schema_version=6·target_schema_version=7·target_usage_policy=registry-only-v1·running_openapi_verified=true·production_services_modified=false·device_delete_activated=false를 확인한다. 실제 건수·공간·이미지 값은 서버 실행 결과로 확정한다.

통과 후 다음 단위는 **10-D2: 스키마 7 업그레이드·복구 격리 리허설**이다. 검증한 이전 이미지/스키마 6과 새 이미지/스키마 7 사이의 업그레이드·권한·장치/소스 삭제·과거 응답 재생·재시작·복원과 데이터 보존을 확인한다. 운영 DB 변경·이미지 전환은 리허설 이후 별도 단계다. 스키마 6 이미지로만 되돌리는 복귀나 자동 운영 DB 복원은 가정하지 않는다. 적용·실행 명령은 채팅으로만 전달한다.
