# 단위 11-B3c3d4j — 백업 경계 검토 초안 서버 인수

작성일: 2026-10-08 · 서버 테스트 120개와 실제 초안 생성/재실행 완료

## 인수 근거

사용자가 제공한 simsys4090/sh_test의 패치 적용·테스트·두 번의 실제 준비 JSON을 근거로 기록한다. 제작 환경에서 서버에 접속하거나 private 초안 본문을 직접 읽지 않았다. 검사 revision은 `d707d61c980023afbc32b71ba6217e25c04eb0a408d4689fddc9b63606e837c5`다. 이 인수 기록 패치가 생성하는 새 manifest 해시와 해당 검사 영수증을 구분한다. 기존 d4i 물리 대응 영수증 `915be4ab56bfef53def591b38b5024920daf745f5525fb35d22f1ca893d1c745`도 유지한다.

| 항목 | 서버 결과 |
|---|---|
| 기능 패치 | applied · written=8 · pending=0 |
| 기능 패치 백업 | var/patch-backups/step11b3c3d4j-t6lsoypy |
| 새 검토 도구 테스트 | 30개 통과 |
| 공급 관련 회귀 테스트 | 90개 통과 |
| 이번 서버 합계 | 120개 통과 |
| 첫 준비 | prepared · review_file_created=true |
| 재실행 | already_prepared · review_file_created=false |
| 두 번의 실제 검사 | inspection_completed=true · current_storage_verified=true |
| 두 번의 초안 가용성 | review_available=true · 같은 파일 위치와 내용 SHA |
| privileged 옵션 | privileged_directory_observer_requested=true |
| 코드 선언 후보 / 미확정 항목 | 8곳 / 22개 |
| 계획과 전체 준비 | incomplete / blocked |

초안의 서버 위치는 `/home/shshin/workspace/vms_project/var/camera/credential-backup-reviews/review-393445ad295d1cc17efe54192d4716dbf9a5095a8047640ea1a99e40b95187d5.json`이며 내용 SHA는 `393445ad295d1cc17efe54192d4716dbf9a5095a8047640ea1a99e40b95187d5`다. 원본 private 파일을 이 패키지에 포함하지 않는다. 이번 공개 JSON으로 실제 fresh mapping 실행과 동일 초안 재실행을 인수하며, 내부 row의 별도 root sender 상세나 디렉터리 권한을 새로 직접 관찰했다고 주장하지 않는다.

로컬 구현 검증 167개는 이전 전달 결과다. 이번 서버에서는 mapping 26개와 observer 21개의 별도 unittest를 다시 실행하지 않았다. 실제 준비 과정이 기존 mapping inspector를 호출한 결과와 단위 검사 실행 횟수를 구분한다.

## 남은 준비 항목

백업·snapshot·restore 작업, 모든 source/backup destination/restore destination·staging, remote materialization, 물리 snapshot의 포함·제외 기능, declared roots, archive/retention 정책, DB·키의 연계 절차 11개 선언이 미확정이다. authority·안정 lock·DB HBA/configuration·TLS CA/server cert/key·maintenance cert/key·maintenance/runtime DSN 위치 11개도 미확정이다.

코드 선언 후보 8곳의 실제 존재/물리 대응이나 운영자의 모든 job 목록을 인수하지 않는다. backup/snapshot/restore_jobs_discovered=false, referenced_backup_locations_opened=false다. backup_topology_verified=false, external_control_exclusion_verified=false, paired_database_key_recovery_verified=false, production_supply_ready=false, activation_allowed=false를 유지한다.

서비스 재시작·DB/schema·키 본문 읽기/로드·admission 생성·HBA·환경·네트워크·호스트 권한·기존 supply review 변경은 모두 false로 보고됐다. DB 파일 본문/디렉터리 목록 조회·백업/snapshot root 생성·공급 계획/승인 binding/공급 파일/authority bootstrap/runtime binding도 수행하지 않았다. credential API/운영 restore fence/업무 runtime은 미활성이다.

## 인수 기록 패치 검증

README·문서 목록·운영 안내·구현 기록·이 인수 기록·project-manifest.json, 6개 문서/메타데이터 파일만 변경한다. baseline 448개에서 이 문서 1개를 추가해 449개를 추적한다. src 전체·Go/SQL/Compose/Makefile/AGENTS.md의 바이트와 기존 인수 영수증은 보존한다.

검증은 적용 helper 8개, 전체 추적 해시, dry-run 6개·백업 적용 6개·재실행 0개, 사용자 변경/새 파일 충돌 시 쓰기 전 거부, 합성 .env/key/authority/기존 backup review 보존, Python 3.10 helper 문법, 적용 tree의 backup review source gate, 문서 링크와 아카이브 범위다. 문서만 변경하므로 운영 Docker/sudo·Go·PostgreSQL이나 기존 120개 테스트를 반복하지 않는다. 명령은 채팅에서 제공한다.

## 다음 단위

다음은 실제 backup/snapshot/restore job·source/destination/staging와 외부 제어 위치의 선언을 구체화하는 검토다. 미확정값을 승인된 경로로 자동 승격하거나 전체 backup topology를 완료 처리하지 않는다. 물리 alias/snapshot 제외와 연계 복구, 실제 공급·전환은 각각 후속 검증을 따른다. Camera Streamlit 브라우저 인수는 기존 보류 상태를 유지한다.
