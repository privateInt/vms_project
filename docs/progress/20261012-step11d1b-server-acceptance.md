# 11-D1b 서버 인수 — PostgreSQL TLS·역할·접속 출처

상태: 대상 서버 패치·Python18개·필수 Go8개·native9개 단계 인수 완료 · 운영 TLS 미전환

## 인수 근거

2026-10-12 사용자 제공 simsys4090/sh_test 출력에 근거한다. 전달 압축본 SHA256 cb2117c6aa810a6b8a66bd24a899aeed53e3afc10534512126e015a7fa7d3704의 검사가 OK였다. 적용은 applied·written11·pending0, 이력은 var/patch-backups/step11d1b-cu1_rfiw다. 패치의 service_restart_performed·runtime_activation_required·database_schema_modified는 false다. Python unit18개가1.926초에 OK였다.

native 검사 project는 vms-database-tls-test-168b1aee7dd6, scope는 camera_database_tls_role_source_native_postgresql, status는 passed다. checked_revision은 f18af0cf9a0580c05609ff7a0585fb023e781220318bb18b4957ed368a4dd103이다. 이번 기록 패치의 새 manifest SHA를 당시 검사 revision으로 바꾸지 않는다. D1a의 후보 준비 인수와 공개 인증서 hash도 이전 bee8f71859c99c31e81997009c950f7360e441b82eff3acf09420998430adf04에 그대로 묶인다.

| 검사 집계 | 서버 결과 |
|---|---|
| Python unit | 18개, OK |
| 필수 endpoint/HBA Go 구성요소 | 5개 |
| 필수 native peer Go test | 3개 |
| native TLS 단계 | 9개 |
| Go race / vet | true / true |
| 격리 network / resources / synthetic input 제거 | 모두 true |

필수 Go test의 고유 개수는5+3=8이다. runtime parent를 컨테이너 재생성 후 다시 실행한 단계까지 native phase9개이며 Python18개·Go8개·phase9개를 합산하지 않는다. 이 출력에 전체 Go 상위/하위 test 수는 없으므로 과거 회귀 수를 이번 실행으로 표시하지 않는다.

## 확인한 실제 격리 동작

아래 항목은 사용자 제공 native report에서 모두 true다.

| report 필드 | 확인 범위 |
|---|---|
| synthetic_d1a_pki_profile_verified / synthetic_pki_only | D1a와 같은 프로파일의 새 합성 PKI |
| actual_runtime_two_role_tls_verified | 기존 public opener를 통한 writer/budget 두 역할의 실제 TLS |
| actual_maintenance_mtls_target_and_control_verified | maintenance의 target/control DB 실제 mTLS |
| exact_leaf_certificates_verified | 합성 server/client leaf 인증서의 정확한 대응 |
| actual_role_source_database_and_tls_identity_verified | 실제 역할·출처/서버 주소·DB·TLS identity |
| wrong_password_ca_hostname_plaintext_and_control_database_rejected | runtime 잘못된 인증·평문·control DB 거부 |
| maintenance_missing_certificate_and_wrong_cn_rejected | maintenance client 인증서 누락·잘못된 CN 거부 |
| valid_credentials_from_wrong_source_rejected | 유효 합성 자격증명이라도 다른 출처의 인증 거부 |
| runtime_privilege_escalation_rejected | runtime CREATE/maintenance SET ROLE 거부 |
| separate_peer_uids_and_read_only_mounts_verified | peer 별도 UID와 실제 읽기 전용 입력 마운트 |
| isolated_database_uid_and_ro_mount_verified | DB 실행 UID와 TLS/control 읽기 전용 마운트 |
| recreated_runtime_fixed_source_and_tls_verified | runtime 컨테이너 재생성 후 같은 고정 출처와 TLS |
| hba_outside_pgdata_verified | 격리 HBA가 PGDATA 밖에 위치 |
| isolated_network_removed / isolated_resources_removed / synthetic_input_removed | 해당 격리 자원과 합성 입력 정리 |

source의 검사 요구 identity는 DB UID/GID999:999, runtime10001:10001, maintenance10002:10002, 다른 출처 probe10003:10003이다. 위 UID/RO 검증 성공의 범위는 격리 fixture이며 현재 운영 프로세스 identity를 새로 조사한 결과가 아니다. runtime에는 owner DSN·maintenance private key를 공급하지 않는다. CA signing key는 peer/DB 공급에서 제외한다.

