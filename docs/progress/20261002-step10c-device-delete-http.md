# 단위 10-C — 장치 논리 삭제 HTTP 연결

작성일: 2026-10-02 · 코드·로컬 검증 완료 · 대상 서버 HTTP 격리 인수 대기 · 운영 활성화 전

## 선행 결과와 범위

AGENTS.md·작업 기준·10-B 기록과 사용자 실행 로그를 확인했다. 10-B 패치 29개 파일 적용과 PostgreSQL 17.11의 전체 race/vet, 장치 삭제·소스 생성의 실제 다중 연결 잠금/롤백, native 역할·열 최소 권한·권한 회수 후 원자적 재시도 검사가 통과했다. 시험 프로젝트와 네트워크 정리가 끝났고 production_services_modified=false다. 상세 서버 인수를 [10-B 기록](20261001-step10b-device-delete-storage.md)에 추가했다.

이번 단위는 장치 DELETE HTTP·엄격한 요청 검사·최소 삭제 응답·오류·OpenAPI·등록 전용 정책·필수 검증·패치 전달이다. 새 개발 코드의 버전은 0.7.0-device-delete·스키마 7이다. 운영은 09 인수 기준의 0.6.0-source-delete·스키마 6을 유지한다. 기존 storage 구현·0001~0007 SQL·운영 Compose·이미지 고정·환경·전환 도구를 바꾸지 않는다.

## 구현

- DELETE /api/v1/devices/{device_id}를 10-B DeleteDevice에 연결했다. 인증 → 메서드 → 쿼리 → 해석된 경로 ID → 조건 헤더 → 단일 멱등 키 → media/JSON → 의미 → 저장소 순서다. 빈 물음표도 거부한다. 장치 단건 Allow는 GET, PATCH, DELETE다. 장치 ID validate와 그 URL 이스케이프는 일반 장치 경로이며 소스의 validate 예약 경로는 유지한다.
- DeviceDelete는 두 필드만 받는 엄격한 디코더를 사용한다. expected_version은 부동소수점 변환 없이 signed int64 원문 정수로 읽는다. 중복/이스케이프 중복 키·미지원/대소문자 필드·잘못된 타입·실수/지수·범위 초과·null·무효 UTF-8·후행 JSON은 INVALID_JSON이다. 누락·0/음수·잘못된 schema_version은 CONTRACT_INVALID다. DELETE 본문 누락을 무조건 삭제로 해석하지 않는다. 기존 64 KiB·application/json·조건 헤더 금지 기준을 적용한다.
- 최초 성공·성공 재생 모두 200이며 최소 DeviceDeletion과 DELETED/runtime_verified=false/request_id만 반환한다. 새 request_id·X-Request-ID 일치, no-store, Idempotency-Replayed false/true를 유지하고 Location·장치 스냅샷·자식/비밀 목록은 반환하지 않는다.
- DEVICE_HAS_ACTIVE_SOURCES·DEVICE_IN_USE는 409, DEVICE_USAGE_UNAVAILABLE는 503이다. 사용 관계 guard는 활성 자식이 없는 경우만 호출한다. 실패는 성공 키를 예약하지 않고 tombstone·version·시각·성공 결과를 함께 롤백한다. 과거 장치/소스 성공 응답은 삭제된 부모/자식을 복원하지 않고 재생한다.
- camera-api 시작 코드와 app 생성자를 확인했다. 설치 경로는 등록 메타데이터 API뿐이며 세션·consumer·ONVIF/PTZ·입력/녹화 어댑터 생성자와 활성화 설정이 없다. 서버가 registry-only-v1을 선택한다. device_delete capability와 장치/소스 삭제의 공통 정확한 허용 목록을 함께 반영해 기존 소스 삭제가 거부되지 않도록 했다. 검토 목록/값 불일치·미확인 모드·취소는 거부한다. 클라이언트/환경은 정책을 선택하지 못한다.
- 이 정책은 외부 장비 사용 감지가 아니다. 실제 관리 사용 관계를 도입하면 장치 사용 시작도 같은 장치 advisory/행 잠금에 참여하고 소스 사용 시작도 소스 행 잠금에 참여하는 원자적 입장 제어로 교체해야 한다. 자식 수 0이나 business_runtime_ready=false만으로 삭제를 허용하지 않는다.
- 실행 OpenAPI에 DeviceDelete/DeviceDeletion/DeviceDeleteResponse를 추가했다. 기존 Device/DeviceResponse·소스 응답 스키마를 보존한다. planned 계약·예제는 설계 기준으로 유지한다. 서버 격리 검사 scope는 camera_device_delete_http_native_postgresql이다.

