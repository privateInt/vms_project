# 단위 10-D2 — 장치 삭제 업그레이드·복구 격리 리허설

작성일: 2026-10-02 · 도구·로컬 검증 완료 · 서버 Docker 리허설 결과 대기 · 운영 활성화 전

## 10-D1 서버 결과 인수

사용자 로그에서 10-D1 패치 applied/written=3·pending=0, 백업 `var/patch-backups/step10d1-6txpvti9`와 사전점검 passed를 확인했다. scope는 camera_device_delete_preflight이며 서비스 재시작·DB 스키마 변경·장치 삭제 활성화는 수행하지 않았다.

| 항목 | 확인 결과 |
|---|---|
| 운영 프로젝트 / 엔드포인트 | vms-project / http://127.0.0.1:18081 |
| 운영 API / 스키마 | 0.6.0-source-delete / 6 |
| 목표 API / 스키마 | 0.7.0-device-delete / 7 |
| 목표 삭제 정책 | registry-only-v1 |
| 실행 OpenAPI | 기존 버전·장치 GET/PATCH·소스 DELETE 일치 |
| 등록·요청 이력 건수 | devices, device_requests, video_sources, stream_profiles, source_requests, device_update_requests, source_update_requests, source_delete_requests 모두 0 |
| DB 크기 | 8,091,315 bytes |
| 호스트 백업 여유 / 최소 기준 | 221,574,402,048 / 67,108,864 bytes |
| 점검 보고서 | var/camera/device-delete-preflight.json |

기존 스키마 6 runtime 역할의 schema USAGE·마이그레이션 SELECT·등록/기록 SELECT/INSERT·장치/소스 수정 열 권한이 일치한다. schema CREATE·장치 deleted_at UPDATE·테이블 전체 변경·불변 열 UPDATE 권한은 없다. 운영 camera 이미지는 `sha256:b104c902592bf67b025b9463e9fcbb8c964281d5162c21e69f9db41d2d9c45f8`, PostgreSQL 이미지는 `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`이다.

이 인수로 [10-D1 기록](20261002-step10d1-device-delete-preflight.md)의 서버 점검 대기가 해소됐다. 운영 전환 완료를 의미하지 않는다. 이번 도구는 실행 시 현재 상태를 다시 점검하며 문서에 적힌 이미지 ID를 하드코딩하지 않는다.

## 이번 범위

한 번에 독립적으로 검토 가능한 단위 하나를 진행한다는 AGENTS.md·작업 기준에 따라, 이번 패치는 리허설 도구·해당 Python 검사·이 기록의 3개 파일만 추가한다. 기존 파일·10-C 프로젝트 명세·10-D1 점검 도구를 보존한다. 새 파일은 패치 명세와 리허설 recipe 해시로 식별한다. 기존 명세의 전달 당시 검증 표시는 보존하고 이후 서버 인수는 진행 기록에서 구분한다.

새 `src/infra/tools/test_camera_device_delete_upgrade.py`는 운영에 읽기 전용 사전점검을 다시 수행한다. 임의의 `vms-device-delete-test-` 프로젝트와 별도 임시 작업 공간·DB 볼륨·비밀값·localhost 포트를 만든다. 현재 운영의 정확한 camera/DB 이미지 ID로 이전 상태를 구성하고, 복사한 검증 코드에서 후보 이미지를 빌드한다. 운영 토큰·DSN·등록 데이터를 시험 공간으로 복사하지 않는다.

운영 Docker 접근은 10-D1 InspectionDocker가 허용한 조회에 한정한다. 시험 핸들은 운영 프로젝트명·운영 폴더·그 하위 폴더를 거부한다. 시험 프로젝트/네트워크/볼륨/후보 이미지 태그 충돌과 데몬 변경을 확인하기 전에는 정리 명령도 실행하지 않는다. DB 포트 비공개·내부 네트워크·별도 복원 DSN/API 포트를 확인한다. 이 단위에 운영 활성화 도구는 포함하지 않는다.

## 리허설에서 확인하는 순서

