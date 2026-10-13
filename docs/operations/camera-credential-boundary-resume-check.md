# 복원 후 격리 업무 재개 검사

작성일: 2026-10-07 · 단위 11-B3c3d2c · 서버 인수 완료

## 전제와 실행 범위

d2b owner environment fix revision172e084b…의 서버 Python33·restore8/native15·race/vet 성공이 선행 조건이다. 이번 patch는 source만 갱신하며 운영 API(schema7/device-delete), DSN/keys/HBA/authority를 활성화하지 않는다. 사용자 적용 명령은 채팅으로 제공한다.

기존 test_camera_credential_boundary_restore.py는 별도 disposable DB에서 uses1 후보의 OPEN까지 거부하고 마지막 PREPARED/closed/NOLOGIN 상태를 유지한다. 이어 test_camera_credential_boundary_resume.py는 새로운 Compose project/DB/synthetic key·cert·password를 만들고 원래 복원 흐름부터 unused candidate까지 다시 수행한다. 앞 검사의 사용량을 초기화하거나 그 후보를 재개에 재사용하지 않는다. host port는 열지 않는다. 매 검사에서 실패 diagnostics를 private log에 수집하고 unique project의 volumes/containers를 제거한다.

## d2c 완료 기준 — 서버 통과

| 항목 | 기대 결과 |
|---|---|
| Python runner unit | 36개 통과 |
| 복원 회귀 | required_restore_tests_passed8/native15·used_candidate_open_rejected_without_reset=true·final PREPARED/closed/NOLOGIN |
| 새 재개 검사 | required_resume_tests_passed12/native_boundary_resume_phases_passed24·credential13·race/vet=true |
| OPEN 순서 | uncommitted marker/다른 OPEN 쌍 거부, OPEN 후 업무 역할 NOLOGIN 유지 및 실제 runtime source 인증 거부, 새 관리 process 재시도 후에도 거부 |
| 경계와 런타임 | runtime 정확한 source/target/two roles/SCRAM TLS; maintenance source의 runtime role 및 runtime source의 maintenance role 거부, 잘못된 password/plaintext/postgres DB 거부 |
| 업무 | UID10001/caps0·exact RO keys/authority·public whole-operation guard, restored HMAC replay·fresh key version2 write/reference/replay, runtime marker/budget mutation 거부 |
| 재실행 | 관리 재시도와 새 runtime process replay 후 candidate uses1 유지, historical/new ciphertext 보존 |
| 종료 | final_admission_state=OPEN/final_candidate_budget_uses1, isolated_resources_removed=true |

OPEN/LOGIN/actual write는 격리 DB에서만 발생한다. production_services_modified, production_database_modified, production_keys_loaded, production_admission_state_created, production_hba_modified, credential_api_activated, production_restore_fence_implemented, business_runtime_ready는 false다. 실제 복원이 중간 실패하면 isolated_restore_outcome=uncertain이고 후속 candidate/runtime 단계는 실행하지 않는다. 복원 후 runtime 단계가 실패해도 실제 복원 완료 사실은 보존하되 전체 인수 flag는 표시하지 않는다. Logs에는 synthetic private input이 존재할 수 있으므로 그대로 공유하지 않는다.

## 남은 범위

서버 Docker 인수를 마쳤다. 다음 단위는 운영 키/권한/단일 endpoint/source/HBA/authority 공급 설정의 읽기 전용 사전점검이다. 공급·full restore fence 운영 절차·schema9 전환은 이후 별도 rehearsal·activation으로 진행한다. 자격증명 API와 실제 연결 설정 업무는 아직 미활성이다. Streamlit 브라우저 인수는 deferred이며 Jupyter 중계는 추가하지 않는다.


## 최신 실행 결과

user 제공 report의 checked_revision은 7d3168b40749aa886f6c359cf12a1bd43e0dda634188fdd1e2998a554669e277이며 두 검사 모두 status=passed다. 복원 project=vms-boundary-restore-test-c37181c59432(top161/sub410), 재개 project=vms-boundary-resume-test-67275dc90db2(top163/sub410)다. 각 resources_removed=true이며 성공 실행에서는 failure diagnostics를 수집하지 않았다. 상세 flag·보고서 경로는 [인수 기록](../progress/20261007-step11b3c3d2c-server-acceptance.md)에 보존했다. 이 인수 문서 적용은 검사를 재실행하거나 서비스를 전환하지 않는다.
