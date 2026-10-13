# 단위 07-C — 장치 표시 이름 수정 HTTP API

작성일: 2026-09-30 · 코드·로컬 검증 완료 · 서버 PostgreSQL HTTP 격리 검사 대기

## 선행 결과와 이번 범위

07-B 패치 19개가 적용됐으며 백업은 `var/patch-backups/step07b-6sjvbgqa`다. 사용자의 `vms-storage-test-8edfe17ca435` 로그에서 PostgreSQL 17.11의 수정 저장소·실제 권한·동시성·기존 기능 검사가 통과했고 전용 DB 컨테이너와 네트워크가 제거됐다. 최종 scope는 `camera_device_update_storage_native_postgresql`, production_services_modified는 false다. 상세는 [07-B 기록](20260930-step07b-device-update-storage.md)에 추가했다.

이번 작은 작업 단위는 장치 수정 HTTP 연결·명세·필수 검증이다. API 코드 버전은 `0.4.0-device-update`, 단계는 `P1_DEVICE_UPDATE`, capability는 device_update=implemented/disabled다. 운영 camera는 계속 단위 06의 `0.3.1-source-list`와 스키마 3이며 이 패치가 운영 서비스나 DB를 변경하지 않는다.

## 변경

- PATCH /api/v1/devices/{device_id}를 07-B UpdateDevice에 연결했다. 수정할 수 있는 필드는 display_name 하나다. 성공 200, 새 request_id, Idempotency-Replayed를 반환하며 Location은 없다.
- DeviceUpdate JSON 디코더는 정확한 필드명·타입·중복 키·유효한 UTF-8을 검사한다. expected_version을 부동소수점으로 바꾸지 않고 int64 정수 토큰으로 읽는다. 소수/지수/문자열/null/범위 초과는 400, 누락·0·음수·잘못된 이름 등 의미 오류는 422다.
- 인증 → 메서드 → 쿼리 → 경로 ID → 조건 헤더 → 멱등 키 → Content-Type/JSON → 필드 의미 → 저장소 순서를 유지한다. If-Match·If-None-Match·If-Unmodified-Since는 빈 값으로 제출해도 400이다. 본문은 64 KiB까지다.
- 단건 경로의 Allow는 GET, PATCH다. 저장소의 장치 없음·버전 충돌·멱등 충돌·버전 소진을 각각 404/409로 매핑한다. DB/트랜잭션 오류는 내부 정보를 노출하지 않는 503이며 동일 키·본문으로 재시도한다.
- 실행 OpenAPI에 DeviceUpdate·PATCH·응답 헤더/상태를 추가하고 버전·단계·smoke 검사를 맞췄다. 07-A planned 파일은 설계 이력으로 보존하고 실행 예제를 별도로 추가했다.

07-B 저장소·마이그레이션 0001~0004·권한 부여 SQL은 변경하지 않았다. 소스 수정/삭제, 장치 삭제, 실제 장비 연결, 운영 IAM과 이미지 전환은 이번 범위에 없다.

## 검증

- Go 1.27.1 전체 go test -p 1 -race 및 go vet 통과. DB 환경이 없는 실행의 통합 검사 skip은 다음 별도 DB 검사와 구분한다.
- JSON 원문 검사: 2^53을 넘는 정수와 int64 최댓값의 정확한 파싱, 소수·지수·문자열·null·범위 초과 거부, 중복/이스케이프된 중복 키·미지원 필드·잘못된 타입/UTF-8 거부, 누락/의미 오류 구분.
- HTTP 경계 검사: 검사 순서, 인증, Allow, 조건 헤더, 단일 멱등 키, JSON/매체 오류, 정확히 64 KiB 허용과 초과 413, 실패 시 성공 전용 헤더 없음, request_id 일치, 요청 값/토큰/키의 로그 비노출.
- PGlite PostgreSQL WASM의 별도 DB에서 app 패키지 전체 통합 검사 통과. 실제 API 프로세스로 수정·GET/목록·정규 JSON/경로 재생·충돌·동일 이름 수정, 자식 소스/프로필과 POST 스냅샷 보존, 프로세스 재시작/토큰 교체 이후 과거 응답 재생, 주입한 성공 기록 저장 실패의 503·전체 롤백·동일 키 재시도, tombstone과 버전 소진을 확인했다.
- 실제 권한 인증 검사는 PGlite에서 skip한다. 서버용 검사에 runtime INSERT/열 UPDATE 권한 회수 시 PATCH 503·readiness 503·변경 롤백·권한 복구 후 동일 키 재시도를 추가했다. 07-C의 이 native HTTP 결과는 아직 받지 않았다. 07-B에서 통과한 native 저장소 결과와 구분한다.
- make smoke: 네 플랫폼을 임시 로컬 프로세스로 실행해 47개 검사 통과. 새 PATCH 경계 4개와 기존 인증·계약·정상 종료를 포함하며 운영 프로세스에는 접속하지 않았다.
- OpenAPI JSON Schema·내부 참조·07-A 요청 제약 일치·예제·응답 코드/헤더와 Python 도구 구문을 확인했다.
- 파일 패치 적용·재적용과 기존 .env/운영 활성화 기록 보존, 명세 해시·문서 링크·기존 SQL 불변을 확인했다.

## 전달과 다음 단위

서버에서는 파일 적용 후 기존 격리 실행 도구로 새 코드를 고유한 `vms-storage-test-*` 프로젝트에서 검사한다. 이번 성공 범위는 `camera_device_update_http_native_postgresql`이며 status=passed, production_services_modified=false를 확인한다. 기존 저장소/장치/소스 회귀도 같은 전용 DB에서 패키지 순서대로 실행한다. 실패하면 이번 HTTP 연결 범위에서 원인을 해결한다.

서버 통과 후 다음 작은 단위는 **07-D1: 운영 전환 읽기 전용 사전점검**이다. 실제 스키마 4 마이그레이션·이미지 전환과 실패 복구는 추가 격리 검증 이후 별도 단계로 진행한다. 새 스키마에 기존 06 이미지만 복귀시키는 방법이나 자동 운영 DB 복원은 사용하지 않는다. 파일 적용 및 서버 검사 명령은 채팅에서만 제공한다.
