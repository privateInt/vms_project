# PGDATA·WAL의 호스트 물리 경로 대응 — 11-B3c3d4i

`src/infra/tools/inspect_camera_database_storage_mapping.py`는 현재 두 PostgreSQL 디렉터리의 컨테이너 위치와 고정 host 후보가 같은 물리적 디렉터리인지 메타데이터로 검증한다. 인수된 d4h revision4151d243…와 전체 소스 해시를 요구하며 저장된 보고서를 현재 증거로 읽지 않는다. 실행 명령은 채팅에서만 제공한다.

| 디렉터리 | 컨테이너 고정 경로 | 호스트 고정 경로 |
|---|---|---|
| PGDATA | /var/lib/postgresql/data | /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data |
| WAL | /var/lib/postgresql/data/pg_wal | /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data/pg_wal |

현재 조사에서 PGDATA/WAL이 이 경로와 다르거나 symlink·외부 사용자 테이블스페이스·archive_mode 변경·소유권/0700 불일치가 있으면 CURRENT_STORAGE_LAYOUT_REVIEW_REQUIRED로 중단한다. 임의 후보를 새로 승인하거나 경로 범위를 확장하지 않는다.

## 검증 흐름

현재 layout 전체 조사를 다시 수행해 READ ONLY SQL·UID999 metadata·현재 init identity·volume mount를 확인한다. 이어 같은 고정 SQL/stat/readlink로 두 디렉터리의 내부 device/inode/type/owner/mode를 얻는다. metadata가 앞선 보고서와 맞는지 비교하고, 호스트의 O_PATH/O_DIRECTORY/O_NOFOLLOW 디스크립터를 루트부터 각 경로 구성요소로 열어 symlink 없이 확인한다.

호스트 leaf의 st_dev/st_ino/st_uid/st_gid/st_mode와 컨테이너 stat의 값이 같아야 한다. WAL의 부모 identity chain은 PGDATA chain과 같아야 한다. 호스트 디스크립터의 실제 fdinfo mount_id와 visible mount가 맞는지 확인하고 두 namespace의 mount device/filesystem/root 및 상대 경로를 대조한다. 선택한 root가 정규 절대 경로이고 지원된 filesystem/ext4·xfs·btrfs이며 읽기 전용 mount가 아니어야 한다. 현재 DB volume 아래 새로운 nested mount는 승인하지 않는다.

전체 parent layout 조사를 다시 수행한 후 처음 관찰한 catalog·디렉터리 identity·host chain·현재 process/mount를 최종 대조한다. 부모 public report에는 inode가 없으므로 같은 경로/소유권의 새 디렉터리로 바뀌어도 internal identity를 비교해 교체를 잡는다. 입력·소스·키 메타데이터·Docker binding을 마지막에 재확인한다. 이는 조사 구간의 반복 증거이며 서비스를 멈춘 snapshot이나 지속적 변경 방지 장치는 아니다.

## 권한과 읽기 경계

기본 모드는 프로젝트 사용자만 사용한다. 명시적 privileged-directory-metadata 옵션은 host 디렉터리 검색 권한이 부족할 때만 기존 isolated system Python 보조를 실행한다. root helper는 위의 두 경로만 허용하며 어느 구성요소의 symlink도 따라가지 않는다. WAL 경로의 launcher는 d4h 서버 인수·새 mapping 구현/source 영수증을 추가로 요구한다. helper 자체는 standalone 표준 라이브러리이며 프로젝트 import·Docker·procfs·DB 파일·키·디렉터리 목록·쓰기 기능이 없다.

기존 anonymous SOCK_SEQPACKET/stdin, SO_PASSCRED/실제 root sender 검증, SCM_RIGHTS로 받은 O_PATH descriptor의 flag/inode/type 재검증과 모든 fd/process 정리를 유지한다. root helper는 요청한 두 경로 중 하나의 descriptor를 반환한다. 프로젝트 사용자가 자신의 procfs mountinfo/fdinfo를 읽고 대조하며 root 보조가 부모 결과를 대신 승인하지 않는다. whole inspector를 root로 실행하지 않는다. sudo 비밀번호·권한·환경·서비스 설정을 프로그램이 변경하지 않는다.

