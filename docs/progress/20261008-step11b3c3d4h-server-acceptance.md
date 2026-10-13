# 단위 11-B3c3d4h — 실제 저장 경로 관찰 서버 인수

작성일: 2026-10-08 · 사용자 simsys4090/sh_test 실행 결과 인수 · 문서와 메타데이터만 갱신

## 실행 결과

마운트 재확인 수정은 written8/pending0, backup `var/patch-backups/step11b3c3d4h-mount-fix-sux26fpc`로 적용했다. service_restart_performed/runtime_activation_required/database_schema_modified=false다. 서버 Python 테스트52개를 통과했다. 이번 명령에서 기존192개 회귀 테스트를 다시 실행하지 않았으며 이전 로컬244개 통과 기록과 구분한다.

실제 검사의 checked_revision은 `4151d24309168d3f0a31da870aed511f2d44cdf96f836431339187e4352c9062`다. status=inspected, inspection_completed=true, layout_readiness=observed, active_database_storage_locations_observed=true, current_volume_mount_verified=true, blockers=[]다. privileged_directory_observer_requested=true다. PostgreSQL version_num170011, read_only_transaction_verified=true, metadata execution UID/GID999:999를 확인했다.

## 인수한 저장 위치

| 항목 | 관찰된 컨테이너 경로/값 | 확인 범위 |
|---|---|---|
| PGDATA | /var/lib/postgresql/data | 해석 경로 동일, leaf symlink=false,999:999/0700, 현재 volume 안 |
| WAL | /var/lib/postgresql/data/pg_wal | 해석 경로 동일, leaf symlink=false,999:999/0700, PGDATA와 현재 volume 안 |
| 테이블스페이스 | catalog2개/custom0개 | 기본2개만 존재, 외부 사용자 테이블스페이스 없음 |
| WAL 아카이브 | archive_mode=off | 아카이브 목적지/retention은 관찰하지 않음 |
| config | /var/lib/postgresql/data/postgresql.conf | 위치 문자열이 현재 PGDATA 안, 본문/물리 경로 미검증 |
| HBA | /var/lib/postgresql/data/pg_hba.conf | 위치 문자열이 현재 PGDATA 안, 본문/물리 경로 미검증 |
| ident | /var/lib/postgresql/data/pg_ident.conf | 위치 문자열이 현재 PGDATA 안, 본문/물리 경로 미검증 |

PGDATA의 host 후보는 /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data이고 WAL 후보는 그 아래 pg_wal이다. 이 값의 근거는 lexical-relative-to-current-verified-volume이다. 현재 volume 자체는 d4g와 반복 조사에서 확인했지만 각 후보 디렉터리의 host_path_verified는 false다. 컨테이너 내부 위치 관찰과 개별 host 물리적 대응을 합치지 않는다.

고정 catalog SQL의 OID bigint 변환과 UID999의 stat/readlink metadata, repeated process/volume/container 검사가 실제 서버에서 끝까지 통과했다. 따라서 OID native production SQL과 마운트 재확인 수정의 서버 검증을 true로 기록한다. 이전 실패의 상세 inspect 응답을 확보하지 않았으므로 당시 Mounts 순서 변동을 직접 확인했다고 주장하지 않는다. 과거 원인 확정 표식은 false로 유지한다.

## 기록 근거와 현재 한계

보고서 위치는 /home/shshin/workspace/vms_project/var/camera/database-storage-layout.json이다. 이번 인수는 사용자가 전달한 JSON을 근거로 한다. 서버 private report를 직접 읽거나 운영 호스트에 접속해 재검사한 것은 아니다. accepted revision은 실제 검사된 실행 소스의 영수증이며 이번 문서 패치 후 manifest 해시와 별개로 유지한다.

readiness=blocked, production_supply_ready=false, activation_allowed=false는 전체 공급 준비의 상태다. 이번 저장 경로 관찰이 실패했다는 뜻이 아니다. backup_topology_verified=false이며 설정 파일 physical_path_verified와 archive_destinations_observed도 false다. 보고서의 ACTIVE_PGDATA_AND_EXTERNAL_WAL_TABLESPACE_LOCATIONS 미완료 범주는 전체 물리적 백업 대응까지 포함하므로 컨테이너 내부 위치를 읽었다는 사실만으로 지우지 않는다.

production_services_modified/service_restart_performed/production_database_modified/database_schema_modified/production_key_material_read/production_keys_loaded/production_admission_state_created/production_hba_modified/environment_modified/host_permissions_modified/database_file_contents_read/database_directory_contents_listed/backup_created/declared_snapshot_roots_created는 모두 false다. 공급 계획/승인 binding/authority/네트워크 생성·변경, credential API/운영 restore fence/business runtime 활성화 표식도 모두 false다. 기존 registry API/schema 전환은 수행하지 않았다. Camera Streamlit의 브라우저 인수는 계속 deferred다.

## 이번 기록 패치 검증

README·문서 index·운영 안내·기존 수정 기록·이 인수 기록과 manifest, 총6개 파일만 변경한다. 기존438개 전체 baseline과 결과439개 해시를 확인한다. patch helper8개·dry-run·원본 백업 적용·재실행0개 쓰기·사용자 편집/새 파일 충돌 거부·env/key/authority sentinel 보존과 새 manifest의 source gate를 확인한다. src·SQL migration·Compose·AGENTS·Makefile은 byte 단위로 유지한다. 문서만 변경하므로 Docker/Go/관찰 테스트를 반복하지 않는다. 적용 명령은 채팅에서만 제공한다.

## 다음 단위

11-B3c3d4i는 현재 PGDATA/WAL host 후보의 물리적 대응을 읽기 전용 metadata로 확인하는 단위다. 실제 server layout/volume 영수증, 현재 source/identity/mount를 선행 조건으로 하고 fixed 후보를 host에서 symlink 없이 관찰해 container 쪽 identity와 맞는지 검증한다. 경로가 추가됐거나 변하면 승인된 것처럼 확장하지 않고 중단한다. 데이터 파일 본문·키·설정 파일은 읽지 않으며 권한/서비스/DB를 변경하지 않는 것이 완료 기준이다.

그 후 모든 backup/snapshot/restore roots와 목적지, authority/lock/HBA/PKI의 물리적 제외, DB/키를 맞춘 복구 절차를 별도 단위로 확정한다. 이번 결과를 전체 백업 인수나 credential 공급 활성화로 표시하지 않는다.

## 인수 기록 파일 적용 — 2026-10-08

사용자가 인수 기록6개를 written6/pending0, backup `var/patch-backups/step11b3c3d4h-notes-nmqqy2wh`로 적용했다. service_restart_performed/runtime_activation_required/database_schema_modified=false다. 인수 기록 전달본 manifest SHA는 `392bc40e57447931738fd6aa30a26a54164ed6b5642fce150c9b558d192569f5`, tracked439개다. 실제 저장 경로의 검증 영수증4151d243…는 유지한다. 다음 단위의 [물리 경로 대응 검사](20261008-step11b3c3d4i-physical-storage-mapping.md)는 작성·로컬 검증 단계이며 실제 서버 인수는 별도다.
