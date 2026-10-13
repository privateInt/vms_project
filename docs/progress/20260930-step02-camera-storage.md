# 작업 단위 02 — 카메라 저장소·마이그레이션

작성일: 2026-09-30 · 런타임 HTTP 버전: 0.1.0-p0 유지

## 서버 확인 완료 — 2026-09-30

사용자 제공 실행 로그로 단위 02의 파일 적용과 PostgreSQL 17.11 격리 검증을 확인했다. 적용은 written=20, 백업은 `/home/shshin/workspace/vms_project/var/patch-backups/step02-53we0ryn`이다. 최초/재적용·DB 제약·실패 원자성·동시 마이그레이션·기존 테이블 보존과 오류 보호 검사가 모두 통과했다. 검사 실행 도구의 최종 결과는 status=passed, scope=camera_storage_native_postgresql, production_services_modified=false다. 임시 DB 컨테이너와 네트워크 제거도 로그로 확인했다.

이에 따라 **단위 02의 대상 서버 격리 검증을 완료**로 처리한다. 아래 로컬 미검증·서버 대기 문구는 최초 전달 당시의 기록이다. 운영 DB 설치·업무 API 활성화·실장비 검증 완료를 뜻하지 않는다. 후속 구현은 단위 03 기록을 따른다.

## 선행 상태

사용자가 단위 01 패치의 서버 적용 결과를 제공했다. status=applied, written=13, 백업 경로는 `/home/shshin/workspace/vms_project/var/patch-backups/step01-svwokfhf`, 재시작 불필요로 확인했다. 이는 파일 반영 확인이며 네 API나 실제 장비 동작을 새로 확인한 것은 아니다.

AGENTS, 작업 기준, 단위 01 기록을 읽고 저장소·마이그레이션만 이번 단위로 선택했다.

## 구현

- PostgreSQL·pgx/v5 v5.11.0 채택. 명시적 URL 접속·제한 시간·트랜잭션·안전한 오류 코드 구현.
- camera 전용 devices/video_sources/stream_profiles와 마이그레이션 이력 테이블. 부모 참조·채널/프로필 유일성·필수 값·ID·전송 조합·치수/FPS·프로필 수 제약 구현.
- 소스의 primary_profile_id를 첫 프로필로 저장하고 지연 외래 키로 트랜잭션 완료 시 최소 1개 프로필 보장. 입력 API 스키마는 변경하지 않음.
- SQL 내장·순서·checksum·이력 검사, 트랜잭션 advisory lock, 오류 시 DDL/이력 롤백 구현. 기존 테이블과 충돌하면 중단.
- 별도 camera-migrate 명령. API 기동 시 자동 DDL 없음. 명시적 apply 옵션과 CAMERA_DATABASE_URL 필요.
- 임시 PostgreSQL 17 / Go 검사 Compose와 고유 프로젝트의 실행·정리 도구 추가. 운영 루트 Compose에는 포함하지 않음.
- ADR·계약 설명·개발/운영 안내·문서 목록·현재 상태 기록 갱신.

## 이번 환경의 검증

환경은 Linux amd64, Go 1.27.1, pgx v5.11.0, PGlite 0.5.8의 PostgreSQL 18.3 WASM 엔진이다. Go 도구 체인은 공식 배포 파일의 SHA-256 확인 후 사용했다. 일반 PostgreSQL 서버 설치가 환경 권한 제한으로 실패했고 Docker 실행 파일도 없어, PGlite socket으로 로컬 DB 통합 검사를 수행했다.

| 검사 | 결과·범위 |
|---|---|
| go test -race 전체 | 통과. 공통 API·계약과 저장소 검증 포함 |
| 저장소 DB 통합 | 최초/재적용, 다중 채널·XR, 필수·범위·유일성·외래 키, 커밋 시 프로필 존재, 오류 롤백, 이력 변조/미래 버전 거부, 기존 데이터 보존 통과 |
| 마이그레이션 CLI | 동일 임시 DB 첫 실행 applied=1/version=1, 재실행 applied=0/version=1 확인 |
| CLI 입력 보호 | apply 옵션 누락·DB URL 누락·잘못된 설정 거부, 오류 출력에 비밀번호 미포함 확인 |
| go vet 전체 | 통과 |
| 네 API HTTP 스모크 | 43개 통과. 기존 프로세스·계약·인증·종료 동작 확인 |
| 파일 패치 도구 | 7개 통과. 사전 충돌 검사·백업·재적용·설정 보존·변조/경로 거부·쓰기 실패 복구 확인 |
| 격리 검사 구성 | Python 구문·Compose 구조 확인. 실제 Docker 실행 결과는 아래처럼 미검증 |
| 일반 PostgreSQL 동시 마이그레이션 | 로컬 미검증. PGlite의 단일 backend 제약 때문에 해당 테스트를 명시적으로 skip |
| 대상 서버 Docker 검사 | 미실행. 전달한 격리 검사 도구로 확인 필요 |
| 카메라·XR·GPU·업무 API | 이번 범위 아님 |

PGlite 검사는 PostgreSQL 엔진의 SQL 검증이며 mock 응답만 확인한 것이 아니다. 다만 일반 PostgreSQL의 인증·다중 backend·컨테이너·네트워크를 대신하지 않는다. PGlite socket의 준비된 문장 캐시 공유 제약 때문에 검사 URL에는 exec 모드 옵션을 사용했다. 운영 접속 기본값은 바꾸지 않았다. 일반 PostgreSQL 검사에서는 기본 pgx 동작을 사용한다.

## 적용과 남은 항목

패치는 단위 01 이후 파일을 기준으로 검사·백업하며 `.env`와 기존 실행 데이터는 보존한다. 패치 적용 자체에 API 재빌드·서비스 재시작·운영 DB 생성은 필요하지 않다. 마이그레이션 이력 해시는 제공 SQL의 일치 여부를 검사하며 DB에 수동으로 가한 모든 DDL 변경을 탐지하는 스키마 비교기는 아니다.

대상 서버에서 격리 검사 도구를 실행하고 동시 마이그레이션을 포함한 PostgreSQL 17 결과를 받으면 단위 02의 서버 검증을 마무리한다. 테스트는 무작위 이름의 별도 컨테이너·네트워크와 임시 DB만 사용하고 종료 후 정리한다. 이미지와 Go 모듈은 최초 실행 시 다운로드한다.

**다음 구현 단위는 장치 등록·조회 API**다. 단위 02의 서버 검증을 먼저 확인한 뒤 영속 DB·권한·서비스 접속, Device 생성/조회/목록, 멱등 처리와 재시작 보존을 연결한다. 소스 CRUD·변경/삭제·연결 세션·ONVIF/XR은 별도 단위로 남긴다.
