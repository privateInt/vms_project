# 단위 11-B3c3d2b 수정 — PostgreSQL 이미지의 owner 환경 격리

작성일: 2026-10-07 · 수정/로컬 검증 완료 · 서버 Docker 재인수 대기

## 서버에서 확인한 상태

사용자 결과에서 d2b source patch17개 적용/pending0, Python29개 OK를 확인했다. native project=vms-boundary-restore-test-fc37ca1c3cbd, checked_revision=076041b2e4d09250213fe4f6d05999f758bb0a7b0138805a2e41410b90c8b576, status=failed다. seed_boundary에서 TestNativeCredentialMaintenanceBoundaryOwner/exit1, 마지막 완료는 prepare_synthetic_keys다. build_tools의 vet는 true이며 전체 race 인수는 false다. 실제 DB/key 복원은 not_started, production 변경과 전체 restore fence는 false다. isolated_resources_removed/isolated_diagnostics_collected=true다. d2b native는 인수하지 않는다.

## 결함 확인과 수정

이전 d2b에서 pg_dump/pg_restore를 같은 유지보수 source에서 실행하기 위해 owner container를 공식 PostgreSQL17.11 image로 바꿨다. 해당 image는 PG_MAJOR=17, PG_VERSION=17.11-1.pgdg12+2, PGDATA=/var/lib/postgresql/data를 기본 environment로 정의한다. maintenanceConfig는 명시적 승인 설정만 사용하기 위해 모든 ambient PG* 변수를 거부한다. host subprocess에서 PG*를 제거해도 container image의 기본 environment는 그대로다. 이를 지난 로컬 검사는 공급하지 않아 놓쳤다.

변경 전 코드에 image 기본 세 변수를 실제 owner seed process로 공급하자 prepare/keys 다음 seed에서 maintenance mTLS control unavailable / CREDENTIAL_MAINTENANCE_UNAVAILABLE로 실패했다. 서버 report와 같은 stage/parent를 재현했다. 원본 서버 log의 stderr는 제공되지 않았으므로 서버의 상세 오류가 이 문자열이었다고 단정하지는 않는다. 공식 [PG17 bookworm Dockerfile](https://github.com/docker-library/postgres/blob/master/17/bookworm/Dockerfile)과 실제 코드의 확정된 환경 충돌을 수정한다.

검사 도구의 owner/restore10 phase를 sh의 exec env -i로 시작하고 PATH·explicit disposable DSN·fixture base/socket/reset/restore flag·phase selectors만 전달한다. PG_MAJOR/PG_VERSION/PGDATA뿐 아니라 연결 옵션·servicefile·미래 PG*·기타 host 값을 전달하지 않는다. 필요한 값 누락/빈 값은 child 실행 전에 실패한다. 인수자 argv는 quoted positional arguments로 보존하며 shell 코드로 조합하지 않는다. LOCAL diagnostic flag는 명시적으로만 전달하고 기존 LOCAL proof 거부를 유지한다.

관리 Go opener의 PG* 거부 정책, TLS·source/CN·HBA, privilege/mount, candidate primitive, migration/SQL, 15 phase 인수 순서는 수정하지 않았다. pg_dump/pg_restore child는 기존 코드가 승인된 TLS/role/address로 구성한 자신의 PG* 설정만 사용한다. owner PATH의 PostgreSQL client 경로는 유지한다. 별도 client UID10001/RO probe와 Docker Compose 배포 파일은 원본 그대로다.

## 검증과 범위

| 검사 | 결과 |
|---|---|
| 변경 전 실제 로컬 PG17.11/OpenSSL | image PG* defaults를 공급하면 prepare/keys 성공 뒤 seed의 strict maintenance opener 실패 재현 |
| Python 새 runner | 33개 통과. 실제 shell child의 image/알 수 없는 PG* 제거·explicit fixture 값 보존·argv literal 전달·누락 child 차단·전체10 owner phase launcher 사용 포함 |
| 관련 credential Python unit | 전체161개 통과 |
| 실제 로컬 PG17.11/OpenSSL + Go race | 모든 owner phase에 PG image defaults와 PGOPTIONS/PGSERVICEFILE/미래 PG*를 주입하고 실제 새 launcher로 실행. seed부터 실제 dump/key restore·PREPARED/후보 retry/reset 거부·final closed까지 local15 phase 통과. storage top80/sub61·전체 module vet 통과 |
| 보존 확인 | platform191개 파일과 PostgreSQL 배포 source 원본 유지. Go/SQL/제품/Compose 변경0 |
| 패치 | baseline388개/hash076041…에 delta7개. dry-run/백업 적용/재실행·user edit/new destination 충돌·보호 환경/키/authority sentinel 보존·archive 제외/helper8개 통과 |

로컬은 Go1.25.1/UID0-only·Unix socket bind 금지 환경이며 Docker가 없다. root 시작 거부 두 곳만 바꾼 로컬 PG fixture에서 SQL/auth는 원본이다. image 환경 주입과 실제 shell/TLS/DB 복원 실행을 검증했으며 수정하지 않은 Docker PG17.11·UID10001·RO mount/socket의 전체 native 인수는 서버 재검사로 확인한다. 임시 PG process는 종료했고 synthetic DB/키/cert/password/archive/binary는 전달하지 않는다. 제품 process/routes 변경이 없어 smoke를 반복하지 않았다.

## 다음 인수

수정 패치 후 Python33개, native status=passed·required_restore_tests_passed=8·native_boundary_restore_phases_passed=15·credential13·Go race/vet=true·isolated_resources_removed=true, final PREPARED/target closed/roles NOLOGIN을 확인한다. 성공 summary의 owner_pg_environment_absence_verified도 true여야 한다. native 전체 성공 전 d2c 업무 재개 단계로 진행하지 않는다. 운영 schema7/API·keys/HBA/authority와 business runtime/production restore fence는 미전환이다. Streamlit 브라우저 인수는 deferred, 중계는 추가하지 않는다. 명령은 채팅에서 제공한다.
