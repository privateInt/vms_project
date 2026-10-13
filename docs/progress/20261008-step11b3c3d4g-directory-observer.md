# 단위 11-B3c3d4g — 제한된 관리자 디렉터리 관찰

작성일: 2026-10-08 · d4f 서버 인수 완료 · d4g 서버192개·실제 sudo 연결과 현재 volume mount 인수 완료

## 선행 상태와 완료 기준

d4f는 simsys4090/sh_test에서 written8/pending0, backup=var/patch-backups/step11b3c3d4f-ecq4ogmt, checked revision=c5c907d2ca09660e684d6e35b47a7854ce50272e65da11bfe01a186800e2e74c/tracked429개다. 마운트50개·identity32개·공급90개 총172개를 통과했다. 실제 조사는 완료됐지만 volumes component 접근 EACCES·열린 부모 /media/simsys/SSD_EXT4/docker의 root:root/0710을 확인했다. 당시 metadata이며 ACL/LSM 등 권한 정책 원인은 확정하지 않았다. volume mount/전체 backup topology는 미검증이다.

이번 단위는 전체 검사를 원래 사용자로 유지하고, 선언된 한 디렉터리 경로의 O_PATH 관찰만 명시적으로 관리자 보조 프로세스에 맡겨 기존 대조를 수행하게 한다. 고정 path·source hash·실제 root sender·directory descriptor·완전한 기존 mount 재검사와 실패 정리가 완료 기준이다. 추가 공급 계약/파일·DB cutover·키 활성화·서비스 변경·권한 확대는 포함하지 않는다.

## 구현

기본 실행은 이전처럼 관리자 프로세스를 실행하지 않는다. 명시적 옵션은 directory search 권한 거부에만 동작하고 d4f 인수/hash와 source 전체 hash를 먼저 확인한다. parent root 실행은 보고서 쓰기 전에 거부한다. 비밀번호나 계정 권한 설정을 자동 처리하지 않고 기존 관리자 인증을 사용한다. root 보조 소스는 표준 라이브러리만 쓰며 manifest로 검증한 byte를 격리 system Python에 전달한다. user 환경·project module·Docker/API/SQL·키·DB 파일·목록을 root로 읽지 않는다.

anonymous socketpair의 stdin0에서 단일 bounded 요청을 받아 고정 HOST_PATH의 디렉터리 component를 O_PATH/NOFOLLOW로 열고 fstat chain을 관찰한다. syscall alarm·socket timeout을 두며 descriptor 하나를 SCM_RIGHTS로 넘긴 후 종료한다. 검사자는 실제 SCM_CREDENTIALS root UID/GID를 확인하고 받은 fd의 O_PATH flags·fstat와 chain 최종값을 검사한다. own fdinfo의 실제 mount ID와 기존 host/DB mountinfo·visible tree·device/root/filesystem을 연결한다. 보조 metadata와 전체 대조를 성공 전 다시 검사한다. 모두 닫고 fd/PID/inode/chain은 보고서에 출력하지 않는다. 보고서·lock의 소유자는 원래 사용자다.

## 검증

Python3.12에서 topology53개·observer17개·identity32개·공급90개 총192개와 patch helper8개를 통과했다. Linux temporary directory의 실제 O_PATH/SCM_RIGHTS/SCM_CREDENTIALS, 독립 system Python 격리 실행의 stdin socket 전달·실제 root sender·own fdinfo 연결을 확인했다. root helper source의 고정 경로만 임시 경로로 대체한 합성 검사다. sender/packet/chain/type/path/descriptor 불일치, 읽기 가능한 fd 거부, 실제 syscall 실패의 비밀 원문 비노출·descriptor 정리, root parent 거부·명시적 옵션·기본 권한 거부 보존·반복 확인 실패를 검사했다. 인증없는 sender는 실패하며 비root 테스트 실행은 실제 비root sender의 거부를 확인한다.

로컬 sudo는 자체 PERM_SUDOERS/setresuid Invalid argument로 시작되지 않았다. native sudo 연결 시도는 PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE로 차단됐고 이를 성공으로 기록하지 않는다. 고정 sudo/system Python 인자·private stdin·격리 환경·timeout 정리의 단위 검증과 sudo를 제외한 실제 root helper 통신은 통과했다. simsys4090의 실제 sudo 연결과 production volume 대조는 이번 전달 후 서버에서 인수한다.

전체429개 baseline과 source432개 hash, Python3.10 문법,10개 delta payload, dry-run·원본 백업 적용·재실행0개 쓰기·사용자 편집/새 경로 충돌 거부·env/key/authority sentinel 보존과 적용 tree의192개를 확인한다. 기존 Go/SQL/Compose·상위 검사 소스는 byte 단위로 유지해 Go/vet/PG 리허설은 반복하지 않는다. API0.7.0-device-delete/schema7/registry-only-v1/TLS off와 credential API·production restore fence·business runtime 미활성은 유지한다.

## 다음 완료 기준

서버192개 테스트와 기존 사용자 검사에서 관리자 보조 연결·root UID·반복 directory/mount 비교를 인수한다. 관리자 인증이 불가하면 unavailable/blocked를 유지하고 host 권한이나 sudoers를 임의로 변경하지 않는다. 실제 source/root/device 불일치는 fixed failed 상태를 확인한 뒤 그 증거에 맞게 조치한다. volume mount 성공 후 active PGDATA·외부 WAL/tablespace·모든 backup/restore roots·authority/lock/HBA/PKI의 물리적 제외·DB/키 coordinated restore와 공급 위치 검토는 다음 단위다. 이번 성공을 전체 backup topology나 credential runtime 배포 완료로 표시하지 않는다. Streamlit browser acceptance는 deferred이며 실행 명령은 채팅에서만 제공한다.

## 서버 인수 — 2026-10-08

simsys4090/sh_test에서 written10/pending0으로 적용했다. backup은 `var/patch-backups/step11b3c3d4g-chm059t1`, checked revision은 `61db0fcc701df8fc5d4e1087107513a60b6b01ac4db96779482d7df8e8ef9009`이며 tracked432개다. topology53개·observer17개·identity32개·공급90개, 총192개가 모두 통과했다.

기존 사용자 검사와 실제 sudo 보조 관찰 결과는 inspected/inspection_completed=true/topology_readiness=verified, blockers=[]다. 선언된 DB volume host 경로의 local_host_path_verified/database_volume_mount_verified/host_path_without_symlinks_verified가 true다. SSD의 마운트 지점 `/media/simsys/SSD_EXT4`, ext4, 디렉터리 owner999:999/mode0700, 중첩 DB mount0개를 확인했다. 실제 root sender와 관리자 보조 사용도 확인했다. 앞의 로컬 sudo 한계는 로컬 환경의 이력이며 실제 서버 sudo 연결은 이번 결과로 인수했다.

DB 파일 본문·디렉터리 목록을 읽지 않았고 권한·서비스·환경·스키마·원본 키도 변경하지 않았다. 전체 backup_topology_verified와 production_supply_ready/activation_allowed는 false다. 다음 d4h는 현재 PostgreSQL의 실제 저장 경로를 컨테이너의 디렉터리 메타데이터와 대조한다. 모든 backup/restore root와 외부 authority/lock/HBA/PKI의 물리적 제외는 별도로 검토한다.
