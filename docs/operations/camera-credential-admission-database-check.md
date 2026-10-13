# camera credential admission DB 격리 검사

상태: 11-B3c3a 구현 · 서버 native Docker 인수 완료 · [인수 근거](../progress/20261007-step11b3c3a-admission-database.md)

## 대상과 격리

src/infra/tools/test_camera_credential_admission_database.py는 전체 manifest/hash 및 새 DB revision을 검사한다. 기존 storage8/API 미구현과 guard 미구현 상태에서만 이번 검사를 수행한다. 새 Compose project vms-admission-db-test-임의값의 postgres17.11 tmpfs DB 및 binary exchange volume만 사용한다. 운영 .env, DB, 키, 외부 admission 경로를 읽지 않는다. port publish·production network·외부 volume이 없고 source만 RO mount한다. 상속 COMPOSE_/CAMERA_/VMS_ADMISSION_/PG 변수를 제거하며 빈 env-file과 합성 랜덤 password를 사용한다.

## 검사

Go1.27.1 서비스가 임시 DB에서 전체 module race test/전체 vet를 수행하며 schema8 기존 native credential13개 및 새 DB marker4개가 실제 통과해야 한다. storage race binary와 cmd/test2json을 빌드한다. 다음에는 같은 project의 PostgreSQL container에서 그 binary로 pg_dump/pg_restore를 실제 수행하는 표식 snapshot 검사를 실행한다. test2json terminal pass와 package pass, 필수5개 DB 검사, 기존 credential native13개를 모두 요구한다. selector skip·실패 후 pass·불완전 transcript를 인수하지 않는다.

마이그레이션8→9/새 DB→9/재적용/실패 rollback, 기존 registry와 사용 budget 보존, 빈 표식 거부·표식 제약, 실제 두 role 인증/SET ROLE 차이, 읽기 권한 상실과 column/table/schema/owner membership 권한 확대, 표식 binding·history/checksum/미래 버전 불일치를 검사한다. snapshot 복원은 새 기대 incarnation을 거부하고 같은 옛 기대값은 옛 dump와 다시 일치하는 한계를 재현한다. 이 기대값은 합성 fixture이며 실제 외부 lease/maintainer 흐름은 연결하지 않는다.

## 결과

var/camera/credential-admission-database-checks에 private log/report를 만든다. 실제 단계·마지막 완료 단계·받은 exit code를 실패 보고에 남긴다. 성공/실패 모두 자체 project만 down/volume 제거하며 cleanup 실패는 passed를 취소한다. 검사 동안 source 변경도 passed를 취소한다.

성공은 schema9 storage foundation의 native 인수다. 운영 DB 변경, 운영 표식 설치, 실제 키 로드, credential API 활성화, production restore fence 또는 business runtime 준비 완료를 뜻하지 않는다. 패치는 source 적용만 수행한다. 실행 명령은 채팅에서 제공한다.
