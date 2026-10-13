# 11-D1a 서버 인수 — DB TLS 인증서 후보 준비

상태: 대상 서버 패치·23개 검사·후보 생성/재실행 인수 완료 · 운영 TLS 미전환

## 인수 근거

2026-10-08 사용자 제공 simsys4090/sh_test 출력에 근거한다. 전달 압축본 SHA256 d3db2c3bfd70383db2cd8417268305f1be65b9ff9ae43c26e5b4b691c52a5f76의 검사가 OK였다. 적용은 applied·written9·pending0, 이력은 var/patch-backups/step11d1a-ce8rn_k0이다. 서비스 재시작·runtime 활성화·DB schema 변경은 false다. Python unit23개가 2.248초에 OK였다.

두 준비 실행의 checked_revision은 bee8f71859c99c31e81997009c950f7360e441b82eff3acf09420998430adf04다. 이 기록 패치가 만드는 새 manifest SHA를 당시 검사 revision으로 바꾸지 않는다. 기존 로컬 회귀42개·전달 도구8개를 이번 서버23개에 합산하지 않는다.

| 항목 | 서버 결과 |
|---|---|
| 최초 생성 / 재실행 | prepared / already_prepared |
| 후보 hash | 두 실행 모두 421c3e0a67ec6e47f3fdab270f7c7448351a42d9e21eb7accc9ab702e7cadc40 |
| 후보 위치 | var/camera/database-tls-candidates/candidate-v1 |
| 디렉터리 / 파일 권한 | 0700 / 0600 |
| 후보 준비 | candidate_ready=true |
| 재실행 후보 보존 | existing_candidate_preserved=true |
| 실제 socketpair mTLS | true, TLSv1.3 |
| 잘못된 hostname / 신뢰되지 않은 CA / client 인증서 누락 | 모두 거부 확인 true |
| endpoint 상태 | proposal-unreserved |

서버명은 camera-db.vms.internal, 유지보수 CN은 camera_maintenance다. server leaf DER SHA256은 a68bbe592f1d176c7ee7c99f053743f8333203c1caec7ed1516d83ddf6f63bff, maintenance leaf DER SHA256은 07b5838426c75a17419a15b1f3cdefb5491e9c4dd5712a6e24c47da7db04b114, CA PEM SHA256은 725467c811d5268ad9561f9120a6b636ee29d04d23aef39839151a63ae5a69e8이며 두 실행에서 같았다. 모두 공개 인증서/후보 receipt의 digest다. private key 원문·hash는 사용자 출력에 없으며 원격 후보 파일을 직접 읽은 결과로 표시하지 않는다.

## 확인 범위와 미완료

candidate_private_keys_loaded_for_local_probe=true는 새 후보 키를 로컬 SSL 검사에 사용한 결과다. 기존 운영 credential 키는 읽거나 로드하지 않았다. TLS handshake는 실제 socketpair였으며 PostgreSQL endpoint·Docker source·HBA·role 검사는 이 단위의 범위 밖이다. 사용자 출력에 별도 validated 실행 결과는 없으므로 최초 생성과 재실행만 서버 인수로 기록한다.

production_services_modified·service_restart_performed·production_database_modified·database_schema_modified·production_key_material_read·production_keys_loaded·production_admission_state_created·production_hba_modified·environment_modified·network_modified·credential_api_activated·business_runtime_ready·production_supply_ready·activation_allowed·runtime_mount_verified·database_tls_activated·endpoint_and_sources_reserved·approved_binding_created는 모두 false다.

후보 IP의 예약이나 실제 운영 공급 승인은 수행하지 않았다. 이 결과를 운영 PostgreSQL TLS 활성화·schema9 cutover·credential API 활성화로 표시하지 않는다. 최근 운영 인수 기준은 API0.7.0-device-delete/schema7/registry-only-v1/TLS off이며 이번 도구는 운영 상태를 재조회하지 않았다.

## 기록 패치와 다음 단위

README·문서 목록·전체 계획·운영 안내·구현 기록·이번 서버 인수 기록·manifest에 결과를 반영한다. src·SQL·Compose·서비스·환경·생성 후보 파일은 변경하지 않는다. 기준 manifest 전체 hash·payload·dry run/적용/재적용·보호 파일과 권한 보존·사용자 변경/신규 파일 충돌을 검증한다. 적용 명령은 채팅에서 제공한다.

다음은 11-D1b: 동일 PKI profile과 고정 endpoint/source 제안을 disposable PostgreSQL/Docker에 연결해 실제 TLS·역할·source별 HBA 거부·제한된 owner/RO mount를 검증한다. 운영 전환은 그 이후 별도 단위다. 키/DSN·authority·schema9·HTTP 실행 경로·운영 IAM·실제 관리 사용 guard와 ConnectionConfig·SourceSession·장치/영상 작업도 남아 있다. 백업 추가 검토는 사용자 지시에 따라 제외하며 Streamlit 브라우저 인수는 보류하고 Jupyter 중계는 만들지 않는다.

[구현 기록](20261008-step11d1a-database-tls-candidate.md) · [운영 안내](../operations/camera-database-tls-candidate.md)
