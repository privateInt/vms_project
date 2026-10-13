# 단위 11-B3b — 격리 키 공급·DB/키 복원 리허설

작성일: 2026-10-02 · native 서버 격리 인수 완료

## 선행 인수

사용자 로그로 [11-B3a 수정/준비 인수](20261002-step11b3a-key-file-backup.md)를 완료했다. Python 42개 OK, native Go race/vet·상위 114개·하위 310개·필수 자격증명 13개·권한/경쟁 passed, 호스트 backed_up/already_backed_up·원본 보존·0700/0600이었다. 해당 source hash는 ff0bcb7a82f8f0d0e30d2f32dc980bc1007d6a5cd0683ff1b721dfae75a820f7다. 운영 서비스/DB/환경과 API 키는 미변경·미활성이었다.

## 이번 결과

합성 키와 임시 Docker DB에 한정한 multi-process 리허설을 완성했다. native Go 검사 1개, 전용 Compose 1개, runner/단위 검사 2개, ADR/운영/진행 문서 3개를 추가한다. 기존 인수 기록/ADR/운영 문서와 프로젝트 명세를 갱신한다. SQL 1..8·저장소 실행 코드·기존 native runner·키 준비/백업 실행 코드·운영 Compose/앱/HTTP·다른 플랫폼은 보존한다.

실제 read-only 키 mount/UID·별도 writer/budget DSN·pg_dump/pg_restore·키 백업 바이트 복원·사용량 3→1 rewind·NOLOGIN/세션 종료·이전 DB CONNECT 거부·옛 키 쓰기 거부·옛 암호문/HMAC replay·새 키 쓰기와 재실행·누락 키 이력 거부·중단/새 프로세스 재검사를 하나의 격리 절차로 검사한다. 로컬에는 Docker가 없으므로 이 native 절차의 실제 passed는 아직 주장하지 않는다.

## 검증

| 검사 | 결과·범위 |
|---|---|
| 새 Python runner 단위 검사 | 16개 통과, ResourceWarning 오류 처리. 실제 Docker 호출은 mock |
| 기존 storage runner 단위 검사 | 12개 통과 |
| 기존 키 준비/호스트 백업 검사 | 42개 통과 |
| 관련 Go race | PGlite 18.3에서 storage/credentialcrypto 상위 58개·하위 114개 통과. native 전용 20개 skip이며 새 리허설 1개 포함 |
| 전체 Go vet | 통과 |
| native Docker·pg_dump/pg_restore | 이 환경에 Docker가 없어 미실행. 서버 도구가 8 phase 모두 실제 pass를 요구 |

 Python runner 검사는 mocked Docker 호출의 14개 단계 실패·timeout/interrupt·cleanup 실패·누락/잘못된 native 증거·source drift·순서·합성 키 이력·비노출을 확인한다. 이것을 실제 mount/role/pg_dump 복원 성공으로 취급하지 않는다.

패치 전달 검사는 적용/재적용·원본 백업·변경 충돌 사전 거부·보호된 합성 환경/키/이력 보존·전체 명세 hash·Python 3.10 문법·문서 링크·압축 경로/바이트를 검증한다. 패치 도구의 8개 검사를 실행한다. 기존 289개 중 5개를 갱신하고 신규 7개를 추가해 payload는 12개다. 기존 284개 파일의 바이트/권한은 보존한다.

## 미완료와 다음 단위

이번 서버 native 리허설 결과를 먼저 인수한다. production restore fence·runtime key supply/startup admission은 미구현이며 credential_restore_fencing_implemented=false다. 운영 schema 7·camera 0.7.0-device-delete·registry-only-v1·business_runtime_ready=false를 유지한다. 다음 단위는 11-B3c 외부 복원 fence/runtime key admission 기반이다. IAM·비밀 HTTP API·설정 CRUD·RTSP/실장비는 이후 별도 단위다. 실행 명령은 채팅에만 둔다.

## 서버 인수 — test2json 수정 후

사용자 로그에서 수정 패치 applied·written=4·pending=0과 Python 17개 OK, native passed를 확인했다. source hash는 b00516b1d169377f1c0dd98eadcf2b161d7d173246aafd21265c5a183390afb3다. vms-credential-restore-test-a1e8d8cc3720에서 Go race/vet와 8 phase 모두 통과했다.

read-only key mount·실행 UID·별도 role DSN·DB/키 복원·3→1 rewind 재현·옛 암호문/replay·옛 키 쓰기 거부·새 키 쓰기·중단 재시도·프로세스 재생성을 인수했다. 임시 자원 정리/합성 입력 제거는 true였다. 운영 서비스/DB/키/API는 미변경·미활성이며 production restore fence와 business_runtime_ready는 false다. 최초 실패의 상세 로그는 받지 않아 당시 명령을 소급 확정하지 않는다.

11-B3b 격리 인수 대기는 해소됐다. 다음은 작은 단위로 나눈 [11-B3c1 외부 admission 계약](20261002-step11b3c1-admission-contract.md)이며 운영 runtime guard/marker/키 공급은 후속 구현이다.
