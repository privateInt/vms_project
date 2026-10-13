# 단위 06-A — 소스 목록 조회·페이지 구분

작성일: 2026-09-30 · 코드·로컬 검증 완료 · 서버 격리 검사 및 06-B 운영 이미지 전환 대기

## 기준과 이번 범위

단위 05의 소스 등록·단건 조회는 스키마 3에서 운영 활성화와 재실행 검증까지 인수했다. 완료 기록 1개가 서버에 적용됐으며 문서 패치 백업은 `/home/shshin/workspace/vms_project/var/patch-backups/step05-notes-hcf9l5vb`다.

작업 기준에 따라 이번 단위는 소스 목록 조회 하나로 제한한다. 기존 계약의 ID 순서·커서 방식·선택적 부모 장치 필터를 구현하고 필요한 테스트·OpenAPI·문서를 함께 전달한다. 수정·삭제·장비 연결·UI·다른 플랫폼 기능은 포함하지 않는다. 06-A에서 파일과 격리 검사를 전달하고 06-B에서 실제 camera 이미지 전환을 별도로 진행한다.

## 구현

- `GET /api/v1/sources`: Bearer 인증, 기본 limit 50·최대 200, 활성 source_id의 ASCII 오름차순.
- 선택적 `device_id` 일치 필터. 없는 장치는 200과 빈 목록을 반환한다.
- 응답: `items`, `next_cursor`, `request_id`. 각 항목은 기존 VideoSource 전체 필드와 등록 순서의 profiles를 포함한다. 빈 items는 배열, 마지막 cursor는 null이다.
- 커서는 소스 목록과 정확한 device_id 필터에 결합한다. 장치 목록 커서, 필터 변경·추가·제거, 비정규 JSON/base64, 중복/알 수 없는 필드 등을 거부한다. limit은 페이지 사이에 변경할 수 있다.
- 잘못된·중복·빈 쿼리, 알 수 없는 파라미터, 범위 밖 limit, 잘못된 ID·cursor는 400 QUERY_INVALID다. DB 미설정·접근 실패는 503이다.
- 한 SQL 스냅샷으로 소스와 프로필을 함께 읽고 `limit+1`로 다음 페이지 유무를 판단한다. 페이지 사이 전체 스냅샷은 보장하지 않는다. 커서 기준 행 삭제 후에도 ID 경계로 이어서 조회한다.

버전은 `0.3.1-source-list`, 단계는 `P1_SOURCE_LISTING`이다. DB 설정 시 `source_list=implemented`, 미설정 시 `disabled`다. 기존 SourceCreate·단건 조회와 `/sources/validate` 동작을 유지한다. 소스 collection의 허용 메서드는 GET/POST다.

DB 스키마는 3을 유지한다. 기존 마이그레이션 0001~0003, 역할·권한, Compose는 변경하지 않는다. 새 목록 SQL은 기존 SELECT 권한을 사용한다. 운영 `.env`는 단위 05 이미지 ID로 고정된 상태를 유지한다.

## 검증

- Go 1.27.1에서 전체 `go test -p 1 -race ./...`, `go vet ./...` 통과. DB 미설정 실행에서 DB 통합 검사는 건너뛰므로 아래와 같이 별도 수행했다.
- PGlite 0.5.8 / PostgreSQL 18.3 WASM 브리지에서 app/storage 패키지를 각각 새 DB로 실행해 통합 검사 통과. 목록 정렬·프로필 원본 일치·필터·빈 목록·마지막 페이지·기준 행 삭제·페이지 사이 삽입·기본 50/최대 200·프로세스 재시작과 토큰 교체 후 cursor 사용을 확인했다.
- WASM 환경은 실제 역할 권한·동시 세션 검증을 대체하지 않는다. 해당 검사는 환경 구분에 따라 건너뛰었다. 새 목록의 stream_profiles SELECT 회수 시 503 및 권한 복구 후 200 검사를 native 서버 실행에 포함했다.
- `make smoke` 43개 통과. 인증·기존 입력 계약·프로세스 종료 범위이며 실제 카메라·영상 입력은 검사하지 않는다.
- OpenAPI component schema와 빈/일반 SourceList 응답을 검증했다. items=null 및 최대 건수 초과 응답의 거부도 확인했다.

이번 로컬 결과는 서버 운영 반영 완료를 뜻하지 않는다. 실제 PostgreSQL 17 서버 검사는 기존 격리 검사 도구로 실행한다. 시험 데이터는 별도 `vms-storage-test-*` 프로젝트에만 생성하고 종료 후 시험 컨테이너·볼륨을 정리한다. 기존 운영 DB·서비스에는 적용하지 않는다.

## 패치와 다음 완료 기준

README·소스 운영 안내·계약·문서 목록·프로젝트 명세를 현재 06-A 상태로 맞췄다. 이전 05 진행 기록과 인수 증거는 보존한다. 명세의 코드 패키지 식별값이 06으로 바뀌므로 04·05 전용 점검·활성화 도구를 다시 실행하지 않는다. 기존 서버 검사 및 전환 보고서는 삭제하거나 갱신하지 않는다.

서버 격리 검사의 `status=passed`, `scope=camera_source_list_and_registry_native_postgresql`, `production_services_modified=false`를 확인하면 다음 06-B에서 새 이미지 빌드·검증과 camera API만의 전환을 준비한다. 스키마 변경이 없으므로 DB 마이그레이션은 필요하지 않다. 실패 시 이번 목록 구현·검사 범위만 수정하고 후속 기능으로 확대하지 않는다.
