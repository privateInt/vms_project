# Codex 개발 순서와 완료 조건

2026-10-12 기준 계획이다. H01만 즉시 선택된 단위이며 H02 이후는 선행 조건이 충족되는 순서로 작은 단위로 나눈다. 사용자 장비·API·모델 자료를 실제로 확인한 뒤 기술 선택을 ADR로 확정한다. 기간/완성 퍼센트를 임의로 약속하지 않는다.

| ID / 상태 | 목표·주요 위치 | 선행 조건 | 완료 조건 |
|---|---|---|---|
| H01 / ready | D1e Compose secret 검사·실패 후 준비 재실행. src/infra/tools의 준비 도구/테스트 | 최신 source·서버 증거, 기존 prepared-v1 관찰 | 정확한 mount 등가성만 허용·위변조 거부. source revision 변경 시 안전한 재사용/제한 갱신. 단위 검사와 실제 준비 두 번 통과, 운영 미변경 |
| H02 / depends H01 | D1f schema7 TLS 전환 실행 도구 개발·격리 인수 | D1e 실제 prepared 인수, 기존 D1d 성공 기준 | 무백업 전환 도구·preflight·단계/중단/retry 상태·실제 isolated 전환. schema7/등록 이력·TLS·UID/RO·타 플랫폼 보존. 여기서는 운영에 실행하지 않음 |
| H03 / depends H02 | Credential 운영 공급·schema9/main 통합을 하위 단위로 구현 | schema7 TLS 검증, key/DSN/authority 공급 계약 | 키·역할·admission·marker 실제 검증, main의 명시적 activation, 관리 권한 정책, 사용 중 참조 폐기/삭제 보호, API 비밀 비공개. 실제 HTTP·권한 상실·lease·재생성 격리 인수. 운영 실행 별도 |
| H04 / depends H03 | ConnectionConfig API/저장소와 SourceSession 계약·상태 전이 | credential 참조/권한·실제 사용 관계 guard | 소스와 credential의 명시적 참조, version/멱등성/동시 삭제 보호. 세션 생성/중지/실패/재연결·자원 해제의 계약 및 테스트 |
| H05 / depends H04 | 최소 RTSP 입력→보기, 이후 ONVIF/profiles/지원 PTZ | 실제 CCTV 정보·SDK/미디어 후보 확인. 합성 송출로 개발 가능 | 실장비 2대에서 등록→연결→보기→재접속. capabilities 기반 PTZ·timeout/인증/로그 비공개·SourceSession 격리. 합성 성공과 장비 인수 구분 |
| H06 / depends H04,H05 공통 경로 | XR 앱/시그널링/WebRTC 입력 | 실제 글래스·SDK/OS/인코더·망/TURN 조건 확인 | 실제 글래스 송출→수신/보기, 장치/세션 식별·재접속·PTS/방향·자원 해제·망 경로. 보조 송출은 실제 글래스 인수를 대체하지 않음 |
| H07 / contract work can proceed after H01 | model 모델/버전/아티팩트 참조 CRUD·배포 상태 계약 | 기존 모델 플랫폼 API 존재 여부, 모델 런타임 기술 확인 | model 소유 저장소·버전·아티팩트 digest·권한·실패 상태·재시도. 공개 API로 조회/관리, 실제 deployment/inference 미완료 명시 |
| H08 / depends H07 | 모델 배포/readiness·실제 추론 | 합법적으로 제공된 모델 2종·GPU/런타임 환경 | 정확한 버전·로드 성공/실패·출력 계약·공유 모델 사용 관계·resource limit·실제 두 모델 추론. 성능은 실측치만 기록 |
| H09 / depends H04,H07; execution depends H05,H08 | analysis 영속 작업·제어 루프·워커 lease·추론 연결 | SourceSession·model readiness/API 계약 | 실제 참조 확인, 작업 생성/중지·부분 실패·재시작·lease 중복 실행 방지. CCTV ROI 침입/XR 검출 경로를 각 단위로 검증 |
| H10 / depends H09 | 추적·시간 규칙·쓰러짐·이벤트, camera의 클립/스냅샷 | timestamp/PTS/source/session/model 추적 계약 | CCTV2+XR1·모델2 다대다 격리, 이벤트 시각과 근거 영상 연결·저장 실패 표시/재처리·재생. 이벤트는 analysis, 영상은 camera가 소유 |
| H11 / depends H09,H10 | operation 조율·관제 UI·이벤트/조치/알림 | 공개 플랫폼 API와 권한 계약 | 소스/모델/분석 적용→상태/실패 원인→이벤트/근거 영상 확인. 타 플랫폼 DB 직접 조작 없이 부분 실패 재시도 |
| H12 / depends H05,H06,H08,H10,H11 | 통합 실장비·장시간·장애·과부하 인수 | 실제 대상 장비와 사용 흐름 준비 | 인수 결과표·재현 가능한 실행 문서·알려진 한계. 미검증 장비/GPU/브라우저 항목은 남겨두고 완료로 표시하지 않음 |

