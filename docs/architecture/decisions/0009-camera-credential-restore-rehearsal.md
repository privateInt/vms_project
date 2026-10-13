# ADR 0009 — 합성 키 공급과 DB/키 복원 격리 리허설

날짜: 2026-10-02 · 상태: 리허설 native 서버 격리 인수 완료

## 결정과 경계

[ADR 0008](0008-camera-protected-key-files.md)의 키 로더/호스트 백업은 서버 인수를 마쳤다. 다음 선행 조건을 입증하기 위해 임시 Docker 프로젝트의 합성 키와 두 임시 DB를 대상으로 리허설을 제공한다. 운영 키 파일·DB·환경·앱/HTTP·Compose를 연결하지 않는다. 기존 SQL 1..8과 저장소 실행 코드도 변경하지 않는다.

리허설의 root 준비 컨테이너만 합성 private 키 볼륨의 소유권을 UID/GID 10001로 준비한다. 검사 프로세스는 해당 UID로 실행하고 키/키 백업 볼륨을 read-only로 mount한다. 부모 0500·파일 0400, 로더의 strict 검사를 적용한다. Statfs MS_RDONLY와 소유자 chmod의 EROFS를 함께 확인해 권한만 제한한 writable 볼륨과 구분한다. 각 단계는 별도 컨테이너/Go 프로세스로 실행한다.

저장소는 writer/budget 고정 역할의 서로 다른 DSN·pool을 사용한다. actual current_user/current_database를 확인한다. superuser는 리허설 fixture와 복원 유지보수에서만 사용하며 운영 애플리케이션의 역할은 아니다. 테스트 authorizer는 합성 fixture 전용이며 IAM 구현을 뜻하지 않는다.

## 복원 절차가 입증할 것

초기 버전/암호문/HMAC 영수증을 기록하고 custom pg_dump와 정확한 키 바이트의 별도 복사본을 만든다. 그 뒤 같은 키로 버전 2와 폐기된 예약을 만들어 사용량을 1에서 3으로 올린다. 복원본의 값 1과 별도 리허설 기록의 값 3을 비교해 rewind를 재현한다. 별도 기록은 테스트 증거이며 운영 high-water ledger가 아니다.

복원 전에 두 계정 NOLOGIN과 기존 세션 종료를 적용하고 원래 DB의 PUBLIC/두 계정 CONNECT를 제거한다. 단일 transaction pg_restore로 별도 DB에 복원한 뒤 모든 옛 키 budget을 disabled로 만든다. 키도 백업에서 복원한다. 이후 NOLOGIN·세션 없음·옛 키 disabled·옛 암호문과 HMAC 영수증의 정확한 row hash·키 바이트 일치·복호화·재실행을 확인한다.

새 독립 encryption/idempotency 키를 생성하고 옛 키들을 읽기 이력으로 유지한다. 새 키 등록 전과 등록 후 각각 별도 프로세스로 두 번 검사해 중단/재시도를 재현한다. 이미 등록된 키는 재등록/사용량 초기화를 거부해야 한다. 파일 로드·옛 복호화/HMAC 재실행 성공을 확인한 뒤에만 LOGIN을 재개한다. 예전 DB 연결과 옛 키의 새 쓰기는 계속 거부한다. 새 DB의 새 버전은 새 암호화 키 사용량 1이어야 하고, 기존/신규 요청 재실행과 프로세스 재생성은 quota를 추가 소비하지 않아야 한다. 누락 파일/누락 역사 키도 거부한다.

## 운영 fence와의 차이

NOLOGIN은 기존 세션을 제거하지 않으므로 종료와 실제 세션 수 검사를 함께 수행한다. 이 리허설은 pg_dump의 단일 DB 스냅샷에 포함되지 않는 해당 임시 클러스터 role 상태를 사용한다. 클러스터 전체 복원·role 복원·운영 관리자의 우회·트래픽/프로세스 재개를 보호하는 외부 admission은 구현하지 않았다. 이 절차를 운영 restore tool로 재사용하거나 credential_restore_fencing_implemented=true로 표시하지 않는다.

production 키 공급/실행 UID·DB identity/역할·백업 일관성·외부 fence·실제 API startup admission은 다음 별도 단위다. 리허설 passed만으로 운영 키 공급·DB 스키마 8·비밀 HTTP/API·복구 완료를 활성화하지 않는다.

공식 동작 근거: [PostgreSQL 17 pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html), [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html), [Docker Compose services](https://docs.docker.com/reference/compose-file/services/). 실제 검사 결과와 한계는 [진행 기록](../../progress/20261002-step11b3b-key-supply-restore-rehearsal.md)에 구분한다.

## 서버 인수 완료

수정 후 source hash b00516b1d169377f1c0dd98eadcf2b161d7d173246aafd21265c5a183390afb3의 native 검사에서 8 phase·Go race/vet·키/DB 복원·재시도·프로세스 재생성과 정리가 모두 passed였다. 운영 기능/production restore fence는 미활성·미구현이다. 상세 범위는 11-B3b 진행 기록의 서버 인수를 따른다. 다음 외부 admission 계약/구현은 별도 인수한다.
