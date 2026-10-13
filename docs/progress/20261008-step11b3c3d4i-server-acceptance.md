# 단위 11-B3c3d4i — 서버 물리 경로 대응 인수

작성일: 2026-10-08 · 서버 테스트 47개와 PGDATA·WAL 대응 검증 완료

## 인수 근거와 리비전

사용자가 제공한 simsys4090/sh_test의 패치 적용·unittest·실제 privileged 검사 JSON을 근거로 기록한다. 제작 환경에서 운영 서버에 접속하거나 보고서 원본을 직접 읽지 않았다. 인수한 검사 revision은 `915be4ab56bfef53def591b38b5024920daf745f5525fb35d22f1ca893d1c745`이며 문서 패치 적용 후의 새 manifest 해시와 구분한다. 기존 d4h 저장 경로 관찰 영수증 `4151d24309168d3f0a31da870aed511f2d44cdf96f836431339187e4352c9062`도 그대로 보존한다.

| 항목 | 서버 결과 |
|---|---|
| 기능 패치 적용 | applied · written=11 · pending=0 |
| 기능 패치 백업 | var/patch-backups/step11b3c3d4i-v0amc64m |
| mapping 단위 검사 | 26개 통과 |
| directory observer 검사 | 21개 통과 |
| 이번 서버 검사 합계 | 47개 통과 |
| 실제 조사 | inspected · inspection_completed=true |
| 물리 대응 상태 | mapping_readiness=verified · individual_host_paths_verified=true |
| 현재 입력 | current_volume_mount_verified=true · current_storage_layout_observed=true |
| 현재 물리 대응 blockers | [] |
| 서버 보고서 위치 | /home/shshin/workspace/vms_project/var/camera/database-storage-mapping.json |

이전 구현 전달 시의 로컬 274개 검증은 별도 결과다. 이번 서버 명령에서 관련 248개 회귀 검사를 다시 실행했다고 주장하지 않는다.

## 확인된 두 디렉터리

| 디렉터리 | 컨테이너 경로 | 검증된 호스트 경로 |
|---|---|---|
| PGDATA | /var/lib/postgresql/data | /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data |
| WAL | /var/lib/postgresql/data/pg_wal | /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data/pg_wal |

두 행 모두 host_path_verified=true, host_path_without_symlinks_verified=true, same_directory_identity_verified=true다. 파일시스템은 ext4, owner UID/GID는 999:999, 권한은 0700이다. privileged_directory_observer_used=true와 privileged_sender_uid_verified=true로 실제 제한된 관리자 보조 사용과 root sender 검증을 인수했다. raw inode/device/PID나 파일 본문을 기록하지 않는다. 이는 해당 조사 구간의 반복 검증이며 지속적인 변경 방지나 정지된 snapshot 보장은 아니다.

d4h 관찰 당시의 host_path_verified=false는 과거 관찰값으로 유지한다. 이번 d4i의 검증 결과는 별도 영수증과 mapping 필드에 기록한다.

## 전체 준비 상태와 남은 범위

물리 대응은 verified지만 전체 readiness=blocked, production_supply_ready=false, activation_allowed=false, backup_topology_verified=false다. 다음 네 항목은 미완료다.

- ALL_BACKUP_AND_RESTORE_SNAPSHOT_ROOTS_AND_DESTINATIONS
- EXTERNAL_AUTHORITY_LOCK_HBA_AND_PKI_PHYSICAL_EXCLUSION
- COORDINATED_DATABASE_AND_KEY_BACKUP_RESTORE_PROCEDURE
- ARCHIVED_WAL_DESTINATIONS_AND_RETENTION_POLICY

이번 서버 JSON에서 서비스 재시작·DB/schema·키 본문 읽기/로드·admission 생성·HBA·환경·네트워크·호스트 권한 변경은 false다. DB 파일 본문 읽기·DB 디렉터리 목록 조회·백업 생성·snapshot root 생성도 false다. 공급 계획·승인 binding·공급 파일·authority bootstrap·runtime binding은 생성하거나 활성화하지 않았다. credential API/운영 restore fence/업무 runtime도 미활성이다. 앞서 인수한 API 0.7.0-device-delete·스키마 7 상태를 이 단위에서 전환하지 않았으며 이번 JSON으로 API 버전을 새로 조회했다고 주장하지 않는다.

## 인수 기록 패치 검증

이번 패치는 README·문서 목록·mapping 운영 안내·구현 기록·이 인수 기록·project-manifest.json, 6개 문서/메타데이터 파일만 변경한다. baseline 443개에서 이 문서 1개를 추가해 444개를 추적한다. src 전체와 Go/SQL/Compose/Makefile/AGENTS.md는 기존 바이트를 유지한다.

전달 검증은 적용 helper 8개, 전체 추적 해시, dry-run 6개·백업 적용 6개·재실행 0개, 사용자 변경 및 새 파일 충돌 시 쓰기 전 거부, 합성 .env/key/authority 보존, Python 3.10 helper 문법, 적용 tree의 mapping source gate와 기존 d4h 영수증 보존, 문서 링크와 아카이브 포함 범위를 확인한다. 문서만 변경하므로 운영 Docker/sudo·Go·PostgreSQL 검사를 반복하지 않는다. 적용 명령은 채팅에서만 제공한다.

## 다음 단위

다음은 모든 백업·snapshot·restore root와 목적지의 검토, 외부 authority/lock/HBA/PKI의 물리적 제외 범위 확정이다. 현재 두 디렉터리 대응을 출발점으로 삼되 전체 백업 범위를 자동 승인하지 않는다. 이 인수 기록 단위에서는 새 공급 경로·파일·권한·네트워크·백업·authority를 생성하지 않는다. Camera Streamlit 브라우저 인수는 기존 보류 상태를 유지한다.
