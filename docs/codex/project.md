# VMS 프로젝트 세부 규칙

공통 배포판: [1.2-preparation](common/release.json). 공통 정책은 [RULES.md](common/RULES.md), 검사 기준은 [TESTING.md](common/TESTING.md)를 참조한다.

## 목표와 기준 위치

camera·model·analysis·operation을 독립적으로 구현해 CCTV·스마트글래스 입력 → 모델 배포 → 분석 → 관제와 근거 확인을 연결한다. 첫 통합 목표와 실제 진행 상태는 [Codex 이관](../development/codex-handoff.md), 작업 순서와 완료 조건은 [backlog](../development/codex-backlog.md), 설계 책임은 [architecture-plan](../architecture/architecture-plan.md)이 기준이다. 운영 API 실행을 실장비·GPU·제품 인수 완료로 해석하지 않는다.

준비 기준 GitHub main은 `84d3e84372a81bbe52d350dce0be3f290c773d3c`이다. 다음 작업에서는 실제 HEAD와 운영 source revision을 다시 확인한다. 첫 기능 작업 H01은 11-D1e 준비 오류와 실패 뒤 재실행 안전성 해결이다. 이번 단계에서 기능 코드·운영 TLS를 바꾸지 않는다.

## 역할별 변경 경계

아래 경로는 담당 후보이며 작업마다 파일 목록을 더 좁힌다. 경로 설명은 실제 OS 접근 제한을 대신하지 않는다.

| 역할 | 프로젝트 경로·책임 | 함께 확인할 경계 |
|---|---|---|
| backend_agent | `src/platform/{camera,model,analysis,operation}` | 각 도메인의 API·DB·상태·계약을 소유. 타 플랫폼 DB/internal 직접 사용 금지 |
| infra_agent | `src/infra`, 플랫폼 Docker/Compose·개발 환경 | H01 준비 도구는 infra 담당. 운영 실행과 현재 준비 자산을 별도로 보존 |
| code_module_agent | `src/platform/internal`의 기술 공통 코드 | HTTP·설정·계측만. Device/VideoSource/SourceSession 등 도메인 객체 이동 금지 |
| front_agent | 현재 `src/platform/camera/test_streamlit`, 이후 API가 준비된 소유 플랫폼의 화면 | 다른 플랫폼의 화면은 아직 구현 완료가 아님. 공유 Conda/Jupyter 변경 없이 환경 확인 |
| ui_design_agent | 관제·상태·오류·근거 흐름 설계 문서 | 장치/영상 소스/세션을 명확히 구분. XR을 ONVIF로 취급하지 않음 |
| test_agent | 변경 대상 옆의 Go/Python 검사, 계약 및 서버 인수 | FakeDocker 검사와 실제 Compose/장치/GPU 인수 구분 |
| reviewer | diff·검사 계획·소스/운영 상태 증거의 독립 확인 | 직접 수정한 변경은 다른 독립 검토 담당에게 인계 |

## 프로젝트별 보호와 예외

- 백업 추가 개발·자동 백업 생성·백업 검토의 선행 조건화는 사용자 지시에 따라 제외한다. D34의 일반 최소화 정책으로 이 제한을 해제하지 않는다.
- 운영 서비스 재시작·DB/schema/HBA 전환·현재 Compose/환경/TLS 적용은 현재 준비·이관 범위에서 보류다. 미래 자동 진행 규칙은 현재 준비 자산의 운영 사용 승인이 아니다.
- `.env`, 현재 키·credential·TLS 공급/후보·DSN/HBA·준비 파일·권한·receipt·Docker volume·운영 데이터를 보존한다. 비밀값이나 전체 Compose config를 문서에 저장하지 않는다.
- prepare 실패 후 ready가 없다는 사실을 준비 파일이 없다는 의미로 해석하지 않는다. 현재 준비 상태를 확인하기 전 같은 apply를 반복하지 않는다.
- 문서와 manifest 변경도 준비 source revision을 바꾼다. 과거 승인/hash/인수 anchor를 새 문서 hash로 덮어쓰지 않는다. 안전한 재사용·미사용 준비 갱신은 H01에서 별도로 검증한다.
- 운영 camera schema7, credential 개발 schema8, 통합 schema9를 구분한다. 인증·동시성·hash 검사를 낮춰 막힌 단계를 우회하지 않는다.

## 검사 연결

| 변경 범위 | 검사 시작점 | 필요한 근거 |
|---|---|---|
| 문서 준비 | 링크·공통 파일 일치·project-manifest 파일 해시·diff·소스 불변 | 역사 메타데이터와 운영 상태 보존. 전체 Go/DB 검사 재실행 불필요 |
| H01 준비 도구 | `src/infra/tools`에서 `python3 -B -m unittest test_prepare_camera_registry_tls_cutover` | 정상 mount, 잘못된 source/target·중복·경로 변조, 실패 준비 파일·source revision 호환성. FakeDocker 통과만으로 서버 오류 해결 아님 |
| 실제 Compose 대응 | 비밀값을 제거한 실제 source/target/mount 경로와 Compose 버전 | normalized secret target 원인은 현재 가설. 원문 운영 환경/전체 config 공개 금지 |
| 반복 준비 안전성 | 기존 backlog H01 및 이관의 서버 인수 조건 | prepare→already_prepared, 동일 준비/volume, 중복 생성 방지. 운영 API/DB/TLS는 유지 |
| 후속 Go/라우팅 변경 | 해당 module의 관련 검사·`go vet ./...`, 프로세스/라우팅 변경의 `make smoke` | 장비/GPU 인수와 격리 검사 분리 |

이 표는 검사 시작점이다. test_agent의 사전 계획과 독립 reviewer 확인을 대체하지 않으며 구체적인 필수 범위는 H01의 기존 계약에 연결한다.

## 실행 준비 상태

서버의 개발 worktree·branch·HEAD·실행 계정·운영 원본 경로는 비공개 실행 기록과 실제 서버 조회로 확인한다. 공개 규칙에 계정별 절대 경로를 배포하지 않는다. 개발 worktree와 운영 원본은 구분하며 현재 일치 여부를 확인하기 전 원본에 문서나 코드를 적용하지 않는다. 실제 환경 확인 절차는 [실행 준비](common/EXECUTION_SETUP.md)를 따른다.

현재 준비 상태 문서는 [20261013-codex-preparation.md](../progress/20261013-codex-preparation.md), 작업별 상세·검토는 PR에 둔다. 제품 인수 근거는 기존 이관/서버 JSON을 그대로 참조한다. 다음 순서는 [work-plan.md](work-plan.md)를 따른다.
