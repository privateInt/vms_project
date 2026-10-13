# camera 외부 admission 기반 격리 검사

상태: 11-B3c2 구현·로컬 검증 및 서버 native Linux 인수 완료 · [인수 근거](../progress/20261007-step11ui1-camera-streamlit.md)

## 입력과 격리

src/infra/tools/test_camera_credential_admission.py는 완전한 project manifest/hash와 이번 foundation revision을 검사한 뒤 vms-credential-admission-test-임의값 project를 생성한다. src/infra/compose.credential-admission-test.yaml의 임시 authority/exchange volume만 사용한다. 운영 서비스·DB·실제 키·host admission 경로를 읽거나 수정하지 않는다. 별도 DB service/production network/포트/외부 volume은 없다. source mount는 read-only이며 복사한 작업 디렉터리에서 빌드한다.

## 검사 의미

golang:1.27.1-bookworm에서 admission package의 race test binary와 실제 cmd/test2json을 빌드하고 전체 module vet를 수행한다. raw parser/전이/CAS/IO 실패/소유권·mode·link·경로·고정 lock 교체/별도 process의 drain·강제 종료 검사를 실행한다. helper나 marker 없는 selector pass만으로 native 인수를 표시하지 않는다.

prepare phase는 UID0:GID10001의 directory0750/file0640에 합성 OPEN metadata와 고정 lock 영수증을 생성한다. 이 OPEN은 DB 준비나 실제 credential 사용을 주장하지 않는 mount fixture다. runtime phase는 별도 UID10001:GID10001·capability 없음·read-only root/volume·network 없음으로 공개 AcquireReadOnly를 호출한다. 실제 statfs read-only, UID 분리, 각자 독립 descriptor, 유지보수 호출 및 metadata 쓰기 거부를 확인한다. 두 phase의 marker와 Go test pass 순서가 모두 필요하다.

## 결과와 실패

var/camera/credential-admission-checks 아래 private log/report를 저장한다. required admission tests 17개와 prepare/read 두 phase의 완전한 transcript·프로젝트 미변경·cleanup까지 성공하면 passed다. 오류/skip/불완전 marker·source 변경·cleanup 실패는 passed를 취소한다. 실패 보고에는 고정 코드와 failed_stage/last_completed_stage 및 실제로 받은 exit code만 넣는다.

성공/실패 모두 자체 project down/volume 제거를 시도한다. runtime volume은 metadata만 포함한다. host 환경의 COMPOSE_/CAMERA_/VMS_ADMISSION_ 변수를 제거하고 빈 env-file을 사용한다. 이 검사 성공은 운영 admission 경로를 생성하거나 production_restore_fence_implemented를 true로 바꾸지 않는다.

## 이후 인수

schema9 DB marker·migration/profile 정규 hash·actual key loader receipt·CredentialStore 전체 작업 구간 lease·계정/세션/복원 제어는 후속 통합이다. 이후 운영 host UID/GID·검토된 외부 경로·고정 lock receipt 공급·preflight/격리 복원/실제 전환을 별도 인수한다. 현재 운영 schema7/API0.7.0-device-delete와 schema8 저장소 구현을 이 패치가 전환하지 않는다. 명령은 채팅에서 제공한다.
