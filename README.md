# VMS Project

CCTV와 스마트글래스의 영상 입력, 모델 배포, 영상 분석, 운영을 독립 플랫폼으로 구성하는 프로젝트입니다. 목표 경로는 `/home/shshin/workspace/vms_project`입니다.

**현재 기능 개발을 중단하고 Codex 이관 자료를 준비했습니다.** 첫 작업은 11-D1e의 `REGISTRY_TLS_COMPOSE_SECRETS_CHANGED` 수정과 실패 후 준비 파일/source revision 대응입니다. 오류 수정·운영 TLS 전환은 아직 수행하지 않았습니다. [Codex 이관](docs/development/codex-handoff.md) · [개발 순서·완료 조건](docs/development/codex-backlog.md) · [시작 지시문](docs/development/codex-start-prompt.txt) · [최신 상태](docs/progress/20261012-codex-handoff.md)

**프로젝트 생성 자료 정리는 서버에서 완료됐습니다.** 대상41개·파일 항목12,021개·논리적 파일 크기472,388,543 bytes를 제거했습니다. `.env`·현재 키·TLS 공급·receipt·코드·검사 JSON은 보존됐고 새 백업은 생성하지 않았습니다. Camera Streamlit 소스는 남아 있지만 전용 Python 환경은 제거됐습니다. UI를 사용할 때 전용 환경을 재생성하며 공유 Conda/Jupyter는 유지합니다. [정리 인수](docs/progress/20261012-codex-handoff.md) · [정리 안내](docs/operations/project-artifact-cleanup.md)

**11-D1e 준비는 서버 dry-run 후 첫 apply의 Compose 검사에서 실패했습니다.** 서버 준비30개·정리12개 Python 검사는 통과했습니다. dry-run은 기존 공급·운영 binding을 확인했지만 apply는 `compose_validation`에서 중단됐고 두 번째 apply는 실행되지 않았습니다. 준비 파일이 남아 있을 수 있으며 문서 반영도 source hash를 바꾸므로, 후속 Codex가 재실행 호환성을 검증하기 전에는 기존 준비 apply를 다시 실행하지 않습니다. 운영 서비스/DB/schema·현재 Compose·환경은 전환하지 않았습니다. [진행 기록](docs/progress/20261012-codex-handoff.md) · [준비 안내](docs/operations/camera-registry-tls-preparation.md)

**11-D1d schema7 등록 API의 TLS 전환 격리 리허설 서버 인수를 완료했습니다.** 서버 Python45개·Go policy race1개/vet·native peer3개/transport5개 phase·전환10개 phase·실제 HTTP 게시 검사4개가 통과했습니다. 같은 운영 API/DB 이미지로 새 합성 DB/PKI를 사용해 schema7·전체 등록/삭제 이력·실제 TLS/source/UID/RO·API/DB 재생성과 정리를 확인했습니다. native probe는 CGO=0이며 race 적용을 주장하지 않습니다. 운영 서비스·DB·준비된 TLS 볼륨은 변경하지 않았고 운영 TLS는 미전환입니다. 다음은11-D1e 운영 DB TLS 전환 준비입니다. [서버 인수](docs/progress/20261012-step11d1d-server-acceptance.md) · [검사 안내](docs/operations/camera-registry-tls-cutover-check.md) · [구현 기록](docs/progress/20261012-step11d1d-registry-tls-cutover.md)

현재 운영 camera는 **`0.7.0-device-delete`·DB 스키마 7·registry-only-v1**입니다. 장치·영상 소스의 등록·조회·목록·이름 수정·논리 삭제까지 운영 인수를 완료했습니다. 근거는 [10 인수 기록](docs/progress/20261002-step10-server-acceptance.md)입니다.

자격증명 저장소·외부 admission·schema9 marker·전 작업 lease·유지보수 차단 경계·격리 복원/재개와 공급 검토 초안을 서버에서 인수했습니다. 실제 init process는 API UID/GID65532:65532, DB999:999이며 mapping·cgroup·독립 PID namespace를 확인했습니다.

**11-B3c3d4g의 서버 테스트192개와 실제 볼륨 마운트 검증을 완료했습니다.** 제한된 관리자 보조 관찰로 `/media/simsys/SSD_EXT4`의 ext4 마운트와 DB 디렉터리 `999:999 / 0700`, 중첩 마운트0개를 확인했습니다. 호스트 권한·DB 파일·서비스는 변경하지 않았습니다.

