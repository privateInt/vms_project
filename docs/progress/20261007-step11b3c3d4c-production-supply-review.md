# 단위 11-B3c3d4c — 운영 공급 검토 초안

작성일: 2026-10-07 · d4b 실제 운영 조사와 d4c 검토 초안 생성 서버 인수 완료

## 선행 인수

사용자 simsys4090/sh_test 로그에서 d4b written8/pending0, backup=var/patch-backups/step11b3c3d4b-59qw5c59, 공급 조사 테스트63개 OK와 실제 Docker 조회 완료를 인수했다. source SHA0e8a55880d8a40e6802260f8b2791c7db046741c309c75f6ed2cd72610ec468e / tracked414개를 이번 delta 기준으로 사용한다. 상세 관찰과 한계는 [d4b 기록](20261007-step11b3c3d4b-production-supply-facts.md)에 있다. raw 서버 private report를 새로 읽었다는 주장은 하지 않는다.

host key owner1006:1007, API daemon-host65532:65532, DB daemon-host999:999, SSD의 volume 선언 경로와 internal192.168.96.0/20 주소를 관찰했다. container UID mapping·host topology·IP pinning·실제 공급 binding은 false다. schema7/API0.7.0-device-delete/registry-only-v1·TLS off·credential roles/key mount 부재와 blocker11개를 유지한다. 서비스/DB/key/authority/HBA/environment/network 변경은 모두 false다.

## 이번 결과

[공급 검토 초안 생성](../operations/camera-credential-supply-review.md)을 추가했다. d4b read-only 조사를 새로 수행하고 camera 소유 SupplyPlan schema의 required field와 고정 정책42개를 추출한다. 현재 checked source SHA·project root·원본 key path/owner UID를 연결하고, 미검증 UID/path/IP는7개 후보로만 기록한다. 정상 metadata가 있으면 미확정40개 field는 null로 남는다. hash·certificate·maintenance/source·authority/snapshot 경로를 임의로 만들거나 선택하지 않는다.

기본 planned 실행과 apply의 private prepared 저장을 제공한다. worksheet/partial profile은 기존 strict SupplyPlan parser에서 거부되며 항상 incomplete/blocked/activation_allowed=false다. 동일 내용SHA는 already_prepared로 재사용하고, 변경 관찰은 새 파일로 저장해 이전 초안·사용자 편집을 보존한다. 새 query/exec/SQL·키/PKI/DSN/authority 공급·Go/API/SQL/Compose 변경은 없다.

## 검증

새 unittest27개와 기존 공급 조사63개를 통과했다. 합성 fresh facts를 사용해 required shape·고정/관찰/후보/null 구분·null40개·SupplyPlan 거부·키/volume 미읽기·stale report 미사용·source acceptance·metadata drift·private mode/idempotency·사용자 edit와 link/permission/size·publication race 거부·버전 보존·secret-safe 출력을 확인했다. parser/schema 원본은 변경하지 않으며 기존 공급/admission 계약57개 인수를 유지한다. Python3.12/jsonschema4.26 로컬이며 서버 Python3.10/jsonschema4.25 인수는 사용자 실행으로 확인한다. 의존성과 UI 환경은 변경하지 않는다.

accepted baseline414개 전체와 payload hash, dry-run·백업 적용·재실행, 사용자 편집·새 경로 충돌, 보호 env/key/authority sentinel 보존, helper8개와 적용된 payload 테스트를 패키지 검사에 포함한다. 이전 Go race/vet/native 복원·재개와 d4b 실제 Docker 인수를 유지한다. 로컬 Docker가 없어 새 서버 초안 저장이나 실제 생성된 파일 경로를 주장하지 않는다.

## 다음 완료 기준

서버에서 초안 생성과 private 저장을 인수한 뒤 필드별 미확정 입력을 검토해 supply 위치/maintenance UID·source/PKI/backup 범위를 구체화한다. 실제 container UID mapping·경로/mount/physical backup topology와 보호 파일 공급을 확인할 독립 단위를 진행한다. worksheet를 배포하거나 static parser 성공만으로 승인 상태를 생성하지 않는다. authority bootstrap/lock receipt·schema9 전환·full production restore fence·credential HTTP API·실장비/영상은 후속이다. Streamlit browser acceptance는 deferred이며 중계를 추가하지 않는다. 패치/실행 명령은 채팅에서만 제공한다.

## 서버 인수 — 2026-10-07

사용자 simsys4090/sh_test 로그에서 written8/pending0와 공급 테스트90개 OK를 인수했다. patch backup은 var/patch-backups/step11b3c3d4c-ohf5thr7이다. source SHA0670c667d5169780ec50e338f029ce118ef19e7ed79a245ff1eccb5f5d887326 / tracked418개이며, 초안 생성은 prepared/review_file_created=true/review_available=true다.

초안 상대 경로는 var/camera/credential-supply-reviews/review-e496c0142a0c8100c7ff1022d2bdbb1b2bcea46714d6a9ead36fe9b04d32b4d9.json이다. 내용 SHAe496c0142a0c8100c7ff1022d2bdbb1b2bcea46714d6a9ead36fe9b04d32b4d9, plan_state=incomplete/unresolved40/후보7개/후속 검증5개 범주를 확인했다. readiness=blocked/activation_allowed=false/review_is_deployable=false를 유지하며 공급 파일·authority·실제 SupplyPlan을 만들지 않았다. 모든 운영 서비스·DB·키·HBA·환경·network 변경과 credential 활성화는 false다. private 파일의 본문을 별도로 읽었다는 주장은 하지 않는다.

다음 독립 단위는 [d4d 현재 프로세스 identity](20261007-step11b3c3d4d-process-identity.md)다. 이번 초안의 UID 후보를 현재 init process와 대조하며, 전체 배포 binding 승인이나 초안 자동 편집으로 확대하지 않는다.
