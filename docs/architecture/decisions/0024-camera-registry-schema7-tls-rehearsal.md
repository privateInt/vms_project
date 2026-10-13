# ADR0024 — 운영 schema7 이미지의 격리 TLS 전환 검사

상태: 채택 · 2026-10-12 · 서버 native 인수 완료 · 운영 TLS 미전환

## 문제와 선택

D1c의 별도 TLS 공급 볼륨 준비는 운영 API의 등록 경로가 TLS 전환 뒤에도 호환됨을 증명하지 않는다. 현재 개발 소스의 기본 마이그레이션·준비 상태·장치 삭제 저장소는 schema8을 요구하지만 운영 API0.7.0-device-delete 이미지는 schema7이다. 최신 소스로 새 API를 빌드해 검사하면 이번 schema7 전환과 자격증명 스키마 변경이 함께 진행된다.

따라서 현재 운영 API와 DB의 immutable image ID만 읽고 동일 이미지를 새 격리 프로젝트에 실행한다. 새 데이터 볼륨·PKI·역할 비밀번호·Bearer 토큰·내부 네트워크를 만들며 운영 키·후보·D1c 공급 볼륨은 읽거나 사용하지 않는다. Go transport probe는 현행 public Open을 사용하되 schema7의1~7 migration name/checksum을 읽기만 한다. 현행 CheckReady나 Migrate를 schema7 probe에서 호출하지 않는다. 운영 이미지의 실제 readiness는 HTTP로 확인한다.

## 인증과 전환 경계

런타임은 고정 source의 camera_runtime/SCRAM과 verify-full 서버 인증서를 사용한다. 기존 camera_migrator 역할과 D1a 프로필의 client CN=camera_maintenance는 이름이 다르다. PostgreSQL17.11 실측에서 SCRAM 행에 map 옵션을 지정하면 HBA가 거부됐다. 유지보수 source의 migrator 행에는 cert map=registry_migrator를 사용하고 pg_ident의 exact camera_maintenance→camera_migrator 한 행으로 인증한다. TLS migrator 인증은 인증서 기반이며 SCRAM 이중 인증으로 표시하지 않는다. bootstrap의 migrator 비밀번호와 DSN에 보존된 비밀번호는 cert 인증에서 검증하지 않는다. 런타임의 잘못된 비밀번호 거부는 별도로 검사한다. migrator에 새 역할이나 superuser 권한을 부여하지 않는다.

PKI·HBA·ident는 PGDATA 밖의 역할별 RO volume이며 DB999/runtime65532/maintenance10002/offsource10003을 분리한다. 런타임 native probe는 실제 API 컨테이너 안에서 실행하여 PID1의 UID/GID65532도 확인한다. probe 실행 파일은 scratch API 이미지에서도 실행하도록 CGO=0으로 빌드한다. native peer probe에 race를 적용했다고 주장하지 않으며 별도 순수 Go policy unit은 race로 실행한다. 전체 모듈 vet도 실행한다.

2026-10-12 readiness 재실행 실패 후 API의 internal-only network 구성을 수정했다. 운영 구성과 같이 테스트 API에는 별도 normal bridge HTTP망과 internal DB망을 연결한다. HTTP망은 API에만 붙이고127.0.0.1 포트만 게시하며 DB·maintenance peer는 internal DB망과 source pin을 유지한다. API 시작/전환/두 재생성 지점에서 실제 Docker NetworkSettings.Ports·PortBindings·image/project/network/source를 확인한다. 준비 상태 조건은 완화하지 않는다. raw server mapping이 미제공된 현재 결과는 internal-only 게시 문제와 일치하는 구성 결함의 수정이며 native 원인/전환 완료 인수가 아니다. [네트워크 수정 기록](../../progress/20261012-step11d1d-http-network-fix.md)에 증거와 한계를 기록한다.

plaintext 상태에서 장치·소스 생성/수정/삭제·활성 자식 거부·재시도와 최초 멱등성 이력을 준비한다. API를 중지하고 runtime/migrator 세션0을 확인한 뒤 같은 격리 데이터 볼륨의 DB를 TLS로 재생성한다. mTLS migration 재실행은 version7/applied0이어야 한다. 모든 registry/profile/journal fingerprint와 권한을 비교하고 최초 응답 재생·조회·목록·새 TLS 쓰기를 검사한다. API와 DB/API의 추가 재생성 뒤에도 같은 검사를 수행한다.

## 검증과 한계

로컬 Python22개·순수 Go policy race1개·전체 vet·CGO=0 probe 빌드·실제 PostgreSQL17.11의 LOCAL transport5개 phase를 확인했다. LOCAL transcript와 root UID 실행은 native 인수로 인정하지 않는다. Docker·현재 운영 이미지의 HTTP 전환·실제 분리 UID/RO mount는 대상 서버 리허설에서 검증한다. 결과는 runner10개 phase와 native transport5개 phase를 별도로 기록한다.

사용자 지시에 따라 백업·dump/restore·추가 복구 절차를 이번 범위와 선행 조건에서 제외한다. 운영 활성화·schema9/admission/credential main 연결·IAM·실장비·Streamlit 브라우저 인수는 이번 완료 기준이 아니다.

HTTP ID/network 수정 후 서버 revision1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159의 전체 격리 리허설을 인수했다. Python45개·policy race1개/vet·native peer3개/transport5개 phase·전환10개 phase·실제 HTTP 게시4개·정리가 통과했다. 같은 image의 schema7/모든 이력·TLS/source/UID/RO·재생성을 확인했으며 native probe race=false와 운영 활성화/변경 false를 유지한다. 상세 근거는 [서버 인수](../../progress/20261012-step11d1d-server-acceptance.md)를 따른다. 앞선 로컬/실패 기록은 해당 시점의 이력으로 보존한다.

근거: [PostgreSQL17 인증서 인증](https://www.postgresql.org/docs/17/auth-cert.html), [SSL](https://www.postgresql.org/docs/17/ssl-tcp.html), [D1c 서버 인수](../../progress/20261012-step11d1c-server-acceptance.md), [검사 안내](../../operations/camera-registry-tls-cutover-check.md).
