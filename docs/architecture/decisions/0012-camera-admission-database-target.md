# ADR 0012 — credential admission DB의 명시적 schema9 대상

상태: 채택 · 2026-10-07 · 11-B3c3a

## 문제와 선택

기존 격리 저장소/DB·키 복원 리허설은 schema8이며 운영은 schema7이다. admission DB marker만 추가한 상태에서 모든 Migrate를 schema9로 바꾸면 이전 리허설과 아직 guard가 없는 runtime이 새 목표를 묵시적으로 선택한다.

기존 embedded migrations1..8과 Migrate/CheckReady의 정확한8 검사는 유지한다. 0009 파일을 별도의 admission_migrations에 embed하고 MigrateCredentialAdmission만 이 집합 전체를 적용한다. 같은 DB migration advisory lock과 한 transaction으로 DDL/history를 직렬화한다. 기존 history 변경·다른 미래 버전은 거부한다. marker 행을 자동 생성하지 않아 schema9 DDL만으로 준비 완료가 되지 않는다. 이 선택은 아직 runtime activation을 허용하지 않는다.

## 표식과 검사

marker는 owner가 관리하고 두 fixed credential role은 읽기만 한다. 외부 기록의 deployment/generation/operation과 새 DB incarnation을 DB marker에 결합한다. dump에 포함되는 표식은 오래된 snapshot을 단독 감지하지 못한다. 표식 설치는 PREPARED와 writer 차단 이후 수행할 유지보수 단계이며 이번에는 구현하지 않는다.

migration hash v1의 exact compact JSON 표현을 [계약](../../contracts/camera-credential-admission.md)에 고정했다. 기대 hash가 embed 코드와 같고 DB history9개도 exact match여야 한다. readiness는 실제 authenticated 두 role 각각의 snapshot 검사이며 전체 작업 구간 lease와 endpoint/key 검사에 결합하기 전까지 storage foundation이다. 모든 실패에 내부 원인을 보존하지 않는 고정 코드를 반환한다.

## 후속 전환

후속 키 loader receipt/profile 비교·CredentialStore shared lease·native maintenance 복원 통합을 끝낸 뒤 schema9 runtime 대상 선택과 운영 preflight/rehearsal/activation을 별도로 진행한다. 기존 schema8 도구를 제거하거나 운영 DB를 이 단계에서 전환하지 않는다. [이번 기록](../../progress/20261007-step11b3c3a-admission-database.md)의 검증 범위를 따른다.
