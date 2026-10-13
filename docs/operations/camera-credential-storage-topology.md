# 현재 DB 볼륨 마운트 대조 — 11-B3c3d4e

src/infra/tools/inspect_camera_credential_storage_topology.py는 현재 camera-data 볼륨의 선언 host 경로를 실제 Linux 마운트와 비교한다. accepted source·d4d 서버 인수와 현재 init identity를 새로 확인한다. 기존 inventory/facts/identity 보고서나 worksheet를 현재 증거로 다시 읽지 않는다. 실행 명령은 전달 채팅에서 제공한다.

| 입력 | 사용 방식 |
|---|---|
| 현재 소유 DB container와 volume | Docker ID/image·init PID·시작 시점·전체 mapping/cgroup와 camera-data의 RW mount 선언을 확인 |
| host source path | 경로 component마다 O_PATH/NOFOLLOW directory descriptor를 열어 metadata만 확인; symlink·다른 타입을 거부 |
| 검사자 own fdinfo | 최종 열린 directory의 실제 mount ID·inode를 확인하고 host mountinfo와 연결 |
| host/DB process mountinfo | device major/minor·filesystem·mount root·mountpoint·RW를 비교; host bind root까지 포함해 같은 경로인지 확인 |
| 반복 관찰 | directory ancestry identity·선택 mount·process·container·volume·source/env/receipt/key metadata 변경을 거부 |

호스트 fd의 mount ID를 사용하므로 동일 mountpoint의 여러 마운트 중 실제 열린 것을 확인한다. DB 쪽은 namespace root와 parent 관계를 따라 현재 보이는 마운트를 고른다. 상위 경로에 새 mount가 겹쳐 기존 DB child를 가리는 경우를 거부하며 단순 longest prefix나 device 번호 하나만으로 승인하지 않는다. ext4/xfs/btrfs만 이번 mount 증거 규칙에서 허용한다. 다른 파일시스템과 DB root 아래 추가 mount는 별도 backup 검토가 필요하다.

metadata parser는1MiB/16384행 이하의 mountinfo,4096byte 이하의 own fdinfo를 읽는다. mount source·전체 options·unrelated mount 이름을 출력하지 않는다. DB directory 안의 파일을 열거나 목록을 만들지 않는다. O_PATH로 디렉터리 자체 metadata만 확인하며 directory mtime 변화는 정상 DB 활동일 수 있어 검사 fingerprint에 넣지 않는다. 입력 host path는 canonical 경로로 한정하고 원본 key/CA/DSN/authority/archive 본문은 읽지 않는다. 추가 Docker exec/SQL·helper container·서비스 변경은 없다.

root 필드는 커널이 출력한 메타데이터 문자열로 보존한다. 직렬화가 유효하고 비어 있지 않은 root를 전역 파싱 단계에서 모두 lookup path로 제한하지 않는다. 다른 mount record를 버리지 않으며 mountpoint·parent tree는 계속 검증한다. 실제 대조에 선택된 host/DB root는 canonical이어야 하고 그렇지 않으면 DATABASE_MOUNT_ROOT_NOT_CANONICAL로 실패한다. 삭제 표기·중복 slash·상대 표기·dot/parent component를 정규화하거나 문자열에서 제거해 승인하지 않는다. 이 root를 가진 상위 overmount는 과거 child를 계속 가리고, DB 아래 nested mount도 계속 backup 검토 대상으로 남는다.

record는 LF, field는 ASCII space만으로 구분한다. Unicode 공백·CR 등의 실제 파일명 byte를 splitlines/split의 추가 구분자로 오해하지 않으며 커널의 space/tab/LF/backslash octal escape를 한 번만 해독한다. 비어 있는 root는 MOUNTINFO_ROOT_PATH_INVALID, canonical이 아닌 mountpoint는 MOUNTINFO_MOUNTPOINT_PATH_INVALID, 잘못된 escape/NUL은 MOUNTINFO_PATH_ESCAPE_INVALID로 거부하고 원문을 오류나 보고서에 넣지 않는다. 실제 선택 root의 비정규 표기는 파서 성공과 무관하게 대조 단계에서 거부한다.

