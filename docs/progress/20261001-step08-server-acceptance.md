# 단위 08 — 영상 소스 표시 이름 수정 운영 인수 완료

작성일: 2026-10-01 · 소스 수정 API 운영 활성화 완료 · 완료 기록의 서버 적용은 이 문서 패치로 진행

## 인수 근거

사용자가 제공한 08-D3 서버 실행 로그에서 패치 파일 3개 적용, 활성화 도구 단위 테스트 25개 통과(1.121초), 운영 전환 성공을 확인했다. 파일 패치 백업은 `var/patch-backups/step08d3-gczkzd0d`다. 패치 적용 자체는 서비스를 재시작하지 않았고, 이어 실행한 활성화 도구가 camera API 정지·운영 DB 백업·스키마 5 적용·검증된 후보 API 시작을 수행했다.

| 항목 | 서버 결과 |
|---|---|
| 상태 / 단계 | `activated` / `completed` |
| 범위 / 프로젝트 | `camera_source_update` / `vms-project` |
| API 주소 | `http://127.0.0.1:18081` |
| 소스 수정 활성화 | `source_update_activated=true` |
| 스키마 / 이번 마이그레이션 | `schema_version=5` / `migration_applied=1` |
| camera API 재시작 | `service_restart_performed=true` |
| DB 컨테이너 / 다른 서비스 | `database_container_unchanged=true` / `other_services_unchanged=true` |
| 자동 DB 복원 | `automatic_database_restore=false` |
| 영상 업무 런타임 | `business_runtime_ready=false` |

활성화 도구의 버전·capability 검사까지 통과한 운영 API는 `0.5.0-source-update`다. 이미지 조합은 08-D2 성공 리허설과 일치한다.

- 현재 camera 이미지: `sha256:6c10ff4314892d952933d457e9dee6ddaf0126aadc551c9bb07813f5344915dd`
- 이전 camera 이미지: `sha256:493ba8654937e62bb4de890a63d32af02354ee67100ecd12cf68d4dd544ab7d8`
- DB 이미지: `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`

`counts_before`는 devices, device_requests, video_sources, stream_profiles, source_requests, device_update_requests 모두 0이었다. 이는 API를 정지한 뒤 확인한 전환 전 값이다. 전환 후나 문서를 읽는 시점의 운영 건수로 해석하지 않는다.

## 백업과 운영 기록

전환 기록 디렉터리는 `/home/shshin/workspace/vms_project/var/camera/source-update-activation-backups/step08d3-7ztwmslq`다. 기존 환경·컨테이너 상태와 결과 기록을 보관하며, 전환 직전 스키마 4의 운영 DB 덤프를 생성했다.

- DB 백업: `/home/shshin/workspace/vms_project/var/camera/source-update-activation-backups/step08d3-7ztwmslq/camera.pgdump`
- 백업 SHA-256: `f926818d910da6f1cf78ada2291a5b46eea1440b6a5ad6e4d730f6efb790a4b4`
- 운영 활성화 보고서: `var/camera/source-update-activation.json`
- 격리 리허설 보고서: `var/camera/source-update-upgrade-check.json`

경로와 해시는 사용자 실행 로그에 근거한다. 이번 문서 작업에서 서버나 백업 파일을 직접 조회·복원하지 않았다. 이 덤프는 전환 전 백업이며 스키마 5에서 새로 접수한 데이터까지 포함하는 최신 백업은 아니다. 과거 백업과 활성화 기록을 보존한다.

## 완료한 기능과 검증 범위

`PATCH /api/v1/sources/{source_id}`로 영상 소스의 `display_name`을 변경할 수 있다. Bearer 인증, 필수 Idempotency-Key와 본문의 expected_version 조건을 사용한다. 새 수정 성공 시 version은 1 증가하며 created_at·식별자·부모 장치·채널·입력 설정과 프로필을 유지한다. 같은 성공 요청은 저장한 최초 수정 응답과 당시 프로필을 재생한다. 다른 본문으로 키를 재사용하거나 버전이 충돌하면 409를 반환하며, 과거 응답 재생이 최신 소스 상태를 되돌리지 않는다.

검증 근거는 다음과 같다.

