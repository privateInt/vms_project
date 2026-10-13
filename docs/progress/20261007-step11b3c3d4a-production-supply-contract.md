# 단위 11-B3c3d4a — 운영 공급 계획 계약

작성일: 2026-10-07 · d3 서버 조회 인수 완료 · 공급 계약 서버 인수 완료

## d3 서버 조회 인수

사용자가 simsys4090의 sh_test에서 d3 patch를 적용했다. written7/pending0, backup=var/patch-backups/step11b3c3d3-xlp_2fgz, restart/runtime activation/schema modification=false다. Python31개 OK이며 inventory는 status=inspected/inspection_completed=true/readiness=blocked/activation_allowed=false다. checked_revision은 effc214a66a3658058490310507d251ea0165fbd325392b9d7bfff0aa1fd1ab4이며 report는 /home/shshin/workspace/vms_project/var/camera/credential-supply-preflight.json이다. 이번 패치는 이 source SHA/403 tracked files를 baseline으로 사용한다.

| 항목 | 실제 조회 결과 | 범위 |
|---|---|---|
| 운영 API/DB | 0.7.0-device-delete / schema7 / registry-only-v1 | schema9 전환 미실행 |
| image | camera sha256:708d5a53f3dcc3d22dca775ef2825bcd271a68c7c3777cf8a6a89bb6933aa7d6; DB sha256:248efd5e58cd743f2a0e0daec8ea4649e5580145ec2a12e2345bc710d4a77201 | 인수 이미지 유지 |
| 키 파일 | metadata_valid·0700/0600 | 본문/무결성/활성 공급은 미검증 |
| DB | READ ONLY 확인·TLS=false·고정 credential 역할3개 없음 | HBA lexical outside=false, 실제 topology/authentication 미검증 |
| 런타임 | configured UID65532·RO rootfs=true·키 bind mount 없음·credential env entries0 | 실제 EUID·key supply·authority/endpoint/source binding 미검증 |

blocker11개는 APPROVED_AUTHORITY_BINDING_NOT_REVIEWED, APPROVED_ENDPOINT_AND_SOURCE_BINDING_NOT_REVIEWED, CREDENTIAL_API_NOT_IMPLEMENTED, CREDENTIAL_DATABASE_ROLES_MISSING, CREDENTIAL_KEY_MOUNT_MISSING, DATABASE_TLS_DISABLED, HBA_PATH_NOT_LEXICALLY_OUTSIDE_DATA, MAINTENANCE_HBA_BOUNDARY_NOT_VERIFIED, PRODUCTION_RESTORE_FENCE_NOT_IMPLEMENTED, RUNTIME_KEY_SUPPLY_NOT_VERIFIED, SCHEMA_9_CUTOVER_NOT_PERFORMED다. raw private report를 새로 읽었다는 주장은 하지 않고 사용자 JSON을 인수 근거로 기록한다.

모든 production modification, key material read/load, admission state creation, HBA change, credential API activation, business runtime readiness는 false다. 실제 Docker exec/env-clean local socket 조회 성공은 이번 서버 결과로 인수하며 로컬에 Docker가 있었다고 표시하지 않는다. inventory 완료는 공급 준비 완료가 아니다.

## 이번 변경과 검증

camera/api/planned에 [SupplyPlan](../contracts/camera-credential-supply.md) schema·합성 example·strict raw parser/semantic validator·test를 추가했다. 기존 Go protected loader 조건에 맞춰 source key 보존/별도 runtime owner 사본, UID/source 구분, RO mount, authority/lock/HBA/PKI snapshot 경계를 선언한다. parser는 참조된 파일/키/authority를 열지 않고 DB나 서비스에 연결하지 않는다. 성공에도 review-only이고 실제 approved profile/receipt는 생성하지 않는다.

정적 계약34개를 통과했다. duplicate/escaped alias·float/exponent/NaN·UTF8/size·unknown secret/bypass·UID/GID·고정 역할/verify-full·canonical IP/path·source family·host alias/mount shadow·project/data/key/snapshot overlap·no referenced-file IO·기존 API 미변경을 확인했다. 기존 admission contract23개도 회귀 검증한다. 로컬 Python3.12/jsonschema4.26을 사용했고 서버 Python3.10/jsonschema4.25 환경의 인수는 사용자 실행으로 확인한다. 기존 요구 jsonschema>=4.18,<5를 사용하며 UI/공용 환경 의존성을 변경하지 않는다.

accepted baseline403개 전체와 payload hash, patch dry-run·백업 적용·재실행·사용자 편집/새 경로 충돌·보호 env/key/authority sentinel 보존, helper8개를 검증한다. Go/API/SQL/Compose 원본은 미변경으로 기존 native race/vet/복원/재개 인수를 유지한다.

## 남은 작업

사용자 서버에서 patch written12/pending0, backup=var/patch-backups/step11b3c3d4a-n0lgq9a1, 계약57개(공급34+admission23)와 기존 점검31개 OK를 인수했다. restart/runtime activation/schema modification=false다. 인수된 소스 SHA는 8ab00aec97ebbc80d90f4536a9c2ad94304ac5d535c312ed0bffb6819e34b85f이며 tracked410개다. 이것은 정적 계약의 인수이며 공급·활성화가 아니다.

다음 [d4b](20261007-step11b3c3d4b-production-supply-facts.md)에서 현재 키 소유자·process identity·volume/network metadata를 읽기 전용으로 조사한다. 관찰만으로 container UID mapping, 고정 source IP·TLS/CA·authority·physical backup topology를 승인하지 않는다. 실제 runtime key/DSN/CA 사본과 authority bootstrap/lock receipt는 아직 생성하지 않았다. schema9 cutover, 전체 production restore fence, credential HTTP API, 실장비/영상은 미완료다. Streamlit browser acceptance는 deferred이며 중계는 추가하지 않는다. 패치/테스트 명령은 채팅에서만 제공한다.
