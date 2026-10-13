# ADR 0004 — 카메라 PostgreSQL 저장소와 명시적 마이그레이션

날짜: 2026-09-30 · 상태: 채택, 단위 02 PostgreSQL 17.11 서버 격리 검증 완료

이번 작업 단위는 Device·VideoSource·StreamProfile의 영속 저장 기반이다. HTTP 등록/조회, 미디어 입력, 다른 플랫폼의 저장소는 포함하지 않는다.

## 선택

- PostgreSQL과 Go pgx/v5 v5.11.0을 사용한다. 기존 계획의 PostgreSQL 후보를 채택하며 외래 키·유일성·트랜잭션으로 등록 데이터의 관계를 보장한다. 임베디드 파일 저장소나 SQLite를 별도 운영 데이터 원본으로 추가하지 않는다.
- camera 소유 DB와 계정을 전제로 `camera` 스키마를 사용한다. 다른 플랫폼은 해당 DB/스키마에 직접 접근하지 않는다. 현재 전달하는 Docker 구성은 검사 전용이고 운영 DB·계정 배포는 아니다.
- 마이그레이션과 Go 저장 코드는 `src/platform/camera/internal/storage`, 실행 진입점은 `camera/cmd/camera-migrate`가 소유한다. SQL은 실행 파일에 포함한다.
- API 시작 시 DDL을 자동 실행하지 않는다. 명시적인 DB URL과 적용 옵션을 요구하는 일회성 명령으로 처리한다. 단위 02 당시 camera-api는 저장소를 호출하지 않았다. 단위 03부터 명시적으로 구성한 DB를 사용하며 자동 DDL 금지는 유지한다.
- 마이그레이션 파일을 번호 순으로 실행하고 이름·SHA-256·버전을 DB에 기록한다. 적용된 파일은 수정하지 않고 다음 번호의 파일을 추가한다.
- 트랜잭션 범위 advisory lock으로 마이그레이션 실행을 직렬화한다. 이번 pending migration 묶음과 이력 갱신은 한 트랜잭션이다. 오류 시 부분 테이블·이력을 남기지 않는다.
- 이력 누락·변조·현재 코드보다 높은 버전이나 기존 테이블 충돌은 중단한다. 자동 덮어쓰기나 강제 down migration은 제공하지 않는다.

## 스키마의 구체화

`devices`는 장치, `video_sources`는 장치의 채널, `stream_profiles`는 소스의 프로필이다. ID·부모 관계·채널·프로필/순서 유일성·필수 값·범위·전송 조합을 SQL로 검사한다. ID는 C 정렬 규칙을 사용한다. 프로필의 position은 1~8로 제한한다.

`video_sources.primary_profile_id`는 최초 생성 요청의 첫 프로필을 가리키는 내부 저장 필드다. `(source_id, primary_profile_id)`에서 프로필로 향하는 지연 외래 키를 사용해 트랜잭션 완료 시 하나 이상의 프로필을 보장한다. 생성 트랜잭션에서는 소스 다음에 프로필을 넣을 수 있다. 이 필드를 새 사용자 요청 필드로 추가하지 않는다. 분석 작업은 기존처럼 명시적인 stream_profile_id를 선택한다.

삭제 이력용 deleted_at과 낙관적 수정용 version을 준비한다. 실제 API의 삭제 정책·불변 필드 검사·버전 증가·멱등 응답 저장은 후속 CRUD 단위에서 구현한다. SQL 소유 계정이 직접 실행하는 임의 DML까지 해당 업무 정책이 강제된다고 주장하지 않는다.

## 접속·권한·검증의 경계

DB URL에는 사용자·접속 위치·DB 이름을 명시한다. SQL을 실행하기 전 연결을 확인하고 접속·문장·잠금·유휴 트랜잭션에 제한 시간을 둔다. 라이브러리 오류 출력은 고정 코드와 SQLSTATE로 제한한다. 원본 드라이버 오류를 직접 로그로 출력하지 않는다.

운영 적용 시 migration 계정은 대상 스키마의 DDL 권한을 갖고, 후속 API 계정은 필요한 DML 권한만 가져야 한다. 기본 스키마는 PUBLIC에 접근 권한을 부여하지 않는다. 실제 DB/역할 생성·비밀 설정·서비스 연결은 후속 운영 활성화 때 확인한다. 검사 Compose의 임시 관리자 계정을 운영 계정으로 사용하지 않는다.

이 환경에서는 일반 PostgreSQL 서버 설치와 Docker 실행이 가능하지 않았다. 따라서 PGlite의 PostgreSQL 18.3 엔진에서 SQL과 pgx 트랜잭션·마이그레이션을 검증했다. 이것은 mock 응답 검사가 아니지만 일반 PostgreSQL의 다중 backend·인증·네트워크·컨테이너 검증을 대신하지 않는다. 검사 시 pgx의 준비된 문장 캐시를 사용하지 않는 연결 옵션을 적용했다. 운영 기본값은 바꾸지 않았다.

대상 서버의 PostgreSQL 17.11 격리 Compose 검사에서 기본 pgx 동작과 동시 마이그레이션이 통과했다. 단위 02 서버 인수를 마무리했으며 사용자 로그 근거는 해당 진행 기록에 추가했다. 단위 03의 새로운 API·권한·동시 생성 검증과 운영 활성화는 별도로 확인한다.

## 근거

- PostgreSQL 공식 문서: https://www.postgresql.org/docs/17/ddl-constraints.html
- PostgreSQL 공식 잠금 문서: https://www.postgresql.org/docs/17/explicit-locking.html
- pgx 공식 저장소: https://github.com/jackc/pgx
- PGlite 및 연결 제약: https://pglite.dev/docs/pglite-socket

소유권·스키마·적용 방식은 이 프로젝트의 결정이다. 검증 상세와 남은 작업은 최신 진행 기록에 둔다.
