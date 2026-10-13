# 07-D3 — 장치 수정 운영 전환 도구

## 이번 단위

07-D2의 서버 격리 리허설 통과를 인수하고, 검증된 이미지로 camera를 스키마 4·장치 수정 API로 전환하는 도구를 추가했다. 작업 시작 시 AGENTS.md, 작업 원칙 문서와 최신 진행 기록을 확인했다. 이번 단위는 활성화 도구·테스트·진행 기록 3개 파일의 추가로 한정한다.

07-C의 제품 코드와 마이그레이션, 프로젝트 명세, 07-D1/D2 파일을 변경하지 않는다. 따라서 리허설에서 검증한 코드·이미지의 연결을 유지한다. 패치 적용 자체는 파일 추가만 수행하며, 실제 운영 전환은 사용자가 활성화 도구를 명시적으로 실행하는 별도 동작이다. 적용·실행 명령은 채팅에서만 제공한다.

## 07-D2 서버 결과 인수

사용자 실행 로그에서 다음을 확인했다.

- 패치 applied, written=3. 백업 `var/patch-backups/step07d2-u5ndiswy`.
- status=passed, scope=`camera_device_update_upgrade_native_docker`.
- 시험 프로젝트 `vms-device-update-test-98d9b4f74c22`.
- 후보 이미지 `sha256:493ba8654937e62bb4de890a63d32af02354ee67100ecd12cf68d4dd544ab7d8`.
- 후보 태그 `vms-device-update-test-98d9b4f74c22-camera:device-update`.
- 이전 camera 이미지 `sha256:f4c88268652fa1002e5a6488201c47ad2d6738e66e5f7b4f7112255f27e989fd`.
- DB 이미지 `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`.
- 스키마 4 전환·runtime 권한·장치와 소스 생성 응답 재생·장치 수정 응답 재생·소스 목록·API 재생성 검증 모두 true.
- 별도 DB의 스키마 3 복원·이전 API 실행·전환 후 데이터 보존 검증 모두 true.
- 보호된 시험 컨테이너와 DB 컨테이너 유지 확인. 시험 컨테이너·볼륨·네트워크 정리 완료.
- production_services_modified=false, device_update_activated=false, automatic_production_database_restore=false.
- 보고서 `var/camera/device-update-upgrade-check.json`.

스키마 4는 시험 DB에서 검증된 상태다. 이 로그만으로 운영 스키마 4 활성화를 완료했다고 기록하지 않는다. 운영은 기존 스키마 3·API `0.3.1-source-list`이며 실제 전환 시 다시 검사한다.

## 활성화 도구 동작

`src/infra/tools/activate_camera_device_update.py`는 명시적인 적용 옵션과 기존 공통 activation 잠금 아래 다음을 수행한다.

1. 07-D2 성공 보고서의 모든 검증 값, 스키마·scope·시험 프로젝트, 코드 명세·리허설 도구 해시·Docker 데몬을 검사한다. 후보·이전·DB 이미지 ID가 현재 로컬 Docker에 존재하는지 확인한다. 이미지를 다시 빌드하지 않는다.
2. 07-D1 읽기 전용 검사로 현재 운영 API·DB·볼륨·비밀·06 완료 기록·공간을 다시 확인한다. 리허설 당시 이전 이미지·DB 이미지·코드·데몬과 일치해야 한다. 최신 운영 건수를 사용하며 과거의 0건을 전제로 삼지 않는다.
3. 원래 Compose와 후보 Compose를 해석해 camera API와 migrator 이미지 이외의 구성이 동일한지 확인한다. `.env`의 기존 단일 이미지 ID만 교체하도록 준비한다. 다른 환경 바이트와 파일 권한을 유지한다.
4. private 백업 경로에 환경·컨테이너 상태·진행 기록을 저장하고 camera API만 정지한다. 스키마 3 이력·역할과 다른 DB 클라이언트가 없는 상태를 확인한 뒤 운영 DB를 custom-format 덤프로 백업하고 목록 검사와 SHA-256을 기록한다.
5. 백업 전후 기존 장치·생성 응답 기록·소스·프로필·소스 생성 응답 기록 건수를 비교한다. 환경·비밀·코드·리허설 및 06 기록·다른 컨테이너가 유지됐는지 다시 확인한다.
6. `.env`를 후보 이미지 ID로 고정하고, 검증한 후보 이미지의 migrator로 스키마 4 마이그레이션 1건과 runtime 권한을 적용한다. 이력·체크섬·테이블과 제한된 열 UPDATE 권한·역할·기존 건수·클라이언트 부재를 확인한다.
7. camera API만 후보 이미지로 시작한다. 의존 서비스 기동·이미지 빌드·pull을 하지 않는다. readiness, API `0.4.0-device-update`, 장치/소스/목록/수정 capability와 목록 GET을 확인한다. 운영 검증용 장치·소스나 PATCH 요청은 만들지 않는다.
8. 최종 스키마·후보 이미지 실행·환경·비밀·기록·다른 서비스와 DB 컨테이너 보존을 확인하고 completed/activated 기록을 저장한다. API 기동 후 정상 요청으로 건수가 바뀔 수 있으므로 기동 이후에는 이전 건수와 같아야 한다는 조건을 적용하지 않는다.

