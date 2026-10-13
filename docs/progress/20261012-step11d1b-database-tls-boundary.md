# 11-D1b — PostgreSQL TLS·역할·접속 출처 격리 검사

상태: 구현·로컬 실제 PostgreSQL 진단·대상 서버 Docker 격리 인수 완료 · 운영 TLS 미전환

## 시작 근거

2026-10-12 사용자가 D1a acceptance notes 압축 SHA8b04e277627ae6774dacd218ea7ff3786a163f189e02b03e882a75d51a0f9c9d를 OK로 확인하고 applied·written7·pending0으로 반영했다. 이력은 var/patch-backups/step11d1a-notes-en10vv3p, 서비스 재시작·runtime 활성화·DB schema 변경은 false다. 이번 source 기준은 manifest308f5939b4ec6ab1ccbdc2d62012c982565f2655edd2da40b8a95517e157914f·tracked488개다.

D1a 서버 Python23개·실제 socketpair TLS1.3·prepared → already_prepared·동일 후보/공개 인증서 hash와0700/0600 인수는 과거 검사 revision bee8f71859c99c31e81997009c950f7360e441b82eff3acf09420998430adf04에 그대로 묶인다. 이번 source나 합성 PKI의 hash로 바꾸지 않는다.

## 구현과 완료 기준

새 Go native test·Python runner/unit·격리 Compose를 추가했다. 동일 D1a 프로파일을 새 합성 키로 생성하고 CA signing key를 export하지 않는다. DB UID999, peer UID10001/10002/10003와 private RO volume, 새로운 internal network의 정적 IP 네 개를 요구한다. 기존 public runtime 두 역할 TLS opener와 maintenance mTLS opener를 실제 PostgreSQL에 연결한다.

TLS/role/session·source/target IP·DB·exact leaf·maintenance CN을 검사한다. 유효 비밀값을 가진 잘못된 출처, plaintext·wrong password·wrong CA/hostname·control DB·누락/wrong-CN client certificate, runtime CREATE/SET ROLE을 정확한 실패로 거부한다. runtime 컨테이너 재생성 뒤 동일 출처/공급/TLS를 다시 검사한다. source 전체 hash와 필수 구성요소5개·native peer3개·ordered phase9개·cleanup을 서버 완료 기준으로 둔다.

## 로컬 검증과 한계

Python runner unit18개가 통과했다. 실제 OpenSSL 프로파일·선별 export·wrong-CN 유효 체인·비밀 비공개·환경 scrub·partial/LOCAL/skip/fail transcript 거부·오류 stage·불확실한 network 생성 및 cleanup 실패를 확인했다. Python3.10 AST와 Compose 구조 검사를 통과했다.

Go1.25.1에서 endpoint3개와 maintenance HBA/config2개의 race 검사가 통과했고 전체 모듈 go vet가 통과했다. source의 앱 main·SQL migrations·현재 OpenAPI·운영 Compose는 변경하지 않았다. 관련 Go native test만 추가했으며 과거 전체 Go/네 플랫폼 smoke 결과를 이번 재실행 결과로 표시하지 않는다.

로컬은 UID map0→0만 지원하고 Docker CLI/daemon 및 별도 UID/RO mount를 사용할 수 없다. 테스트 전용 root 실행을 허용한 PostgreSQL17.11 SSL build와 별도 loopback 주소에서 실제 TCP/TLS·SCRAM·HBA를 진단했다. Go LocalTransport1개가 race로 PASS했고 runtime 두 역할·runtime 거부·maintenance target/control·maintenance 거부·다른 출처 거부의5개 LOCAL phase를 확인했다. Unix filesystem socket bind가 제한돼 로컬 fixture 초기화만 임시 TCP owner 규칙을 사용하고 검사 전에 완전한6개 HBA 규칙으로 바꿨다. target 서버 Docker fixture에는 Unix 초기화 경로와 표준 PostgreSQL 이미지를 사용한다.

