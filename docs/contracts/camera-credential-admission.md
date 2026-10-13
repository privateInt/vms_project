# camera 자격증명 복원 차단·쓰기 허용 계약 v1

상태: 11-B3c1 계약, 11-B3c2 외부 state/lease, 11-B3c3a DB marker, 11-B3c3b 키/profile, 11-B3c3c 전 작업 lease, 11-B3c3d1 DB 차단, 11-B3c3d2a HBA 경계, 11-B3c3d2b 실제 복원/PREPARED, 11-B3c3d2c 격리 업무 재개까지 서버 인수

원본은 src/platform/camera/api/planned/credential-admission.schema.json, 합성 예제는 같은 폴더의 credential-admission.examples.json이다. 이 계약은 camera 로컬 유지보수 기록이다. HTTP 입력·공개 API·실행 OpenAPI나 준비 완료 인증서가 아니다. 현재 운영 스키마 7과 격리 저장소 스키마 8을 변경하지 않는다. 스키마 9 marker는 11-B3c3a의 명시적 격리 마이그레이션 대상으로 구현했다. 기존 Migrate는 스키마 8이며 패치 적용은 운영 DB를 변경하지 않는다.

## 단일 소유권과 외부 권위

camera가 키·budget·DB incarnation·쓰기 입장을 소유한다. 하나의 키는 승인된 단일 DB/endpoint의 하나의 budget 권위에만 사용한다. DB 복사본·동시 새 배포에서 같은 encryption material/ID로 쓰지 않는다. 단일 Linux 호스트의 검증된 로컬 파일시스템을 첫 범위로 한다. 다중 호스트·NFS/JuiceFS·분산 lease·자동 failover는 별도 인수 전 지원하지 않는다.

외부 상태와 바뀌지 않는 admission.lock은 프로젝트 트리·PG data/volume·DB dump·키 백업 바깥에 둔다. 유지보수 계정만 상태를 갱신하며 runtime에는 directory를 read-only로 공급한다. 예전 OPEN 상태나 lock 파일을 DB/키 백업과 함께 복원하지 않는다. timestamp는 감사 정보이고 시간 경과나 유효기간으로 차단을 해제하지 않는다.

목표 파일 정책은 유지보수 UID와 전용 runtime GID 소유의 directory 0750·state/lock 0640이다. runtime group에는 읽기/탐색만 허용한다. 현재 UID 전용 0700/0600 또는 0500/0400 키 로더와 다른 정책이며 키 로더의 권한 검사를 완화하지 않는다. 미래 admission reader가 승인된 소유 UID/GID·mode·단일 link·일반 파일·no-follow·경로/metadata 안정성·read-only mount를 별도로 검사한다. 실제 운영 호스트 UID/GID와 mount 구성은 후속 운영 준비에서 정한다. 11-B3c2는 별도 유지보수 UID·runtime GID와 실제 read-only mount를 요구하는 기반과 임시 Docker volume 검사를 추가한다. 운영 경로의 chmod/chown·bootstrap 도구는 아직 없다.

외부 상태는 DB 스냅샷과 독립된 유지보수 권위다. 파일 자체가 임의 관리자 복원이나 호스트 전체 rollback을 자동 탐지하는 장치는 아니다. 권위가 유실/충돌/복원됐거나 미확인 DB 복사가 있으면 자동 초기화/OPEN을 금지한다. 승인된 별도 복구와 새 독립 키가 필요하다. bootstrap은 비밀 이력/budget 사용과 기존 외부 권위가 없는 최초 배포에만 명시적으로 허용한다.

## 기록 형식

| 필드 | 의미·제한 |
|---|---|
| schema_version | v1 |
| deployment_id | 최초 배포의 canonical lowercase UUID4. 일반 변경/복원에서 보존 |
| generation | 양의 int64. 새 차단 작업은 정확히 1 증가. 최대값이면 차단 해제 불가 |
| operation_id | 해당 generation 유지보수 작업의 canonical UUID4. 다른 작업/재시도 혼동 거부 |
| state | FENCED, PREPARED, OPEN만 허용 |
| written_at | 유효한 UTC 시각, 최대 소수 9자리. 권한/lease 만료 값 아님 |
| counter_policy | new-key-after-fence-v1만 허용 |
| seen_encryption_key_ids | 사용/승인 후보로 등록한 모든 encryption ID의 단조 증가 집합. 중복 없이 최대 512개 |
| binding | 미선택 초기 FENCED에서 null 가능. 나머지는 아래 정확한 후보/마지막 문맥 |