9개 단계는 runtime-supply-ro-uid → runtime-two-role-tls → runtime-denials → maintenance-supply-ro-uid → maintenance-mtls-target-control → maintenance-denials → offsource-supply-ro-uid → offsource-denials → runtime-recreated다. 이전 로컬5개 LOCAL 단계·root 거부 진단은 별도 근거로 보존한다. 로컬 separate UID/RO 미검증 필드를 이번 서버 성공으로 바꾸지 않는다.

출력의 log는 var/camera/database-tls-checks/vms-database-tls-test-168b1aee7dd6-v9k0lhql.log, report는 var/camera/database-tls-checks/vms-database-tls-test-168b1aee7dd6.json이다. 원격 파일을 직접 읽었다고 표시하지 않는다. 출력에 production_candidate_files_read=false가 명시됐으므로 실제 D1a 후보 파일이나 키가 격리 공급에 사용됐다고 표시하지 않는다.

## 운영 미완료

다음 report 필드는 모두 false다.

| 범위 | 필드 |
|---|---|
| 운영 변경 | production_services_modified, service_restart_performed, production_database_modified, database_schema_modified, production_hba_modified, production_network_modified, environment_modified |
| 운영 키·admission | production_key_material_read, production_keys_loaded, production_admission_state_created, production_candidate_files_read |
| 실제 공급·활성화 | production_runtime_mount_verified, database_tls_activated, production_endpoint_and_sources_reserved, approved_binding_created, production_supply_ready, activation_allowed, credential_api_activated, business_runtime_ready |

합성 PKI·격리 주소·역할·HBA 성공은 운영 TLS 후보·고정 IP 예약·실제 공급 binding·schema9 cutover·credential HTTP 활성화 인수가 아니다. HBA의 실제 새 인증 거부를 확인했지만 packet filter·기존 세션 drain·운영 restore fence를 이 검사로 입증하지 않는다. 최근 운영 인수 기준은 API0.7.0-device-delete/schema7/registry-only-v1/TLS off이며 이번 도구는 운영 상태를 재조회하지 않았다.

## 기록 패치와 다음 단위

README·문서 목록·전체 계획·운영 안내·구현 기록·이번 서버 인수 기록·manifest의7개 파일에 결과를 반영한다. source·SQL·Compose·환경·TLS/credential/authority 실행 파일을 보존한다. 기준 전체 hash·payload·dry run/적용/재적용·사용자 변경/신규 파일 충돌·보호 파일과 권한·현재 source gate를 검증한다. 적용 명령은 채팅에 둔다. 문서/메타데이터 기록이므로 native 검사를 다시 실행하지 않는다.

다음 단위는 11-D1c 운영 TLS 공급 위치와 고정 endpoint/source 구성 준비다. 완료 기준은 D1a 후보 receipt에 묶인 실제 공급 경로·소유권·읽기 전용 마운트와 DB/runtime/maintenance의 분리된 고정 주소를 구체화하고, 기존 서비스에 적용하기 전 구성을 검사해 전달하는 것이다. 운영 서비스 전환은 별도 인수 단위로 진행한다. 이후 키/DSN·authority·schema9/admission·HTTP 실행 경로·IAM·관리 참조/사용 guard, ConnectionConfig·SourceSession·실장비/영상과 다른 플랫폼 업무가 남는다.

백업 추가 설계·검토는 사용자 요청에 따라 제외한다. Streamlit 브라우저 인수 보류와 Jupyter 중계 미구현을 유지한다.

[구현 기록](20261012-step11d1b-database-tls-boundary.md) · [검사 안내](../operations/camera-database-tls-boundary-check.md)

## 인수 기록 패치 반영

2026-10-12 사용자 제공 서버 출력에서 acceptance notes 압축 SHA256 a5a4d78df7db410e678af311c169a0d1a8074bea619f497f0d0eae68badf34c7의 검사가 OK였다. applied·written7·pending0으로 반영됐고 service_restart_performed·runtime_activation_required·database_schema_modified는 false다. 이력은 var/patch-backups/step11d1b-notes-2nmfn60y다. 기록 패치의 manifest는 fc755d5d904f039c83144d58649e6fd9bbf692d965c3c7c7f07db1438aa5138e이며 native 검사를 다시 실행한 결과로 표시하지 않는다.
