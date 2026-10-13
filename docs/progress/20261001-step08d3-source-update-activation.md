# 08-D3 — 소스 수정 운영 전환 도구

작성일: 2026-10-01 · 도구·로컬 검증 완료 · 서버 운영 전환 결과 대기

## 이번 단위

08-D2 격리 리허설 통과를 인수하고, 검증한 후보 이미지로 camera를 스키마 5·소스 수정 API로 전환하는 도구를 추가했다. 작업 기준에 따라 이번 범위는 활성화 도구·테스트·진행 기록의 3개 파일이다.

08-C 제품 코드·마이그레이션·프로젝트 명세와 08-D1/D2 및 시간 비교 수정 파일을 유지한다. 서버에서 검증한 이미지·코드·리허설 해시의 연결을 보존한다. 패치 적용은 파일 추가만 수행하고, 실제 운영 전환은 활성화 도구의 명시적 적용 옵션으로 실행한다. 적용·실행 명령은 채팅으로만 제공한다.

## 08-D2 서버 결과 인수

Python 3.10 시간 비교 수정 패치는 applied/written=3, 백업은 `var/patch-backups/step08d2-timefix-zgjwi4ng`다. 서버 단위 테스트 34개가 0.231초에 통과했다. 앞선 ValueError 실패는 수정 후 리허설 완료로 해소됐다.

- status=passed, scope=`camera_source_update_upgrade_native_docker`.
- 시험 프로젝트: `vms-source-update-test-f2450eac508a`.
- 후보 이미지: `sha256:6c10ff4314892d952933d457e9dee6ddaf0126aadc551c9bb07813f5344915dd`.
- 후보 태그: `vms-source-update-test-f2450eac508a-camera:source-update`.
- 이전 camera 이미지: `sha256:493ba8654937e62bb4de890a63d32af02354ee67100ecd12cf68d4dd544ab7d8`.
- DB 이미지: `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`.
- 스키마 5 업그레이드·runtime 권한·장치와 소스 생성 응답 재생·장치와 소스 수정 응답 재생·목록 보존·API 재생성 검증 모두 true.
- 별도 DB의 스키마 4 복원·이전 API 실행·전환 후 데이터 보존 검증 모두 true.
- 보호된 시험 컨테이너와 DB 컨테이너 유지, 시험 컨테이너·볼륨·네트워크 정리 완료.
- production_services_modified=false, source_update_activated=false, automatic_production_database_restore=false.
- 보고서: `var/camera/source-update-upgrade-check.json`.

[시간 비교 수정 기록](20261001-step08d2-python310-timestamp-fix.md)의 서버 재검증 대기는 이 결과로 해소됐다. 스키마 5와 새 API는 격리 환경에서 검증된 상태다. 운영은 기존 API `0.4.0-device-update`·스키마 4이며 실제 전환 직전에 다시 확인한다.

## 활성화 도구 동작

`src/infra/tools/activate_camera_source_update.py`는 기존 activation 잠금을 사용한다.

1. 08-D2 성공 보고서의 scope·스키마·모든 검증 값·자원 정리와 코드 명세·리허설 해시·Docker 데몬을 확인한다. 후보·이전·DB 이미지 ID가 로컬에 존재해야 한다. 후보 이미지를 다시 빌드하지 않는다.
2. 08-D1의 읽기 전용 사전점검으로 운영 API·DB·볼륨·비밀·07 완료 기록·공간을 다시 검사한다. 리허설 당시 이전 이미지·DB 이미지·코드·데몬과 일치해야 한다. 현재 운영 데이터가 0건이라는 가정은 하지 않는다.
3. 원래 구성과 후보 이미지 적용 구성을 비교해 camera API와 migrator의 이미지 이외 설정이 동일한지 검사한다. `.env`의 기존 단일 이미지 ID만 교체하며 다른 내용과 파일 권한을 유지한다.
4. 환경·컨테이너 상태·진행 기록을 보관하고 camera API만 정지한다. 스키마 4 이력·역할 및 다른 DB 클라이언트 부재를 확인한다. 운영 DB를 custom-format 덤프로 백업하고 목록 검사·SHA-256을 기록한다.
5. 백업 전후 장치·장치 생성 이력·소스·프로필·소스 생성 이력·장치 수정 이력의 6개 건수가 유지되는지 확인한다. 환경·비밀·코드·리허설·07 완료 기록 및 다른 컨테이너도 다시 확인한다.
6. `.env`를 후보 이미지 ID로 고정하고 검증한 후보의 migrator로 스키마 5 마이그레이션 1건과 runtime 권한을 적용한다. 이력·체크섬·소스 수정 이력 테이블, 장치·소스의 제한된 열 UPDATE 권한·역할·기존 6개 건수·클라이언트 부재를 확인한다.
7. camera API만 후보 이미지로 실행한다. API 실행 명령은 의존 서비스 기동·이미지 빌드·pull을 수행하지 않는다. readiness, 버전 `0.5.0-source-update`, 장치/소스 등록·목록·장치 수정·소스 수정 capability와 목록 GET을 확인한다. 운영 확인용 등록·PATCH 요청은 만들지 않는다.
8. 최종 스키마·실행 이미지·환경·비밀·기록·다른 서비스와 DB 컨테이너 보존을 확인하고 completed/activated 결과를 기록한다. API 기동 후 정상 요청이 들어올 수 있으므로 기동 이후 건수는 백업 당시와 같아야 한다고 강제하지 않는다.