Binding은 database_id(UUID4 incarnation), database_name, schema_version=9, migration_set_sha256, endpoint_profile_sha256, key_bundle_sha256, active_encryption_key_id, active_idempotency_key_id, writer_role=camera_credential_writer, budget_role=camera_credential_budget를 모두 요구한다. URI·DSN·password·key material·파일 경로·주소 원문·ready/force/skip 필드는 없다.

migration_set_sha256은 적용된 순서별 migration의 version/checksum 목록을 정해진 JSON 형태로 직렬화해 hash한다. endpoint_profile_sha256은 승인된 단일 host/port/database/TLS mode/server name/CA digest/두 role의 정해진 profile을 hash하고 password·DSN 원문은 제외한다. key_bundle_sha256은 strict 검사를 통해 실제 로드한 정확한 private bundle 바이트의 SHA-256이다. migration의 정규 표현은 11-B3c3a, endpoint 표현 및 실제 loader 영수증은 아래 11-B3c3b에 고정했다. hash를 서명이나 준비 완료 증명으로 취급하지 않는다.

11-B3c2 raw parser는 최대 32768바이트, unknown/duplicate/escaped-alias 필드·후행 JSON·잘못된 UTF-8·정수의 bool/decimal/exponent token을 거부한다. JSON Schema는 1.0을 integer로 인정하고 중복 원문 필드를 검사하지 못한다. 파일 형식 이외의 값 간/기록 간 조건은 11-B3c2 parser/state machine으로 추가 검사한다. DB/키 원문과 profile hash 영수증 확인은 후속 통합이다.

## 상태와 전이

| 상태 | 쓰기 입장 | 유지보수 의미 |
|---|---|---|
| FENCED | 거부 | 새 복원/차단 작업. binding이 있어도 마지막 문맥일 뿐 허용하지 않음 |
| PREPARED | 거부 | 정확한 후보·키 ID를 외부 권위에 먼저 영속 등록. DB 준비 완료 주장 아님 |
| OPEN | 추가 검증과 shared lease를 통과해야 허용 | 해당 binding/generation에 대한 조건부 허용 의도. 자체 ready 인증 아님 |

처음에는 FENCED로 생성한다. PREPARED에서 후보 binding/operation/generation을 고정하고 seen 집합에 fresh encryption ID를 fsync로 기록한 뒤 DB budget을 등록한다. 이후 DB marker·권한·키 이력/복호화/HMAC replay·활성 새 budget을 확인해 OPEN으로 전환한다. OPEN의 같은 기록 재확인은 generation이나 budget을 초기화하지 않는다.

새 복원/재차단은 새 operation과 generation+1의 FENCED를 **DB/키를 변경하기 전에** 영속 기록한다. seen 집합은 제거/교체하지 않는다. 새 encryption ID/material은 이미 seen에 있거나 과거 공급했던 키가 아니어야 한다. 기존 material에 새 ID만 붙이는 재사용을 금지한다. 키 원문은 보호된 CSPRNG 준비 도구에서 생성하고 암호화와 HMAC 목적을 분리한다.

같은 PREPARED 작업의 재시도만 이미 선택된 후보를 다시 검사할 수 있다. 기존 DB 등록을 발견해도 정확한 operation/generation/binding, 활성 상태, uses=0·해당 키의 저장 버전 없음이 일치할 때만 후보 등록 재시도로 취급한다. count를 reset/감소시키거나 disabled 키를 재활성화하지 않는다. PREPARED 후 다시 DB 복원을 수행하려면 새 FENCED generation을 만들고 또 다른 새 키를 선택한다. 중단된 후보도 seen 집합에서 제거하지 않는다.

활성 encryption ID는 seen에 포함돼야 한다. generation 후퇴/건너뛰기·배포 ID 변경·다른 operation·후보 변경·seen 삭제·기존 encryption ID 재선택은 거부한다. max generation/seen 상한 도달은 자동 압축·초기화 대신 차단한다. 시각 비교만으로 동일 작업이나 순서를 판정하지 않는다.

