# 단위 09-D2 — 소스 삭제 업그레이드·복구 격리 리허설

작성일: 2026-10-01 · 도구·로컬 검증 완료 · 서버 Docker 리허설 결과 대기

## 09-D1 서버 결과 인수

사용자 로그에서 09-D1 패치 applied/written=3, 백업 `var/patch-backups/step09d1-mru6jzkl`과 사전점검 passed를 확인했다. scope는 camera_source_delete_preflight이며 운영 서비스 변경·소스 삭제 활성화는 수행하지 않았다.

| 항목 | 확인 결과 |
|---|---|
| 운영 프로젝트 / 엔드포인트 | vms-project / http://127.0.0.1:18081 |
| 운영 API / 스키마 | 0.5.0-source-update / 5 |
| 목표 API / 스키마 | 0.6.0-source-delete / 6 |
| 목표 삭제 정책 | registry-only-v1 |
| 등록·요청 이력 건수 | devices, device_requests, video_sources, stream_profiles, source_requests, device_update_requests, source_update_requests 모두 0 |
| DB 크기 | 8,025,779 bytes |
| 호스트 백업 여유 / 최소 기준 | 220,907,761,664 / 67,108,864 bytes |
| 점검 보고서 | var/camera/source-delete-preflight.json |

운영 camera 이미지는 `sha256:6c10ff4314892d952933d457e9dee6ddaf0126aadc551c9bb07813f5344915dd`, PostgreSQL 이미지는 `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`이다. 이 인수로 [09-D1 기록](20261001-step09d1-source-delete-preflight.md)의 서버 점검 대기가 해소됐다. 운영 전환 완료를 의미하지 않는다.

## 이번 범위

한 번에 검토 가능한 작업 단위 하나를 진행한다는 `AGENTS.md`와 작업 기준에 따라, 이번에는 09-D2 도구·검사·이 기록의 3개 파일만 추가한다. 기존 코드·프로젝트 명세·09-D1 도구를 변경하지 않는다. 실행 시 프로젝트 명세와 모든 등록 파일의 해시를 검사하고, 명세 밖의 신규 도구는 패치 명세와 리허설 recipe 해시로 식별한다.

새 도구 `src/infra/tools/test_camera_source_delete_upgrade.py`는 운영에 읽기 전용 사전점검을 다시 수행한다. 임의의 `vms-source-delete-test-` 프로젝트와 별도 임시 작업 공간·DB 볼륨·비밀값·localhost 포트를 만든다. 현재 운영의 정확한 camera/DB 이미지 ID를 기준으로 이전 상태를 구성하고, 복사한 검증 코드에서 후보 이미지를 빌드한다. 운영 토큰·DSN·데이터를 시험 공간으로 복사하지 않는다.

운영 접근은 기존 InspectionDocker의 허용된 조회에 한정한다. 시험용 Docker 핸들은 운영 프로젝트명과 운영 폴더·하위 폴더를 거부한다. 시험 프로젝트명 충돌·데몬 변경을 확인하기 전에는 정리 명령도 실행하지 않는다. DB 포트 비공개·내부 네트워크, 별도 복원 DSN과 API 포트를 검사한다.

## 리허설에서 확인하는 순서

1. 이전 이미지로 임시 스키마 5를 만들고 장치 생성·수정, 소스 생성·수정, 형제 소스를 기록한다. 전환 전 POST/PATCH 응답과 cursor를 보관한다.
2. 시험 API를 정지하고 DB 클라이언트가 없는지 확인한 뒤 시험 DB를 백업한다. 후보 이미지로 스키마 6을 적용·재적용하고 마이그레이션 이름·체크섬·적용 건수와 runtime 최소 권한을 확인한다. 기존 7개 업무 테이블의 모든 행이 그대로인지 비교한다.
3. 후보 API의 버전·전체 capability가 등록 전용 전제와 일치하는지 확인한다. 이전 생성·수정 이력을 재실행하고 전환 후 장치·소스 수정 및 새 소스 등록을 수행한다.
4. 오래된 버전의 DELETE 거부와 무변경을 확인한다. 동일 키를 POST/PATCH/DELETE에 사용해 요청 범위 독립성을 검사한다. 최초 삭제는 최소 응답·버전 증가·UTC 시간·DB deleted_at=updated_at·성공 기록 한 건을 확인한다.
5. 삭제 대상의 version/updated_at/deleted_at 외에는 전체 행이 유지되어야 한다. 프로필·장치·형제 소스와 기존 성공 이력을 비교한다. 동일 DELETE 재실행은 같은 삭제 결과와 새 요청 ID를 반환해야 한다. 다른 내용의 동일 키는 409, 삭제 후 새 DELETE/PATCH와 GET은 404여야 한다. 과거 POST/PATCH 성공 결과 재실행은 삭제된 소스를 되살리지 않아야 한다.
6. 후보 API 컨테이너를 재생성해 삭제·과거 이력의 지속성을 확인한다. 목록·장치 필터에서 삭제 소스가 제외되고 삭제 전 cursor가 유효한지, 부모·형제·전환 후 등록 데이터가 유지되는지 확인한다.
7. 백업을 같은 시험 DB 컨테이너의 별도 `vms_camera_restore` DB에 복원한다. 스키마 5와 백업 전 모든 업무 행을 비교하고 이전 API로 조회·과거 응답 재실행을 확인한다. 이전 API의 DELETE는 405이며 전환 후 데이터는 복원 DB에 없어야 한다.
8. 스키마 6 시험 DB의 삭제 기록·전환 후 데이터가 복원 시험 전과 동일한지 다시 비교한다. 백업 파일 해시, 시험 DB 컨테이너와 다른 플랫폼 역할의 임시 sentinel 컨테이너도 보존되어야 한다.

