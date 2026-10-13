# schema7 등록 API의 TLS 전환 격리 리허설

상태: 11-D1d 서버 native 인수 완료, 운영 TLS 미전환

도구는 src/infra/tools/test_camera_registry_tls_cutover.py이며 호출 명령은 전달 채팅에만 제공한다. D1c 서버 인수 revision5d2f6e3ce0016e173157051c44540cc9cbc8274d8cf567711985701c9815c9d7과 현재 전체 source hash를 요구한다. 운영은 API0.7.0-device-delete/schema7/registry-only-v1/TLS off여야 하며 현재 process identity·내부 storage network·image ID를 읽기만 확인한다.

## 리허설 범위

| 구간 | 필수 증거 |
|---|---|
| 새 격리 project/network/volume | 새 random namespace의 기존 자원 부재, 운영과 다른 network, 합성 PKI·토큰·비밀번호 |
| plaintext schema7 | 현재 운영 API·DB의 같은 image ID, migration7개, 기존 registry 권한 |
| 최초 등록 이력 | 생성·수정·삭제·활성 자식409 후 같은 parent key 재시도, tombstone·active 목록·모든 journal |
| 전환 전 API drain | API 중지, runtime/migrator 세션0, 동일 synthetic 데이터 fingerprint |
| TLS DB | 같은 data volume·schema7·행/이력·권한, UID999·PGDATA 밖 RO PKI/HBA/ident |
| 유지보수 | 고정 source·mTLS cert/CN→camera_migrator map, migration version7/applied0 |
| API·transport peer | 실제 API TLS 세션, API PID1 UID/GID65532, RO 파일, native peer3개/transport5개 phase |
| 인증 거부 | runtime의 잘못된 CA/hostname/password/plaintext/control DB, maintenance의 missing cert/wrong CN·runtime role, 다른 source의 두 역할 |
| 재생과 새 쓰기 | 전환 전 최초 응답·목록·tombstone 보존, 새 TLS 등록/수정/삭제·재생 |
| 재생성 | API 및 DB/API 재생성 후 schema7·volume·모든 응답/행/이력·실제 TLS source 보존 |
| 최종 보존·정리 | 현재 source/.env/운영 service/network/identity 재검사, 격리 container/network/volume·합성 입력 제거 |

기존 운영 이미지 안의 migration을 사용한다. 개발 소스의 schema8/API를 새로 실행하지 않으며 schema9 전환도 없다. 고정 source는 새 격리 network의 .2/.3/.4/.5로만 예약한다. D1c의 운영 network 주소 예약을 완료한 결과가 아니다.

TLS migrator는 cert map 인증이며 비밀번호 검증을 주장하지 않는다. runtime은 SCRAM이다. client 인증서 CN은 camera_maintenance, DB role은 기존 camera_migrator이며 explicit pg_ident가 둘을 연결한다. 고정 DB/source/role에만 허용하고 나머지 IPv4/IPv6·local runtime·평문은 거부한다. 자세한 판단은 [ADR0024](../architecture/decisions/0024-camera-registry-schema7-tls-rehearsal.md)에 기록한다.

## 결과·실패 진단

scope는 camera_registry_schema7_tls_cutover_native_docker다. passed는 runner10개 phase, 필수 Go policy1개/native parent3개/transport5개 phase, 전체 vet·별도 policy race와 정리가 모두 성공해야 한다. native_probe_race_enabled=false는 scratch API에서 실행할 CGO=0 probe의 실제 범위다. Go test2json의 parent/phase 순서·terminal pass를 검사하며 skip·누락·중복·LOCAL marker는 성공 근거가 아니다.

로그와 report는 var/camera/registry-tls-checks 아래0700/0600으로 보관한다. 실패 공개 JSON은 code·failed_stage·last_completed_phase·command exit만 포함하며 DSN·비밀번호·PKI 내용은 내보내지 않는다. 실패 시 격리 DB/API의 제한된 로그를 private log에 수집하고 격리 자원을 정리한다. cleanup 실패는 passed로 표시하지 않고 synthetic_input_removed=false 및 private retained_workspace를 남긴다. 충돌한 기존 namespace는 삭제하지 않는다.

첫 서버 실행의 plaintext seed 실패 후 D1d HTTP client를 새 fixture ID에 맞게 수정했다. HTTP 실패에는 검증한 exception_type과 failed_http_step의 collection/method/synthetic resource_id/status/API error code를 추가한다. body·token·headers·원래 exception 문자열은 공개하지 않는다. 원래 Step10 mutation helper를 호출하지 않으며3개 campaign의 loopback 요청만 허용한다. HTTP ID 수정 당시 Python 자동 검사는32개였고 이후 네트워크 수정본의45개와 전체 native 리허설이 통과했다. 앞선 실패/수정 이력은 [수정 기록](../progress/20261012-step11d1d-http-fixture-id-fix.md), 최종 인수는 아래 절을 따른다.

최신 수정본은 API 전용 normal HTTP network와 기존 internal storage network를 분리한다. DB/migrator/maintenance/offsource는 HTTP망에 붙거나 포트를 게시하지 않는다. 실제 image/project/network ID·storage source·HTTP API 단독 연결·선언 및 actual loopback8080 mapping을4개 지점에서 검사한다. 단순 PortBindings 선언은 성공 근거가 아니다. 성공 report의 isolated_http_binding_checks_passed는4, isolated_loopback_http_port_and_storage_boundary_verified는 true여야 한다. Python 검사 수는45개이며 이전32개는 앞선 수정 이력이다. 새 network의 cleanup은 project Compose down에 포함된다.

포트 게시가 확인되지 않으면 plaintext_http_binding/tls_http_binding/recreated_api_http_binding/recreated_db_api_http_binding stage에서 실패한다. 게시 후 기존 준비 상태가 실패하면 http_readiness_probe에 status·알려진 platform/scope·boolean ready/business field와 존재 여부 또는 exception class를 기록한다. arbitrary body/string·token·DSN은 포함하지 않는다. [HTTP network 수정 기록](../progress/20261012-step11d1d-http-network-fix.md)의 source 및 서버 재검사 상태를 따른다.

현재 운영 서비스/DB/schema/HBA/.env/network·credential 키/admission·D1a 후보/D1c 준비 파일·볼륨은 변경하지 않는다. 운영 DB를 dump/restore하지 않고 백업을 만들지 않는다. 새 supply·binding 승인·운영 TLS·credential API 활성화는 수행하지 않는다. 전체 운영 준비와 business_runtime_ready는 false다. Streamlit 브라우저 인수는 계속 보류한다.

[구현 기록](../progress/20261012-step11d1d-registry-tls-cutover.md) · [D1c 인수](../progress/20261012-step11d1c-server-acceptance.md)

## 서버 인수 완료 — 2026-10-12

사용자 제공 revision1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159/project vms-registry-tls-test-cfeb7a2c0284의 status=passed를 확인했다. Python45개·필수 policy1개 race/vet·native peer3개/transport5개 phase·전환10개 phase와 isolated_http_binding_checks_passed=4가 통과했다. schema7·모든 row/journal·TLS/source/UID/RO·재생성과 격리 정리를 인수했으며 native_probe_race_enabled=false다. 이번 native 결과는 별도 합성 자원만 사용했고 운영 변경/공급/활성화 필드는 false다. 현재 최신 기준은 [D1d 서버 인수](../progress/20261012-step11d1d-server-acceptance.md)다. 앞선 본문에 기재한 재실행 대기는 당시 실패/수정 단계의 이력이며, 같은 native 검사를 인수 기록 patch 적용을 위해 반복할 필요는 없다.
