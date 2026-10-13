# ADR 0016 — 유지보수 전용 HBA와 상호 TLS 경계

상태: 채택 · 2026-10-07 · 11-B3c3d2a 구현, 서버 native 인수 대기

## 결정과 보장

DB ALLOW_CONNECTIONS 차단 뒤 실제 복원을 위해 target을 다시 열려면 새 연결을 지정한 유지보수 주체로 제한해야 한다. complete HBA 원본은 PostgreSQL data directory와 DB/key snapshot 바깥의 관리 경로에 둔다. 지정된 canonical source IP 한 개(/32 또는 /128), camera_maintenance 역할, target과 별도 postgres control DB에만 hostssl·SCRAM·clientcert=verify-full을 허용한다. local socket·그 밖의 IPv4/IPv6를 reject한다. target 이름은 인용해 all/replication 같은 HBA 키워드도 문자 이름으로 처리한다. include나 기존 허용 rule에 붙이는 fragment를 만들지 않는다.

유지보수 역할은 LOGIN SUPERUSER이면서 target owner인 d1 모델을 따른다. password와 client private key는 protected trusted deployment 입력이며 공개 API가 받지 않는다. OpenCredentialMaintenanceDatabase는 검토된 canonical endpoint/CA/서버 hostname, 명시적 verify-full URI, exact source bind, CN=camera_maintenance인 단일 leaf client certificate로 fresh 실제 TLS 연결을 확인한다. 환경 PG 설정, options, 다른 역할/DB/port, fallback을 거부한다. TLS1.2 이상이며 client cert DER와 CA roots를 복제한다. private key는 호출자가 immutable하게 유지한다. 현재 direct CA 발급 leaf만 지원한다.

InspectCredentialMaintenanceHBA는 deadline·정확한 durable FENCED/exclusive lease·같은 endpoint/profile, actual control session/current user/source/TLS/client DN/target owner 및 runtime role NOLOGIN을 검사한다. HBA의 canonical absolute path가 data directory 바깥인지, disk exact bytes·parse errors·prepared transaction 부재를 확인하고 FENCED를 다시 fsync한다. symlink/mount/backup topology와 host 운영자 신뢰는 배포 검토 책임이다. 이 함수는 접속 재개 영수증이 아니다.

## 적용 확인과 한계

pg_hba_file_rules는 disk 내용이고 reload 요청은 active policy 완료 증거가 아니다. 격리 테스트는 fresh 유지보수 control 접속의 성공, 올바른 password/cert라도 다른 주소에서 PostgreSQL 28000으로 거부, 잘못된 role·없는 cert·다른 CN·plaintext·Unix socket 거부를 실제로 확인한다. 별도 probe가 같은 유효한 합성 자격을 경계 전 성공하고 경계 후 실패해야 하므로 DNS/불량 password/network timeout을 차단 성공으로 세지 않는다. 그 proof를 확인한 runner만 test-only target reconnect phase를 실행한다. 신규 target 접속과 sentinel write, 새 control process/exclusive lease로 budget42·FENCED 보존 및 재차단까지 검사한다.

HBA는 PostgreSQL 인증 경계다. packet firewall/host 네트워크 차단, credential 탈취와 승인 source에서의 impersonation, privileged administrator의 재설정 방어를 주장하지 않는다. HBA 적용 이전 control DB의 다른 privileged 세션은 d1이 모두 제거하는 범위가 아니며 실제 복원 운영자는 control-plane 세션/관리자/host 권한의 독점도 확보해야 한다. 이번 새 정책 설치/reload/target reopen은 disposable fixture에만 있다. 제품용 설치·재개 orchestration, DB/key 복원과 fresh key·budget·incarnation·PREPARED→OPEN은 후속 d2b다. credential API와 전체 production restore fence는 활성화하지 않는다.

근거: [PostgreSQL17 HBA](https://www.postgresql.org/docs/17/auth-pg-hba-conf.html), [pg_hba_file_rules](https://www.postgresql.org/docs/17/view-pg-hba-file-rules.html), [client certificates](https://www.postgresql.org/docs/17/auth-cert.html). 서버 인수 기준은 [검사 안내](../../operations/camera-credential-boundary-check.md), 결과는 [진행 기록](../../progress/20261007-step11b3c3d2a-maintenance-hba-boundary.md)을 따른다.

CN mismatch는 유효한 password를 사용해 PostgreSQL SCRAM/clientcert 경로의 정확한 28P01을 요구한다. 다른 source/role·없는 cert·plaintext·Unix socket 거부는 28000을 요구한다. 특히 다른 IP의 positive-before/negative-after probe에서 28P01이나 network 오류를 허용하지 않는다. 유지보수 leaf subject는 CN=camera_maintenance 하나이며 PostgreSQL17의 actual client_dn 표기는 /CN=camera_maintenance다.
