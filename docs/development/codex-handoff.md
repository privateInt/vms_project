# Codex 개발 이관 — 2026-10-12

2026-10-13 추가: 공통 규칙·에이전트 구성·템플릿과 VMS 세부 규칙을 [Codex 문서](../codex/README.md)에 정리했다. 현재 준비 상태는 [준비 상태 문서](../progress/20261013-codex-preparation.md)에서 관리한다. 서버 실행 구성 확인과 사용자 사전 알림 전에는 본격 기능 개발을 시작하지 않는다. 아래 이관·운영 보류·백업 제외·H01 근거는 유지한다.

상태: 기능 개발 중단·이관 자료 준비. 후속 Codex가 아래 backlog를 기준으로 개발을 재개한다. 이 문서 자체는 TLS 오류 수정이나 운영 활성화의 증거가 아니다.

## 목표와 사용자의 최신 결정

목표는 camera / model / analysis / operation 네 플랫폼을 독립적으로 구현하고, CCTV·스마트글래스 영상 입력 → 모델 배포 → 분석 실행 → 관제·근거 영상 확인으로 연결하는 VMS다. 최초 통합 목표는 CCTV 2대, 실제 스마트글래스 1대, 모델 2종 및 영상 소스-모델 다대다 연결이다. CCTV는 ROI 침입·쓰러짐, XR은 객체 검출을 대상으로 한다. 실장비·GPU 성능이나 상용 운영 완료를 이미 달성한 상태는 아니다.

| 사용자 결정 | 적용 |
|---|---|
| Codex가 자동 개발 진행 | 작은 단위마다 구현·검증·기록 후 승인된 backlog를 계속 수행 |
| 백업은 고려하지 않음 | 백업 추가 설계·복구 검토·자동 백업 생성을 범위에서 제외 |
| 불필요한 파일 최대한 제거 | 기존 정리 완료. 재생성 가능한 환경·캐시를 배포 소스에 포함하지 않음 |
| 플랫폼별 Streamlit 테스트 front page | API 기능이 준비된 시점에 각 소유 플랫폼에 구현 |
| 외부 작업 중 Jupyter Lab 포트만 접근 가능 | UI 브라우저 인수 보류. relay·proxy·새 포트 공개를 임의로 추가하지 않음 |
| 구조·플랫폼 책임 유지 | 구현·테스트·스크립트는 src, 문서는 docs. 플랫폼 간 API 계약 사용 |

백업 제외는 현재 키·접속 설정·DB·사용자 자료를 삭제하거나 인증·재시도·동시성 검사를 제거한다는 의미가 아니다. 과거 복원 코드/문서는 참고 이력으로 유지하되 이번 backlog의 선행 작업으로 다시 선택하지 않는다. 필요 없는 추가 인프라 검토로 카메라 기능 개발을 지연시키지 않는다.

## 플랫폼별 실제 진행 상태

| 플랫폼 | 확인된 구현·인수 | 남은 핵심 기능 |
|---|---|---|
| camera | 운영 API 0.7.0-device-delete / schema7 / registry-only-v1. 장치·소스 생성/조회/목록/이름 수정/논리 삭제·재생 인수. credential storage·admission·schema9 marker·lease·관리 HTTP는 격리 인수. TLS 후보/공급 준비와 schema7 TLS 리허설 인수. Camera Streamlit 코드 있음 | D1e 준비 오류, 운영 TLS 및 credential 공급/main 통합·사용 관계 guard, ConnectionConfig, SourceSession, 실제 RTSP·ONVIF/PTZ·XR 입력, 녹화/클립/재생 |
| model | 독립 HTTP API·health/OpenAPI/인증 기반. 기능 manifest는 model_registry / deployment_runtime / training을 planned로 표시 | 모델·버전 영속 관리, 아티팩트 참조, 배포/readiness·실제 추론 또는 기존 모델 플랫폼의 명시적 API 연동 |
| analysis | 독립 HTTP 기반, POST /api/v1/analysis-jobs/validate 입력 형식 검사. 응답은 contract_only, resource_created=false | 영속 작업, 실제 참조 확인, 제어 루프·워커 lease·추론·추적·규칙·이벤트 |
| operation | 독립 HTTP 기반. orchestration / operator_ui / notifications는 planned | 플랫폼 API 조율, 소스-모델-분석 사용자 흐름, 관제·실패 원인·이벤트·조치·알림 |

퍼센트로 전체 완성도를 추정하지 않는다. 네 API가 실행된다는 사실은 네 업무 플랫폼이 완성됐다는 뜻이 아니다. 등록 전용 삭제 guard는 세션/소비자 생성이 없는 현재 릴리스의 전제이므로, 연결·분석 기능 추가 전에 실제 사용 관계와 삭제/폐기 경쟁 조건을 해결한다.

## 멈춘 지점과 서버 증거