추가 Docker exec는 없다. 기존 LayoutDocker의 현재 소유 DB·999:999·정확한 READ ONLY SQL/stat/readlink allowlist만 재사용한다. 데이터/설정 파일 본문·원본 키·DSN·authority·archive 내용은 열지 않는다. 원본의 데이터 파일 mtime/atime이나 디렉터리 목록을 검사하지 않는다.

## 결과와 실패

성공은 status=inspected, inspection_completed=true, mapping_readiness=verified, individual_host_paths_verified=true, blockers=[]다. mapping.pgdata/wal에는 두 경로·owner/mode·filesystem과 same_directory_identity_verified/host_path_without_symlinks_verified/host_path_verified=true를 기록한다. root 도움 여부와 sender 확인도 기록한다. PID·device/inode·signature·Docker stderr는 공개 출력/보고서에 담지 않는다.

최초 관찰의 권한/가용성 부족은 mapping_readiness=blocked, mapping=null, individual_host_paths_verified=false, fixed blocker와 종료0이다. symlink/형식/identity/mount/source 불일치, 검사 중 변경이나 재확인 가용성 상실은 failed/fixed code/stage·종료1이다. 첫 실행/실패가 이전 성공 보고서를 대체한다. 새 private 보고서는 var/camera/database-storage-mapping.json(0600)이며 기존 parent 보고서들은 덮어쓰지 않는다. 기존 coordination lock과 이 보고서만 기록한다.

readiness=blocked, backup_topology_verified/production_supply_ready/activation_allowed=false는 성공 후에도 유지한다. 이 두 경로를 맞췄다는 사실로 전체 backup/snapshot/restore root와 목적지, authority/lock/HBA/PKI의 물리적 제외, 아카이브 정책·DB/키 복구 절차를 완료하지 않는다. 공급 파일/계획/authority/DB migration/credential API/fence/business runtime 활성화는 수행하지 않는다.

근거: [Linux open/openat/O_PATH](https://man7.org/linux/man-pages/man2/open.2.html), [stat/fstat 메타데이터](https://man7.org/linux/man-pages/man2/stat.2.html).

## 서버 인수 — 2026-10-08

사용자 제공 simsys4090/sh_test 실행 결과로 서버 mapping 26개와 observer 21개, 총 47개 통과를 인수했다. 검사 revision은 `915be4ab56bfef53def591b38b5024920daf745f5525fb35d22f1ca893d1c745`다. status=inspected, mapping_readiness=verified, individual_host_paths_verified=true, blockers=[]이며 위 두 경로 모두 host_path_verified/host_path_without_symlinks_verified/same_directory_identity_verified=true다. 두 디렉터리는 ext4·999:999/0700이고 privileged_directory_observer_used/privileged_sender_uid_verified=true다.

이 기록은 제공된 서버 JSON을 근거로 한다. 제작 환경에서 운영 서버에 접속하거나 private 보고서를 직접 읽은 결과는 아니다. 로컬 274개 검증은 이전 구현 전달 시의 결과이며 이번 서버 명령에서 다시 실행한 검사는 47개다. 인수 기록 패치는 문서와 프로젝트 메타데이터만 변경하고 원래 검사의 소스를 유지한다. [상세 인수 기록](../progress/20261008-step11b3c3d4i-server-acceptance.md)

전체 backup_topology_verified/production_supply_ready/activation_allowed=false와 readiness=blocked는 유지한다. 후속 검토는 모든 백업·snapshot·restore 경로와 목적지, 외부 authority/lock/HBA/PKI의 물리적 제외, DB·키의 연계 복구 절차, archived WAL 목적지와 보존 정책이다.