H03은 하나의 대형 변경으로 구현하지 않는다. 역할/DSN 공급 → 키·authority 공급 → schema9 cutover 도구/격리 인수 → main 구성 → 실제 사용 관계 guard/API 인수처럼 각각 검토·검증 가능한 하위 단위로 나눈다. 기업 IAM 제품/조직 정보가 없다면 현재 개발용 권한 정책의 한계를 명시하고 기업 통합을 완료했다고 주장하지 않는다. 백업/snapshot 검토는 이 경로의 선행 조건이 아니다.

H05/H06/H08의 외부 입력이 없더라도 계약·어댑터·합성 테스트는 개발할 수 있다. 선행 관계가 있는 실제 실행을 건너뛰어 인수 완료로 만들지 않는다. 의존하지 않는 H07 모델 관리처럼 진행할 수 있는 단위로 이동하고 필요한 입력을 목록으로 보고한다.

## 플랫폼별 Streamlit 화면

| 화면 | 작업 시점·위치 | 완료 조건 |
|---|---|---|
| Camera | 기존 src/platform/camera/test_streamlit 유지. H04/H05의 API 완료 뒤 확장 | 현재 CRUD 회귀 유지. 실제 API readiness/계약 확인, 실패·멱등 재시도·세션 상태 표시. 환경은 전용 venv, 브라우저 인수는 접근 가능 시 별도 |
| Model | H07 CRUD 공개 API 완료 직후 model/test_streamlit | 모델/버전 관리·조회·상태·실패 원인. H08 뒤 실제 배포/readiness 표시, 가짜 inference 성공 금지 |
| Analysis | H09 작업 관리 API 완료 직후 analysis/test_streamlit | 생성/시작/중지·상태/실패·source/model 참조·이벤트 확인. worker 상태를 DB 직접 조회하지 않음 |
| Operation | H11 조율 API 준비 시 operation/test_streamlit | 공개 API로 통합 흐름·부분 실패/재시도 검증. 실제 관제 제품 UI와 테스트 페이지의 목적 구분 |

테스트 화면만 먼저 만들어 준비되지 않은 업무 기능을 완성된 것처럼 보이게 하지 않는다. agent_project는 화면 방식의 참고이며 다른 프로젝트의 QA/GPU/workflow 실행 결과를 VMS 인수 근거로 사용하지 않는다. 외부 작업을 이유로 Jupyter 중계나 port 공개를 추가하지 않는다.

## 단위별 공통 완료 조건

1. 소유 플랫폼의 API/저장소/실행 책임과 입력·오류·version·멱등성 계약이 코드와 일치한다.
2. 핵심 정상·실패·권한·동시성·재시작 위험을 실제 변경에 맞게 검사한다. 단순 구현을 복제한 테스트나 불필요한 전체 재검사를 늘리지 않는다.
3. 비밀값·원본 영상·모델 가중치는 반환/로그/커밋하지 않는다. 권한 상실이나 실제 참조 사용 중 폐기/삭제를 성공으로 처리하지 않는다.
4. 코드·테스트·문서·manifest를 함께 갱신한다. 선행 조건, 실제 검증 환경, 결과, 미완료, 다음 단위를 docs/progress에 남긴다.
5. 승인된 범위에서 독립적인 다음 단위는 자동으로 진행한다. 운영 실행 범위·외부 입력·실제 인수 증거가 필요한 지점에서는 의존 작업을 멈추고 구체적으로 보고한다.

[현재 상태와 주의점](codex-handoff.md) · [원래 아키텍처/요구사항](../architecture/architecture-plan.md)
