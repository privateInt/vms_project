# 11-B3b — test2json 준비 경로 수정과 실패 단계 진단

작성일: 2026-10-02 · 수정·native 서버 재검사 인수 완료

## 받은 서버 결과

사용자 로그에서 [11-B3b](20261002-step11b3b-key-supply-restore-rehearsal.md) applied·written=12·pending=0과 Python 16개 OK를 확인했다. patch backup은 var/patch-backups/step11b3b-fk0qhcxm이다. 검사 source hash는 4b3eaf8974722ae36c6d53e9213c695632778ce06a8e89a6b8c3b9dcd0f13994다.

native 검사는 ISOLATED_REHEARSAL_COMMAND_FAILED로 실패했다. 임시 프로젝트 vms-credential-restore-test-d10081dc2ca6의 정리와 합성 입력 제거는 true였다. 운영 서비스/DB/키/API와 production restore fence는 미변경·미활성이다. 상세 로그를 아직 받지 않아 서버에서 처음 실패한 명령은 확정하지 않는다. go_race_passed/go_vet_passed=false는 전체 완료 판정이며 어느 준비 명령이 실패했다는 직접 증거는 아니다.

## 로컬에서 확인한 오류와 수정

기존 준비 shell은 GOTOOLDIR/test2json 파일이 사전 설치됐다고 가정하고 복사했다. 현재 로컬 Go 1.25.0 도구 체인에서 해당 파일이 없고 복사가 FileNotFoundError로 실패하는 것을 재현했다. 이번 수정은 해당 경로 의존성을 제거하고 표준 cmd/test2json 소스를 같은 컨테이너의 Go로 직접 빌드한다. 실행 권한 0755는 기존처럼 명시한다. 로컬 표준 도구 빌드 성공과 실제 race Go 테스트 바이너리의 JSON pass 출력을 확인했다. 이것을 서버 Go 1.27.1에서 발생한 최초 오류와 동일하다고 단정하지 않는다.

보고서에 failed_stage·last_completed_stage·명령이 반환한 failed_command_exit_code를 추가한다. 반복 blocked/enrolled 단계도 번호로 구분한다. timeout/interrupt는 없는 종료 코드를 만들지 않으며 cleanup 실패가 기존 단계 실패 정보를 지우지 않는다. 원문 명령·환경·DSN·비밀값은 공개 보고서에 넣지 않는다. 기존 코드/로그 경로·성공 증거 요구·격리 정리 조건은 유지한다.

## 검증과 전달 범위

Python native runner 검사 17개가 통과했다. 새 shell 회귀 검사는 비어 있는 사전 도구 디렉터리와 가짜 Go compiler/chown을 사용하며 실제 cp·chmod·shell 실패 전파를 실행한다. 기존 경로 복사는 실패하고 수정 준비는 두 실행 파일 0755로 완료해야 한다. 나머지 14개 명령의 실패 위치·종료 코드·재개 차단·정리, timeout/interrupt, transcript/source/cleanup 실패 진단을 확인했다. 기존 저장소 runner 12개도 통과했다.

실제 로컬 Go 1.25.0으로 cmd/test2json과 storage race 테스트 바이너리를 빌드하고 TestSafeDatabaseError의 실제 test2json 출력/종료 상태를 확인했다. Go 소스·SQL·Compose·운영 앱/HTTP·키 준비/백업 실행 코드에는 변경이 없다. 따라서 전체 Go race/vet와 smoke를 반복하지 않았다. native Docker/DB/키 복원은 이 환경에 Docker가 없어 서버 재검사를 기다린다.

패치 도구 8개, 기준 296개 파일의 적용/재적용·원본 백업·사용자 충돌 사전 거부·보호된 합성 환경/키/이력 보존·Python 3.10 문법·전체 명세 hash·문서 링크·압축 바이트/경로를 검증한다. 기존 296개 중 runner/단위 검사/명세 3개를 갱신하고 이 문서 1개를 추가해 payload는 4개다. 기존 293개 파일을 보존한다.

## 다음 완료 기준

수정 적용 후 Python 17개와 native 리허설을 다시 실행해 8 phase의 실제 pass와 정리를 먼저 확인한다. 실패하면 새 failed_stage와 private 로그로 해당 명령을 진단한다. 11-B3b는 아직 서버 인수 전이며 11-B3c/운영 활성화로 진행하지 않는다. 운영 schema 7·camera 0.7.0-device-delete·business_runtime_ready=false를 유지한다. 실행 명령은 채팅에만 제공한다.

## 서버 인수 — test2json 수정 후

사용자 로그에서 수정 패치 applied·written=4·pending=0과 Python 17개 OK, native passed를 확인했다. source hash는 b00516b1d169377f1c0dd98eadcf2b161d7d173246aafd21265c5a183390afb3다. vms-credential-restore-test-a1e8d8cc3720에서 Go race/vet와 8 phase 모두 통과했다.

read-only key mount·실행 UID·별도 role DSN·DB/키 복원·3→1 rewind 재현·옛 암호문/replay·옛 키 쓰기 거부·새 키 쓰기·중단 재시도·프로세스 재생성을 인수했다. 임시 자원 정리/합성 입력 제거는 true였다. 운영 서비스/DB/키/API는 미변경·미활성이며 production restore fence와 business_runtime_ready는 false다. 최초 실패의 상세 로그는 받지 않아 당시 명령을 소급 확정하지 않는다.

11-B3b 격리 인수 대기는 해소됐다. 다음은 작은 단위로 나눈 [11-B3c1 외부 admission 계약](20261002-step11b3c1-admission-contract.md)이며 운영 runtime guard/marker/키 공급은 후속 구현이다.
