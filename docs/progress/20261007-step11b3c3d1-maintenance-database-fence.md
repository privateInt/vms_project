# 단위 11-B3c3d1 — 유지보수 DB 접속 차단·비협력 세션 종료

작성일: 2026-10-07 · 서버 native 인수 완료

## 선행 인수와 범위

11-B3c3c signal diagnostics 수정8개·Python18개 및 native passed를 사용자 11:28 Asia/Seoul 로그로 인수했다. revision 0765dfb6560779e289c129f96d1a656b6da3cc79c7e31ed64ffc74678aff28f0, top153/sub412·operation5개/9 phase·binding5개/2 phase·receipt2개·credential13개, race/vet·전체 작업 lease·중단 사용량 보존·process death drain·fenced recreation·격리 자원 정리를 확인했다. 상세 결과는 직전 c 기록에 반영했다.

이번 단위는 FENCED 아래 privileged DB 접속 차단과 세션 종료 기반 하나다. d 전체 복원 절차를 한 번에 묶지 않는다. source만 적용하며 운영 camera API/schema7/image/DB/key/authority를 변경하지 않는다.

## 구현

FenceCredentialDatabase는 owner의 실제 exclusive MaintenanceLease/정확한 FENCED를 fsync 재확인하고 same endpoint의 별도 postgres control DB에서 동작한다. deadline, 실제 connection identity/transport, owner-superuser/고정 role 속성, prepared transaction 부재를 확인한다. 두 role NOLOGIN+target 신규 접속 차단을 함께 commit하고 target 모든 session과 이 cluster의 두 role session을 terminate/refresh/drain한다. 상태0과 차단 설정을 재검사한 뒤 반환한다. lease를 자동 해제하거나 DB/key/budget/authority를 복원·재개하지 않는다. first owner 모델과 운영 공급 미완료는 ADR0015에 명시했다.

새 runner는 manifest/source/hash 및 c 인수를 요구하고 disposable PostgreSQL tmpfs에서 전체 race/vet·native 기존13개·새 maintenance4개/7 phase를 확인한다. 무해한 고정 실패 이름·stage/exit를 남기며 자체 project 정리를 항상 시도한다. 이전 c runner도 manifest 인수 상태 true로 반복 검사할 수 있도록 했고 hash·전체 phase 요구를 유지했다.

## 로컬 검증

| 검사 | 결과 |
|---|---|
| 실제 local PG17.11+Go race | storage top77/sub61 통과, 새 maintenance4개 및 native7 phase와 기존 native credential13개·DB/migration/dump/restore/operation 권한 회귀 포함 |
| Go vet | 전체 module 통과 |
| Python | 새 maintenance runner18개, 관련 credential unit 전체102개 통과. c 반복 검사 인수 flag 회귀 포함 |
| 전달 | baseline358개와 manifest/hash, 최초 적용/재실행/원본 백업/보호 파일/사용자 수정·신규 목적지 충돌/압축 exclusion 검사 |

local PG는 기존 UID0-only namespace용 시작 거부 조건 두 곳만 수정한17.11 fixture다. SQL/auth 변경은 없으며 key/DB/임시 password/binary를 전달하지 않는다. 종료를 확인했다. 준비된 transaction cleanup과 deliberately terminated pool의 fixture cleanup 결함을 발견해 수정한 뒤 전체 storage race를 통과했다. 이 수정은 test-only이며 product의 자동 재개를 추가하지 않았다.

이번 native control 테스트는 owner filesystem lease와 실제 DB 계정/session/2PC이며 distinct runtime UID/RO key/TLS 결합을 새로 주장하지 않는다. 수정8개 이후 서버 c 인수를 그대로 기록했다. Docker가 없는 local에서는 서버의 unmodified Docker image 실행을 하지 않았고 서버 결과 인수 전 maintenance native_verified=false다. 제품 프로세스/라우팅을 변경하지 않아 기존 smoke62개 인수를 유지한다.

## 남은 작업과 다음 완료 기준

서버 Python18개와 native status=passed, required maintenance4개, native phase7개 및 격리 자원 제거를 인수했다. 다음 11-B3c3d2는 필요한 maintenance 계정/네트워크 차단을 추가하고 실제 DB/key 복원·옛 budget disabled·독립 fresh material과 seen 보존·새 incarnation/marker·PREPARED 우선 영속화·OPEN 전 검사를 연결한다. 중단/재시도와 과거 key/process/endpoint 거부가 완료 기준이다. target DB를 복원용으로 다시 열기 전에 네트워크/계정 경계를 먼저 확보한다.

production_restore_fence_implemented·credential_runtime_key_supply_verified·credential_api_activated·business_runtime_ready=false, network_fence_verified=false다. 운영 preflight/rehearsal/activation 및 credential HTTP는 각각 후속 단위다. Streamlit 브라우저 인수는 deferred이고 중계를 추가하지 않는다. 적용 명령은 채팅에서 제공한다.

## 서버 인수 — 2026-10-07 사용자 실행 로그

패치18개 적용·pending0, Python18개 OK, native status=passed를 인수했다. project vms-credential-maintenance-test-bf460b7c3211, checked_revision a2116e85a9d93b03ea54e65c4209d3b5b82b946c27e2f2377f6fe64e5e812e0d다. Go race/vet, top155/sub406, credential13개·maintenance4개·native7 phase를 통과했다. 외부 FENCED 우선·위험 authority/endpoint 거부·NOLOGIN 기존 세션 한계·target 신규 연결 차단·비협력/owner 및 cross-DB fixed-role 세션 drain·committed retry·prepared transaction 거부·row/budget 보존을 확인했다. isolated_resources_removed=true다.

production_services_modified/production_database_modified/production_keys_loaded/production_admission_state_created/credential_api_activated/production_restore_fence_implemented/business_runtime_ready/database_and_key_restore_performed/network_fence_verified는 모두 false다. 운영 schema7/API는 그대로다. 위 '서버 인수 대기'와 이전 다음 단위 설명은 전달 시점 기록이며 현재는 d1을 인수하고 d2를 나눈다. 다음 d2a는 유지보수 HBA/TLS 접속 경계, 그 서버 검사를 인수한 뒤 d2b에서 실제 DB/key 복원을 연결한다.