## lease와 복원 순서

1. 새 입장을 중지하고 deadline 있는 exclusive lease를 바뀌지 않는 lock inode에서 획득한다. 획득 실패이면 DB/키 복원은 시작하지 않는다.
2. 그 lease 아래 새 FENCED 상태를 파일 fsync·atomic replace·부모 directory fsync로 확정한다. 성공 여부가 불명확하면 복원을 진행하거나 이전 OPEN을 복사해 되돌리지 않는다.
3. 쓰기/비밀 소비 프로세스를 중지하고 두 credential 계정 NOLOGIN·기존 세션 종료·세션 0을 확인한다. 원래 DB/endpoint의 계정 연결도 차단한다. 어느 조건이 실패해도 외부 상태를 차단한 채 종료한다.
4. 승인된 DB와 정확한 키 백업을 복원하고 모든 이전 encryption budget을 disabled로 둔다. 새로운 DB incarnation·marker, 보존한 옛 encryption/HMAC 이력, 독립 새 encryption key와 정확한 후보를 준비한다.
5. PREPARED를 먼저 영속 기록한 뒤 새 budget/marker를 준비하고 재검사한다. OPEN 전까지 유지보수 lease와 차단을 유지한다. 단일 DB뿐 아니라 role/클러스터 복원 경로도 이 외부 절차를 거쳐야 한다.
6. 승인된 OPEN 기록을 영속 확정한 후 계정/프로세스 재개를 수행한다. 실제 두 role DSN의 인증/DB/권한/marker/키 검사를 마치기 전에는 비즈니스 트래픽을 열지 않는다. OPEN은 각 runtime의 검증을 생략시키지 않는다. 재개 검증 실패 시 다시 차단하고 그 generation의 후보를 자동 재사용하지 않는다.

유지보수는 변하지 않는 sidecar lock만 잠근다. atomic replace되는 state 파일 자체를 lock하거나 lock inode를 재생성하면 서로 다른 잠금 권위가 생길 수 있으므로 금지한다. runtime 작업마다 독립 descriptor/lease 또는 검증된 참조 수 관리가 필요하다. 같은 process의 공유 descriptor를 한 작업이 unlock해 다른 작업의 보호를 제거하지 않는다. 프로세스 종료가 lock을 해제해도 영속 FENCED/PREPARED가 자동 OPEN으로 바뀌지 않는다.

flock은 협력하는 참가자의 advisory lock이다. DB role·접속 경계·모든 입장 코드와 함께 검증해야 한다. direct SQL/admin 우회를 lock만으로 막았다고 주장하지 않는다. 분산/원격 filesystem의 lock 동작을 로컬 결과로 대신 인수하지 않는다.

## runtime의 필수 재검사

runtime은 shared lease를 획득한 다음 현재 OPEN·승인 deployment/generation/binding과 실제 로드한 immutable keyring 영수증, 두 distinct role/pool의 actual session/current user·database·승인 단일 endpoint profile·migration/checksum·DB marker를 비교한다. DB marker의 deployment_id/generation/database_id는 외부 권위와 모두 일치해야 한다. 이전 pool/keyring 또는 이전 generation을 캐시한 프로세스는 거부하고 검토된 재시작/재로드가 필요하다.

DB marker는 스키마 9의 owner 전용 쓰기 관계다. runtime 두 계정은 변경하지 못한다. marker도 dump에 포함되므로 **marker 일치만으로 예전 DB snapshot 복원을 자동 감지하지 못한다.** 외부 차단 절차를 거쳐 모든 과거 키 쓰기를 폐쇄한 뒤 새 incarnation/generation을 결합해야 한다. budget/키 이력·현재 키 ready를 검사해도 외부 권위/lease를 대신하지 못한다.

shared lease는 WriteVersion의 첫 확인 transaction → 별도 committed budget 예약 → 암호화/저장 transaction → 결과 확정 전체 구간을 보호한다. startup이나 예약 전 한 번만 확인하고 lease를 놓지 않는다. 과거 성공 replay·RevokeVersion·CheckReference와 미래 원문 resolve/장비 연결 입장도 같은 차단에 참여한다. 인증·자격증명 대상/장치/정확한 버전·사용 guard·DB transaction 경계는 별도로 유지한다. 새 기본 unused 또는 우회 guard를 제공하지 않는다.

