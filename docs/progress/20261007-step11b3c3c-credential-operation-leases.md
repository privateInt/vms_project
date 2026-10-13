# 단위 11-B3c3c — credential 전 작업 구간 admission lease

작성일: 2026-10-07 · 서버 native 통합 인수 완료 (11:28 Asia/Seoul)

## 선행 인수

11-B3c3b의 source23개 적용·Python12개·native passed를 사용자 로그로 인수했다. checked_revision 7ee49570fe511cc30d13742b38c84e1c47fa03832df79bc1ec1256d12f11c43e의 Go race/vet top146/sub412, credential native13개, binding5개·receipt2개·native2 phase가 통과했다. actual RO key mount/separate UID/two-role TLS/wrong CA/hostname/downgrade/key/profile/marker mismatch, inspection budget0 및 격리 자원 제거를 확인했다. 운영 서비스/DB/key/authority/API/restore fence/business runtime은 변경·활성화하지 않았다.

## 구현과 완료 기준

NewAdmittedCredentialStore가 검토된 Policy/lock identity/완전한 OPEN record/endpoint를 pin한다. WriteVersion·RevokeVersion·CheckReference·CheckReady는 최초 업무 DB 접근 전 RO authority lease를 얻고 actual loaded key/profile/두 DB role/marker/history/ready와 필수 업무 grants를 검사한다. 각 실제 data/budget connection과 transaction에서도 TLS/identity/marker/history/개별 grants를 확인한다. 처음 확인 → 별도 committed use → 암호화/저장 → 최종 검사/메서드 반환까지 lease를 유지하고 rollback/commit 뒤 해제한다.

기존 NewCredentialStore는 inspection foundation이며 업무 호출은 guard 부재 시 원인 없는 고정 코드로 차단한다. 기존 schema8 회귀에는 _test.go 내부 fixture만 사용한다. production의 bypass callback/flag를 추가하지 않았다. 기존 SQL1~9/키 loader/등록 API/운영 Compose를 바꾸지 않았다. 단위의 API는 Go storage이며 HTTP 응답 전송까지 보호하는 코드나 운영 restore 제어는 아직 없다.

## 로컬 검증

| 검사 | 결과와 실제 범위 |
|---|---|
| 새 Go race | 승인 없는 valid 업무 입력/no DB IO, caller-owned binding/history/policy 복사, error/panic/cancel rollback/lease 정리, 실제 별도 role의 개별 grant 상실·복구 검사 통과 |
| 실제 local PostgreSQL race | storage top71/sub61 통과. 기존 credential native13개·DB native5개·dump/restore, 새 grant 검사와 기존 저장소 회귀 포함. schema8 fixture guard는 native external authority proof가 아님 |
| Go vet | 전체 module 통과; 새 native parent/child 코드도 compile |
| Python | 새 runner14개 및 관련 credential unit 전체79개 통과. operation phase 순서/중복/누락/wrong parent/skip/fail 거부, 단계 실패·timeout·source drift·보호 sentinel·cleanup 실패 검사 |
| 전달 | baseline348개/hash, payload/manifest hash, 최초 적용·재실행·백업 원문·보호 파일·충돌 사전 거부·archive exclusion 검사 |

local PG17.11은 UID0-only namespace 대응 시작 조건 두 곳만 수정한 직전 fixture를 재사용했다. SQL/auth 코드를 바꾸지 않았으며 DB/binary/password/CA/private fixture를 전달하지 않는다. 모든 local PostgreSQL 프로세스를 종료했다. Docker와 외부 UID/실제 RO mount가 없는 로컬에서는 native operation parent/child positive 검사를 실행하지 않았다.

서버 runner는 unmodified image에서 기존 binding 검사 후 실제 authority RO/RW volume과 distinct UID를 결합한다. failure unwind, 여섯 정상 업무 흐름의 maintenance wait/drain, committed budget 직후 process death/drain/FENCED, stale process recreation 거부의 native9 phase와 required5개를 모두 요구한다. 부모의 marker만 수집하는 synthetic runner unit은 이 통합 검증을 대신하지 않는다.

## 남은 작업과 다음 단위

서버 적용·runner14개·native report를 인수한다. 이어 11-B3c3d에서 cooperative lease 외에 DB owner/비협력 writer 계정과 네트워크 제어를 포함한 유지보수 복원 리허설을 연결한다. FENCED→DB/key 복원→독립 fresh key/budget/DB incarnation·표식→PREPARED/검증→OPEN의 interruption/retry 기준을 검증한다. 운영 preflight/rehearsal/activation과 credential HTTP는 각각 후속 단위다.