**11-B3c3d4h의 서버 테스트 52개와 실제 PostgreSQL 저장 경로 관찰을 완료했습니다.** PostgreSQL 17.11의 PGDATA와 WAL은 현재 데이터 볼륨 안에 있고 symlink가 아니며 999:999/0700입니다. 사용자 테이블스페이스는 없고 archive_mode는 off입니다. 고정 READ ONLY SQL·UID999 메타데이터·반복 볼륨 확인을 인수했습니다. 당시 미완료였던 개별 호스트 경로 대응은 아래 d4i에서 완료했고, 전체 백업 범위는 후속입니다.

**11-B3c3d4i의 서버 테스트 47개와 PGDATA·WAL의 호스트 물리 경로 대응 검증을 완료했습니다.** 사용자 제공 서버 JSON에서 두 고정 경로 모두 symlink 없이 컨테이너와 같은 디렉터리이며 ext4·999:999/0700임을 확인했습니다. 제한된 관리자 보조와 실제 root sender 검증도 통과했습니다. 로컬 274개 검증과 이번 서버 47개 검증은 별도로 기록합니다. [검사 안내](docs/operations/camera-database-storage-mapping.md) · [구현 기록](docs/progress/20261008-step11b3c3d4i-physical-storage-mapping.md) · [서버 인수](docs/progress/20261008-step11b3c3d4i-server-acceptance.md)

**11-B3c3d4j의 서버 테스트 120개와 실제 검토 초안 생성·재실행을 완료했습니다.** 현재 PGDATA·WAL을 다시 검증했고, 같은 내용 SHA의 초안이 prepared → already_prepared로 보존됐습니다. 코드 선언 위치 후보 8곳과 미확정 선언 22개를 기록하며 전체 백업 범위·외부 제어 파일의 물리적 제외·운영 공급 준비는 미완료입니다. 로컬 167개와 이번 서버 120개 검증을 구분합니다. [검토 안내](docs/operations/camera-credential-backup-review.md) · [구현 기록](docs/progress/20261008-step11b3c3d4j-backup-boundary-review.md) · [서버 인수](docs/progress/20261008-step11b3c3d4j-server-acceptance.md)

**11-C1 생성·교체 HTTP 구성요소의 서버 인수를 완료했습니다.** Python7개·Go 상위170개/하위494개와 race/vet, 필수 HTTP7개·계약5개·기존 자격증명13개가 통과했습니다. actual TLS와 입력/권한/비밀 비공개 검사를 인수했으며 HTTP 성공은 synthetic writer 범위입니다. 실제 admitted store와 HTTP 성공의 결합은 아직 미검증입니다. 현재 main에는 미등록이며 메타데이터 조회·폐기 HTTP는 아래 11-C2에서 구현했습니다. 백업 추가 검토는 사용자 요청에 따라 제외합니다. [HTTP 계약](docs/contracts/camera-credential-write-http.md) · [구현 기록](docs/progress/20261008-step11c1-credential-write-http.md) · [서버 인수](docs/progress/20261008-step11c1-server-acceptance.md)

**11-C2 버전 메타데이터 조회·폐기 HTTP의 서버 격리 인수를 완료했습니다.** GET은 비밀값 없는 정확한 버전 이력을 반환하고, DELETE는 기존 사용 보호·논리 폐기·결과 재생을 호출합니다. 새 메타데이터 조회는 MANAGE 권한과 전체 작업 lease를 요구하며 암호화 예산을 소비하지 않습니다. 실제 PostgreSQL의 이력/권한 회수 검사와 HTTP/TLS 검사를 로컬에서 통과했습니다. HTTP 성공은 synthetic manager이며 실제 admitted store와 결합한 HTTP 검사는 후속입니다. 서버 Python9개·Go185/567·race/vet·필수40개가 통과했고 격리 자원을 정리했습니다. 현재 실행 경로에는 미등록입니다. [조회·폐기 계약](docs/contracts/camera-credential-versions-http.md) · [진행 기록](docs/progress/20261008-step11c2-credential-versions-http.md) · [서버 인수](docs/progress/20261008-step11c2-server-acceptance.md)

**11-C3 실제 관리 정책과 승인 저장소 HTTP의 서버 격리 인수를 완료했습니다.** Python9개·Go 상위192개/하위567개·필수47개·8개 native phase·race/vet·자원 정리가 통과했습니다. schema9·실제 RO key/authority·UID10001·두 TLS 역할·concrete admitted store로 생성/교체·조회·폐기·재생과 권한/marker/FENCED 차단을 확인했습니다. C1/C2의 synthetic component 회귀는 별도 이력으로 유지합니다. main에는 미등록이고 운영 IAM·관리 참조/사용 guard와 운영 공급·활성화는 후속입니다. [진행 기록](docs/progress/20261008-step11c3-admitted-credential-http.md) · [서버 인수](docs/progress/20261008-step11c3-server-acceptance.md) · [검사 안내](docs/operations/camera-credential-management-check.md)

