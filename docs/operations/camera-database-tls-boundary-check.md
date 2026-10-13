# PostgreSQL TLS·역할·출처 격리 검사 — 11-D1b

상태: 코드·로컬 진단·대상 서버 Docker 격리 인수 완료 · 운영 TLS 미전환

## 실행 전제와 파일

도구는 src/infra/tools/test_camera_database_tls_boundary.py, 옆 unit은 test_camera_database_tls_boundary_unit.py다. Linux Python3.10 이상·시스템 OpenSSL·로컬 Unix Docker daemon/Compose를 사용한다. 검사 전 현재 전체 source manifest와 11-D1a 서버 인수 근거를 확인한다. 공용 Conda/Jupyter에 의존성을 설치하거나 기존 서비스·DB·credential 키·TLS 후보 파일을 읽지 않는다. 적용/실행 명령은 채팅에서 제공한다.

Compose는 src/infra/postgresql/compose.database-tls-test.yaml이며 Go native test는 camera/internal/storage/database_tls_supply_native_test.go다. 표준 postgres17.11-bookworm과 기존 golang1.27.1-bookworm을 사용한다. 새 난수 project 이름과 새 내부 network·named volumes·tmpfs PGDATA만 생성한다. 기본 bridge의 새 subnet 안에서 네 IP를 고정하며 운영 IP 예약은 수행하지 않는다. host port는 없다.

| 시험 프로세스 | UID/GID | 허용 인증·공급 |
|---|---|---|
| DB PID1 | 999:999 | RO 서버 TLS3개·외부 HBA/init control, CA signing key 없음 |
| runtime | 10001:10001 | RO endpoint/CA/wrong-CA와 writer/budget DSN, 별도 두 SCRAM/TLS 역할 |
| maintenance | 10002:10002 | RO endpoint/CA·유효 client cert/key·maintenance DSN, 지정 출처의 SCRAM+mTLS |
| 다른 출처 probe | 10003:10003 | negative fixture 전용 유효 합성 DSN/client key로 출처 거부 확인 |

host 임시 디렉터리와 생성 파일은0700/0600이다. Docker fixture owner가 private named volume에 복사하고 client/DB 입력은0700/0400으로 소유자를 분리한다. runtime에는 maintenance secret이나 owner DSN을 넣지 않는다. maintenance와 다른 출처의 합성 runtime DSN 사본은 유효 비밀값을 사용한 negative 검사 전용이다. 이 구성을 운영 secret 공급으로 재사용하지 않는다.

## 검사와 PASS 조건

builder는 전체 모듈 go vet와 storage race binary를 만들고 기존 endpoint3개·maintenance HBA/config2개를 검사한다. native 단계는 runtime supply/UID/RO → runtime 두 역할 TLS → runtime 거부 → maintenance supply/UID/RO → maintenance target/control mTLS → maintenance 거부 → 다른 출처 supply/UID/RO → 유효 자격증명 출처 거부 → runtime 컨테이너 재생성·재접속의9개다.

정상 접속은 기존 public opener로 실제 DB user/session·database·server/client IP·TLS1.2 이상·maintenance DN·생성한 exact leaf hash를 확인한다. runtime의 schema CREATE/maintenance SET ROLE은42501로 거부해야 한다. control DB·plaintext·잘못된 source는28000, 잘못된 password는28P01이다. maintenance client 인증서 누락은28000, 올바른 비밀번호/CA-signed clientAuth이지만 잘못된 CN은SCRAM 결합 경로에서28P01로 거부됨을 로컬 실제 PostgreSQL에서 확인했다. CA/hostname은 typed x509 원인을 요구한다.

출처 규칙은 HBA의 정확한 /32와 hostssl을 사용하며 그 뒤 IPv4/IPv6 reject를 둔다. HBA disk parse뿐 아니라 새 positive/negative 인증을 검증한다. packet filter나 기존 session drain·restore fence를 이 검사로 입증하지 않는다. maintenance 쪽은 public opener의 입력 CN 검사만으로 끝내지 않고, raw negative transport로 실제 server의 잘못된 CN 거부를 확인한다.