- **08-A~C 계약·저장소·HTTP:** 표시 이름 수정 계약, 스키마 5의 소스 수정 요청 기록과 제한된 열 UPDATE 권한, 원자적 수정·멱등성·충돌·오류 처리, PATCH 라우팅을 구현하고 단계별 검사를 마쳤다. 세부 내용과 실행 환경은 각 단계의 기존 기록을 따른다.
- **08-D1 사전점검:** 당시 운영 API `0.4.0-device-update`·스키마 4의 이미지·역할·비밀·컨테이너·백업 공간 조건을 통과했다. 운영 서비스를 변경하지 않았다.
- **08-D2 실제 이미지 리허설:** Python 3.10.19에서 발생한 시간 파싱 ValueError를 시간 비교 수정으로 해소했다. 서버 단위 테스트 34개와 이후 전체 리허설이 통과했다. 별도 Docker 프로젝트에서 스키마 4→5 전환, runtime 권한, 장치/소스 생성·수정 응답 재생, 소스 목록, API 재생성을 검증했다. 별도 시험 DB의 스키마 4 복원과 이전 API 실행, 스키마 5 쪽 전환 후 데이터 보존, 보호 대상 컨테이너 보존과 시험 자원 정리도 확인했다. 상세 성공 결과는 08-D3 준비 기록에 있다.
- **08-D3 운영 전환:** 성공 리허설·코드·이미지 일치를 재확인하고 운영 백업 후 마이그레이션 1건을 적용했다. 새 API의 readiness·버전·capability와 기존 목록 GET, 최종 스키마·권한 및 DB 컨테이너·다른 서비스 보존 조건을 통과했다. 운영 인수용 HTTP 요청은 GET만 사용했고 시험용 등록·PATCH 데이터를 만들지 않았다.

이번 서버 결과는 최초 전환의 `activated`다. 운영 재실행의 `already_activated` 결과를 받은 것으로 기록하지 않는다. 실패·중단·재실행 동작은 활성화 도구 단위 테스트로 검증했으며 운영 환경에 장애를 일부러 유발하지 않았다.

스키마 4 복원 검증은 08-D2의 별도 시험 DB에서 수행했다. 이번에 생성한 운영 백업을 실제 복원했다는 뜻은 아니다. 스키마 5에서 이전 이미지로만 복귀하거나 운영 DB를 자동 복원하는 절차는 사용하지 않는다.

## 현재 기준과 이번 문서 패치

단위 08의 소스 표시 이름 수정 구현·격리 검사·이미지 리허설·운영 전환을 완료했다. 이전 문서의 ‘운영 스키마 4’, ‘소스 PATCH 미활성’, ‘서버 전환 결과 대기’는 각 문서 작성 당시 상태다. 현재 운영 기준은 이 완료 기록과 서버의 08-D3 활성화 결과다.

이번 패치는 이 문서 한 파일만 추가한다. 리허설과 활성화 검증에 사용한 기존 코드·계약·진행 기록·도구·프로젝트 명세의 바이트와 해시를 유지한다. 파일 적용·재적용, 충돌 시 쓰기 중단, 기존 파일·환경·운영 기록 보존을 확인했다. 제품 검사·이미지 빌드·서비스 재시작·마이그레이션은 반복하지 않았다. 완료 기록 패치의 서버 적용 결과는 아직 받기 전이다.

## 남은 범위와 다음 단위

현재 운영 범위는 장치와 소스의 등록·단건/목록 조회·표시 이름 수정이다. 장치/소스 삭제, 접속 설정·자격증명 관리, SourceSession, 실제 RTSP/XR 수신·영상 분석·UI는 완료 범위가 아니다. `business_runtime_ready=false`를 유지한다.

다음 작은 단위로 **09-A: 영상 소스 삭제 계약**을 제안한다. 삭제 상태와 조회 규칙, version 조건·멱등 재시도, 프로필·요청 이력 보존, 식별자·채널 키 재사용 제한, 사용 중인 세션·소비자 보호 조건과 오류 규칙을 먼저 확정하는 것이 완료 기준이다. 저장소·HTTP 구현·운영 전환은 후속 단위로 분리한다. 이번 문서 패치에서 삭제 기능 구현을 시작하지 않는다.

참고: [08-D3 전환 도구와 리허설 인수](20261001-step08d3-source-update-activation.md), [Python 3.10 시간 비교 수정](20261001-step08d2-python310-timestamp-fix.md), [소스 수정 계약](../contracts/camera-source-update.md), [등록·변경·삭제 순서](../contracts/camera-registry.md), [작업 원칙](../development/working-standards.md).
