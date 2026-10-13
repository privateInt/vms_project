# 단위 11-B3c3d2a — 유지보수 HBA/TLS 접속 경계

작성일: 2026-10-07 · 구현/로컬 검증 완료 · 서버 시작 단계 실패 · 수정 후 재인수 대기

## 선행 인수와 이번 결과

사용자의 d1 서버 로그를 인수했다. patch18개·Python18개, revision a2116e85a9d93b03ea54e65c4209d3b5b82b946c27e2f2377f6fe64e5e812e0d, project vms-credential-maintenance-test-bf460b7c3211, race/vet·top155/sub406·credential13개·maintenance4개/native7 phase·격리 자원 제거 모두 통과했다. 관련 문서/manifest에 반영했다. 운영 변경·DB/key 복원·network fence·전체 production restore fence는 false다.

d2를 한 번에 묶지 않고 이번 d2a는 복원 전 필요한 유지보수 접속 경계 하나를 완결한다. complete deny-by-default HBA 생성, 승인 source/CA/hostname/client subject로 fresh mTLS 관리 연결, durable FENCED와 actual session/disk 정책 검사를 구현했다. HBA를 DB data directory 바깥에 배치하고 disk exact bytes·parse errors·prepared transaction을 검사한다. 제품용 설치/reload/reopen과 실제 복원 orchestration은 아직 없다. [ADR0016](../architecture/decisions/0016-camera-maintenance-hba-boundary.md)을 따른다.

새 disposable runner는 같은 owner/client container에서 서로 다른 process를 exec해 source IP를 유지한다. 새 native test3개/phase8개와 unit2개, 기존 credential13개 및 전체 module race/vet를 요구한다. 유효 password/cert의 다른 source가 before에 성공한 뒤 closed/open에서 실제 28000으로 거부되어야 한다. 잘못된 CN은 실제 SCRAM+clientcert 경로의 28P01을 요구한다. 파일 변조와 reload signal만으로 정책 활성화를 표시하지 않는 원칙을 검사한다. test-only target reconnect는 closed-client proof를 확인한 runner 뒤에만 실행한다.

## 검증

| 검사 | 결과와 범위 |
|---|---|
| 실제 local PostgreSQL17.11/OpenSSL + Go race | storage top79/sub61 통과. 기존 credential13개·d1 maintenance4개/7 phase·DB/migration/dump/restore 회귀와 새 unit2개 포함 |
| 새 HBA/TLS local phase | prepare/seed/서로 다른 loopback source의 before/closed/open/fence/reopen/retry, 모두 통과. fresh 유지보수 TLS·잘못된 role/없는 cert/다른 CN/plaintext·disk tamper 거부, target write·새 control process/lease·budget42/FENCED 보존 확인 |
| Go vet | 전체 module 통과 |
| Python | 새 runner21개, 관련 credential unit 전체123개 통과. phase 순서/누락/중복/fail·local-only proof 거부·각 stage 실패 후 중단/정리·source drift·정리 실패·보호 파일 포함 |
| 패치 | 전체 baseline hash·manifest·payload, dry run/적용/재실행/원본 백업·사용자 수정/새 목적지 충돌·보호 파일·archive exclusion 확인 |

local은 Go1.25.1, UID0-only namespace 및 Unix socket bind가 금지된 환경이다. PostgreSQL17.11 원본에서 initdb/postgres의 root 시작 거부 두 곳만 바꿔 OpenSSL로 fresh build한 격리 fixture를 사용했다. SQL/auth 변경은 없다. source127.0.0.1과127.0.0.2의 실제 인증 경계는 확인했지만 local에서 UID10001/RO mount와 Unix socket reject를 주장하지 않는다. 이 local-only 경로는 _test.go 안에만 있고 모든 phase에 LOCAL_BOUNDARY_PHASE_OK를 출력하여 서버 parser가 인수할 수 없다. 임시 native DB process 종료를 확인했으며 DB/password/cert/key/binary를 전달하지 않는다.

서버 검사는 수정하지 않은 PG17.11 Docker image, UID10001/capability0/actual RO probe와 Unix socket reject를 반드시 요구한다. Docker가 없는 local에서 서버 Docker positive는 실행하지 않았다. 서버 인수 전 credential_boundary_native_verified=false다. 제품 process/routes 변경이 없어 기존 smoke62개 인수를 유지한다. 이번 patch는 production API/schema7/image/DB/key/authority/HBA·shared Python을 변경하거나 서비스를 재시작하지 않는다.

## 다음 완료 기준

서버 Python21개, native status=passed·required_boundary_tests_passed=5·native_boundary_phases_passed=8·isolated_resources_removed=true를 인수한다. production_hba_modified, database_and_key_restore_performed, network_packet_filter_verified, production_restore_fence_implemented 및 business_runtime_ready는 false여야 한다.

이후 d2b에서 실제 DB/key 복원과 old budget disabled·독립 fresh material/seen 보존·새 incarnation/marker·PREPARED 우선 영속화·OPEN 전 검사 및 중단/재시도를 연결한다. HBA는 인증 경계이며 host packet filter, 다른 endpoint/replica, 승인 source의 credential 탈취, privileged 관리자 재설정 또는 control-plane 독점을 대신하지 않는다. 제품용 HBA 공급/유지보수 실행 및 운영 preflight/rehearsal/activation은 별도 단위다. Streamlit browser 인수는 deferred이고 relay를 추가하지 않는다. 명령은 채팅에서만 제공한다.

## 서버 결과와 시작 수정

2026-10-07 12:08 사용자 로그에서 patch16개·Python21개는 통과했으나 native start_isolated_peers/exit1을 확인했다. 실제 HBA 동작 phase는 아직 인수하지 않는다. 기본 socket과 공식 초기화 SQL의 충돌 및 진단 보존을 [시작 수정 기록](20261007-step11b3c3d2a-startup-fix.md)에 반영했다. 재검사 Python은26개이며 native5개/8 phase 기준을 유지한다.