실제 PostgreSQL이 leaf 외 issuer certificate도 보낼 수 있으므로 leaf hash와 신뢰 체인을 고정하며 PeerCertificates 길이를1로 제한하지 않는다. SCRAM+clientcert의 wrong CN은 실제28P01, missing certificate는28000을 확인했다. 생성 과정에서 한 로컬 실행은 후보 내용 변경 감지로 중단됐으며 무결성 검사를 약화하지 않았다. 후속 새 합성 fixture 실행의 성공만 인수 근거로 기록한다.

root 실행의 native guard는 별도 UID 조건으로 실제 실패했고 LOCAL/root 로그는 native parser에서 거부됐다. native separate UID·실제 RO named volume·DB PID1/mount·runtime 컨테이너 재생성·Docker 정리의 positive는 로컬에서 검증하지 못했다. 이후 아래 서버 인수로 확인했으며 로컬 미검증 상태는 그대로 보존한다. 모의 runner 결과는 orchestration unit 검증이며 native 운영/서버 인수가 아니다.

전달 패키지는 baseline 전체 hash·payload·dry run/적용/재적용·사용자 변경/신규 충돌·TLS/credential/authority/environment sentinel 보존과 현재 source gate를 검증한다. 생성 키·DB·실행 로그/바이너리를 압축본에 포함하지 않는다. 적용/실행 명령은 채팅에 둔다.

## 대상 서버 인수 — 2026-10-12

사용자 제공 simsys4090/sh_test 출력에서 전달 압축 SHA256 cb2117c6aa810a6b8a66bd24a899aeed53e3afc10534512126e015a7fa7d3704 검사가 OK였다. 패치는 applied·written11·pending0이며 서비스 재시작·runtime 활성화·schema 변경은 false다. 이력은 var/patch-backups/step11d1b-cu1_rfiw다. Python18개가1.926초에 OK였다.

격리 project vms-database-tls-test-168b1aee7dd6의 scope=camera_database_tls_role_source_native_postgresql, status=passed다. checked_revision은 f18af0cf9a0580c05609ff7a0585fb023e781220318bb18b4957ed368a4dd103이다. 필수 endpoint/HBA5개·native peer3개·native9개 단계·go race/vet가 모두 통과했다. 실제 두 역할 TLS·maintenance mTLS·exact leaf·role/source/DB/TLS identity·잘못된 인증/출처/권한 상승 거부·DB/peer UID/RO·runtime 재생성과 network/resources/synthetic input 정리를 인수했다. 합성 PKI 전용이며 운영 D1a 후보 파일은 읽지 않았다. [상세 서버 인수](20261012-step11d1b-server-acceptance.md)에 공개 JSON의 모든 true/false 범위와 경로를 기록한다.

## 남은 작업

서버 Docker 검사의 status=passed·phase9·필수8개·별도 UID/RO·재생성/정리를 받아 D1b 서버 인수를 완료했다. 운영 후보를 읽거나 IP를 예약하지 않았다. 최근 운영 인수 기준은 API0.7.0-device-delete/schema7/registry-only-v1/TLS off이며 이번 작업은 운영 상태를 재조사하지 않았다. 실제 운영 key/mount/role/source binding·TLS·schema9·OPEN admission·credential HTTP activation은 미완료다.

다음 단위는 11-D1c 운영 TLS 공급 위치·고정 endpoint/source의 구성 준비다. 키/DSN·authority·schema9 cutover·HTTP 실행 경로·IAM·실제 관리 사용 guard, ConnectionConfig·SourceSession·실장비/영상 및 model/analysis/operation 업무가 남는다. 백업 추가 설계·검토는 제외하고 Streamlit 브라우저 인수 보류·Jupyter 중계 미구현을 유지한다.

[운영 안내](../operations/camera-database-tls-boundary-check.md) · [ADR0022](../architecture/decisions/0022-camera-database-tls-isolated-boundary.md)