최신 근거는 사용자 제출 `붙여넣은 텍스트(1)(20261012-061522).txt`이다. 원격 서버에 직접 접속해 다시 측정한 결과는 아니다. 요약 원본은 [서버 증거 JSON](../progress/20261012-codex-handoff-server-evidence.json)에 보존했다.

| 항목 | 최신 결과 |
|---|---|
| 서버 source manifest SHA | 654c8864cf1330b2e21beb985ed3206e01140f03279eb79bb72ff0e9eee7027e |
| image pin 수정/정리 패치 | checksum OK, applied, written11, pending0, backup_created=false |
| 서버 Python 검사 | cleanup12개 / D1e 준비30개 모두 OK |
| 정리 | cleaned, 대상41개 제거, 파일 항목12,021개, 논리적 크기472,388,543 bytes |
| UI 환경 | var/test-streamlit 제거. UI 소스·requirements 보존, 브라우저 인수 보류 |
| D1e dry-run | planned. 기존 TLS 공급·현재 registry 재검사 성공, 운영 미변경 |
| D1e 첫 apply | failed / REGISTRY_TLS_COMPOSE_SECRETS_CHANGED / compose_validation |
| D1e 두 번째 apply | set-e로 실행되지 않음 |
| 운영 전환 | cutover_preparation_ready=false, database_tls_activated=false, credential_api_activated=false |

472MB는 논리적인 파일 크기이며 실제 filesystem의 회수량 측정은 아니다. 정리 도구는 .env·키·TLS 공급·receipt·검사 JSON·소스를 보존했다고 보고했다. Docker 자원과 공유 Conda/Jupyter는 변경하지 않았다. 전용 UI 환경을 다시 만들기 전에는 기존 interpreter 경로를 사용하지 않는다.

## 첫 작업: D1e 오류와 실패 후 재실행

수정 대상은 `src/infra/tools/prepare_camera_registry_tls_cutover.py`와 옆의 `test_prepare_camera_registry_tls_cutover.py`다. 현재 secret 검사는 Compose 결과의 target을 source 이름과 문자 그대로 비교한다. 테스트의 FakeDocker는 target을 생략하므로 실제 Compose 결과의 정상화 형태를 놓칠 가능성이 있다. 정확한 원인은 서버의 **비밀값을 제거한 source/target 형태**와 실제 Compose 버전으로 확인해야 한다. 마지막 로그는 normalized target 원문을 제공하지 않았다. 이 가설을 확정 원인으로 보고하지 않는다.

작업 순서:

1. AGENTS·작업 기준·이 문서·backlog·증거 JSON을 읽고 실제 source hash와 환경을 확인한다. Git 사용 시 기존 사용자 변경을 보존한다.
2. 실제 Compose config는 환경/비밀값을 포함할 수 있으므로 통째로 stdout·문서·커밋에 내보내지 않는다. 필요한 서비스별 secret source/target·파일 경로·Compose 버전만 안전하게 추출해 검사를 재현한다.
3. Linux 컨테이너의 정확한 기대 mount 경로가 같은 경우에만 정상화를 허용한다. 다른 source/target, 중복, 예상 외 mount/파일, 경로 조작과 실제 mount 변경은 거부한다. 인증·image pin·source·UID/RO·다른 플랫폼 구성 검사도 유지한다.
4. **실패 후 prepared-v1을 먼저 관찰한다.** 현재 흐름은 prepare_files → validate_compose → prepare_control이다. 따라서 오류 전에 준비 파일이 쓰였을 수 있고 control volume은 이번 호출에서 생성 단계에 도달하지 않았다. 실제 디렉터리/volume 존재는 별도 확인한다. 실패 응답의 ready=false를 “파일 없음”으로 해석하지 않는다.
5. receipt·DSN·Compose·HBA/ident·기존 운영 snapshot·공급 hash·권한을 재검사하고 안전한 재사용 또는 사용되지 않은 준비의 제한된 갱신을 설계한다. 전체 var 삭제·receipt 수동 편집·검사 제거로 해결하지 않는다. 이전 준비 source와 현재 source의 차이가 검증된 경우에만 재사용을 허용한다.
6. 관련 단위/회귀 검사와 실제 서버 준비 검증을 수행한다. prepared → already_prepared, 같은 preparation SHA/control volume, 생성1 → 0 또는 이미 검증된 volume의 0 → 0, 운영 서비스/DB/환경/기존 TLS 공급 미변경을 확인한다. 이후 D1e 완료 기록을 남긴다.

이관 문서/manifest 반영도 source revision을 바꾼다. 현재 bundle은 `prepared_source_revision`을 hash에 포함하고 기존 파일은 exact bytes로 검사한다. 그러므로 문서 패치 반영 후 **기존 도구의 apply를 그대로 재실행하지 않는다**. Codex가 재실행 호환성까지 해결하는 것이 첫 단위의 완료 조건이다.

직전 planned metadata: preparation SHA `fa4b07e802f1be09423e5c02d345ada0cd3308116ffadca283a01d6583c0d1cc`, control volume 제안 `vms-project-camera-registry-tls-control-fa4b07e802f1be09`, 준비 경로 `var/camera/registry-tls-preparations/prepared-v1`. 이는 제안 결과의 식별자이며 실제 receipt의 존재·활성화 증거를 대체하지 않는다.

