# camera 키·DB 접속 binding 격리 검사

상태: 구현·로컬 검사 완료 · 서버 native UID/RO/PostgreSQL TLS 인수 완료

## 격리와 실행 단계

src/infra/tools/test_camera_credential_bindings.py는 manifest/hash 및 11-B3c3a 서버 인수 flag·이번 revision을 확인한다. 새 vms-credential-bindings-test-임의값 project와 임시 DB tmpfs/exchange volume만 사용한다. source는 RO mount, 실제 key/production DB·.env·external authority 경로는 접근하지 않는다. project port publish·외부 volume·production network를 두지 않는다. host COMPOSE_/CAMERA_/VMS_BINDINGS_/VMS_ADMISSION_/PG 설정을 제거하고 빈 env-file을 사용한다.

1. golang1.27.1에서 module vet, storage race binary와 actual cmd/test2json을 빌드한다.
2. 별도 fixture test가 합성 bundle과 임시 CA/server certificate/key를 만든다. private bundle은 runtime UID10001 소유 mode0400/parent0500이다.
3. postgres17.11의 전용 owner container가 TLS server key를 postgres 계정의0400으로 준비한다. DB는 read-only exchange와 SSL/TLS1.2 이상으로 시작한다.
4. Go container에서 전체 module race 및 기존 credential native13개·profile/TLS/receipt 검사를 수행한다.
5. UID10001/GID10001·capability 없음·RO root/exchange·전용 tmpfs에서 native approved binding test를 실행한다. 실제 loader receipt, 두 fixed role TLS 접속·marker/history·budget ready, wrong CA/hostname/downgrade/hash/active ID/generation/권한 상실/disabled budget 및 검사 전후 사용0을 확인한다. mode0400/RW mount와 parser-only/legacy pool을 거부한다.

TLS certificate와 key bundle은 이 격리 검사에서 생성하는 합성 자료다. 외부 OPEN/PREPARED 값도 fixture이며 actual production authority/lease 승인을 대신하지 않는다. 준비와 runtime의 exact marker와 terminal test pass, 필수 binding5개·receipt2개·기존 native13개 및 package pass를 요구한다. 일반 regression의 skip만으로 native 작업을 인수하지 않는다.

## 결과

var/camera/credential-binding-checks에 private log/report를 보관한다. 실패 단계/마지막 완료 단계/실제 exit code를 기록한다. 실패·중단·불완전 transcript·source 변경·cleanup 실패를 passed로 표시하지 않는다. 자체 project의 down/volume 제거만 수행한다.

patch apply는 source와 원본 백업만 갱신한다. 이번 native 성공도 운영 키 로드/DB schema9 cutover/실제 authority 생성/credential API 활성화/production restore fence/업무 runtime 준비를 뜻하지 않는다. 다음은 CredentialStore 전체 작업 구간 lease다. 적용 명령은 채팅에서 제공한다.

2026-10-07의 실제 서버 결과는 [11-B3c3b 인수 기록](../progress/20261007-step11b3c3b-key-endpoint-bindings.md)을 따른다. 후속 revision에서의 전체 작업 lease 검사는 별도 runner로 수행한다.