**11-D1a DB TLS 인증서 후보 준비의 서버 인수를 완료했습니다.** Python23개와 실제 socketpair TLS1.3 상호 인증이 통과했고 prepared → already_prepared에서 같은 후보/인증서 hash와 0700/0600 권한을 보존했습니다. 잘못된 서버명·신뢰되지 않은 CA·client 인증서 누락도 거부했습니다. endpoint IP는 미예약 제안이며 PostgreSQL 역할/source/HBA·실제 mount 검증은 11-D1b입니다. 운영 TLS·서비스·schema는 미전환입니다. [진행 기록](docs/progress/20261008-step11d1a-database-tls-candidate.md) · [서버 인수](docs/progress/20261008-step11d1a-server-acceptance.md) · [준비 안내](docs/operations/camera-database-tls-candidate.md)

**11-D1b PostgreSQL TLS·역할·출처 격리 검사의 서버 인수를 완료했습니다.** 서버 Python18개·필수 Go 구성요소5개/native peer3개·native9개 단계·race/vet가 통과했습니다. 실제 두 역할 TLS와 유지보수 mTLS, 잘못된 출처/인증 거부, 별도 UID·읽기 전용 마운트·컨테이너 재생성과 자원 정리를 확인했습니다. 합성 PKI·격리 DB 검증이며 운영 후보는 읽지 않았고 운영 TLS·IP 예약·서비스는 미변경입니다. 다음은 11-D1c 운영 TLS 공급 위치와 고정 endpoint/source 구성 준비입니다. [진행 기록](docs/progress/20261012-step11d1b-database-tls-boundary.md) · [서버 인수](docs/progress/20261012-step11d1b-server-acceptance.md) · [검사 안내](docs/operations/camera-database-tls-boundary-check.md)

**11-D1c DB TLS 공급 준비의 서버 인수를 완료했습니다.** Python23개와 prepared → already_prepared에서 같은 후보/공급 SHA·볼륨3개를 보존했습니다. 각 실행의 공급 probe3개·UID 간 접근 거부6개·실제 UID/RO·exact bytes·helper 정리와 Compose config가 통과했습니다. 현재 DB/runtime 주소와 비어 있는 maintenance 제안을 확인했고 주소 예약은 수행하지 않았습니다. CA 서명 키는 복사하지 않았으며 운영 TLS는 미전환입니다. 다음은 11-D1d schema7·기존 등록 API와 TLS 전환의 격리 리허설입니다. [진행 기록](docs/progress/20261012-step11d1c-database-tls-supply.md) · [서버 인수](docs/progress/20261012-step11d1c-server-acceptance.md) · [공급 안내](docs/operations/camera-database-tls-supply.md)

운영 기준은 schema7/API0.7.0-device-delete/registry-only-v1·TLS off이며 credential 역할·키 mount·HTTP API·업무 runtime은 미활성입니다. 11-D1c 서버 준비 도구의 현재 process identity 및 schema7/API0.7/TLS off 전제와 전후 재검사가 통과했습니다. 이는 사용자 제공 JSON과 해당 revision의 검사 조건에 근거하며 원격 DB나 receipt 파일을 직접 읽은 결과는 아닙니다. 운영 IAM·TLS·키/역할·admission 공급과 활성화는 후속입니다. Camera Streamlit은 코드가 준비됐고 브라우저 인수는 보류했습니다. 전용 환경은 2026-10-12 정리에서 제거했습니다. [화면 안내](docs/operations/camera-streamlit-test.md)

## 작업 기준

| 경로 | 용도 |
|---|---|
| `src/platform/camera` | 장치·영상 소스·연결 세션, 향후 ONVIF/PTZ·CCTV/XR 입력·녹화 |
| `src/platform/model` | 모델 등록·버전·배포·학습 관리 |
| `src/platform/analysis` | 분석 작업·실행·워커·추적·이벤트 |
| `src/platform/operation` | 운영 API·관제 UI·플랫폼 간 업무 조율 |
| `src/platform/internal/httpapi` | 공통 HTTP·인증·프로세스 종료 코드. 도메인 코드 금지 |
| `src/infra` | 공통 인프라·배포 보조·설치·운영 도구 |
| `docs` | 설계·ADR·계약 설명·운영 절차·작업 이력 |
| `build`, `var` | 생성한 바이너리·로컬 실행 데이터. 버전 관리 제외 |

