# 단위 11-B3c3d2a 수정 — 기본 socket 호환·시작 확인·실패 로그

작성일: 2026-10-07 · 수정/로컬 검증 완료 · 서버 Docker 재인수 대기

## 서버에서 확인한 상태

12:08 Asia/Seoul 사용자 로그에서 기존 patch16개 적용·pending0·Python21개 OK를 확인했다. native는 project vms-credential-boundary-test-1eebec34f53a, checked_revision 05b38a74ea1adea6feadce22f3ac3f8efbfb5fdccf9aa6f7a478313259f3632c, status=failed다. start_isolated_peers에서 exit1, 마지막 완료 own_fixture_files다. 업무 단계 seed/fence/reopen/retry와 전체 race regression에 도달하지 않았으며 d2a native를 인수하지 않는다. 운영 변경·실제 DB/key 복원·HBA 변경·전체 production restore fence는 false, isolated_resources_removed=true다.

## 확인한 결함과 수정

공식 PostgreSQL Docker entrypoint의 docker_process_sql은 PGHOST와 PGHOSTADDR를 비워 initial SQL을 기본 Unix socket에 연결한다. 기존 fixture는 unix_socket_directories=/socket만 열고 PGHOST=/socket을 공급했으므로 그 환경 변수가 initial SQL에 적용되지 않는다. 공식 코드와 시작 설정의 충돌을 확인했고 source contract subprocess에서 재현했다. 서버의 원본 PostgreSQL stderr는 아직 제공되지 않았으므로 이 수정으로 전체 server native가 통과했음을 주장하지 않는다. [공식 entrypoint](https://github.com/docker-library/postgres/blob/master/docker-entrypoint.sh)의 docker_process_sql/docker_temp_server_start를 근거로 한다.

DB와 공유 volume·owner probe·file helper의 socket 경로를 /var/run/postgresql에 통일하고 PGHOST 우회값을 제거했다. healthcheck는 임시 socket-only 초기화 서버가 아니라 최종 TCP server의 readiness를 기다린다. product HBA/auth 정책은 그대로다.

fixture의 base/tls/hba traversal mode는 명시적으로0755를 설정한다. prepare phase 안에서 실제 umask0077로 생성하여 PostgreSQL과 UID10001 probe가 필요한 public path 접근을 얻도록 검증한다. probe/authority의 private mode와 key owner/mode는 기존 기준을 유지한다. 테스트 전용 Go 파일만 변경하며 제품 생성자·SQL·migration·runtime·운영 compose를 바꾸지 않는다.

검사 실패 시 같은 disposable project의 ps --all과 마지막100줄 peer logs를 private log에 보존한 뒤 down/volume 제거한다. 진단 명령 실패/timeout/interrupt도 cleanup을 막지 않는다. 실패 단계·원래 command exit/마지막 완료를 덮어쓰지 않는다. report에 raw 진단/DSN/secret을 넣지 않고 isolated_diagnostics_collected만 표시한다. go_vet_passed는 build_tools의 실제 성공으로 기록한다. 이전 false는 전체 검사 완료 기준이었으므로 서버 vet 오류가 확인된 것은 아니다. go_race_passed는 전체 transcript/source 검증을 요구한다.

## 검증 결과와 한계

| 검사 | 결과 |
|---|---|
| Python boundary runner | 26개 통과. 공식 initial SQL의 환경 제거 contract에 기존 /socket 실패·기본 경로 성공 재현. 실패 후 ps/logs→cleanup, 진단 오류/timeout/interrupt, stage/exit 보존·report 비노출 포함 |
| 관련 credential Python unit | 전체128개 통과 |
| 실제 local PostgreSQL17.11/OpenSSL + Go race | storage top79/sub61, local boundary 8 phase 및 full module vet 통과. umask0077 fixture·실제 서로 다른 loopback source·HBA/TLS/disk tamper·FENCED/budget 보존 회귀 포함 |
| 패치 | baseline376개/정확한 manifest hash·delta/hash·dry run/적용/재실행/원본 백업·사용자 edit/new collision·보호 파일·archive exclusion, apply helper8개 통과 |

local은 Go1.25.1과 UID0-only/Unix socket bind 금지 환경이다. Go/TLS 실제 실행과 entrypoint shell contract 검사는 구분한다. 수정하지 않은 PG17.11 Docker image의 초기화와 별도 UID/actual RO mount/socket reject는 대상 서버에서 다시 확인해야 한다. local PG의 root 시작 거부 두 곳만 바꾼 fixture, SQL/auth 원본, 임시 process 종료 및 DB/cert/password/binary 미전달은 이전 기록과 같다. 제품 process/routes를 변경하지 않아 smoke62개 이전 인수를 유지한다.

## 다음 단계

서버 재검사의 Python26개, native passed·required_boundary_tests_passed=5·native_boundary_phases_passed=8·isolated_resources_removed=true를 인수한다. 성공 시 Go race/vet=true여야 한다. 재실패하면 새 log에 ISOLATED_BOUNDARY_DIAGNOSTIC:ps/logs 뒤 actual peer stderr가 남는다. production flag들과 database_and_key_restore_performed/network_packet_filter_verified는 false다. d2a 통과 전 d2b 실제 DB/key 복원 통합으로 진행하지 않는다. Streamlit browser 인수는 deferred, relay는 추가하지 않는다. 명령은 채팅에서 제공한다.
