# schema7 등록 DB TLS 전환 준비

상태: 11-D1e 준비 도구 구현, 서버 인수 대기 · 운영 서비스 미전환

도구는 src/infra/tools/prepare_camera_registry_tls_cutover.py다. 기존 schema7 운영 API/DB와 D1c의 준비 공급, D1d 전체 격리 리허설 인수를 요구한다. 대상은 registry-only-v1이며 camera credential HTTP/schema9를 활성화하지 않는다.

## 준비의 동작

현재 source와 process identity·DB schema/TLS 상태·운영 image·HTTP 게시·network/data volume을 읽기만 확인한다. 기존 TLS 후보 receipt와 D1c 공급을 다시 검증하고 준비 디렉터리에 TLS runtime/migrator DSN·외부 HBA/ident·Compose 자료를 만든다. 새 control volume만 초기화하며 기존 TLS/data volume은 RO probe만 수행한다. API/DB/다른 플랫폼의 lifecycle 호출과 운영 환경 변경은 없다.

runtime은 camera_runtime의 기존 비밀번호와 verify-full을 사용한다. migrator는 camera_maintenance CN을 기존 camera_migrator에 매핑하는 cert 인증이다. 이는 비밀번호와 인증서를 함께 요구하는 인증이 아니다. TLS private key는 D1c 공급에 남고 새 Compose는 그 volume을 RO 참조한다. CA 서명 키와 credential 암호화 키를 읽거나 복사하지 않는다.

Compose config의 source·DSN/secret 경로·UID·RO/nocopy·고정 source IP·exact port·이미지를 검사한다. 다른 세 플랫폼의 resolved service는 현재 구성과 같아야 한다. 기존 default HTTP network는 Compose 소유 정의를 유지하며 storage/data/TLS/control은 external 참조한다. 구성만 해석하고 서비스는 실행하지 않는다.

## 결과와 재실행

| 필드 | 의미 |
|---|---|
| status | 준비 자료 미생성 planned, 최초 완료 prepared, 같은 자료 재검사 already_prepared |
| cutover_preparation_ready | 준비 파일·Compose 해석·offline 공급/control 검사 완료 |
| control_volumes_created | 최초1개, 재실행0개 |
| preparation_sha256 | source/env/image/network/DSN/control 내용을 묶은 준비 자료의 식별값 |
| compose_recipe_validated | 서버 Docker Compose가 자료를 해석하고 의미 검사 통과 |
| production_candidate_files_read·production_prepared_supply_files_read | candidate receipt·selected TLS 공급을 검사하므로 true |
| production_key_material_read·credential_key_material_read | camera credential 암호화 키를 읽지 않으므로 false |
| recipe_is_deployable·activation_allowed·database_tls_activated | 실제 전환 단계 이전이므로 false |

준비 자료는 caller 소유0700 디렉터리에 보관한다. DSN 파일은 기존 file bind 방식과 같은0444이며 다른 host 사용자의 디렉터리 접근은 허용하지 않는다. receipt/Compose/HBA/ident host 파일은0600이다. container의 control 파일은999:999/0400이고 RO로 공급된다. 이 단위는 기존 파일의 host 권한을 바꾸지 않는다.

불완전한 준비나 기존 내용/권한 변경은 실패한다. 덮어쓰기·자동 복구·기존 볼륨 재초기화를 하지 않는다. 실패 출력의 code/failed_stage로 중단 지점을 확인한다. 원문 secret·DSN·예외/상세 stderr는 공개하지 않는다. 새 준비 자원이 남을 수 있지만 운영 자원은 그대로 유지한다.

다음 전환 도구는 준비 receipt의 hash와 운영 상태를 다시 확인해야 한다. 준비 결과만으로 runtime의 운영 TLS 접속이나 주소 예약 완료를 표시하지 않는다. backup/restore를 새 선행 조건으로 만들지 않는다. 명령은 전달 채팅을 따른다.

[진행 기록](../progress/20261012-step11d1e-registry-tls-preparation.md) · [ADR0025](../architecture/decisions/0025-camera-registry-tls-production-preparation.md)
