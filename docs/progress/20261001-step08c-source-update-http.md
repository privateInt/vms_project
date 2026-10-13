# 단위 08-C — 소스 표시 이름 수정 HTTP API

작성일: 2026-10-01 · HTTP 구현·로컬 검증 완료 · 서버 격리 검사 및 운영 전환 전

## 선행 단계 인수와 이번 범위

08-B 사용자 로그에서 파일 패치 applied/written=24, 백업 `var/patch-backups/step08b-inoz1s8s`와 PostgreSQL 17.11 검사 통과를 확인했다. 프로젝트는 `vms-storage-test-7b812c2ab795`, scope=camera_source_update_storage_native_postgresql, production_services_modified=false다. 실제 runtime 권한·동시성·롤백과 기존 API 회귀가 통과했고 임시 컨테이너·네트워크도 정리됐다. 상세 인수는 [08-B 기록](20260930-step08b-source-update-storage.md)에 추가했다.

작업 시작 시 AGENTS.md·작업 원칙·최신 기록과 계약을 읽었다. 이번 단위는 소스 이름 수정 HTTP 연결과 검증 패키지다. 운영 사전점검·이미지 업그레이드 리허설·활성화는 후속 단위로 남긴다.

## 변경

- `PATCH /api/v1/sources/{source_id}`를 기존 UpdateSource 저장소에 연결했다. 장치가 아닌 소스의 expected_version으로 display_name을 수정한다. 성공은 전체 SourceResponse·200·Idempotency-Replayed 헤더이며 Location은 없다.
- SourceUpdate의 정확한 필드명·중복 키·null/타입·UTF-8·signed int64 정수 토큰 검증을 추가했다. 1.0/1e0·문자열·범위 초과 버전은 400, 누락/0/음수·이름 의미 오류는 422다. 본문 제한 64 KiB·인증·조건 헤더·쿼리·멱등 키 오류 순서를 유지한다.
- SOURCE_VERSION_CONFLICT와 SOURCE_VERSION_EXHAUSTED를 409로 연결했다. 미존재/삭제는 404, 저장소 실패는 503이며 성공 기록이 없는 실패는 같은 키로 재시도할 수 있다.
- 일반 소스 경로는 GET/PATCH, 예약 validate 경로는 기존 POST를 유지한다. 동등한 URL 이스케이프도 예약 경로로 처리한다. source_update 기능 표기와 camera 코드 버전 `0.5.0-source-update`, 단계 P1_SOURCE_UPDATE를 추가했다.
- 실행 OpenAPI에 SourceUpdate·PATCH 요청/응답을 추가하고 예제를 제공했다. 기존 장치 수정·소스 등록/조회/목록 계약과 예정 계약 파일을 보존했다. 소스 version의 int64 상한을 명세에 명시했다.
- 기존 서버 격리 검사 도구의 scope를 camera_source_update_http_native_postgresql로 변경했다. 새 HTTP 검사와 기존 회귀를 함께 실행한다.

08-B 저장소 트랜잭션·runtime 권한·readiness·마이그레이션 0001~0005는 변경하지 않았다. 부모·형제·프로필·primary_profile_id 보존은 기존 저장소 계약을 따른다. 현재 운영 API/DB는 계속 0.4.0-device-update/스키마 4이며 새 코드가 요구하는 스키마 5와 구분한다.

## 검증

- Go 1.27.1의 전체 패키지 race 검사와 go vet 통과. DB 설정이 없는 실행에서 건너뛴 통합 검사는 DB 검증 결과로 계산하지 않았다.
- SourceUpdate 엄격한 JSON·의미 검사, HTTP 오류 순서·성공 헤더 미노출·본문 크기 경계·예약 경로/이스케이프·로그 비밀 미노출 검사 통과.
- PGlite 18.3 임시 DB와 실제 API 프로세스에서 기존 API 및 새 소스 PATCH 통합 검사 통과. 전체 프로필 응답, 부모/형제 보존, 부모 버전 독립성, POST·장치 PATCH·소스별 키 범위, 정규 경로/본문 재생, 최신 상태와 과거 응답 구분, 목록/cursor/부모 필터를 확인했다.
- 같은 임시 DB 검사에서 실제 API 재시작·토큰 교체 후 재생, 동일 이름의 version 증가, 버전/키 충돌·최댓값·tombstone, 성공 기록 강제 실패의 503·원자적 롤백·같은 키 재시도를 확인했다.
- 새 HTTP의 실제 PostgreSQL 계정 권한 상실 검사는 PGlite에서 실행하지 않았다. 서버 검사에는 source_update_requests SELECT/INSERT와 video_sources의 각 수정 열 권한을 제거한 뒤 readiness/HTTP 503·현재 소스 보존·권한 복구 후 같은 키 성공을 확인하는 검사를 포함했다. 08-B의 저장소 권한 검증 완료와 이 새 HTTP 검사 대기를 구분한다.
- 네 API의 임시 프로세스를 사용하는 make smoke 52개 통과. 신규 PATCH 경계·예약 경로를 포함하며 실제 장비·운영 서비스에 접속하지 않았다.
- 기존 소스 수정 정적 계약 검사 9개, 실행 OpenAPI 스키마·참조 및 요청/응답 예제 검증 통과.
- 패치 적용·재적용·충돌 시 사전 중단·백업·압축본/manifest 무결성과 기존 `.env`·운영 활성화 기록 보존을 확인했다.

Docker 엔진이 없는 제작 환경에서는 새 native HTTP 검사를 완료로 표시하지 않는다. 실장비 입력·미디어 수신·업무 런타임 검증은 이번 범위가 아니다.

## 서버 인수와 다음 단위

서버에서 격리 도구 결과 status=passed, scope=camera_source_update_http_native_postgresql, production_services_modified=false를 확인한다. 임시 PostgreSQL 17.11과 Go 1.27.1 컨테이너는 독립 프로젝트를 사용하고 검사 후 정리한다. 패치 파일 적용은 서비스 재시작·운영 마이그레이션·환경 변경을 하지 않는다. 사용자 적용 명령은 채팅으로만 전달한다.

검사 통과 후 **08-D1: 소스 수정 운영 전환 사전점검**을 진행한다. 운영 상태를 읽어 기존 0.4 이미지·스키마 4·데이터 규모와 백업 여유를 확인하는 단위로 한정한다. 스키마 4→5 업그레이드/복구 리허설과 실제 활성화는 그 결과를 보고 나눈다. 이전 버전 전용 활성화 도구를 재사용하거나 운영 DB를 자동 복원하지 않는다.