별도 mountinfo 진단 모드는 전체 source hash를 확인하고 검사자 자신의 procfs mountinfo만 읽는다. root_shapes에는 canonical_absolute·deleted_suffix·relative_or_synthetic·double_leading_slash·parent_component·dot_component·repeated_slash·trailing_slash·other_noncanonical의 고정 키와 개수만 담는다. 이는 형식 관찰이며 특정 경로·filesystem·DB volume 승인이 아니다. 원문·mount ID·PID를 출력하지 않고 Docker/API/SQL·키 metadata·환경·DB 디렉터리에 접근하지 않는다. coordination lock이나 보고서도 만들지 않으며 diagnostic_only=true, report_modified=false, database_volume_mount_verified=false다. 서버 집계는369개 중 canonical_absolute269개·relative_or_synthetic100개·나머지0개다. 실제 mount 종류나 원문을 이 집계만으로 확정하지 않는다. 실행 명령은 전달 채팅에서 제공한다.

정상 대조는 status=inspected/inspection_completed=true/topology_readiness=verified다. volume.database_volume_mount_verified와 local_host_path_verified/host_path_without_symlinks_verified가 true이며 확인된 host filesystem mountpoint·filesystem·directory owner/mode를 출력한다. PID·inode·raw mountinfo·fd 번호는 저장하지 않는다. 이 결과는 현재 volume mount 증거다. 실제 active PGDATA subdirectory·외부 WAL/tablespace·모든 backup/restore roots 및 목적지·authority/lock/HBA/PKI의 물리적 제외·DB와 키를 맞춘 복구 절차는 아직 검증하지 않았다. 따라서 backup_topology_verified=false/production_supply_ready=false/activation_allowed=false를 항상 유지한다. SupplyPlan·declared_snapshot_roots를 생성하거나 초안을 수정하지 않는다.

current identity가 다시 확인되지 않으면 CURRENT_PROCESS_IDENTITY_NOT_VERIFIED로 host path를 열지 않는다. host path/procfs 권한 부족은 HOST_STORAGE_METADATA_PERMISSION_REQUIRED, 경로 부재는 HOST_STORAGE_METADATA_UNAVAILABLE로 blocked 처리하고 blocked_stage를 함께 출력한다. 다른 filesystem은 DATABASE_FILESYSTEM_REVIEW_REQUIRED, nested mount는 DATABASE_NESTED_MOUNTS_REQUIRE_REVIEW다. blocked 조사가 끝나면 종료값0이며 성공 증거는 false다. 기본 모드는 관리자 프로세스를 실행하지 않으며 모든 모드에서 chown/chmod·mount 변경을 하지 않는다. metadata 재검사 불가, source/device/root 불일치, symlink, process·container 변경은 fixed code/stage의 failed/종료값1로 중단한다.

11-B3c3d4f에서는 host_database_directory 단계의 실제 O_PATH 접근 거부에 volume.access_diagnostics를 붙인다. operation은 open_filesystem_root, open_directory_component, read_own_directory_fdinfo 중 하나다. attempted_path는 이미 선언된 host 경로의 prefix이며 component 실패는 부모, fdinfo 실패는 열린 최종 디렉터리의 path·owner_uid·owner_gid·permissions를 observed_directory에 담는다. root descriptor 자체를 열지 못하면 observed_directory는 null이다. error는 EACCES/EPERM 고정값이며 OS 오류 본문·임의 exception 속성·PID·inode·fd 번호는 출력하지 않는다. context는 선언 경로와 연결하고 고정 필드·타입을 검사하며 무관한 경로나 잘못된 context는 STORAGE_ACCESS_DIAGNOSTICS_INVALID로 실패한다.

metadata_basis=already-open-directory-descriptor는 당시 획득한 descriptor의 fstat 관찰임을 뜻한다. 경로 rename·mount 변경 이후의 물리적 연결을 blocked 상태에서 다시 증명하지 않으므로 path_binding_rechecked=false다. permissions만으로 ACL·LSM 등의 원인이나 적절한 권한 변경을 확정하지 않으며 permission_policy_cause_proven=false다. 거부된 component 뒤의 경로는 열지 않는다. procfs mountinfo 단계의 거부나 일반 OSError에는 디렉터리 context를 추측해 붙이지 않는다. 성공 후 반복 확인 중 권한을 잃으면 기존 failed 규칙을 유지한다. d4f 서버 결과는 volumes 접근 EACCES·열린 부모 docker root:root/0710이며172개 테스트와 함께 인수했다.

