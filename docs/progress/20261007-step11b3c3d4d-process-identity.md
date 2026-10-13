# 단위 11-B3c3d4d — 현재 컨테이너 프로세스 UID/GID 검증

작성일: 2026-10-07 · d4c 공급 검토 초안과 d4d 현재 프로세스 identity 서버 인수 완료

## 선행 인수

사용자 simsys4090/sh_test 로그에서 d4c written8/pending0, backup=var/patch-backups/step11b3c3d4c-ohf5thr7, 테스트90개 OK와 검토 초안 prepared 저장을 인수했다. source SHA0670c667d5169780ec50e338f029ce118ef19e7ed79a245ff1eccb5f5d887326 / tracked418개를 이번 delta baseline으로 사용한다. review SHAe496c0142a0c8100c7ff1022d2bdbb1b2bcea46714d6a9ead36fe9b04d32b4d9, incomplete/null40개/후보7개/후속 확인5개 범주를 유지한다. 실제 SupplyPlan·authority·키 사본을 만들지 않았으며 운영 변경과 활성화는 모두 false다.

## 이번 결과

[현재 프로세스 identity 검사](../operations/camera-credential-process-identity.md)를 추가했다. accepted source와 기존 운영 사실 조사를 새로 확인하고 camera-api/camera-db init PID의 Docker top과 호스트 procfs를 대조한다. 검사자/대상의 전체 identity UID/GID mapping, 실제 effective/filesystem UID/GID, 전체 container ID cgroup component·독립 PID namespace의 내부 PID1과 lifecycle·metadata 안정성을 확인한다. PID·raw map·comm·환경·명령행을 보고서에 저장하지 않는다. 현재 init scope만 검증하며 미래 credential binding receipt를 만들거나 worksheet를 자동 채우지 않는다.

권한 부족·부분 mapping·host PID/cgroup visibility 부족은 blocked로 분리한다. 관측 UID/PID/starttime/inode/source가 변하거나 검증된 metadata를 다시 읽을 수 없으면 실패로 중단한다. NOFOLLOW·procfs magic·bounded readonly file IO를 사용하고 권한·mount·UID·sudo 자동 수정을 제공하지 않는다. private identity 보고서와 coordination lock 이외의 쓰기는 없다. 기존 src/Go/SQL/Compose/API와 운영 schema7/API0.7.0-device-delete를 유지한다.

## 검증

새 unittest32개와 기존 공급 조사90개를 통과했다. synthetic Docker/proc records로 source acceptance, owned init/top/cgroup, UID/GID 및 namespace mapping, 한 대상만 blocked, PID 재사용·inode/starttime drift, observer·top·source/env/receipt/key/container 변화, metadata permission loss, secret-safe 출력·키 미읽기·기존 reports/worksheet 보존을 검증했다. 실제 Linux procfs read/fstatfs, 허용 metadata 목록, symlink·비procfs file·크기 제한을 확인했다. 로컬 Python3.12이며 코드/테스트는 Python3.10 문법으로 검사한다.

로컬에는 Docker가 없고 제한된 UID namespace/PID view가 있으므로 실제 운영 UID mapping이 검증됐다고 표시하지 않는다. 서버 검사는 다음 실행 결과로 인수한다. Go/SQL/프로세스 라우팅 변경이 없어 기존 race/vet/native restore·resume 인수를 유지하며 관련 Python 회귀만 실행한다. 새 Python 의존성이나 UI 환경 변경은 없다.

적용 tree의 첫 회귀 실행에서 기존 native ps 검사가 로컬 PID view의 self lookup 오류로 한 번 실패했다. 별도 실제 ps 조회와 기존90개 회귀를 확인한 뒤 동일 패키지 검사를 재실행해 새32개·기존90개 모두 통과했다. 운영 소스나 기존 테스트를 수정해 우회하지 않았다. 이 환경 관찰은 서버 인수 결과로 취급하지 않는다.

패키지는 baseline418개와 delta9개를 hash 검증한다. dry-run·백업 적용·재실행, baseline 사용자 편집과 새 경로 충돌 거부, env/key/authority sentinel 보존, helper8개와 실제 적용된 payload32+90개를 확인한다. 운영 파일과 보호 입력은 패키지에 포함하지 않는다.

## 다음 완료 기준

서버 identity_readiness와 각 process 결과를 인수한다. verified이면 현재 UID/GID 근거를 공급 위치·maintenance identity/group·물리 경로 및 완전한 backup topology 검토에 연결한다. blocked이면 해당 code가 가리키는 host visibility/permission 전제를 구체적으로 검토하며 추정값을 승인하지 않는다. 프로세스 관찰만으로 미래 mounted key·TLS/source/role/authority binding을 완료 처리하지 않는다. 공급 보호 파일 준비·authority bootstrap·schema9 cutover·credential HTTP API·full production restore fence는 후속이다. Streamlit browser acceptance는 deferred이며 중계를 추가하지 않는다. 실행 명령은 채팅에서만 제공한다.

## 서버 인수 — 2026-10-07

사용자 simsys4090/sh_test 로그에서 written9/pending0, backup=var/patch-backups/step11b3c3d4d-b95deza3, 새32개와 공급90개 OK를 인수했다. source SHA8048bc6efcbfc0a227c2f10af225056fda294cf7b5b9ddc2dc9bd1c4786dcec3 / tracked422개다. 실제 조사 status=inspected/inspection_completed=true/identity_readiness=verified/verified_process_count=2이며 observer mapping도 true다.

camera-api의 effective/filesystem UID/GID는65532:65532, camera-db는999:999다. 두 init process의 전체 identity mapping·cgroup·독립 PID namespace를 확인했고 blockers는 비었다. identity_scope=current-container-init-process, credential_runtime_binding_verified=false를 유지한다. 실제 schema7/API0.7.0-device-delete와 모든 운영 변경 false·activation_allowed=false를 확인했다. 권위 bootstrap·미래 key mount·전체 복원 fence·credential API를 인수한 것으로 승격하지 않는다.

다음 독립 단위는 [d4e DB 볼륨 마운트 대조](20261007-step11b3c3d4e-database-mount-topology.md)다. 현재 UID 근거를 사용하되 실제 host path/mount와 전체 backup 범위를 분리해 확인한다.
