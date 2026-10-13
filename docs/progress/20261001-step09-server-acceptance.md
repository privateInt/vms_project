# 단위 09 — 소스 논리 삭제 서버 인수 완료

작성일: 2026-10-01 · 운영 전환 인수 완료 · 완료 기록의 서버 반영은 이 문서 패치로 진행

## 인수 근거

사용자가 제공한 09-D3 서버 실행 로그에서 패치 파일 3개 적용, 활성화 도구 단위 검사 31개 통과(1.552초), 운영 전환 성공을 확인했다. 파일 패치 백업은 `var/patch-backups/step09d3-tsymmssy`다. 파일 적용 자체는 서비스 작업을 수행하지 않았고, 이어 실행한 활성화 도구가 camera API 정지·운영 DB 백업·스키마 6 적용·검증된 후보 이미지 시작을 수행했다.

| 항목 | 서버 결과 |
|---|---|
| 상태 / 단계 | activated / completed |
| 범위 / 프로젝트 | camera_source_delete / vms-project |
| API 주소 | http://127.0.0.1:18081 |
| 소스 삭제 활성화 | source_delete_activated=true |
| 스키마 / 이번 마이그레이션 | schema_version=6 / migration_applied=1 |
| 삭제 정책 | usage_policy=registry-only-v1 |
| camera API 재시작 | service_restart_performed=true |
| DB 컨테이너 / 다른 서비스 | database_container_unchanged=true / other_services_unchanged=true |
| 자동 DB 복원 | automatic_database_restore=false |
| 영상 업무 런타임 | business_runtime_ready=false |

활성화 도구의 버전·전체 capability 검사까지 통과한 운영 API는 `0.6.0-source-delete`, 단계는 `P1_SOURCE_DELETE`다. 현재 이미지 조합은 09-D2에서 실제 Docker 리허설을 통과한 조합과 일치한다.

- 현재 camera 이미지: `sha256:b104c902592bf67b025b9463e9fcbb8c964281d5162c21e69f9db41d2d9c45f8`
- 이전 camera 이미지: `sha256:6c10ff4314892d952933d457e9dee6ddaf0126aadc551c9bb07813f5344915dd`
- DB 이미지: `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`

`counts_before`는 devices, device_requests, video_sources, stream_profiles, source_requests, device_update_requests, source_update_requests 모두 0이었다. 이는 API 정지 후 확인한 전환 전 건수다. 전환 후 또는 문서를 읽는 시점의 운영 건수로 해석하지 않는다.

## 백업과 운영 기록

전환 기록 디렉터리는 `/home/shshin/workspace/vms_project/var/camera/source-delete-activation-backups/step09d3-tr0atqek`다. 기존 환경·컨테이너 상태와 결과 기록을 보관하고, 전환 직전 스키마 5의 운영 DB 덤프를 생성했다.

- DB 백업: `/home/shshin/workspace/vms_project/var/camera/source-delete-activation-backups/step09d3-tr0atqek/camera.pgdump`
- 백업 SHA-256: `283a31dac21c8e6c9ff0ef40d49df13c2326a5e6aa53a8623dfbe445fc5aeed8`
- 운영 활성화 보고서: `var/camera/source-delete-activation.json`
- 격리 리허설 보고서: `var/camera/source-delete-upgrade-check.json`

경로·해시·전환 성공은 사용자 실행 로그에 근거한다. 이번 문서 작업에서 서버나 백업 파일을 직접 조회·복원하지 않았다. 이 덤프는 전환 전 백업이며 스키마 6에서 이후 접수한 데이터까지 포함하는 최신 백업은 아니다. 이전 단계의 백업·활성화 기록도 유지한다.

## 완료한 기능

`DELETE /api/v1/sources/{source_id}`로 영상 소스 등록을 논리 삭제할 수 있다. Bearer 인증, 필수 Idempotency-Key와 JSON 본문의 schema_version·expected_version을 사용한다. 새 성공 시 소스 version을 1 증가시키고 deleted_at=updated_at을 같은 트랜잭션에서 성공 기록과 함께 저장한다. UTC 삭제 시각은 직전 updated_at보다 과거가 될 수 없다.

소스 행·프로필·ID/장치 채널 예약·기존 POST/PATCH 성공 이력, 부모 장치·형제 소스를 보존한다. 삭제된 소스는 GET에서 404, 일반 목록에서 제외된다. 삭제 전 cursor도 기존 ID 이후 탐색 규칙을 유지한다. 이 기능은 물리 삭제·복원·녹화 정리를 수행하지 않는다.

같은 성공 키와 본문은 최초 삭제 결과를 200으로 재생하고 version·시각을 다시 변경하지 않는다. 같은 성공 키의 다른 본문은 409 IDEMPOTENCY_CONFLICT다. 삭제 후 다른 키의 새 DELETE/PATCH는 404다. 과거 POST/PATCH 성공 요청은 당시 스냅샷을 재생하지만 소스를 되살리지 않는다. 현재 존재 여부는 GET/목록으로 판단한다.

