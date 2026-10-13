# DB TLS 공급 준비 — 11-D1c

상태: 구현·로컬23개 검사·서버 실제 공급/재실행 인수 완료 · 운영 TLS 미전환

## 준비와 경로

도구는 src/infra/tools/prepare_camera_database_tls_supply.py, 옆 test는 test_prepare_camera_database_tls_supply.py다. Linux/Python3.10 이상·시스템 OpenSSL·로컬 Unix Docker/Compose와 인수된 D1a 후보·D1b native 결과가 필요하다. 적용/실행 명령은 채팅에서 제공한다. Docker image를 pull하거나 공용 Conda/Jupyter 의존성을 설치하지 않는다.

기존 var/camera/database-tls-candidates/candidate-v1의 receipt SHA와 공개 server/client/CA hash를 D1a 서버 인수 값에 맞춘다. 실제 체인·키 대응·유효기간과 socketpair mTLS를 다시 검사한다. 후보 파일 원문은 읽지만 생성·수정하지 않는다. 기존 credential encryption key 파일은 읽지 않는다.

호스트 선별 사본과 구성 자료는 var/camera/database-tls-supply/supply-v1에 caller 소유0700/0600으로 보관한다. receipt.json에는 공개 후보/인증서 SHA·volume name·network recipe·선별 이름·target UID만 넣는다. compose.recipe.json은 config-only이며 현재 Compose에 연결하지 않는다. CA signing key·DSN·API token·authority·DB 파일은 포함하지 않는다.

| 공급 | 호스트 선별 하위 경로 | 파일 | 전용 볼륨 UID/GID |
|---|---|---|---|
| DB | database | ca.pem, server.pem, server.key | 999:999 |
| runtime | runtime | ca.pem | 65532:65532 |
| maintenance | maintenance | ca.pem, maintenance.pem, maintenance.key | 10002:10002 |

전용 볼륨 이름은 vms-project-camera-tls-역할-공급SHA앞16자리이며 실제 이름을 receipt/공개 결과에 기록한다. 각 볼륨 root0700·파일0400이다. 현재 DB immutable image를 사용한 일회용 owner helper가 host selected directory를 RO로 읽고 새 볼륨만 초기화한다. 기존 호스트 파일·권한과 camera-data 볼륨을 변경하지 않는다. owner helper는 network none·rootfs RO·no-new-privileges·cap drop ALL에 CHOWN/DAC_OVERRIDE만 추가한다. PGDATA 위치는 별도 tmpfs로 대체한다.

## 실제 볼륨 검사와 재실행

세 target UID의 network none·rootfs RO·cap drop ALL 검사 helper가 공급 볼륨을 RO로 읽는다. exact selected bytes·UID/GID·full UID/GID map·파일 type/single link·owner·mode를 요구한다. 쓰기 가능한 owner0700 디렉터리에 생성 시도를 해 실제 Read-only file system 거부를 확인하고 다른 두 UID 소유 디렉터리를 열 수 없어야 한다. 3개 positive probe와6개 cross UID denial을 공개 결과로 구분한다. 이들은 PostgreSQL 연결/role 검사 수가 아니다.

기존 볼륨은 expected label·local driver·빈 driver options와 실제 파일이 모두 일치해야 한다. 기존 공급을 검사하기 전에 누락된 다른 볼륨을 생성하지 않는다. 기존 완전한 볼륨은 재검사만 하며 initializer를 다시 실행하지 않는다. partial/unknown/wrong-owner/wrong-bytes나 손상된 공급은 자동 복구·교체하지 않고 실패한다. 새 볼륨 생성/초기화의 불확실한 중단 뒤에는 완전한 기존 내용만 인수한다. 부분 생성 파일·볼륨은 private하게 남을 수 있으며 자동 삭제하지 않는다.

정상 및 오류 종료에서 이번 helper의 정확한 name/label을 검증해 제거한다. 불확실한 run 뒤에도 같은 검사 후 rm을 수행하고 anonymous volume 정리를 포함한다. helper identity/cleanup 오류는 준비 성공으로 표시하지 않는다. 세 준비 볼륨과 호스트 선별 사본은 보존한다.

## 현재 네트워크 관찰과 고정 주소 자료