1. 이전 이미지로 임시 스키마 6을 만들고 이력 0001~0006·runtime 최소 권한을 확인한다. 대상 장치 생성/수정, 활성 자식 소스 2개와 수정 이력, 이전 버전에서 이미 삭제한 소스/성공 기록, 별도 보존 장치/소스를 만든다. 전환 전 응답과 장치/소스 cursor를 보관한다.
2. 시험 API를 정지하고 DB 클라이언트가 없는지 확인한 뒤 시험 DB를 백업한다. 후보 이미지로 스키마 7을 적용/재적용한다. 이력 이름·체크섬·적용 건수 1/0·새 삭제 기록 테이블·runtime 최소 권한을 확인하고 기존 8개 업무 테이블의 전체 행을 비교한다.
3. 후보 API 0.7.0-device-delete·P1_DEVICE_DELETE와 전체 capability가 검토한 등록 전용 전제에 일치해야 한다. 기존 장치/소스 POST/PATCH와 이전 소스 DELETE의 결과를 재생하고 cursor를 확인한다. 전환 후 장치/소스 수정 및 별도 새 장치/소스 등록도 수행한다.
4. 오래된 장치 버전은 DEVICE_VERSION_CONFLICT, 활성 자식이 있으면 DEVICE_HAS_ACTIVE_SOURCES여야 한다. 실패 전후 9개 테이블을 비교한다. 자식 소스 하나를 삭제한 뒤 같은 장치 삭제 키로 재시도해 여전히 거부되는지 확인한다. 나머지 자식도 삭제한 후 같은 키로 부모를 삭제한다. POST/PATCH/DELETE는 같은 키를 쓰되 성공 기록의 범위가 독립적이어야 한다.
5. 소스 삭제는 대상 소스 2개의 version/updated_at/deleted_at와 새 성공 기록 외에는 전체 행이 유지돼야 한다. 장치 삭제는 대상 장치의 같은 3개 열과 새 장치 삭제 성공 기록 외에는 소스 tombstone·프로필·기존 모든 성공 기록·보존 장치/소스가 그대로여야 한다. 최소 삭제 응답·버전 증가·UTC 시간·DB deleted_at=updated_at·장치 성공 기록 1건/소스 기록 3건을 확인한다.
6. 동일 DELETE는 같은 삭제 영수증과 새 request_id를 반환해야 한다. 다른 내용의 같은 장치 키는 409, 삭제 후 새 DELETE/PATCH/GET은 404다. 과거 장치/소스 POST/PATCH와 소스 DELETE 재생이 대상/부모를 복원하지 않아야 한다. 장치 ID 재사용·삭제 부모의 새 소스 생성도 거부하며 실패/재생으로 행이 변하지 않아야 한다.
7. 후보 API를 재생성하고 장치/소스 삭제·모든 과거 응답·보존/전환 후 등록 데이터를 확인한다. 장치/소스 목록에서 삭제 대상은 제외되고 삭제 전 장치 cursor는 유효하며 삭제 부모의 소스 필터/cursor는 빈 목록이어야 한다.
8. 백업을 시험 DB 컨테이너의 별도 vms_camera_restore DB에 복원한다. 스키마 6 이력·권한·백업 전 8개 테이블의 전체 행을 비교한다. 이전 API로 장치/소스 조회·POST/PATCH·소스 DELETE 과거 결과와 cursor를 확인한다. 이전 API의 장치 DELETE는 405·Allow=GET,PATCH이며 전환 후 등록 데이터는 복원 DB에 없어야 한다.
9. 계속 실행 중인 스키마 7 DB의 장치/소스 삭제·과거 이력·전환 후 데이터를 다시 확인한다. 9개 테이블이 복원 전과 동일해야 한다. 백업 해시, 시험 DB 컨테이너와 다른 플랫폼 역할의 임시 sentinel 컨테이너 3개도 유지돼야 한다.

전체 행 비교는 합성 시험 데이터만 대상으로 한다. 삭제 대상의 3개 열만 정확한 ID 조건에서 정규화한다. 다른 장치·소스·프로필·이전 삭제 기록은 제외하지 않는다. runtime은 테이블 SELECT/INSERT와 명시한 장치/소스 수정 열만 허용하며 테이블 전체 변경·프로필/기록 열 UPDATE·관리자/replication/RLS 우회 권한을 거부한다. 별도 복원 DB의 스키마 6에서는 장치 deleted_at UPDATE 권한이 없어야 한다.

이번 검사는 외부 미디어 사용을 탐지하지 않으며 실장비·영상·추론·세션·소비자 런타임을 구현하거나 검증하지 않는다. registry-only-v1은 이미 인수한 코드와 capability의 등록 전용 전제를 확인한다.

## 결과·정리·실패 처리

정상 종료와 시험 중 예외/사용자 중단 시 이번 임의 프로젝트의 컨테이너·볼륨·네트워크를 정리하고 실제 제거를 조회한다. 정리 실패 시 bound secret이 필요한 시험 공간을 보존하고 경로를 표시한다. 충돌한 기존 프로젝트는 정리하지 않는다. 후보 이미지는 후속 전환 단계의 검증 기준으로 유지한다.

운영 환경·비밀·컨테이너·09 완료 기록·코드·점검 도구·리허설 recipe가 실행 전후 동일해야 성공한다. 운영 쓰기는 계속 가능하므로 정상 요청으로 건수가 달라지는 것만으로 실패하지 않는다. 운영 서비스 정지·재시작·마이그레이션·복원은 수행하지 않으며 운영 DB를 자동 복원하지 않는다.

