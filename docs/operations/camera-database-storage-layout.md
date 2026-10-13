# 현재 PostgreSQL 저장 경로 관찰 — 11-B3c3d4h

`src/infra/tools/inspect_camera_database_storage_layout.py`는 실제 운영 PostgreSQL의 데이터 디렉터리·WAL·사용자 테이블스페이스 위치를 읽기 전용으로 관찰한다. d4g 서버 볼륨 인수와 전체 소스 해시를 요구하고 현재 프로세스·볼륨 마운트를 다시 확인한다. 이전 보고서나 공급 초안을 현재 증거로 읽지 않는다. 적용·실행 명령은 전달 채팅에서 제공한다.

| 입력 | 관찰과 제한 |
|---|---|
| 실제 DB 설정 | `data_directory`, `config_file`, `hba_file`, `ident_file`; PGDATA 환경값으로 실제 저장 위치를 대신하지 않음 |
| PostgreSQL 카탈로그 | 테이블스페이스 OID·`pg_tablespace_location`; 사용자 이름·권한·역할 비밀번호는 조회하지 않음 |
| WAL 위치 | 실제 data_directory 아래 pg_wal의 leaf 타입과 해석된 대상 디렉터리 |
| 디렉터리 메타데이터 | 고정 stat/readlink 명령으로 owner/mode·디렉터리/링크 타입·해석 경로·내부 identity를 비교 |
| 반복 관찰 | catalog·postmaster 시작 시점·directory identity·volume mount·process·container·입력 변경을 거부 |

SQL은 camera_admin/vms_camera로 로컬 소켓에 접속하고 REPEATABLE READ READ ONLY 트랜잭션, statement/lock timeout, 고정 search_path·DateStyle·TimeZone을 사용한다. catalog의 DB·session/current role·read-only 표식과 PostgreSQL17을 검증한다. 테이블스페이스는 기본 OID1663/1664를 포함해 최대128개만 허용하고 전체 개수와 반환 행 수를 비교한다. JSON 생성 시 OID는 bigint로 변환해 정수로 전달한다. 원래 oid 타입을 그대로 넣으면 문자열이 되므로 파서가 거부한다. bigint는 signed int4로 변환할 때의 unsigned OID 범위 문제도 피한다. 파서는 문자열·불리언·소수·범위 밖 값을 정수로 강제 변환하지 않는다. 상대 경로나 in-place 테이블스페이스, 누락·중복·새 필드·잘못된 타입은 승인하지 않는다. archive_mode는 off/on/always만 기록하고 archive_command나 목적지는 읽지 않는다.

새 Docker exec는 현재 소유 DB의 정확한 ID와 OS UID/GID999:999, 고정 SQL 또는 고정 shell·등록된 경로 인자만 허용한다. 경로는 SQL 응답 검증 후 등록하며 shell 본문에 삽입하지 않는다. 경로 인자는 따옴표로 처리하고 eval을 사용하지 않는다. metadata 명령 환경은 PATH/LC_ALL만 전달한다. 디렉터리 목록·DB 파일 본문·설정 파일 본문·키/DSN/CA/authority·백업 파일은 열지 않는다. DB 이미지에 필수 GNU stat/readlink/id가 없으면 설치하지 않고 관찰을 차단한다.

stat 메타데이터와 readlink -e의 결과를 NUL로 구분한다. readlink 결과를 command substitution으로 넘기지 않으므로 실제 파일명의 끝 개행을 지워 다른 경로로 오인하지 않는다. 응답은1MiB 이하, 고정 protocol/UID/GID/필드 수, canonical 절대 경로와 디렉터리 타입을 요구한다. 링크·대상 identity와 해석 경로를 반복 비교한다. 디렉터리 mtime/ctime은 정상 DB 활동으로 바뀔 수 있어 비교하지 않는다. 관찰은 시점별 메타데이터 비교이며 일관된 백업 snapshot을 만들거나 서비스를 멈추지 않는다.

