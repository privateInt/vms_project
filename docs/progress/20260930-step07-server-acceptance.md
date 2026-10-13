# 단위 07 — 장치 표시 이름 수정 운영 인수 완료

작성일: 2026-09-30 · 장치 수정 API 운영 활성화 완료 · 완료 기록의 서버 적용은 이 문서 패치로 진행

## 인수 근거

사용자가 제공한 07-D3 서버 실행 로그에서 패치 파일 3개 적용과 운영 전환 성공을 확인했다. 파일 패치 백업은 `var/patch-backups/step07d3-qwmddhch`다. 패치 적용 자체는 서비스를 재시작하지 않았고, 이어 실행한 활성화 도구가 camera API 정지·운영 DB 백업·스키마 4 적용·후보 API 시작을 수행했다.

| 항목 | 서버 결과 |
|---|---|
| 상태 / 단계 | `activated` / `completed` |
| 범위 / 프로젝트 | `camera_device_update` / `vms-project` |
| API 주소 | `http://127.0.0.1:18081` |
| 장치 수정 활성화 | `device_update_activated=true` |
| 스키마 / 이번 마이그레이션 | `schema_version=4` / `migration_applied=1` |
| camera API 재시작 | `service_restart_performed=true` |
| DB 컨테이너 / 다른 서비스 | `database_container_unchanged=true` / `other_services_unchanged=true` |
| 자동 DB 복원 | `automatic_database_restore=false` |
| 영상 업무 런타임 | `business_runtime_ready=false` |

현재 camera 이미지 ID는 `sha256:493ba8654937e62bb4de890a63d32af02354ee67100ecd12cf68d4dd544ab7d8`다. 이전 camera 이미지는 `sha256:f4c88268652fa1002e5a6488201c47ad2d6738e66e5f7b4f7112255f27e989fd`, DB 이미지는 `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`이다. 이는 07-D2 리허설에서 검증한 이미지 조합과 일치한다. 활성화 도구의 버전·capability 검사도 통과한 운영 API는 `0.4.0-device-update`다.

`counts_before`는 devices, device_requests, video_sources, stream_profiles, source_requests 모두 0이었다. 이는 API를 정지한 뒤 확인한 전환 전 값이며, 전환 후나 문서를 읽는 시점의 운영 건수라고 해석하지 않는다.

## 백업과 운영 기록

전환 기록 디렉터리는 `/home/shshin/workspace/vms_project/var/camera/device-update-activation-backups/step07d3-atc1xpvz`다. 원래 환경·컨테이너 상태와 결과 기록을 보관한다. 이번에는 스키마 3 상태의 실제 운영 DB 덤프도 생성했다.

- DB 백업: `/home/shshin/workspace/vms_project/var/camera/device-update-activation-backups/step07d3-atc1xpvz/camera.pgdump`
- 백업 SHA-256: `0f464755728074a57b785c31842f97d5a3a6cc827c935cfc35c92c100cb1f90d`
- 운영 활성화 보고서: `var/camera/device-update-activation.json`
- 격리 리허설 보고서: `var/camera/device-update-upgrade-check.json`

경로와 해시는 사용자 실행 로그에 근거한다. 이번 문서 작업에서 서버 백업 파일을 직접 열거나 복원하지 않았다. 과거 단계의 백업과 활성화 기록은 보존한다.

## 완료한 기능과 검증 범위

`PATCH /api/v1/devices/{device_id}`로 장치의 `display_name`을 변경할 수 있다. Bearer 인증, 필수 Idempotency-Key와 본문의 expected_version 조건을 사용한다. 새 수정 성공 시 version은 1 증가하며 created_at·device_id·device_kind·자식 소스와 프로필은 유지한다. 같은 성공 요청은 저장한 최초 수정 응답을 재생하고, 다른 본문으로 키를 재사용하거나 버전이 충돌하면 409를 반환한다. 과거 수정 응답 재생이 최신 장치 상태를 되돌리지 않는다.

검증은 단계별 증거로 구분한다.

