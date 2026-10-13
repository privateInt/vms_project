# 단위 10 — 장치 논리 삭제 서버 인수 완료

작성일: 2026-10-02 · 운영 최초 전환·성공 재실행 인수 완료 · 완료 기록의 서버 반영은 이 문서 패치로 진행

## 인수 근거

사용자가 제공한 simsys4090 서버 로그에서 10-D3 파일 패치 applied·written=3·pending=0, 이어 실행한 운영 전환 activated·completed와 두 번째 실행 already_activated를 확인했다. 파일 패치 백업은 `var/patch-backups/step10d3-z97em5a8`이다. 파일 적용 자체는 서비스·DB를 바꾸지 않았고, 전환 도구가 camera API 정지·스키마 6 DB 백업·스키마 7 적용·검증된 후보 API 시작을 수행했다.

| 항목 | 최초 전환 | 두 번째 실행 |
|---|---|---|
| status / stage | activated / completed | already_activated / completed |
| scope / project | camera_device_delete / vms-project | 동일 |
| API 주소 | http://127.0.0.1:18081 | 동일 |
| 스키마 / 최초 적용 마이그레이션 | schema_version=7 / migration_applied=1 | 완료 기록의 값을 반환 |
| 장치 삭제 활성화 | device_delete_activated=true | true |
| camera API 재시작 | service_restart_performed=true | false |
| DB 컨테이너 / 다른 서비스 보존 | database_container_unchanged=true / other_services_unchanged=true | 동일 완료 기록 |
| 기존 행 보존 / 전환 당시 새 삭제 기록 비어 있음 | existing_rows_preserved=true / new_device_delete_journal_empty_at_cutover=true | 동일 완료 기록 |
| 삭제 정책 | usage_policy=registry-only-v1 | 동일 |
| 자동 DB 복원 / 영상 업무 런타임 준비 | automatic_database_restore=false / business_runtime_ready=false | 동일 |

최초 성공 전에 전환 도구의 readiness·버전·전체 capability·장치/소스 목록·실행 OpenAPI 검사가 수행됐다. 따라서 인수한 운영 API는 **0.7.0-device-delete·P1_DEVICE_DELETE·스키마 7**이다. 후보 이미지는 10-D2 실제 Docker 리허설과 일치한다.

- 현재 camera 이미지: `sha256:708d5a53f3dcc3d22dca775ef2825bcd271a68c7c3777cf8a6a89bb6933aa7d6`
- 이전 camera 이미지: `sha256:b104c902592bf67b025b9463e9fcbb8c964281d5162c21e69f9db41d2d9c45f8`
- DB 이미지: `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`

`counts_before`의 devices·device_requests·video_sources·stream_profiles·source_requests·device_update_requests·source_update_requests·source_delete_requests는 모두 0이었다. 이는 API 정지 후 읽은 전환 전 건수이며 이후 운영 건수를 의미하지 않는다. 운영에서 기존 업무 행이 있는 상태의 보존을 시험한 것으로 확대하지 않는다. 데이터가 있는 전환·과거 성공 이력 보존 검증은 10-D2의 격리 시험 결과를 따른다.

두 번째 실행은 현재 이미지·스키마·권한·읽기 API·DB health/영속 볼륨·비밀 마운트와 코드/보고서 일치를 다시 검사하고 성공했다. 백업·마이그레이션·서비스 재시작·완료 기록 재작성을 수행하지 않았다. 출력의 migration_applied=1은 최초 전환의 저장된 값이며 두 번째 마이그레이션 1건을 뜻하지 않는다. 보존·전환 당시 빈 기록 필드도 최초 전환 결과다. 재실행은 정상 운영에서 추가된 등록·삭제 데이터를 허용한다.

## 백업과 운영 기록

전환 기록 디렉터리는 `/home/shshin/workspace/vms_project/var/camera/device-delete-activation-backups/step10d3-98wucmwh`다. 기존 환경·컨테이너 상태·결과와 전환 직전 스키마 6의 운영 DB 덤프를 보관한다.

- DB 백업: `/home/shshin/workspace/vms_project/var/camera/device-delete-activation-backups/step10d3-98wucmwh/camera.pgdump`
- 백업 SHA-256: `b5942e0756c46e766a3fa6473cb2b63add1502424663dfa4b8697a8c7243f7d1`
- 운영 활성화 보고서: `var/camera/device-delete-activation.json`
- 격리 리허설 보고서: `var/camera/device-delete-upgrade-check.json`
- 사전점검 보고서: `var/camera/device-delete-preflight.json`

