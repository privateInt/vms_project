# 단위 11-B3c3d2c — 서버 인수 완료

작성일: 2026-10-07 · 사용자 서버 로그 인수 · 문서/메타데이터만 반영

## 결과와 적용

사용자가 simsys4090의 sh_test에서 controlled boundary resume patch를 적용했다. written16/pending0, backup=/home/shshin/workspace/vms_project/var/patch-backups/step11b3c3d2c-luqkx700이다. service_restart_performed/runtime_activation_required/database_schema_modified=false다. boundary Python unit95개가 통과했다.

두 native report의 checked_revision은 7d3168b40749aa886f6c359cf12a1bd43e0dda634188fdd1e2998a554669e277이다. 같은 코드에서 서로 독립된 disposable project/DB/key를 사용했으며 두 검사 모두 status=passed, schema9/legacy8, Go race/vet=true, credential13, native roles/concurrency verified=true다.

| 검사 | 프로젝트 | top/subtests | 필수/native phase | 최종 격리 상태 |
|---|---|---|---|---|
| 복원 회귀 | vms-boundary-restore-test-c37181c59432 | 161 / 410 | 8 / 15 | PREPARED, target closed, 두 runtime role NOLOGIN |
| 복원 후 업무 재개 | vms-boundary-resume-test-67275dc90db2 | 163 / 410 | 12 / 24 | OPEN, candidate key uses1 |

## 인수한 범위

복원 회귀는 실제 dump/key restore·snapshot budget rewind·external authority/HBA 보존·off-source 거부·historical ciphertext/HMAC 보존·independent fresh key/incarnation·PREPARED-before-budget/marker·restored old key disabled·same candidate retry를 확인했다. 사용된 후보의 budget reset/OPEN, 잘못된 backup marker, 손상 archive를 거부했고 data/authority를 보존했다. 마지막에 target을 닫고 계정을 잠갔다.

재개는 unused committed candidate만 OPEN으로 전환하고 uncommitted marker를 보정하지 않음을 확인했다. durable OPEN 후에도 계정이 NOLOGIN인 중단 상태에서 실제 runtime 인증을 거부했고 동일 OPEN의 새 관리 process retry 후에도 잠긴 상태를 유지했다. 그다음 source-pinned runtime HBA/LOGIN을 재개하고 actual separate runtime UID10001·exact RO key/authority mount·두 실제 TLS role pool·public whole-operation admission으로 업무를 실행했다.

유지보수 source의 runtime role, runtime source의 maintenance role, 잘못된 password, plaintext, control postgres DB 인증을 거부했다. 복원된 HMAC/history replay, 새 키 version2 저장·reference·replay, runtime의 marker/budget mutation 거부, post-write OPEN retry의 budget 보존, 새 runtime process의 durable replay가 모두 true다. 실제 historical/new ciphertext를 보존했고 final OPEN/uses1을 확인했다. owner PG environment absence도 두 검사에서 true다.

두 검사 모두 database_and_key_restore_performed=true/isolated_restore_outcome=completed, isolated_resources_removed=true다. 성공 실행이므로 isolated_diagnostics_collected=false는 정상이다.

## 기록 위치

서버 복원 report: /home/shshin/workspace/vms_project/var/camera/credential-boundary-restore-checks/vms-boundary-restore-test-c37181c59432.json

서버 복원 log: /home/shshin/workspace/vms_project/var/camera/credential-boundary-restore-checks/vms-boundary-restore-test-c37181c59432-nev870s0.log

서버 재개 report: /home/shshin/workspace/vms_project/var/camera/credential-boundary-resume-checks/vms-boundary-resume-test-67275dc90db2.json

서버 재개 log: /home/shshin/workspace/vms_project/var/camera/credential-boundary-resume-checks/vms-boundary-resume-test-67275dc90db2-czjoo2p9.log

이번 인수 기록은 사용자 JSON을 근거로 한다. 원본 private log를 새로 읽었거나 운영 상태를 직접 조회했다는 주장은 하지 않는다. 기존 runner가 고정한 restore 선행 revision172e084b… 영수증은 유지하고 이번 7d3168b4… 복원 회귀를 latest validated 필드에 따로 기록한다. accepted revision은 실제 검사된 코드 영수증이며 문서 패치 후 프로젝트 SHA와 별개다.

## 운영 상태와 다음 작업

production_services_modified, production_database_modified, production_keys_loaded, production_admission_state_created, production_hba_modified, credential_api_activated, production_restore_fence_implemented, business_runtime_ready는 두 검사 모두 false다. network_packet_filter_verified도 false다. 최종 OPEN은 격리 재개 DB의 상태이며 운영 카메라 API는 기존 schema7/0.7.0-device-delete다. 실장비 연결·영상 수신·자격증명 HTTP API·운영 전환을 완료한 것으로 표시하지 않는다. Streamlit browser acceptance는 deferred이며 Jupyter 중계는 추가하지 않는다.

다음 단위는 11-B3c3d3: 운영 키·authority·DB 접속/role/TLS/source·HBA 공급 설정의 읽기 전용 사전점검이다. 누락/불일치를 고정된 안전한 코드로 보고하고 운영 key/authority를 생성하거나 API/DB/HBA를 바꾸지 않는 것이 완료 기준이다. 이후 실제 공급·full restore fence 절차·schema9 전환을 별도 rehearsal/activation으로 진행한다. 문서 패치 적용 명령은 채팅에서만 제공한다.

## 인수 기록 패치 검증

README/계약/검사 안내/진행 기록/프로젝트 메타데이터만 갱신했다. 제품·테스트·SQL·Compose 원본은 유지한다. baseline398개를 확인하고 patch dry-run·백업 적용·재실행·사용자 편집/새 경로 충돌·보호 env/key/authority sentinel 보존·helper8개 및 기존 두 native runner의 source 검사를 확인했다. 문서만 바뀌어 Go/Docker 검사는 반복하지 않았다.