## 명시적 관리자 디렉터리 관찰 — 11-B3c3d4g

privileged-directory-metadata 옵션을 선택한 경우에도 전체 inventory·Docker/API·기존 read-only SQL·key metadata·보고서 쓰기는 원래 사용자로 수행한다. root로 전체 검사를 시작하면 RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER로 보고서 쓰기 전에 거부한다. 현재 identity와 전체 source hash를 새로 확인하고, 경로 탐색의 EACCES/EPERM에서만 root 보조 프로세스를 사용한다. 경로 부재·symlink·procfs 권한 부족에는 관리자 실행으로 재시도하지 않는다. 보조 경로는 서버에서 관찰한 /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data 하나로 고정하며 다른 선언 위치는 승인하지 않는다.

보조 소스 camera_storage_directory_observer.py는 표준 라이브러리만 쓰며 project module·키·환경·Docker·DB 파일·procfs를 읽지 않는다. O_PATH/NOFOLLOW directory component와 fstat만 관찰하고 디렉터리 목록·파일 본문·권한 변경을 하지 않는다. 파일을 root로 다시 import하지 않고 일반 사용자 검사에서 manifest와 대조한 소스 byte를 고정 system Python의 격리 실행에 전달한다. administrator credential이 미리 인증돼 있어야 하며 비밀번호를 프로그램에 전달·저장하지 않는다. 새 sudoers 규칙이나 root 서비스도 만들지 않는다. 실행 및 인증 명령은 채팅에서 제공한다.

프로세스 간 통신은 filesystem 경로가 없는 AF_UNIX/SOCK_SEQPACKET socketpair다. socket을 stdin descriptor0으로 넘겨 sudo의 일반 close-from 정책에 다른 descriptor 보존 설정을 요구하지 않는다. root 보조 프로세스는 한 요청·한 응답 후 종료하며 bounded packet·socket timeout·alarm을 둔다. SCM_RIGHTS로 최종 O_PATH descriptor 하나만 전달하고 수신측은 SCM_CREDENTIALS의 실제 UID/GID0을 확인한다. SO_PEERCRED는 socketpair 생성 시점의 identity이므로 root 발신 근거로 사용하지 않는다. UID나 inode를 JSON에 주장하는 것만으로 승인하지 않는다.

수신자는 packet 크기/잘림·고정 필드/타입·선언 경로·chain 개수·root 발신을 검사한다. descriptor의 실제 flags는 O_PATH/DIRECTORY/NOFOLLOW이어야 하고 fstat는 chain 최종값과 정확히 같아야 한다. own fdinfo에서 받은 핸들의 mount ID를 얻고 기존 host/DB mountinfo·visible parent tree·device/root/filesystem과 다시 대조한다. 다른 namespace의 descriptor가 host mountinfo와 연결되지 않으면 거부한다. 성공 전 보조 관찰과 전체 비교를 다시 수행하고 inode·owner/mode·mount·process·source drift를 검사한다. 열린 fd와 socket은 성공/실패 모두 정리하고 raw fd/PID/inode/chain을 보고서에 저장하지 않는다.

인증·프로세스·timeout 문제는 PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE, root도 접근할 수 없는 경로는 PRIVILEGED_DIRECTORY_PERMISSION_DENIED로 blocked다. 잘못된 송신 identity/packet/descriptor나 실제 source 불일치는 fixed failed code로 중단한다. 성공일 때 volume.privileged_directory_observer_used/privileged_sender_uid_verified가 true다. 이것은 현재 volume mount proof이며 complete backup topology·미래 credential runtime binding·supply/activation은 계속 false다. 디렉터리 권한을 일반 사용자에게 확대하지 않는다.

