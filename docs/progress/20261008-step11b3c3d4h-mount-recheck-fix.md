# 단위 11-B3c3d4h 수정 — 마운트 순서와 컨테이너 재확인

작성일: 2026-10-08 · OID 수정 서버 적용·44개 통과/실제 관찰 재실패 · 이번 수정 서버52개·실제 저장 경로 관찰 인수 완료

## 실패와 범위

simsys4090/sh_test에서 OID 수정은 written8/pending0, backup `var/patch-backups/step11b3c3d4h-fix-72ivw1kk`로 적용했다. 전달본 manifest SHA는 `6efd0adae3f620aecd1bc5455ac40195d78b8c158109b0013653116b07758b21`, tracked437개다. 서버44개 테스트는 통과했지만 실제 관찰은 DATABASE_CONTAINER_CHANGED_DURING_INSPECTION·topology_input_recheck로 실패했다. 이번 서버 명령에서는 기존192개를 다시 실행하지 않았다. inspection_completed/위치 관찰/공급 활성화와 모든 운영 변경 표식은 false다.

이번 범위는 읽기 전용 layout 검사에서 마운트 목록의 순서를 실제 변경으로 판단하는 오류와 자체 컨테이너 재확인 단계 표시를 수정하는 것이다. 실제 서버의 상세 inspect 응답을 확보하지 않았으므로 마지막 실패의 정확한 원인이나 SQL 통과 여부를 확정하지 않는다. 저장 경로 관찰 완료·공급 준비·백업·복원·credential 활성화는 포함하지 않는다.

## 재현과 수정

기존 fake DB는 마운트1개만 제공했다. 실제 compose는 데이터 volume, secret3개, init bind로5개를 갖는다. 모의 Docker inspect가 모든 경로·속성·PID·설정은 그대로 반환하고5개 마운트 순서만 매번 회전하게 했을 때 기존 코드에서 정확히 DATABASE_CONTAINER_CHANGED_DURING_INSPECTION·topology_input_recheck가 재현됐다. 이 로컬 재현에서는 catalog/metadata 명령을 각각2회 완료한 뒤 자체 마지막 비교가 실패했다. 서버에서 같은 경로를 실행했다고 주장하지 않는다.

Mounts는 canonical하고 고유한 Destination별로 전체 레코드를 비교한다. 목록과 객체 필드의 순서만 제외하며 Source/Type/Name/Driver/RW/Mode/Propagation·알려지지 않은 필드·중첩 값·JSON 타입까지 보존한다. RW=false와 숫자0도 다르게 판단한다. 추가·제거·목적지·실제 속성 변경은 계속 거부하고, 중복 목적지나 잘못된 응답은 승인하지 않는다. 값·경로·컨테이너 ID·HostConfig는 오류에 출력하지 않는다.

자체 마지막 비교 전에 database_layout_container_recheck를 명시한다. PID 변경, HostConfig 변경, 마운트 변경, 마운트 형식 오류를 각각 DATABASE_LAYOUT_CONTAINER_PID_CHANGED/DATABASE_LAYOUT_HOST_CONFIG_CHANGED/DATABASE_LAYOUT_MOUNTS_CHANGED/DATABASE_LAYOUT_MOUNTS_INVALID로 구분한다. 상위 topology의 기존 PID/volume/HostConfig·identity·source 검증은 그대로다. 자동 재시도·설정 보정·서비스 재시작·권한 변경은 하지 않는다. OID bigint SQL도 그대로 유지한다.

## 검증과 전달

Python3.12에서 layout52개·topology53개·observer17개·identity32개·공급90개, 총244개를 통과했다. 새8개 테스트는 전체 관찰에서5개 마운트의 반복 순서 변화, 객체 필드 순서,5개 마운트의 각 속성/타입/중첩 변경, 추가·제거·목적지 변경, 초기/최종 형식과 중복, PID·HostConfig 오류 구분, private failure report의 정확한 단계와 값 비노출을 확인한다. 기존 native 임시 디렉터리/WAL symlink 메타데이터와 명령 allowlist 검사는 유지한다.

패치 helper8개, baseline437개·결과438개 해시와8개 변경 파일을 확인한다. Python3.10 문법·백업 적용·재실행0개 쓰기·사용자 편집/새 파일 충돌 거부·env/key/authority sentinel 보존·적용 tree의52개 테스트를 확인한다. 기존 Go·DB migration·Compose·상위 도구·AGENTS는 byte 단위로 유지한다. 해당 실행 경로를 변경하지 않았으므로 Go/native PostgreSQL 전체 테스트나 서비스 smoke를 반복하지 않는다.

대상 운영 Docker/PostgreSQL에 접속하거나 이번 SQL을 실제 engine에서 실행하지 않았다. 로컬 모의 Docker 재현을 서버 root observer·실제 마운트·native SQL 인수로 표시하지 않는다. 패치는 적용 파일 백업만 만들며 DB와 운영 서비스는 변경하지 않는다. 이후 검사는 기존 read-only SQL/metadata와 제한된 root 디렉터리 관찰 범위다.

## 미완료와 다음 단위

이번 수정은 서버52개 테스트와 실제 관찰 실행에서 inspection_completed=true·layout_readiness=observed·active_database_storage_locations_observed=true가 확인돼야 인수한다. 다른 fixed code/stage가 나오면 같은 관찰 단위에서 진단한다. 현재 API0.7.0-device-delete/schema7/registry-only-v1·credential HTTP API/fence/business runtime 미활성 상태는 그대로다. 전체 backup_topology_verified/production_supply_ready/activation_allowed는 계속 false다.

저장 위치 관찰이 인수된 뒤 개별 경로의 host 물리적 대응, 전체 backup/snapshot/restore roots와 목적지, authority/lock/HBA/PKI 제외 및 DB/키 복구 절차를 후속 단위로 진행한다. 적용·실행 명령은 채팅에서만 제공한다.

## 서버 인수 결과 — 2026-10-08

이번 수정은 written8/pending0, backup `var/patch-backups/step11b3c3d4h-mount-fix-sux26fpc`로 적용됐다. 서버52개 테스트를 통과했고 revision `4151d24309168d3f0a31da870aed511f2d44cdf96f836431339187e4352c9062`에서 실제 검사는 status=inspected, inspection_completed=true, layout_readiness=observed, active_database_storage_locations_observed=true, blockers=[]다. PostgreSQL17.11 READ ONLY SQL과 UID999의 메타데이터가 정상 실행됐으므로 앞서 남긴 native SQL/저장 경로 관찰 인수 대기는 해소됐다. 이전 실제 inspect 배열을 읽지는 않았으므로 서버의 과거 순서 변동 원인을 확정하지 않는다.

PGDATA/WAL은 현재 볼륨 안의 비symlink 디렉터리이며999:999/0700, 사용자 테이블스페이스는0개다. 개별 host_path_verified와 설정 파일 physical_path_verified, 전체 backup_topology_verified/production_supply_ready/activation_allowed는 false다. 전체 결과와 후속 경계는 [서버 인수 기록](20261008-step11b3c3d4h-server-acceptance.md)을 따른다. 이 문서의 이전 대기/실패 문단은 당시 상태를 보존한 이력이다.
