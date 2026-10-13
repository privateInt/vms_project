# 11-D1c — 운영 TLS 공급 위치·고정 접속 구성 준비

상태: 구현·로컬23개 검사·서버 실제 공급/재실행 인수 완료 · 운영 TLS 미전환

## 시작 근거와 이번 완료 기준

2026-10-12 사용자가 D1b acceptance notes SHA a5a4d78df7db410e678af311c169a0d1a8074bea619f497f0d0eae68badf34c7을 OK로 확인하고 applied·written7·pending0으로 반영했다. 서비스 재시작·runtime 활성화·schema 변경은 false, 이력은 var/patch-backups/step11d1b-notes-2nmfn60y다. 이번 baseline은 manifest fc755d5d904f039c83144d58649e6fd9bbf692d965c3c7c7f07db1438aa5138e·tracked496개다.

D1b 서버 Python18개·필수 Go8개/native9개 phase·race/vet·UID/RO·재생성·정리의 native checked_revision은 f18af0cf9a0580c05609ff7a0585fb023e781220318bb18b4957ed368a4dd103으로 보존한다. D1a 후보421c3e0a67ec6e47f3fdab270f7c7448351a42d9e21eb7accc9ab702e7cadc40과 공개 인증서 SHA도 기존 bee8f71859c99c31e81997009c950f7360e441b82eff3acf09420998430adf04 인수 근거를 유지한다.

이번 단위는 인수 후보의 실제 공급 사본·프로세스별 소유권과 RO 볼륨 및 현재 상태에 대응하는 고정 주소 recipe를 준비하는 것이다. 운영 서비스 전환은 다음 별도 단위다. 기존 caller0700/0600 파일을 runtime UID에 직접 디렉터리 mount하는 대신 전용 볼륨에 필요한 파일만 복사한다.

## 변경

src/infra/tools에 준비 도구와 옆23개 test를 추가했다. 현재 process identity·schema7/API0.7/TLS off·소유 network·DB/runtime 주소와 비어 있는 maintenance 제안을 읽고 인수된 후보 receipt/공개 인증서·실제 SSL을 확인한다. 호스트 선별 사본0700/0600과 DB999/runtime65532/maintenance10002별 전용 local 볼륨0700/0400을 준비한다. CA signing key·credential 키·DSN·HBA·authority·DB 데이터는 복사하지 않는다.

network none의 일회용 helper만 실행하며 현재 DB immutable image와 tmpfs PGDATA를 사용한다. 새 볼륨 복사 helper는 CHOWN/DAC_OVERRIDE만 필요하고 각 검사 helper는 해당 UID·cap drop ALL·RO mount다. exact bytes·UID map/권한·실제 EROFS·다른 두 UID 접근 거부와 정확한 helper 정리를 요구한다. 기존 공급은 재검사만 하고 손상·불완전 상태는 수리하지 않는다.

주소 recipe는 현재 external storage network와 D1a DB/runtime/maintenance 제안을 명시한다. Compose config만 검사하며 recipe 서비스는 opt-in profile의 /bin/true다. 운영 배포 정의·네트워크 예약·API/DB 재시작은 포함하지 않는다. .env·현재 Compose·SQL·Go·실제 서비스/DB 상태는 보존한다. 후보/source/network/process/schema의 전후 재검사를 완료해야 성공한다.

## 로컬 검증과 한계

실제 OpenSSL 합성 PKI·key pair/체인·socketpair mTLS를 사용하는23개 Python test가 통과했다. 선별 export·CA signing key 제외·private metadata·권한/umask·symlink/hardlink·부분/손상 파일·wrong binding·재적용 보존·주소/peer/IPv6/aux 충돌을 검사했다. Docker orchestration fixture는 label·3개 volume·재실행 initializer 미호출·기존 partial 볼륨을 다른 생성보다 먼저 거부·입력/서비스 변경·exact probe 출력·불확실 run/cleanup·안전한 오류 출력을 검사했다. 첫 검사에서 role별 label 재사용 오류를 잡아 수정했고 전체23개를 다시 통과했다.

