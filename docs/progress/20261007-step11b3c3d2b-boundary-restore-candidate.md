# 단위 11-B3c3d2b — 차단 경계 아래 실제 복원과 후보 준비

작성일: 2026-10-07 · 구현/로컬 검증 완료 · 서버 Docker 격리 인수 대기

## 선행 단계 서버 인수

사용자 결과에서 d2a startup fix 적용10개/pending0, Python26개 OK를 확인했다. native project=vms-credential-boundary-test-04c8f12e37f0, checked_revision=08d9f3ae44d7a7f7d3d77a0d47606bfba6208ab47e3bf7385ba1e9144f148002, status=passed다. Go race/vet=true, top156/sub406, credential13/boundary5/native8 phase다. FENCED-before-HBA·snapshot 밖 정책·actual maintenance mTLS·다른 source의 valid credential 거부·잘못된 role/cert/CN/plaintext/socket 거부·reload 후 fresh 인증·maintenance target reconnect·fresh lease/control·FENCED/budget 보존·별도 UID/RO mount를 인수했다. 운영/실제 복원/full production fence 관련 flag는 false, isolated_resources_removed=true다. 해당 성공으로 다음 실제 복원 단위를 시작한다.

## 이번 결과

1. protected ring 사이 역사 key material 보존과 독립 새 encryption ID/material을 비교하는 CheckRestoreSuccessor를 추가했다. 현재 HMAC 활성 값을 유지한다. 비밀값을 반환하지 않는다.
2. durable PREPARED와 exclusive lease 아래 실제 maintenance TLS/role/source·승인 endpoint·disk HBA·NOLOGIN·migration/history·backup marker를 검사하는 PrepareRestoredCredentialDatabase를 추가했다. 기존 uses를 보존하고 old budget disabled/new budget0/fresh marker를 atomic transaction으로 반영한다. 같은 후보 재시도만 허용하며 used/disabled/mismatched candidate는 초기화하지 않는다.
3. synthetic DB/key archive의 실제 TLS pg_dump/pg_restore, backup 이후 예산 증가·snapshot rewind, 정확한 key 복원·ciphertext/HMAC 행 보존·복호화, old-key disable, PREPARED-before-enrollment, 프로세스 재생성/후보 retry와 reset 거부를 하나의 disposable 검사로 연결했다.
4. 전체15 phase와 정확한 test/prefix/order·crypto/storage 필수 검사·legacy13·source integrity·clean up을 인수 조건으로 만든 Python runner를 추가했다. 오류 report는 복원 command의 미시작/완료/불확실 상태를 구분한다.

최종 합성 candidate는 negative 검사에서 새 use1을 소비하므로 의도적으로 재개 불가다. 외부 PREPARED와 writer/budget NOLOGIN을 유지하고 target ALLOW_CONNECTIONS=false 및 activity0을 확인한다. OPEN/LOGIN/업무 write/replay 성공은 이번 완료 기준이 아니다.

## 검증

| 검사 | 결과 |
|---|---|
| Python 새 runner unit | 29개 통과: phase forgery/누락/순서/LOCAL 거부, 각 command fail/timeout/cleanup/source drift, 완료 후 실패와 restore 불확실 상태, production 파일 보존 포함 |
| 관련 credential Python unit | 전체157개 통과 |
| Go module | 전체 race 테스트와 vet 통과. DB 없는 module 실행에서 native 전용 검사는 skip되며 아래 실제 DB 실행을 별도로 수행 |
| 실제 로컬 PostgreSQL17.11/OpenSSL + race binary | schema9 history와 custom dump/key 실제 복원, budget rewind, old disable, PREPARED/atomic candidate/retry/reset 거부·final closed를 포함한 local15 phase 통과. storage regression top80/sub61 |
| 패치 | 기준 source388개 중 변경17개, baseline377개; hash/dry-run/적용/재실행/원본 백업·user edit/new collision·보호 sentinel·archive 제외 및 helper8개 검사 통과 |

로컬은 Go1.25.1·UID0-only·Unix socket bind 금지 환경이다. PostgreSQL root 시작 거부 두 곳만 바꾼 로컬 fixture를 사용하며 SQL/auth는 원본이다. 서로 다른 loopback source의 실제 TLS/HBA와 actual pg_dump/pg_restore를 실행했지만 수정하지 않은 Docker image 초기화·UID10001·actual RO probe mount/Unix socket은 서버에서 다시 인수해야 한다. LOCAL prefix는 native runner가 인수하지 않는다. 임시 PostgreSQL은 종료했으며 생성 DB·키·password·certificate·archive·binary는 전달 파일에 포함하지 않는다. 프로세스/routes는 변경하지 않아 smoke는 재실행하지 않았다.

## 적용 범위와 다음 단위

source 패치만 적용하고 운영 camera 0.7.0-device-delete/schema7·운영 DSN/keys/HBA/authority를 전환하지 않는다. 제품에는 restore/reopen/HBA activation/OPEN/LOGIN orchestration이 없고 이번 실제 복원은 disposable fixture에서만 수행한다. trusted dump 및 maintenance source/control-plane 독점은 별도 배포 전제다. packet filter/replica/host-admin 방어·운영 full restore fence·credential API·business runtime 완료를 주장하지 않는다.

서버에서는 Python29개, status=passed·required_restore_tests_passed=8·native_boundary_restore_phases_passed=15·credential13·Go race/vet=true·isolated_resources_removed=true 및 final PREPARED/target closed/roles NOLOGIN을 확인한다. 성공 후 11-B3c3d2c에서 durable OPEN·runtime HBA/LOGIN 재개 순서와 실제 두 role/RO key/authority/grants·중단 차단을 별도로 검증한다. Streamlit 브라우저 인수는 보류하고 중계는 추가하지 않는다. 적용/검사 명령은 채팅에서 제공한다.
