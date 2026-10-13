# 11-D1d — schema7 등록 API와 TLS 전환 격리 리허설

상태: 서버 Docker/native 격리 인수 완료 · 운영 TLS 미전환

## 이번 결과

현재 운영 API0.7.0-device-delete와 DB의 immutable image ID를 그대로 새 테스트 프로젝트에 실행하는 리허설을 추가했다. 최초 plaintext schema7에 장치/소스 CRUD·모든 멱등성 이력을 만들고 API를 중지·drain한 뒤 같은 격리 data volume을 TLS로 전환한다. 기존 행·profile·journal·권한·조회/목록·최초 응답 재생을 확인하고 새 TLS CRUD·API 재생성·DB/API 재생성까지 검사한다. 운영 프로세스와 준비된 TLS 볼륨을 전환하지 않는다.

신규 Go test는 현행 public Open의 TLS·CA·hostname·SQLSTATE·source·실제 DB/session role을 확인한다. current CheckReady의 schema8 요구와 분리해 migration1~7 name/checksum·schema8 객체 부재를 읽기만 확인한다. runtime probe는 실제 isolated API 컨테이너 안에서 PID1 UID65532와 RO 공급을 검사한다. 별도 maintenance10002/offsource10003을 사용한다. HBA/ident와 TLS 파일은 PGDATA 밖 RO volume에 둔다.

PostgreSQL17.11 실측으로 SCRAM+map HBA 불가를 확인하고 maintenance migrator는 cert map으로 구현했다. client CN=camera_maintenance를 기존 camera_migrator에 exact 매핑하며 runtime은 SCRAM/verify-full을 유지한다. cert의 잘못된 CN은 SQLSTATE28000, runtime의 잘못된 password는28P01로 구분했다. pg_stat_ssl client DN의 실제 /CN= 표기도 확인했다. TLS migrator를 password+cert 이중 인증으로 표시하지 않는다.

## 로컬 검증

| 검사 | 결과와 범위 |
|---|---|
| Python runner22개 | 통과. 실제 새 PKI/파일 선별·권한, parser fail/skip/missing/중복/LOCAL 차단, mock 순서/drain/replay/recreation·namespace collision·실패/uncertain create/cleanup/private diagnostics |
| Go policy | TestRegistryTLSInputPolicy race1개 통과 |
| 전체 Go vet | 통과 |
| 실제 PostgreSQL17.11/pgx5.11.0 | schema7 source SQL/ledger/grants를 새 로컬 DB에 구성, LOCAL transport1개 parent의5개 phase 통과: runtime TLS+권한상승 거부·runtime 인증 거부·migrator mTLS map·client 인증 거부·다른 source 거부 |
| native 경계의 음성 확인 | 로컬 root native runtime 실행 거부, LOCAL transcript native 성공 처리 거부 |
| CGO=0 test probe | 빌드 통과. scratch API 컨테이너에서 실행할 native probe에 race 적용을 주장하지 않음 |
| Python3.10·쉘·전달 패치 | Python 문법·BUILD/OWN_FILES shell syntax, 전체 baseline/source/payload hash·적용/재적용·conflict·보호 파일/권한·archive 검사 |

로컬 PostgreSQL은 test-only 빌드·loopback 진단이며 Docker·현재 운영 이미지의 HTTP 전환·UID999/65532/10002/10003·실제 RO volume 인수가 아니다. 합성 키와 DB는 진단 종료 후 제거했다. Go native peer는 대상 서버에서 필수3개 parent/5개 transport phase로 검사한다. runner의10개 전환 phase와 transport5개 phase를 합산해 하나의 검사 수로 표시하지 않는다. no-new-business-code: 기존 API/main/store/SQL/Compose 원본을 변경하지 않고 검사·문서만 추가한다.

## 기존 인수 보존

