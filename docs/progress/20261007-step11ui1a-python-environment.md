# 단위 11-UI1a — 테스트 UI Python 환경 분리·이전 버전 복구

작성일: 2026-10-07 · 도구·로컬 검증 및 서버 환경 분리·관찰 버전 복구 인수 완료

## 범위와 근거

사용자 첨부 로그에서 11-UI1 파일13개 적용, Python3.10 자동22개 OK, Streamlit 기동을 인수했다. 외부에서 JupyterLab 포트만 접근 가능하며 사용자가 중계는 필요 없다고 했으므로 브라우저 인수는 보류한다. UI 접속을 backend 개발 선행 조건으로 두지 않는다.

앞선 설치 안내가 공용 sh_test에 UI requirements를 설치해 세 버전을 변경했다. 이번 수정은 전용 venv 준비와 로그에 확인된 세 버전 복구를 하나의 독립된 수정 단위로 끝낸다. backend admission·DB 마이그레이션·API 구현은 다음 단위로 유지한다.

| 패키지 | 설치 전 로그 | UI 설치 후 로그 | 복구 목표 |
|---|---|---|---|
| streamlit | 1.50.0 | 1.45.1 | 1.50.0 |
| cachetools | 6.2.1 | 5.5.2 | 6.2.1 |
| protobuf | 7.36.0 | 6.33.6 | 7.36.0 |

Streamlit1.50.0의 PyPI distribution metadata도 protobuf<7을 요구함을 확인했다. 기존 grpcio-tools1.83.1의 요구는 protobuf>=7.35.1,<8이다. 따라서 기존 공용 조합 전체가 호환됐다고 주장하지 않는다. 이전 버전 복구와 UI의 독립된 정상 환경을 구분한다. qwen-tts/transformers는 로그에 존재하던 별도 불일치이며 이 단위에서 수정하지 않는다.

## 구현

src/infra/tools/prepare_camera_test_environment.py의 기본 실행은 계획만 출력한다. apply 실행은 var/test-streamlit/python의 별도 venv를 준비하고 pip check와 실제22개 UI/HTTP 테스트를 수행한다. 원본 요구 버전·소유 marker·system-site-packages 분리·interpreter prefix를 확인하며 미관리 디렉터리·symlink·다른 UI 버전은 덮어쓰지 않는다.

restore-shared 옵션은 관찰된 sh_test prefix와 현재/이전 버전만 허용한다. 전용 환경 검사가 먼저 통과해야 복구를 진행한다. 현재 세 wheel과 원래 세 wheel을 변경 전에 확보하고 hash 영수증을 만든다. 공용 버전을 재확인한 뒤 no-deps/no-index로 변경이 필요한 패키지만 되돌린다. 재실행에서 이미 원래 버전이면 공용 pip 작업을 하지 않는다.

복구는 일반 pip 패키지 파일 쓰기이므로 중단에 대한 원자성을 제공하지 않는다. 실패 영수증·백업·private log를 남기고 자동 rollback은 하지 않는다. 보고에는 확인한 변경 여부만 기록한다. Jupyter/API service 제어·DB/실제 키 접근·port proxy를 추가하지 않는다.

## 검증

| 검사 | 결과·범위 |
|---|---|
| 도구 unit | 8개 통과. 잘못된 환경/미관찰 버전·미관리 경로·symlink·system-site-packages·불완전 UI 검사·download 실패·준비 중 변경·복구 실패/재실행 검사 |
| 실제 별도 venv | Python3.12, Streamlit1.45.1 설치·pip check·UI/HTTP22개 통과. 같은 venv에서 재실행도 통과 |
| 실제 UI process | 전용 venv interpreter로 loopback health/HTML 응답·정상 종료 통과. 실제 운영 API 호출 없음 |
| 실제 pip 복구 리허설 | 임시 venv fixture에 설치 후 실제 wheel6개 다운로드·hash·세 원래 버전 복구·already_restored 재실행 통과. Conda prefix 신원은 fixture로 모델링하고 별도 unit에서 실제 도구의 제한을 검사 |
| 공용 환경 guard | 로컬 일반 Python에서 restore-shared 실행을 거부하며 공용 변경 없음 |
| 전달 | 전체 baseline/payload/manifest hash·최초 적용/재실행·원본 백업·합성 보호 파일 보존·충돌 사전 거부·archive 내용 검사 |

Go/SQL/API routing/운영 Compose가 변경되지 않아 직전 make smoke62개 결과를 유지하며 반복하지 않았다. 이번에 실제 실행한 process 검사는 전용 venv의 Streamlit이다. 대상 서버의 venv 생성·기존 세 버전 복구 및 재검증 결과는 아래 서버 인수에 반영했다.

## 다음 단위

서버에서 파일 적용·도구8개 unit·계획 확인·전용 venv 준비/22개 검사·관찰된 공용 버전 복구 결과를 인수했다. 브라우저 접속과 Jupyter 중계는 요청하지 않는다. 그다음 11-B3c3의 schema9 marker·profile hash·actual key loader receipt·CredentialStore 전체 작업 구간 admission 통합과 native DB/key 복원을 진행한다. credential API·production restore fence·business runtime은 여전히 미완료다. 명령은 채팅에만 제공한다.

## 서버 인수 — 2026-10-07

사용자 첨부 로그에서 파일9개 적용, 도구8개 unit OK, 계획 출력에서 공용 환경 미변경, apply 실행에서 전용 interpreter·분리·dependencies_verified와 UI22개 통과를 확인했다. sh_test의 세 패키지 버전 streamlit1.50.0/cachetools6.2.1/protobuf7.36.0 복구를 인수한다. 복구 범위는 logged_versions_only이며 전체 공용 dependency consistency는 확인하지 않았다는 보고를 유지한다. 서버 복구 백업은 var/test-streamlit-recovery/step11ui1a-ec5jxjin이다. 운영 서비스·DB·실제 키 변경 없음, 브라우저 인수 deferred를 확인했다. Jupyter 중계는 추가하지 않는다. 다음은 11-B3c3a DB 표식·읽기 전용 준비 검사다.
