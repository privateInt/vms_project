# ADR 0017 — 유지보수 경계 아래 실제 복원과 PREPARED 후보

상태: 채택 · 2026-10-07 · 서버 격리 인수 대기

11-B3c3d2a의 native HBA 경계를 서버에서 인수했다. 이번 단위는 그 경계 안에서 실제 덤프와 정확한 키 백업을 복원하고, 사용 횟수가 과거로 돌아가는 상황을 독립 새 암호화 키로 처리한다. 종료 상태는 PREPARED, writer/budget NOLOGIN, target DB 신규 연결 차단이다. 업무 재개는 별도 완료 기준이다.

## 선택한 범위

CheckRestoreSuccessor는 비밀을 반환하지 않고 복원 후보와 복원 전/백업의 두 immutable ring을 비교한다. 양쪽의 모든 암호화·HMAC ID와 정확한 재료를 보존하며 현재 활성 HMAC을 유지한다. 새 암호화 ID는 두 입력에 없어야 하고 새 재료도 어느 입력의 암호화/HMAC 값과 같으면 안 된다. 백업 이후 쓰인 키를 빠뜨리거나 기존 재료에 새 이름을 붙이는 것을 허용하지 않는다. 이 검사는 신뢰된 입력의 출처·외부 seen-ID 이력·키 보관 정책을 대신하지 않는다. 키 개수 한계는 기존 bundle 한계인 집합당16개다.

PrepareRestoredCredentialDatabase는 trusted orchestration용 Go primitive다. 실제 exclusive lease와 durable PREPARED, protected loader의 exact candidate hash/활성 ID, 두 역사 ring, 승인된 backup marker를 받는다. FENCED/OPEN/lease 부재/바뀐 기록은 거부한다. 실제 maintenance control/target 연결의 동일 승인 endpoint·TLS·source·CN·role과 외부 HBA disk/NOLOGIN/2PC 상태를 검사한다. PREPARED 검사 허용은 이 primitive 내부에만 있으며 공개 InspectCredentialMaintenanceHBA는 FENCED 전용이다.

실제 migration1..9와 backup marker 또는 같은 candidate marker, 모든 암호문/HMAC의 key availability를 확인한다. 별도 serializable transaction에서 marker/budget 테이블을 잠근다. 최초 준비는 기존 budget의 uses를 보존하고 enabled만 false로 바꾸며 새 budget0과 fresh DB incarnation을 함께 커밋한다. 재시도는 정확한 candidate marker, enabled=true/uses=0, 새 키의 암호문 부재, 다른 budget 모두 disabled를 요구하고 아무 예산도 초기화하지 않는다. 일부 사용/disabled/다른 marker/이미 존재하는 후보 budget은 실패한다. 응답을 잃으면 같은 후보만 재검사하고 실패 시 PREPARED를 유지한다.

## 통합 리허설

새 disposable Compose는 기존 TCP readiness/default socket/별도 UID10001·RO probe 구성을 재사용한다. 고정 owner container를 PostgreSQL17.11 image로 선택해 pg_dump/pg_restore가 실제 유지보수 source IP에서 mTLS 인증한다. Go binary/test2json은 별도 build image에서 만든다. 운영 DSN/키/HBA/authority를 공급하지 않는다.

합성 credential history를 schema9에 작성하고 실제 custom dump·정확한 private key 복사본의 hash를 보관한다. 예산을 백업 이후 두 번 소비하고 FENCED→DB drain→maintenance-only HBA의 실제 인증 인수를 거친다. 승인된 유지보수 source만 target에 재접속하고, 손상 archive 실패 시 기존 데이터/권위 보존을 확인한 뒤 pg_restore의 single transaction으로 복원한다. 정책 파일·외부 권위·cluster role은 이 DB archive 밖에 남는다. 이전 키를 즉시 disable하고 역사 복호화/원본 ciphertext·HMAC 행 hash와 budget rewind를 확인한다.

PREPARED를 먼저 커밋한 뒤 종료된 별도 프로세스가 후보를 준비하고 다시 생성된 프로세스가 재시도한다. 마지막 negative fixture는 새 budget을1로 소비하여 재시도가 reset하지 않는지 확인한다. 따라서 마지막 후보는 의도적으로 재개 불가다. 마지막에 target도 닫는다. OPEN/LOGIN/업무 성공을 표시하지 않는다.

## 신뢰와 남은 작업

dump는 신뢰된 승인 백업이어야 한다. pg_restore는 archive의 SQL을 실행하므로 hash 일치만으로 비신뢰 dump가 안전해지지 않는다. 이 primitive는 DB/key 복원, HBA 설치/reload/active-policy 인수, maintenance-only reopen을 자동화하지 않는다. 그 작업은 이번 disposable fixture에서만 수행한다. privileged source와 control-plane/host 관리자 독점·replica/다른 endpoint/packet filter는 배포 절차의 별도 책임이다. 현재 HBA 검사도 disk snapshot이며 신규 실제 인증을 대체하지 않는다.

다음 단위는 재개 전 후보·grants·RO key/authority·두 실제 TLS role의 검사, durable OPEN과 runtime HBA/LOGIN 재개 순서, 중단 시 차단 유지의 격리 통합이다. full production restore fence·운영 key/API·business runtime는 계속 false다.

공식 근거: [pg_dump17](https://www.postgresql.org/docs/17/app-pgdump.html), [pg_restore17](https://www.postgresql.org/docs/17/app-pgrestore.html). pg_restore의 single transaction 및 archive SQL 실행 성질은 공식 문서를 따르며 본 프로젝트의 검증 사실은 진행 기록에 구분한다.