## 검증

- Go 1.25.0에서 전체 패키지 race 검사와 go vet가 통과했다. 임시 PostgreSQL 18.3(PGlite 0.5.8)에서 app 최상위 15개·camera contracts 15개·storage 28개·analysis contracts 3개·httpapi 4개가 통과했다. storage native 전용 15개는 skip됐다. PGlite를 native 역할/동시 접속 검증으로 계산하지 않는다.
- 실제 camera API 프로세스와 임시 DB에서 활성 자식 거부·version 우선순위, 각 자식의 소스 DELETE 후 같은 실패 키로 부모 삭제 재시도, 최소 삭제 결과/version/UTC 시각, 삭제 기록 쓰기 실패 HTTP 503/원자적 롤백, 장치/삭제 자식/프로필/기존 이력 보존을 확인했다.
- 장치 GET/PATCH/새 DELETE의 404·목록 제외·삭제 전 페이지 cursor·삭제 부모 소스 필터의 빈 목록, ID 재사용 거부, 삭제 후 새 소스 생성의 DEVICE_UNAVAILABLE 및 소스/프로필/기록 미저장을 확인했다. JSON/URL 정규화·키 충돌·버전 소진·validate 장치 경로가 통과했다.
- 실제 API 재시작·토큰 교체 후 장치 DELETE와 장치 POST/PATCH·소스 POST/PATCH/DELETE 최초 결과 재생을 확인했다. 기존 장치/소스 HTTP 회귀와 소스 validate 예약 경로도 통과했다.
- 장치/소스 등록 전용 정책의 전체 capability 누락/값 변경·미확인 기능 추가·모드·취소 거부, 장치 자식/사용 상태 오류의 HTTP 매핑을 확인했다. 실제 사용 중 세션을 관측한 검사가 아니다.
- 네 플랫폼 실제 프로세스 smoke 62개가 통과했다. 장치 DELETE 인증·키·정수·의미 오류·본문 유실과 기존 계약/프로세스 정상 종료를 확인했다.
- 장치 planned 계약 검사 8개와 실행 OpenAPI 검사 12개가 통과했다. 요청·최소 영수증·응답 스키마의 계약 일치, 실제 명세 예제·오류/헤더·validate 장치와 예약 소스 경로·전체 내부 참조를 확인했다.
- 패치 적용 도구 검사 8개와 전체 패키지 적용/재적용·백업·기존 환경/운영 기록 보존, payload/압축본 경로·해시·manifest 파일 해시를 확인했다. Python 3.10 문법으로 변경된 Python 파일을 파싱했다. storage 전체·기존 마이그레이션·운영 구성·전환 도구가 변경되지 않았음을 해시로 확인했다.

새 장치 DELETE HTTP의 native 역할 인증·새 이력/열 권한 회수 시 503/readiness 실패·롤백/권한 복원 후 같은 키 재시도는 대상 서버 검사에 포함했다. 로컬 PGlite에서는 이 부분을 수행하지 않았다. 10-B native 서버 검증은 저장소의 선행 결과이며 새 HTTP 코드의 서버 인수나 운영 활성화로 확대하지 않는다. 실장비·미디어·GPU·모델·분석·UI·운영 DB 전환은 이번 검증 범위가 아니다.

## 적용 전제와 다음 단위

10-B가 적용된 프로젝트에 기준 파일·해시 검사와 백업 후 변경 파일만 적용한다. 패치는 서비스·DB 명령을 실행하지 않고 환경·기존 운영 자료를 보존한다. 새 코드는 스키마 7을 요구하므로 운영 스키마 6에서 임의 재빌드·재시작하지 않는다. 사용자 명령은 채팅에서 따로 제공한다.

대상 서버의 고유 임시 Docker 프로젝트에서 PostgreSQL 17.11과 전체 race/vet, 실제 HTTP/native 권한 검사를 실행한다. 성공 기준은 status=passed·scope=camera_device_delete_http_native_postgresql·production_services_modified=false와 시험 컨테이너/네트워크 정리다. 서버 결과는 아직 받기 전이다.

통과 후 다음 단위는 **10-D1: 장치 삭제 운영 전환 사전점검**이다. 현재 운영 0.6.0·스키마 6의 이미지·이력·권한·백업 전제를 읽기 전용으로 확인한다. 이미지/마이그레이션·보존/복원 리허설과 실제 운영 활성화는 이후 별도 단위로 진행한다. 과거 활성화 도구를 새 코드에서 재사용하지 않으며 운영 DB를 자동 복원하지 않는다.
