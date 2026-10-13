# 단위 10-B — 장치 논리 삭제 저장소와 스키마 7

작성일: 2026-10-01 · 코드·로컬 검사 완료 · 대상 서버 격리 인수 전 · HTTP/운영 전환 전

## 선행 상태와 이번 범위

첨부 프로젝트에서 10-A 패치 적용 기록 applied/written=5와 백업 var/patch-backups/step10a-_xtsn2r_를 확인했다. 기록에는 service_actions_performed=false·runtime_activation_required=false가 있다. 10-A의 계약 문서·스키마·예제·검사 다섯 파일도 확인했다. 당시 진행 문서의 서버 적용 대기는 이 파일 근거로 해소한다. 실시간 서버를 직접 조회한 것은 아니다.

09 운영 인수 및 source-delete-activation.json의 activated/completed·스키마 6·source_delete_activated=true를 기준으로 현재 운영을 0.6.0-source-delete·스키마 6으로 판단했다. 네 플랫폼 중 camera의 등록 관리와 소스 삭제가 운영 반영됐으며 model/operation은 실행 기반, analysis는 실행 기반과 입력 형식 검증이다. 실제 영상 업무 런타임은 미구현이다.

AGENTS.md·작업 기준에 따라 이번 단위는 장치 삭제 저장소·스키마 7·격리 검사와 해당 문서/패키지 전달까지다. HTTP 라우트·실행 OpenAPI·capability·운영 Compose·환경·기존 마이그레이션 0001~0006은 유지한다.

## 구현

- DeviceDelete 내부 명령·의미 검증, 최소 DeviceDeletion 결과와 DeleteDevice 저장소를 추가했다. 명령은 HTTP에 노출하지 않는다. 기본 JSON 디코더를 새 DELETE API에 사용하는 것도 허용하지 않으며 엄격한 원문/중복 키/헤더 검사는 10-C에서 연결한다.
- 인증 주체·DELETE·정규 경로·키의 성공 이력을 먼저 재생한다. 새 요청은 CreateSource와 동일한 장치별 advisory transaction lock(1447908164, hashtext(device_id))을 획득하고, 활성 부모 행 FOR UPDATE 이후 version·소진·미삭제 자식·사용 관계 순서로 검사한다.
- WithTx의 격리 수준을 READ COMMITTED로 명시했다. 연결/DB 기본 격리 수준이 더 강해도 잠금 뒤의 별도 부모/자식 조회가 앞선 소스 생성 커밋을 볼 수 있도록 한다. 장치 PATCH는 동일한 부모 행 잠금으로 직렬화한다.
- 미삭제 자식이 하나라도 있으면 DEVICE_HAS_ACTIVE_SOURCES다. 모든 자식이 삭제됐거나 자식이 없을 때만 DeviceDeleteGuard를 호출한다. nil·unknown·잘못된 상태·오류는 DEVICE_USAGE_UNAVAILABLE, 사용 중은 DEVICE_IN_USE다. 운영용 기본 미사용 guard·force/cascade·실제 사용 관계를 추가하지 않는다.
- tombstone·version+1·동일한 deleted_at/updated_at·최초 삭제 결과를 같은 트랜잭션으로 저장한다. 시각 역행·정수 오버플로를 막는다. 성공 이력 실패 시 부모 변경도 롤백한다. 과거 성공 재생은 부모/자식을 복원하지 않는다.
- 신규 0007_device_delete.sql과 독립 device_delete_requests를 추가했다. 기존 0001~0006 바이트·체크섬과 FK·장치/소스/프로필/이력을 유지한다. 장치 ID validate를 예약하지 않는다.
- runtime 권한에 devices.deleted_at 열 UPDATE와 새 이력 SELECT/INSERT만 추가하고 readiness도 이를 확인한다. 기존 version/updated_at 열 권한을 사용하며 테이블 전체 UPDATE·물리 DELETE·DDL·프로필 변경 권한을 추가하지 않는다.
- 기존 마이그레이션/권한/HTTP 테스트 fixture를 스키마 7에 맞췄다. 서버 검사 도구 scope는 camera_device_delete_storage_native_postgresql이다. 새 코드로 빌드한 기존 API도 스키마 7을 요구하므로 운영 스키마 6에 임의로 재빌드·재시작하지 않는다.
- README·문서 목록·저장소 안내·계약 요약·아키텍처의 현재 상태를 정리했다. 이전 단계의 진행 기록은 작성 당시 이력으로 보존한다. 프로젝트 명세는 운영 인수 스키마 6과 개발 코드 스키마 7을 구분한다.

## 검증