credential runtime guard의 source 구현은 true, native operation 인수는 pending, production_restore_fence_implemented·credential_runtime_key_supply_verified·credential_api_activated·business_runtime_ready는 false다. UI browser acceptance는 deferred이고 중계는 추가하지 않는다. API 프로세스/라우팅을 바꾸지 않아 기존 smoke62개 인수를 유지한다. 명령은 채팅에서만 제공한다.

## 서버 실패와 검사 수정 — 2026-10-07 11:12 Asia/Seoul

사용자 로그의 already_applied/written0/pending0 및 Python14개 OK를 확인했다. revision 6ba079440fa5e9e4176820daf55ccf99fe4ff575772eea0969f996afe970e1b7, project vms-credential-operations-test-8098513c7fb9의 native report는 ISOLATED_OPERATION_COMMAND_FAILED다. 실패 단계는 runtime_operation_leases, 직전 runtime_tls_bindings까지 command0, 실패 command exit1, isolated_resources_removed=true다. native operation 전체 인수는 보류한다. production 서비스/DB/key/authority/API/restore fence/business runtime은 false다.

실제 로그 본문은 제공되지 않아 이번 실패가 특정 내부 assertion 때문이라고 확정하지 않는다. 소스 검사에서 operations-owner의 cap_drop ALL 및 CHOWN/FOWNER/SETUID/SETGID 조합에 CAP_KILL이 빠진 결함을 확인했다. UID0의 부모가 UID10001의 자식에 SIGKILL을 보내는 경로/정리 경로가 이 권한을 요구한다. Linux UAPI include/uapi/linux/capability.h의 CAP_KILL 정의도 이를 명시한다. 격리 owner에만 KILL을 추가했으며 runtime의 effective capability0 검사는 유지한다. host PID/production container mount를 사용하지 않는다.

부모에 effective CAP_KILL preflight를 추가했다. 자식의 실패는 고정된 component 영수증으로 전달하며 raw stderr/일반 test output/DSN/key를 부모 출력에 복사하지 않는다. runner는 해당 부모 test/package의 허용된 고정 태그만 failed_native_component에 넣고, failure 영수증 뒤 pass로 실패를 감추는 transcript를 거부한다. 현재 native9 phase/operation required5개의 성공 기준은 유지한다.

수정 검증은 Go race의 capability 누락/잘못된 hex/비유효 effective field 거부와 diagnostic privacy2개 및 전체 Go vet 통과, Python18개/관련 unit 전체83개 통과다. 이전 역할/동시성 PG 회귀 이후 production storage/SQL/키 loader/HTTP 코드를 바꾸지 않아 native PG 회귀를 반복하지 않았다. 수정 source도 서버 Docker 통합 인수 전이다. source357개 baseline에 대한 최초 적용/재실행/원본 백업/충돌/보호 파일/패키지 검사를 수행했다.

원래 서버 log는 var/camera/credential-operation-checks/vms-credential-operations-test-8098513c7fb9-p4ehkl2w.log, report는 같은 폴더의 vms-credential-operations-test-8098513c7fb9.json이다. signal-and-diagnostics-fix 적용 후 fresh isolated project에서 전체 runner를 재실행한다. native passed 인수 전에는 다음 유지보수 복원 단위로 진행하지 않는다. 명령은 채팅에서 제공한다.

## 수정 후 서버 인수 — 2026-10-07 11:28 Asia/Seoul

사용자 로그의 signal diagnostics 수정8개 적용, Python18개 OK를 확인했다. project vms-credential-operations-test-2193a06e16dd와 revision 0765dfb6560779e289c129f96d1a656b6da3cc79c7e31ed64ffc74678aff28f0의 native status=passed, Go race/vet, top153/sub412, 기존 credential13개·binding5개·receipt2개·binding2 phase·operation5개·operation9 phase를 인수했다. 전 작업 lease, replay/reference/revoke, 정상 대기/drain, error/panic/cancel unwind, process death drain, data 미커밋 시 committed budget 보존, fenced process recreation 거부, 승인 없는 업무 호출 거부가 모두 true다. 격리 자원 제거도 true다.

실패 뒤 수정한 source의 통합 검증이 통과했으나 이전 실패 로그의 내부 assertion을 역으로 확정하지 않는다. 운영 서비스/DB/key/authority/API/restore fence/business runtime은 계속 false다. report는 var/camera/credential-operation-checks/vms-credential-operations-test-2193a06e16dd.json, log는 같은 폴더의 vms-credential-operations-test-2193a06e16dd-b_w7gn1v.log다.

다음 11-B3c3d는 독립 인수 가능한 하위 단위로 진행한다. d1은 FENCED 아래 DB 신규 접속 차단·비협력 세션 종료·재시도 기반, d2는 필요한 계정/네트워크 경계와 실제 DB/key 복원·독립 fresh key/budget/incarnation·PREPARED/OPEN의 통합이다. 각 단위의 서버 결과를 확인한 뒤 이어간다.
