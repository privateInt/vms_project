# 11-D1c 서버 인수 — DB TLS 공급 준비와 재실행

상태: 서버 패치·Python23개·공급 probe3/UID 거부6·재실행 보존 인수 완료 · 운영 TLS 미전환

## 인수 근거

2026-10-12 사용자 제공 simsys4090/sh_test 출력에 근거한다. 전달 압축 SHA256은01c3b0e189579f6b8182e48ca547c5465888a381f8a0986cdc1180842bda770c이며 checksum OK였다. 적용은 applied·written10·pending0, 이력은 var/patch-backups/step11d1c-tvq1a4kg다. 패치의 service_restart_performed·runtime_activation_required·database_schema_modified는 false다. Python23개가2.430초에 OK였다.

두 준비 실행의 scope는 camera_database_tls_supply_preparation, checked_revision은5d2f6e3ce0016e173157051c44540cc9cbc8274d8cf567711985701c9815c9d7이다. 이번 인수 기록 패치가 만드는 새 manifest SHA를 이 검사 revision으로 바꾸지 않는다. D1a 후보 준비와 D1b native 검사 revision/인수 근거도 그대로 보존한다.

| 항목 | 최초 준비 | 재실행 |
|---|---|---|
| status | prepared | already_prepared |
| TLS 볼륨 생성 수 | 3 | 0 |
| 공급 probe | 3개 통과 | 3개 통과 |
| UID 간 접근 거부 | 6개 통과 | 6개 통과 |
| 파일·볼륨 준비 | true | true |
| UID/RO·exact bytes·상호 UID 차단·helper 정리 | 모두 true | 모두 true |

두 결과는 status와 tls_supply_volumes_created 외 모든 필드가 같다. probe/denial은 각각의 실행 기준이며 두 실행을 합산해 새로운 검사 수로 표시하지 않는다. 이번 실행은 Python 검사와 native 공급 준비이며 새로운 Go race/vet·전체 회귀·플랫폼 smoke 결과는 없다.

## 보존된 후보와 공급

두 실행의 candidate SHA는421c3e0a67ec6e47f3fdab270f7c7448351a42d9e21eb7accc9ab702e7cadc40, supply SHA는22ccacd8f4ec043219d2eef4f21378772c0705e26b1b2fa906d5b2b57aad4a6e다. supply_directory는 /home/shshin/workspace/vms_project/var/camera/database-tls-supply/supply-v1이다. 모두 사용자 출력의 값이며 원격 receipt 파일을 직접 읽은 결과는 아니다.

| 공급 역할 | 두 실행에서 보존된 볼륨 이름 | 도구가 요구하는 UID/GID·권한 |
|---|---|---|
| DB | vms-project-camera-tls-database-22ccacd8f4ec0432 | 999:999, root0700/file0400 |
| runtime | vms-project-camera-tls-runtime-22ccacd8f4ec0432 | 65532:65532, root0700/file0400 |
| maintenance | vms-project-camera-tls-maintenance-22ccacd8f4ec0432 | 10002:10002, root0700/file0400 |

prepared_separate_uid_and_ro_mounts_verified·prepared_exact_candidate_bytes_verified·cross_uid_access_rejected·offline_probe_helpers_removed·current_process_identity_verified·source_candidate_unchanged·current_services_unchanged·compose_recipe_validated·actual_socketpair_mtls_verified는 두 실행에서 모두 true다. tls_supply_files_prepared와 tls_supply_volumes_ready도 true다. UID/GID·권한은 해당 revision의 필수 probe 조건과 성공 필드에 근거하며 공개 결과에 raw stat/UID 값을 새로 받은 것처럼 표시하지 않는다.

tls_candidate_private_keys_read=true는 미활성 D1a TLS 후보의 검사·선별 사본·공급 probe 범위다. ca_signing_key_exported=false이며 runtime에는 CA 공개 인증서만 공급한다. 기존 credential encryption key를 읽거나 운영 API에 TLS/credential 키를 활성화한 결과가 아니다. 준비한 세 볼륨은 보존했고 일회용 helper만 정리했다. 전체 공급 자료를 삭제했다고 표시하지 않는다.

## 현재 주소와 예약 경계