- 로컬 Go 1.25.0 전체 패키지 race 검사 및 go vet 통과. DB 설정 없이 skip된 통합 검사를 DB 검증으로 계산하지 않았다.
- 별도 임시 PostgreSQL 18.3(PGlite 0.5.8)에서 전체 Go race 검사가 통과했다. storage 최상위 28개 통과·native 전용 15개 skip, app 최상위 11개 통과, camera contracts 14개·analysis contracts 3개·httpapi 4개 통과다. app에는 실제 API 프로세스 실행·재시작·토큰 교체·소스 DELETE 회귀가 포함된다. PGlite의 다중 접속은 native 동시성 증거로 사용하지 않았다.
- 신규 storage 검사는 스키마 6→7/재적용·이전 마이그레이션 보존, 부모/삭제된 자식/프로필/모든 과거 이력 보존, 목록/삭제 cursor·ID 예약, 연결 재생성 후 장치/소스 POST/PATCH/DELETE 응답 재생, 키/주체/버전/자식/사용 상태 오류 순서, 실패 키 재시도·성공 기록 실패 롤백·int64 최대·시각 역행·validate 장치 ID·기록 제약을 확인했다.
- 기존 장치 삭제 JSON Schema 정적 검사 8개 통과. Python 3.10 문법과 패치 적용/재적용/충돌/경로·payload 해시/중도 실패 복구 검사는 패키지 검증 결과를 따른다.
- 실제 native PostgreSQL 역할 인증·열 권한 회수/복구, 다중 연결 소스 생성/부모 삭제 양방향과 롤백·같은/다른 키 삭제·장치 행 잠금, 연결 기본 repeatable read 조건은 로컬에서 실행하지 못했다. PostgreSQL 16.2 도구는 발견했지만 이 실행 환경은 프로세스 사용자 전환을 허용하지 않아 native 서버 기동을 중단했다. 이 조건은 Docker PostgreSQL 17.11 서버 검사로 인수한다.

HTTP 라우팅·프로세스 구성을 변경하지 않았으므로 별도 smoke·운영 이미지 빌드·서비스 재시작·운영 마이그레이션은 수행하지 않았다. 실제 장비·연결·추론·UI는 검증 범위가 아니다.

## 서버 인수와 다음 단위

파일 적용은 백업·기준 파일/해시 검사 후 변경 파일만 쓴다. 환경·실행 데이터·운영 백업은 포함하지 않으며 서비스/DB 명령을 호출하지 않는다. 대상 서버에서는 기존 운영 이미지·DB를 유지하면서 별도 고유 Docker 프로젝트의 임시 PostgreSQL 17.11에서 전체 race/vet와 native 검사를 수행한다.

성공 기준은 status=passed, scope=camera_device_delete_storage_native_postgresql, production_services_modified=false 및 시험 DB/네트워크 정리 완료다. 서버 검사 결과는 아직 받기 전이다. 이 패치의 SQL 파일 추가는 운영 스키마 7 적용이나 장치 DELETE 활성화가 아니다.

격리 검사 통과 후 다음 단위는 **10-C: 장치 논리 삭제 HTTP 연결**이다. 엄격한 요청/헤더·응답/오류·OpenAPI·capability와 등록 전용 장치 사용 정책을 연결하고, 새 capability 도입 후 기존 소스 삭제 정책의 정확한 허용 목록과 회귀를 함께 확인한다. 운영 사전점검·리허설·전환은 그 뒤 별도 단위다. 적용/격리 검사 명령은 채팅으로 전달한다.

## 서버 격리 인수 확인 — 2026-10-02

사용자가 첨부한 실행 로그에서 10-B 적용 status=applied·written=29·pending=0을 확인했다. 백업은 var/patch-backups/step10b-a_0e3qyk이며 service_restart_performed=false·database_schema_modified=false다.

고유 시험 프로젝트 vms-storage-test-ed2bcd5b5148에서 PostgreSQL 17.11의 전체 Go race 검사와 vet가 성공했다. 장치 삭제 같은/다른 키 경쟁, 삭제↔소스 생성 양방향의 실제 잠금 대기와 commit/rollback, 이름 수정 행 잠금, native runtime 역할·열 최소 권한·권한 회수/복원 후 원자적 롤백과 같은 키 재시도, READ COMMITTED 강제 검사가 모두 PASS다. 장치·소스 등록/수정/삭제 저장소와 기존 실제 API 프로세스 회귀도 통과했다.

시험 컨테이너와 네트워크 제거를 확인했다. 최종 결과는 status=passed·scope=camera_device_delete_storage_native_postgresql·production_services_modified=false다. 10-B 저장소 서버 격리 인수를 완료한다. 이는 운영 스키마 7 적용이나 새 장치 DELETE HTTP 인수가 아니다. 운영은 09 인수 기준의 0.6.0-source-delete·스키마 6을 유지하며 다음 단위는 10-C HTTP 연결이다.
