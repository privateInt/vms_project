# 11-D1e 수정과 프로젝트 생성 자료 정리

상태: image pin 수정/정리 도구 서버 검사 및 정리 완료 · D1e Compose 준비 실패 · 기능 개발 중단/이관 · 운영 TLS 미전환

최신 결과: 서버 정리는41개 대상·472,388,543 logical bytes 제거로 완료됐다. 준비 dry-run은 통과했으나 첫 apply는 REGISTRY_TLS_COMPOSE_SECRETS_CHANGED/compose_validation에서 실패했다. 이 아래의 수정/정리 계획은 작성 당시 이력이며 현재 다음 작업은 [Codex 이관 기록](20261012-codex-handoff.md)을 따른다.

## 서버 실패와 수정

사용자 제공 D1e 압축 checksum OK·applied/written10/pending0, patch 이력 var/patch-backups/step11d1e-31xdm11n을 확인했다. Python27개는1.361초에 OK였다. 첫 준비 확인은 code=REGISTRY_TLS_PREPARATION_FAILED/failed_stage=accepted_source로 중단됐으며 준비 파일/control volume과 운영 변경·TLS 활성화는 false다. set-e로 두 apply 실행은 진행되지 않았다.

첨부 현재 프로젝트의 manifest SHA는 efe24aa1cbba6eae6ab8363e0f618d93c64ddd558da4ed070beb1e7954ae78c8이고 tracked516개 파일의 hash가 모두 맞았다. 소스 인수 검사는 성공했다. 실제 첨부 .env의 VMS_CAMERA_IMAGE는 D1d에서 인수한 immutable API image와 같았지만 초기 활성화용 enabled_environment가 이를 일괄 사용자 지정 설정으로 거부했다. 원문 환경/비밀값은 공개하지 않고 그 조건을 재현했다.

새 validate_current_environment는 정확한 active Compose와 인수된 API image pin만 허용한다. 다른 image·중복 설정·다른 Compose/project 설정은 거부한다. .env를 수정하거나 조건을 느슨하게 해 다른 image를 허용하지 않는다. coordination_lock/docker_preflight/environment_binding 단계를 구분하고 안전한 ActivationError code를 보존해 같은 실패가 소스 오류로 표시되지 않도록 했다. 신규 준비 검사30개가 통과했다.

## 실제 첨부 용량

| 항목 | 일반 파일 bytes |
|---|---:|
| 원본 압축 크기 | 156,703,980 |
| 압축 내부 파일 합계 | 476,920,567 |
| Streamlit 전용 환경 | 431,066,828 |
| 선택한 생성 자료/백업/로그/캐시 | 472,388,543 |
| 정리 후 기존 자료 합계 | 4,532,024 |

선택한 생성 자료는 기존 일반 파일 bytes의 약99.05%다. 이 숫자는 첨부 원본의 논리적 파일 크기이며 서버의 실제 디스크 회수량은 filesystem/block/hardlink에 따라 다를 수 있다. 이번 코드/문서 추가분은 별도다. DB Docker volume의 크기를 합산한 값이 아니다.

## 정리 범위와 실행 파일

cleanup_project_artifacts.py는 build·src의 __pycache__·과거 patch/activation/key 백업·UI 패키지 복구 자료·백업 검토 초안·기존 격리 검사 폴더의 .log만 선택한다. remove-ui-environment 옵션은 var/test-streamlit과 그 상태 JSON/설치 log도 제거한다. UI 코드·requirements·검사 JSON 결과는 남는다. 사용 중인 전용 UI 환경은 프로세스 인자/CWD/접근 가능한 maps로 확인해 제거를 차단한다. 다른 동일 UID 프로세스의 접근 불가능한 maps는 추가 관찰에서 제외하고, cmdline 확인은 유지한다.

.env·현재 registry 접속 파일·credential 암호화 키·TLS 후보/공급·준비 파일·authority·활성화 receipt·사용자 실행 자료는 보존한다. Docker container/image/network/volume이나 Conda sh_test·Jupyter 환경을 정리하지 않는다. 선택한 경로의 mount/상위 또는 최상위 symlink·특수 파일·소스/대상 변경은 거부한다. 전용 환경 내부의 interpreter symlink는 그 링크만 제거하고 외부 interpreter는 보존한다. 같은 준비 coordination lock을 사용하며 기존 파일의 권한을 바꾸지 않는다.

정리는 새 백업 없이 수행한다. 제거된 과거 백업을 통한 수동 롤백/복구는 사용할 수 없으며, 유지한 활성화 receipt와 검사 JSON은 작은 인수 증거다. 중단 시 완료된 대상 수를 보고하고 원문 예외·비밀값은 출력하지 않는다. 반복 실행은 이미 제거된 대상을 다시 만들지 않는다.

## 검증과 전달

정리 검사12개는 dry-run/실제 제거·재실행·키/DSN/receipt/사용자 자료와 권한 보존·symlink/mount·사용 중 UI·source 충돌·중단 결과·소스 압축 제외 범위를 검사했다. 준비 수정30개는 실제 첨부 환경이 내용 변경 없이 통과함을 재현하고, 기존 PKI/파일/Compose fixture를 회귀 검사했다. Python3.10 문법·control shell 구문·patch 적용/재적용·충돌/중간 실패와 무백업 적용을 확인했다. Go/API/SQL/운영 Compose 원본은 변경하지 않았다.

전달 패치는 소스 전체 hash를 검사한 뒤 메모리에서 변경 전 파일을 잠시 보관해 쓰기 실패를 되돌린다. 디스크 patch backup은 생성하지 않는다. 현재 source만 담은 경량 압축도 제공한다. 경량 압축은 manifest에 등록된 코드/문서/구성만 포함하고 .env·var·build·설치된 Python 환경/비밀 파일을 포함하지 않는다. 이는 기존 서버에서 보존한 실행 설정을 대체하는 자료가 아니다. 적용 명령은 채팅에 제공한다.

서버에서 정리한 뒤 D1e 준비를 재실행해 prepared→already_prepared·control volume1→0·같은 SHA를 확인한다. 운영 TLS 전환이나 D1f 인수는 이번 결과에 포함하지 않는다. Streamlit 브라우저 인수는 계속 보류하며 나중에 prepare_camera_test_environment의 apply로 전용 환경을 재생성할 수 있다. 백업 추가 작업은 사용자 지시대로 제외한다.

[정리 안내](../operations/project-artifact-cleanup.md) · [D1e 준비 기록](20261012-step11d1e-registry-tls-preparation.md)
