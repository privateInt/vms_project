# 11-C3 서버 인수: 실제 승인 저장소와 자격증명 관리 HTTP

상태: 서버 패치 적용·실제 native HTTP 격리 인수 완료 · 운영 활성화 전

## 근거

2026-10-08 사용자가 제공한 simsys4090/sh_test 출력에 근거한다. 적용 결과는 applied·written14·pending0이며 적용 이력은 var/patch-backups/step11c3-3fecmno7이다. 서비스 재시작·runtime 활성화·DB schema 변경은 없었다. Python runner unit9개가 OK였다.

검사한 manifest SHA는 `0b2891f179dddca6d3e43a09e253c915b7babd32b8a437fc6d61b5d3f4dd50aa`다. native Docker 검사는 status=passed, scope=camera_credential_admitted_management_http_native_postgresql, project=vms-credential-management-test-b8b77ef3488d였다. 이번 기록 패치의 새 SHA를 이 서버 검사의 revision으로 바꾸지 않는다.

| 서버 검사 | 결과 |
|---|---|
| Go race / vet | 모두 true |
| Go 상위 / 하위 테스트 | 192 / 567 PASS |
| 기존 credential 저장소 | 필수13개 PASS, native 역할·동시성 true |
| C1 HTTP / 입력 계약 | 필수7개 / 5개 PASS |
| C2 버전 HTTP / 폐기 계약 / metadata | 필수8개 / 3개 / 4개 PASS |
| 실제 관리 정책 / native HTTP 부모 | 필수6개 / 1개 PASS |
| native 통합 단계 | 8개 PASS |
| 실제 admitted store 생성·교체 HTTP | true |
| 실제 admitted store 버전 조회·폐기 HTTP | true |
| 격리 자원 정리 | true |

필수47개는 13+7+5+8+3+4+6+1이며 전체192/567 안에 포함된다. 단계8개는 별도의 실행 transcript다. Python9개와 기존 로컬 테스트 수를 합산해 서버 Go 테스트 수로 표시하지 않는다. 이번 서버 출력에는 별도 네 플랫폼 smoke 재실행 증거가 없으므로 기존 로컬62개 인수와 구분한다.

## 실제 통합 인수 범위

schema9 DB marker·migration history·writer/budget 두 verify-full TLS 역할·실제 RO key/authority receipt·별도 runtime UID를 사용하는 concrete admitted store와 직접 mTLS HTTP를 결합했다. client 인증서의 exact leaf hash를 scope/principal/device MANAGE 정책에 연결했고, 정책 교체로 성공 재생도 거부했다. runtime에 owner DSN이 없음을 검증했다.

생성·교체·정확한 버전 metadata·폐기·HMAC receipt 재생, 실제 권한 회수와 marker mismatch의 차단, 새 process 재생과 예산 보존을 인수했다. 폐기 HTTP의 guard 대기 동안 maintenance lease가 차단되고 완료 후 정상 drain됐다. FENCED 이후 기존 process와 재생성한 runtime의 mutation·조회·재생도 거부했다. native_admitted_store_http_writes_verified와 native_admitted_store_version_http_verified는 이번 C3에서 모두 true다.

기존 C1/C2 component 회귀에는 synthetic writer/manager/metadata admission guard가 남아 있다. http_writer_success_uses_synthetic_store·version_http_success_uses_synthetic_store·metadata_store_test_admission_uses_synthetic_guard는 그 회귀 범위를 설명하며 c1_c2_component_native_admitted_http_verified=false도 보존한다. 이번 별도 C3 native 성공과 모순되지 않으며 과거 C1/C2 검사 결과를 소급 변경하지 않는다.

폐기의 InUse/Unknown/Unused usage source는 fixture 전용이다. usage_guard_success_is_fixture_only=true, production_managed_reference_usage_guard_implemented=false, enterprise_iam_integration_verified=false다. 실제 운영 참조·reservation·사용 해제 guard나 기업 IAM을 구현했다고 표시하지 않는다. 로컬 UID 변경 제한으로 실패했던 과거 전면 검사는 로컬 이력으로 보존하고, 이번 대상 서버의 PASS를 별도 기록한다.

## 운영 경계와 결과 경로

management_database_schema_version=9와 legacy_storage_schema_version=8은 격리 검사 대상이다. 운영 schema9 전환 증거가 아니다. production_services_modified·production_database_modified·production_keys_loaded·production_admission_state_created·credential_api_activated·business_runtime_ready는 모두 false다. 현재 main에는 credential HTTP가 등록되지 않았다. 최근 운영 인수 기준은 API0.7.0-device-delete/schema7/registry-only-v1이며 이번 도구는 운영 상태를 재조사하지 않았다.

서버 report는 var/camera/credential-management-checks/vms-credential-management-test-b8b77ef3488d.json, log는 같은 디렉터리의 vms-credential-management-test-b8b77ef3488d-y3va582n.log다. 사용자 제공 JSON으로 기록하며 원격 파일을 직접 읽었다고 표시하지 않는다.

## 이번 기록 패치와 다음 단위

README·문서 목록·전체 계획·통합 계약·진행 기록·manifest에 이번 인수 결과를 반영한다. src·SQL·Compose·실행 환경·키·서비스 변경은 없다. 적용 기준과 payload hash, dry run/적용/재적용, 사용자 변경 및 새 파일 충돌, 보호 파일 보존을 검증한다. 적용 명령은 채팅에서 제공한다.

다음 단위는 운영 TLS·고정 endpoint/source 공급의 준비다. 운영 전환 후보를 검토 가능한 설정/공급 계획으로 만들고 격리 환경에서 실제 TLS·역할·source 결합을 검증하는 것을 완료 기준으로 둔다. 키/역할 DSN·authority 공급, schema9 cutover·HTTP 실행 경로 활성화는 후속의 작은 단위로 분리한다. 기업 IAM과 실제 관리 사용 관계도 남아 있다. ConnectionConfig·SourceSession·실장비·영상 및 다른 플랫폼 업무는 이후 진행한다. 사용자 지시에 따라 백업 추가 검토는 개발 선행 조건에서 제외하며 Streamlit 브라우저 인수는 보류하고 Jupyter 중계는 만들지 않는다.

[구현 기록](20261008-step11c3-admitted-credential-http.md) · [통합 계약](../contracts/camera-credential-management-http.md) · [검사 안내](../operations/camera-credential-management-check.md)
