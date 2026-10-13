# ADR 0013 — 실제 키·DB endpoint 영수증과 승인 값 비교

상태: 채택 · 2026-10-07 · 11-B3c3b

## 선택

DB marker가 승인 값과 같아도 다른 pool·TLS 설정·키 ring을 사용하는 프로세스를 허용해서는 안 된다. protected loader가 얻은 exact bundle SHA-256와 실제 RO mount 관찰을 immutable Keyring에 보관한다. 일반 parser와 caller가 주장한 hash는 이 영수증을 만들지 못한다. receipt는 로드된 ring의 근거이며 file path의 현재 상태를 보장하지 않는다.

첫 endpoint는 canonical IP 하나를 고정한다. DNS·자동 failover·UDS·다중 CA·client certificate는 범위 밖이다. 승인 객체가 직접 CA PEM bytes를 파싱·hash하고 private CertPool을 만든다. URI에는 role/password/주소/포트/DB 및 명시적 sslmode만 허용하며 ambient PG 설정을 거부한다. default CA/file/service를 읽지 않는 controlled config에 승인 TLS만 붙여 peer·verified chain·server name·CA를 실제 확인한다. TLS downgrade fallback은 없다. disable은 별도 승인 profile의 명시적 선택이고 verify-full의 대체 경로가 아니다.

## 결과와 경계

legacy Open 및 schema8 저장소는 유지하며 새 opener만 private endpoint 영수증을 보유한다. CheckCredentialAdmissionBindings는 승인 PREPARED/OPEN과 실제 key/pool/DB를 읽기만 비교한다. transport와 role/marker/history는 같은 acquired connection/snapshot에서 확인한다. budget ready도 실제 budget role에서 읽으며 use를 소비하지 않는다. 실패 원문을 wrapping하거나 key/address/DSN을 출력하지 않는다.

runtime의 승인 기록은 실제 external authority에서 와야 한다. 이번 함수는 lease를 획득/보유하거나 전체 업무 권한을 부여하지 않으므로 ready flag 또는 API guard로 단독 사용하지 않는다. 키 재라벨링/과거 material과의 독립성·복원 이후 fresh budget 생성은 유지보수 통합에서 검사한다. [계약](../../contracts/camera-credential-admission.md)과 [진행 기록](../../progress/20261007-step11b3c3b-key-endpoint-bindings.md)을 따른다.
