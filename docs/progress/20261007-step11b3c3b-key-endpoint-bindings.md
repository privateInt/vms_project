# 단위 11-B3c3b — 키 로더 영수증·DB 접속 profile 비교

작성일: 2026-10-07 · 구현·로컬 검사 완료 · 서버 native UID/RO/PostgreSQL TLS 인수 완료

## 선행 인수와 범위

11-B3c3a 서버 source14개 적용·unit13개·native passed를 인수했다. checked_revision 81abb5d7962b9d9ed6dc01a2511faa5924185d18c56bc67de97fdc74031b8838의 Go race/vet와 전체 top140/sub406, 필수 DB5개·기존 credential native13개 및 실제 dump restore가 통과했다. 실제 운영 schema7/API0.7.0과 private keys/admission은 변경하지 않았으며 격리 자원 제거를 확인했다. UI 브라우저는 deferred이고 중계를 추가하지 않는다.

이번 독립 단위는 actual protected ring과 승인 single endpoint를 두 실제 DB role/표식에 비교하는 storage foundation이다. 전체 CredentialStore 작업 구간 lease·maintenance restore 절차·credential HTTP/운영 전환은 다음 단계다.

## 구현

- protected file loader에 exact-byte bundle SHA-256와 실제 Linux RO mount 관찰을 기록했다. parser-only ring에는 이 영수증이 없으며 file mode0400/RW mount는 RO로 인정하지 않는다. immutable ring/영수증은 이후 파일 교체에 따라 바뀌지 않는다.
- private immutable CredentialEndpoint는 canonical IP 하나/port/DB/명시적 disable 또는 verify-full을 지원한다. 실제 CA PEM 한 장에서 digest/CertPool을 얻고 fixed ordered compact JSON hash를 만든다. 주소 원문/DSN/password/CA key를 serialize하지 않는다. DNS·UDS·자동 failover·여러 CA/client cert는 아직 지원하지 않는다.
- 새 opener는 explicit role/password/IP/port/DB/sslmode URI만 인수한다. duplicate query·주소 override·ambient PG·service/passfile/default CA를 사용하지 않고 controlled pgx config에 승인 TLS를 붙인다. fallback이 없으며 actual peer/TLS1.2+/server name/verified CA chain을 확인한다. legacy Open에는 endpoint receipt가 없다.
- CheckCredentialAdmissionBindings는 locked external record에서 전달할 PREPARED/OPEN과 loader RO/hash·active encryption/HMAC ID·endpoint hash·두 distinct approved pool·actual TLS/session/current role/DB/marker/history·budget ready를 읽기만 대조한다. pool별 같은 acquired connection과 read-only repeatable-read snapshot을 사용한다. 실패는 내부 cause 없는 고정 코드다.
- 기존 schema8/legacy registry/단위11-B3c3a의 public DB reader는 유지했다. transport와 표식 검사에 같은 snapshot helper를 재사용하며 기존8/새9 migration SQL은 변경하지 않았다. Store의 private field 추가에 맞춰 기존 lazy-pool fixture만 keyed literal로 수정했다.

## 검증

| 검사 | 결과·범위 |
|---|---|
| 새 Go race | receipt2개·endpoint3개 통과. exact bytes/immutable ring/parser-only/RW0400, canonical JSON·CA 입력 소유권·privacy/DSN 제한·ambient service, 실제 Go TLS handshake/verified chain/다른 CA·transport mode 비교 |
| 기존 crypto 관련 race | KeyBundle·Keyring 및 protected loader의 load/reject 회귀 검사 통과. foreign UID chown 검사는 로컬 namespace에서 실행하지 않으며 서버 전체 module 검사가 요구 |
| 실제 local PostgreSQL race | storage top67/sub61 통과. 기존 DB native5개·credential native13개, actual plaintext single endpoint 연결 및 verify-full 실패의 plaintext fallback 부재 포함 |
| Go vet | 전체 module 통과 |
| Python runner | 새12개 통과. 모든 단계 실패/timeout/cleanup/source drift/protected sentinel, marker/order/skip/incomplete transcript/crypto package proof 검사. 관련 기존 unit 포함65개 통과 |
| 전달 | 모든 baseline/payload/manifest hash, 최초 적용/재실행/백업 원문/protected fixture/충돌 사전 거부/archive 검사 |

