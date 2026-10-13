# ADR 0007 — camera 자격증명 버전 저장과 암호화 사용량

날짜: 2026-10-02 · 상태: 11-B2 저장소 코드 채택, native 서버 검사·운영 연결 전

## 결정과 소유권

[ADR 0006](0006-camera-credential-crypto.md)의 암호화 기반을 camera 전용 PostgreSQL 저장소에 연결한다. 새 스키마 8은 기존 마이그레이션 1..7을 변경하지 않고 추가한다. 새 API·키 mount·서비스 활성화는 이 단위에 포함하지 않는다.

| 관계 | 보관 내용 |
|---|---|
| credentials | 불변 credential_id·scope_id·device_id, 현재 head_version·시각 |
| credential_versions | 불변 정확한 버전·private RTSP protocol/host/port 정책·policy hash·암호문 envelope·최초 폐기 시각 |
| credential_requests | 주체/범위/논리 변경 경로/멱등 키 hash·HMAC 형식/키 ID/지문·안전한 성공 메타데이터 |
| credential_encryption_budgets | 암호화 키의 공개 ID·이미 예약한 사용량·쓰기 허용 상태. 키 원문 없음 |

다른 플랫폼은 이 테이블이나 camera internal 모듈에 직접 접근하지 않는다. 실제 비밀·키 원문은 등록 DTO·DB 원문 요청·성공 이력·공개 메타데이터·로그에 넣지 않는다. 공개 결과에는 장치/자격증명 ID·정확한 버전·생성/폐기 시각만 있다.

## 저장·재생·폐기

WriteVersion은 ExpectedVersion=0으로 최초 버전 1을 만들고, 양수의 정확한 현재 head와 일치할 때 새 불변 버전을 추가한다. 같은 값이라도 새 성공 키로 추가하면 새 버전이다. 과거 버전의 값·대상 정책은 바뀌지 않는다. SQL 제약·보호 trigger는 head 진행/최대 버전 결합·암호문 사용 순번 중복·버전 불변·폐기 취소를 보호한다.

엄격히 검증한 typed DTO를 고정 필드 순서로 직렬화해 HMAC에 넣는다. ScopeID·DeviceID·CredentialID·ExpectedVersion·전체 대상 정책·username/password의 의미를 포함한다. 원문 바이트는 일시적으로만 사용하고 보관하지 않는다. 성공 응답은 JSON blob 대신 typed metadata 열로 기록해 비공개 주소/비밀을 추가할 공간을 만들지 않는다.

인증된 ScopeID·PrincipalID와 별도 자격증명 관리/참조 권한을 검증하는 authorizer가 모든 호출과 성공 재생에 필수다. nil·오류·거부는 허용으로 해석하지 않는다. **현재 구현은 필수 인터페이스와 저장소의 범위 확인이며 실제 IAM/권한 매핑 구현이 아니다.** 검사에서는 합성 권한 callback을 사용한다. HTTP는 이후 실제 인증 경계와 엄격한 비밀 입력 계약을 마련해야 한다.

재생은 옛 HMAC 키를 선택해 같은 최초 메타데이터를 반환한다. 현재 폐기/부모 상태를 되돌리지 않으며 새로운 사용을 승인하지 않는다. 옛 지문 키가 없으면 새 키로 재처리하지 않는다. 성공 이력 실패는 head·버전·폐기를 함께 롤백한다. 실패 키는 이후 조건이 해소되면 재시도할 수 있다.

RevokeVersion은 지정한 불변 버전에 최초 revoked_at을 기록한다. 참조·준비 예약·세션·소비·정리가 해제됐음을 같은 트랜잭션에서 확인하는 신뢰된 guard가 필수다. 기본 unused guard는 없다. 암호문·과거 성공 결과는 보존하며 이 단위는 원문 파기·purge·긴급 중단을 구현하지 않는다.

## 원자적 허용과 사용량 예약

범위/멱등 요청 잠금 → 기존 장치 advisory 잠금 → credential head 잠금 순서를 사용한다. 활성 자격증명 버전은 장치 삭제를 막는다. 등록 계정은 private 테이블 SELECT 없이 고정 boolean 함수를 호출하며 SQL parent trigger도 논리 삭제를 보호한다. 새 버전 삽입은 활성 부모·예약된 키 사용량을 다시 검사한다.

