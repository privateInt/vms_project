# 단위 11-B3c3d4e — 현재 DB 볼륨 마운트 대조

작성일: 2026-10-07 · d4d 실제 identity 서버 인수 완료 · d4e 서버 파일 적용/마운트 테스트 실패

## 서버 적용 결과와 후속 수정

사용자 로그에서 written9/pending0, backup=var/patch-backups/step11b3c3d4e-s7kn8rvm을 확인했다. 새27개 검사 중 test_native_directory_and_fdinfo_without_contents_or_following_symlinks가 MOUNTINFO_INVALID로 실패했다. set-e 때문에 이후 identity32개·공급90개·실제 topology inspector는 실행되지 않았다. 적용 상태는 인수했지만 DB volume proof는 인수하지 않는다. 운영 서비스·DB schema 변경은 없다.

문제가 된 root/mountpoint 원문은 로그에 없어 서버의 정확한 경로는 아직 확정하지 않는다. 커널이 삭제된 mount root에 붙이는 //deleted 표기로 기존 파서의 같은 오류를 재현했고 [mountinfo 수정](20261007-step11b3c3d4e-mountinfo-fix.md)에 처리·회귀 검증과 서버 재검사 기준을 기록했다. 아래 로컬27개 검증은 최초 전달 버전의 기록이다.

## 선행 인수

사용자 simsys4090/sh_test 로그에서 d4d written9/pending0, backup=var/patch-backups/step11b3c3d4d-b95deza3, 테스트32+90개와 실제 두 init process verified를 인수했다. source SHA8048bc6efcbfc0a227c2f10af225056fda294cf7b5b9ddc2dc9bd1c4786dcec3 / tracked422개를 이번 delta 기준으로 사용한다. API actual effective/filesystem65532:65532, DB999:999이며 observer/target 전체 mapping·cgroup·init namespace가 true다. 실제 credential binding은 false이며 schema7/API0.7.0-device-delete와 모든 운영 변경 false를 유지한다.

## 이번 결과

[DB 볼륨 마운트 대조](../operations/camera-credential-storage-topology.md)를 추가했다. 기존 read-only identity 조사를 새로 수행하고, 현재 Docker volume source path를 component별 O_PATH/NOFOLLOW metadata와 own fdinfo mount ID로 확인한다. host/DB process mountinfo의 실제 device·filesystem·root/mountpoint를 비교한다. bind root와 겹친 mount parent를 처리하며 상위 overmount에 가려진 과거 DB child를 현재 증거로 채택하지 않는다.

host path 권한 부족·비지원 filesystem·nested mount는 blocked를 구분해 보고하고 변경/불일치/symlink/재검사 불가는 failed로 중단한다. DB file content·directory listing·추가 exec/SQL·원본 키·secret/archive·authority를 읽거나 수정하지 않는다. private 보고서와 coordination lock 이외 쓰기는 없고 선언 snapshot roots나 공급 worksheet를 수정하지 않는다. 성공은 현재 volume mount만 확인하며 complete backup_topology_verified=false·activation_allowed=false다.

## 검증

새27개, 기존 identity32개·공급90개를 통과했다. 합성 Docker/kernel record로 source gate·namespace tree/stacked mount·bind root·fd mount/inode·root/device/readonly 불일치·permission/missing·unsupported filesystem/nested mount·process/PID/directory/mount/source/env/key/volume drift·고정 오류/private report를 검사했다. 실제 로컬 temporary directory의 O_PATH·mountinfo·own fdinfo와 symlink rejection을 확인했고 directory listing/DB 비밀 파일을 열지 않았다. Python3.12 로컬이며 새 파일의 Python3.10 문법도 검사한다. 현재 Docker가 없어 실제 simsys4090 volume proof를 아직 주장하지 않는다.

중첩 Python 실행의 적용 tree 검사에서 기존 native ps의 self lookup이 로컬 PID view 차이로 두 번 실패했다. 적용 파일을 별도 tree에 그대로 설치한 뒤 각 검사를 독립 실행해 새27개·identity32개·공급90개 모두 통과했다. 기존 source나 테스트를 수정/skip해 우회하지 않았다. 이는 로컬 실행 환경 한계이며 운영 서비스 오류로 인수하지 않는다.

패키지는 accepted baseline422개와 delta9개, 전체 hash·dry-run·백업 적용·재실행·사용자 편집/새 경로 충돌·env/key/authority sentinel 보존·helper8개를 확인한다. 적용된 payload의 새27개와 기존122개도 검사한다. 기존 src/Go/SQL/Compose·서비스 라우팅을 유지하므로 이전 Go race/vet/native restore/resume 인수를 유지하고 관련 Python 회귀만 실행한다. 신규 의존성·공용 Python·UI 환경 변경은 없다.

## 다음 완료 기준

서버 topology_readiness와 volume proof/blocked_stage를 인수한다. 권한 부족이면 필요한 정확한 metadata 범위에 맞춰 host 접근 전제를 구체화한다. verified이면 실제 host volume 경로를 공급 위치와 snapshot 범위 검토에 연결한다. active PGDATA·외부 WAL/tablespace·모든 physical backup/restore roots 및 목적지·authority/lock/HBA/PKI 제외·DB/키 복구 일관성은 후속 확인이며 mount 성공으로 전체 backup 준비를 표시하지 않는다. 이후 보호된 공급 준비·schema9 cutover·credential HTTP API·production restore fence를 진행한다. Streamlit browser acceptance는 deferred이며 중계를 추가하지 않는다. 실행 명령은 채팅에서만 제공한다.
