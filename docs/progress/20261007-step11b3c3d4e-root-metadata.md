# 단위 11-B3c3d4e 재수정 — root 메타데이터와 대조 경로 검증

작성일: 2026-10-07 · root 수정 서버165개 테스트·집계 인수 완료 · 실제 volume mount는 권한 부족으로 blocked

## 관찰과 범위

사용자 simsys4090/sh_test 로그에서 첫 수정 written8/pending0, backup=var/patch-backups/step11b3c3d4e-fix-yguoyxty를 확인했다. native directory/fdinfo 테스트는 MOUNTINFO_ROOT_PATH_INVALID로 재실패했다. 36개 중 오류1개이며 이후 identity32개·공급90개·실제 volume inspector는 set-e로 실행되지 않았다. 서버 문제 원문이 없으므로 root의 정확한 형태는 확정하지 않는다. 첫 수정의 //deleted 처리만으로는 서버 파싱 문제를 해결하지 못했다.

서버에 적용된 project manifest SHA4f39b1beeddd8e8ce92a396aa2b8d9d0bddbb25cf5993b961ef2deefc54de648 / tracked427개를 이번 delta 기준으로 사용한다. d4d 실제 init identity 인수와 운영 schema7/API0.7.0-device-delete는 유지하며 complete backup topology·credential binding/API·production restore fence·business runtime은 아직 미완료다.

## 이번 변경

파서는 root를 lookup path가 아닌 커널 출력 메타데이터로 정확히 보존한다. 비어 있지 않은 필드·NUL/escape·record 구조·크기/개수 한도는 계속 검사한다. mountpoint와 parent tree 규칙은 유지하고 mount record를 삭제하거나 숨기지 않는다. 실제 대조에 선택된 host/DB root의 기존 canonical 검사는 경로 계산 전에 유지한다. 비정규 root끼리 일치하거나 정규화하면 일치해 보이는 경우에도 DATABASE_MOUNT_ROOT_NOT_CANONICAL로 실패한다. 같은 device 번호만으로 source를 승인하지 않는다.

추측 대신 서버의 실제 표기 분포를 볼 수 있도록 own mountinfo 형태별 진단을 추가했다. 고정9개 키와 개수만 출력하며 원문·mount ID·PID·filesystem source·option을 출력하지 않는다. source 전체 hash를 확인하지만 Docker/DB/API/SQL·키/환경/authority에 접근하지 않으며 보고서나 lock도 쓰지 않는다. 진단 성공은 파싱 집계일 뿐 DB mount proof가 아니며 diagnostic_only=true·database_volume_mount_verified=false다. 일반 volume inspector의 read/write 범위와 실패 보고서는 유지한다.

## 검증

마운트43개와 기존 identity32개·공급90개를 로컬 Python3.12에서 통과했다. 상대 표기·중복 slash·parent component의 합성 root 3종으로 첫 수정의 MOUNTINFO_ROOT_PATH_INVALID를 재현했다. 이 결과는 서버의 실제 형태를 확정하는 증거가 아니다. 이번 버전에서 root 원형과 모든 record를 보존하고 선택 root이면 host/DB 양쪽에서 거부함을 검사했다. 상위 overmount·nested WAL mount·fd/device/root/권한/drift 검증을 유지한다.

기존36개 중 파서의 전역 canonical 거부를 요구하던 검사는 메타데이터 보존과 실제 선택 root 거부로 경계를 옮겼다. 비어 있는 필드/NUL/unknown escape/잘못된 mountpoint/record 한도 거부는 남겼다. 추가7개는 비정규 root별 전체 proof·선택 root·상위/중첩 mount 보존, 진단의 읽기 범위·파일/보고서 보존·CLI 분기·오류 비노출·고정 키 집계를 검사한다. 기존 native O_PATH/own fdinfo/mountinfo 테스트를 유지해 통과했다. Python3.10 문법도 확인하며 새 의존성은 없다.

source/test·manifest·문서8개 delta와 전체 baseline427개 hash/source428개를 검사한다. helper8개, dry-run·원본 백업 적용·재실행·사용자 편집/새 경로 충돌 거부·env/key/authority sentinel 보존을 확인한다. 적용 payload에서43+32+90개와 별도 native 진단을 확인한다. 기존 Go/SQL/Compose·상위 검사 소스는 byte 단위로 유지하므로 관련 Go/vet/PG 리허설을 반복하지 않는다. 로컬에 운영 Docker가 없어 실제 서버 볼륨 대조 성공은 아직 주장하지 않는다.

## 다음 완료 기준

수정 적용 후 서버 own mountinfo 집계를 먼저 인수하고 마운트43개·identity32개·공급90개·실제 topology inspector를 확인한다. 선택된 root가 비정규면 실제 filesystem/경로 증거를 보완하기 전까지 거부 상태를 유지한다. topology_readiness=verified 또는 blocked_stage/blocker를 인수한 뒤 공급 위치·모든 backup/restore roots 검토로 진행한다. 자동 권한 변경·키 공급·DB cutover·서비스 재시작은 이번 범위에 없다. Streamlit browser acceptance는 deferred이며 중계는 추가하지 않는다. 실행 명령은 채팅에서만 제공한다.

## 서버 인수 — 2026-10-07

simsys4090/sh_test 로그에서 root 수정 written8/pending0와 backup=var/patch-backups/step11b3c3d4e-root-ihry22v3를 확인했다. checked revision은 e7055fd06997db432eca2220cf87b9e176584a524af4cdfd3b0ca3d8bcf9ef12이며 tracked428개다. 마운트43개·identity32개·공급90개 총165개가 통과했다. 별도 형태 진단은 status=inspected/inspection_completed=true로 mount369개, canonical_absolute269개·relative_or_synthetic100개를 집계했다. 나머지7개 형태는0개다. 원문·PID·mount ID를 출력하지 않고 보고서를 변경하지 않았다. 상대/합성 표기의 존재는 확인했지만 해당 mount의 원문·종류·이름은 집계만으로 확정하지 않는다.

실제 topology inspector도 status=inspected/inspection_completed=true로 완료됐다. 현재 process identity는 verified이나 volume은 HOST_STORAGE_METADATA_PERMISSION_REQUIRED, blocked_stage=host_database_directory, topology_readiness=blocked다. 선언 경로는 /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data다. 어느 component에서 거부됐는지는 이 버전이 출력하지 않아 후속 d4f에서 진단한다. database_volume_mount_verified/local_host_path_verified/host_path_without_symlinks_verified/backup_topology_verified는 모두 false이며 운영 변경·key material 읽기·activation은 없다. root 파서와 집계 진단을 인수하며 volume 대조 성공이나 전체 backup topology 인수로 올리지 않는다.