local PostgreSQL17.11 빌드는 직전 단위의 UID0-only namespace 대응 initdb/postgres 시작 조건 두 곳 수정 fixture를 재사용했다. SQL/인증 코드는 변경하지 않았으며 DB/binary/password/CA/private fixture는 패치에 포함하지 않는다. 모든 local DB process를 종료했다. Docker가 없으므로 UID10001/actual RO key mount/실제 PostgreSQL TLS를 한 runtime에서 결합하는 positive 검사는 아직 서버 인수 전이다. 일반 Go TLS handshake 통과와 PostgreSQL plaintext 검사로 그 native proof를 대체하지 않는다.

제공한 runner는 unmodified postgres17.11-bookworm/golang1.27.1-bookworm, 합성 CA와 key bundle, 실제 RO volume·UID10001에서 완전한 binding 검사와 전체 module race/vet를 요구한다. 필수 binding5개·receipt2개·native prepare/runtime2 phase·기존 credential native13개·완전한 package terminal pass와 cleanup이 모두 통과해야 한다.

API process/routing/제품 운영 Compose는 변경하지 않아 기존 smoke62개 인수를 유지한다. 추가 Compose는 격리 검사 전용이다. patch apply는 source와 private 원본 백업만 쓰고 runtime 활성화/DB DDL/실제 key/외부 authority 작업을 하지 않는다.

## 남은 작업과 다음 완료 기준

서버 source 적용·runner12개 unit·native UID/RO/TLS report를 인수한다. 다음 11-B3c3c는 CredentialStore의 최초 DB 접근부터 budget reserve/encrypt/save/응답까지, replay/revoke/reference를 포함한 모든 작업에 shared admission lease를 결합한다. marker/profile/key 비교를 lease 아래 호출하고 유지보수 exclusive lease의 대기·drain·fence와 작업 중 프로세스 실패를 native 환경에서 검증한다.

이번 비교 성공은 입장 승인/전체 private 권한/restore fresh-key 독립성 증명이 아니다. 운영 키 공급·full restore fence·credential API·business runtime은 아직 false다. maintenance FENCED→복원→PREPARED→fresh budget/marker→OPEN 절차와 운영 schema9 preflight/rehearsal/activation은 후속 독립 단위다. 명령은 채팅에서 제공한다.

## 서버 인수 — 2026-10-07 10:51 Asia/Seoul

사용자 로그의 적용23개/unit12개 OK와 native passed를 인수했다. checked_revision은 7ee49570fe511cc30d13742b38c84e1c47fa03832df79bc1ec1256d12f11c43e, project는 vms-credential-bindings-test-afc322003d8a다. 전체 Go race/vet top146/sub412, 기존 credential native13개·binding5개·receipt2개·native2 phase가 통과했다. exact loader bytes/RO mount/separate UID/actual two-role TLS, wrong CA/hostname/downgrade/marker/key/profile mismatch 거부와 검사 중 budget 소비0을 확인했다. production 서비스/DB/key/authority/API/restore fence/business runtime은 false, isolated_resources_removed=true다.

로그와 보고서는 var/camera/credential-binding-checks/vms-credential-bindings-test-afc322003d8a-irs2wp8o.log 및 같은 폴더의 vms-credential-bindings-test-afc322003d8a.json이다. 소스 백업은 var/patch-backups/step11b3c3b-j_fh8ssj다. 다음 구현은 [11-B3c3c](20261007-step11b3c3c-credential-operation-leases.md)이며 그 native 통합 인수는 별도다.