## 환경과 보존할 기준

| 항목 | 기준 |
|---|---|
| 원격 개발 서버 | simsys4090, /home/shshin/workspace/vms_project |
| Python | Conda sh_test, Python3.10. 새 Python 코드는 3.10 호환 |
| Go | src/platform/go.mod의 Go1.25.0과 go.sum 기준. race에는 C toolchain 필요 |
| Docker | 서버에서 Engine/Compose 사용. 실제 버전과 현재 서비스 확인 후 격리 project 사용 |
| 기본 HTTP | loopback camera18081 / model18082 / analysis18083 / operation18084 |
| 운영 API image | sha256:708d5a53f3dcc3d22dca775ef2825bcd271a68c7c3777cf8a6a89bb6933aa7d6 |
| 운영 DB image | sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201 |
| D1d 인수 revision | 1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159 |
| D1c 공급 SHA | 22ccacd8f4ec043219d2eef4f21378772c0705e26b1b2fa906d5b2b57aad4a6e |

현재 운영 schema는7, 일반 credential storage의 개발 schema는8, admission 통합 대상은9다. 이 세 숫자를 하나로 덮어쓰지 않는다. 최신 source 전체를 재빌드해 기존 운영 schema7에 즉시 실행하지 않는다. global manifest의 이전 인수 revision·파일 hash는 단순한 장애 회피 목적으로 바꾸지 않는다.

보존 대상은 .env, var/camera/secrets, credential-keys, database-tls-candidates, database-tls-supply, registry-tls-preparations, authority/lock/활성화 receipt 및 Docker camera data·TLS volumes다. 비밀값·영상·모델 가중치는 소스 압축/커밋/공유 결과에 넣지 않는다.

## 실행 범위와 중단 조건

이번 Codex 자동 개발의 범위는 코드·테스트·문서·자신이 만든 격리 자원이다. 운영 서비스 재시작·운영 schema/HBA/Compose/.env 반영·운영 네트워크 전환은 현재 이관의 실행 범위에 포함되지 않는다. 향후 사용자 지시가 이를 명시적으로 포함하면 그 지시와 이미 제공된 권한을 따른다.

일상적인 코드 수정·로컬 검증·문서·격리 검사마다 확인을 요청하지 않는다. 승인된 backlog를 계속 진행하고 변경/검증/미완료를 기록한다. 환경이나 입력이 부족하면 독립적인 코드 작업을 수행할 수 있지만, 실제 검증이 필요한 단계는 blocked로 남긴다. 다음 경우에는 의존하는 실행을 멈추고 필요한 입력·조건을 구체적으로 보고한다.

- 사용자 변경과 patch/source hash 충돌, 예상하지 않은 현재 운영 image/UID/network/schema/snapshot 변화.
- 기존 준비가 사용/활성화됐거나 receipt·파일·권한·volume 소유권을 확실하게 검증할 수 없는 경우.
- 실제 장비·endpoint/자격증명·SDK·모델 파일·GPU 또는 운영 실행 범위가 필요한데 제공되지 않은 경우.
- 테스트 실패/비밀 유출/다른 플랫폼 데이터 직접 접근이 확인된 경우. 검사를 지우거나 성공값을 고정하지 않는다.

Go 변경은 관련 테스트와 vet, 프로세스/라우팅 변경은 smoke를 수행한다. DB·TLS·권한 경계 변경에는 실제 Docker/PostgreSQL 격리 검증을 붙인다. 문서만 변경했으면 소스 hash·링크·패치 검증으로 충분하며 전체 Go/DB 검사를 불필요하게 재실행하지 않는다.

단위마다 docs/progress에 목표·변경 파일·실제 검증 환경/명령/결과·미완료·다음 작업을 기록하고 project-manifest.json의 files hash를 갱신한다. 구현 완료, 모의/합성 검사, 서버 격리 인수, 운영 활성화, 실장비 인수를 구분한다. 자동 개발 중에는 이 기록을 갱신하며 backlog의 상태와 최신 다음 작업을 함께 유지한다.

## 이관 자료의 사용

기존 서버에서 이어갈 때는 문서 이관 패치를 적용한 **기존 프로젝트**를 Codex의 작업 폴더로 사용한다. 실행 입력과 Docker 자원은 그 서버에 남아 있다. 경량 source 압축은 source-only 작업/검토용으로, .env·var·build·설치 환경·키·DB·실행 receipt가 없다. 별도 폴더에서 풀고 작업한다. 운영 폴더 위에 전체 소스를 덮어쓰는 배포 자료로 사용하지 않는다.

[자동 개발 backlog](codex-backlog.md) · [첫 시작 지시문](codex-start-prompt.txt) · [전체 아키텍처](../architecture/architecture-plan.md) · [진행 기록](../progress/20261012-codex-handoff.md)
