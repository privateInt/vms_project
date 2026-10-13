# 단위 11-B3c3d4i — PGDATA·WAL 호스트 물리 경로 대응

작성일: 2026-10-08 · 구현·로컬 274개 검증 완료 · 서버 47개 및 실제 물리 대응 인수 완료

## 선행 상태와 범위

d4h는 simsys4090/sh_test에서52개 검사와 실제 layout 조사를 인수했다. 실제 checked revision은 `4151d24309168d3f0a31da870aed511f2d44cdf96f836431339187e4352c9062`이며 PGDATA/WAL은 현재 볼륨 내부의 비symlink999:999/0700, 사용자 테이블스페이스0개/archive off다. 개별 host_path_verified는 false다. 이후 인수 기록6개가 written6/pending0, backup `var/patch-backups/step11b3c3d4h-notes-nmqqy2wh`로 적용됐다. 이번 baseline은 그 전달본392bc40e…/439개다.

이번 단위는 두 고정 host 후보와 컨테이너 디렉터리를 device/inode·owner/mode·실제 mount 대응으로 확인하는 것이다. 경로 변경·외부 WAL/테이블스페이스·archive 변경을 새로운 승인으로 처리하지 않는다. 전체 백업 root/공급 파일/authority/credential 활성화는 포함하지 않는다.

## 구현

새 검사와 테스트는 src/infra/tools에 뒀다. accepted d4h/source gate, 실제 parent layout 조사, 고정 stat/readlink의 internal identity와 두 host O_PATH chain 비교를 추가했다. host/DB mount의 device/filesystem/root+상대 경로를 대조하고 fd의 visible mount와 WAL 부모 chain을 확인한다. parent 전체 조사 후 internal identity를 다시 비교해 공개 보고서 값이 같아도 inode 교체를 잡는다. process·catalog·mount·host chain·key metadata·입력·container binding을 반복 확인하며 raw inode/device/PID를 보고하지 않는다.

기존 standalone directory helper와 receiver는 root 고정 경로 및 그 아래 pg_wal 하나를 허용한다. WAL launcher는 accepted d4h/새 mapping 구현/source 영수증을 요구한다. 두 경로의 실제 root sender·O_PATH descriptor 검증과 fd/process cleanup, isolated system Python/no project import, anonymous stdin socket을 유지한다. 다른 경로·파일 본문·목록·권한 변경은 허용하지 않는다. 기존 topology/layout의 검사와 명령 allowlist는 유지한다.

성공 시 individual_host_paths_verified와 두 row.host_path_verified만 true로 반환한다. 전체 backup_topology_verified/production_supply_ready/activation_allowed 및 운영 변경 표식은 false다. 최초 가용성 부족은 blocked, 불일치·변경·재검사 실패는 failed다. 새 private 보고서만 쓰며 parent 보고서는 읽거나 덮어쓰지 않는다. source gate는 기록된 영수증을 읽고 live 상태를 다시 조사한다.

## 검증

Python3.12에서 mapping26개·observer21개·topology53개·layout52개·identity32개·공급90개, 총274개를 통과했다. mapping은 device/inode/owner/mode·부모 chain·fd mount·host overmount source 불일치, 외부 경로/profile 변경, 권한/부재, symlink, 두 namespace에서 동시 교체된 WAL, catalog/process/container/input/key drift, mount 순서, private failure/success report와 보호 키 미열기를 확인한다.

실제 임시 디렉터리에서 fixed stat와 O_PATH fstat의 identity 일치를 확인했고 데이터 sentinel의 atime/mtime을 보존했다. standalone root helper를 isolated /usr/bin/python3로 실행해 고정 임시 WAL path의 SCM_RIGHTS descriptor와 실제 kernel sender credentials를 확인했다. root helper/receiver의 chain·flag·extra fd·bad request·정리 테스트도 유지한다. 이 native 임시 경로 검증은 실제 운영 Docker bind나 서버 sudo 검증이 아니다.

패치 helper8개·baseline439개/결과443개 전체 해시·11개 변경 파일·Python3.10 문법·source gate·백업 적용·재실행·충돌 거부·env/key/authority 보존과 적용 tree의 mapping26/observer21개를 확인한다. 기존 Go/SQL migration/Compose/DB schema/API source는 유지한다. Go/서비스 라우팅을 변경하지 않아 native PostgreSQL/Go/smoke를 반복하지 않는다.

## 전달 당시 미완료와 서버 인수 기준

운영 host/Docker/sudo에는 접속하지 않았다. 실제 두 경로의 물리 대응·sudo launcher·운영 데이터 보존은 서버 실행 결과로 인수한다. 서버에서 mapping26개와 observer21개를 통과하고 actual mapping_readiness=verified·individual_host_paths_verified=true·blockers=[]를 확인해야 한다. source/context 변경이나 안전한 fixed blocker가 있으면 같은 단위에서 진단한다. 서비스 재시작·DB/schema/권한/원본 키 변경 없이 수행한다.

다음 단위는 모든 backup/snapshot/restore root와 목적지 및 외부 authority/lock/HBA/PKI의 물리적 제외 검토다. 이번 두 경로의 성공을 전체 backup topology로 표시하지 않는다. 적용·검사 명령은 채팅에서만 제공한다.

## 서버 실행 결과 인수 — 2026-10-08

사용자 제공 실행 결과에서 패치 written=11/pending=0, 백업 `var/patch-backups/step11b3c3d4i-v0amc64m`, mapping 26개와 observer 21개 통과를 확인했다. 실제 검사 revision은 `915be4ab56bfef53def591b38b5024920daf745f5525fb35d22f1ca893d1c745`다. 위 전달 당시의 서버 대기 상태를 이 결과로 완료한다.

실제 mapping_readiness=verified·individual_host_paths_verified=true·blockers=[]다. PGDATA와 WAL의 고정 호스트 경로는 모두 symlink 없이 컨테이너와 같은 디렉터리이며 ext4·999:999/0700이다. 두 경로의 제한된 관리자 보조와 실제 root sender 검증도 true다. 제작 환경에서는 운영 서버에 접속하거나 private 보고서를 직접 읽지 않았다.

서비스·DB/schema·원본 키·권한·네트워크·HBA·공급 계획·authority는 변경하지 않았다는 서버 표식을 인수한다. 전체 backup topology와 운영 공급은 blocked이며 credential API/restore fence/업무 runtime은 미활성이다. 로컬 274개와 이번 서버 47개는 별도 검증 결과다. [상세 서버 인수 기록](20261008-step11b3c3d4i-server-acceptance.md)