상태/파일/lock/소유권/DB/marker/key 확인이 불가능하면 입장 거부다. 프로세스 health와 registry CRUD는 자격증명 입장 준비 상태와 구분한다. 공개 오류에는 고정 unavailable/conflict 코드만 쓰고 key 원문·DSN·주소·내부 원인·파일 경로를 넣지 않는다. HTTP 상태/코드는 실제 비밀 API 계약에서 별도 확정한다.

## 후속 인수

정적 스키마와 예제는 파일 내용 형태만 확인한다. structurally_valid_but_disallowed 예제는 shape 검사에 통과하지만 동적 guard가 거부해야 할 key membership·재사용·generation rollback이다. 이를 실행된 fence로 표시하지 않는다.

11-B3c2는 strict parser·외부 state/sidecar lease·create-only FENCED·CAS/중단/경합/권한/경로 교체 검사를 구현했다. 서버의 실제 mount/UID 검사와 필수17개·native2 phase 통과는 사용자 로그로 인수했다. 이후 DB marker·키 loader 영수증·CredentialStore 전 구간 guard·역할/계정/복원 제어를 native 환경에서 결합한다. 마지막으로 서버 preflight/격리 리허설/운영 전환을 분리해 인수한다. production_restore_fence_implemented·credential_runtime_key_supply_verified·credential_api_activated는 이번 계약에서 false다. [ADR 0010](../architecture/decisions/0010-camera-credential-admission.md)과 [진행 기록](../progress/20261002-step11b3c1-admission-contract.md)을 따른다.

## 11-B3c2 실행 기반의 경계

Bootstrap은 외부 directory를 자동 생성하지 않으며 이미 승인·공급한 0750 경로에서 빈 최초 FENCED만 생성한다. 최초 배포에 비밀 이력/budget 사용/이전 외부 권위가 없다는 사실은 호출 유지보수 계층에서 증명해야 한다. 기존 state 또는 lock이 있으면 재초기화·복구하지 않는다. 중단된 bootstrap은 별도 감사 복구 대상이다.

lock 생성 시 device/inode 영수증을 반환한다. 이를 DB/키 snapshot 바깥의 검토된 host 설정에 고정하고 모든 maintenance/runtime Policy에 공급한다. lock 파일 교체를 기존 lease뿐 아니라 새 process에서도 거부한다. 경로에서 inode를 매번 자동 재발견하거나 복원된 receipt를 신뢰해 권위를 재설정하지 않는다. 이 영수증은 서명이나 전체 host rollback 탐지기가 아니다. 배포 설정 공급/보존은 후속 운영 준비 단위다.

공개 AcquireReadOnly는 유지보수 UID와 다른 runtime UID·실제 read-only local mount·고정 lock 영수증·완전한 expected OPEN 기록을 검사한다. bootstrap/maintenance는 실제 EUID=owner를 요구한다. ext4/XFS/Btrfs/tmpfs/overlay의 Linux statfs 종류를 허용하며 NFS/FUSE/미확인 종류는 거부한다. 로컬 검사는 overlay에서 수행했으며 모든 허용 FS의 전원 장애 내구성을 인수한 것은 아니다.

Commit은 exclusive lease 아래 정확한 기존 Record와 허용 전이를 비교한다. FENCED 유지보수 시작은 generation+1/new operation, PREPARED는 fresh ID/fresh DB incarnation과 append-only seen 집합, OPEN은 PREPARED 이후만 허용한다. generation/seen 상한에 도달한 기록의 OPEN 입장은 거부한다. 이 기반은 key material의 재라벨링 여부나 DB 준비를 검사하지 않는다. OPEN 전환 호출을 DB 준비 완료 증명으로 사용하지 않는다.

성공은 file fsync·rename·directory fsync·다시 읽기 완료를 의미한다. IO 실패는 COMMIT_UNCERTAIN과 사용 불가 lease를 반환한다. 새 lease에서 상태를 재검사하고 동일 기록을 Commit해도 파일/부모 fsync를 재확인한다. 단순 Snapshot은 복원 진행 승인이나 내구성 영수증이 아니다. deadline은 잠금 획득 제한이며 획득한 lease를 자동 만료·해제하지 않는다. 작업 종료까지 Close 책임을 유지한다.

