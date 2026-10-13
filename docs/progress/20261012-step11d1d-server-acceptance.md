# 11-D1d 서버 인수 — schema7 등록 API의 TLS 전환 격리 리허설

상태: 서버 격리 리허설 인수 완료 · 운영 TLS 미전환

## 인수 근거

2026-10-12 사용자 제공 simsys4090/sh_test 출력에 근거한다. HTTP network 수정 압축 SHA256은2bb67f16c4a667754199bc9344c687b195821d834642946b691553d8675bc815이며 checksum OK였다. applied/written10/pending0, patch 이력 var/patch-backups/step11d1d-http-network-fix-aguthxrp를 확인했다. 패치 restart/runtime activation/schema modification은 false다. Python45개가2.555초에 OK였다.

native scope는 camera_registry_schema7_tls_cutover_native_docker, project는 vms-registry-tls-test-cfeb7a2c0284, status는 passed다. checked_revision은1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159다. 이번 기록 patch의 새 manifest SHA를 native 검사 revision으로 바꾸지 않는다. 앞선 두 실패·수정과 D1a/D1b/D1c/C3의 인수 revision을 보존한다. 원격 log/report 파일을 직접 읽은 결과가 아니라 제공 JSON과 이 revision의 검사 조건에 근거한다.

| 검사 | 이번 서버 결과 |
|---|---|
| Python unit | 45개 OK |
| Go policy | 필수1개, go_unit_race_passed=true |
| Go vet | go_vet_passed=true |
| Native transport | 필수 peer parent3개, transport phase5개 |
| Native probe race | native_probe_race_enabled=false, CGO=0 실행 범위 |
| 전환 리허설 | cutover_phases_passed=10 |
| 실제 HTTP 게시/망 검사 | isolated_http_binding_checks_passed=4 |
| 자원/입력 정리 | isolated_resources_removed=true, synthetic_input_removed=true |
| 실패 진단 수집 | isolated_diagnostics_collected=false, 성공 시 실패 진단 수집을 수행하지 않음 |

숫자는 서로 다른 검사 범위이므로45+1+3+5+10+4를 하나의 test 수로 합산하지 않는다. 이전 로컬 foundation smoke62개·LOCAL TLS5개 phase·현행 source/schema8 HTTP 검사도 이번 서버 검사 수에 합산하지 않는다. 전체 native peer에 race를 적용했다고 표시하지 않는다.

## 같은 운영 이미지로 검증한 범위

| 항목 | 값 |
|---|---|
| 테스트 API image | sha256:708d5a53f3dcc3d22dca775ef2825bcd271a68c7c3777cf8a6a89bb6933aa7d6 |
| 테스트 DB image | sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201 |
| 운영 이미지 재사용 | running_image_reused_for_test=true |
| registry schema | registry_schema_version=7, schema7_preserved=true |
| PKI | synthetic_pki_only=true |
| runtime TLS 인증 | scram-sha-256 |
| migrator TLS 인증 | certificate-cn-map |

새 격리 DB의 schema7·등록/profile·전체 journal을 준비하고 API drain 후 같은 data volume을 TLS로 재생성했다. 운영 이미지 migration의 TLS 재실행은 source가 요구한 version7/applied0 조건을 통과했다. existing_rows_and_all_journals_preserved·registry_create_update_delete_replay_verified·active_children_rejection_verified·isolated_data_volume_preserved는 모두 true다. 최초 HTTP 응답과 이력 재생·활성 목록/tombstone·새 TLS CRUD·API 및 DB/API 재생성을 인수했다.

actual_api_tls_sessions_verified·runtime_uid_and_ro_supply_verified·database_uid_and_ro_tls_control_verified·migrator_certificate_role_map_verified는 모두 true다. 해당 source의 API PID1/probe UID65532, DB999, maintenance10002/offsource10003·RO 공급 조건을 충족했다. raw UID/stat 결과를 새로 받은 것처럼 표시하지 않는다. 기존 camera_migrator와 client CN=camera_maintenance의 exact cert map을 확인했으며 migrator의 비밀번호 이중 인증을 주장하지 않는다. runtime은 SCRAM이며 wrong_ca_hostname_password_plaintext_control_db_and_source_rejected=true다.

