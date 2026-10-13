# ADR0025 — schema7 운영 TLS의 별도 준비 자료와 외부 control 공급

상태: 채택 · 준비 코드/로컬 검사 완료 · 운영 인수 대기 · 2026-10-12

## 결정

D1d가 같은 운영 이미지의 schema7·등록 이력·실제 TLS·재생성을 서버 격리 환경에서 인수했으므로 기존 registry 경로에 한정한 운영 TLS를 다음 단위로 준비한다. schema9 credential 활성화와 묶지 않는다. 준비 도구는 현재 source/image/UID/network/HTTP/data와 D1c 공급을 재검사하고 별도 TLS DSN·HBA/ident·Compose·receipt와 새 private control volume을 만든다. 실제 서비스 전환은 다음 도구가 담당한다.

현재 registry password를 유지해 runtime SCRAM/verify-full DSN을 만들고 migrator는 기존 camera_migrator와 maintenance CN의 cert map을 사용한다. secret 파일 bind가 UID remap을 제공한다고 가정하지 않으며 기존 private0700 부모/0444 file 방식과 별도 UID/RO 공급을 사용한다. D1c의 key volume은 재생성·수리하지 않는다. CA signing key와 credential 암호화 키는 이번 준비 입력이 아니다.

HBA/ident는 PGDATA 밖 새 control volume에999:999/0400·RO로 공급한다. server TLS는 기존 D1c database volume을 RO로 참조한다. DB/API/migrator UID는999/65532/10002를 명시한다. 기존 data volume·운영 image를 유지하고 신규 migration8/9가 들어간 개발 source image를 운영 schema7에 시작하지 않는다.

기존 default network의 Compose 소유 정의를 유지해 다른 플랫폼 include의 암묵적 default와 동일하게 해석한다. storage/data/TLS/control은 external 참조이며 실제 network ID·source IP·HTTP 게시·다른 플랫폼 service를 준비 전후 검사한다. 미래 DB/TLS 프로세스가 실행되는 것과 offline probe는 별도 완료 기준이다.

준비 실패·변조·권한/경로/주소 변경을 자동 수리하지 않는다. receipt는 실제 준비 source와 현 상태를 묶으며 후속 도구가 다시 확인해야 한다. 준비 자료가 있다는 이유로 운영 승인이나 business readiness를 true로 바꾸지 않는다. 사용자 지시대로 백업 추가 작업을 제외한다.

## 검증과 결과

신규 Python27개는 실제 합성 PKI/파일/권한과 Docker fixture로 재실행·변조/중단·source/HTTP/data 경계·Compose 의미·비밀 비공개를 검사한다. 기존 후보/공급과 D1d 회귀도 수행한다. 로컬 Docker/Compose native 실행은 하지 못했으며 서버 준비 인수에서 확인한다. Go/API/SQL와 현재 운영 경로는 바꾸지 않았다.

근거: [PostgreSQL17 인증서/CN map](https://www.postgresql.org/docs/17/auth-pg-hba-conf.html), [PostgreSQL17 TLS 공급](https://www.postgresql.org/docs/17/ssl-tcp.html), [Compose include 경계](https://docs.docker.com/reference/compose-file/include/), [Compose network 정의](https://docs.docker.com/reference/compose-file/networks/).

[11-D1e 기록](../../progress/20261012-step11d1e-registry-tls-preparation.md) · [D1d ADR0024](0024-camera-registry-schema7-tls-rehearsal.md)
