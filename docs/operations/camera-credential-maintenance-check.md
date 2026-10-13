# camera credential 유지보수 DB 차단 격리 검사

상태: 11-B3c3d1 구현/로컬 검증 완료 · 서버 Docker native 인수 완료

## 전제와 격리

test_camera_credential_maintenance.py는 인수한 11-B3c3c revision과 현재 manifest의 모든 source hash를 검사한다. 임의 project vms-credential-maintenance-test-* 아래 새 PostgreSQL17.11 tmpfs·내부 network와 Golang1.27.1 검사 container를 만든다. source만 RO로 공급하며 운영 .env/DB/key/authority/volume/network를 연결하지 않는다. published port·privileged·host PID·external resource는 없다. host COMPOSE_/VMS_/CAMERA_/PG 설정을 제거하고 합성 password만 공급한다.

서버에서 Docker Compose와 image/dependency 다운로드가 필요하다. 유지보수 fixture는 해당 container의 실제 owner UID/GID로 private authority를 생성한다. runtime UID/RO key/TLS positive 검증은 인수한 11-B3c3c 결과이며 이 d1은 owner가 수행하는 DB gate와 실제 PostgreSQL account/session/2PC 검사다. d1의 native DB endpoint는 명시적 disable 모드의 isolated network이다. 이를 운영 TLS/네트워크 인수로 표시하지 않는다.

## 성공 기준

전체 module vet/race와 기존 native credential13개, 새 필수 maintenance4개 및 해당 native parent의 정확한 phase7개를 모두 요구한다.

| Native parent | 필수 phase |
|---|---|
| AuthorityAndIdentity | authority-rejection, unsafe-role-rejection |
| FenceAndRetry | no-login-existing-session, closed-database-drain, interrupted-fence-retry |
| PreparedTransactions | prepared-transaction-rejection, prepared-drain-retry |

실제 보호 파일/sidecar exclusive lease로 OPEN·stale record·closed lease·deadline 없음/취소·wrong endpoint/runtime role·위험 role을 거부한다. 이미 연결된 raw writer는 FENCED와 NOLOGIN만으로 종료되지 않음을 재현한다. target owner/writer/budget와 다른 DB의 writer 연결을 실제 gate/drain으로 제거하고 신규 target login을 owner까지 거부한다. 새 control connection과 lease에서 같은 record로 재시도하며 authority·committed row·budget42 보존을 확인한다. prepared transaction을 실제로 생성해 거부하고 fixture의 명시적 rollback 뒤 다시 차단한다.

fixture 정리는 격리 DB만 다시 열고 terminated pool을 reset해 역할·스키마를 제거한다. 이 test-only cleanup은 production primitive의 resume 절차가 아니다. 서버 runner는 검사 성공/실패와 무관하게 해당 project만 down/volume 제거하고 private log/report에 결과를 기록한다. 불완전 phase·skip·중복·wrong test/package·앞선 fail·source drift·cleanup 실패는 passed가 아니다. failed_native_test에는 allowlisted test 이름만 넣는다.

## 결과 해석

report는 var/camera/credential-maintenance-checks에 저장한다. production 서비스/DB/key/authority/API/restore fence/business runtime, database_and_key_restore_performed, network_fence_verified는 false다. 성공은 접속 차단·drain 기반의 인수이며 전체 복원 또는 운영 전환이 아니다. 적용/검사 명령은 채팅에서만 제공한다. 다음 단위는 account/network 경계와 실제 DB/key 복원·fresh key/budget/incarnation·PREPARED/OPEN을 연결하는 격리 통합이다.

서버의 새 maintenance4개/7 phase와 기존 credential13개, 전체 race/vet 및 격리 자원 제거를 인수했다. 결과는 [d1 기록](../progress/20261007-step11b3c3d1-maintenance-database-fence.md)을 따른다. 다음 접속 경계는 d2a, 실제 복원 통합은 그 인수 뒤 d2b로 분리한다.