공유 잠금 아래 `var/camera/device-delete-upgrade-check.json`을 0600으로 기록한다. 실행 시 이전 결과를 running으로 바꾸고 실패/중단 시 failed로 무효화한다. 공개 출력은 비밀·환경 해시·데몬 식별자·recipe 해시를 제외한다. 실패 진단은 고정 코드·예외 종류·Python 버전·허용된 도구의 함수/행 번호로 제한하며 예외 원문·토큰·DSN·HTTP 응답은 출력하지 않는다. 리허설 도구는 적용 인자를 받지 않는다.

## 로컬 검증과 한계

- Python 단위 검사 48개 통과. 격리 경계·이미지/프로젝트 충돌·데몬 변경·중단/정리 실패, 스키마 6/7·권한·capability, 최소 장치/소스 삭제 영수증·새 요청 ID·오류 헤더·과거 응답·목록/cursor, 시간/버전·행 비교 범위, 보고서 무효화·비밀 제외·적용 인자 차단을 확인했다.
- 모의 IO로 전체 스키마 6 준비 → 이전 소스 삭제 이력 → 백업 → 7 적용/재적용 → 활성 자식 거부/삭제 → 부모 삭제/재생 → API 재생성 → 별도 스키마 6 복원 순서를 실행했다. 마이그레이션 행 변조·자식 삭제 중 프로필 변조·부모 삭제 중 자식 변조·실패 키의 성공 기록 저장·재생 중 행 변경·잘못된 복원·복원으로 새 DB가 되돌려지는 7가지 오류에서 성공 보고를 차단했다.
- 임시 PostgreSQL 18.3(PGlite 0.5.8)에서 도구의 실제 SQL을 실행했다. 스키마 6/7 이력·체크섬·기존 8개 행 집계 해시 보존, 새 기록 포함 9개 테이블 해시, 정확한 장치/소스 tombstone 열 정규화와 다른 소스/프로필/장치 변경 탐지, 역할/최소 권한·장치 삭제 기록 INSERT/열 UPDATE 회수·프로필/기록 열 UPDATE 확장·테이블 DELETE 확장 거부를 확인했다. native 역할 인증·Docker 이미지·pg_dump/pg_restore 통과로 계산하지 않는다.
- Python 3.10 문법과 실제 10-C 프로젝트 명세/해시를 확인했다. 패치 적용 도구 검사 8개, 전체 패키지 3개 파일 적용/재적용·기준 충돌 시 사전 중단, payload/압축본 경로/해시와 기존 245개 파일·환경·운영 기록 보존을 확인했다.

현재 작성 환경에는 Docker 실행 환경이 없어 실제 후보 이미지 빌드·이전 운영 이미지 실행·native PostgreSQL 17 백업/복원을 수행하지 않았다. 서버 실행 결과로 인수한다. Go/HTTP/마이그레이션·운영 구성을 변경하지 않았으므로 서버에서 이미 통과한 전체 Go/race/vet/smoke 검사를 반복하지 않았다.

## 서버 인수와 다음 단위

서버 성공 기준은 status=passed·scope=camera_device_delete_upgrade_native_docker·previous_schema_version=6·schema_version=7·usage_policy=registry-only-v1이다. 다음 17개 검증 필드가 모두 true여야 한다.

| 구분 | 검증 필드 |
|---|---|
| 전환/권한 | schema_upgrade_verified, runtime_grants_verified |
| 과거 성공 결과 | device_and_source_replay_verified, device_update_replay_verified, source_update_replay_verified, source_delete_replay_verified, device_delete_replay_verified |
| 삭제/목록 | active_children_rejection_verified, deletion_rows_preserved, registry_only_policy_verified, device_and_source_list_preserved |
| 재시작/복원 | api_recreation_verified, schema_6_restore_verified, old_api_on_restored_database_verified, post_upgrade_data_preserved |
| 보호 대상 | protected_sentinels_unchanged, isolated_database_unchanged |

production_services_modified=false·device_delete_activated=false·isolated_resources_removed=true·automatic_production_database_restore=false를 확인하고 후보 이미지 ID와 recipe를 다음 단계의 기준으로 삼는다. 이 단계 이후에도 운영 API는 0.6.0-source-delete·스키마 6이며 업무 런타임 준비 완료가 아니다.

통과 후 다음 단위는 **10-D3: 검증된 장치 삭제 이미지·스키마 7 운영 전환 준비**다. 성공 보고서·현재 운영 상태를 다시 확인하고 정지·백업·전환·인수 도구를 별도 단계로 전달한다. 스키마 6 이미지로만 되돌리는 복귀나 자동 운영 DB 복원은 가정하지 않는다. 적용·실행 명령은 채팅으로만 제공한다.