d4g 로컬 검증은 마운트53개·보조 도구17개·identity32개·공급90개 총192개다. native socket의 실제 descriptor/credential 전달, 격리 system Python/stdin socket의 실행과 root sender·own fdinfo 연결, malformed/nonroot/읽기 가능한 descriptor 거부·모든 fd 정리·source hash·명시적 CLI·기본 모드 보존을 확인했다. 시스템 Python 검사는 임시 디렉터리로 고정 경로를 대체한 합성 실행이다. 로컬 sudo는 PERM_SUDOERS/setresuid Invalid argument로 시작되지 않아 sudo 경유 검증은 못 했으며 서버 결과로 인수한다. 비root로 실행한 테스트는 실제 비root 발신을 거부하는 경로를 검사한다. 당시 운영 volume mount 인수는 대기 상태였으며 실제 서버 인수는 아래 2026-10-08 기록을 따른다.

쓰기 범위는 공통 coordination lock과 private var/camera/credential-storage-topology.json(mode0600)뿐이다. 실행 시작/실패 보고서는 이전 성공을 대체하며 기존 preflight/facts/identity/review 파일은 보존한다. source gate는 전체 tracked source hash와 accepted d4d source SHA를 요구한다. 기존 Go/SQL/Compose·DB schema7/API0.7.0-device-delete·원본 키·환경은 변경하지 않는다.

root 수정은 서버 마운트43개·identity32개·공급90개를 통과했다. 실제 조사도 완료했지만 host_database_directory 접근 권한 부족으로 blocked다. d4f는 서버 마운트50개와 기존122개·실제 경로 접근 진단을 인수했다. 합성 kernel/Docker records에서 namespace root/stacked parent·bind root·같은 device의 잘못된 source root·fd mount/inode·권한 부족·비지원 filesystem/nested mount·metadata drift·private report와 고정 오류를 검사했다. 여러 root 표기의 무관한 mount 처리·선택 root 거부·상위/중첩 mount 보존·추가 공백 문자와 원문 비노출을 확인했다. 진단의 source gate·메타데이터만 읽기·파일/보고서 보존·고정 키 집계·CLI 분기와 오류도 검사했다. native temporary directory에서 강제한 root/중간/최종 component와 fdinfo 권한 거부를 구분하고 descriptor 정리·원문 비노출·본문/목록/권한 변경 없이 부모 metadata만 관찰함을 확인했다. 이 강제 거부는 서버의 실제 권한 원인 재현이 아니다. 기존 native O_PATH·own fdinfo·mountinfo 성공/심볼릭 링크 거부 검사도 유지했다.

형식 근거는 [Linux mountinfo](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html), [Linux fdinfo](https://man7.org/linux/man-pages/man5/proc_pid_fdinfo.5.html), [Linux O_PATH](https://man7.org/linux/man-pages/man2/open.2.html), [UNIX descriptor/credential 통신](https://man7.org/linux/man-pages/man7/unix.7.html), [Python3.10 socket](https://docs.python.org/3.10/library/socket.html), 커널의 [dentry_path](https://github.com/torvalds/linux/blob/master/fs/d_path.c)와 [seq_dentry/경로 escaping](https://github.com/torvalds/linux/blob/master/fs/seq_file.c)다. 각 경로의 실제 읽기 권한과 백업 도구의 포함 범위는 별개다.

## 실제 서버 인수 — 2026-10-08

d4g 서버192개 검사와 기존 사용자·sudo 보조 관찰을 인수했다. checked revision은 `61db0fcc701df8fc5d4e1087107513a60b6b01ac4db96779482d7df8e8ef9009`다. topology_readiness=verified, blockers=[]이며 현재 camera-data의 host 경로·mount source·root sender를 확인했다. host filesystem mountpoint는 `/media/simsys/SSD_EXT4`, filesystem은 ext4, DB 디렉터리는999:999/0700, 중첩 mount는0개다. 권한이나 서비스를 바꾸지 않았다. 현재 volume mount proof만 완료했으며 전체 backup topology는 계속 false다. 후속 실제 DB 저장 경로 관찰 범위는 [d4h 안내](camera-database-storage-layout.md)를 따른다.
