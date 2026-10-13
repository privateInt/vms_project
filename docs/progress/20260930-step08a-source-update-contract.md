# 단위 08-A — 영상 소스 표시 이름 수정 계약

작성일: 2026-09-30 · 계약·예제·정적 계약 검사 완료 · 저장소/HTTP 구현 및 운영 활성화 전

## 선행 단계 인수

사용자 서버 로그에서 07 완료 기록 패치 applied, written=1을 확인했다. 백업은 `var/patch-backups/step07-notes-kihwq0rv`, service_restart_performed=false, runtime_activation_required=false다. 단위 07의 장치 수정 구현·검증·운영 전환과 완료 기록 반영까지 인수를 마쳤다.

현재 운영 camera는 `0.4.0-device-update`, DB는 스키마 4다. 운영 이미지와 백업은 [07 완료 기록](20260930-step07-server-acceptance.md)을 따른다. 기존 문서의 완료 기록 적용 대기는 이번 로그로 해소했다.

작업 시작 시 AGENTS.md·작업 원칙·최신 인수 기록을 확인했다. 이번 단위는 소스 수정 계약 하나에 한정한다.

## 확정한 내용

- 첫 소스 수정 범위는 `PATCH /api/v1/sources/{source_id}`의 display_name이다. 부모 device_id·source_id·channel_key는 불변이다. transport·input_mode·motion_mode와 profiles 전체는 이번 수정에서 유지한다.
- 프로필 추가·삭제·재정렬이나 코덱·해상도·FPS 변경은 별도 단위로 남긴다. 이름 수정만으로 부모 장치·형제 소스·프로필·primary_profile_id·실제 연결 상태를 바꾸지 않는다.
- 본문은 schema_version, expected_version, display_name이다. expected_version은 부모 장치가 아닌 소스의 version을 사용한다. 새 수정 성공은 version+1, 동일 성공 재생은 추가 변경 없음이다.
- Idempotency-Key와 최초 성공 스냅샷을 사용한다. 수정과 프로필을 포함한 전체 소스 응답 기록은 같은 트랜잭션으로 저장한다. 버전 충돌과 멱등 키 충돌을 각각 구분한다.
- 응답은 기존 SourceResponse 형식으로 source 전체 정보, 등록 순서의 profiles, registration_state=REGISTERED, runtime_verified=false, request_id를 반환한다. 200 및 Idempotency-Replayed 헤더를 사용한다.
- 기존 POST 성공 기록은 최초 생성 당시 이름·프로필·version을 유지한다. 과거 응답 재생은 현재 소스를 되돌리지 않는다. 목록의 ID 정렬·부모 필터·cursor 경계를 유지한다.
- 정확한 예약 값 validate와 기존 POST 검증 경로를 보존한다. 소스 수정 구현 이후에도 해당 예약 경로의 PATCH는 405/Allow: POST다.

계약 원본·예제·검사는 camera 소유의 `src/platform/camera/api/planned`에 추가했다. 상세 규칙은 [소스 수정 계약](../contracts/camera-source-update.md)에 기록했다.

## 다음 구현에 미치는 영향

현재 스키마 4는 장치에만 제한된 UPDATE 권한을 제공한다. 08-B에서는 새 source_update_requests 테이블·스키마 5와 video_sources의 display_name/version/updated_at 열 UPDATE를 준비해야 한다. 기존 POST 및 장치 PATCH 기록은 유지한다. 이번 패치에는 마이그레이션이나 권한 변경을 포함하지 않는다.

다음 저장소 단위의 완료 기준은 동일 키/다른 키의 동시 수정, 버전·키 충돌과 원자적 롤백, 실제 runtime 최소 권한, 부모·형제 소스·프로필 순서·primary_profile_id·기존 생성 스냅샷·장치 수정 기능 보존이다. HTTP 구현과 서버 이미지 전환은 후속 단계로 분리한다.

## 검증과 한계

- JSON Schema 계약 검사 9개 통과: 요청 예제, 필수/null 필드, 불변·프로필·전송·비밀 필드 거부, version 범위·타입, Unicode 이름 경계, 기존 SourceCreate 이름 규칙 일치, 필드 대소문자·최상위 타입, 예약·잘못된 ID, 기존 SourceResponse를 따르는 전체 응답 예제.
- 검사에는 기존 planned/requirements-test.txt의 jsonschema 의존성을 사용했다. 원문 정수 표기 1.0/1e0·중복 JSON 키, 실제 HTTP 헤더/상태·라우팅·권한·멱등 재생·동시성·DB 원자성은 정적 스키마 검증 범위 밖이며 후속 구현의 검사 항목으로 명시했다.
- 새 파일 5개만 추가하고 기존 실행 OpenAPI·Go·Compose·마이그레이션·프로젝트 명세와 모든 이전 파일의 바이트를 유지했다. 현재 실행 OpenAPI에 소스 PATCH가 없는 상태도 확인했다. 장치 PATCH는 기존대로 유지한다.
- 패치 적용·재적용, payload/압축본 무결성과 기존 코드·환경·활성화 기록 보존을 확인했다. 런타임 코드 변경이 없어 Go/DB 전체 검사·이미지 빌드·서비스 작업을 반복하지 않았다.

이번 계약 패치만으로 운영에서 소스 PATCH를 사용할 수 없다. 서버에 이번 08-A 패치가 적용됐다는 확인은 아직 받기 전이다. 패치 적용 명령은 채팅으로만 전달한다.

## 다음 단위

**08-B: 소스 표시 이름 수정 저장소·스키마 5와 격리 테스트**를 진행한다. 그 결과를 확인한 뒤 HTTP 연결, 격리 이미지 전환·복구 검증, 운영 활성화를 각각 필요한 단위로 나눈다. 삭제·프로필 수정·장치 연결·UI는 이번 단위에서 시작하지 않는다.
