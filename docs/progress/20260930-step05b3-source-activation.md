# 단위 05-B3 — 검증된 소스 API의 실제 전환 준비

작성일: 2026-09-30 · 05-B2 서버 인수 완료 · 05-B3 도구 전달 · 운영 전환 대기

## 05-B2 서버 결과

사용자 실행 로그에서 패치 4개 적용과 `camera_source_upgrade_native_docker`의 `status=passed`를 확인했다. 패치 백업은 `/home/shshin/workspace/vms_project/var/patch-backups/step05b2-ngm8snga`, 검사 프로젝트는 `vms-source-upgrade-test-bdfa9c4951ab`이다.

검증된 후보 이미지: `sha256:3c0b6919565eceb0511b55c5f5d4faea3fa94c4404de8020f7fdb8df3ae20b93`.

스키마 2→3, runtime 권한, 장치·소스 멱등 응답, API 재생성, 별도 DB 스키마 2 복원과 구버전 API, 전환 후 소스 데이터 보존, 다른 시험 컨테이너 보존이 모두 통과했다. 시험 컨테이너·볼륨 정리가 완료됐고 후보 이미지는 유지됐다. `production_services_modified=false`, `source_api_activated=false`이므로 이 시점의 운영 API는 아직 구버전이다.

## 이번 범위

이번 단위는 실제 camera 전환 도구·필수 실패 처리 검사·운영 안내다. 새 소스 기능이나 다른 플랫폼 작업을 포함하지 않는다. 기존 05-A 배포 명세 및 05-B2 검사 코드·보고서와의 연결을 유지한다. 패치 적용은 파일만 변경하며 운영 작업은 별도 전환 도구 실행에서 수행한다.

전환 도구는 서버 검사 성공 결과와 이미지 ID를 대조한 뒤 camera API를 중지하고 DB 클라이언트 종료·스키마를 확인한다. 기존 설정과 DB 백업을 보존하고 스키마 3·권한을 반영한다. `.env`에 검증된 이미지 ID를 고정하고 camera API만 시작한다. DB 컨테이너와 다른 플랫폼의 상태가 유지되는지 확인한다. 업무 데이터 변경 없이 GET 요청으로 소스 조회 경로를 확인한다.

마이그레이션 요청 전 실패하면 스키마 2와 원래 설정·컨테이너가 유지되는 경우 기존 API를 다시 시작한다. 마이그레이션을 요청한 이후에는 DB 백업을 자동 복원하거나 구버전 API를 다시 시작하지 않는다. 현재 DB·후보 이미지·백업·진행 기록을 보존한다. 실패·중단 기록이 있으면 재실행을 막아 동일 작업을 무조건 반복하지 않는다. 완료 상태에서 재실행하면 조회 검증만 수행한다.

세부 절차와 실패 처리 기준은 `docs/operations/camera-source-upgrade.md`를 갱신했다. 작업 중 camera API에는 짧은 중단이 발생한다. 실장비 연결·영상 수신·분석은 이번 단계의 완료 조건이 아니며 `business_runtime_ready=false`를 유지한다.

## 검증

- 로컬 분기 검사 11개 통과: 성공·이미지 고정·다른 컨테이너 보존, 잘못된 인수 보고서 거부, 백업 실패/중지 결과 불명 시 기존 API 복구, 별도 DB 클라이언트 거부, DDL 반영 후 실패 시 구버전 재시작 금지, 시작 후 받은 데이터 보존, 동시 설정 수정 보존, 미완료 재실행 차단, 완료 재실행의 조회 전용 동작, GET 조회 확인.
- `make smoke` 43개 통과. HTTP·인증·계약·정상 종료 범위이며 실장비 검증은 아니다.
- Compose 구성 확인: `.env`에 고정한 이미지 ID가 API와 migrator에 동일하게 적용되고 DB 이미지·호스트 포트 설정이 유지된다.
- 실제 Docker·PostgreSQL 전환의 기반 동작은 05-B2 사용자 서버 로그로 확인했다. 신규 05-B3 도구 자체를 제작 환경의 Docker에서 실행하지는 못했다. 실제 운영 전환 완료는 서버 결과를 받은 뒤 기록한다.

## 다음 완료 기준

서버의 `status=activated`, `scope=camera_source_registry`, `schema_version=3`, `source_api_activated=true`, `other_services_unchanged=true`, `database_container_unchanged=true`를 확인한다. 실패하면 자동으로 다음 기능으로 넘어가지 않고 기록된 단계와 DB 상태를 기준으로 해당 문제를 처리한다.

성공 결과를 인수하면 단위 05의 운영 활성화 완료 기록을 반영한다. 이후 소스 목록 조회를 다음 독립 기능 단위로 검토한다. 수정·삭제·장비 연결을 한 번에 묶지 않는다.
