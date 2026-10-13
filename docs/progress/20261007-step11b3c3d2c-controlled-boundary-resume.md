# 단위 11-B3c3d2c — 복원 후 OPEN 의도와 격리 업무 재개

작성일: 2026-10-07 · 소스/로컬 검증 완료 · 이후 서버 Docker 인수 완료

## 선행 서버 인수

사용자 실행 결과에서 d2b owner environment fix patch7/pending0·Python33 OK를 확인했다. project=vms-boundary-restore-test-511a65221d6f, checked_revision=172e084b609aa8a06940cd8d4f4670c7f1b850844260f14752094ab1e46c11da, status=passed, restore8/native15, Go race/vet=true, top159/sub410이다. 실제 dump/key restore·budget rewind·historical ciphertext/HMAC·independent fresh key/incarnation·PREPARED-before-budget·same candidate retry·used budget reset/wrong marker/corrupt archive 거부를 인수했다. 최종 PREPARED/target closed/runtime NOLOGIN, owner PG environment absence·isolated resources removed=true다. 실제 복원은 격리 DB이며 production/API/business/full restore fence는 false다.

## 구현 결과

- 후보 검사를 공통화하고 pure mode에서 이미 commit된 정확한 marker와 fresh enabled uses0, old disabled만 허용한다. 원래 backup marker를 OPEN 단계가 보정하거나 budget을 등록·초기화하지 않는다.
- privileged AuthorizeRestoredCredentialOpen은 exact prepared/opened 쌍·exclusive lease·actual maintenance TLS/source/HBA·protected candidate/history keys·schema/marker/budget를 확인하고 동일 binding/generation/op/history의 OPEN을 durably 기록한다. 동일 OPEN의 새 관리 process 재시도는 의도만 재확인하고 이후 사용량을 보존한다. 실제 runtime readiness는 기존 public guard의 책임이다.
- complete runtime HBA builder는 유지보수 mTLS source와 별도 runtime source를 분리한다. runtime source는 target DB의 two fixed roles/SCRAM/TLS만 허용한다. HBA 설치/reload·LOGIN·process 실행은 disposable native fixture에서만 수행한다.
- 격리 재개 24 phase는 실제 복원과 commit 직후 uses0 후보부터 OPEN → 여전히 NOLOGIN인 중단 상태/실제 인증 거부 → OPEN 재시도/인증 거부 → runtime boundary/LOGIN → UID10001·RO exact keys/authority·실제 두 TLS pool/public whole-operation guard → restored/new HMAC replay·새 key version2 저장·reference → account/OPEN retry·새 runtime process replay를 연결한다. final OPEN/uses1과 양쪽 ciphertext 보존을 확인한다.
- uses1 후보의 OPEN 거부는 별도 d2b 복원 회귀 fixture의 마지막에 추가했다. 양성 재개와 별도 DB/keys/project에서 수행하며 사용량을 0으로 되돌리는 절차는 없다. 초기 시험이 되감기를 시도하자 기존 monotonic DB guard가 차단했고 이 구조로 고쳤다.
- strict owner env allowlist를 새 resume selector까지 확장했다. CHOWN/FOWNER만 가진 관리 owner가 UID10001 private 파일을 읽지 않도록 owner용 root0600 receipt와 runtime용 UID10001 copy를 분리했다. 모든 phase 증거의 test/package/run/output/pass/global order를 확인하고 LOCAL prefix·skip·missing·실패·source drift·cleanup failure는 인수를 취소한다. 실패 diagnostics는 cleanup 전에 private log에 수집하며 production input을 읽지 않는다.

## 검증

| 검사 | 결과 |
|---|---|
| 새 runner Python | 36개 통과. 24 phase·모든 실행 stage 실패/cleanup·중단 restore 상태·LOCAL resume 거부·shell PG scrub/argv literal·필수 값 누락 포함 |
| 관련 credential Python | 197개 통과 |
| 실제 로컬 PG17.11/OpenSSL·Go race | 별도 fresh DB의 restore 회귀15 phase: 사용량1 후보의 Prepare/OPEN 거부·미전환 확인. 재개24 LOCAL phase: 실제 dump/key restore, OPEN/중단 retry/NOLOGIN, two role source pin, 새 ciphertext/HMAC replay/reference·process recreation·post-write budget 보존. storage top82/sub61 및 전체 module vet 통과 |
| Go unit | runtime HBA exact IPv4/IPv6·ambiguous source/DB 거부, missing authority/deadline 거부 및 기존 후보 단위 통과 |
| 패치 | 서버 accepted baseline389개/hash172e084b…에서 delta16개/archive19개. dry-run·backup apply·재실행·baseline user edit/new destination collision·protected env/key/authority sentinel 보존·archive 제외/helper8개 통과 |

로컬은 Docker/별도 UID/RO mount 성공을 확인할 수 없는 환경이다. root-start 거부 두 곳만 수정한 local PG fixture에서 원본 SQL/auth와 distinct loopback을 사용했고 owner image PG defaults를 실제로 주입·새 allowlist로 제거했다. LOCAL runtime은 public guard가 owner/RW를 거부함을 확인한 뒤 test-only synthetic guard로 DB 동작을 진단했다. 실제 UID10001/RO/public guard 성공은 서버 Docker의 native prefix로만 인수하며 완료 flag를 false로 유지한다. 로컬 PG process는 종료하고 synthetic DB/keys/cert/password/archive/binary를 패키지에 넣지 않는다. product routes/process/migrations/운영 Compose 변경이 없어 smoke를 반복하지 않았다.

## 미완료와 다음 단위

서버에서 Python36, 복원 회귀8/native15·used candidate OPEN 거부 및 재개12/native24·credential13·race/vet·isolated removed를 확인해야 한다. 이후 실제 운영 key/authority/HBA/단일 endpoint·source 공급을 검토하고 production full restore fence·schema9 운영 전환을 별도 preflight/rehearsal/activation 단위로 진행한다. 운영 schema7/API0.7.0-device-delete, 실제 credential API/business runtime은 미전환이다. Streamlit browser acceptance는 deferred, Jupyter 중계는 추가하지 않는다. 적용 명령은 채팅에서 제공한다.


## 서버 후속 인수 — 2026-10-07

사용자 결과에서 patch16/pending0·Python95와 같은 revision7d3168b4…의 복원8/native15·재개12/native24 및 race/vet=true를 확인했다. 복원 top161/sub410·재개 top163/sub410, 실제 별도 UID/RO mount/public guard·업무 저장/참조/재시도·새 프로세스 재생·post-write budget 보존이 모두 통과했다. resources_removed=true이며 production 변경/API/business/full restore fence는 false다. 이 문서의 앞부분은 당시 소스 전달/로컬 검증 기록이고 현재 상태는 [서버 인수](20261007-step11b3c3d2c-server-acceptance.md)를 따른다.
