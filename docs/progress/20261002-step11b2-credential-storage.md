# 단위 11-B2 — 자격증명 버전·암호문 저장소

작성일: 2026-10-02 · 서버 파일/native 검사 인수 완료 · 운영 연결·활성화 전

## 11-B1 서버 결과 인수

사용자 로그에서 11-B1 applied·written=10·pending=0과 백업 `var/patch-backups/step11b1-jiubgb5a`를 확인했다. Python 20개 검사도 OK였다. 키 최초 준비 prepared와 재실행 already_prepared에서 같은 enc-e36370d41ab57a7d·idem-5cf993c8fd7089ed, 각 1개·디렉터리 0700·파일 0600을 확인했다.

keys_activated_in_api·service_restart_performed·database_schema_modified·environment_modified는 false다. 호스트 준비 인수이며 키 내용을 읽거나 API/DB 연결을 확인한 결과는 아니다. 직전 운영 인수의 camera 0.7.0·스키마 7·registry-only-v1·business_runtime_ready=false를 기준으로 유지한다.

## 구현과 변경

이번 범위는 DB 버전/암호문·typed 성공 이력·키별 커밋된 사용량 예약과 부모/폐기 보호다. 실제 비밀 API·설정 CRUD·런타임 키 공급·복원 전환·RTSP는 포함하지 않는다.

신규 파일은 저장소 코드 4개·검사 2개·스키마 8 SQL·native 검사 도구/단위 검사·ADR/운영/진행 문서의 12개다. 기존 267개 중 저장소 삭제/준비/권한 코드 3개·이력 기대값 검사 8개·native HTTP 검사 fixture 1개·프로젝트 명세 1개를 변경한다. 나머지 기존 254개 파일과 SQL 1..7·암호화 모듈·키 준비 도구·실행 OpenAPI·Compose·앱 라우팅/진입점은 보존한다.

CredentialStore는 불변 비밀 버전을 추가하고 정확한 대상의 safe metadata를 확인하며, 필수 권한 callback과 폐기 guard를 요구한다. 원문은 암호화에만 사용하고 HMAC 지문/typed metadata만 성공 이력에 남긴다. old-version/old-key 재생·ID/장치/scope 경계·폐기/부모 tombstone·실패 키 재시도를 구현했다.

예약은 첫 권한/이력/부모/head 확인 뒤 별도 pool에서 커밋한다. 두 번째 저장 트랜잭션에서 다시 확인한 뒤 변경·성공 이력을 원자적으로 기록한다. 실패/경쟁으로 미사용 예약이 소비될 수 있으나 rollback·재시작으로 사용 순번을 재사용하지 않는다. 기존 키 재등록·count 감소·폐기한 키 재활성화를 거부한다.

장치 삭제는 활성 비밀 버전이 있으면 DEVICE_IN_USE로 거부한다. 등록 계정은 private 테이블 접근 없이 boolean predicate만 사용한다. 새 private writer/budget role의 최소 권한 함수는 구현했지만 운영 역할 생성·grant·DSN/키 공급은 실행하지 않는다. app readiness는 새 target schema 8을 요구하므로 이번 소스를 운영 이미지로 재시작하지 않는다.

## 검증과 실제 한계

| 검사 | 결과·범위 |
|---|---|
| 전체 Go race, 격리 PGlite 18.3 | 상위 89개·하위 298개 통과, 실패 0. native 전용 상위 19개 skip |
| 새 저장소 검사 | 상위 9개·rollback 하위 2개 통과. 암호문 복호화·안전한 이력·최대 사용량·새 연결/옛 키·권한 재검사·폐기/부모 보호 |
| 전체 Go vet | 통과. native HTTP fixture의 새 predicate grant도 컴파일 확인 |
| native runner 단위 검사 | 12개 통과. fake subprocess/로그로 skip/누락/실패/소스 변경·중단·정리 실패의 성공 거부와 보호 파일/권한 보존 |
| 패치 도구·전체 적용 | 적용 도구 8개 통과. 기준 267개·변경 25개, 최초 25개/재실행 0개·원본 백업·충돌 시 사전 거부 |
| 정적 전달 검사 | Python 3.10 문법·gofmt·문서 상대 링크·프로젝트 전체 hash·압축본 payload/경로 일치 |

PGlite는 native PostgreSQL 계정 인증·여러 실제 동시 연결을 검증하지 않는다. 모의 runner 검사는 Docker/native 검사의 대체 증거가 아니다. native 계정/function/column 권한·grant 상실·32개 동시 예약·같은 성공 키/버전 경쟁·장치 삭제 양방향 경쟁은 별도 서버 도구가 4개 상위 검사의 실제 pass를 요구한다. 아래 서버 로그로 이 범위를 추가 인수했다.

별도 커밋된 예약의 데이터 rollback/재연결 보존은 검증했지만 운영 DB pg_dump 복구·백업된 키 공급·외부 restore fence는 아직 검증하지 않았다. SQL에 fresh 키 등록/쓰기 중단 기반이 있어도 DB 복원을 자동 감지하는 기능은 아니다. 한 키를 여러 독립 DB에서 쓰는 전역 예산 관리도 운영 설계/입증이 필요하다.

프로세스/라우팅에는 변화가 없으므로 smoke·운영 이미지 전환은 실행하지 않았다. 운영 DB·환경·키·다른 플랫폼을 변경하거나 비밀 원문 resolve·RTSP/세션·GPU 기능을 인수하지 않는다. 기존 실행 API 버전은 유지하되 새 source storage revision/schema와 과거 서버 인수 버전을 구분해 명세에 기록한다. 새 source revision의 native 검증은 아래 로그로 인수했으며 새 HTTP/운영 활성화는 대기다.

## 서버 인수 — 2026-10-02

사용자 로그의 적용 결과는 applied·written=25·pending=0, 백업은 `var/patch-backups/step11b2-zkxyccdj`다. native runner 단위 검사 12개가 OK였다.

native 검사는 scope=camera_credential_storage_native_postgresql, project=vms-credential-storage-test-fecf2fd33ee4, status=passed였다. 검증한 프로젝트 명세 SHA-256은 `1d171e4820db56d569a7e665f83759710f3c7b88cd9f2ed88ea830bd576938b0`다. 임시 DB 스키마는 8, Go race·vet는 true, 상위 108개·하위 310개·필수 자격증명 13개가 통과했고 native_roles_and_concurrency_verified=true였다.

production_services_modified·production_database_modified·production_keys_loaded·credential_api_activated·business_runtime_ready는 false, isolated_resources_removed는 true였다. 보고서는 `var/camera/credential-storage-checks/vms-credential-storage-test-fecf2fd33ee4.json`이며 이는 사용자가 제공한 실행 로그의 인수다. 이 환경에서 운영 보고서나 실제 호스트 키 내용을 읽은 결과는 아니다.

## 다음 인수와 단위

서버 적용과 native 검사 passed를 확인했다. 다음 **11-B3 보호된 키 공급과 백업/복원 fence 준비**도 준비와 리허설로 나눈다. 먼저 [11-B3a 키 파일 로더·호스트 백업](20261002-step11b3a-key-file-backup.md)을 독립 완료한다. 이후 별도 DSN·읽기 전용 mount·운영 restore 전 쓰기 차단·새 키 선택·격리 복구를 11-B3b에서 검증한다. HTTP 비밀 입력·실제 IAM/권한·설정 저장·부모/참조의 같은 트랜잭션 결합·사용/연결은 이후 별도 진행한다. business_runtime_ready=false를 유지하며 적용 명령은 채팅으로만 제공한다.