Go tests의 private mount 검사 생략 helper는 파일/lease 로컬 검사용이며 공개 입장 API에 옵션/우회값으로 노출하지 않는다. 실제 runtime positive 검사는 격리 Docker의 read-only volume과 UID10001에서 공개 API로 수행한다. DB9·CredentialStore·키 영수증·계정/네트워크 제어와 결합 전 production_restore_fence_implemented=false다. 자세한 결과와 다음 인수는 [11-B3c2 진행 기록](../progress/20261002-step11b3c2-external-state-and-leases.md)을 따른다.

## 11-B3c3a DB 검사 표현

명시적 MigrateCredentialAdmission은 기존 SQL1..8의 원본을 그대로 사용하고 admission_migrations/0009_credential_admission.sql을 마지막에 적용한다. 운영/이전 리허설의 Migrate와 CheckReady는 계속 스키마8만 인수하며 스키마9를 거부한다. 전체 runtime 통합 이후 목표 선택을 별도 전환한다.

마이그레이션 hash v1은 UTF-8 compact JSON array에 version,name,checksum 순서의 키를 가진 entry를 버전 순으로 배열한 SHA-256이다. version은 정수1..9이며 name은 상대 경로 원문, checksum은 해당 SQL 파일의 정확한 bytes SHA-256 소문자 hex다. 공백·마지막 newline이 없다. 1..8 경로는 migrations 아래, 9 경로는 admission_migrations 아래다. CredentialAdmissionMigrationsSHA256은 코드에 embed된 이 집합만 사용한다. 실제 DB의 version/name/checksum도 모두 비교하므로 표식에 같은 hash를 적는 것만으로 잘못된 history를 인수하지 않는다.

camera.credential_admission_database는 singleton=1 한 행, deployment_id/generation/operation_id/database_id/database_name/schema_version=9/migration_set_sha256 및 written_at audit 필드다. ID는 canonical UUID4, generation은 양수 bigint다. 마이그레이션은 빈 테이블만 만든다. 유지보수의 PREPARED 기록·writer 차단·fresh key/budget·표식 설치 순서를 자동화하는 코드는 아직 없다.

CheckCredentialAdmissionDatabase는 외부 기록에서 전달할 기대값을 기준으로 실제 접속 role·session_user/current_user·DB 이름·위험 role 속성·SELECT 및 marker/history 변경/소유 role membership/schema CREATE 권한 부재를 검사한다. fixed writer 또는 budget 역할의 각 pool에서 repeatable-read read-only transaction 하나로 전체 migration history와 표식 모든 필드를 확인한다. 실패는 내부 driver cause 없는 ADMISSION_DATABASE_UNAVAILABLE이다. 결과를 캐시하거나 encryption budget을 예약하지 않는다. 11-B3c3b는 별도 비교 함수에서 actual endpoint/TLS profile·키 loader 영수증을 결합했다. 외부 lease와 CredentialStore 작업 구간은 아래 11-B3c3c의 별도 승인 생성자에서 연결한다. 이 함수의 성공은 credential 입장 승인이나 restore fence 완료가 아니다.

## 11-B3c3b 키·endpoint 비교 표현

ProtectedBundleReceipt는 strict protected file loader가 실제 로드한 exact bytes SHA-256과 Linux mount의 ST_RDONLY 관찰을 immutable ring 내부에 기록한 결과다. ParseKeyBundle에는 파일 영수증이 없으며 mode0400 파일을 RW mount에서 읽은 것만으로 RO를 표시하지 않는다. 로드 후 파일 내용이 바뀌어도 기존 ring과 영수증은 바뀌지 않는다. 같은 파일을 다시 읽은 current path 증명·서명·restore fence가 아니며 새 승인 hash와 다른 기존 ring을 거부하는 비교에 사용한다. 실제 운영 공급은 아직 수행하지 않았다.