전체 행 비교는 시험 데이터만 대상으로 한다. 이번 검사는 외부 미디어 사용을 탐지하지 않으며 실장비·영상·추론·세션·소비자 런타임을 구현하거나 검증하지 않는다. 09-C에서 검증한 등록 전용 정책과 capability 전제를 확인한다.

## 결과·정리·실패 처리

정상 종료와 시험 중 예외·사용자 중단 시 임의 시험 프로젝트의 컨테이너·볼륨·네트워크를 정리한다. 정리 실패 시 bound secret이 필요한 시험 작업 공간을 보존하고 경로를 표시한다. 기존 프로젝트와 충돌한 경우 기존 리소스를 정리하지 않는다. 후보 이미지는 후속 전환 단계에서 사용할 수 있도록 유지한다.

운영 환경·비밀·컨테이너·완료 기록·코드·도구 recipe가 검사 전후 동일해야 성공한다. 운영 쓰기는 계속 가능하므로 정상 요청에 따른 건수 변화만으로 실패하지 않는다. 운영 서비스 정지·재시작·마이그레이션·복원은 없다. 운영 DB의 자동 복원도 수행하지 않는다.

기존 도구와 공유하는 잠금 아래 `var/camera/source-delete-upgrade-check.json`을 0600으로 기록한다. 실행 시 이전 결과를 running으로 바꾸고 실패·중단 시 failed로 무효화한다. 공개 출력은 비밀·환경 해시·데몬 식별자를 제외한다. 실패 원인은 고정 코드·예외 종류·Python 버전·허용된 도구의 함수/행 번호로 제한하고 예외 원문·토큰·DSN은 출력하지 않는다.

## 로컬 검증과 한계

- Python 3.12.14에서 단위 검사 43개 통과. 격리 경계·충돌/중단/정리 실패, 스키마·권한·capability, 응답/오류 헤더와 과거 스냅샷, 삭제 결과·시간·버전·행 비교 범위, 보고서 무효화·비밀 제외를 확인했다.
- 모의 IO로 전체 리허설의 스키마 5 준비 → 백업 → 6 적용/재적용 → 별도 DB 복원 순서를 실행했다. 마이그레이션 행 변조, 삭제 중 프로필 등 보호 행 변조, 잘못된 복원, 복원으로 새 DB가 되돌려지는 상황에서 성공 보고를 차단하는지 확인했다. 모의 검사는 실제 Docker/PostgreSQL 통과를 대체하지 않는다.
- Python 3.10 문법으로 파싱했다. 시간 비교는 기존 수정에서 검증한 RFC3339Nano 파서를 사용하며 `fromisoformat`의 Python 버전별 Z 처리에 의존하지 않는다. 서버 Python 3.10.19에서의 실행은 아래 서버 인수로 확정한다.
- 패치 사전점검·3개 파일 적용·재적용 무변경·충돌 시 사전 중단, 압축본 경로/해시, 기존 프로젝트 명세·파일·환경·운영 완료 기록 보존을 확인했다.

현재 작성 환경에는 Docker/PostgreSQL 실행 환경이 없어 실제 후보 이미지 빌드·마이그레이션 SQL·HTTP·백업/복원을 실행하지 않았다. 운영 서버의 다음 실행 결과가 필요하다. Go/HTTP/DB 구현을 변경하지 않았으므로 기존 전체 Go/vet/smoke 검사는 반복하지 않았다.

## 서버 인수와 다음 단위

서버 성공 기준은 status=passed, scope=camera_source_delete_upgrade_native_docker, schema_version=6, usage_policy=registry-only-v1이다. schema_upgrade_verified, runtime_grants_verified, device_and_source_replay_verified, device_update_replay_verified, source_update_replay_verified, source_delete_replay_verified, deletion_rows_preserved, registry_only_policy_verified, source_list_preserved, api_recreation_verified, schema_5_restore_verified, old_api_on_restored_database_verified, post_upgrade_data_preserved, protected_sentinels_unchanged, isolated_database_unchanged가 모두 true여야 한다.

production_services_modified=false, source_delete_activated=false, isolated_resources_removed=true, automatic_production_database_restore=false를 확인하고 후보 이미지 ID를 다음 단계 기준으로 삼는다. 이 단계 이후에도 운영 API는 0.5.0-source-update·스키마 5이며 업무 런타임 준비 완료가 아니다.

통과 후 다음 단위는 **09-D3: 검증된 소스 삭제 이미지·스키마 6 운영 전환 준비**다. 성공 보고서·현재 운영 상태를 다시 확인하고 기존 패턴에 따른 정지·백업·전환·인수 도구를 별도 단계로 전달한다. 이번 패치에 활성화 도구를 포함하지 않는다. 적용·실행 명령은 채팅에서 제공한다.
