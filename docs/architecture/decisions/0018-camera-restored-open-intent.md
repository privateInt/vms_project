# ADR0018 — 복원 후보의 OPEN 의도와 실제 업무 재개

상태: 채택 · 2026-10-07 · 소스/로컬 검증 완료, 서버 Docker 인수 대기

## 배경과 판단

d2b 서버 검사에서 실제 DB/key 복원과 새 key/incarnation/budget/marker 준비를 인수했으나 종료 상태는 PREPARED·target closed·업무 역할 NOLOGIN이다. 유지보수 권한과 복원 입력을 가진 프로세스가 즉시 업무 API가 되지 않도록 OPEN 의도 기록과 실제 런타임 인증·전 작업 lease를 분리한다.

기존 후보 primitive를 공통 검사로 추출한다. prepare=false는 이미 정확히 commit된 marker·새 budget0·old disabled만 허용하고 INSERT/UPDATE/repair를 하지 않는다. 초기 OPEN은 이 검사와 외부 exclusive lease 아래에서 기록한다. 동일 OPEN 재호출은 당시 의도만 확인한다. 재개 후 실제 write가 budget을 소비했더라도 OPEN 재확인이 counter를 초기화하지 않으며, runtime은 매 업무 호출의 기존 public guard에서 actual key/endpoint/marker/grants/budget을 다시 검사한다.

제품에는 source-pinned runtime HBA builder와 privileged OPEN primitive까지만 둔다. HBA 설치/reload·LOGIN·dump/restore·process 실행은 이번 disposable test fixture에 한정한다. OPEN 다음 HBA/LOGIN 단계가 끊기면 업무 계정은 계속 잠긴 상태다. 신뢰하는 배포 관리자, 승인 source/DB endpoint, 독점 관리 채널은 전제이며 host/network packet filter나 다른 관리자의 변경을 방어했다는 주장은 하지 않는다. 운영 자동 복원/재개 기능을 완성한 것으로 표시하지 않는다.

## 영향과 검증

마이그레이션·업무 HTTP routes·운영 Compose·API 버전은 변경하지 않는다. 공통 candidate 검사 추출의 회귀는 d2b 실제 복원·used budget 거부 검사에서 확인한다. 새 d2c 별도 DB는 unused candidate에서 OPEN·중단 재시도·계정 재개·새 키 저장·historical/new HMAC replay·reference·새 프로세스 replay를 실행한다. 사용자 서버에서 UID10001/RO mount/실제 두 TLS role의 전체 public guard 성공까지 확인해야 인수한다. 로컬 owner/RW 검사는 LOCAL prefix로만 기록하고 native summary에서 거부한다.