- **07-A~C 계약·저장소·HTTP:** 장치 표시 이름 수정 계약, 스키마 4의 수정 요청 기록과 최소 열 UPDATE 권한, 원자적 수정·멱등성·동시성·오류 처리, PATCH 라우팅을 구현했다. PostgreSQL 17.11의 저장소 및 HTTP 격리 검사 결과를 인수했다. 세부 증거는 기존 07-B 기록과 07-D1의 07-C 인수 기록을 따른다.
- **07-D1 사전점검:** 당시 운영 스키마 3·이전 이미지·역할·비밀·컨테이너·공간 검사 통과. 운영 서비스를 변경하지 않았다.
- **07-D2 실제 이미지 리허설:** 별도 Docker 프로젝트에서 스키마 3→4 전환, 권한, 장치/소스 생성 응답과 수정 응답 재생, 소스 목록, API 재생성, 별도 시험 DB의 스키마 3 복원과 이전 API 실행, 스키마 4 쪽의 전환 후 데이터 보존을 확인했다. 시험 자원 정리 완료를 인수했다.
- **07-D3 운영 전환:** 리허설·코드·이미지 일치를 재확인하고 실제 운영 백업 후 마이그레이션 1건을 적용했다. 새 API의 readiness·버전·수정 capability와 기존 목록 GET, 최종 스키마·권한 및 DB 컨테이너·다른 서비스 보존 조건을 통과했다. 운영 인수용 HTTP 요청은 GET만 사용했으며 시험용 장치 등록이나 PATCH를 실행하지 않았다.

이번 서버 로그는 최초 전환의 `activated` 결과다. 운영 재실행의 `already_activated` 결과를 받은 것으로 기록하지 않는다. 실패·중단·재실행 처리는 07-D3 로컬 대체 객체 테스트에서 확인했으며 이번 운영 환경에 장애를 일부러 유발하지 않았다.

스키마 3 덤프의 복원 검증은 07-D2의 별도 시험 DB에서 수행했다. 새 운영 백업을 실제 복원해 검증했다는 뜻은 아니다. 스키마 4에서 이전 스키마 3 이미지로만 복귀하는 절차와 자동 운영 DB 복원은 사용하지 않는다.

## 현재 기준과 문서 패치

단위 07의 장치 표시 이름 수정 구현·서버 격리 검사·실제 이미지 리허설·운영 전환을 완료했다. 이전 계약·진행 문서의 ‘운영 스키마 3’, ‘PATCH 405’, ‘서버 검사/전환 대기’는 해당 문서 작성 당시 상태다. 현재 운영 상태는 이 완료 기록과 서버의 07-D3 활성화 결과를 기준으로 판단한다.

이번 패치는 이 문서 한 파일만 추가한다. 리허설과 활성화가 사용하는 명세·도구 해시를 유지하기 위해 기존 코드·계약·진행 기록과 프로젝트 명세를 다시 쓰지 않는다. 파일 적용·재적용과 기존 파일·환경·운영 기록 보존을 확인했으며, Go/DB 검사·이미지 빌드·서비스 재시작·마이그레이션을 반복하지 않았다. 완료 기록 패치의 서버 적용 확인은 아직 받기 전이다.

## 남은 범위와 다음 단위

현재 운영 범위는 장치 등록·단건/목록 조회·표시 이름 수정과 소스 등록·단건/목록 조회다. 소스 수정, 장치/소스 삭제, 접속 설정·자격증명 관리, SourceSession, 실제 RTSP/XR 수신·영상 분석·UI는 완료 범위가 아니다. `business_runtime_ready=false`를 유지한다.

다음 작은 단위는 등록 계약의 변경·삭제 순서에 따라 **08-A: 영상 소스 수정 계약**을 정리하는 것이다. 변경 가능한 필드와 불변 식별자·부모 관계, 프로필 변경의 포함 여부, version 조건·멱등 재시도·오류 규칙을 먼저 확정한다. 저장소·HTTP 구현과 삭제·장비 연결은 후속 단위로 분리하며 이번 문서 패치에서 시작하지 않는다.

참고: [07-D1 사전점검](20260930-step07d1-device-update-preflight.md), [07-D2 격리 리허설](20260930-step07d2-device-update-upgrade.md), [07-D3 전환 도구](20260930-step07d3-device-update-activation.md), [장치 수정 계약](../contracts/camera-device-update.md), [작업 원칙](../development/working-standards.md).