플랫폼별 테스트·API 명세·Dockerfile·단독 Compose는 해당 플랫폼 폴더에 둡니다. 루트 Compose와 Makefile은 실행 진입점입니다. 플랫폼의 데이터와 업무 로직은 소유 플랫폼이 관리하고 다른 플랫폼은 API로 접근합니다. 자세한 기준은 [작업 규칙](docs/development/working-standards.md)과 [AGENTS.md](AGENTS.md)를 따릅니다.

## 패키지 적용

패키지 적용 명령은 전달 시 채팅에서 별도로 제공합니다. 현재 초기 설치 도구는 기존 파일과 내용이 다르면 쓰기 전에 중단하며, 후속 업데이트는 기준 파일을 검사하는 별도 패치로 전달합니다. 사용자의 백업 제외 지시에 따라 이번 이관 패치와 앞으로의 신규 도구는 자동 백업을 생성하지 않습니다. 과거 패치/활성화 도구는 해당 리비전의 이력입니다. 기존 `.env`와 실행 데이터는 보존합니다.

## 실행

Streamlit 테스트 화면은 Python 3.10 이상과 전용 requirements를 사용해 `var/test-streamlit/python`의 독립 venv에서 실행합니다. 공용 sh_test/Jupyter 환경에 UI 의존성을 설치하지 않습니다. 이번 파일 적용에는 운영 API 재빌드·재시작·DB 전환이 없습니다. 기존 Docker 격리 검사와 과거 활성화 도구는 해당 리비전 전용입니다. 운영 camera 이미지·schema7은 10 인수 상태를 유지합니다.

기본 주소는 `127.0.0.1`, 포트는 camera `18081`, model `18082`, analysis `18083`, operation `18084`입니다. `.env`의 `VMS_BIND_ADDR`와 포트를 바꿀 수 있습니다. 개발용 Bearer 토큰은 생성 후 출력하지 않습니다. 운영 IAM·TLS 구성은 후속 작업입니다.

Docker 없이 Go 1.25 이상과 Python 3.10 이상으로 실행 기반을 검증할 수도 있습니다. 패키지 제작 시 사용한 Go 버전과 검증 결과는 [작업 이력](docs/progress/20260929-p0-foundation.md)에 기록했습니다.

```bash
make test
make vet
make smoke
```

`make smoke`는 네 바이너리를 임시 폴더에 빌드하고 임의의 로컬 포트로 실행하여 인증·계약·종료 동작을 검사한 뒤 프로세스와 임시 파일을 정리합니다. 실제 카메라·GPU·기존 서비스에는 접근하지 않습니다.

## 제공 API

| 플랫폼 | 경로 | 현재 기능 |
|---|---|---|
| 전체 | `GET /health/live`, `GET /health/ready` | 프로세스·HTTP 기반 상태, 인증 불필요 |
| 전체 | `GET /openapi.json` | 플랫폼별 API 명세, 인증 불필요 |
| 전체 | `GET /api/v1/platform` | 구현·예정 기능 구분, Bearer 인증 |
| camera | `POST /api/v1/devices`, `GET /api/v1/devices`, `GET /api/v1/devices/{device_id}` | DB 연결 시 장치 생성·조회·목록, Bearer 인증 |
| camera | `PATCH /api/v1/devices/{device_id}` | expected_version 조건의 표시 이름 수정, 단위 07 운영 활성화 완료 |
| camera | `POST /api/v1/sources`, `GET /api/v1/sources/{source_id}` | 소스 등록·단건 조회, 운영 활성화 완료 |
| camera | `GET /api/v1/sources` | ID 순서·커서·장치 필터를 지원하는 소스 목록, 단위 06 운영 활성화 완료 |
| camera | `PATCH /api/v1/sources/{source_id}` | 소스 expected_version 조건의 이름 수정·전체 소스 응답 재생, 단위 08 운영 활성화 완료 |
| camera | `DELETE /api/v1/sources/{source_id}` | 등록 전용 논리 삭제·최초 결과 재생, 단위 09 운영 활성화 완료 |
| camera | `DELETE /api/v1/devices/{device_id}` | 미삭제 자식이 없는 장치의 등록 전용 논리 삭제·결과 재생, 단위 10 운영 활성화 완료 |
| camera | `POST /api/v1/sources/validate` | CCTV/XR 입력 계약 검증, Bearer 인증 |
| analysis | `POST /api/v1/analysis-jobs/validate` | 소스·모델 버전 참조 형식 검증, Bearer 인증 |

검증 성공은 장치 접속, 저장, 모델 배포 또는 추론 성공을 뜻하지 않습니다. 상세 API 명세와 입력 예제는 각 플랫폼의 `api` 폴더에 있습니다.

[문서 목록](docs/README.md) · [전체 작업 계획](docs/architecture/architecture-plan.md) · [개발·실행 방법](docs/operations/local-development.md)
