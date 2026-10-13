# camera 유지보수 HBA/TLS 접속 경계 격리 검사

상태: 11-B3c3d2a 시작 수정 완료 · 서버 native 재인수 대기

## 전제와 격리

test_camera_credential_boundary.py는 d1의 인수 revision a2116e85a9d93b03ea54e65c4209d3b5b82b946c27e2f2377f6fe64e5e812e0d와 현재 manifest/source 전체 hash를 먼저 요구한다. vms-credential-boundary-test-* project 아래 PostgreSQL17.11/Golang1.27.1 disposable DB tmpfs·합성 TLS·HBA·authority·private password만 만든다. 운영 .env/키/DB/volume/network는 공급하지 않는다. 공개 port·privileged·host PID·외부 자원이 없고 COMPOSE_/VMS_/CAMERA_/PG 환경을 제거한다. source mount는 RO다.

owner와 client container를 up 후 exec로 재사용해 maintenance source IP가 단계 사이에 바뀌지 않게 한다. owner는 격리 관리 UID0와 최소 file fixture capability만 사용한다. client는 UID/GID10001, effective capability0, actual statfs RO mount를 검사한다. 의도적으로 유효한 합성 maintenance password/client certificate를 private client fixture에 복제해 다른 IP에서 거부되는지 검증한다. 실제 credential 공급 모델이 아니다. PostgreSQL Docker 초기화에는 bootstrap local trust를 사용하고 본 경계 설치 시 complete deny 정책으로 교체한다. 공식 entrypoint의 initial SQL은 PGHOST를 비우므로 기본 socket /var/run/postgresql과 공유 mount/owner probe/helper를 맞춘다. healthcheck는 최종 TCP server를 기다린다. fixture public path는 umask0077에서도 명시적0755를 유지한다.

## 성공 기준

전체 module race/vet, 기존 credential13개와 새 필수 boundary5개 및 정확한 8 phase 모두 필요하다.

| 순서 | parent | 완료 증거 |
|---|---|---|
| 1 | Fixture | prepare — 합성 cert/HBA/authority 준비 |
| 2 | Owner | seed — schema9·marker·budget42·유지보수 계정·source pin |
| 3 | Client | client-before — 유효 자격으로 다른 IP에서 control/target 성공 |
| 4 | Owner | fence — durable FENCED·DB gate/drain·complete HBA reload·fresh mTLS/금지 자격 검사 |
| 5 | Client | client-closed — 유효 자격의 다른 IP를 두 DB에서 28000으로 거부 |
| 6 | Owner | reopen — test-only target reconnect·유지보수 TLS 접속·sentinel write |
| 7 | Client | client-open — target을 열어도 두 DB에서 다른 IP 거부 |
| 8 | Owner | retry — 새 control connection/lease·row/budget/FENCED 보존·재차단 |

phase-only fixture의 일반 regression skip는 정상이다. 각 실제 phase는 해당 run/output/pass 순서, 정확한 parent·순서·고유 phase를 요구한다. proof가 없는 pass, native에서 LOCAL_BOUNDARY_PHASE_OK 표식만 있음, 중복/순서 변경/누락/실패/package 불일치/source drift/정리 실패는 passed가 아니다. Go test2json binary와 -test.v=test2json으로 phase를 파싱한다. 모든 실패는 뒤 mutation 단계로 진행하지 않고 해당 project down/volume 제거를 항상 시도한다. 고정 failed_stage/last_completed_stage/exit와 allowlisted test 이름만 공개하고 driver/DSN/secret 원인을 report에 포함하지 않는다.

## 결과 해석

private log/report는 var/camera/credential-boundary-checks에 저장한다. status=passed, required_boundary_tests_passed=5, native_boundary_phases_passed=8, isolated_resources_removed=true가 인수 기준이다. HBA disk 검사와 reload 응답만으로 active policy를 인수하지 않는다. product 정책 설치/운영 reopen/DB·키 복원/API 전환은 수행하지 않는다. production_hba_modified·database_and_key_restore_performed·network_packet_filter_verified·production_restore_fence_implemented·business_runtime_ready 및 모든 production 변경 flag는 false다. 다음 d2b에서 실제 복원 통합을 진행하며 운영 전환은 별도 preflight/rehearsal/activation이다. 적용 명령은 채팅에서 제공한다.

CN mismatch는 유효한 password를 사용해 PostgreSQL SCRAM/clientcert 경로의 정확한 28P01을 요구한다. 다른 source/role·없는 cert·plaintext·Unix socket 거부는 28000을 요구한다. 특히 다른 IP의 positive-before/negative-after probe에서 28P01이나 network 오류를 허용하지 않는다. 유지보수 leaf subject는 CN=camera_maintenance 하나이며 PostgreSQL17의 actual client_dn 표기는 /CN=camera_maintenance다.

## 시작 실패 진단 — 2026-10-07 수정

시작 또는 이후 검사 실패 시 cleanup 전에 동일 project의 ps --all 및 마지막100줄 boundary-db/owner/client logs를 private log에 보존한다. 실패 단계/exit/완료 이력은 원래 값이며 진단 실패/timeout/interrupt도 cleanup을 계속한다. raw output은 JSON report에 포함하지 않는다. isolated_diagnostics_collected는 두 진단 명령이 성공했는지를 나타낸다. go_vet_passed는 build_tools의 실제 성공, go_race_passed는 전체 검증 완료를 나타낸다. 성공에는 동일 필수5개/8 phase와 cleanup이 필요하고 Python runner 검사는26개다. [수정 기록](../progress/20261007-step11b3c3d2a-startup-fix.md)을 따른다.