| 고정 주소 자료 | 두 실행의 값 |
|---|---|
| network name | vms-project_camera-storage |
| network ID | bc1a7f1ef8899e4939d6f06ff369accf60d90e457b72948f9bbcf07526017288 |
| subnet / gateway | 192.168.96.0/20 / 192.168.96.1 |
| DB / runtime / maintenance 제안 | 192.168.96.2 / 192.168.96.3 / 192.168.96.4 |
| internal | true |
| current_database_and_runtime_addresses_verified | true |
| maintenance_address_currently_unattached | true |
| address_state | observed-recipe-unreserved |
| address_reservation_verified | false |

현재 주소와 Compose config는 검증했지만 유지보수 주소 예약·운영 service 재연결·binding 승인은 수행하지 않았다. recipe_is_deployable=false다. 현재 시점의 미연결 관찰은 미래 예약 보장이 아니므로 실제 연결 전에 재검사한다.

## 운영 미완료

두 실행에서 다음 필드는 모두 false다.

| 범위 | 필드 |
|---|---|
| 운영 변경 | production_services_modified, service_restart_performed, production_database_modified, database_schema_modified, production_hba_modified, environment_modified, production_network_modified, host_permissions_modified, current_compose_modified |
| credential 키·admission | production_key_material_read, production_keys_loaded, production_admission_state_created, credential_key_material_read |
| 운영 공급·활성화 | credential_api_activated, business_runtime_ready, production_supply_ready, activation_allowed, production_runtime_mount_verified, database_tls_activated, production_endpoint_and_sources_reserved, approved_binding_created |

준비 볼륨의 TLS 공급 검증은 현재 API/DB에 실제 mount된 운영 공급이나 PostgreSQL TLS 인증·주소 예약·schema9·credential HTTP 활성화 인수가 아니다. 도구의 현재 identity/schema7/API0.7/TLS off 전제와 전후 재검사가 통과했다. 이 결론은 제공 JSON과 해당 source revision의 검사 조건에 근거하며 원격 DB를 직접 질의한 결과로 표시하지 않는다. 최신 운영 기준은 API0.7.0-device-delete/schema7/registry-only-v1/TLS off다.

## 기록 패치와 다음 단위

README·문서 목록·전체 계획·공급 안내·구현 기록·이번 서버 인수 기록·manifest의7개 파일에 결과를 반영한다. source·SQL·현재 Compose·환경·TLS 후보/선별 사본·credential/authority 실행 자료를 보존한다. 전체 baseline/source/payload hash·dry run/적용/재적용·보호 파일과 권한·사용자 변경/신규 충돌·현재 source gate를 검증한다. 적용 명령은 채팅에서 제공한다. 기록 작업이므로 준비 도구나 native 검사를 다시 실행하지 않는다.

다음은 11-D1d schema7·기존 등록 API와 TLS 전환의 격리 리허설이다. 실제 운영 반영 전에 기존 registry 경로·역할/source/HBA·읽기 전용 공급·서비스 재생성 후 동작의 호환성을 확인한다. 이후 운영 TLS 전환과 credential 역할/DSN·schema9·admission/HTTP 공급·IAM·관리 사용 guard를 각각 진행한다. ConnectionConfig·SourceSession·실장비/영상·model/analysis/operation 업무도 남는다.

백업 추가 설계·검토는 사용자 요청에 따라 제외한다. Streamlit 브라우저 인수 보류·Jupyter 중계 미구현을 유지한다.

[구현 기록](20261012-step11d1c-database-tls-supply.md) · [공급 안내](../operations/camera-database-tls-supply.md)

## 인수 기록 패치 서버 반영 — 2026-10-12

사용자 제공 출력에서 vms_step11d1c_acceptance_notes_20261012.tar.gz의 SHA2562a6cd5f1e5c93eedcbad343eafeec177f6575659bfadb2f885119ee33304c333 checksum OK와 applied/written7/pending0을 확인했다. 패치 이력은 var/patch-backups/step11d1c-notes-qxqx39_9다. service_restart_performed/runtime_activation_required/database_schema_modified는 false다. 이 출력은 기록 적용의 인수이며 D1c 준비/native 검사를 새로 수행한 결과가 아니다. 다음 [D1d 격리 TLS 리허설](20261012-step11d1d-registry-tls-cutover.md)의 source·서버 인수 상태는 별도로 기록한다.