첫 CredentialEndpoint는 canonical IPv4/IPv6 주소 하나와 포트, DB를 승인 설정으로 받는다. DNS host·여러 주소·UDS·자동 failover는 지원하지 않는다. TLS mode는 명시적 disable 또는 verify-full만 허용하며 require/prefer/allow/verify-ca는 거부한다. verify-full은 승인된 server name과 CA certificate PEM 하나를 요구하고 생성기가 그 정확한 bytes hash와 CertPool을 직접 얻는다. default/system CA·client certificate·servicefile·passfile을 접속 근거로 삼지 않는다. CA는 공개 신뢰 정보이지만 endpoint 설정의 출처는 신뢰된 배포 설정이어야 하며 HTTP 입력은 허용하지 않는다.

endpoint hash v1은 compact UTF-8 JSON object를 format_version(정수1),host,port(정수),database,tls_mode,tls_server_name,ca_sha256,writer_role,budget_role 순서로 직렬화한 SHA-256이다. 두 role은 기존 고정 값이다. disable의 server name/CA hash는 빈 문자열이며 verify-full의 CA hash는 exact PEM bytes의 SHA-256이다. 공백·마지막 newline이 없다. password/DSN/path는 표현에 넣지 않는다. 객체는 raw address를 출력/JSON serialize하지 않고 hash만 제공한다.

OpenCredentialAdmissionDatabase는 explicit role/password/IP/port/DB/sslmode URI만 받아 승인 객체와 대조한다. query의 duplicate/host/service/TLS 확장, ambient PG 환경, password 생략을 거부한다. complete controlled pgx config에서 승인 CA/TLS만 적용하고 fallback을 없앤다. 연결의 실제 peer IP/port, verify-full handshake·TLS1.2 이상·verified chain/server name/승인 CA를 확인한다. legacy Open은 이 접속 영수증을 만들지 않는다.

CheckCredentialAdmissionBindings는 caller의 잠긴 외부 기록에서 온 PREPARED 또는 OPEN의 비교 검사다. actual ring의 RO receipt/hash와 active 두 key ID, endpoint hash, 두 distinct approved pool의 실제 transport/role/DB/marker/history, active encryption budget ready를 확인한다. 각 pool에서는 같은 acquired connection의 read-only repeatable-read snapshot으로 transport와 SQL 증거를 결합하며 budget use를 예약하지 않는다. 실패는 driver cause 없는 ADMISSION_BINDING_UNAVAILABLE이다. 두 pool snapshot 사이 및 이후 작업의 연속성을 제공하는 external lease는 아래 별도 operation guard에서 결합한다. 이 비교 함수는 업무 권한/전체 private grants·fresh-key 독립성·복원 차단·작업 구간 guard를 대신하지 않는다.

## 11-B3c3c 업무 메서드와 lease

NewCredentialStore의 foundation 비교 함수는 inspection만 한다. 그 생성자로 만든 저장소의 WriteVersion/RevokeVersion/CheckReference/CheckReady는 guard 부재 시 DB IO 전에 CREDENTIAL_ADMISSION_UNAVAILABLE로 거부한다. NewAdmittedCredentialStore는 검토된 Policy/안정 inode pin/전체 OPEN record/승인 endpoint를 받고 binding/history 복사본을 소유한다. 생성자는 DB를 조회하거나 기대 기록을 자동 재발견하지 않는다. 실제 호출 context에는 deadline이 필요하다.

공개 업무 메서드는 credentialadmission.AcquireReadOnly로 OPEN/동일한 전체 record·RO mount/distinct UID/안정 lock을 확인한 다음 동일 lease 아래 actual loader bytes/keys/endpoint/two-role DB/표식/history/budget ready를 비교한다. 각 실제 data 및 별도 budget transaction에서도 transport/session/current role/history/marker와 필요한 개별 grants를 검사한다. pool 초기 인증 접속은 별도 준비 작업이며 승인 없이 업무 SQL/예산 소비를 허용하지 않는다.

shared lease는 첫 확인 tx부터 독립 budget commit, 암호화/저장 tx, success replay/revoke/reference/CheckReady와 최종 검사·메서드 반환까지 유지한다. transaction의 commit/rollback·panic defer 뒤 lease를 닫는다. 커밋 뒤 최종 검사 실패/응답 손실은 이미 durable journal/use가 있을 수 있고 이를 되돌리거나 재사용하지 않는다. 아직 구현하지 않은 HTTP 응답 전송이나 resolve/장비 연결은 이 Go 메서드 수명으로 완료됐다고 표시하지 않는다.

