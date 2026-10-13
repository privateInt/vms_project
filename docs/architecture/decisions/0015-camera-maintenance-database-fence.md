# ADR 0015 — FENCED와 결합한 DB 접속 차단·세션 종료

상태: 채택 · 2026-10-07 · 11-B3c3d1 구현/로컬 검증 완료, 서버 native 인수 완료

## 결정

cooperative flock만으로 direct SQL이나 소유자 연결을 차단할 수 없다. FenceCredentialDatabase는 정확한 외부 FENCED와 deadline 있는 exclusive lease를 먼저 확인·fsync한 뒤 DB 계정과 접속 문을 닫는다. 유지보수 호출자는 lease를 단독 소유하며 전체 후속 절차가 끝날 때까지 Close/Commit을 동시에 호출하지 않는다. 별도 postgres control DB를 같은 검토된 단일 endpoint에서 사용하므로 target DB가 신규 연결을 거부해도 재시도할 수 있다. DB/endpoint/세대는 재발견하지 않는다.

실제 maintenance connection은 검토된 canonical IP/port/transport, postgres DB, session=current user, LOGIN superuser이면서 target DB owner여야 한다. 첫 owner 모델은 제한된 격리 기반이며 운영 계정/secret 공급은 아직 없다. 고정 writer/budget의 superuser/createdb/createrole/replication/bypassrls 속성과 prepared transaction을 거부한다. SQL의 catalog/function은 pg_catalog로 고정한다. 검토된 last binding에서 target DB를 얻고 Identifier로 인용한다. bootstrap의 binding 없는 초기 FENCED는 허용하지 않는다.

두 credential role NOLOGIN과 target ALLOW_CONNECTIONS=false를 하나의 catalog transaction으로 커밋한 후 대상 모든 세션과 두 역할의 이 cluster 내 다른 DB 세션을 종료한다. signaling true만으로 종료 완료를 표시하지 않고 refreshed pg_stat_activity의 0과 catalog 차단 상태를 확인한다. target의 기존 owner 연결도 종료한다. 다른 DB의 unrelated maintenance owner 세션은 유지한다. prepared transaction의 사전/사후 부재를 요구한다. pg_prepared_xacts가 남으면 자동 처분하거나 복원을 진행하지 않는다.

## 중단과 경계

외부 FENCED fsync가 불명확하거나 precondition/DB/드레인 검사가 실패하면 cause 없는 고정 CREDENTIAL_MAINTENANCE_UNAVAILABLE를 반환한다. 성공 응답이 유실돼도 같은 세대·operation·binding의 새 maintenance lease/control 연결에서 다시 검사·차단할 수 있다. 자동 LOGIN/DB 재개·authority rollback·use reset·budget reactivation·lease Close를 제공하지 않는다. 후속 restore는 이 primitive 반환 뒤에도 exclusive lease를 보유해야 한다.

이 단계는 차단 기반 하나를 인수한다. DB/key restore·새 독립 key material·budget disable/enrollment·새 incarnation/marker·PREPARED/OPEN 검증은 별도다. target 신규 연결을 모두 막으면 registry 연결도 영향을 받는다. 실제 DB 복원을 위한 privileged reconnect를 허용하기 전에 계정과 네트워크 경계를 구현·검증해야 한다. OS/service 관리자나 control DB에 접근 가능한 별도 superuser가 catalog를 되돌리는 행위, replica/다른 endpoint/host rollback은 이 primitive의 보장 밖이다. network fence와 전체 production restore fence는 false다.

근거: [PostgreSQL17 ALTER DATABASE](https://www.postgresql.org/docs/17/sql-alterdatabase.html)의 ALLOW_CONNECTIONS, [administration functions](https://www.postgresql.org/docs/17/functions-admin.html)의 signal acknowledgement와 termination 구분. 전이·lease 계약은 [credential admission](../../contracts/camera-credential-admission.md)을 따른다. 실제 NOLOGIN 후 기존 writer 세션의 UPDATE 성공과 전체 DB gate 뒤 종료는 native test로 각각 확인한다.

서버 native4개/7 phase와 전체 race/vet를 인수했다. 상세 결과는 [d1 기록](../../progress/20261007-step11b3c3d1-maintenance-database-fence.md)을 따른다. 유지보수 HBA 경계 d2a와 실제 복원 d2b를 순서대로 진행한다.
