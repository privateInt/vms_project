# 11-D1d 수정 — 검사 HTTP 네트워크와 실제 포트 게시

상태: 수정 후 서버 native 전체 리허설 인수 완료 · 운영 TLS 미전환

## 수정 전 서버 실패 이력

사용자 제공 2026-10-12 simsys4090/sh_test 출력에서 HTTP ID 수정 패치 SHA256897efa0c21675451154829f5940ce846ec23eef9cb66c450a44b6bbe802f1923 checksum OK, already_applied/written0/pending0을 확인했다. 재적용 출력만 제공됐으므로 최초 적용 시각·patch backup 경로를 새로 추정하지 않는다. Python32개는3.323초에 OK였다.

native scope camera_registry_schema7_tls_cutover_native_docker의 project는 vms-registry-tls-test-8e80074afba3, checked_revision은 d3eb43c56da0d555e1b19e04101407497a68af4499af7f76f45ac2649f0127d9다. status=failed, code=CAMERA_REGISTRY_READINESS_FAILED, exception_type=ActivationError, failed_stage=plaintext_registry_seed, last_completed_phase=null, last_command_exit_code=0이었다. Go unit race/vet은 true이고 native_probe_race_enabled는 false다. 테스트 API/DB image ID는 앞선 D1d 결과와 같다. running_image_reused_for_test는 false로 전체 전환 성공을 주장하지 않는다.

운영 서비스·DB/schema·HBA·환경·network·credential 키/admission·미활성 후보/D1c 공급 파일/볼륨·활성화·백업/restore 관련 false 필드를 보존한다. isolated_resources_removed/synthetic_input_removed/isolated_diagnostics_collected는 true다. 실패는 TLS 전환 전이며 이번 JSON은 실제 HTTP ready 응답이나 Docker의 포트 mapping을 포함하지 않았다.

## 확인한 구성 문제와 수정

