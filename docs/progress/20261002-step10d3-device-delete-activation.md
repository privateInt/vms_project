# 단위 10-D3 — 장치 삭제 운영 전환 준비

작성일: 2026-10-02 · 전환 도구·로컬 검사 완료 · 서버 전환 결과 대기

## 10-D2 서버 리허설 인수

사용자 로그에서 10-D2 패치 applied/written=3·pending=0, 백업 `var/patch-backups/step10d2-sad9pjb6`과 실제 Docker 리허설 passed를 확인했다. scope는 camera_device_delete_upgrade_native_docker, 임시 프로젝트는 `vms-device-delete-test-75ce968cddde`다.

| 항목 | 서버 검증 결과 |
|---|---|
| 스키마 6→7 / runtime 최소 권한 | 통과 |
| 장치·소스 생성/수정 및 이전 소스 삭제 이력 재생 | 통과 |
| 활성 자식 거부 / 자식 삭제 후 같은 키로 부모 삭제 재시도 | 통과 |
| 장치 삭제 결과 재생 / 자식·프로필·보호 행 보존 | 통과 |
| 등록 전용 정책 / 장치·소스 목록·cursor | 통과 |
| API 재생성 후 모든 이력 유지 | 통과 |
| 별도 DB 스키마 6 복원 / 이전 API | 통과 |
| 전환 후 데이터·시험 DB 컨테이너·sentinel 보존 | 통과 |
| 임시 컨테이너·볼륨·네트워크 정리 | 완료 |
| 운영 서비스 변경 / 장치 삭제 활성화 / 자동 운영 DB 복원 | 모두 false |

검증된 후보는 `sha256:708d5a53f3dcc3d22dca775ef2825bcd271a68c7c3777cf8a6a89bb6933aa7d6`이며 태그는 `vms-device-delete-test-75ce968cddde-camera:device-delete`다. 이전 camera 이미지는 `sha256:b104c902592bf67b025b9463e9fcbb8c964281d5162c21e69f9db41d2d9c45f8`, DB 이미지는 `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`이다.

검증 필드 17개가 모두 true였으며 previous_schema_version=6·schema_version=7·usage_policy=registry-only-v1을 확인했다. 서버 보고서는 `var/camera/device-delete-upgrade-check.json`이다. 이 인수로 [10-D2 기록](20261002-step10d2-device-delete-rehearsal.md)의 실제 서버 리허설 대기가 해소됐다. 운영은 아직 0.6.0-source-delete·스키마 6이다.

## 이번 작업 범위

AGENTS.md·작업 기준의 작은 작업 단위 원칙을 따른다. 이번 패치는 전환 도구 `src/infra/tools/activate_camera_device_delete.py`, 해당 Python 검사, 이 문서의 3개 파일만 추가한다. 기존 248개 파일·Go·SQL 마이그레이션·Compose·프로젝트 명세·10-D1/10-D2 도구를 보존한다. 전달 당시 명세의 검증 표시는 그대로 유지하고 이후 서버 인수는 진행 기록으로 구분한다.

파일 패치 적용은 서비스나 DB를 변경하지 않는다. 전환 도구에 명시적으로 적용 옵션을 전달한 경우에만 운영 전환을 수행한다. 새 후보 이미지를 빌드하지 않고 리허설 보고서의 정확한 로컬 이미지 ID를 사용한다. 이 단위는 장치 삭제의 운영 전환 준비이며 장치 연결·미디어·세션·추론·UI 구현은 포함하지 않는다.

## 전환 전 확인

- 성공 리허설의 scope·임시 프로젝트 이름·이전 스키마 6/목표 7·registry-only-v1과 검증 필드 17개, 시험 자원 정리·운영 무변경·미활성화·자동 복원 미수행을 요구한다.
- 리허설의 프로젝트 명세·전체 파일 해시·도구 recipe·Docker 데몬이 현재 상태와 일치해야 한다. 후보/이전/DB 이미지가 로컬에 있어야 하며 후보와 이전 이미지가 달라야 한다. 이미지 ID를 코드에 하드코딩하지 않는다.
- 현재 운영은 09 완료 기록에 맞는 0.6.0-source-delete·스키마 6이어야 한다. 기존 읽기 전용 사전점검을 다시 수행해 컨테이너·볼륨·비밀·마운트·실행 OpenAPI·capability·DB 이력/역할/권한·백업 공간을 확인한다.
- 후보 Compose 구성은 camera API/migrator 이미지 값 외에는 현재 구성과 같아야 한다. 환경 파일의 camera 이미지 고정 값만 교체하며 다른 내용·줄바꿈·권한을 보존한다.
- 전환 중에도 코드·리허설 보고서·09 완료 기록·전환 도구·환경·비밀·다른 컨테이너를 확인한다. 동시 수정이 있으면 해당 상태를 덮어쓰지 않는다.

