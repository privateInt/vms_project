# ADR0021 — DB TLS 후보 생성과 운영 공급의 분리

상태: 채택 · 2026-10-08 · 11-D1a

## 선택과 이유

11-C3 실제 admitted store·mTLS 관리 HTTP의 서버 격리 인수를 마쳤지만 운영 PostgreSQL은 최근 인수 기준 TLS off/schema7이다. 먼저 검토하고 재사용할 수 있는 PKI 후보를 만든다. 11-D1a 완료 기준은 private 최초 생성·기존 후보 보존·인증서 검증·실제 로컬 mTLS다. PostgreSQL 역할/source/HBA와 Docker 공급의 인수는 11-D1b로 분리한다.

현재 호스트 계정 소유의 0700 staging 디렉터리에 별도 CA·DB 서버·유지보수 클라이언트 키와 인증서를 만든다. 키는 각각 독립 RSA3072, CA는 pathlen0·397일, leaf는 CA:FALSE·365일이다. 서버에는 serverAuth와 camera-db.vms.internal DNS SAN, 유지보수에는 clientAuth와 camera_maintenance CN을 부여한다. CA private key는 서버나 runtime mount에 포함할 공급 파일이 아니다.

명시적 apply가 필요하다. 기존 후보는 hash·profile·키 일치·체인·유효기간을 재검사하고 바꾸지 않는다. 손상·중단·권한 불일치를 자동 수리하거나 키를 자동 교체하지 않는다. 실제 SSL socketpair로 검사하며 리스닝 포트와 기존 credential 암호화 키·DSN·authority·DB에 접근하지 않는다.

## 후보와 실제 승인

후보 receipt는 운영 SupplyPlan이나 approved binding이 아니다. 이전 관찰 subnet의 IP 제안은 proposal-unreserved이며 현재 Docker 주소·충돌·예약·권한을 입증하지 않는다. 해당 값은 실제 접속 검사에 사용하지 않는다. staging 경로는 운영 control/HBA/PKI 위치의 승인도 대신하지 않는다. 이후 공급 단위가 endpoint/source와 실제 owner·mount·CA·role binding을 확인해야 한다.

운영 compose/main/SQL/schema·서비스는 변경하지 않는다. 후보 키를 로컬 TLS 검사에 로드한 사실과 운영 credential key/API 활성화를 구분한다. production_supply_ready·activation_allowed·database_tls_activated는 false다. 사용자 지시에 따라 백업 추가 설계·검토는 새 선행 조건으로 넣지 않는다.

[운영 안내](../../operations/camera-database-tls-candidate.md) · [진행 기록](../../progress/20261008-step11d1a-database-tls-candidate.md)