현재 API/DB process의 actual UID/GID·full identity map·cgroup/namespace와 schema7/API0.7/TLS off를 읽기 전용으로 확인한다. 프로젝트 소유 internal IPv4 bridge에서 DB/runtime 주소가 D1a 제안192.168.96.2/192.168.96.3과 같고 다른 peer가 없음을 요구한다. maintenance192.168.96.4가 subnet 내에서 gateway/aux reservation/peer와 충돌하지 않는지 확인한다. 제안과 현재 상태가 다르면 주소를 임의 변경하지 않고 중단한다.

Compose config로 세 UID·external 공급 볼륨·RO/nocopy·현재 external network의 고정 주소 recipe를 검사한다. recipe에는 /bin/true와 전용 opt-in profile만 있고 운영 서비스 정의는 없다. config 검사는 주소를 예약하지 않는다. fixed_address_recipe.address_state는 observed-recipe-unreserved, address_reservation_verified는 false다. 실제 운영 연결 직전에는 충돌과 identity를 다시 확인해야 한다.

## 결과와 다음 단계

명시적 apply 없이 공급이 없으면 planned이고 새 TLS 공급 파일·볼륨을 만들지 않는다. 기존 공급이 있으면 검증 helper는 실행·제거할 수 있다. 최초 공급은 prepared, 같은 파일·볼륨 재검사는 already_prepared다. 서버 완료 기준은 prepared → already_prepared에서 같은 candidate/supply SHA·볼륨 이름, prepared_separate_uid_and_ro_mounts_verified·prepared_exact_candidate_bytes_verified·cross_uid_access_rejected·offline_probe_helpers_removed=true와 probe3/denial6을 확인하는 것이다. 에러는 safe code/failed_stage만 공개하며 private key/DSN/원시 stderr/개별 private key hash를 출력하지 않는다.

2026-10-12 사용자 제공 서버 JSON에서 Python23개·2.430초 OK와 prepared → already_prepared를 인수했다. candidate SHA는421c3e0a67ec6e47f3fdab270f7c7448351a42d9e21eb7accc9ab702e7cadc40, supply SHA는22ccacd8f4ec043219d2eef4f21378772c0705e26b1b2fa906d5b2b57aad4a6e로 두 실행에서 같다. volume 생성 수는3 → 0이며 각 실행의 probe3/denial6·UID/RO/exact bytes·상호 UID 차단·helper 정리·Compose config·현재 process identity·원본/서비스 보존·실제 socketpair mTLS는 모두 true다. 당시 검사 revision은5d2f6e3ce0016e173157051c44540cc9cbc8274d8cf567711985701c9815c9d7로 보존하며 기록 패치의 새 SHA를 넣지 않는다.

tls_candidate_private_keys_read=true는 인수된 미활성 TLS 후보와 선별 공급 검사 범위다. production_keys_loaded·credential_key_material_read·production_services_modified·service_restart_performed·production_database_modified·database_schema_modified·production_hba_modified·production_network_modified·environment_modified·host_permissions_modified·current_compose_modified는 false다. production_runtime_mount_verified·database_tls_activated·production_endpoint_and_sources_reserved·approved_binding_created·production_supply_ready·activation_allowed·credential_api_activated·business_runtime_ready도 false다.

서버 결과는 실제 준비 볼륨의 검사이며 현재 camera API/DB에 연결된 mount·운영 TLS·주소 예약·schema9·HTTP 활성화를 뜻하지 않는다. 다음은 11-D1d schema7/registry 호환 TLS 전환의 격리 리허설이다. 키/DSN·authority/admission/schema9·운영 IAM·관리 사용 guard·ConnectionConfig·SourceSession과 실장비/다른 플랫폼 업무는 후속이다. 백업 추가 검토는 제외하며 Streamlit 브라우저 인수 보류·Jupyter 중계 미구현을 유지한다.

설정 의미는 [Docker volume/RO/nocopy 문서](https://docs.docker.com/reference/compose-file/services/#volumes), [external network 문서](https://docs.docker.com/reference/compose-file/networks/#external), [PostgreSQL17 SSL 파일 문서](https://www.postgresql.org/docs/17/ssl-tcp.html)를 확인했다. 실제 실행 인수는 서버 결과에 따른다.

[ADR0023](../architecture/decisions/0023-camera-database-tls-supply-volumes.md) · [진행 기록](../progress/20261012-step11d1c-database-tls-supply.md) · [서버 인수](../progress/20261012-step11d1c-server-acceptance.md)
