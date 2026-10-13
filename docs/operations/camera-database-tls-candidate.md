# DB TLS 인증서 후보 준비 — 11-D1a

상태: 로컬 구현·검증 및 대상 서버 후보 생성/재실행 인수 완료 · 운영 TLS 미전환

## 실행 전제와 결과

도구는 src/infra/tools/prepare_camera_database_tls_candidate.py다. Linux Python3.10 이상, /proc/self/fd, SSL socketpair, 시스템 OpenSSL을 사용한다. 공용 Conda/Jupyter 환경에 패키지를 설치하지 않는다. CLI는 현재 전체 manifest 파일과 11-C3 서버 인수 근거를 확인한 뒤 실행한다. 사용자 적용·실행 명령은 채팅에서 별도로 제공한다.

| 생성 항목 | 위치·권한·용도 |
|---|---|
| 준비 디렉터리/잠금 | var/camera/database-tls-candidates, 현재 계정 소유 0700 / .prepare.lock 0600 |
| 후보 디렉터리 | candidate-v1, 현재 계정 소유 0700 |
| CA | ca.pem·ca.key, 각각 0600, 이번 후보 전용 CA |
| DB 서버 | server.pem·server.key, 각각 0600, serverAuth·DNS SAN |
| 유지보수 | maintenance.pem·maintenance.key, 각각 0600, clientAuth·camera_maintenance CN |
| 후보 receipt | candidate.json 0600, 고정 profile·각 파일 hash·미예약 endpoint 제안 |

apply 없이 새 디렉터리·키를 만들지 않는다. 최초 성공은 prepared, 재실행은 already_prepared, 기존 후보의 읽기 검증은 validated다. 후보가 없으면 not_prepared·EXPLICIT_APPLY_REQUIRED이며 CLI exit2다. 새 키는 OpenSSL의 캡처된 결과를 exclusive-create 파일에만 쓰고 fsync한다. 사용자 파일을 덮어쓰지 않는다. 생성 파일은 코드/패치 압축본에 포함하지 않는다.

서버명 camera-db.vms.internal은 TLS 검증용 제안이며 DNS 등록을 수행하지 않는다. receipt의 DB192.168.96.2:5432/runtime192.168.96.3/maintenance192.168.96.4는 이전 관찰 subnet의 미예약 제안이다. 현재 IP를 재관찰하거나 고정한 결과가 아니다. 이 단위의 TLS 검사는 IP 제안을 사용하지 않는다.

## 검증과 출력

전체 파일 집합·owner·mode·일반 파일·단일 link·크기·읽는 동안 변경, receipt와 내용 hash를 확인한다. RSA3072 profile·독립 public key·certificate/key 일치·CA/leaf constraints·정확한 EKU·서버 DNS SAN·유지보수 CN·strict 체인·현재 유효기간·최소 하루 잔여 유효기간을 검사한다.

실제 TLS1.2 이상 socketpair에서 상호 인증과 양방향 application byte 교환을 수행한다. 공개 결과에는 두 leaf DER SHA256과 CA PEM SHA256, 검증 상태만 포함한다. 잘못된 서버명, 신뢰 anchor 없는 CA, 클라이언트 인증서 누락의 실패도 확인한다. unit 검사는 TLS1.2 성공·TLS1.1 거부와 서버 전용 인증서의 client 사용 거부까지 포함한다. 리스닝 포트·Docker·PostgreSQL에 연결하지 않는다.

OpenSSL stderr·private key 원문·private key hash·DSN·OS 예외 원문은 출력하지 않는다. 깨끗한 OpenSSL 환경·고정 profile·호출마다 timeout30초를 사용한다. 검사 후 path chain을 다시 열어 디렉터리 교체와 내용 변경을 거부한다. root 또는 같은 계정의 비밀 접근을 막는 별도 보안 서비스는 아니다.

## 보존과 후속

실패·중단한 후보는 partial 상태로 남을 수 있으며 재실행은 이를 거부한다. 기존 후보를 지우거나 chmod·재생성·갱신하지 않는다. 만료/손상 파일이 있으면 그 사실을 확인하는 별도 수정 단위가 필요하다. CA private key는 staging에 남기며 향후 PostgreSQL/runtime 공급 목록에서 제외한다.

candidate_ready와 actual_socketpair_mtls_verified는 로컬 후보 검증이다. production_supply_ready·activation_allowed·runtime_mount_verified·database_tls_activated·endpoint_and_sources_reserved는 false다. candidate_private_keys_loaded_for_local_probe는 true이며 기존 운영 credential key는 읽거나 로드하지 않는다. 사용자 서버의 Python23개·TLS1.3·prepared → already_prepared·동일 후보/공개 인증서 hash·권한 보존을 [서버 인수](../progress/20261008-step11d1a-server-acceptance.md)에 기록했다. 당시 검사 revision을 새 기록 manifest로 바꾸지 않는다.

다음 11-D1b는 이 profile의 인증서와 endpoint/source 제안을 disposable PostgreSQL·Docker에 연결하고 source별 역할·HBA 거부와 실제 제한된 mount/owner를 검증한다. 운영 전환, 키/DSN·authority·schema9 공급, IAM·managed reference guard는 이후다. 백업 추가 검토와 Streamlit 브라우저 인수·Jupyter 중계는 이번 범위에 넣지 않는다.

[ADR0021](../architecture/decisions/0021-camera-database-tls-candidate.md) · [진행 기록](../progress/20261008-step11d1a-database-tls-candidate.md)