## 적용 절차

1. 공유 activation 잠금을 잡고 `var/camera/device-delete-activation-backups/step10d3-*`에 기존 환경·컨테이너 상태와 전환 단계를 기록한다.
2. camera API만 정지한다. 원래 camera 컨테이너가 정지했으며 DB의 다른 클라이언트가 종료됐는지 확인한다. PostgreSQL 17·스키마 6의 전체 이력/체크섬·역할/최소 권한과 기존 테이블 8개의 건수·전체 행 집계 해시를 수집한다. source_delete_requests를 포함한다.
3. 운영 스키마 6 DB를 custom-format pg_dump로 백업한다. 파일 형식·pg_restore 목록·SHA-256을 확인한다. 백업 후 스키마·다른 클라이언트·건수와 전체 행 해시가 동일해야 다음 단계로 간다.
4. 환경 파일에 후보 이미지 ID를 고정한다. 검증한 후보 migrator로 스키마 7 적용 1건과 runtime 최소 권한을 확인한다. 기존 8개 테이블의 건수/전체 행 해시가 유지되고 새 device_delete_requests가 비어 있어야 새 API를 시작한다.
5. 후보 camera API만 no-deps/no-build/pull-never 방식으로 시작한다. readiness·플랫폼 정보·장치/소스 목록·실행 OpenAPI를 GET으로 확인한다. API 0.7.0-device-delete·P1_DEVICE_DELETE와 등록 전용 capability 전체가 일치해야 한다. 명세에는 장치/소스 DELETE가 함께 있어야 한다.
6. 스키마 7·실행 이미지·DB health·영속 볼륨·읽기 전용 runtime DSN 마운트·파일 비밀 구성, 기존 DB 컨테이너·다른 서비스·환경·비밀 보존을 확인하고 완료 기록을 저장한다.

운영 인수에서 POST/PATCH/DELETE를 호출하거나 시험 데이터를 만들지 않는다. 삭제 동작·과거 응답 재생·복원은 10-D2에서 검증한 동일 이미지의 결과를 사용한다. 새 API 시작 후 정상 업무 요청으로 발생한 데이터 변경은 허용한다. 실제 사용 관계 감지나 업무 런타임 준비 완료를 의미하지 않는다.

건수·전체 행 해시는 BEGIN READ ONLY·statement/lock timeout을 둔 고정 SQL의 한 SELECT에서 읽는다. 등록 원문이나 성공 응답 원문을 출력/기록하지 않는다. 전체 행 비교는 업무 쓰기를 중단한 백업/마이그레이션 구간에만 수행한다. 스키마 7의 장치 삭제 기록 수는 별도의 고정 READ ONLY SQL로 확인한다.

## 실패·재실행 동작

마이그레이션 요청 전의 정지/백업 실패는 스키마 6·원래 컨테이너·코드·환경·비밀 등이 일치할 때만 이전 API를 다시 시작한다. 사용자 동시 수정·보고서 변경·다른 서비스 변경 등이 있으면 상태를 보존하고 검토를 요구한다.

마이그레이션 요청 이후에는 오류/중단 시에도 후보 이미지 설정·DB·비밀·백업을 유지한다. 응답을 받지 못해도 DDL이 커밋됐을 수 있으므로 이전 이미지를 자동 시작하거나 운영 DB를 자동 복원하지 않는다. 새 API가 이미 처리한 데이터도 덮어쓰지 않는다. 실패/중간 단계 기록이 있으면 재실행해도 추가 전환을 진행하지 않고 검토를 요구한다.

완료 기록이 있으면 현재 스키마·이미지·권한·읽기 API/OpenAPI·DB health/마운트·환경/비밀·recipe·전환 도구 해시를 다시 확인한 뒤 already_activated를 반환한다. 성공 재실행은 백업·마이그레이션·재시작을 하지 않는다. 정상 운영 중 추가된 데이터와 장치 삭제 기록을 허용하며 과거 cutover 건수/행 해시로 되돌리거나 같은 값을 요구하지 않는다.