현재 허용 범위는 **등록 전용 릴리스**다. SourceSession·소비자·입력 어댑터 생성 기능이 없는 코드·구성 전제를 registry-only-v1 및 고정 capability 목록으로 검사한다. 이 정책은 외부 카메라의 미디어 사용을 탐지하는 기능이 아니다. 향후 세션·소비자·어댑터를 도입하려면 삭제와 새 사용 시작이 같은 소스 잠금 또는 동등한 원자적 사용 허용 절차를 공유하도록 먼저 구현해야 한다. 확인 불가 상태에서 임의로 삭제를 허용하지 않는다.

## 검증 범위

- **09-A~C 계약·저장소·HTTP:** 엄격한 요청·오류 순서, 스키마 6의 source_delete_requests와 제한된 runtime 권한, 원자적 삭제·성공 이력·실패 롤백·삭제/수정 경쟁, 등록 전용 정책과 HTTP 경로를 구현했다. PostgreSQL 17.11의 실제 서버 HTTP/권한/동시성 검사 인수는 09-D1 기록을 따른다.
- **09-D1 사전점검:** 당시 운영 API 0.5.0-source-update·스키마 5, 이미지·역할·비밀·컨테이너·capability·백업 공간 조건을 확인했다. 성공 인수는 09-D2 기록에 있다.
- **09-D2 이미지 리허설:** 서버 단위 검사 43개 및 별도 Docker 프로젝트의 스키마 5→6 전환·재적용·runtime 권한·삭제/기존 이력 재생·보호 행과 목록/cursor 보존·API 재생성이 통과했다. 별도 시험 DB의 스키마 5 복원과 이전 API, 스키마 6의 전환 후 데이터 보존, 시험 DB/보호 컨테이너 보존·임시 리소스 정리도 통과했다. 상세 결과는 09-D3 준비 기록에 있다.
- **09-D3 운영 전환:** 리허설·코드·이미지 일치를 재확인하고 운영 백업 후 마이그레이션 1건을 적용했다. 새 API의 readiness·버전·등록 전용 capability·기존 목록 GET, 스키마·권한·기존 7개 테이블 건수, DB 컨테이너와 다른 서비스 보존 조건을 통과했다. 운영 인수용 HTTP 요청은 GET만 사용했고 시험용 등록·수정·삭제 요청을 만들지 않았다.

이번 사용자 로그는 최초 전환의 activated다. 운영 재실행의 already_activated 결과를 받은 것으로 기록하지 않는다. 재실행·실패·중단 동작은 전환 도구 검사로 검증했으며 운영 장애를 일부러 유발하지 않았다.

스키마 5 복원 검증은 09-D2의 별도 시험 DB에서 수행했다. 이번에 생성한 운영 백업을 실제 복원했다는 뜻은 아니다. 마이그레이션 요청 이후에는 후보 이미지·DB·비밀·백업을 보존하며, 이전 이미지로만 되돌리거나 운영 DB를 자동 복원하지 않는다.

## 현재 기준과 이번 문서 패치

단위 09의 소스 논리 삭제 계약·저장소·HTTP 구현·격리 검사·이미지 리허설·운영 전환을 완료했다. 기존 문서의 운영 0.5.0·스키마 5, DELETE 미활성, 서버 결과 대기는 해당 문서 작성 당시 상태다. 현재 인수 기준은 이 기록과 서버의 09-D3 활성화 결과다.

이번 패치는 이 문서 한 파일만 추가한다. 기존 코드·계약·진행 기록·도구·프로젝트 명세와 리허설 recipe의 바이트/해시를 유지한다. 적용·재적용·충돌 시 사전 중단, 압축본 경로/해시와 기존 파일·환경·운영 기록 보존을 확인했다. 제품 테스트·이미지 빌드·서비스 재시작·마이그레이션은 반복하지 않았다. 완료 기록 패치의 서버 적용 결과는 아직 받기 전이다.

## 남은 범위와 다음 작은 단위

현재 운영은 장치와 소스의 등록·단건/목록 조회·표시 이름 수정 및 소스 논리 삭제를 지원한다. 장치 삭제, 접속 설정·자격증명 관리, SourceSession, 실제 RTSP/XR 수신·영상 분석·UI는 완료 범위가 아니다. business_runtime_ready=false를 유지한다.

다음 작은 단위로 **10-A: 장치 논리 삭제 계약**을 제안한다. 장치 version·멱등 요청, 활성/삭제된 자식 소스의 처리 기준, 부모 삭제와 새 소스 생성의 경쟁 보호, 장치·소스·프로필·과거 응답 보존, ID 재사용 제한과 오류를 먼저 확정하는 것이 완료 기준이다. 강제 연쇄 삭제를 기본으로 가정하지 않는다. 저장소·HTTP 구현·운영 전환은 각각 후속 단위로 분리하며 이번 문서 패치에서는 시작하지 않는다.

참고: [09-D3 전환 도구와 리허설 인수](20261001-step09d3-source-delete-activation.md), [09-D2 리허설](20261001-step09d2-source-delete-rehearsal.md), [09-D1과 HTTP 서버 인수](20261001-step09d1-source-delete-preflight.md), [소스 삭제 계약](../contracts/camera-source-delete.md), [등록·변경·삭제 순서](../contracts/camera-registry.md), [작업 원칙](../development/working-standards.md).