경로·해시·성공 상태는 사용자 실행 로그에 근거한다. 이번 문서 작업은 서버나 백업 파일을 직접 조회·복원하지 않았다. 전환 도구는 custom-format 덤프 형식·pg_restore 목록·SHA-256을 확인했다. 이 덤프는 전환 전 스키마 6 백업이며 스키마 7에서 이후 접수한 데이터를 포함하는 최신 백업은 아니다. 이전 단계의 백업과 완료 기록도 유지한다.

스키마 6 복원·이전 API 동작은 10-D2의 별도 시험 DB에서 검증했다. 이번 운영 덤프를 실제 복원했다는 뜻은 아니다. 마이그레이션 요청 이후에는 실패/중단 시에도 후보 이미지 설정·DB·비밀·백업을 유지하며 이전 이미지를 자동 시작하거나 운영 DB를 자동 복원하지 않는다.

## 완료한 기능

`DELETE /api/v1/devices/{device_id}`는 등록 장치를 논리 삭제한다. Bearer 인증·필수 Idempotency-Key·JSON 본문의 schema_version 및 expected_version을 사용한다. 성공 시 version을 정확히 1 증가시키고 deleted_at=updated_at을 같은 트랜잭션에서 삭제 성공 기록과 함께 저장한다. 삭제 시각은 직전 updated_at보다 과거로 내려가지 않는다.

미삭제 자식 소스가 있으면 DEVICE_HAS_ACTIVE_SOURCES로 거부한다. 자식 삭제를 자동 수행하지 않는다. 모든 자식이 삭제된 뒤 같은 실패 키·본문으로 부모 삭제를 재시도할 수 있다. 장치 삭제와 새 소스 등록은 같은 장치별 트랜잭션 잠금을 사용한다. 소스 등록이 먼저 성공하면 부모 삭제를 거부하고, 부모 삭제가 먼저 성공하면 새 소스 등록은 DEVICE_UNAVAILABLE이며 소스·프로필·성공 기록을 만들지 않는다.

장치 행·삭제된 자식 소스·프로필·ID/채널 예약·장치/소스의 과거 POST/PATCH/DELETE 성공 이력을 보존한다. 삭제 장치는 새 GET에서 404, 일반 장치 목록에서 제외된다. 과거 cursor는 해당 ID 이후부터 탐색한다. 삭제 device_id를 새 생성 키로 재사용할 수 없다.

같은 성공 키·본문은 최초 삭제 결과를 200으로 재생하며 version·시각을 다시 바꾸지 않는다. 같은 성공 키의 다른 유효 본문은 IDEMPOTENCY_CONFLICT다. 삭제 후 새로운 키의 DELETE/PATCH는 404다. 과거 생성·수정 성공 요청의 스냅샷 재생은 장치나 자식 소스를 복원하지 않는다. 현재 등록 존재 여부는 새 GET/목록으로 판단한다. 상세 요청·오류·동시성 기준은 [장치 삭제 계약](../contracts/camera-device-delete.md)을 따른다.

현재 운영은 **등록 전용 릴리스**다. 관리되는 세션·소비자·입력 어댑터 생성이 없는 검토 코드·구성·정확한 capability 목록에서만 registry-only-v1 정책을 적용한다. 이 정책은 외부 카메라의 실제 사용을 탐지하는 기능이 아니다. 향후 연결·세션·소비자를 도입하면 사용 시작과 삭제 판단이 장치/소스의 원자적 허용 경계에 함께 참여하도록 먼저 구현해야 한다. business_runtime_ready=false를 유지한다.

## 검증 범위와 단계 완료

| 단계 | 인수한 범위 | 근거 |
|---|---|---|
| 10-A 계약 | 논리 삭제·자식 처리·이력 보존·멱등성·경쟁·오류 계약과 예제 | [10-A 기록](20261001-step10a-device-delete-contract.md) |
| 10-B 저장소 | 스키마 7·장치 삭제 기록·열 최소 권한·원자성·실제 다중 연결 경쟁 | [10-B 기록](20261001-step10b-device-delete-storage.md) |
| 10-C HTTP | 엄격한 입력·최소 삭제 응답·OpenAPI·등록 전용 정책·기존 HTTP 회귀 | [10-C 기록](20261002-step10c-device-delete-http.md), 서버 인수는 [10-D1 기록](20261002-step10d1-device-delete-preflight.md) |
| 10-D1 사전점검 | 운영 0.6.0·스키마 6의 이미지·권한·구성·비밀·백업 전제 | 성공 인수는 [10-D2 기록](20261002-step10d2-device-delete-rehearsal.md) |
| 10-D2 실제 Docker 리허설 | 스키마 6→7·권한·장치/소스 삭제·모든 성공 이력 재생·보호 행/목록·API 재생성·별도 DB 복원·정리 | 성공 필드 17개, 서버 인수는 [10-D3 기록](20261002-step10d3-device-delete-activation.md) |
| 10-D3 운영 최초 전환·재실행 | 백업·스키마 7·검증된 후보 API·보존·GET 인수·재전환 없는 완료 검사 | 이번 사용자 서버 로그와 이 문서 |