사용자 제공 D1c 기록 패치는 SHA2562a6cd5f1e5c93eedcbad343eafeec177f6575659bfadb2f885119ee33304c333의 checksum OK, applied/written7/pending0이다. 이력은 var/patch-backups/step11d1c-notes-qxqx39_9이며 restart/runtime activation/schema modification은 false다. baseline manifest a4da43346cdc26dbe53dd490918425f9c66c9ba8e8a9ede5d8ad014e6a315d09의502개 tracked 파일에서 이번 단위를 시작했다. D1c 실제 server 검사 revision5d2f6e3ce0016e173157051c44540cc9cbc8274d8cf567711985701c9815c9d7 및 candidate/supply hash·볼륨·native probe3/UID denial6 인수는 유지한다.

## 미완료와 다음 단위

서버 리허설은 아래 최종 인수 결과로 완료했다. 다음 11-D1e에서 현재 공급·주소·기존 schema7 경로에 한정한 운영 DB TLS 전환을 준비한다. credential 역할/DSN·schema9/admission/main HTTP·IAM·실제 관리 사용 guard는 이후 독립 단위로 진행한다. ConnectionConfig·SourceSession·실장비/영상·model/analysis/operation 업무는 남는다. 이번 patch 자체는 운영 서비스 재시작/DB/schema 변경을 요구하지 않는다.

사용자 요청에 따라 백업의 추가 구현·검토·리허설을 제외한다. Streamlit 브라우저 인수 보류·Jupyter 중계 미구현을 유지한다. 실행 명령은 채팅에서 별도로 전달한다.

[검사 안내](../operations/camera-registry-tls-cutover-check.md) · [ADR0024](../architecture/decisions/0024-camera-registry-schema7-tls-rehearsal.md)

## 첫 서버 실행과 HTTP fixture ID 수정 — 2026-10-12

서버 패치11개와 Python22개는 통과했으나 native 리허설은 plaintext_registry_seed에서 실패했다. Go race/vet·격리 자원/합성 입력 정리는 통과했고 운영 관련 필드는 false다. 이전 Step10 HTTP helper의 고정 ID 제한이 D1d의 신규 fixture PATCH를 요청 전에 거부하는 결함을 재현해 전용 HTTP client로 수정했다. 새 Python32개·실제 현재 Go API/schema8의3개 campaign·성공 mutation14개·전체 재생/활성 자식 재시도/API 재생성이 통과했다. 운영 schema7 image·Docker/TLS 전환 성공으로 표시하지 않는다. 이 절의22개·5개 LOCAL phase는 원래 구현 당시의 기록이며 이번 수정 검증과 합산하지 않는다. [HTTP ID 수정 기록](20261012-step11d1d-http-fixture-id-fix.md)에 revision·실패·검증·서버 재실행 기준을 기록한다.

그 뒤 서버의 HTTP ID 수정본/Python32개 재실행을 확인했으나 native는 CAMERA_REGISTRY_READINESS_FAILED로 멈췄다. 테스트 API를 internal storage network에만 연결한 구성 결함을 수정해 API 전용 normal HTTP망·실제 loopback port/source/network 검사4개·안전한 readiness 진단을 추가했다. 수정 당시 Python45개·4 platform foundation smoke62개는 통과했고 서버 재인수는 대기 상태였다. 이후 성공은 아래 최종 인수와 [HTTP network 수정 기록](20261012-step11d1d-http-network-fix.md)에 반영한다.

## 최종 서버 인수 — 2026-10-12

HTTP network 수정의 checksum OK·applied/written10/pending0·Python45개 OK와 native status=passed를 확인했다. checked_revision1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159/project vms-registry-tls-test-cfeb7a2c0284에서 필수 policy race1개/vet·native peer3/transport5개 phase·전환10개 phase·actual HTTP binding4개가 통과했다. 같은 운영 image의 schema7·등록/삭제/모든 journal·실제 TLS/source/UID/RO·API/DB 재생성과 정리를 인수했다. native probe race=false·운영 변경/활성화 false를 유지한다. 최신 근거와 다음 D1e 준비 범위는 [서버 인수 기록](20261012-step11d1d-server-acceptance.md)을 따른다. 위22/32/45개 로컬 검사·실패/대기 문구는 각 시점 이력으로 보존한다.
