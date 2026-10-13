# 유지보수 경계 아래 DB·키 복원 격리 검사

11-B3c3d2a startup fix의 서버 인수 SHA08d9f3ae44d7a7f7d3d77a0d47606bfba6208ab47e3bf7385ba1e9144f148002를 전제로 한다. 패치 적용은 source 파일만 변경하며 운영 schema7/API·서비스·실제 키/HBA를 전환하지 않는다. 명령은 채팅에서 제공한다.

검사 도구는 unique project의 PostgreSQL17.11/Golang build, 임시 PKI·keys·authority·DB, 고정 owner/source와 UID10001 RO probe만 사용한다. build에서 full Go vet/race regression을 실행하며 phase binary는 test2json의 정확한 이벤트로 확인한다. LOCAL proof·순서/부모/prefix 불일치·skip/missing phase·과거 fail·source drift·cleanup 실패는 passed로 인정하지 않는다.

필수 native 이벤트15개는 fixture prepare, keys, seed, history, backup, advance, client-before, fence, client-closed, restore, client-open, prepare, commit, retry, client-closed 순서다. 마지막 probe는 PREPARED/NOLOGIN 및 닫힌 target에서 off-source 인증 거부를 확인한다. required_restore_tests_passed=8은 storage unit3/phase parent4/crypto material1을 뜻하며 legacy credential13도 필요하다.

검사 성공 시 actual_dump_and_key_restore_verified, snapshot_budget_rewind_reproduced, historical_ciphertext_and_hmac_preserved, independent_fresh_key_and_incarnation_verified, prepared_before_budget_and_marker_verified, same_candidate_process_retry_verified, used_candidate_budget_reset_rejected 등이 true다. final_admission_state=PREPARED, final_target_database_closed=true, runtime_roles_remain_nologin=true여야 한다. isolated_resources_removed=true, Go race/vet=true여야 인수한다.

합성 seed guard는 schema9 백업 이력을 만들기 위한 _test.go 코드이며 실제 업무 admission의 증거가 아니다. 이 단계는 historical replay의 원본 HMAC/ciphertext 보존과 복호화를 검사한다. guarded runtime의 replay/새 write를 재개했다는 의미는 아니다. 복원 후보와 역사 ring은 유지보수 owner의 protected files이고 runtime RO key 공급 검사는 후속 재개 단계다.

report의 database_and_key_restore_performed는 격리 restore command의 완료 사실이다. 실패한 command는 isolated_restore_outcome=uncertain, 이전 단계 실패는 not_started, 복원 이후 실패는 completed로 남긴다. 전체 인수 실패 시 phase 성공 요약은 제거한다. report에 secret·raw DSN·archive 내용을 넣지 않는다. 실패 시 같은 disposable project의 ps/peer logs를 private log에 저장한 뒤 volumes/network를 제거한다. 실패 시 production이나 synthetic DB를 자동 복원하지 않는다. 로그와 report의 경로만 반환한다.

production_services_modified/production_database_modified/production_keys_loaded/production_admission_state_created/production_hba_modified/credential_api_activated/business_runtime_ready/production_restore_fence_implemented/network_packet_filter_verified는 모두 false다. Streamlit 브라우저 인수와 relay 없는 접근 방식은 기존 결정을 유지한다.


## owner image 환경 수정

서버의 첫 d2b 검사에서 seed_boundary가 실패했으며 복원은 시작되지 않았다. 공식 PG image의 PG_MAJOR/PG_VERSION/PGDATA와 모든 ambient PG*를 거부하는 관리 연결 정책 사이의 충돌을 재현했다. 수정 runner는 owner/restore10 phase에서 exec env -i로 PATH와 명시적 합성 fixture 환경만 전달한다. 제품 PG* 거부는 유지한다. pg_dump/pg_restore child의 승인된 설정 공급은 기존 코드가 맡는다. 별도 probe와 Compose 권한/마운트는 변경하지 않는다.

수정 이후 Python unit 인수는33개다. 성공 summary의 owner_pg_environment_absence_verified=true와 기존15 phase/필수8개/credential13/cleanup 기준을 함께 확인한다. 상세 재현·검증·현재 인수 상태는 [환경 수정 기록](../progress/20261007-step11b3c3d2b-owner-environment-fix.md)을 따른다.