쓰기의 첫 트랜잭션은 권한·이전 성공·부모·head를 확인한다. 성공 재생이면 종료한다. 새로운 쓰기는 별도 budget pool의 단일 SQL 호출로 사용량을 먼저 커밋한다. 이후 저장 트랜잭션에서 권한·성공 이력·부모·head를 모두 다시 검사한 뒤 암호화·버전·성공 이력을 저장한다. 단계 사이의 권한 변경·동시 성공·부모 삭제는 재검사로 처리한다. 쓰기 실패·응답 손실·경쟁으로 실제 암호화가 없더라도 예약이 소비될 수 있으며 순번을 재사용하지 않는다.

두 pool은 같은 명시적 단일 DB endpoint·database를 사용하고 서로 다른 pool을 요구한다. 운영 공급은 writer/budget의 별도 계정을 사용해야 하며 native 검사는 이를 검증한다. 계정 이름만으로 실제 역할 분리를 보장하지는 않는다. 다중 서버 fallback은 거부한다. 같은 암호화 키를 별도 독립 DB/복사본에서 동시에 사용하면 DB별 사용량만으로 전역 상한을 증명할 수 없다. 보호된 키 공급과 운영 절차에서 한 키의 단일 사용량 권위를 유지해야 한다.

키 ID 최초 등록은 schema owner 작업이며 기존 ID를 재등록해 count를 0으로 만들지 않는다. SQL 보호는 count 감소·폐기한 키 재활성화를 거부한다. 저장소 준비 검사는 마이그레이션 이력·권한·현재 키의 남은 예산을 읽고 예약을 소비하지 않는다. 준비 검사 성공은 런타임/키 mount 인수 증거가 아니다.

## 계정과 복원 경계

기존 camera_runtime은 등록 테이블과 활성 비밀 존재 predicate만 접근한다. camera_credential_writer는 private 버전/typed journal과 지정한 head·폐기 열, camera_credential_budget은 고정 예약/준비 함수만 접근한다. 키 생성·등록·쓰기 중단은 별도 schema owner 책임이다. 역할 생성과 운영 DSN/키 공급은 아직 적용하지 않았다.

SECURITY DEFINER 함수는 고정 search_path와 명시적 camera 관계 이름을 사용하고 마이그레이션 트랜잭션 안에서 PUBLIC 실행을 취소한다. budget 계정이 테이블을 직접 읽거나 count를 초기화할 권한을 갖지 않는다. PostgreSQL의 [보호된 함수 작성](https://www.postgresql.org/docs/17/sql-createfunction.html#SQL-CREATEFUNCTION-SECURITY)과 [READ COMMITTED 동작](https://www.postgresql.org/docs/17/transaction-iso.html)을 확인했다.

**DB 복원은 사용량도 과거로 되돌릴 수 있다.** DB만으로 이를 자동 감지하거나 평생 사용량을 증명하지 못한다. 복원 시 쓰기/트래픽을 먼저 fence하고 모든 과거 암호화 키의 쓰기를 중단한 뒤 새 독립 키 ID를 등록하는 절차가 필요하다. 이번 owner-only DisableCredentialEncryption과 옛 키를 재활성화하지 않는 규칙은 그 기반이다. 보호된 운영 키 백업·외부 복원 fence·새 키 공급·pg_dump 복구 리허설은 후속 단위로 검증하기 전까지 실제 비밀 API를 활성화하지 않는다.

## 검증 범위

격리 PGlite에서 암호문 저장·이전 버전/키·HMAC 재생·정확한 대상·권한 재검사·폐기/장치 보호·원자적 실패·커밋된 예산 보존을 검사했다. native 계정 인증·column/function 최소 권한·여러 연결의 예약/변경/삭제 경쟁은 서버 검사 도구로 별도 확인한다. [11-B2 기록](../../progress/20261002-step11b2-credential-storage.md)과 [운영 문서](../../operations/camera-credential-storage.md)를 따른다.
