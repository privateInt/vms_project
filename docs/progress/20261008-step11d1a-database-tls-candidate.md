# 11-D1a — DB TLS 인증서 후보 준비

상태: 코드·로컬 검사·전달 패키지 및 대상 서버 후보 생성/재실행 인수 완료

## 시작 근거와 범위

사용자가 11-C3 acceptance notes를 applied·written7·pending0으로 적용했다. 적용 이력은 var/patch-backups/step11c3-notes-xf9c7wi8이며 서비스 재시작·runtime 활성화·DB schema 변경은 false다. 이번 기준 manifest는 e982214e2eb088036f0b9701d7e7a745193d35f974e599f9eae91b686df17c62, tracked482개다. 11-C3 실제 서버 검사 revision 0b2891f179dddca6d3e43a09e253c915b7babd32b8a437fc6d61b5d3f4dd50aa와 192/567·필수47·phase8 PASS는 기존 인수 근거로 보존한다.

다음 TLS·endpoint/source 공급을 독립 적용 가능한 하위 단위로 나눴다. 이번은 실제 private CA·서버·유지보수 인증서 후보 생성과 로컬 TLS 검증을 완결한다. PostgreSQL/Docker 역할·source·HBA 인수와 운영 전환은 분리한다. 새로운 backup 작업을 선행 조건으로 넣지 않는다.

## 구현

Python 도구와 옆 unit test를 src/infra/tools에 추가했다. 현재 실행 계정의 private candidate-v1에 독립 RSA3072 세 키, CA/서버/유지보수 세 인증서와 고정 receipt를 최초 생성한다. 서버 DNS SAN·serverAuth, 유지보수 CN·clientAuth, CA pathlen0을 구분한다. 기존 후보는 byte·mode·mtime를 보존하며 다시 검증한다.

CLI 진입점에서 현재 manifest의 파일 hash를 확인한다. exclusive-create·준비 잠금·descriptor/no-follow·hash/profile·strict 체인·유효기간·재확인으로 불일치와 partial 상태를 거부한다. OpenSSL private 출력과 오류는 공개 결과에 전달하지 않는다. IP 세 값은 미예약 제안이며 후보 생성만으로 승인/고정 처리하지 않는다.

## 검증

Linux Python3.12.14·시스템 OpenSSL3.0.13·Python SSL OpenSSL3.5.8에서 private 임시 합성 후보를 사용했다. Python3.10 문법 호환도 확인한다. 실제 SSL socketpair mTLS와 TLS1.2/1.3, 잘못된 hostname·신뢰되지 않은 CA·client 인증서 누락·서버 인증서의 client 사용·TLS1.1 차단을 검사했다. 키 불일치, 실제 만료 leaf, 손상 PEM/receipt, symlink/hardlink/FIFO/owner/mode/잠금 경쟁, 생성 중단·파일 경쟁·디렉터리 교체·umask027과 공개 오류/결과의 비밀 비공개를 검사한다.

새 unit23개와 기존 key 준비/backup helper 회귀42개가 모두 통과했다. 과거 backup helper 회귀는 코드 보존 확인이며 추가 backup 개발·운영 backup 실행을 뜻하지 않는다. Python3.10 AST 문법 검사가 통과했다. 전달 도구8개 검사와 baseline482개·변경9개 적용/재적용·보호 sentinel·변경/신규 충돌·전체 hash·실제 CLI 후보 생성/재검증을 패키지 검사에 포함한다. 최종 전달은 해당 검사가 통과한 압축본이다. Go·현재 API·SQL·Compose 코드는 변경하지 않아 기존 Go/native/네 플랫폼 smoke 인수를 재실행 결과로 소급 표시하지 않는다. 운영 DB·credential key·DSN·authority·서비스와 실장비를 사용하지 않았다.

## 미완료와 다음 단위

대상 서버 Python23개·실제 socketpair TLS1.3·prepared → already_prepared에서 같은 후보/공개 인증서 hash·0700/0600 권한 보존을 인수했다. 당시 manifest SHA bee8f71859c99c31e81997009c950f7360e441b82eff3acf09420998430adf04와 후보 SHA 421c3e0a67ec6e47f3fdab270f7c7448351a42d9e21eb7accc9ab702e7cadc40를 [서버 인수 기록](20261008-step11d1a-server-acceptance.md)에 별도로 남긴다. 운영 최근 인수는 API0.7.0-device-delete/schema7/registry-only-v1/TLS off이며 이번 도구가 운영 상태를 재조회하지 않았다. candidate_ready는 실제 운영 owner·RO mount·CA/role/source binding·schema9·OPEN admission·credential HTTP 활성화를 입증하지 않는다.

다음 11-D1b 완료 기준은 이 PKI profile과 고정 endpoint/source 제안으로 disposable native PostgreSQL의 실제 TLS·역할·source 거부 경계를 검증하고 운영 공급 후보의 mount/owner 요구를 확정하는 것이다. 그 이후 키/DSN·authority·schema9 cutover·HTTP 실행 경로·운영 IAM·실제 관리 사용 guard를 진행한다. ConnectionConfig·SourceSession·실장비/영상과 model/analysis/operation 업무도 남아 있다. 백업 추가 설계·검토는 제외하고 Streamlit 브라우저 인수는 보류하며 Jupyter 중계는 만들지 않는다.

[운영 안내](../operations/camera-database-tls-candidate.md) · [ADR0021](../architecture/decisions/0021-camera-database-tls-candidate.md)
