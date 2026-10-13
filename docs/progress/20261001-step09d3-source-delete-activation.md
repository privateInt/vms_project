# 단위 09-D3 — 소스 삭제 운영 전환 준비

작성일: 2026-10-01 · 전환 도구·로컬 검사 완료 · 서버 전환 결과 대기

## 09-D2 서버 리허설 인수

사용자가 전달한 09-D2 패치 applied/written=3, 백업 `var/patch-backups/step09d2-9qy__90x`, Python 검사 43개 통과와 실제 Docker 리허설 passed를 확인했다. scope는 camera_source_delete_upgrade_native_docker, 임시 프로젝트는 `vms-source-delete-test-7be121c241e4`다.

| 항목 | 서버 검증 결과 |
|---|---|
| 스키마 5→6 / runtime 권한 | 통과 |
| 기존 장치·소스 생성/수정 이력 재실행 | 통과 |
| 삭제 결과 재실행 / 프로필·보호 행 보존 | 통과 |
| 등록 전용 정책 / 목록·cursor | 통과 |
| API 컨테이너 재생성 후 이력 유지 | 통과 |
| 별도 DB의 스키마 5 복원 / 이전 API | 통과 |
| 전환 후 데이터·시험 DB 컨테이너·sentinel 보존 | 통과 |
| 임시 컨테이너·볼륨·네트워크 정리 | 완료 |
| 운영 서비스 변경 / 삭제 활성화 / 자동 운영 DB 복원 | 모두 false |

검증된 후보는 `sha256:b104c902592bf67b025b9463e9fcbb8c964281d5162c21e69f9db41d2d9c45f8`이며 태그는 `vms-source-delete-test-7be121c241e4-camera:source-delete`다. 이전 camera 이미지는 `sha256:6c10ff4314892d952933d457e9dee6ddaf0126aadc551c9bb07813f5344915dd`, DB 이미지는 `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`이다.

모든 검증 플래그가 true였으며 schema_version=6, usage_policy=registry-only-v1을 확인했다. 서버 보고서는 `var/camera/source-delete-upgrade-check.json`이다. [09-D2 기록](20261001-step09d2-source-delete-rehearsal.md)의 실제 서버 리허설 대기가 해소됐다. 운영은 아직 0.5.0-source-update·스키마 5를 유지한다.

## 이번 작업 범위

`AGENTS.md`와 `docs/development/working-standards.md`의 작은 작업 단위 원칙을 따른다. 이번에는 전환 도구 `src/infra/tools/activate_camera_source_delete.py`, 해당 Python 검사, 이 문서의 3개 파일만 추가한다. Go·SQL 마이그레이션·Compose·프로젝트 명세·09-D1/09-D2 도구와 기존 파일의 해시는 보존한다.

파일 패치 적용은 서비스나 DB를 변경하지 않는다. 전환 도구에 명시적으로 적용 옵션을 전달한 경우에만 운영 전환을 수행한다. 후보 이미지를 새로 빌드하거나 pull하지 않고, 서버 리허설 보고서가 가리키는 정확한 이미지 ID를 사용한다. 이번 단계에는 새 CRUD·장치 연결·미디어·UI 기능을 포함하지 않는다.

## 전환 전 확인

- 성공 리허설의 scope·프로젝트 이름·스키마 6·registry-only-v1과 모든 검증 플래그, 시험 리소스 정리, 운영 무변경·미활성화·자동 복원 미수행을 요구한다.
- 리허설의 프로젝트 명세·전체 파일 해시·도구 recipe·Docker 데몬과 현재 상태가 같아야 한다. 후보/이전/DB 이미지 ID가 로컬에 존재해야 하며 후보와 이전 이미지는 달라야 한다.
- 현재 운영은 08 완료 기록에 맞는 0.5.0-source-update·스키마 5여야 한다. 기존 읽기 전용 사전점검을 다시 수행해 컨테이너·볼륨·비밀·마운트·API capability·DB 역할과 백업 공간을 확인한다.
- 후보 Compose 구성은 camera API/migrator 이미지 값 외에는 현재 구성과 같아야 한다. 기존 환경 파일의 다른 내용과 권한은 유지한다.
- 전환 중에도 코드·리허설 보고서·08 완료 기록·전환 도구·환경·비밀·다른 서비스의 변경을 감시한다. 사용자 동시 수정이 발견되면 덮어쓰지 않는다.

## 적용 절차

1. 공유 activation 잠금을 잡고 `var/camera/source-delete-activation-backups/step09d3-*`에 기존 환경·컨테이너 상태를 저장한다.
2. camera API만 정지한다. 기존 camera 컨테이너가 정지했으며 DB의 다른 클라이언트가 모두 종료됐는지 확인한다. DB 컨테이너와 다른 서비스는 재시작하지 않는다.
3. 스키마 5 운영 DB를 custom-format pg_dump로 백업한다. 파일 형식·pg_restore 목록과 SHA-256을 확인한다. 정지 후와 백업 후의 스키마·7개 기존 테이블 건수를 검사한다. 이 건수에는 source_update_requests가 포함된다.
4. 환경 파일의 camera 이미지 ID를 후보로 고정한다. 검증된 이미지의 migrator를 한 번 실행해 스키마 6 적용 1건과 runtime 최소 권한을 확인한다. 기존 7개 테이블 건수가 유지돼야 새 API를 시작한다.
5. 후보 camera API만 no-deps/no-build/pull-never 방식으로 시작한다. readiness·장치 목록·플랫폼 정보·소스 목록을 GET으로 확인한다. 플랫폼은 0.6.0-source-delete, P1_SOURCE_DELETE와 등록 전용 capability 전체가 일치해야 한다. 소스 삭제는 implemented이고 세션·소비자·미디어 기능은 planned여야 한다.
6. 스키마 6, 실행 이미지, 기존 DB 컨테이너·다른 서비스·환경·비밀 보존을 확인하고 완료 기록을 저장한다.

