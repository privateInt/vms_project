# 실제 승인 저장소와 자격증명 HTTP의 격리 검사

도구는 test_camera_credential_management.py, scope는 camera_credential_admitted_management_http_native_postgresql이다. 임의의 vms-credential-management-test 프로젝트에 PostgreSQL17.11·Go build·synthetic TLS/키·control volume을 만든다. 운영 Compose·데이터·키·admission·서비스를 읽거나 변경하지 않는다. host port는 게시하지 않으며 컨테이너 안의 실제 임시 mTLS HTTP socket으로 검사한다.

## 성공 기준

| 단계 | 확인할 결과 |
|---|---|
| schema9-role-key-authority | 명시적 schema9·두 제한된 역할·새 budget·DB marker·OPEN authority |
| actual-runtime-bindings | UID10001·capability 없음·owner DSN 없음·RO key receipt·고정 authority·두 verify-full 역할 |
| http-write-metadata-revoke-replay | 실제 생성/교체·정확한 버전 조회·논리 폐기·원래 HMAC receipt 재생 |
| policy-and-usage-denials | 현재 정책 상실·다른 장치 거부·InUse/Unknown fixture guard 거부 |
| whole-http-lease-and-drain | 폐기 HTTP의 guard 대기 동안 maintenance 차단, 응답 이후 정상 drain |
| recreated-http-replay | 새 runtime process의 교체·조회·폐기 재생, 새 budget/행 없음 |
| actual-grant-and-marker-loss | 실제 writer/budget grant 회수와 marker mismatch 때 모든 경로 거부, 복구 후 재생 |
| fenced-and-recreated-denial | 외부 FENCED 이후 기존/새 runtime의 mutation·조회·재생 거부 |

기존 C1/C2 필수40개와 새 정책6개를 유지한다. native 부모1개의 실제 PASS와 정확한 순서의8개 phase가 추가로 필요하다. 일반 회귀의 native skip은 성공으로 세지 않는다. 잘못된 package/test의 phase, 누락·중복·순서 변경, 실패 뒤 pass, 미완료 transcript는 거부한다. 전체 race/vet와 source manifest 재확인·격리 정리를 요구한다.

component 결과의 synthetic writer/manager/metadata admission 표시는 과거 C1/C2 회귀를 설명한다. 이번 native 성공 여부는 별도의 native_admitted_store_http_writes_verified와 native_admitted_store_version_http_verified에 반영한다. usage_guard_success_is_fixture_only=true, production_managed_reference_usage_guard_implemented=false, enterprise_iam_integration_verified=false를 함께 유지한다.

## 실패와 운영 경계

실패 단계·마지막 완료 단계·exit code를 안전한 report에 남기고 완료 여부와 관계없이 해당 임시 프로젝트를 정리한다. 실패나 정리 불완료에는 native 성공 필드를 제공하지 않는다. private log/report는 var/camera/credential-management-checks에 둔다. child stderr/DSN/키/secret은 stdout protocol에 포함하지 않는다.

성공해도 production_services_modified·production_database_modified·production_keys_loaded·production_admission_state_created·credential_api_activated·business_runtime_ready는 false다. 운영 TLS/키/역할/schema9·경로 등록·IAM·실장비·영상 인수가 아니다. 검사에는 백업 생성/복원 리허설·추가 백업 검토를 넣지 않는다. Camera Streamlit 브라우저 인수도 별도 보류 상태다. 적용/검사 명령은 채팅에서 제공한다.

[진행 기록](../progress/20261008-step11c3-admitted-credential-http.md)
