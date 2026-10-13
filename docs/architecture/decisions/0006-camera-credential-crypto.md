# ADR 0006 — camera 자격증명 암호화와 분리 키

날짜: 2026-10-02 · 상태: 11-B1 독립 기반 구현, 저장소·API·운영 연결 전

## 배경과 범위

[접속 설정 계약](../../contracts/camera-connection-config.md)은 장치에 속한 비밀의 정확한 불변 버전과 승인된 접속 대상 정책을 요구한다. 비밀은 나중에 장비 인증에 사용해야 하므로 복원 가능한 암호화가 필요하다. 일반 등록 DTO·공개 응답·원문 멱등 요청 기록에 username/password를 넣지 않는다.

이번 결정은 camera 내부 암호화 모듈과 호스트 키 최초 준비에 한정한다. 모델·분석·운영 플랫폼에 비밀이나 DB 접근을 공유하지 않는다. DB 저장·사용량 기록·대상 권한·HTTP·실제 연결은 아직 구현하지 않았다.

## 암호문 형식과 호출 경계

Go 1.25 표준 `crypto/aes`와 `cipher.NewGCMWithRandomNonce`로 AES-256-GCM을 사용한다. 모듈이 random nonce를 생성하고 ciphertext 앞에 붙인다. 호출자가 nonce를 지정하지 않는다. envelope는 format_version·algorithm·key_id·encryption_use·ciphertext만 가진다.

추가 인증 데이터는 목적 식별자와 envelope 형식·키 ID·사용 순번, ScopeID·DeviceID·CredentialID·CredentialVersion·TargetPolicySHA256이다. 다른 장치/버전/대상 정책의 암호문으로 교환하거나 순번·ciphertext를 변조하면 복호화에 실패한다. 대상 정책의 canonical 직렬화·DB 저장·승인 검사는 후속 저장소 책임이며 임의 HTTP 입력의 hash를 신뢰하면 안 된다. AAD 결합 자체가 권한 검사는 아니다.

Secret은 username UTF-8 1..128바이트, password UTF-8 1..4096바이트다. 제어 문자·DEL을 거부하며 공백 password를 보존한다. 원문 getter는 미래 내부 장비 adapter용이다. Secret과 Keyring의 일반 Go 포맷은 redacted, JSON 직렬화는 실패한다. 평문 버퍼는 사용 후 지우지만 Go 문자열/힙의 모든 복사본 제거를 보장하지 않는다. HTTP/로그에서 비밀을 안전하게 처리하는 책임은 후속 통합에도 남는다.

Go 문서의 키당 메시지 제한에 따라 예약 범위를 1..2^32-1로 둔다. Seal은 현재 암호화 키 ID·유효 범위만 확인한다. **전역 사용량 제한을 구현한 것은 아니다.** 저장소는 Seal 전에 여러 프로세스가 공유하는 키별 원자적·영속적 사용량을 예약하고 실패한 암호화 시도도 소비해야 한다. 트랜잭션 취소·프로세스 재시작·DB 복원으로 사용량을 되돌릴 수 없다. 복원 후에도 고수위를 증명하거나 새 암호화 키를 선택하는 절차가 API 활성화의 선행 조건이다. 이 기록과 절차가 없는 현재 모듈은 API에서 사용하지 않는다.

## 멱등 지문

독립적인 256비트 키로 HMAC-SHA256을 계산한다. 목적 문자열, PrincipalID·변경 Method·고정 API Path·멱등 키 SHA256, 명시적 길이를 가진 canonical 요청 바이트를 결합한다. 응답/DB에는 format·algorithm·key_id·digest만 저장하도록 설계한다. 비교는 기록된 정확한 키 버전과 constant-time 비교를 사용한다.

모듈은 원문 JSON을 canonicalize하지 않는다. 호출자가 엄격한 DTO 검증 뒤 안정적인 전체 의미를 직렬화해야 한다. 인증 주체를 실제 권한 경계에서 정하고 성공 응답을 비밀 없는 메타데이터로 저장하는 구현도 후속 책임이다. 지문 키가 없어졌다고 현재 키로 옛 요청을 다시 처리하지 않는다.

## 키 공급과 이력

호스트의 `var/camera/credential-keys/key-bundle.json`에 purpose별 active ID와 key history를 둔다. 암호화 ID는 enc-, 멱등 ID는 idem- 접두어와 16자리 소문자 hex다. 각 값은 서로 다른 32바이트, canonical base64이며 목적별 1..16개를 허용한다. DB 비밀번호·Bearer·비밀 원문에서 키를 파생하거나 재사용하지 않는다. 키 준비 도구는 최초 생성만 지원한다.

키 파일은 소유자 전용 0600, 전용 디렉터리는 0700이다. 이는 DB 덤프만 유출된 경우와 키 파일 접근을 분리하는 로컬 파일 기반의 제한된 보호다. 파일 키는 평문이며 동일 계정·root·전체 호스트 침해를 막는 KMS/HSM이 아니다. KEK를 같은 위치에 추가해 강한 분리인 것처럼 표시하지 않는다. 관리형 키 공급은 후속 선택지다.

ParseKeyBundle은 보호된 바이트만 파싱한다. 런타임의 파일 소유권·권한·읽기 전용 mount 확인은 별도 loader에서 구현해야 한다. 현재 Compose/환경/API 시작 경로에는 키 파일 연결이 없다.

정확한 이전 키를 유지한 채 새 active 키로 새 암호화/지문을 생성하고 이전 결과를 검증할 수 있다. 이전 암호화 키는 기존 행의 rewrap과 관련 백업 수명 종료 전까지, 이전 HMAC 키는 옛 성공 journal 재생이 필요한 기간까지 보존해야 한다. 운영 키 교체·rewrap·폐기·보호된 백업 절차는 이번에 구현하지 않았다.

## 검증과 근거

독립 암호화·HMAC·엄격한 키 파싱·변조/자원 교환·이전 키 부재·최대 비밀·동시 호출 검사와 격리된 키 복원을 통과했다. [키 운영 문서](../../operations/camera-credential-keys.md)와 [11-B1 진행 기록](../../progress/20261002-step11b1-credential-crypto-keys.md)에 구체적인 범위와 증거를 기록한다.

설계 근거는 [Go 1.25 cipher 문서](https://pkg.go.dev/crypto/cipher@go1.25.0#NewGCMWithRandomNonce), [OWASP 암호화 저장 지침](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html), [OWASP 키 관리 지침](https://cheatsheetseries.owasp.org/cheatsheets/Key_Management_Cheat_Sheet.html)을 확인했다. 인증 암호화와 검증된 난수 사용, 키/데이터 분리 및 백업을 고려하되 이 단위의 로컬 보호 한계를 명시한다.