전체 검사는 프로젝트 사용자로 실행한다. 명시적인 privileged-directory-metadata 옵션은 d4g와 같은 고정 host 경로의 O_PATH 관찰에만 관리자 보조를 사용한다. 새 SQL·컨테이너 메타데이터 명령은 DB OS 사용자999로 실행하며 root 보조의 경로·소스·권한 범위는 확대하지 않는다. 관리자 인증은 기존 sudo 인증을 사용하고 프로그램이 비밀번호를 처리하지 않는다. root로 전체 검사를 시작하면 보고서 쓰기 전에 거부한다.

정상 관찰은 status=inspected, inspection_completed=true, layout_readiness=observed, active_database_storage_locations_observed=true다. layout에는 PGDATA·WAL·사용자 테이블스페이스의 컨테이너 경로/해석 경로·링크 여부·owner/mode·PGDATA 밖인지가 담긴다. config/HBA/ident는 문자열 위치만 기록하며 물리적 제외나 실제 파일을 검증하지 않는다. PID·inode·device 원문·postmaster 시각·DSN·테이블스페이스 이름은 보고서에 저장하지 않는다.

검증된 현재 volume 아래 해석 경로에 대해서만 상대 경로를 붙인 host_path_candidate를 기록한다. 이는 lexical-relative-to-current-verified-volume 후보이며 개별 경로를 호스트에서 열어 물리적으로 확인했다는 뜻이 아니다. 모든 위치의 host_path_verified는 false다. volume 밖의 PGDATA·WAL·테이블스페이스는 host 후보가 null이고 물리적 mount 대응 검토가 필요하다. 컨테이너에서 관찰한 경로를 전체 백업 범위 확정으로 표시하지 않는다.

현재 volume/identity나 최초 명령의 가용성이 부족하면 layout_readiness=blocked, 위치 관찰=false, 고정 blocker와 종료값0을 반환한다. SQL/metadata 형식 불일치·변경·재검사 실패는 fixed failed code/stage와 종료값1이다. 실행 시작/실패가 이전 성공 보고서를 대체한다. 오류 원문·Docker stderr·임의 exception 속성을 출력하지 않는다.

쓰기 범위는 기존 coordination lock과 private `var/camera/database-storage-layout.json`(0600)뿐이다. 기존 topology/identity/supply/review 보고서를 수정하지 않는다. 전체 backup_topology_verified·production_supply_ready·activation_allowed·credential API/fence/business runtime은 계속 false다. 모든 snapshot/backup/restore root와 목적지, archive WAL 정책, authority/lock/HBA/PKI의 물리적 제외, DB/키를 맞춘 복구 절차와 실제 공급 binding은 후속 작업이다.

