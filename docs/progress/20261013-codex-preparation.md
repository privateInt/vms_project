# Codex 준비 상태 — 갱신 2026-10-14

현재 문서 준비의 상태 기준이다. 제품 진행과 서버 인수 원문은 [기존 이관](../development/codex-handoff.md)과 [서버 증거](20261012-codex-handoff-server-evidence.json)를 유지한다.

| 준비 항목 | 현재 판정 |
|---|---|
| 공통 규칙·테스트 기준·에이전트 구성·템플릿 | 1.1-docs 배포판 준비 |
| VMS 책임·보호·검사·첫 H01 연결 | [프로젝트 규칙](../codex/project.md)과 기존 backlog를 연결 |
| 이번 문서 GitHub 전달 | 2026-10-14 privateInt 연결·두 저장소 쓰기 권한 확인. [문서 PR](https://github.com/privateInt/vms_project/pulls)에서 게시·검토 결과 확인. main 반영은 독립 검토 후 |
| GitHub 필수 검사·독립 승인 강제 | 현재 main 보호 없음·ruleset 없음·필수 검사 목록 비어 있음. 자동 개발 전 적용 필요 |
| GitHub 자동 병합 | 현재 꺼짐. PR 게시와 별개이며 아직 활성화하지 않음 |
| 서버 CLI·ChatGPT 계정·모델·동시 실행 | 실제 확인 전 |
| 크레딧 미사용 제어 | 확인 전·무인 실행 차단 |
| 독립 검사 계획·최종 reviewer | 경로 적용 전·자체 확인을 독립 승인으로 세지 않음 |
| 기능 개발·worker·scheduler·운영 변경 | 미시작 |

문서와 project-manifest 파일 해시만 정리했다. 기존 역사 메타데이터·준비 승인/hash anchor·운영 상태를 새 문서 기준으로 재작성하지 않는다. 문서 변경도 H01의 준비 source revision에 영향을 주므로 기존 apply를 반복하지 않는다.

다음 준비와 첫 작업의 진입점은 [work-plan.md](../codex/work-plan.md)다. H01 오류는 아직 수정되거나 서버 인수되지 않았다. 백업 추가 개발 제외와 기존 운영 실행 보류를 유지한다.