유지보수 exclusive lease는 정상 반환/오류/panic/취소 또는 process death로 drain된 뒤 FENCED를 커밋한다. 기존 OPEN record를 pin한 새 process는 자동 재승인되지 않는다. private guard 인터페이스는 caller에게 노출하지 않고 schema8 회귀 fixture는 _test.go에만 존재한다. 운영 계정/네트워크 차단·DB/key 복원·독립 fresh material/budget/marker·PREPARED→OPEN 절차를 포함한 full restore fence는 후속 단위다. [ADR 0014](../architecture/decisions/0014-camera-credential-operation-leases.md) 및 [진행 기록](../progress/20261007-step11b3c3c-credential-operation-leases.md)을 따른다.

## 11-B3c3d1 DB 입장 차단 기반

FenceCredentialDatabase는 maintenance 전용 Go primitive다. deadline·실제 exclusive MaintenanceLease·정확한 기존 binding을 가진 FENCED를 요구하며 같은 record의 fsync 재확인 후 DB에 접근한다. trusted endpoint의 실제 peer/transport, 별도 postgres control DB, session/current user와 owner-superuser, 고정 runtime role의 위험 속성을 확인한다. 첫 범위에서는 privileged maintenance session이 target DB를 직접 소유해야 한다. 실제 운영 계정은 아직 지정·공급하지 않았다.

고정 writer/budget을 cluster-wide NOLOGIN으로, bound target DB를 ALLOW_CONNECTIONS=false로 함께 커밋한다. NOLOGIN은 기존 연결의 종료를 대신하지 않는다. target DB의 모든 세션(소유자 포함)과 두 고정 역할의 이 cluster 내 다른 DB 세션을 종료하고 실제 activity0을 확인한다. 준비된 transaction은 backend 종료 뒤에도 남을 수 있으므로 사전/사후 모두 검사하며 자동 commit/rollback하지 않는다. 실패하면 복원으로 진행하지 않고 외부 FENCED를 유지한다.

이 primitive는 DB/key 복원·budget disable·OPEN·LOGIN 재개·lease 해제를 수행하지 않는다. 기존 registry 접속도 target DB 차단의 영향을 받으므로 실제 운영 적용은 별도 유지보수 preflight/절차를 요구한다. PostgreSQL 내부 접속 차단이며 host/network 차단, 다른 endpoint/replica, 임의 privileged administrator의 재설정 방어가 아니다. 데이터 복원을 위해 DB를 다시 열기 전에 maintenance 전용 계정/네트워크 경계를 완성해야 한다. 전체 복원 fence와 운영 활성화 상태는 false다.

## 11-B3c3d2a 유지보수 HBA 경계

CredentialMaintenanceHBA는 target/postgres·canonical 단일 source IP·camera_maintenance 역할에만 hostssl SCRAM과 clientcert=verify-full을 허용하는 complete 정책을 생성한다. local 및 나머지 IPv4/IPv6는 reject다. OpenCredentialMaintenanceDatabase는 승인 server CA/hostname/profile, source bind와 client CN·명시적 URI를 검사한 fresh mTLS 관리 연결을 연다. InspectCredentialMaintenanceHBA는 durable FENCED/exclusive lease, 실제 관리 세션·NOLOGIN·exact disk 정책과 data directory 밖의 경로·parse/2PC 부재를 확인한다. disk/reload가 active policy proof는 아니며 제품의 reopen 권한을 반환하지 않는다. 새 positive/negative authentication과 관리자/control-plane 독점, snapshot 밖 정책 보존은 실제 복원 절차의 필수 선행 조건이다. HBA 인증 경계이며 packet firewall를 주장하지 않는다. [ADR0016](../architecture/decisions/0016-camera-maintenance-hba-boundary.md) 및 [격리 검사](../operations/camera-credential-boundary-check.md)를 따른다.

## 11-B3c3d2b 복원 후보 준비

