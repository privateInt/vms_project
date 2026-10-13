# ADR0022 — TLS·역할·출처 공급의 격리 인수

상태: 채택 · 2026-10-12 · 11-D1b 코드/로컬 검증, 서버 Docker 인수 대기

## 선택

11-D1a의 PKI 후보 생성/재실행은 서버에서 인수했지만 실제 PostgreSQL·role/source·mount를 검증하지 않았다. 이번 단위는 같은 CA/RSA3072/serverAuth/clientAuth 프로파일을 새로운 합성 키로 생성하고 disposable PostgreSQL17.11에 공급한다. 운영 후보의 private key를 읽거나 사본으로 반출하지 않는다. 검사 대상은 TLS 접속 경계이며 credential schema/업무 HTTP를 배포하는 단위가 아니다.

Docker가 새 내부 네트워크의 subnet을 할당하고 DB·runtime·maintenance·다른 출처 probe의 서로 다른 IP를 그 네트워크 안에서만 고정한다. 운영192.168.96.x 제안은 그대로 미예약이다. 현재 운영 네트워크에 시험 컨테이너를 연결하지 않으며 호스트 포트를 게시하지 않는다.

runtime 두 역할은 지정 출처에서만 SCRAM/TLS로 시험 DB에 접속한다. maintenance는 별도 출처·UID에서 SCRAM과 clientcert=verify-full로 시험 DB와 postgres control DB에 접속한다. 다른 출처 probe에는 일부러 같은 유효 합성 자격증명을 공급해 올바른 비밀값만으로는 접근할 수 없음을 검증한다. 이 negative fixture의 credential 공유는 운영 공급 설계가 아니다.

## 공급과 인수 경계

서버 TLS·HBA/init control·runtime·maintenance·다른 출처의 named volume을 분리한다. CA signing key는 host 합성 생성 디렉터리에만 남고 입력 bind/컨테이너 volume에 내보내지 않는다. DB의 실제 PID1 UID/GID999 및 RO TLS/control mount와 client UID10001/10002/10003·0700/0400·실제 RO mount를 요구한다. runtime에는 maintenance key/DSN·owner DSN이 없다.

기존 public OpenCredentialAdmissionDatabase와 OpenCredentialMaintenanceDatabase를 실제 인증 성공 경로로 사용한다. role/session user·DB·server/client IP·TLS version·client DN·exact leaf hash를 확인한다. 권한 거부는 PostgreSQL SQLSTATE28000/28P01/42501, 잘못된 CA/hostname은 typed x509 실패를 요구한다. 연결 거부·timeout을 인증 경계 PASS로 세지 않는다.

런타임 컨테이너를 재생성한 후 동일한 고정 출처/파일/TLS로 재접속한다. Go JSON transcript에서 필수 구성요소5개·native peer3개와 순서대로9개 phase를 모두 요구한다. LOCAL 진단 prefix·skip·부분 실행·cleanup 실패는 native PASS가 아니다. 로컬 단일 UID 환경의 실제 PostgreSQL 검사는 별도 근거로 기록한다.

이번 HBA의 owner Unix socket trust는 disposable DB 초기화용이며 TCP owner 접근을 허용하지 않는다. maintenance SUPERUSER·sentinel table은 시험 fixture로만 생성한다. schema9 cutover·운영 권한/파일·admission·API 활성화나 운영 IAM을 구현/완료로 표시하지 않는다. 백업 추가 설계·검토는 사용자 지시에 따라 제외한다.

[운영 안내](../../operations/camera-database-tls-boundary-check.md) · [진행 기록](../../progress/20261012-step11d1b-database-tls-boundary.md)
