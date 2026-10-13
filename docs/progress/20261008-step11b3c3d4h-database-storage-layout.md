# 단위 11-B3c3d4h — 실제 DB 저장 경로 관찰

작성일: 2026-10-08 · d4g 서버 인수 완료 · d4h 서버 파일 적용·테스트 통과/실제 카탈로그 검사 실패

## 선행 상태와 이번 완료 기준

d4g는 simsys4090/sh_test에서 written10/pending0, backup `var/patch-backups/step11b3c3d4g-chm059t1`, checked revision `61db0fcc701df8fc5d4e1087107513a60b6b01ac4db96779482d7df8e8ef9009`로 적용했다. tracked432개, topology53·observer17·identity32·공급90, 총192개가 통과했다. 실제 sudo 보조 연결과 root sender, 현재 volume의 host mount/source를 인수했다. SSD mountpoint `/media/simsys/SSD_EXT4`, ext4, DB directory999:999/0700, 중첩 mount0개다. 현재 volume proof는 verified지만 전체 backup topology·공급 활성화는 blocked다.

이번 단위는 실제 PostgreSQL 설정과 카탈로그에서 저장 위치를 가져와 컨테이너의 디렉터리·링크 메타데이터와 반복 대조하는 도구를 전달한다. PGDATA·외부 WAL/tablespace를 누락 없이 관찰하고, host 후보와 물리적 확인을 구분하며 변경·가용성 부족을 정직하게 보고하는 것이 완료 기준이다. 백업 생성·복원·공급 계획 완성·credential cutover는 포함하지 않는다.

## 구현과 쓰기 범위

새 검사와 테스트를 src/infra/tools에 추가했다. 기존 topology/identity/observer/supply의 실행 소스는 유지한다. 정확한 소유 DB에서 OS999:999의 고정 READ ONLY SQL과 stat/readlink 명령만 추가한다. 현재 data_directory 설정, 기본/custom tablespace 전체 개수·OID·위치, PGDATA 아래 pg_wal의 링크/해석 대상, config/HBA/ident의 문자열 위치와 archive_mode를 관찰한다. 이름·권한·비밀번호·archive_command·DB 파일 본문·목록을 읽지 않는다.

catalog/metadata의 크기·개수·타입·경로·디렉터리·실제 명령 UID/GID를 검사한다. 소유 process와 고정 host volume의 descriptor/mount identity를 저장 위치 관찰 전후 대조하고 전체 소스/env/receipt/key metadata·daemon·서비스 상태를 다시 확인한다. 보고서는 새 database-storage-layout.json/0600 하나이며 기존 coordination lock을 사용한다. 부모 보고서와 공급 검토 초안은 그대로 둔다.

새 결과의 layout_readiness=observed는 컨테이너 경로 관찰이다. host_path_candidate는 확인된 volume과 상대 경로의 문자열 후보이며 host_path_verified=false다. 외부 경로는 후보 null이다. archive 목적지와 전체 snapshot/backup/restore roots·물리적 제외·coordinated DB/key restore는 unresolved로 남긴다. production_supply_ready/activation_allowed·전체 backup proof를 올리지 않는다.

## 검증

Python3.12에서 새 검사41개·기존 topology53개·observer17개·identity32개·공급90개, 총233개를 통과했다. 새 검사에는 실제 임시 디렉터리/외부 WAL symlink, shell 기호가 있는 안전한 positional 경로, 개행 대상의 보존과 거부, dangling link·형식/타입/개수/권한·명령 allowlist·source 및 선행 인수·catalog/inode/process/volume/env 변경·재검사 명령 실패·private report와 비밀 원문 비노출을 포함한다. 파일 sentinel의 atime/mtime/mode를 보존하며 본문을 명령 결과에 포함하지 않음을 확인했다. 합성 Docker/catalog를 실제 운영 DB 관찰로 표시하지 않는다.

패치 helper8개, baseline432개와 새 source436개 전체 해시,9개 delta payload, dry-run·원본 백업 적용·재실행0개 쓰기·사용자 편집 및 새 파일 충돌 거부·env/key/authority sentinel 보존과 Python3.10 문법을 검증한다. 적용 tree의 새41개 검사도 확인한다. 기존 Go/SQL migration/Compose/상위 실행 소스를 byte 단위로 유지해 Go/vet/격리 PG 리허설을 반복하지 않는다.

로컬에 대상 서버 PostgreSQL/Docker를 연결하지 않았다. 새 SQL과 GNU coreutils의 실제 운영 이미지 호환성, 현재 data_directory/WAL/tablespace 결과는 서버 실행으로 인수한다. API0.7.0-device-delete/schema7/registry-only-v1/TLS off와 원본 키·서비스·권한·브라우저 인수 보류 상태는 유지한다.

## 다음 완료 기준

서버 테스트233개와 실제 검사에서 layout_readiness=observed, read-only transaction·metadata execution999:999·현재 volume 검증·안정된 저장 위치를 확인한다. blocked/failed면 fixed code/stage에 근거해 같은 단위의 문제를 해결하고 서비스나 권한을 임의로 변경하지 않는다. 성공 후 외부 경로가 있으면 실제 호스트 mount 대응을 확인하고, 모든 backup/restore root·목적지와 외부 authority/lock/HBA/PKI 물리적 제외를 완성한다. 실행·적용 명령은 채팅에서만 제공한다.

## 서버 실행 결과 — 2026-10-08

simsys4090/sh_test에서 written9/pending0으로 적용했다. patch backup은 `var/patch-backups/step11b3c3d4h-osak1nwz`다. 적용 전달본의 project manifest SHA는 `db2c08af60d1877aab4e69a4c6e8c6a15b0aefd2269e47fea77a8ff7d6a28748`, tracked436개다. 새41개·topology53개·observer17개·identity32개·공급90개, 총233개 테스트가 모두 통과했다.

실제 검사 결과는 failed, code=DATABASE_LAYOUT_TABLESPACE_INVALID, failed_stage=database_layout_catalog, inspection_completed=false다. active_database_storage_locations_observed=false이며 저장 경로를 인수하지 않았다. service/schema/database/key/HBA/env/권한/백업 생성 등 모든 변경 표식은 false다. 카탈로그 단계에서 중단해 새 디렉터리 metadata 명령은 실행되지 않았다.

SQL은 pg_tablespace의 oid 타입을 그대로 json_build_object에 넣었지만 PostgreSQL17은 이를 JSON 문자열로 전달한다. 파서는 정수 OID를 요구했고 모의 응답은 이미 정수였으므로 이 차이를 테스트에서 놓쳤다. 실제 서버의 원문 응답을 추가 수집하지 않았으며 사용자가 준 fixed code/stage와 PostgreSQL17.11 공식 소스의 타입 처리로 원인을 확인했다. 수정 및 재검사 상태는 [OID JSON 수정 기록](20261008-step11b3c3d4h-oid-json-fix.md)을 따른다.
