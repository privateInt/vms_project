# 11-D1e — 운영 schema7 등록 DB의 TLS 전환 준비

상태: 준비 도구 구현·로컬 검사 완료, 서버 준비 결과 대기 · 운영 TLS 미전환

## 완료 범위

11-D1d 기록 패치의 checksum OK·applied/written9/pending0을 사용자 출력으로 확인했다. 이력은 var/patch-backups/step11d1d-notes-f0q38zhd이며 재시작·runtime 활성화·schema 변경은 false다. 이 단위의 baseline은 manifest SHA38f8d690bf596ac52875773f65a4b10fb360b42827e233116ea8b0f02e793bcc, tracked511개다. 실제 D1d 인수 revision1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159를 그대로 유지한다.

prepare_camera_registry_tls_cutover.py를 추가했다. 현재 source 전체 hash와 D1d/D1c 인수, API0.7.0-device-delete/schema7/TLS off·실제 process identity·같은 운영 API/DB 이미지·loopback HTTP 게시·기존 data volume·storage/default network를 확인한다. API·DB·기타 플랫폼을 시작/중지하거나 .env/운영 Compose를 수정하는 호출은 없다.

기존 D1c receipt와 selected TLS 파일·인증서 유효기간/서버명·key pair·exact bytes·볼륨 소유권/UID/RO를 다시 검사한다. CA signing key와 camera credential 암호화 키는 읽지 않는다. candidate.json·D1c selected TLS private key와 기존 registry 접속 파일은 검증을 위해 읽으며, 출력은 내용이나 DSN을 포함하지 않는다. production_candidate_files_read/production_prepared_supply_files_read=true와 production_key_material_read/credential_key_material_read=false의 범위를 구분한다.

## 생성 자료

| 자료 | 내용·보존 조건 |
|---|---|
| private 준비 디렉터리 | var/camera/registry-tls-preparations/prepared-v1, caller 소유0700 |
| runtime-dsn | 기존 camera_runtime password를 유지하고 verify-full/고정 서버명/전용 CA 경로를 사용;0444 파일을 private0700 부모 아래 보관 |
| migrator-dsn | 기존 camera_migrator와 maintenance 인증서의 CN map; 비밀번호를 넣지 않는 cert 인증,0444 |
| database/hba.conf·pg_ident.conf | runtime .3의 SCRAM·migrator .4의 cert map, 다른 TCP 출처/DB/역할 거부; host 파일0600 |
| 새 외부 control volume | 준비 hash로 명명,999:999 디렉터리0700/파일0400; offline RO 검사와 runtime65532/maintenance10002 접근 거부 |
| compose.camera.json | 같은 immutable API/DB 이미지·기존 외부 camera-data와 D1c 공급·고정 storage 주소·API 전용 default HTTP망·loopback 포트 |
| compose.root.json·receipt.json | 현재 다른 세 플랫폼 include와 token 참조를 유지하는 구성 자료·source/env/image/network/파일 hash를 묶은 준비 receipt,0600 |

Compose CLI의 config만 실행하며 raw resolved token/DSN·Docker stderr를 반환하지 않는다. default network는 기존 Compose 소유 정의를 유지해 다른 플랫폼 include의 암묵적 default와 충돌하지 않게 한다. camera-storage와 data/TLS/control volumes는 기존 이름의 external 참조다. camera-api65532·camera-db999·camera-migrate10002를 명시하며 서버 TLS/HBA/ident는 PGDATA 밖 RO 공급 경로를 사용한다.

반복 실행은 같은 파일 bytes/mode/mtime와 control volume을 보존한다. 변조·추가 파일·symlink/hardlink·잘못된 권한·current source/env/network/image 변경·불완전한 volume은 거부하며 덮어쓰기나 자동 수리하지 않는다. 새 준비 실패 시 새 파일/volume은 진단을 위해 남을 수 있고 기존 D1c 공급·운영 data는 수정/삭제하지 않는다. 적용 없이 확인할 때에는 준비 파일/volume을 만들지 않으며 기존 공급을 읽는 offline helper와 coordination lock은 사용할 수 있다.