백업 디렉터리는 `var/camera/device-update-activation-backups/step07d3-*`, 결과 보고서는 `var/camera/device-update-activation.json`이다. 백업·환경 사본·진행 기록은 0600, 백업 디렉터리는 0700이다. 토큰·비밀번호·DSN은 결과 JSON에 포함하지 않는다.

## 실패와 재실행

- 마이그레이션 요청 전 실패: 스키마 3, 기존 컨테이너, 환경·비밀·코드·기록·다른 서비스가 보존됐는지 확인한 경우에만 동일한 기존 camera 컨테이너를 다시 시작할 수 있다. 동시 환경 편집은 덮어쓰지 않는다.
- 마이그레이션 요청 후 실패·중단: DDL이 이미 커밋됐을 수 있으므로 후보 이미지 고정, 현재 DB, 비밀과 백업을 유지한다. 이전 이미지 자동 실행·운영 DB 자동 복원은 수행하지 않는다. 실패 기록을 확인한 뒤 별도 복구 판단이 필요하다.
- 실패 또는 중간 진행 기록이 있으면 재실행으로 마이그레이션을 반복하지 않고 검토 필요 상태로 중단한다.
- completed/activated 기록이 있으면 현재 이미지·스키마·권한·API와 기록 일치 여부를 조회한다. 정상일 때 already_activated를 반환하며 정지·시작·마이그레이션·백업을 반복하지 않는다.
- `--apply`가 없으면 Docker를 호출하지 않고 not_applied로 종료한다.

## 로컬 검증

- Python 테스트 23개 통과. 정상 전환·최초 백업·다른 서비스 보존, 불완전한 리허설·누락 이미지·다른 운영 상태 거부, 공간 부족·구성 변화·스키마 및 권한 이상 차단, 백업 중 건수 변화, 동시 환경·리허설 기록 편집 보존, 타 컨테이너 변화 차단을 확인했다.
- 백업/정지 실패 후 기존 API 재시작, 마이그레이션 커밋 후 오류·키보드 중단 시 이전 이미지/DB 자동 복원 금지, 새 데이터 기록 후 기동 실패 시 데이터 유지, 완료 후 재실행의 조회 전용 동작을 확인했다.
- 운영 HTTP 검증의 GET 사용, 명시적 적용 옵션, 보고서·백업 파일 모드와 오류 비밀 비노출을 확인했다.
- 실제 Docker Compose CLI의 오프라인 구성 해석으로 이전 이미지→후보 이미지 override와 `.env` 고정 결과가 같고, camera API/migrator 이미지 외 DB·볼륨·비밀 등 모든 구성이 유지되는지 확인했다. Docker 엔진의 운영 전환은 실행하지 않았다.
- 패치 적용·재적용, 모든 기존 파일과 환경·운영 기록 보존, 압축본 해시·payload 무결성을 확인했다.
- 제품 Go·라우팅·SQL 변경이 없어 앞서 서버에서 통과한 Go/DB 전체 검사와 07-D2 이미지 빌드를 반복하지 않았다.

## 남은 작업

사용자 서버에서 실제 운영 활성화 실행과 결과 인수가 남아 있다. 성공 결과는 scope=`camera_device_update`, status=activated, stage=completed, schema_version=4, migration_applied=1, device_update_activated=true다. other_services_unchanged=true, database_container_unchanged=true, automatic_database_restore=false, business_runtime_ready=false를 함께 확인한다.

성공 결과를 받으면 다음 작은 단위는 **07 장치 수정 운영 인수 기록 반영**이다. 다음 기능 구현은 그 기록 이후 별도 단위로 진행한다.