결과는 `var/camera/device-delete-activation.json` 및 백업 폴더의 `result.json`에 남긴다. 기록·백업·기존 환경 사본은 0600, 백업 디렉터리는 0700이다. 전체 행 해시와 내부 검증 해시는 개인 기록에만 두며 공개 출력에서 제외한다. 토큰·DSN·비밀번호·기존 환경 원문은 공개하지 않는다. 이전 완료 기록·리허설 보고서를 수정하지 않는다.

## 검증과 한계

- Python 전환 검사 45개 통과. 모의 Docker로 정상 전환·성공 재실행, 백업 실패·정지 응답 불확실·다른 DB 클라이언트·마이그레이션 후 오류/중단·기동/읽기 인수 실패를 확인했다.
- 리허설 증거 17개와 이전 스키마/정책, 이미지/구성/코드·환경·보고서·이전 완료 기록·다른 컨테이너 변경, 부족한 백업 공간·백업 변조, 잘못된 스키마/관리자·replication/RLS 권한·runtime 권한·집계 형식·비밀 마운트를 차단했다.
- 기존 장치/소스 수정 및 소스 삭제 이력의 건수 감소와 같은 건수에서의 행/성공 응답 변조, 새 장치 삭제 기록의 비정상 생성이 후보 API 시작 전에 중단됨을 확인했다. 마이그레이션 후 실패에서는 후보 상태·새 데이터·백업을 보존하고 이전 API 재시작/운영 DB 복원을 하지 않는다.
- 실제 리허설의 capability 검사와 새 장치/소스 OpenAPI 검사를 연결해 운영 인수가 GET만 사용하는지 확인했다. 완료 후 합법적인 업무 쓰기·장치 삭제 기록이 생겨도 재전환 없이 검증하며, 완료 도구 변경/DB 볼륨/비밀 마운트 변경은 거부한다. 개인 행 해시가 공개 성공 출력에 없음을 확인했다.
- 임시 PostgreSQL 18.3(PGlite 0.5.8)에서 도구의 고정 SQL을 실행했다. 스키마 6/7 이력·기존 8개 건수/전체 행 해시 보존·장치 삭제 열 권한 변화·기존 소스 삭제 기록 포함, 같은 건수의 장치/삭제 응답 변경 탐지·새 삭제 기록 수 0/1과 READ ONLY 쓰기 거부를 확인했다. native 역할 인증·Docker 전환·운영 백업 검증을 대체하지 않는다.
- Python 3.10 문법, 패치 적용 도구 검사 8개, 전체 패키지 적용 3개/재적용 0개·기준 충돌 시 쓰기 없음, 기존 248개 파일·프로젝트 명세·환경/운영 기록의 내용과 권한 보존, payload/압축본 경로·해시를 확인했다.

현재 작성 환경에는 Docker가 없어 새 전환 도구를 실제 운영 환경에서 실행하지 않았다. 10-D2 실제 Docker 검증은 사용자 로그로 인수했고 이번 검사는 전환 제어 흐름을 모의 IO와 임시 DB SQL로 확인한 결과다. Go/HTTP/마이그레이션·Compose를 바꾸지 않아 기존 전체 Go/race/vet/smoke 검사를 반복하지 않았다.

## 서버 인수 기준과 다음 단위

최초 성공은 status=activated·scope=camera_device_delete·stage=completed·schema_version=7·migration_applied=1·usage_policy=registry-only-v1·device_delete_activated=true다. candidate_image가 위 리허설 후보와 같아야 한다. other_services_unchanged=true·database_container_unchanged=true·existing_rows_preserved=true·new_device_delete_journal_empty_at_cutover=true·automatic_database_restore=false·business_runtime_ready=false도 확인한다.

실제 적용 시 camera API가 잠시 중단된다. 성공 후 API는 0.7.0-device-delete·스키마 7이다. 재실행 성공은 already_activated·service_restart_performed=false이며 완료 기록을 다시 쓰지 않는다.

다음 단위는 **10 운영 전환 결과 인수와 완료 기록 반영**이다. 서버 최초 적용/재실행 결과를 확인한 뒤 진행한다. 이번 문서는 도구 준비 상태이며 실제 전환 완료로 표시하지 않는다. 적용·실행 명령은 채팅으로만 제공한다.
