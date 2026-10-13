# ADR 0014 — credential 작업 전체에 외부 admission lease 적용

상태: 채택 · 2026-10-07 · 11-B3c3c 서버 native 통합 인수 완료

## 결정

키/profile 비교가 성공해도 비교 직후 유지보수가 복원하거나 예산을 되돌리면 안전한 작업 입장이 아니다. NewAdmittedCredentialStore가 검토된 외부 Policy/안정 lock identity, 완전한 OPEN record, 승인 endpoint를 받는다. record의 binding/history는 복사해 소유한다. 생성자는 DB 작업을 하지 않으며 기대 기록을 자동 재발견하지 않는다.

WriteVersion, RevokeVersion, CheckReference, CheckReady는 실제 RO authority shared lease를 최초 credential DB 접근 전에 획득한다. 실제 loader/key/profile/두 역할/DB 표식/history/budget ready와 필요한 업무 grants를 검사한다. 각 data transaction과 별도 budget transaction의 실제 connection에서도 transport, session/current role, history/marker, 필요한 개별 grants를 다시 확인한다. lease는 첫 확인, committed budget, 암호화/저장, replay, 최종 검사와 Go 메서드 반환까지 유지한다. rollback/commit의 내부 defer가 실행된 뒤 외부 lease가 해제되므로 error/panic에도 이 순서를 유지한다.

NewCredentialStore는 비교 검사 전용 foundation으로 남긴다. 승인 guard가 없는 모든 업무/CheckReady 호출은 고정 CREDENTIAL_ADMISSION_UNAVAILABLE로 DB 접근 전에 차단한다. 기존 schema8 검사 전용 guard는 _test.go에만 존재한다. production 생성자는 caller callback으로 guard를 대체하거나 끄는 옵션을 제공하지 않는다. pool 초기 연결과 foundation read-only 비교는 업무 입장 승인과 별개다.

## 트랜잭션과 중단

budget SQL function은 data transaction과 다른 pool의 독립 transaction에서 커밋한다. 이후 data 작업이 실패하거나 프로세스가 종료해도 소비한 use를 되돌리거나 재사용하지 않는다. commit 응답이 불확실하면 기존 멱등 journal을 통해 확인한다. 최종 lease 검사 실패 시 성공 metadata를 반환하지 않아도 이미 커밋된 journal/use가 존재할 수 있다.

유지보수는 같은 안정 lock의 exclusive lease로 모든 cooperative 작업의 종료를 기다린 뒤 FENCED를 커밋해야 한다. 작업 도중 프로세스가 죽으면 kernel이 descriptor/flock을 해제한다. 이전 OPEN을 pin한 재생성 프로세스는 FENCED 또는 다른 generation에서 자동 repin하지 않는다. storage 메서드 반환 이후 HTTP 응답 전송의 수명은 아직 구현하지 않은 HTTP 계층의 별도 책임이다.

## 범위와 검증

고정 역할의 위험 속성, marker/history 변경권한 부재와 필요한 개별 업무 grants를 검사한다. PostgreSQL의 comma-separated privileges는 ANY 의미이므로 SELECT와 INSERT는 각각 검사한다. 모든 private table의 과도 권한을 총망라하는 감사·비협력 계정/네트워크 차단·fresh key material 독립성·전체 복원 운영 절차는 후속 단위다. 실제 운영 schema7/API/keys/authority는 변경하지 않는다.

서버 runner는 기존 UID10001/RO key/TLS binding과 전체 race/vet를 재확인한 뒤 실제 RO/RW authority mount를 같은 volume에 연결한다. maintenance UID0가 UID10001·effective capability0 자식 runtime을 실행한다. 여섯 업무 흐름의 유지보수 대기/정상 drain, error/panic/cancel 정리, budget 커밋 직후 SIGKILL/drain/FENCED, stale process 재생성 차단을 검증한다. 합성 isolated DB owner DSN은 fixture 준비/검사 전용으로 runtime 프로세스에도 전달되며 실제 배포 권한 구성을 의미하지 않는다. 자세한 인수 범위는 [진행 기록](../../progress/20261007-step11b3c3c-credential-operation-leases.md)을 따른다.