Python3.10 AST와 initializer3개·full/own-only probe6개의 shell syntax가 통과했다. 로컬 Docker daemon·별도 UID/실제 RO 공급 볼륨·Compose config 실행은 사용할 수 없어 검증하지 못했다. mock helper의 성공을 실제 native 공급 인수로 표시하지 않는다. Go/main/SQL/운영 routing은 변경하지 않았으며 과거 Go race/vet·플랫폼 smoke를 이번 재실행 수로 합산하지 않는다.

전달 패키지는 전체 baseline/source/payload hash·dry run/적용/재적용·사용자 변경/신규 충돌·환경/TLS/credential/authority sentinel 보존·current source gate를 검증한다. 실제 키·DB·실행 자료는 압축본에 포함하지 않는다. 적용/준비/재실행 명령은 채팅에서 제공한다.

## 서버 인수 — 2026-10-12

사용자 제공 출력에서 전달 압축 SHA01c3b0e189579f6b8182e48ca547c5465888a381f8a0986cdc1180842bda770c가 OK였다. 패치는 applied·written10·pending0, 이력은 var/patch-backups/step11d1c-tvq1a4kg다. 재시작·runtime 활성화·schema 변경은 false다. Python23개가2.430초에 OK였고 준비 결과는 prepared → already_prepared다.

두 실행의 checked_revision은5d2f6e3ce0016e173157051c44540cc9cbc8274d8cf567711985701c9815c9d7, candidate SHA는421c3e0a67ec6e47f3fdab270f7c7448351a42d9e21eb7accc9ab702e7cadc40, supply SHA는22ccacd8f4ec043219d2eef4f21378772c0705e26b1b2fa906d5b2b57aad4a6e다. 첫 생성3개·재실행0개에서 같은 볼륨 이름과 각 probe3/denial6·UID/RO/exact bytes·cross UID denial·helper 정리·Compose config·현재 identity·원본/서비스 보존·실제 socketpair mTLS를 인수했다. 로컬 UID/RO·Compose CLI 미검증 이력은 그대로 보존하며 서버 성공으로 바꾸지 않는다. [상세 인수](20261012-step11d1c-server-acceptance.md)에 공개 결과 전체 범위와 주소·볼륨 이름을 기록한다.

고정 주소 자료는 같은 network ID와192.168.96.0/20에서 DB.2/runtime.3/maintenance.4를 보존했다. maintenance는 현재 미연결이며 address_state=observed-recipe-unreserved, address_reservation_verified=false다. recipe_is_deployable와 운영 변경/활성화는 모두 false다. 원격 공급 receipt/volume 파일을 직접 읽은 결과는 아니다.

## 다음 단위

서버 공급·재실행 완료 기준을 충족했다. 이후 실행 실패로 부분 공급이 남을 경우에는 자동 수리·교체·삭제하지 않는 정책을 유지한다.

현재 실제 운영 mount/TLS·고정 주소 예약·credential 역할/DSN·schema9·admission/HTTP 활성화는 미완료다. 다음 단위는 11-D1d 현재 schema7/registry와 TLS 전환의 격리 리허설이다. 공급 파일과 고정 주소 구성을 적용하기 전에 schema7 경로·역할/source/HBA·기존 등록 API의 호환성을 확인하고 그 이후 운영 전환으로 진행한다. 운영 IAM·관리 사용 guard·ConnectionConfig·SourceSession·실장비/영상·다른 플랫폼 업무가 남는다.

백업 추가 설계·검토는 제외한다. Streamlit 브라우저 인수 보류·Jupyter 중계 미구현을 유지한다.

[공급 안내](../operations/camera-database-tls-supply.md) · [ADR0023](../architecture/decisions/0023-camera-database-tls-supply-volumes.md)
