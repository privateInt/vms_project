# 백업·복원 경계 검토 초안 — 11-B3c3d4j

src/infra/tools/prepare_camera_credential_backup_review.py는 실제 두 고정 PGDATA/WAL 경로를 다시 검증한 뒤 불완전한 백업 경계 worksheet를 만든다. d4i 서버 인수 영수증과 현재 전체 소스 해시를 요구한다. 이전 storage/supply 보고서는 현재 증거로 읽거나 덮어쓰지 않는다. 명령은 채팅에서 제공한다.

## 연결하는 근거

| 항목 | 근거와 의미 |
|---|---|
| 현재 PGDATA·WAL | 기존 mapping inspector의 실제 READ ONLY SQL·stat·O_PATH·process/mount 반복 검사 |
| 현재 profile | 현재 volume 내 WAL·사용자 테이블스페이스 없음·archive off를 mapping이 요구 |
| DB 덤프 후보 7곳 | 추적된 activation 코드의 고정 저장 위치 선언 |
| 키 백업 후보 1곳 | 추적된 key backup 코드의 고정 저장 위치 선언 |
| 전체 프로젝트 복사 후보 | project root를 재귀 복사/복원한다면 포함될 수 있는 검토 범위 |
| 원본 키 참조 | 기존 inventory의 고정 경로만 표시, 키 본문·hash·복구 가능성 미검증 |

코드 선언은 해당 백업이 존재하거나 현재 실행되는 작업이라는 관측이 아니다. 후보 디렉터리를 stat/open/list하지 않는다. 코드와 선언이 달라지면 고정 오류로 중단하며 경로를 추측해 채우지 않는다. mapping이 blocked면 초안을 생성하지 않고 status=blocked로 반환한다. symlink·inode·mount·source/profile 변경은 기존 failed 경계를 유지한다. 실제 반복 조사는 정지된 snapshot이나 지속적인 변경 방지 장치가 아니다.

## 필요한 선언 22개

required_declarations는 운영자가 검토할 내용이며 모두 null로 둔다. backup_jobs/snapshot_jobs/restore_jobs, 모든 source root·backup destination·restore destination/staging, remote destination의 복원 materialization, 물리 snapshot 범위와 exclusion 기능, declared_snapshot_roots, archived WAL 목적지/보존 정책, DB·키의 연계 백업/복원 절차 11개가 필요하다.

외부 제어 선언 11개는 authority directory, 안정 lock receipt, DB HBA, DB configuration, TLS CA/server certificate/server private key, maintenance client certificate/private key, maintenance DSN 파일과 runtime DSN 파일이다. 미래 공급 위치를 선택하거나 파일을 생성하지 않는다. 임의 null을 예제 경로로 채우지 않는다.

경로 component 비교에 더해 실제 no-follow metadata·symlink/bind alias·mount source·ancestor 범위를 확인해야 한다. 파일 단위의 lexical exclusion만으로 filesystem/block/host/VM snapshot의 rewind 범위를 제외했다고 볼 수 없다. 원격 백업도 다시 materialize되는 staging과 최종 restore 목적지를 포함해야 한다. authority·안정 lock·HBA·PKI의 독립 보존과 fenced restore, 복원 후 새 독립 key/incarnation/budget을 검증해야 한다.

현재 archive off를 확인해도 운영자 backup job 목록, 과거 보관본과 미래 archive/retention 정책을 알 수 없다. declared_snapshot_roots가 현재 모든 source/destination/restore 범위를 포함한다는 실제 검증은 후속이다. worksheet는 기존 SupplyPlan과 승인 binding·runtime authorization으로 사용할 수 없다.

## 저장과 보존

기본 실행은 fresh 검사를 수행하고 status=planned, review_file=null로 반환한다. apply 옵션은 var/camera/credential-backup-reviews(0700)의 review-<내용SHA>.json(0600)에 검토 문서만 저장한다. 새 내용은 prepared, 동일 내용 재실행은 already_prepared다. revision이나 공개 경로 metadata가 바뀌면 새 내용 파일을 만들고 이전 버전을 보존한다. 다른 supply review 디렉터리와 별도로 저장한다.

기존 create-only publisher에 내부 고정 directory 선택 인수만 추가했다. 기본 supply review 경로와 처리는 유지한다. 기존 파일의 edit/symlink/hardlink/mode/owner/size/읽는 중 metadata 변경과 publication race는 고정 코드로 중단한다. 쓰기 범위는 coordination directory/activation.lock과 새 초안 directory/file이다. 참조된 백업/키/제어 파일·공급 review·기존 보고서·환경·서비스·DB/schema·HBA·네트워크·호스트 권한은 수정하지 않는다.

privileged-directory-metadata 옵션은 기존 두 고정 디렉터리 보조만 재사용한다. 전체 inspector를 root로 실행하지 않는다. 임의 backup root/authority/PKI 경로를 root helper에 추가하지 않는다. 새로운 Docker exec나 SQL을 추가하지 않는다.

plan_state=incomplete, readiness=blocked, backup_topology_verified/production_supply_ready/activation_allowed=false, external_control_exclusion_verified=false를 유지한다. prepared는 초안 저장 완료이며 전체 백업 준비나 운영 자격증명 활성화가 아니다. server stdout에는 위치 후보의 상세 내용 대신 개수와 미확정 field 이름·private 파일 위치를 반환한다.

## 검증과 후속

로컬 Python 3.12의 기존 독립 테스트 환경에서 새 30개와 mapping 26개·observer 21개·공급 관련 90개, 총 167개를 통과했다. 합성 Docker/kernel 입력과 실제 임시 파일 publication 검증이다. 이번 서버에서는 새 30개와 공급 90개, 총 120개 검사를 통과했다. mapping/observer의 별도 단위 검사를 다시 실행했다고 주장하지 않는다. [작업 기록](../progress/20261008-step11b3c3d4j-backup-boundary-review.md)

2026-10-08 사용자 제공 simsys4090/sh_test JSON에서 실제 privileged 옵션의 fresh 저장 경로 검증과 초안 prepared → already_prepared를 인수했다. 두 번 모두 current_storage_verified=true, known_code_location_count=8, unresolved_field_count=22다. 인수 revision은 `d707d61c980023afbc32b71ba6217e25c04eb0a408d4689fddc9b63606e837c5`, 초안 내용 SHA는 `393445ad295d1cc17efe54192d4716dbf9a5095a8047640ea1a99e40b95187d5`다. private 보고서 본문이나 별도 privileged sender 상세를 직접 읽은 결과는 아니다. 전체 물리 backup topology/external exclusion은 미검증이며 incomplete/blocked를 유지한다. [서버 인수 기록](../progress/20261008-step11b3c3d4j-server-acceptance.md)

다음 단위는 생성한 초안의 누락 선언을 구체화하고 source/destination/restore 경로 및 외부 제어 위치의 관계를 검토하는 것이다. 전체 host의 임의 backup job을 자동 발견하거나 새 경로에 파일을 배치하는 기능은 이 도구에 없다.
