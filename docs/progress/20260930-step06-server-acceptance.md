# 단위 06 — 소스 목록 조회 운영 인수 완료

작성일: 2026-09-30 · 소스 목록 API 운영 활성화 완료 · 완료 기록의 서버 적용은 이 문서 패치로 진행

## 인수 근거

사용자가 제공한 06-B2 서버 실행 로그에서 패치 파일 4개 적용과 camera API 전환 성공을 확인했다. 파일 패치 백업은 `var/patch-backups/step06b2-9cgn9c2o`다. 패치 적용 자체는 서비스를 재시작하지 않았고, 이어 실행한 활성화 도구에서 camera API만 교체했다.

| 항목 | 서버 결과 |
|---|---|
| 상태 / 단계 | `activated` / `completed` |
| 범위 / 프로젝트 | `camera_source_list` / `vms-project` |
| API 주소 | `http://127.0.0.1:18081` |
| 소스 목록 활성화 | `source_list_activated=true` |
| 스키마 / 이번 마이그레이션 | `schema_version=3` / `migration_applied=0` |
| camera API 교체 | `service_restart_performed=true` |
| DB 컨테이너 / 다른 서비스 | `database_container_unchanged=true` / `other_services_unchanged=true` |
| 자동 DB 복원 | `automatic_database_restore=false` |
| 영상 업무 런타임 | `business_runtime_ready=false` |

현재 camera 이미지 ID는 `sha256:f4c88268652fa1002e5a6488201c47ad2d6738e66e5f7b4f7112255f27e989fd`다. 이전 camera 이미지는 `sha256:3c0b6919565eceb0511b55c5f5d4faea3fa94c4404de8020f7fdb8df3ae20b93`, DB 이미지는 `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`이다. 이는 06-B1에서 검증한 이미지 조합과 일치한다.

설정 전환 기록 디렉터리는 `/home/shshin/workspace/vms_project/var/camera/source-list-activation-backups/step06b2-m3ew_m_i`다. 이 경로에는 원래 환경 파일·컨테이너 상태·전환 결과가 있으며 이번에 새 DB 덤프를 만들었다는 뜻은 아니다. 활성화 결과 파일은 `var/camera/source-list-activation.json`이고 기존 05 단계의 활성화 기록과 DB 백업은 보존한다.

## 완료한 기능과 검증 범위

단위 06-A에서 `GET /api/v1/sources`를 구현했다. Bearer 인증, ID 오름차순, 기본 limit 50·최대 200, cursor 페이지 구분, 선택적 device_id 필터, 전체 소스 필드와 등록 순서의 프로필 반환을 지원한다. 빈 목록은 배열이며 마지막 next_cursor는 null이다. cursor는 소스 목록 및 정확한 장치 필터에 결합한다. 기존 소스 등록·단건 조회 계약을 유지한다.

검증은 다음 단계별 증거에 근거한다.

- **06-A 서버 격리 검사:** 실제 PostgreSQL 17.11에서 목록 정렬·프로필·페이지·필터·제한값·재시작·토큰 교체 후 cursor 및 권한 회수/복구 시 503/200 처리가 통과했다. 기존 등록 API의 원자성·멱등성·동시성·스키마 검사, Go race 검사와 vet도 통과했다.
- **06-B1 실제 이미지 검사:** 별도 Docker 프로젝트에서 새 이미지의 목록 API, API 재생성, 동일 스키마 3의 이전 이미지 복귀와 새 데이터 보존이 통과했다. 운영 서비스는 변경하지 않았고 시험 컨테이너·볼륨·네트워크를 정리했다. 보고서는 `var/camera/source-list-image-check.json`이다.
- **06-B2 운영 전환:** 활성화 도구가 검사 결과·코드·이미지의 일치를 확인한 뒤 camera API만 전환했다. readiness, `0.3.1-source-list` 버전, source_list capability와 목록 GET 응답을 확인했고 스키마 3·DB 컨테이너·다른 서비스 유지 조건을 통과했다. 운영 검증은 GET과 읽기 전용 SQL이며 운영 DB에 시험 데이터를 등록하지 않았다.

이번 서버 로그는 최초 전환의 `activated` 결과다. 운영에서 활성화 도구를 재실행한 `already_activated` 로그를 받은 것으로 기록하지 않는다. 재실행과 실패 시 자동 이미지 복귀 동작은 06-B2의 로컬 대체 객체 테스트에서 검증했고, 이미지 자체의 복귀 호환성은 06-B1 실제 Docker 검사에서 검증했다. 이번 운영 전환에서 장애·복귀를 일부러 유발하지 않았다.

## 현재 기준과 남은 범위

단위 06의 기능 구현·서버 격리 검사·이미지 검사·운영 전환을 완료했다. 기존 준비 문서의 ‘서버 전환 대기’는 작성 당시의 이력이며, 현재 운영 상태는 이 완료 기록과 서버의 활성화 결과를 기준으로 판단한다.

이번 패치는 이 완료 기록 한 파일만 추가한다. 검사에 사용한 프로젝트 명세·도구 해시를 유지하기 위해 이전 코드 패키지 명세와 진행 기록을 다시 쓰지 않는다. 환경 파일·이미지·DB·API를 변경하거나 검사를 다시 실행하지 않는다. 파일 적용·재적용과 기존 파일 보존만 확인한다. 완료 기록 패치가 서버에 적용됐다는 확인은 아직 받기 전이다.

현재는 장치·소스의 메타데이터 등록과 조회까지 운영 가능하다. 수정·삭제 API, 접속 설정·자격증명 관리, SourceSession, 실제 RTSP/XR 수신·영상 분석·UI는 완료 범위가 아니다. `business_runtime_ready=false`는 이 범위 구분과 일치한다.

다음 작업은 등록 계약 문서의 ‘변경·삭제’ 순서에서 **장치 수정 API 하나**를 먼저 선택한다. 첫 작업 단위는 변경 가능한 필드, 요청의 version 조건, 동시 수정·재시도·오류 응답 계약을 확정하는 것이다. 소스 수정·삭제·장비 연결을 같은 단위에 묶지 않는다. 이번 응답에서는 다음 기능 구현을 시작하지 않는다.

참고: [06-A 구현 기록](20260930-step06-source-list.md), [06-B1 이미지 검사](20260930-step06b1-source-list-image.md), [06-B2 전환 준비](20260930-step06b2-source-list-activation.md), [전환 운영 안내](../operations/camera-source-list-activation.md), [작업 원칙](../development/working-standards.md).
