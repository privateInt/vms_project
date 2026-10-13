# 단위 04 서버 인수 완료 — 영속 DB·장치 API 활성화

확인일: 2026-09-30 (Asia/Seoul) · 04-A 격리 검사 완료 · 04-B 실제 활성화 완료

이 문서는 사용자 서버의 실행 결과를 반영한 최신 기록이다. README 및 `20260930-step04-camera-activation.md`에 남아 있는 서버 검사·전환 대기는 패치 전달 당시 상태이며, 이번 인수 결과로 해소됐다. 직접 서버에 접속한 결과가 아니라 사용자가 제공한 로그와 활성화 도구의 완료 조건을 근거로 확인했다.

## 04-A — 패치와 서버 격리 검사

- 적용: 28개 파일, 서비스 재시작 없음.
- 파일 백업: `/home/shshin/workspace/vms_project/var/patch-backups/step04-135o0i1e`.
- PostgreSQL 17.11의 Go/API/저장소 검사 통과. 프로젝트: `vms-storage-test-93600fef22e6`.
- 파일 기반 DB 비밀, 장치 생성·조회·멱등 응답·페이지 조회, API 재시작·토큰 교체, 권한 실패 시 롤백·재시도, 동시 생성·마이그레이션 검사 통과.
- Docker 격리 검사: `status=passed`, `scope=camera_activation_native_docker`. 프로젝트: `vms-activation-test-5e2f503fb346`.
- DB 컨테이너 교체 후 데이터 보존, 별도 DB로 백업 복원, camera 전환 실패 시 복구, 보호 대상 검사 컨테이너 보존을 확인했다.
- `production_services_modified=false`. 검사 도구는 임시 프로젝트 정리 성공 후 최종 통과를 출력한다.

제작 환경 WASM 검사에서 관찰됐던 일회성 API 종료 실패는 이번 일반 PostgreSQL 검사에서 재현되지 않았다. 그 원인을 확정한 것은 아니다.

## 04-B — 실제 camera 서비스 활성화

| 확인 항목 | 사용자 서버 결과 |
|---|---|
| 상태 | `activated` |
| 범위 | `camera_device_registry` |
| Compose 프로젝트 | `vms-project` |
| API 주소 | `http://127.0.0.1:18081` |
| DB 스키마 버전 | `2` |
| 이번에 적용한 마이그레이션 | `2` |
| 다른 서비스 상태 보존 | `other_services_unchanged=true` |
| 영상 분석 업무 런타임 | `business_runtime_ready=false` |

DB 백업: `/home/shshin/workspace/vms_project/var/camera/activation-backups/step04-pvbfq72p/camera.pgdump`.

활성화 도구는 이미지 빌드, 영속 DB 시작과 백업, 명시적 마이그레이션·runtime 권한 부여, camera API 전환을 완료했다. 최종 성공은 DB readiness, 인증된 장치 목록 조회, 장치 등록 capability, 다른 서비스의 전후 상태 비교를 포함한다. 실제 운영 DB에 시험 장치를 생성한 결과는 아니다. 장치 생성·재시작 보존은 04-A 격리 환경에서 검증했다.

이제 기존 개발용 Bearer 인증을 사용하는 장치 등록·단건/목록 조회 API와 영속 저장소가 동작한다. 외부 접근, 실장비 ONVIF/RTSP 연결, 영상 수신·추론·관제 UI까지 완료한 상태는 아니다. `business_runtime_ready=false`는 이 구현 범위를 나타내는 정상 값이다.

## 이번 기록의 적용 범위

완료 기록 파일 하나만 추가한다. 검증된 소스·Compose·기존 문서·프로젝트 배포 명세와 서버 검사 성공 기록을 보존한다. 따라서 기록 추가로 기존 활성화 검사 식별값이 바뀌지 않는다. 다음 기능 패치에서 이 인수 기록을 포함해 문서와 배포 명세를 갱신한다.

## 다음 작은 작업 단위

다음 구현은 **소스 등록·단건 조회**로 한정한다. 기존 등록 계약을 기준으로 부모 장치 확인, 채널·프로필 관계의 원자적 저장, 동일 요청의 멱등 응답과 실패 롤백을 구현·검증한다. 소스 목록 조회는 별도 후속 단위로 둔다. 소스 수정·삭제, 연결 세션, 실장비 입력, UI는 각각 후속 작업이다.

이번 응답에서는 서버 결과 확인과 완료 기록만 수행했다. 다음 기능 구현은 시작하지 않았다.