Go JSON에서 각 native parent의 run/output/pass와 필수9개 phase의 정확한 순서를 확인한다. skip·fail·미완성·중복·LOCAL prefix·다른 parent의 출력은 거부한다. 필요한 세 native peer와 기존 구성요소5개가 모두 PASS여야 한다. 실패하면 다음 단계를 진행하지 않고 failed_stage·last_completed_stage·exit code를 private report에 남긴다.

## 결과·정리와 운영 미완료

report와 log는 var/camera/database-tls-checks 아래0600이며 scope는 camera_database_tls_role_source_native_postgresql이다. 공개 JSON에는 비밀값·OpenSSL stderr·DSN·private key/hash를 넣지 않는다. 성공에는 go_race_passed·go_vet_passed·native_tls_phases_passed=9·별도 UID/RO·컨테이너 재생성과 cleanup true가 필요하다. 실제 Go/crypto/Docker 오류의 원문은 private log에서만 확인한다.

성공/실패 모두 해당 project의 compose down·volumes 정리와 정확한 project label/name network 제거를 수행한다. network 생성의 불확실한 timeout도 소유 label을 확인한 뒤 정리한다. 생성 입력·CA signing key·password는 임시 디렉터리와 함께 제거한다. 정리가 실패하면 전체 status=failed이며 성공 phase summary를 내보내지 않는다.

합성 PKI·DB·주소의 PASS는 운영 후보 key/owner/RO mount나 실제 운영 IP/source 승인 증거가 아니다. production_candidate_files_read·production_services_modified·production_database_modified·production_hba_modified·production_network_modified·database_tls_activated·production_endpoint_and_sources_reserved·production_supply_ready·activation_allowed·credential_api_activated·business_runtime_ready는 false다. 최근 운영 인수 API0.7.0-device-delete/schema7/registry-only-v1/TLS off를 이번 도구가 재조회하거나 변경하지 않는다.

2026-10-12 사용자 제공 서버 JSON에서 status=passed, Python18개·필수 endpoint/HBA5개·native peer3개·native9개 단계·race/vet와 전체 자원 정리를 인수했다. 검사 revision은 f18af0cf9a0580c05609ff7a0585fb023e781220318bb18b4957ed368a4dd103이며 기록 패치의 새 revision으로 바꾸지 않는다. 실제 두 역할 TLS·maintenance target/control mTLS·exact leaf·역할/source/DB/TLS identity, 인증/출처/권한 상승 거부, DB/peer 별도 UID·RO mount와 runtime 재생성을 확인했다. 원격 log/report 파일을 직접 읽은 결과는 아니다. 로컬에서 검증하지 못한 별도 UID/RO와 Docker 재생성은 이번 서버 검사 근거로만 표시한다.

다음 단위는 11-D1c 실제 운영 TLS 공급 위치와 고정 endpoint/source 구성 준비다. 키/DSN·authority·schema9·HTTP activation·IAM·managed reference usage guard는 여전히 남는다. 백업 추가 검토는 제외하며 Streamlit 브라우저 인수 보류·Jupyter 중계 미구현을 유지한다.

설정 의미는 [PostgreSQL17 HBA 문서](https://www.postgresql.org/docs/17/auth-pg-hba-conf.html)와 [서버 SSL 문서](https://www.postgresql.org/docs/17/ssl-tcp.html)를 확인했다. 일반 문서가 이 프로젝트의 실제 실행 인수를 대신하지 않는다.

[ADR0022](../architecture/decisions/0022-camera-database-tls-isolated-boundary.md) · [진행 기록](../progress/20261012-step11d1b-database-tls-boundary.md) · [서버 인수](../progress/20261012-step11d1b-server-acceptance.md)
