# camera credential 작업 lease 격리 검사

상태: 서버 native 프로세스·RO authority 통합 인수 완료 (2026-10-07)

## 범위와 전제

src/infra/tools/test_camera_credential_operations.py는 11-B3c3b 서버 인수 및 이번 manifest revision과 전체 source hash를 확인한다. vms-credential-operations-test-임의값으로 새 project를 만들고 내부 network, tmpfs PostgreSQL, exchange/control volume만 사용한다. 포트를 publish하지 않으며 production DB/network/.env/key/authority 경로를 연결하지 않는다. COMPOSE_/CAMERA_/VMS_BINDINGS_/VMS_ADMISSION_/VMS_OPERATIONS_/PG host 설정을 제거한다.

서버의 Docker Compose와 image/dependency 다운로드가 필요하다. 이미지 버전은 기존 인수의 golang1.27.1-bookworm, postgres17.11-bookworm이다. local Docker/UID namespace 제약을 우회했다고 native 인수를 표시하지 않는다.

## 검사 순서

1. 전체 module vet와 storage race binary/actual cmd/test2json을 빌드한다.
2. 합성 key bundle와 임시 CA/server certificate/key fixture를 만들고 server key 소유권을 postgres 계정으로 준비한다.
3. TLS1.2 이상 DB를 시작하고 전체 module race, 기존 native13개 및 새 operation unit/실제 권한 상실 검사를 실행한다.
4. 기존 binding native 검사를 UID10001·RO key mount에서 실행한다. 두 역할의 actual TLS·CA/hostname/downgrade·marker/key/profile mismatch 검증을 유지한다.
5. 새 operation maintenance fixture가 RW authority에서 최초 FENCED를 bootstrap하고 실제 stable identity를 pin한다. 같은 volume의 다른 RO mount를 이용하는 UID10001·effective capability0 자식이 application의 공개 승인 생성자/업무 메서드를 호출한다. owner는 합성 record로 PREPARED/OPEN을 커밋한다.
6. error/panic/cancel의 자원 정리, create/write replay/reference/revoke/revoke replay/append 도중 exclusive lease timeout과 메서드 반환 후 정상 획득을 확인한다. append는 별도 budget 커밋 이후 두 번째 authorization에서 일시 정지한다.
7. 다음 append를 같은 지점에서 SIGKILL하고 wait한다. use3은 보존되고 중단한 버전/journal은 추가되지 않는다. maintenance는 drain 후 FENCED를 커밋한다. 과거 record를 pin한 새 프로세스의 write replay/reference/revoke replay/CheckReady는 authorization callback과 budget/data 변경 전에 차단돼야 한다.

기존 binding2 phase, 새 operation9 phase의 정확한 순서·해당 부모 test의 terminal pass, operation 필수5개·binding5개·receipt2개·기존 credential13개·package pass를 모두 요구한다. skip·출력 marker만 있는 transcript·실패 후 나중 pass는 성공 증거가 아니다. killed fixture의 역할은 child wait 후 isolated DB에서만 정리한다. child 임시 restart DSN/합성 키/DB와 volume은 최종 teardown에서 제거된다.

## 결과와 한계

var/camera/credential-operation-checks의 private log/report에 실패 단계·마지막 완료 단계·exit code를 남긴다. source drift/중단/불완전 증거/자체 project 정리 실패를 passed로 표시하지 않는다. report의 runtime_admission_guard_implemented=true는 source 구현이며 운영 활성화가 아니다. production 서비스/DB/key/authority/API/restore fence/business runtime은 false다.

fixture의 UID0 owner와 UID10001 runtime이 사용하는 DB owner DSN은 준비와 관찰을 위한 합성 자료다. 실제 업무 pool은 고정 writer/budget 역할의 승인 TLS 연결이다. 이는 credential runtime에서 owner 비밀을 허용한다는 배포 설계가 아니다. 실제 owner 계정/네트워크 fence, DB와 key 복원, 독립 fresh-key/budget/marker 갱신을 연결하는 전체 유지보수 리허설은 다음 단위다. 적용 명령은 채팅에서 제공한다.

## 2026-10-07 검사 권한·실패 진단 수정

operations-owner는 CHOWN/FOWNER/SETUID/SETGID 외에 KILL을 포함한다. 이는 다른 UID의 합성 child 종료/정리에 필요한 isolated owner 권한이다. runtime은 계속 UID10001/effective capability0이며 business guard/실제 권한 검사를 약화하지 않는다. 부모가 시작할 때 effective CAP_KILL을 검사하고 누락 시 owner_signal로 실패한다.

runtime_operation_leases 실패 보고서의 failed_native_component는 owner_signal, child_start/protocol/wait, identity/keys/pin/database_setup/endpoint/restart_fixture/approved_pools/constructor/ready/failure_unwind/required_grants, 각 업무 흐름/interrupted_write/recreated/unknown 중 검토된 고정 이름이다. 자식 실패의 일반 output/stderr를 raw로 보고서에 붙이지 않는다. tag는 같은 실제 부모 test/package에서 나와야 하며 불명확하거나 비허용 값은 출력하지 않는다. 실패 영수증이 있는 transcript는 뒤의 pass로 인수되지 않는다. 기존 nine phase 및 필수 five test 인수 기준은 유지한다.

이번 서버 실패의 내부 assertion은 사용자 JSON만으로 확정되지 않았으며 수정 후 인수를 다시 요구한다. [실패·수정 기록](../progress/20261007-step11b3c3c-credential-operation-leases.md)을 따른다.

## 서버 인수 반영

수정8개/Python18개 및 native required operation5개/phase9개, binding5개/phase2개, key receipt2개, 기존 credential13개와 Go race/vet가 통과했다. 서버 revision은 0765dfb6560779e289c129f96d1a656b6da3cc79c7e31ed64ffc74678aff28f0다. 인수 기록은 위 진행 문서의 11:28 절을 따른다. manifest의 native 인수 상태가 true여도 이 검사를 다시 실행할 수 있으며 전체 source hash와 모든 성공 증거 요구는 유지한다.
