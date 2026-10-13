# 11-D1d 수정 — 새 HTTP fixture ID와 요청 실패 진단

상태: 원인 결함 재현·수정·로컬 검증 완료 · 대상 서버 재인수 대기

## 서버 결과와 재현

2026-10-12 사용자 제공 simsys4090/sh_test 출력에서 원래 D1d 패치 SHA256ac92706daa9c9340988b9e235c3ad795453be197fa499df4c4555b36fb5b2028 checksum OK, applied/written11/pending0, patch 이력 var/patch-backups/step11d1d-u8cckz65를 확인했다. 패치의 restart/runtime activation/schema modification은 false다. Python22개는2.594초에 OK였다.

native scope camera_registry_schema7_tls_cutover_native_docker, project vms-registry-tls-test-5c10fc73ffda의 status는 failed다. checked_revision은 e745d617cb4be4c45c5f3df30c7c97e9e826b6036ee91979d1375f26ab1ef83f다. code=REGISTRY_TLS_REHEARSAL_FAILED, failed_stage=plaintext_registry_seed, last_completed_phase=null, last_command_exit_code=0이다. Go policy race/vet은 true, isolated_resources_removed/synthetic_input_removed/isolated_diagnostics_collected는 true다. test API image708d5a53f3dcc3d22dca775ef2825bcd271a68c7c3777cf8a6a89bb6933aa7d6, DB image248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201를 선택했다. 전체 전환 성공 전 running_image_reused_for_test=false이므로 image ID 선택을 전환 완료로 기록하지 않는다. 운영 service/DB/schema/HBA/.env/network·키/admission·후보/D1c 공급·활성화·백업/restore 관련 공개 필드는 모두 false다.

원격 traceback이나 HTTP 응답은 제공되지 않았다. 동일 source의 최초 PATCH 경로를 네트워크 없이 실행하여 ActivationError/INVALID_TEST_RESOURCE를 확정 재현했다. D1d의 before-tls-device는 Step10 mutation_request가 허용한 upgrade-test와 다르다. 이 helper가 요청 전에 중단하는 결함은 최초 seed 단계와 일치한다. 기존22개 unit은 campaign을 mock 처리했으므로 이 ID 제한 결함을 발견하지 못했다.

## 수정

D1d 전용 실제 HTTP client를 사용해 POST/PATCH/DELETE를 전송한다. 허용 collection/method·before-tls/retained/after-tls의 장치/소스 ID·명시적 loopback endpoint를 검사한다. 같은 Bearer/Content-Type/Idempotency-Key와 JSON 입력을 유지한다. redirect·proxy 환경을 따르지 않으며 HTTP 오류는 API 계약 응답으로 반환한다. 기존 Step10 helper의 fixture 제한은 변경하지 않는다.

malformed JSON/non-object response·transport 오류·seed/replay receipt 불일치에는 RegistryHTTPError와 failed_http_step을 기록한다. 공개 JSON은 collection/method/synthetic resource_id/status/형식 검증한 API error code만 포함하고 요청·응답 body, token, headers, 원래 예외 문자열을 포함하지 않는다. 기존 ActivationError의 안전한 대문자 code도 보존한다. 알 수 없는 exception은 일반 code와 검증한 exception_type만 기록한다. failed_stage·private DB/API diagnostics·cleanup은 유지한다.

## 검증

| 검사 | 결과 |
|---|---|
| 이전 코드 실패 재현 | before-tls-device PATCH가 socket 연결 전에 INVALID_TEST_RESOURCE로 거부됨 |
| Python32개 | 통과. 기존22개와 새10개: 실제 loopback packet18개로 모든 synthetic ID/verb·헤더·JSON 확인, HTTP error/redirect/proxy/잘못된 경로·endpoint·JSON·transport·안전한 실패 report |
| 실제 현재 Go API/PostgreSQL17.11 | 새 schema8 DB와 수정 없는 현행 Go API에서3개 campaign·성공 receipt14개·활성 자식409 후 같은 parent key 재시도·전체 이력 재생·목록/tombstone·API process 재생성 통과 |
| fingerprint | 최초 이력 재생 및 API 재생성 뒤 registry/profile/journal9개 table의 synthetic 행을 변경하지 않음 |
| 전달 | Python3.10 문법·기존 Go/API/SQL/Compose byte 보존·전체 source/baseline/payload hash·적용/재적용·conflict·보호 파일/권한·archive 검사 |

로컬 실제 HTTP 검사는 현행 source/schema8이며 정확한 운영 schema7 image·Docker 분리 UID/RO·TLS cutover 인수가 아니다. 새 Go 코드·SQL·이미지·운영 Compose 변경은 없다. 이번 수정에서 새 Go race/vet·전체 smoke 결과를 추가로 주장하지 않으며 원래 D1d의 서버 race/vet 결과는 보존한다. 로컬 DB/process는 검사 후 제거했다.

## 다음 완료 기준

수정 패치를 적용하고 Python32개 및 같은 D1d native runner를 재실행한다. status=passed, 전환10개 phase/native transport5개 phase·기존 이력·실제 TLS/source/UID/RO·재생성·정리가 모두 통과하기 전에는 운영 TLS 전환을 진행하지 않는다. 실패하면 새 JSON의 code/exception_type/failed_http_step/failed_stage로 다음 원인을 확인한다. 원래 source revision과 이번 수정 revision은 별도로 보존한다.

백업 추가 작업 제외·Streamlit 브라우저 보류·Jupyter 중계 미구현을 유지한다. 적용 명령은 채팅에만 제공한다.

[원래 D1d 기록](20261012-step11d1d-registry-tls-cutover.md) · [리허설 안내](../operations/camera-registry-tls-cutover-check.md)

## 서버 재실행 후 네트워크 수정

사용자 출력에서 이번 패치의 checksum OK·already_applied/written0/pending0, Python32개 OK를 확인했다. checked_revision d3eb43c56da0d555e1b19e04101407497a68af4499af7f76f45ac2649f0127d9의 native 리허설은 plaintext_registry_seed에서 CAMERA_REGISTRY_READINESS_FAILED/ActivationError로 실패했다. race/vet·격리 정리는 true, 운영 관련 false 필드는 유지됐다. 실제 HTTP ready 응답·port mapping은 미제공이다. 내부망에만 붙은 API의 HTTP 게시 구성 결함을 확인해 normal HTTP망과 actual binding 검사4개·readiness 진단을 추가했다. 최신 [HTTP network 수정 기록](20261012-step11d1d-http-network-fix.md)은 Python45개·foundation smoke62개를 통과했으며 서버 native는 대기 중이다. 이번 문서의32개·current source/schema8 HTTP 결과를 서버 TLS 성공으로 표시하지 않는다.
