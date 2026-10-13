# 단위 11-B3c3a — credential admission DB 표식·준비 검사

작성일: 2026-10-07 · 소스·로컬 검증 완료 · 서버 native Docker 인수 완료

## 선행 인수와 범위

11-UI1a 서버 로그의 도구8개·전용 UI22개·환경 분리 및 관찰된 세 버전 복구를 인수했다. 브라우저 deferred와 전체 공용 환경 consistency 미주장은 유지한다. 사용자 요청대로 Jupyter 중계는 추가하지 않는다. 기존 11-B3c2 외부 state/lease의 native17개·2 phase 서버 인수도 유지한다.

이번 독립 단위는 schema9 DB marker·정확한 migration hash·두 역할의 읽기 전용 DB 준비 검사다. DB 표식 확인을 키 receipt/endpoint profile/작업 구간 lease에 결합하는 전체 B3c3는 하위 단위로 진행한다. production database/schema7·API0.7.0·기존 schema8 리허설을 이번 source 적용으로 변경하지 않는다.

## 변경과 의미

기존8개 SQL 파일·Migrate·CheckReady는 그대로다. 명시적 MigrateCredentialAdmission만 마지막9번 파일을 추가하여 기존 advisory lock/한 transaction에서 schema9를 만든다. 표식은 빈 상태로 생성하며 자동 ID·OPEN·budget·restore 작업이 없다. 실제 표식 설치 및 외부 PREPARED 통합은 후속 유지보수 단위다.

marker는 singleton, deployment/generation/operation/database incarnation/name, schema9, canonical migration hash 및 audit timestamp를 저장한다. 고정2개 credential 역할에 history/marker SELECT만 부여하는 별도 owner 호출을 추가했다. registry 역할의 private 권한을 확대하지 않는다.

CheckCredentialAdmissionDatabase는 실제 pool configuration, session/current user와 DB, LOGIN 및 role 속성, marker/history 변조·owner membership·schema CREATE 권한 부재, 전체9개 version/name/checksum 및 기대 표식을 read-only repeatable-read transaction에서 비교한다. 실패에 driver cause/SQLSTATE/비밀을 붙이지 않는 고정 오류만 반환한다. DB 검사의 성공은 credential 입장 승인이 아니다.

## 검증

| 검사 | 결과와 한계 |
|---|---|
| storage Go native race | Go1.25.1·PostgreSQL17.11에서 top63개 및 sub61개 통과. 기존 native credential13개와 새 admission DB5개 모두 실제 실행 |
| migration/history | 새 DB→9, 8→9, 재적용, 실패 rollback/retry, 기존 registry·사용42/disabled budget 보존, legacy8 target의9 거부 |
| marker/role | 빈/불일치 marker·UUID4/양수 generation/singleton/schema/hash 제약, writer/budget actual authentication, SET ROLE 차이, owner/다른 role, grant loss와 column/table/schema/owner membership·NOLOGIN/CREATEDB 확대 거부 |
| 실제 snapshot | pg_dump/custom 및 pg_restore/clean 실행. 새 기대 generation/operation/incarnation에서 오래된 dump 거부. 같은 옛 외부 기대값이면 옛 dump와 일치하는 한계도 재현 |
| Go vet | 전체 module 통과 |
| Python runner | 새 단위13개 통과. cleanup/timeout/실패 단계/불완전·skip transcript/source drift/inherited env/protected fixture 검사. 관련 기존 unit 포함53개 통과 |
| 계약 | jsonschema 기반 기존 admission 계약23개 통과 |
| 전달 | 전체 baseline/payload/manifest hash·최초 적용/재적용·백업 원문·보호 파일 보존·충돌 사전 거부·archive 검사 |

로컬 환경에는 Docker가 없으며 UID namespace에 UID0만 매핑되어 일반 비특권 UID로 PostgreSQL을 시작할 수 없다. 로컬 임시 PostgreSQL17.11 소스 빌드는 initdb/postgres 시작의 root 거부 조건 두 곳만 fixture 환경에 맞게 수정했다. SQL/인증/트랜잭션/backup 코드는 수정하지 않았다. 그 빌드·DB·password·로그는 패치에 포함하지 않으며 모든 DB process를 종료했다. 이 결과는 대상 Docker 이미지·UID/mount 인수를 대신하지 않는다.

전체 module race 시도에서 기존 crypto의 foreign UID chown 테스트가 namespace 제한으로 실패했다. 이를 pass/전체 module 인수로 표시하지 않는다. 수정 후 storage package 전체63개와 vet는 통과했고, 제공한 서버 runner는 기존 테스트를 건너뛰지 않고 unmodified postgres17.11-bookworm 및 golang1.27.1-bookworm에서 전체 module race/vet와 native snapshot을 요구한다.

API 프로세스·routing·제품 운영 Compose는 변경하지 않아 기존 smoke62개 결과를 유지한다. 새 Compose는 격리 검사 전용이다. 패치 apply는 파일과 private 원본 백업만 변경하고 서비스 재시작/DB DDL/실제 키/외부 state 작업을 하지 않는다.

## 남은 작업과 다음 기준

서버에서 새 runner unit13개 및 native schema9 검사 결과를 인수했다. 다음 독립 단위 11-B3c3b는 actual protected key loader의 exact-byte receipt와 승인된 단일 endpoint/TLS profile hash를 구현하고 두 실제 pool을 DB 기대값·키 영수증과 대조한다. 이후 전체 CredentialStore의 reserve/encrypt/save/replay/revoke/reference 작업 구간 shared lease, native FENCED→restore→PREPARED→fresh budget/marker→OPEN 유지보수 통합을 검증한다.

credential_runtime_admission_guard_implemented·production_restore_fence_implemented·credential_runtime_key_supply_verified·credential_api_activated·business_runtime_ready는 계속 false다. 운영 schema9 cutover는 후속 preflight/격리 리허설/activation으로 분리한다. 명령은 채팅에서만 제공한다.

## 서버 인수 — 2026-10-07

사용자 첨부 로그에서 source14개 적용·unit13개 OK·native passed를 확인했다. checked_revision은 81abb5d7962b9d9ed6dc01a2511faa5924185d18c56bc67de97fdc74031b8838이다. unmodified PostgreSQL17.11/golang1.27.1의 전체 module race/vet와 top140/sub406, 기존 native credential13개, 필수 DB5개를 인수한다. 8→9/기존 registry와 budget 보존/실제 role 권한/표식 및 history mismatch 거부/native dump restore 및 옛 binding 한계 재현이 통과했다. 로컬 UID 제한으로 인수하지 못했던 전체 crypto 검사도 서버 전체 module 인수에 포함한다.

격리 project vms-admission-db-test-5e24f62be088의 resources 제거와 production service/DB/key/admission 미변경을 확인했다. report는 var/camera/credential-admission-database-checks/vms-admission-db-test-5e24f62be088.json이다. credential API/restore fence/business runtime/작업 구간 guard는 아직 false이며 다음은 11-B3c3b 키·접속 profile 비교다.
