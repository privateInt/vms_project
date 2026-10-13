# 단위 11-B3c3d4h 수정 — OID의 JSON 정수 변환

작성일: 2026-10-08 · 원본 d4h 서버 적용·테스트233개 통과/실제 카탈로그 실패 · 수정 서버8개 적용·44개 통과/실제 관찰 재실패

## 실패와 이번 범위

simsys4090/sh_test에서 d4h는 written9/pending0, backup `var/patch-backups/step11b3c3d4h-osak1nwz`로 적용했다. 전달본 manifest SHA는 `db2c08af60d1877aab4e69a4c6e8c6a15b0aefd2269e47fea77a8ff7d6a28748`, tracked436개다. 새41개·기존192개 테스트는 통과했다. 실제 검사는 database_layout_catalog 단계에서 DATABASE_LAYOUT_TABLESPACE_INVALID로 실패했고 inspection_completed/위치 관찰/공급 활성화는 false다. 운영 서비스·DB·schema·키·권한·HBA·환경·백업은 변경되지 않았다.

이번 단위는 JSON 생성 시 OID 타입을 정수로 명시적으로 변환하는 SQL 오류 하나를 수정한다. 저장 경로 관찰 기능 확대, 복원·백업·공급 계획·credential 활성화는 포함하지 않는다.

## 원인과 수정

이전 SQL은 json_build_object의 oid 필드에 pg_tablespace.oid를 그대로 넣었다. PostgreSQL17.11의 json_categorize_type는 int2/int4/int8/float/numeric을 JSON 숫자로 처리하고, 원래 oid 타입은 JSON 문자열을 만드는 OTHER 경로로 처리한다. 파서는 type(oid) is int를 요구했으므로 기본1663/1664도 문자열이면 거부된다. 모의 catalog가 정수 OID를 직접 제공한 탓에 SQL/JSON 타입의 차이를 놓쳤다. 실제 서버 원문 응답을 확보했다고 주장하지 않으며 사용자의 오류 단계와 공식17.11 소스의 타입 처리에 근거한 진단이다.

SQL의 JSON oid 값만 `oid::bigint`로 바꿨다. pg_tablespace_location에는 원래 OID를 넘기고 정렬·전체 개수/128개 제한·역할/READ ONLY guard·Docker 명령 제한·root 보조 범위는 그대로다. bigint는 unsigned OID의 signed int4 경계를 넘는 양수도 보존한다. Python의 정수/범위 검증을 느슨하게 하지 않고 문자열·불리언·소수·중복·범위 밖 값의 거부를 유지한다.

## 검증

Python3.12에서 저장 경로44개·topology53개·observer17개·identity32개·공급90개, 총236개를 통과했다. 새 회귀는 기본 OID가 문자열일 때 이전 오류가 재현되는지, signed int4 상한을 넘는 허용 정수 OID4294967294를 보존하는지, 문자열/불리언/소수/범위 밖 OID를 거부하는지를 확인한다. 기존 명령 allowlist·실제 임시 WAL symlink·drift·source/private report·원본 키 미열기 검사는 유지한다.

SQL 변환과 cast의 타입 처리 근거는 로컬에 있는 공식 PostgreSQL17.11 소스 및 공식 문서로 확인했다. 대상 운영 DB/Docker에는 접속하지 않았으며 PostgreSQL engine에서 새 SQL을 실행한 로컬 검증도 수행하지 못했다. 이 결과를 native SQL/실제 서버 저장 경로 인수로 표시하지 않는다. 수정된 실제 SQL은 서버 재실행에서 검증한다.

패치 helper8개·baseline436개와 결과437개 전체 해시·8개 변경 파일·Python3.10 문법을 확인한다. 원본 백업 적용·재실행0개 쓰기·사용자 편집/새 경로 충돌 거부·env/key/authority sentinel 보존과 적용 tree의44개 검사를 확인한다. 실행 소스의 변경은 새 검사 SQL 한 줄과 해당 테스트뿐이며 기존 Go/SQL migration/Compose/상위 도구는 byte 단위로 유지한다.

## 인수 기준

서버44개 검사와 실제 기존 사용자 실행에서 catalog 단계를 지나 layout_readiness=observed·active_database_storage_locations_observed=true를 확인한다. 다른 fixed code/stage가 나오면 같은 단위에서 증거에 맞게 수정한다. 실제 저장 위치와 GNU coreutils 호환성·전체 backup topology는 현재 인수 대기다. 전체 backup_topology_verified/production_supply_ready/activation_allowed·credential API/fence/business runtime은 계속 false다. 적용·실행 명령은 채팅에서만 제공한다.

## 서버 재검사 결과 — 2026-10-08

OID 수정은 written8/pending0, backup `var/patch-backups/step11b3c3d4h-fix-72ivw1kk`로 적용했고44개 검사는 통과했다. 전달본 manifest SHA는 `6efd0adae3f620aecd1bc5455ac40195d78b8c158109b0013653116b07758b21`, tracked437개다. 이번 서버 명령에서는 기존192개를 다시 실행하지 않았다. 실제 관찰은 DATABASE_CONTAINER_CHANGED_DURING_INSPECTION·topology_input_recheck로 실패했다. inspection_completed·active_database_storage_locations_observed·activation_allowed·production_supply_ready와 모든 운영 변경 표식은 false다.

오류 단계는 상위 topology 함수의 마지막 단계가 남은 상태에서 layout 자체의 컨테이너 비교가 실패해도 동일하게 표시된다. 이 응답만으로 실제 PID·설정·마운트 변경이나 카탈로그 통과 여부를 확정하지 않는다. OID bigint 변환은 유지하지만 native 운영 SQL·저장 위치 인수는 계속 대기다. 같은 단위의 [마운트 재확인 수정](20261008-step11b3c3d4h-mount-recheck-fix.md)으로 이어서 검증한다.