근거: [PostgreSQL17 실제 데이터·설정 파일 위치](https://www.postgresql.org/docs/17/runtime-config-file-locations.html), [PGDATA·pg_wal·pg_tblspc 파일 배치](https://www.postgresql.org/docs/17/storage-file-layout.html), [pg_tablespace_location](https://www.postgresql.org/docs/17/functions-info.html), [GNU readlink의 기존 경로와 NUL 출력](https://www.gnu.org/software/coreutils/manual/html_node/readlink-invocation.html). 실제 서버 관찰은 전달 후 인수한다.

## OID JSON 형식 수정 — 2026-10-08

d4h 파일 적용과 서버233개 테스트는 통과했지만 실제 카탈로그 단계는 DATABASE_LAYOUT_TABLESPACE_INVALID로 실패했다. 저장 위치 관찰 완료를 표시하지 않는다. 수정은 JSON 생성의 OID 값에 bigint 변환을 추가하며 pg_tablespace_location의 원래 OID 인자·정렬·카탈로그 개수·READ ONLY transaction·Docker allowlist 범위를 유지한다. 로컬44개·기존192개를 통과했고 서버 수정8개 적용·44개 검사도 통과했다. 실제 관찰은 컨테이너 재확인 오류로 재실패했으며 OID native SQL·저장 위치 인수는 계속 대기다. 근거는 [PostgreSQL17 JSON 변환](https://www.postgresql.org/docs/17/functions-json.html), [OID 타입과 unsigned 범위](https://www.postgresql.org/docs/17/datatype-oid.html) 및 공식17.11 소스의 json_categorize_type/oid→int8 cast다.

## 마운트 순서와 컨테이너 재확인 — 2026-10-08

이전 구현은 Docker inspect의 Mounts 목록을 그대로 비교했다. 데이터 volume·secret3개·init bind의5개 마운트에서 목록 순서만 바뀌어도 DATABASE_CONTAINER_CHANGED_DURING_INSPECTION·topology_input_recheck가 재현됐다. 서버 원문 inspect 응답은 확보하지 않았으므로 실제 실패 원인의 확정과 구분한다. 상위 함수의 마지막 단계가 남아 자체 비교 오류에 잘못 표시된 것도 수정한다.

목적지별 전체 마운트 레코드를 비교한다. 목록 순서와 JSON 객체의 필드 순서만 비교에서 제외하며 모든 속성·중첩 값·JSON 타입은 유지한다. 중복/비정규 목적지·잘못된 응답은 DATABASE_LAYOUT_MOUNTS_INVALID로 거부한다. 실제 Source/Type/Name/Driver/RW/Mode/Propagation 변경·추가/제거·목적지 변경은 DATABASE_LAYOUT_MOUNTS_CHANGED로 실패한다. PID는 DATABASE_LAYOUT_CONTAINER_PID_CHANGED, HostConfig는 DATABASE_LAYOUT_HOST_CONFIG_CHANGED다. 자체 마지막 컨테이너 비교는 database_layout_container_recheck 단계로 보고한다. 상위 topology의 실제 변경 거부·SQL/metadata 명령 제한·권한 검사는 유지하며 자동 재시도나 복구는 하지 않는다.

로컬52개·기존192개 검사를 통과했다. 실제 서버에서 inspection_completed=true·layout_readiness=observed·active_database_storage_locations_observed=true를 확인해야 한다. 전체 backup topology와 공급 활성화의 완료 표식은 계속 false다.

## 서버 인수 — 2026-10-08

revision `4151d24309168d3f0a31da870aed511f2d44cdf96f836431339187e4352c9062`에서 서버52개 테스트와 실제 privileged-directory-metadata 검사를 인수했다. inspection_completed=true, layout_readiness=observed, active_database_storage_locations_observed=true, current_volume_mount_verified=true, blockers=[]다. PostgreSQL17.11/READ ONLY SQL·OS UID/GID999:999를 확인했다. PGDATA는 /var/lib/postgresql/data, WAL은 그 아래 pg_wal이며 두 해석 경로가 원래 경로와 같고 symlink가 아니다. 두 위치는999:999/0700이고 현재 volume 안에 있다. 기본 테이블스페이스2개만 존재하고 custom_tablespaces=[], archive_mode=off다.

config/HBA/ident 위치는 모두 현재 PGDATA 안이며 물리 경로나 파일 본문은 검사하지 않았다. 두 host 후보는 현재 검증된 volume 경로를 기준으로 만든 lexical 후보이고 host_path_verified=false다. 따라서 개별 물리 경로 대응·전체 backup topology·authority/HBA/PKI 제외·DB/키 백업 및 복구 범위는 여전히 후속이다. readiness=blocked는 전체 공급 준비의 상태이며 이 관찰의 성공과 구분한다. 운영 서비스/DB/schema/키/권한/환경은 변경하지 않았고 공급/API/fence/business 활성화 표식은 false다.

후속 단위는 현재 PGDATA와 WAL의 host 후보가 실제 동일한 저장 위치인지 고정 metadata 범위로 확인하는 것이다. 백업 root/목적지 전체 선언이나 공급 파일 생성으로 범위를 확대하지 않는다. 자세한 영수증과 미완료 항목은 [서버 인수 기록](../progress/20261008-step11b3c3d4h-server-acceptance.md)에 있다. 위의 재검사 대기 문단은 이전 전달 시점의 이력이다.
