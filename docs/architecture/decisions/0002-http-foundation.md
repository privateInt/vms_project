# ADR 0002 — Go HTTP 실행 기반

날짜: 2026-09-29 · 상태: P0-A 범위에서 채택, 미디어·AI 기술 선택은 미확정

## 배경과 결정

네 플랫폼의 실행·설정·계약을 먼저 확인할 수 있도록 Go 표준 라이브러리로 별도 HTTP API를 만든다. 네트워크 I/O와 프로세스 수명 관리가 주된 현재 범위에 적합하고, 외부 Go 의존성 없이 재현 가능한 시작점을 만들 수 있다. 이 결정은 Go가 모든 영상·AI 처리에 가장 빠르다는 판단이 아니다.

외부 조회와 초기 계약 검증은 REST/JSON + OpenAPI 3.1로 제공한다. 아직 플랫폼 간 실행 호출이 없으므로 gRPC·이벤트 브로커를 설치하지 않는다. 후속 세션·프레임·분석 계약을 확정하면서 내부 제어 호출의 gRPC와 durable event/outbox를 구체화한다. 프레임 원본은 JSON API나 일반 업무 이벤트에 싣지 않는다.

## 현재 구현

- 네 API의 별도 실행, 환경 설정, 요청 ID, 제한된 구조화 로그, SIGTERM 종료.
- 비즈니스 API의 개발용 Bearer 토큰 인증, 64 KiB 본문 제한, JSON 형식과 도메인 필드 검증.
- CCTV·XR 소스와 분석 작업 입력 검증. 저장이나 실제 장비·모델 조회는 없음.
- readiness는 HTTP 기반만 나타내며 `business_runtime_ready`는 false. 예정 기능은 manifest에 planned로 표시.

## 후속 전환 조건

사용자·테넌트가 생기면 고정 개발 토큰을 OIDC/RBAC와 서비스 인증으로 교체하고 TLS 종료 지점을 구성한다. 저장소·모델 런타임이 생기면 의존성별 준비 상태, deadline·retry·멱등성, 감사 기록을 정의한다. 단일 토큰을 운영 IAM으로 사용하지 않는다.

Go/Pion 수신, 미디어 엔진, Python 추론 런타임, 스마트글래스 앱 언어는 P0-T와 실제 장비 검증에서 선택한다. 녹화·트랜스코딩·GPU 추론을 Go HTTP 서버에 직접 추가하는 것을 기본값으로 삼지 않는다.

참고: [Go net/http](https://pkg.go.dev/net/http), [Compose include](https://docs.docker.com/reference/compose-file/include/). Docker 이미지 빌드·컨테이너 실행은 현재 제작 환경에서 검증하지 않았다.
