# 2026-10-12 Codex 이관

상태: 대화 기반 기능 개발 중단 · 문서 이관 준비 · H01 후속 개발 대기 · 운영 TLS 미전환

## 최신 사용자 지시와 중단 판단

사용자는 프로젝트를 Codex에 넘겨 자동 개발을 진행하고, 적절한 지점에서 현재 개발을 멈추며 목표/계획을 명확하게 정리하라고 요청했다. 생성 자료 정리는 서버에서 완료됐고 D1e는 운영 전환 전에 Compose 검사에서 중단됐다. 따라서 새로운 TLS 수정·전환을 현재 대화에서 수행하지 않고 이 상태를 기준으로 이관한다.

## 사용자 서버 결과 반영

image pin 수정/정리 archive checksum OK·applied/written11/pending0/backup_created=false를 확인했다. 서버 cleanup12개(0.240초), 준비30개(2.310초) 검사가 OK였다. cleaned 결과는 대상41개·파일 항목12,021개·472,388,543 logical bytes이며 전용 UI 환경을 제거했다. 설정/키/TLS 공급/Docker/공유 Conda/Jupyter 변경은 보고되지 않았다. JSON 검사 결과와 source는 보존됐다.

D1e dry-run은 planned로 공급/현재 운영 확인을 통과했다. 첫 apply는 REGISTRY_TLS_COMPOSE_SECRETS_CHANGED, compose_validation에서 실패했다. 다음 apply는 set-e로 실행되지 않았다. D1e prepared/재실행·control volume/Compose 인수는 미완료다. 오류를 이번 이관에서 수정하지 않았다.

서버 기준 source SHA는654c8864cf1330b2e21beb985ed3206e01140f03279eb79bb72ff0e9eee7027e다. planned preparation SHA는fa4b07e802f1be09423e5c02d345ada0cd3308116ffadca283a01d6583c0d1cc다. 증거는 [요약 JSON](20261012-codex-handoff-server-evidence.json)에 기록했다. 이는 사용자 제공 로그의 해석이며 현재 서버를 직접 재관찰한 결과가 아니다.

## 이관 변경

- AGENTS와 작업 기준에 자동 개발 시 작은 단위별 완료/기록 후 backlog를 계속 진행하는 규칙, 사용자 백업 제외, 운영 실행 범위를 반영했다.
- [이관 문서](../development/codex-handoff.md)에 네 플랫폼의 실제 상태·서버 evidence·환경·보존 기준·첫 오류·실패 후 준비 파일과 revision 문제를 명시했다.
- [개발 backlog](../development/codex-backlog.md)에 H01~H12의 목표·선행 조건·완료 조건과 플랫폼별 Streamlit 구현 시점을 정리했다.
- [시작 지시문](../development/codex-start-prompt.txt)을 제공했다. 실행 코드/API/SQL/Compose 원본과 현재 TLS 준비 알고리즘은 변경하지 않았다.
- README·문서 목록·아키텍처 최신 작업 순서와 manifest의 서버 상태를 갱신했다. 과거 인수 anchor와 이전 실패 이력은 보존했다.

이관 패치는 문서/메타데이터만 반영하고 새 백업을 만들지 않는다. global manifest hash는 변경되므로, 기존 prepared-v1과 새 source의 호환성을 H01에서 해결하기 전에는 준비 apply를 다시 실행하지 않는다. 현재 operating image/schema7과 credential의 개발 schema8/통합 schema9를 구분한다.

## 검증 범위

manifest의 전체 파일 hash와 변경 범위를 확인한다. 문서의 저장소 내부 링크, source-only 압축의 제외 경로와 구성, 패치 dry-run/적용/재적용·충돌·실행 입력/준비 파일 보존 및 무백업 적용을 확인한다. 이관 installer의 8개 회귀 검사를 실행한다. 기능 코드 변경이 없으므로 Go/race/vet·Docker/native·smoke를 새로 수행하거나 기존 결과를 이번 변경의 재인수로 표시하지 않는다. 실제 이관 문서의 서버 적용은 전달 후 사용자 실행 사항이다.

## 다음 단위

Codex H01: 실제 Compose secret 정상화와 정확한 mount 검사를 재현·수정하고, 실패 후 준비 receipt/file/volume·source revision 대응을 검증한다. 준비 두 번 인수한 뒤 H02 도구/격리 검증으로 진행한다. 현재 대화에서는 기능 개발을 재개하지 않는다.