운영 인수 검사에서 등록·수정·삭제 API를 호출하거나 운영 데이터를 시험용으로 만들지 않는다. DELETE/PATCH 동작은 09-D2에서 검증된 동일 이미지의 결과를 사용한다. 실제 사용자가 이후 API를 호출하면 그 업무 변경은 별개다.

## 실패·재실행 동작

마이그레이션을 요청하기 전의 백업/정지 실패는 스키마 5·원래 컨테이너·코드·환경·비밀 등이 그대로일 때만 이전 API를 다시 시작한다. 사용자 동시 수정이나 상태 불일치가 있으면 해당 상태를 보존하고 검토를 요구한다.

마이그레이션 요청 이후에는 오류·중단 시에도 후보 이미지 설정, DB·비밀·백업을 유지한다. 응답을 못 받았어도 DDL이 커밋됐을 수 있으므로 이전 이미지를 자동으로 시작하거나 운영 DB를 자동 복원하지 않는다. 새 API가 이미 처리한 데이터도 덮어쓰지 않는다. 실패/중간 단계 기록이 있으면 도구를 다시 실행해도 추가 전환을 진행하지 않고 검토를 요구한다.

완료 기록이 있으면 현재 스키마·이미지·등록 전용 정책·권한·읽기 API·해시를 다시 확인한 뒤 already_activated를 반환한다. 성공 재실행은 백업·마이그레이션·재시작을 하지 않는다.

전환 결과는 `var/camera/source-delete-activation.json` 및 백업 폴더의 `result.json`에 남긴다. 기록·백업·기존 환경 사본은 0600, 백업 디렉터리는 0700이다. 공개 출력은 토큰·DSN·환경 내용·내부 검증 해시를 제외한다. 기존 다른 단계의 완료 기록과 리허설 보고서를 수정하지 않는다.

## 검증

- Python 3.12.14에서 새 전환 검사 31개 통과. 모의 Docker로 정상 전환·성공 재실행과 백업 실패·정지 응답 불확실·다른 DB 클라이언트·마이그레이션 후 오류/중단·기동/읽기 인수 실패를 검증했다.
- 리허설의 삭제 정책·보호 행·삭제/수정 이력·복원 증거 누락, 이미지/구성/코드·환경·보고서·다른 컨테이너 변경, 부족한 백업 공간, 잘못된 스키마/역할/건수를 차단했다. 스키마 5의 source_update_requests 이력이 줄면 후보 API 시작 전에 중단함을 확인했다.
- 실제 리허설의 capability 검증 함수를 연결해 등록 전용 정책을 확인했고, 운영 인수가 GET만 사용하는지 점검했다. 마이그레이션 이후 실패 시 이전 API 재시작·운영 DB 복원 없이 후보 상태를 보존하는지 확인했다.
- Python 3.10 문법 파싱, 기존 210개 프로젝트 명세 파일의 해시와 모든 기존 파일 보존을 확인했다. 패키지 사전점검·적용 3개·재적용 0개·충돌 시 쓰기 없음, 기존 환경/완료 기록의 내용·권한 보존과 압축본 해시/경로를 검사했다.

현재 작성 환경에는 Docker가 없어 새 전환 도구를 실제 운영 환경에서 실행하지 않았다. 09-D2의 실제 Docker 검증은 사용자 로그로 인수했고, 이번 31개 검사는 전환 제어 흐름을 모의 IO로 검증한 결과다. Go/HTTP/Compose를 바꾸지 않아 기존 전체 Go/vet/smoke 검사는 반복하지 않았다.

## 서버 인수 기준과 다음 단위

최초 성공은 status=activated, scope=camera_source_delete, stage=completed, schema_version=6, migration_applied=1, usage_policy=registry-only-v1, source_delete_activated=true다. candidate_image가 위 리허설 후보와 일치해야 한다. other_services_unchanged=true, database_container_unchanged=true, automatic_database_restore=false, business_runtime_ready=false도 확인한다.

실제 실행 시 camera API가 잠시 중단된다. 성공 후 API는 0.6.0-source-delete·스키마 6이며 업무 런타임·실장비 연결 준비 완료를 의미하지 않는다. 재실행 성공은 already_activated 및 service_restart_performed=false다.

다음 단위는 **09 운영 전환 결과 인수와 완료 기록 반영**이다. 서버 결과를 확인한 뒤 수행하며 이번 문서에서는 전환을 완료로 표시하지 않는다. 적용·실행 명령은 채팅에서 별도로 제공한다.