백업 경로는 `var/camera/source-update-activation-backups/step08d3-*`, 결과 보고서는 `var/camera/source-update-activation.json`이다. 백업·환경 사본·진행 기록은 0600, 백업 디렉터리는 0700이다. 토큰·비밀번호·DSN은 결과 JSON에 포함하지 않는다.

## 실패와 재실행

- 마이그레이션 요청 전 실패: 스키마 4와 기존 컨테이너·환경·비밀·코드·기록·다른 서비스가 유지됐음을 확인한 경우에만 같은 기존 camera 컨테이너를 다시 시작한다. 동시 환경 편집은 덮어쓰지 않는다.
- 마이그레이션 요청 후 실패·중단: DDL이 이미 커밋됐을 수 있으므로 후보 이미지 고정과 현재 DB·비밀·백업을 유지한다. 이전 이미지 자동 실행이나 운영 DB 자동 복원은 수행하지 않는다.
- 실패·중간 진행 기록이 있으면 재실행으로 전환을 반복하지 않고 검토 필요 상태로 중단한다.
- completed/activated 기록이 있으면 현재 이미지·스키마·권한·API와 기록을 조회한다. 정상일 때 already_activated를 반환하며 정지·시작·마이그레이션·백업을 반복하지 않는다.
- 명시적 적용 옵션이 없으면 Docker를 호출하지 않고 not_applied로 종료한다.

## 로컬 검증

- Python 테스트 25개 통과. 정상 전환·백업·이미지 고정·다른 서비스 보존, 오래되거나 불완전한 보고서·누락 이미지·운영 상태 불일치 거부, 구성·공간·스키마·역할 검사, 백업 중 건수 변화, 환경·보고서 동시 편집 보존, 타 컨테이너 변화 차단을 확인했다.
- 장치·소스 수정 응답 재생과 스키마 4 복원 검증이 없는 보고서는 거부한다. 마이그레이션 중 기존 장치 수정 이력 건수가 줄면 새 API 기동을 막고 현재 DB·후보 고정 상태를 유지한다.
- 백업·정지 실패 후 기존 API 재시작, DDL 커밋 후 오류·중단 시 자동 복원 금지, 기동 후 새 데이터가 생긴 상태의 실패 보존, 완료 후 재실행의 조회 전용 동작을 확인했다.
- 실제 Docker Compose CLI의 오프라인 해석으로 camera API/migrator 이미지 외 DB·볼륨·비밀·포트 등 모든 구성이 유지되고 `.env` 고정 결과와 이미지 override 결과가 같음을 확인했다.
- PGlite 임시 스키마 4·5에서 실제 조회 SQL을 실행해 마이그레이션 체크섬·테이블 유무·6개 건수·클라이언트·역할 결과를 확인했다. 장치 수정 이력 1건을 넣어 스키마 5에서도 조회 건수가 유지됨을 확인했다. native PostgreSQL 17 버전 판정과 운영 전환 실행을 대신하는 검증은 아니다.
- 패치 적용·재적용·충돌 시 쓰기 중단, 기존 환경·실행 기록·리허설 해시 및 179개 프로젝트 명세 파일 보존을 확인했다.

제품 Go·라우팅·마이그레이션을 바꾸지 않았으므로 이미 통과한 제품 전체 검사와 08-D2 이미지 빌드·복원 리허설을 반복하지 않았다. 로컬에는 Docker 엔진이 없어 실제 운영 전환은 실행하지 않았다.

## 남은 작업

사용자 서버의 실제 운영 활성화 결과 인수가 남아 있다. 성공 결과는 scope=`camera_source_update`, status=activated, stage=completed, schema_version=5, migration_applied=1, source_update_activated=true다. other_services_unchanged=true, database_container_unchanged=true, automatic_database_restore=false, business_runtime_ready=false를 함께 확인한다.

그 결과를 받은 뒤 다음 작은 단위는 **08 소스 수정 운영 인수 기록 반영**이다. 다음 기능 구현은 그 기록 이후 별도로 진행한다.