원래 D1d recipe는 API를 internal storage network에만 연결하고 호스트 포트를 선언했다. 운영 Compose는 camera-api를 default와 camera-storage 두 network에 연결한다. Moby의 [internal bridge 포트 게시 보고](https://github.com/moby/moby/discussions/53256)에는 container가 healthy여도 HostConfig.PortBindings만 남고 NetworkSettings.Ports가 null일 수 있음이 재현돼 있다. 이 구성 결함과 이번 readiness timeout이 일치한다고 판단했다. 해당 서버의 raw mapping/HTTP 응답을 직접 관찰한 확정 진단으로 표시하지 않는다.

새 random test project에 normal bridge HTTP network를 추가하고 API만 연결한다. HTTP는 기존127.0.0.1 임의 포트로 게시한다. storage는 internal을 유지하고 API.3/DB.2/maintenance.4/offsource.5와 HBA source 규칙을 바꾸지 않는다. DB/migrator/maintenance/offsource는 HTTP network에 연결하지 않으며 DB 포트를 게시하지 않는다. 운영 Compose/network·DB·이미지는 변경하지 않는다. HTTP network도 Compose project의 정리 대상이며 external test storage는 기존 제한된 cleanup으로 제거한다.

API 시작과 TLS 전환 후, API 재생성 후, DB/API 재생성 후의4개 지점에서 실제 컨테이너 selected metadata를 확인한다. 정확한 project/service/working directory/image·running 상태·network ID/source IP·internal DB망/normal HTTP망·HTTP API 단독 연결을 검사한다. 선언 PortBindings와 실제 NetworkSettings.Ports 모두 exact127.0.0.1:선택포트→8080이어야 하며 선언만 있으면 ISOLATED_HTTP_PORT_NOT_PUBLISHED로 readiness 전에 실패한다. DB 포트 게시·HTTP망 연결·wildcard/다른 포트·추가 interface 게시를 거부한다. metadata 조회 template는 Config.Env를 읽거나 로그에 복사하지 않는다.

준비 상태 조건은 기존 camera_registry·ready=true·business_runtime_ready=false와 버전/capability 검사를 유지한다. readiness 실패 시 마지막 /health/ready를 추가로 읽어 status·알려진 platform/scope·boolean ready·business_runtime_ready 존재/boolean 또는 exception class만 http_readiness_probe에 남긴다. 미지의 문자열·token·DSN·headers·전체 body/exception text는 공개하지 않는다. 사용자 환경에서 DB readiness가 별도로 실패해도 조건을 완화하지 않는다.

## 로컬 검증과 제한

| 검사 | 결과·범위 |
|---|---|
| Python45개 | 통과. 이전32개와 새13개: API 전용 HTTP망/DB망 유지, 실제 mapping 누락·wildcard/다른 포트·DB 게시·source/network/image/label 변경·외부 peer 거부,4개 binding 검사 순서·실패/정리·안전한 readiness 진단 |
| make smoke | 4개 실제 Go foundation process의 HTTP·인증·입력·readiness·종료62개 통과, scope=http_api_and_contracts, business_runtime_verified=false |
| Python3.10/쉘 | 문법과 기존 BUILD/OWN_FILES의2개 shell script 구문 통과 |
| source·전달 | 기존 Go/API/SQL/운영 Compose byte 보존, 전체 baseline/source/payload hash·적용/재적용·conflict·보호 파일/권한·archive 검사 |

Docker daemon이 없는 로컬 검사는 selected metadata fixture와 mock orchestration이다. 실제 Docker HTTP 포트 게시·정확한 운영 schema7 이미지·TLS/source/UID/RO·전환 완료는 아래 서버 재인수 결과로 확인했다. 앞선 current source/schema8 실제 HTTP CRUD·재생 검사는 이력으로 보존하며 이번 네트워크 native 인수로 합산하지 않는다. 이 수정의 Go source 변경은 없으며 로컬 검사와 사용자가 제공한 서버 race/vet 결과를 구분한다.

## 수정 당시 재실행 완료 기준 — 아래 서버 결과로 충족

수정본 Python45개와 같은 D1d native runner를 다시 실행한다. passed는 기존 전환10개 phase/native transport5개 phase와 추가 actual HTTP binding4개·이력/조회/목록·실제 TLS·API/DB 재생성·정리가 모두 성공한 결과다. 실패하면 binding stage/code 또는 http_readiness_probe로 host publication과 API/DB readiness를 구분한다. 통과 전 운영 TLS 전환은 진행하지 않는다.

사용자 요청에 따른 백업 추가 작업 제외·Streamlit 브라우저 보류·Jupyter 중계 미구현을 유지한다. 적용 명령은 채팅에만 제공한다.

근거: [Docker 복수 network와 frontend/backend 분리](https://docs.docker.com/engine/network/), [원래 D1d 기록](20261012-step11d1d-registry-tls-cutover.md), [HTTP ID 수정](20261012-step11d1d-http-fixture-id-fix.md), [검사 안내](../operations/camera-registry-tls-cutover-check.md).

## 수정본 서버 재인수 완료 — 2026-10-12

사용자 제공 checksum OK·applied/written10/pending0, patch 이력 var/patch-backups/step11d1d-http-network-fix-aguthxrp, Python45개/2.555초 OK를 확인했다. 동일 수정 source revision1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159의 native project vms-registry-tls-test-cfeb7a2c0284가 passed다. 실제 HTTP 게시/망 검사4개·schema7/row/모든 journal·TLS/source/UID/RO·재생성·전환10개/transport5개 phase·policy race/vet·정리가 모두 통과했다. native probe race=false이며 운영 서비스/DB/network·기존 후보/D1c 공급·키/admission·TLS 활성화·백업/restore 필드는 false다. 성공 시 실패 diagnostics 수집은 false다. 로컬 fixture/smoke와 이번 실제 서버 인수를 구분하며 raw Docker mapping이나 앞선 timeout의 원인을 소급해 직접 관찰했다고 표시하지 않는다. 자세한 [서버 인수 기록](20261012-step11d1d-server-acceptance.md)을 최신 기준으로 사용한다.
