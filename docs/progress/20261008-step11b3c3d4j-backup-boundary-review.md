# 단위 11-B3c3d4j — 백업·복원 경계 검토 초안

작성일: 2026-10-08 · 구현·로컬 167개 완료 · 서버 120개 및 실제 초안 생성/재실행 인수 완료

## 선행 인수와 이번 범위

사용자 서버 결과로 d4i mapping 26개·observer 21개와 실제 PGDATA/WAL 대응을 인수했다. 검증 revision은 `915be4ab56bfef53def591b38b5024920daf745f5525fb35d22f1ca893d1c745`다. 이어 인수 기록 6개가 applied/written=6/pending=0, 백업 var/patch-backups/step11b3c3d4i-notes-f16q9yoc로 적용됐다. 이번 baseline은 그 전달본 manifest `c086d526e89f1c9bc4ed274542428dfcdc2953b75937a59b6f7006f1da55e5ff`, 추적 444개다. 운영 서버에 직접 접속하거나 private 보고서를 읽지 않았다.

이번 결과는 현재 두 저장 경로를 새로 확인하고, 코드 선언 백업 위치와 운영자가 선언해야 할 전체 source/destination/restore 범위 및 외부 제어 경계를 담은 불완전 worksheet를 생성하는 것이다. 백업/복원 실행·공급 파일 생성·authority bootstrap·schema9/credential API 전환은 포함하지 않는다.

## 구현

새 도구와 테스트는 src/infra/tools에 있다. accepted d4i receipt·전체 tracked hash·새 구현 flag·참조 코드 포함을 검사한다. 기존 mapping inspector를 fresh 실행하고 성공한 정확한 공개 metadata만 다시 구성해 저장한다. 원본 키·백업·HBA/PKI 파일·이전 report를 읽지 않는다. 코드에 선언된 DB dump 후보 7곳과 키 백업 후보 1곳은 literal이 현재 추적 코드와 일치하는지만 확인하며 존재/물리 대응/전체 inventory 포함 주장은 false다.

required_declarations 22개는 null이다. 전체 backup/snapshot/restore 작업·source/destination/staging·remote materialization·물리 snapshot 제외 기능·declared roots·archive 정책·DB/키 연계 절차 11개와 외부 제어 위치 11개다. project recursive-copy와 기존 원본 키 위치는 검토용 참조다. 기존 supplied plan/review를 덮어쓰거나 deployable plan으로 완성하지 않는다.

create-only publisher는 내부 directory 인수만 추가해 새 private 검토 폴더를 지원하고 기존 supply review의 기본 동작을 보존했다. fresh 조회 실패 시 저장하지 않고, source 재검사를 통과한 뒤 prepared/already_prepared로 내용 SHA 파일을 반환한다. root helper 범위/SQL/명령 allowlist·Go/DB/Compose는 변경하지 않는다. 전체 backup topology와 외부 control physical exclusion은 미검증이며 readiness=blocked와 activation_allowed=false를 유지한다.

## 검증

기존 독립 Python 3.12 환경의 jsonschema를 사용했고 공용 환경에 의존성을 설치하지 않았다. 새 테스트 30개와 공급 90개·mapping 26개·observer 21개, 총 167개가 통과했다. fresh 실제 검사 호출 경로는 합성 Docker/kernel 데이터로 검증하고 publication은 실제 임시 파일로 검증했다.

새 검사는 accepted source/receipt·tracked 선언 drift·old report 미사용·key/backup IO 금지·blocked/failed mapping·archive profile 변경·source 재검사·공개 metadata의 타입/불필요 필드 제거·SupplyPlan 거부를 확인한다. 새 private directory/mode·재실행·revision별 이전 버전 보존·보호 파일 content/mode/mtime·사용자 편집·symlink/hardlink·잘못된 권한·oversize·publication race·root/CLI guard·고정 오류 비밀값 비출력을 포함한다. 기존 publisher 27개를 포함한 공급 90개는 default directory 동작을 확인한다.

패키지 검증은 적용 helper 8개, baseline 444개/결과 448개 전체 hash, 8개 변경 파일, Python 3.10 문법, source gate, 백업 적용/재실행, 사용자 변경·새 파일 충돌 거부, .env/key/authority 합성 sentinel 보존과 문서 링크를 확인한다. 적용 tree에서도 새 30개 검사를 확인한다. Go/라우팅을 변경하지 않아 Go/vet/smoke/native PostgreSQL을 반복하지 않는다.

## 전달 당시 서버 인수 기준과 다음 단위

운영 서버에서는 파일 적용과 새 테스트 30개·공급 회귀 90개 통과를 확인한다. 기존 제한된 privileged directory observer를 사용하는 fresh 검사 후 새 private 초안 prepared, 재실행 already_prepared, known_code_location_count=8·unresolved_field_count=22·current_storage_verified=true를 인수한다. plan_state=incomplete/readiness=blocked와 production_supply_ready/activation_allowed/backup_topology_verified=false는 예상 결과다. 최초 metadata 권한/가용성 부족으로 blocked면 초안은 생성하지 않으며 고정 blocker를 같은 단위에서 확인한다.

다음은 생성한 초안의 실제 backup/snapshot/restore 작업·포함 범위·destination/staging와 외부 authority/lock/HBA/PKI 위치 선언을 구체화하는 검토다. 현재 source 후보를 전체 백업 인벤토리로 승인하지 않는다. 별도 물리 path/alias/snapshot 제외·연계 복구 절차와 실제 공급/전환은 후속 단위다. Camera Streamlit 브라우저 인수와 Jupyter 중계는 기존 보류 상태를 유지한다. 사용자 적용·실행 명령은 채팅에서만 제공한다.

## 서버 실행 결과 인수 — 2026-10-08

사용자 제공 실행 결과에서 파일 applied/written=8/pending=0, 백업 var/patch-backups/step11b3c3d4j-t6lsoypy, 새 테스트 30개와 공급 회귀 90개 통과를 확인했다. 실제 revision은 `d707d61c980023afbc32b71ba6217e25c04eb0a408d4689fddc9b63606e837c5`다. 이번 서버 검사 120개는 전달 당시 로컬 167개와 구분한다.

실제 fresh 검사 후 prepared, 재실행 already_prepared이며 두 번 모두 inspection_completed/current_storage_verified=true다. 내용 SHA `393445ad295d1cc17efe54192d4716dbf9a5095a8047640ea1a99e40b95187d5`와 같은 파일 위치를 유지했고 두 번째 review_file_created=false다. privileged_directory_observer_requested=true이며 코드 선언 후보 8곳과 미확정 22개는 그대로다. 제작 환경에서 서버에 접속하거나 private 초안 본문을 읽지 않았다.

서버의 서비스·DB/schema·키·권한·네트워크·기존 review 변경 표식은 모두 false다. backup/snapshot/restore job discovery와 참조 백업 위치 open, 전체 backup topology·외부 control exclusion·DB/키 연계 복구는 미완료다. 계획 incomplete·전체 준비 blocked·활성화 불가는 예상 상태로 유지한다. [상세 서버 인수](20261008-step11b3c3d4j-server-acceptance.md)
