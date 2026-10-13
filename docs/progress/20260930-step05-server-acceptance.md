# 단위 05 — 소스 등록·단건 조회 운영 활성화 인수

작성일: 2026-09-30 · 05-A 구현·서버 검사 및 05-B 운영 전환 완료

## 인수 근거

사용자가 2026-09-30에 제공한 05-B3 재실행 로그를 확인했다. 파일 패치는 `already_applied`, 변경 0개였고 전환 도구는 `already_activated`, `stage=completed`를 반환했다.

이 결과는 이전 전환 완료 기록이 존재하고, 재실행 시 실제 컨테이너의 이미지·실행 상태, 이미지 설정, DB 스키마 3, API 버전 `0.3.0-source-registry`, readiness, 소스 capability와 인증된 소스 GET 경로의 검증이 통과했다는 뜻이다. 이번 재실행의 `service_restart_performed=false`를 확인했다. 최초 전환의 콘솔 로그 자체는 전달받지 않았으며, 저장된 완료 기록과 현재 상태 재검증 결과를 인수 근거로 삼았다.

| 항목 | 확인 결과 |
|---|---|
| 범위 | `camera_source_registry` |
| 프로젝트 | `vms-project` |
| API 주소 | `http://127.0.0.1:18081` |
| 스키마 | 3 |
| 소스 API 활성화 | `source_api_activated=true` |
| 다른 서비스 보존 | 최초 완료 기록의 `other_services_unchanged=true` |
| DB 컨테이너 보존 | 최초 완료 기록의 `database_container_unchanged=true` |
| 이번 재실행 | 조회 검증만 수행, 서비스 재시작 없음 |
| 업무 실행 준비 | `business_runtime_ready=false` |

`migration_applied=1`은 저장된 최초 전환 결과다. 이번 재실행에서 마이그레이션을 추가 실행했다는 뜻이 아니다. `counts_before`의 장치·장치 멱등 응답·소스·프로필 0건도 최초 전환 전 건수이며, 현재 데이터 건수를 새로 보고한 값으로 해석하지 않는다.

## 이미지와 백업

활성 camera 이미지: `sha256:3c0b6919565eceb0511b55c5f5d4faea3fa94c4404de8020f7fdb8df3ae20b93`.

이전 camera 이미지: `sha256:53743baaebd5ffdb174eb4c54530f231ebf80cf5148fa2ceee12d5adbba877fb`.

DB 이미지: `sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201`.

보고된 백업 폴더는 `/home/shshin/workspace/vms_project/var/camera/source-activation-backups/step05b3-29z57zik`이며 DB 백업은 그 아래 `camera.pgdump`다. 기록된 SHA-256은 `bce61e48fc09a9f0b22e22b50ed10ac4d185a2de87114973eb5958929f0a58b9`다. 이 경로와 체크섬은 최초 완료 기록에 포함된 값이며, 이번 재실행이 백업 파일 복원을 다시 검사한 것은 아니다.

운영 전환 기록은 `var/camera/source-activation.json`에 보존된다. 자동 DB 복원은 수행하지 않았다. 마이그레이션 이후 구버전 이미지만 재시작하거나 기존 백업으로 현재 DB를 자동 덮어쓰지 않는 복구 기준을 유지한다.

## 단위 05의 완료 범위

- 05-A: 소스 등록·단건 조회, 엄격한 입력 계약, 부모 장치·채널 제약, 프로필과 멱등 응답의 원자적 저장 구현. PostgreSQL 17.11 서버 회귀 검사 완료.
- 05-B1: 운영 구버전·스키마·볼륨·건수의 읽기 전용 점검 완료.
- 05-B2: 격리 DB의 스키마 2→3, 실제 runtime 권한, 장치·소스 멱등 응답 보존, API 재생성, 별도 백업 복원과 구버전 API 검사 완료.
- 05-B3: 검증된 이미지로 운영 소스 API 활성화 완료 및 재실행의 조회 전용 검증 확인.

사용 가능한 소스 API는 `POST /api/v1/sources`와 `GET /api/v1/sources/{source_id}`다. 등록은 메타데이터 저장을 의미한다. 실제 장비 연결·RTSP 수신·WebRTC 수신·추론·녹화는 아직 완료 범위에 포함되지 않으므로 `business_runtime_ready=false`가 정상이다.

## 이번 문서 반영과 다음 단위

이번 패치는 이 인수 기록 1개만 추가한다. 코드·Compose·`.env`·비밀·운영 DB·검사 및 전환 보고서를 변경하지 않으며 빌드·재시작·마이그레이션·서버 검사를 요구하지 않는다. 기존 배포 명세와 검사 코드의 체크섬을 그대로 유지한다.

앞선 05-A/B1/B2/B3 문서의 대기 표기는 각 문서 작성 시점의 이력이다. 현재 운영 활성화 상태는 이 인수 기록과 실제 전환 보고서를 기준으로 판단한다. 기존 프로젝트 명세는 검사에 사용한 코드 패키지의 식별값으로 보존한다.

다음 독립 기능 단위는 **소스 목록 조회**다. 기존 장치 목록의 방식과 맞춰 목록 계약·페이지 구분·필요한 필터·조회 구현 및 검증을 진행한다. 소스 수정·삭제·장비 연결·UI를 같은 작업에 묶지 않는다.
