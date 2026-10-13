# 단위 11-B3c3d3 — 운영 공급의 읽기 전용 목록화

작성일: 2026-10-07 · 도구 준비/로컬 검증 및 서버 조회 인수 완료

## 선행 결과와 이번 결과

사용자가 d2c acceptance notes를 적용했다. written6/pending0, backup=var/patch-backups/step11b3c3d2c-notes-hst6h79q이며 restart/runtime activation/schema modification=false다. 기준 manifest SHA는 ada736c8d63500e869ec519d52f4d13b85b8650a844608c8d1993fba32fb17c3, tracked399개다. 격리 복원/재개 인수와 기존 운영 schema7/API0.7.0을 유지한다.

이번 결과는 운영 공급 준비가 부족한 항목을 안전하게 보고하는 독립 도구다. src/infra/tools에 inspector와 failure-boundary test를 추가하고 [점검 안내](../operations/camera-credential-supply-preflight.md)에 결과 의미를 기록했다. 전체 source/receipt/image/volume·실제 DSN RO mount·API/OpenAPI와 schema7 migration을 확인하고, 키 본문을 읽지 않고 파일 metadata만 확인한다. fixed-role catalog·TLS 설정·HBA의 lexical 위치를 읽되 approved authority/endpoint/source·실제 UID·신규 TLS/HBA 인증·키 무결성은 미검증으로 명시한다.

status=inspected/exit0는 목록화 완료다. readiness=blocked 및 activation_allowed=false를 항상 유지하며 공급 완료나 운영 전환 승인으로 사용하지 않는다. 불일치/위험한 link·권한/동시 변경/조회 실패는 fixed code의 failed/exit1이다. 임의 authority 경로를 탐색하지 않으며 리허설 IP/UID/키/CA를 운영값으로 추정하지 않는다. 보고서와 공통 activation coordination lock 외에는 쓰지 않는다.

## 검증

- Python 31개 통과: production command/API write 거부, extra environment 금지, key no-read, malformed inventory, key symlink/hardlink/권한/크기, source/env/key/container drift, secret-safe failure와 private report 재실행.
- 실제 로컬 PostgreSQL17.11 schema7에서 고정 SQL을 실행했다. 정확한 migration hash, 고정 역할 부재/존재, READ ONLY transaction, data mutation 거부, 점검 전후 schema/row 보존을 확인했다. 테스트 DB는 정리했다.
- 이 환경에 Docker가 없어 운영 container exec/socket 경로는 아직 인수하지 않았다. 가짜 Docker/HTTP 테스트와 로컬 SQL 검증을 대상 서버 조회 인수로 표시하지 않는다. 제품 Go/SQL/Compose/HTTP routing은 미변경이므로 기존 race/vet/격리 인수를 반복하지 않는다.
- 패치는 accepted baseline399개 전체를 검사하며 dry-run·백업 적용·재실행·사용자 변경/새 경로 충돌·보호 env/key/authority sentinel 보존과 helper8개를 검증한다.

## 남은 작업

사용자 서버 실행에서 written7/pending0·Python31개 OK와 status=inspected/readiness=blocked를 인수했다. 조회 source SHA는 effc214a66a3658058490310507d251ea0165fbd325392b9d7bfff0aa1fd1ab4다. 실제 schema7·TLS off·credential 역할3개/키 mount 부재·configured UID65532를 확인했고 production modifications/key material read=false다. [서버 조회 상세 및 다음 계약](20261007-step11b3c3d4a-production-supply-contract.md)에 결과를 기록했다. 키 metadata 확인은 무결성/공급 인수가 아니며 authority/endpoint/source·실제 EUID/HBA 인증은 미검증이다. 이후 운영 공급 계획과 실제 공급·full restore fence·schema9 cutover를 별도 단계로 진행한다. credential API·업무 runtime·실장비·영상 수신은 미완료다. Streamlit browser acceptance는 deferred, 중계는 추가하지 않는다. 패치/점검 명령은 채팅에서만 제공한다.
