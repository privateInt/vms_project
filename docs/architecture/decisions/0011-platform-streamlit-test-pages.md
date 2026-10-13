# ADR 0011 — 플랫폼별 독립 Streamlit 테스트 페이지

상태: 채택 · 2026-10-07

## 결정과 이유

사용자가 agent_project처럼 각 플랫폼에 테스트 front page를 요청했고, 구현 순서는 현재 준비 상태에 맞춰 진행하기로 했다. 첫 페이지는 기존 등록 CRUD를 검증할 수 있는 Camera다. Python/Streamlit은 테스트 화면에 사용하고 현재 Go 제어 API의 언어·책임은 유지한다.

각 페이지는 소유 플랫폼의 `test_streamlit`에 독립 실행 스크립트와 HTTP 호출 코드를 둔다. 화면은 해당 플랫폼의 공개 API만 호출한다. 다른 플랫폼의 DB·Go internal·MinIO·호스트 키 파일을 직접 읽거나 쓰지 않는다. 처음에는 Docker/Compose·통합 portal·공통 UI framework를 추가하지 않는다. 통합 관제 제품 UI는 operation 소유의 별도 작업이다.

API 기능 구현 → 해당 기능의 테스트 화면 → 서버에서 확인 순서로 확장한다. Model·Analysis·Operation은 실제로 호출 가능한 기능과 인수 기준이 준비된 시점에 각각 만든다. 아직 없는 API를 완료된 화면이나 모의 성공 상태로 표시하지 않는다.

## Camera 적용

Camera 화면은 이미 운영 인수된 API 0.7.0-device-delete·registry-only-v1의 장치·소스 CRUD만 제공한다. 공개 명세의 정확한 SHA-256과 등록 readiness·인증된 플랫폼 버전을 확인한다. 이후 API를 채택할 때 HTTP 계약과 화면을 함께 검토해 digest를 갱신한다.

쓰기 요청은 명시적인 폼 제출에만 발생한다. 응답 유실·5xx에는 같은 origin/method/path/key/body를 유지해 사용자가 재시도한다. 수정·삭제는 상세 조회의 버전을 사용하며 삭제는 정확한 ID와 체크박스 확인이 필요하다. 최초 성공 응답의 재생과 현재 조회 결과를 구분한다.

## 검증과 영향

Streamlit 1.45.1을 고정했다. Python 3.10 이상이 설치 전제이며 로컬 검증은 Python 3.12에서 수행했다. 실제 HTTP test server와 Streamlit AppTest로 요청·화면 동작을 검증하고, 독립 Streamlit 프로세스와 기존 네 Go API smoke를 확인했다. 대상 서버 Python 3.10 설치·자동22개 검사·기동은 사용자 로그에서 인수했다. 브라우저 사용은 외부 작업으로 보류한다.

영상 연결·재생·ONVIF/PTZ·자격증명·연결 설정·DB/키 복원 제어는 이번 페이지 범위에 포함하지 않는다. 화면 성공은 business runtime 준비를 뜻하지 않는다.

## 2026-10-07 환경 분리 수정

공용 sh_test 설치가 protobuf/cachetools/Streamlit 버전을 변경한 로그를 확인했다. 이후 UI는 소유 프로젝트의 var/test-streamlit/python 전용 venv에 설치하며 Jupyter 서버·커널·타 프로젝트 환경과 분리한다. 도구가 관리하지 않는 디렉터리·공유 site-packages는 사용하지 않는다. 사용자에게 전달하는 실행 명령도 전용 interpreter를 사용한다. 공용 환경 복구는 확인된 세 버전만 대상으로 하며 전체 의존성 정합성을 주장하지 않는다.