API/DB 재생성과4개 지점의 실제 loopback 게시·API 전용 HTTP망/internal DB망·고정 storage source를 인수했다. api_and_database_recreation_verified·isolated_loopback_http_port_and_storage_boundary_verified·production_services_and_network_unchanged는 true다. HTTP network 수정 뒤 전체 검사가 통과했지만 앞선 실패 당시의 raw port mapping을 소급해 직접 관찰한 것으로 표시하지 않는다.

## 운영 미전환과 보존

이번 JSON에서 다음 필드는 모두 false다.

| 범위 | 필드 |
|---|---|
| 운영 변경 | production_services_modified, service_restart_performed, production_database_modified, database_schema_modified, production_hba_modified, environment_modified, production_network_modified |
| 운영 키/admission | production_key_material_read, production_keys_loaded, production_admission_state_created |
| 기존 후보·준비 공급 | production_candidate_files_read, production_prepared_supply_files_read, production_prepared_volumes_modified |
| 운영 활성화·승인 | credential_api_activated, business_runtime_ready, production_supply_ready, activation_allowed, production_runtime_mount_verified, database_tls_activated, production_endpoint_and_sources_reserved, approved_binding_created |
| 백업·복원 | backup_created, database_backup_restore_performed |

정리한 것은 새 테스트 project/container/network/volume과 합성 입력이다. 운영 DB·D1a 후보·D1c 준비 공급 볼륨을 삭제한 결과가 아니다. 검사 source의 현재 API0.7.0-device-delete/schema7/registry-only-v1/TLS off 전제와 전후 재검사를 통과했다. 운영 TLS·주소 예약·runtime mount·schema9/admission·credential main HTTP·IAM·관리 사용 guard는 아직 후속이다.

서버 log 위치는 /home/shshin/workspace/vms_project/var/camera/registry-tls-checks/vms-registry-tls-test-cfeb7a2c0284.log, report 위치는 같은 디렉터리의 vms-registry-tls-test-cfeb7a2c0284.json이다. 비밀값이나 파일 내용을 이번 전달물에 포함하지 않는다.

## 기록 patch와 다음 단위

README·문서 목록·전체 계획·ADR0024·검사 안내·D1d 구현/HTTP network 수정 기록·이번 인수 기록·manifest의9개 파일에 결과를 반영한다. 기존 source/Go/API/SQL/Compose·환경·키/authority·후보/준비 공급 자료는 보존한다. 전체 baseline/source/payload hash·계획/적용/재적용·사용자 변경/신규 충돌·보호 파일/권한·source gate·archive를 검사한다. 기록 작업이므로 native 리허설이나 실제 서비스 전환을 다시 실행하지 않는다. 적용 명령은 채팅에만 제공한다.

다음은11-D1e에서 기존 schema7 API 경로를 유지한 운영 DB TLS 전환을 준비하는 단위다. 현재 D1c 공급과 최신 process/image/network·실제 mount/주소 조건을 재검사하고 전환 경로와 실행 도구를 구체화한다. 이번 인수 기록은 곧바로 운영 활성화가 가능한 deployable recipe나 approved binding이 아니다. credential 역할/DSN·schema9/admission·실행 HTTP·IAM·관리 사용 guard·ConnectionConfig·SourceSession·실장비/영상과 model/analysis/operation 업무는 각각 후속이다.

백업 추가 작업 제외·Streamlit 브라우저 인수 보류·Jupyter 중계 미구현은 사용자 지시대로 유지한다.

[구현 기록](20261012-step11d1d-registry-tls-cutover.md) · [HTTP network 수정](20261012-step11d1d-http-network-fix.md) · [검사 안내](../operations/camera-registry-tls-cutover-check.md)

## 기록 패치 서버 반영 확인

2026-10-12 사용자 제공 checksum OK·applied/written9/pending0을 확인했다. 압축 SHA256은8787549f4413114c7aa2531990c175e2c4ff300ee3618190592e416f84368933이며 patch 이력은 var/patch-backups/step11d1d-notes-f0q38zhd다. restart/runtime activation/schema modification은 false다. 다음 구현은 [11-D1e 운영 TLS 준비](20261012-step11d1e-registry-tls-preparation.md)로 진행한다.
