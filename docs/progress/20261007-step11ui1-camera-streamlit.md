# 단위 11-UI1 — Camera Streamlit 등록 테스트 화면

작성일: 2026-10-07 · 서버 설치·자동 검사·기동 확인 완료 · 브라우저 인수 보류

## 이번 범위와 선행 인수

사용자가 각 플랫폼에 Streamlit 테스트 front page를 요청하고 작업 순서를 맡겼다. 기존 CRUD가 운영 인수된 Camera에 첫 독립 페이지를 추가했다. backend·DB·키·복원 fence 구현은 이번 단위에 묶지 않았다. ADR 0011과 Camera 화면 안내에 책임 경계와 사용 방법을 기록했다.

사용자 제출 로그의 11-B3c2 패치 applied/written17/pending0, Python 11개 OK, native Linux passed를 인수했다. project는 vms-credential-admission-test-3a99f865b6ae, 검증 리비전은 5cc861915dedf583fa51cf6bdfaea6f5f843683fef39735988886701ff940ea4다. Go race/vet, 핵심 admission 테스트17개·native phase2개, 실제 RO control mount·별도 maintenance/runtime UID·public reader·runtime metadata 쓰기 거부·stable lock/process drain·uncertain commit 재시도와 cleanup이 확인됐다. production 서비스·DB·키·admission state는 변경되지 않았다. 보고서 경로는 var/camera/credential-admission-checks/vms-credential-admission-test-3a99f865b6ae.json이다.

## 구현 결과

Camera 소유 test_streamlit 아래 독립 화면·stdlib HTTP client·고정 Streamlit 의존성·HTTP 및 화면 테스트를 추가했다. 장치와 영상 소스 등록·단건·목록·이름 수정·등록 삭제, 프로필·부모 필터·cursor, 최근 ID 사용, 정확한 버전·삭제 확인, 요청 영수증·현재 조회/과거 replay 분리, timeout/5xx 동일 요청 재시도를 제공한다. 실제 키·환경 파일·DB 직접 접근이나 가짜 credential 완료 표시는 없다.

운영 계약 원본의 byte digest를 확인한 뒤 bearer 변경을 보낸다. redirect·환경 proxy로 bearer를 전달하지 않는다. 응답은 크기를 제한하고 로컬 IO 오류 원문을 표시하지 않는다. 토큰은 브라우저 세션별 입력으로 사용하며 전역 cache/영수증에 저장하지 않는다. 새 운영 명세를 채택할 때 digest와 호출 계약 검토가 필요하다.

## 검증

| 검사 | 환경·결과 |
|---|---|
| HTTP client | Python3.12·실제 loopback HTTP server. 14개 통과: 공개/auth 분리·명세 불일치·DELETE JSON/int64·응답 유실과 동일 요청 retry·503/409·redirect 거부·응답 제한/불완전 chunk·cursor/filter·origin 변경·입력 검사 |
| Streamlit 화면 | Streamlit1.45.1 AppTest와 합성 API. 8개 통과: 초기/입력 변경 시 요청 없음·ready/auth 실패 차단·중복 제출/replay·불명확 요청/종료·2^53 초과 버전·삭제 확인/부모 거부·WEBRTC/프로필·필터 유지·주소/토큰 변경 |
| Streamlit process smoke | 실제 별도 loopback process의 health·HTML 응답·정상 종료 통과. 운영 API 호출 없음 |
| 기존 네 API smoke | Go1.25.1, make smoke 62개 통과. 임시 포트·프로세스이며 운영 서비스/DB 접근 없음 |
| 전달 검사 | 기준 전체 파일·payload/manifest hash·최초 적용/재실행·원본 백업·합성 보호 파일 보존·충돌 사전 거부·archive 내용 검사 |

화면 테스트는 AppTest이며 수동 브라우저 시각 검사·운영 CRUD 인수는 아직 수행하지 않았다. 대상 서버 Python3.10 설치·자동22개·기동은 아래 사용자 로그로 인수했다. backend Go/SQL/HTTP·운영 Compose·이미지·키와 API 원본은 변경하지 않았다. 기존 native DB/키 복원 리허설은 반복하지 않았다.

## 남은 작업과 다음 단위

서버 패치·설치·자동22개·기동을 인수했다. 사용자가 브라우저 CRUD는 보류하기로 했으므로 다음 backend의 선행 조건으로 두지 않는다. 11-UI1a 환경 분리·기존 버전 복구 수정을 먼저 마친 뒤 기존 11-B3c3 DB/key/runtime 통합으로 돌아간다. schema9 marker·정규 profile hash·actual key loader receipt·CredentialStore 작업 전체 구간 admission 보호와 native DB/key 복원 검증이 완료 기준이다. 이후 준비된 API 기능에 맞춰 각 플랫폼 테스트 페이지를 추가한다.

현재 운영 camera0.7.0-device-delete/schema7/registry-only-v1, credential 저장소 구현 schema8이다. credential API·connection config API·production restore fence·business runtime은 미완료다. Model/Analysis/Operation 테스트 페이지와 실제 영상·추론·관제 UI도 이번에 구현하지 않았다. 패치 적용·실행 명령은 채팅에만 제공한다.

## 서버 인수·브라우저 보류 — 2026-10-07

사용자 첨부 로그에서 applied/written13/pending0, Python3.10의 화면/HTTP22개 OK, Streamlit1.45.1 기동 및 127.0.0.1:18501 안내를 확인했다. 원본 백업은 var/patch-backups/step11ui1-6mopb8kz다. 사용자에게 현재 JupyterLab 포트만 열려 있고 중계는 필요 없음을 확인했다. 브라우저 CRUD 인수만 보류하며 backend 진행을 막는 조건으로 두지 않는다.

설치 과정에서 공용 sh_test의 Streamlit1.50.0→1.45.1, cachetools6.2.1→5.5.2, protobuf7.36.0→6.33.6 변경과 grpcio-tools1.83.1의 protobuf>=7.35.1 요구 충돌을 확인했다. 기존 qwen-tts/transformers 충돌도 로그에 있었으며 해당 패키지를 이번 UI 설치가 변경한 것은 아니다. 11-UI1a에서 UI 전용 venv와 로그에 확인된 세 버전의 제한된 복구를 준비한다. 실제 환경 복구는 서버 실행 결과로 별도 인수한다.