## 검증 범위

로컬 신규 Python27개, 기존 후보/공급 도구 회귀와 D1d runner 회귀를 검사했다. 실제 새 합성 PKI와 OpenSSL로 receipt·key pair·서버명/유효기간·exact bytes를 확인했으며 file/umask/충돌·DSN/HBA·current HTTP/data/source 경계·불완전/중단 control·Compose 의미 검사·다른 플랫폼 보존·safe CLI를 포함한다. Python3.10 문법과 control initializer/probe의2개 shell 구문도 확인했다. 패치의 baseline/payload hash·적용/재적용·사용자 충돌·보호 파일과 archive를 검사한다.

로컬에는 Docker daemon/Compose CLI가 없어 Docker orchestration과 normalized config는 fixture 검사다. 실제 container UID/RO/control volume·Compose include 해석은 서버에서 준비 도구를 실행한 결과로 인수한다. 새 Go/API/SQL 구현이나 현재 프로세스·라우팅 변경은 없으며 이번에 새 Go race/vet·운영 TLS 접속 성공을 주장하지 않는다. D1d의 서버 native 인수는 별도 이력이다.

서버 성공 시 첫 실행 prepared/control_volumes_created=1, 반복 already_prepared/0·같은 preparation SHA를 확인한다. 각 실행은 두 번의 D1c 재검사에 full probe6개·precheck6개·cross UID denial12개, control RO/exact-byte probe1개·cross UID denial2개를 수행한다. 이는 offline 공급 검사 수이며 운영 PostgreSQL TLS 접속 검사 수가 아니다. 모든 helper는 network none·pull never·정확한 소유권 label로 정리한다.

## 미완료와 다음 단위

cutover_preparation_ready는 준비 파일과 offline 공급의 검증만 의미한다. recipe_is_deployable/activation_allowed/database_tls_activated/production_supply_ready/business_runtime_ready는 false다. 고정 주소의 실제 예약·현재 API의 TLS mount·운영 TLS 접속/인증·schema9/admission/credential HTTP/IAM은 아직 미완료다. Compose 자료를 생성하는 것만으로 활성화 승인을 기록하지 않는다.

서버 prepared→already_prepared 인수 후 다음11-D1f에서 준비 hash와 현재 상태를 재확인하는 schema7 TLS 전환 실행 도구를 구현한다. API drain·기존 data volume/이미지 유지·TLS DB 재생성·version7/applied0 migration 확인·실제 runtime TLS·registry 이력 보존·반복 실행 결과를 그 단계에서 인수한다. 이번 단위에 실제 서비스 전환을 묶지 않는다. 백업 추가 작업 제외·Streamlit 브라우저 보류·Jupyter 중계 미구현은 유지한다. 실행 명령은 채팅에서 제공한다.

[준비 안내](../operations/camera-registry-tls-preparation.md) · [ADR0025](../architecture/decisions/0025-camera-registry-tls-production-preparation.md) · [D1d 서버 인수](20261012-step11d1d-server-acceptance.md)

## 서버 첫 실행과 image pin 수정

서버 패치10개·Python27개는 통과했으나 첫 준비 확인이 accepted_source 단계의 일반 오류로 중단됐다. 첨부 source hash와 인수 조건은 맞았고, 초기 활성화용 환경 검사기가 정상 immutable VMS_CAMERA_IMAGE를 거부하는 결함을 재현했다. 정확한 인수 image만 허용하는 검사와 단계 진단을 수정했다. 사용자 요청에 따라 전용 UI 환경·과거 백업·로그·캐시의 정리 도구를 함께 추가했다. 현재 작업 기준은 [수정/정리 기록](20261012-step11d1e-image-pin-fix-and-cleanup.md)이며 운영 TLS 전환은 계속 미완료다.
