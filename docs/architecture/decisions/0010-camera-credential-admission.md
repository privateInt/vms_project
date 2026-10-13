# ADR 0010 — 외부 복원 차단 상태와 작업 구간 lease

날짜: 2026-10-02 · 상태: 11-B3c1 계획 계약 채택 · 구현/운영 활성화 전

## 문제와 선택

[11-B3b 서버 리허설](../../progress/20261002-step11b3b-key-supply-restore-rehearsal.md)은 DB snapshot에서 encryption budget이 3에서 1로 되돌아오는 상황과 기존 키의 쓰기 차단, 새 키/기존 암호문/HMAC replay를 입증했다. 그러나 해당 리허설의 NOLOGIN은 단일 DB dump 바깥의 같은 임시 클러스터 상태다. role/클러스터 전체 복원과 실제 runtime 입장을 보호하는 외부 권위는 아직 없다.

첫 구현 목표는 camera 단일 Linux 호스트의 유지보수 계정만 갱신하는 외부 state와 바뀌지 않는 sidecar lease다. DB/키 백업·프로젝트 트리와 분리한다. 새 복원 전 FENCED를 영속 확정하고 프로세스/계정/세션을 정지한 뒤 복원한다. 새로운 encryption key 후보를 PREPARED에 먼저 등록하고, 새 DB incarnation과 generation을 결합해 OPEN으로 진행한다. 운영 root/admin이 외부 권위까지 되돌리거나 임의 SQL로 우회하는 경우를 자동 해결한다고 주장하지 않는다.

## 대안과 이유

DB 내부 marker/budget만 사용하면 둘 다 snapshot으로 복원될 수 있다. read-only key mount만 확인하면 같은 key material의 사용량 rewind와 오래 실행되는 쓰기를 막지 못한다. startup에서 한 번 읽는 OPEN flag도 두 transaction 사이의 복원과 이전 pool/keyring을 보호하지 못한다. 따라서 marker와 파일 확인을 실제 작업 전 구간의 lease 및 계정/프로세스/네트워크 통제에 결합한다.

분산 ledger/consensus/KMS와 다중 호스트 admission은 이번 단일 호스트 범위보다 별도 인수 비용이 크다. 첫 버전은 이를 자동 대체하거나 NFS/JuiceFS로 확대하지 않는다. file 권위 유실/백업 충돌은 자동 bootstrap 대신 차단하고 승인된 별도 복구를 요구한다. generation/seen-ID 집합을 보존하고 암호화 material의 재라벨링을 금지한다. 실패/중단된 후보도 다시 새로운 후보인 것처럼 사용하지 않는다.

## 상태와 구현 경계

FENCED/PREPARED에서는 runtime 입장을 거부한다. OPEN은 조건부 의도이며 준비 완료 certificate가 아니다. actual role/database/endpoint/key loader receipt·migration/미래 schema 9 marker와 shared lease 확인을 요구한다. Writer의 기존 두 transaction·별도 budget commit과 과거 성공 replay 전체가 lease에 참여해야 한다. key file의 UID 전용 strict loader와 metadata control-record의 유지보수 UID/runtime GID 정책을 서로 바꾸지 않는다.

[계약](../../contracts/camera-credential-admission.md)이 기록 필드·전이·복원 순서·CAS/중단·세대/키 이력·검증 범위를 정의한다. schema/examples는 camera api/planned에만 추가한다. 현재 Go/SQL/Compose/HTTP·운영 schema 7·격리 schema 8·production_restore_fence_implemented=false는 유지한다. schema 9 marker와 external runtime guard는 후속 코드 단위에서 구현한다.

기록/예제의 정적 검사는 unknown fields·키 원문/DSN/경로/우회 옵션·잘못된 상태·역할·ID·int64/UTC 형태를 거부한다. 실제 flock/fsync/원자 교체·DB 권한·monotonic generation·anti-reuse·바이트 제한/raw JSON 검사는 아직 없다. 구조상 유효하지만 의미상 거부할 예제를 함께 보관해 static validation을 실제 admission으로 오해하지 않도록 한다.

## 근거와 다음 인수

[Linux flock(2)](https://man7.org/linux/man-pages/man2/flock.2.html)은 advisory lock와 open-file-description 소유를 설명한다. state 교체와 별도 stable lock을 분리하고 전 참가자의 협력을 요구하는 근거로 사용했다. [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)는 단일 DB와 global objects를 구분하고, [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)는 단일 transaction 복원을 제공한다. 제품의 외부 상태/세대 정책은 이 문서에서 선택한 설계이며 해당 도구가 자동 구현하는 기능이 아니다.

다음은 11-B3c2 외부 상태/lease의 로컬 구현·실패/경합 검사다. 이후 native DB/key/role/marker/쓰기 guard 결합과 실제 운영 준비/전환을 따로 인수한다. 이번 계약 패치는 복원/키/API 실행 도구가 아니다.

## 11-B3c2 구현 보완

계약 서버 정적 검사 23개를 인수한 뒤 camera/internal/credentialadmission에 parser/state machine과 Linux 외부 state·lease를 구현했다. lock이 교체된 뒤 시작하는 process도 거부하도록 Bootstrap의 device/inode receipt를 검토된 host Policy에 고정한다. state JSON에 비밀값이나 별도 readiness 필드를 추가하지 않는다. host 설정 공급·DB marker·실제 key receipt/쓰기 guard는 후속 통합이다.

기록 교체는 fsync/rename/부모 fsync이며 성공이 불명확한 lease는 재사용하지 않는다. 동일 기록 재시도도 fsync를 재확인해 rename 후 sync 실패를 단순 no-op으로 인정하지 않는다. shared 작업은 각자 descriptor를 소유한다. 실제 공개 reader는 RO mount와 owner와 다른 runtime UID를 요구한다. 여러 process drain/kill·IO 실패·권한/링크/경로/lock 교체·CAS와 fresh 후보 규칙은 로컬 race 검사에서 확인했다. 실제 Docker RO mount/UID 검사는 서버 인수 대기다. 이 기반만으로 운영 restore fence나 key budget/DB readiness를 완료 표시하지 않는다.
