# 단위 11-B3c3d4f — 호스트 저장 경로 접근 진단

작성일: 2026-10-07 · 2026-10-08 서버172개 테스트·접근 진단 인수 완료 · volume mount는 blocked

## 현재 상태와 이번 완료 기준

simsys4090/sh_test에서 root 수정 written8/pending0, checked revision=e7055fd06997db432eca2220cf87b9e176584a524af4cdfd3b0ca3d8bcf9ef12, tracked428개를 확인했다. 마운트43개·identity32개·공급90개 총165개를 통과했다. own mountinfo369개 중 canonical_absolute269개·relative_or_synthetic100개·나머지0개를 인수했다. 실제 topology 조사는 완료됐지만 현재 identity verified/volume blocked, HOST_STORAGE_METADATA_PERMISSION_REQUIRED/host_database_directory다. root 파서 문제는 해결됐으며 실제 volume mount 성공과 complete backup topology는 미완료다.

이번 단위는 기존 O_PATH 경로 탐색이 어디에서 거부되는지를 읽기 전용 metadata로 기록한다. 전체428개 baseline hash를 지키며 source/test·manifest·문서8개 delta로 전달한다. API0.7.0-device-delete/schema7/registry-only-v1·TLS off, credential API·production restore fence·business runtime 미활성은 유지한다.

## 변경

실제 디렉터리 component 열기가 EACCES/EPERM으로 거부되면 이미 열린 부모 descriptor의 fstat에서 owner UID/GID·mode와 탐색 경로를 관찰한다. 거부된 component 뒤는 열지 않는다. root descriptor 거부는 부모 metadata를 만들지 않고 own fdinfo 읽기 거부는 디렉터리 탐색과 별도 operation으로 표시한다. 일반 OSError나 다른 stage에는 경로를 추측하지 않는다. 원본 오류 문구·임의 exception 속성을 반영하지 않고 context의 고정 키·타입·host 선언 prefix/parent 관계를 검사한다.

volume.access_diagnostics는 당시 열린 descriptor 관찰이며 path_binding_rechecked=false/permission_policy_cause_proven=false다. 이름과 descriptor의 현재 물리적 일치를 blocked 상태에서 추가 승인하거나 mode만 보고 ACL/LSM 원인을 확정하지 않는다. database_volume_mount_verified와 supply/activation은 계속 false다. 원본 키·DB 파일/목록·ACL·새 SQL·환경·authority를 읽거나 바꾸지 않는다. 기존 inventory의 read-only SQL과 key metadata 관찰 범위는 유지한다. 쓰기 범위는 기존 private 보고서와 coordination lock뿐이다. 권한 변경·sudo·helper container·DB cutover·서비스 재시작을 추가하지 않는다.

## 검증

로컬 Python3.12에서 마운트50개·identity32개·공급90개 총172개와 패치 helper8개를 통과했다. 추가7개는 선언 경로에 묶인 blocked context, 임의 오류 속성 비반영, 무관한 경로/필드/타입의 context 거부와 private 실패 보고서, native O_PATH의 최종/중간 component 및 root 거부, fdinfo 거부 구분을 검사한다. native 강제 오류는 실제 descriptor를 열고 fstat 관찰·모든 descriptor 정리·남은 경로 미접근·본문/목록/권한 변경 금지를 확인한다. 서버의 실제 ACL/LSM/권한 원인을 재현했다고 주장하지 않는다.

기존 root parser·전체 mount record 보존·선택 root 거부·source/device/root/namespace 대조·symlink 거부·drift·보고서/입력 보존을 유지한다. source 전체 hash, Python3.10 문법, payload hash와 full baseline428개/source429개, dry-run·원본 백업 적용·재실행0개 쓰기·사용자 편집/새 경로 충돌 거부·env/key/authority sentinel 보존을 확인한다. 적용 payload에서 같은172개를 확인한다. Go/SQL/Compose·상위 검사 소스는 byte 단위로 유지하므로 Go/vet/PG 리허설을 반복하지 않는다. 실제 운영 Docker 접근은 없어 새 진단의 서버 인수는 대기 중이다.

## 다음 완료 기준

서버 적용과50+32+90개 테스트 이후 실제 topology inspector의 access_diagnostics를 인수한다. 접근 거부가 이어지면 operation·attempted_path·관찰한 부모 metadata를 근거로 해당 metadata만 확인할 수 있는 최소 범위의 실행 방법을 검토한다. 검사 전체를 root로 실행하거나 host 디렉터리를 임의로 chmod/chown하지 않는다. 접근 가능한 경우 기존 source/device/root 재검사까지 통과해야 volume mount를 인수한다. active PGDATA/WAL/tablespace·전체 backup/restore roots·authority/lock/HBA/PKI의 물리적 제외와 공급 경로 검토는 후속이며 이번 단계에 묶지 않는다. Streamlit browser acceptance는 deferred다. 서버 적용 명령은 채팅에서만 제공한다.

## 서버 인수 — 2026-10-08

simsys4090/sh_test에서 written8/pending0, backup=var/patch-backups/step11b3c3d4f-ecq4ogmt와 마운트50개·identity32개·공급90개 총172개 통과를 확인했다. checked revision=c5c907d2ca09660e684d6e35b47a7854ce50272e65da11bfe01a186800e2e74c/tracked429개다. 실제 조사는 inspection_completed=true/current_process_identity_verified=true지만 volume과 topology_readiness는 blocked이며 HOST_STORAGE_METADATA_PERMISSION_REQUIRED/host_database_directory다.

진단 operation=open_directory_component, attempted_path=/media/simsys/SSD_EXT4/docker/volumes, error=EACCES다. 열린 부모 /media/simsys/SSD_EXT4/docker는 owner_uid=0/owner_gid=0/permissions=0710으로 관찰됐다. 당시 descriptor의 metadata이며 path_binding_rechecked=false/permission_policy_cause_proven=false다. mode만으로 ACL/LSM 등 최종 권한 정책 원인을 확정하지 않는다. 실제 volume mount·backup topology·supply/activation은 false이며 서비스·DB·키·권한 변경은 없다. 후속 d4g는 선언된 한 경로의 O_PATH descriptor만 보조 프로세스로 열고 기존 사용자 검사에서 물리적 mount 대조와 반복 확인을 수행한다.