CheckRestoreSuccessor는 trusted pre-fence/backup ring의 모든 역사 material과 현재 active HMAC을 보존하고 독립 새 암호화 material/ID를 요구한다. PrepareRestoredCredentialDatabase는 durable PREPARED/exclusive lease·protected exact candidate·승인 backup marker·실제 maintenance TLS/source/role·disk HBA/NOLOGIN·migration/history를 비교한 뒤 새 budget0과 incarnation을 하나의 transaction에 반영한다. 재시도는 같은 candidate marker·uses0/enabled·다른 budget disabled·새 키의 데이터 부재를 요구하며 used/disabled budget을 reset/reactivate하지 않는다. 공개 HBA inspection은 FENCED 전용을 유지한다.

실제 DB/key restore와 maintenance-only reopen은 disposable 통합 fixture에서만 수행한다. 제품 primitive는 restore·HBA activation·OPEN/LOGIN을 하지 않는다. trusted archive/control-plane 독점 및 actual new authentication proof는 caller 책임이다. 이번 인수 종료 상태는 PREPARED와 닫힌 target이며 업무 재개는 후속 단위다. [ADR0017](../architecture/decisions/0017-camera-boundary-restore-candidate.md)을 따른다.


## 11-B3c3d2c OPEN 의도 기록과 격리 업무 재개

AuthorizeRestoredCredentialOpen은 배포 관리 코드만 호출하는 primitive다. 동일한 exclusive lease·PREPARED/Open 쌍·protected key receipt·승인 endpoint/source·maintenance-only HBA 아래에서 이미 commit된 정확한 후보 marker, 새 키 enabled/uses0, 이전 키 disabled를 검사한다. 복원 전 marker를 보정하거나 budget을 등록/초기화하지 않는다. 검사 후 동일한 binding/generation/op/history의 OPEN을 durably 기록한다. 이미 동일한 OPEN이 기록된 재호출은 그 의도의 durability만 확인하며 이후 사용량을 다시 0으로 요구하거나 되돌리지 않는다. 불확실한 응답은 새 lease의 snapshot으로 같은 쌍을 확인한다. OPEN 의도는 실제 runtime readiness 영수증이 아니다.

CredentialRestoredRuntimeHBA는 완전한 파일을 생성한다. 유지보수 source의 camera_maintenance mTLS 규칙 뒤에 별도의 정확한 runtime source/단일 target DB/two fixed role/SCRAM over TLS 규칙을 넣고 나머지 TCP와 Unix socket을 reject한다. Runtime은 승인 endpoint CA/hostname을 verify-full로 확인한다. 제품 함수는 HBA 설치/reload·LOGIN·서비스 실행을 하지 않는다.

격리 fixture만 OPEN → runtime HBA 설치/reload → 업무 역할 LOGIN → exclusive lease 해제 → UID10001/RO key·authority를 가진 실제 두 TLS pool과 public whole-operation admission → 저장/조회/재시도·새 프로세스 재생을 연결한다. 중단 시 OPEN만 존재하고 계정은 NOLOGIN인 상태에서도 실제 runtime source 인증이 거부됨을 검사한다. 사용된 후보 OPEN 거부는 별도 disposable 복원 회귀 검사에서 수행하고 재개 fixture에서 사용량을 되돌리지 않는다. [ADR0018](../architecture/decisions/0018-camera-restored-open-intent.md)을 따른다.


## 2026-10-07 서버 재개 인수

동일 revision7d3168b40749aa886f6c359cf12a1bd43e0dda634188fdd1e2998a554669e277에서 복원 회귀8/native15와 재개12/native24, Python95, Go race/vet를 인수했다. 재개 검사는 actual UID10001·exact RO key/authority mount·actual two-role TLS pool·public whole-operation guard·새 키 저장/reference/replay 및 재생성 process 재시도 성공을 확인했다. 별도 복원 회귀 DB는 최종 PREPARED/closed/NOLOGIN이고 재개 DB는 OPEN/uses1이다. 운영 DB의 상태 전환이 아니다.

운영 key/authority/HBA 공급·schema9 전환·full production restore fence·credential API·business runtime은 미활성이다. 다음 단위는 운영 공급 설정의 읽기 전용 사전점검이며 생성/변경/activation과 분리한다. 결과 및 경계는 [서버 인수 기록](../progress/20261007-step11b3c3d2c-server-acceptance.md)을 따른다.