10-B/C의 native PostgreSQL 17.11 검사와 10-D2 실제 Docker 시험은 모의 IO·PGlite 로컬 검사와 구분한다. 10-D3 도구 준비 시 전환 검사 45개·패치 검사 8개·임시 DB SQL 검증을 수행했으며 이번 사용자 로그에는 해당 단위 검사를 다시 실행한 결과가 없다. 실제 서버 최초 전환과 성공 재실행을 추가로 인수했다. 운영 인수용 HTTP는 GET만 사용했고 시험 등록·수정·삭제를 운영 DB에 만들지 않았다. 실제 운영 장애를 일부러 유발하지 않았다.

단위 10의 장치 삭제 계약·저장소·HTTP·격리 검증·이미지 리허설·운영 전환·성공 재실행 인수를 완료했다. 기존 문서의 운영 0.6.0·스키마 6, 장치 DELETE 미활성 및 서버 결과 대기는 각 문서 전달 당시 상태다. 현재 운영 인수 기준은 이 문서와 서버 10-D3 완료 기록이다.

## 네 플랫폼의 현재 범위

| 플랫폼 | 이 프로젝트에서 완료한 범위 | 남은 주요 범위 |
|---|---|---|
| camera | 독립 API·영속 장치/소스 등록·단건/목록 조회·이름 수정·양쪽 논리 삭제·멱등/버전·운영 전환 | 접속 설정·자격증명 관리·SourceSession·ONVIF/PTZ·RTSP/XR 수신/재접속·영상 제공/녹화 |
| model | 독립 HTTP API·health·인증·기능 상태/명세 기반 | 모델 등록/버전·배포/런타임·추론·학습 관리 또는 외부 모델 플랫폼 계약 연동 |
| analysis | 독립 API·분석 작업 입력의 형식 검증 | 작업 영속화·참조 실존 확인·실행 조정·워커 lease·추론·추적·이벤트 |
| operation | 독립 HTTP API·health·인증·기능 상태/명세 기반 | 플랫폼 업무 조율·관제 UI·알림·사용자 작업 |

model/analysis/operation은 이 VMS 저장소의 구현 상태를 기준으로 한다. 별도 agent_project의 모델·운영 플랫폼 구현을 VMS 연동 완료로 계산하지 않는다. 카메라 등록 기능 완료는 P1 전체 완료나 실제 CCTV·스마트글래스 영상 인수를 의미하지 않는다.

## 이번 문서 패치와 다음 작은 단위

이번 패치는 이 문서 1개만 추가한다. 기존 251개 파일·프로젝트 명세·10-D3 전환 도구·리허설 recipe를 그대로 보존한다. 명세의 운영 대기/이전 검증 필드는 10-C 전달 당시 기록이며 완료 도구의 검증 근거가 해시로 묶여 있으므로 이번 패치에서 다시 쓰지 않는다. 이후 인수 상태는 이 진행 기록으로 구분한다.

패치 적용 도구 검사 8개, 전체 패키지 적용 1개/재적용 0개·기준 충돌 시 사전 중단, 기존 파일/환경/운영 보고서의 내용·권한 보존, Markdown 상대 링크와 payload/압축본 경로·해시를 확인했다. 코드·SQL·Compose를 바꾸지 않아 제품 검사·빌드·서비스 재시작·마이그레이션은 반복하지 않았다. 완료 기록 패치의 서버 적용 결과는 아직 받기 전이다. 적용 명령은 채팅으로만 제공한다.

다음 작은 단위는 **11-A: 카메라 접속 설정·자격증명 참조 계약**을 제안한다. 기존 Device/VideoSource 등록과 분리한 접속 설정의 소유권·식별자·version, 어댑터별 필요한 정보, 비밀 입력/보관/응답 비노출·교체, 삭제 및 향후 사용 시작 보호를 먼저 확정하는 것이 완료 기준이다. 이 계약 작업에서 실제 장비 연결·SourceSession·미디어·모델·UI를 함께 구현하지 않는다. 실제 연결 어댑터를 도입하기 전에 등록 전용 삭제 정책을 대체할 사용 관계 보호 기준과 기술 검증 조건도 명시해야 한다.
