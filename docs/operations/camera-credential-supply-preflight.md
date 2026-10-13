# 운영 자격증명 공급 사전점검 — 11-B3c3d3

현재 인수된 camera schema7/API 0.7.0-device-delete의 공급 준비 상태를 읽기 전용으로 목록화한다. 운영 공급 승인이나 활성화를 허용하는 영수증은 아니다. 도구는 src/infra/tools/inspect_camera_credential_supply.py이며 실행 명령은 전달 채팅에 제공한다.

## 확인 범위

| 항목 | 확인 방법 | 확인하지 않는 것 |
|---|---|---|
| 소스·인수 전제 | 전체 manifest hash, 격리 재개 서버 인수, step10 활성화 이미지·schema7 영수증 | 현재 소스가 운영 이미지에 재빌드됐다는 주장 |
| 실행 구성 | 로컬 Unix Docker, 소유 volume, 실행 container/image, Compose image, DSN 파일의 실제 RO mount, API readiness/platform/OpenAPI | 실제 프로세스 UID, 자격증명 runtime 동작 |
| 호스트 키 | descriptor-relative no-follow stat, 소유 UID·0700/0600·regular file·단일 link·크기·점검 전후 metadata | 키 본문·key ID·형식·암호학적 무결성·백업 일치 |
| DB | 고정 READ ONLY SQL, camera_admin/session identity, PostgreSQL17, 정확한 migration1–7 hash, 고정 세 역할의 catalog 속성, TLS 설정 | ciphertext/HMAC/비밀값, TLS 신규 인증·인증서·두 pool binding |
| HBA | 설정 경로 문자열이 data directory 문자열 바깥인지 | 실제 파일·symlink/mount topology·reload·source/CN 인증·packet filter |
| authority·접속 승인 | approved_authority_binding 및 approved_endpoint_and_source_binding을 not_reviewed로 명시 | 임의 경로 탐색·승인 상태 본문 읽기·격리 fixture 값을 운영 승인으로 채택 |

운영 profile/authority 공급 계약과 생성 절차가 아직 없다. 임시 리허설의 UID10001, IP, CA, 키, authority 경로를 운영값으로 복사하거나 추정하지 않는다. 현재 container의 numeric USER는 configured_uid로만 보고하며 actual_execution_uid_verified=false다. 키 bind mount가 보이더라도 credential_key_supply_verified=false다. 권한이 맞는 파일에 잘못된 키 본문이 들어 있어도 이번 점검은 metadata_valid로만 표시하므로 키의 무결성이나 ready를 의미하지 않는다.

DB exec는 env -i의 고정 PATH와 공식 image의 /var/run/postgresql socket·5432 port·camera_admin/vms_camera를 사용한다. PGHOST/PGSERVICE/PGOPTIONS 등의 inherited 환경과 psql startup file을 사용하지 않는다. 고정 SQL은 statement/lock timeout, pg_catalog search_path 아래에서 한 SELECT를 실행한다. 다른 container, 다른 SQL, stdin/stdout redirect, extra environment, Compose 실행·build·restart·grant·migration을 allowlist에서 거부한다. HTTP는 proxy/redirect 없는 loopback GET 세 경로만 허용한다.

## 결과와 실패

완료된 목록화는 status=inspected, inspection_completed=true, readiness=blocked, production_supply_ready=false, activation_allowed=false이며 exit0다. blocker는 schema9 전환·승인 authority/endpoint/source·runtime 키 공급·유지보수 인증 경계·전체 복원 fence·credential HTTP API의 미완료를 나타낸다. 현재 조회 결과에 따라 host key 누락, 별도 역할 누락, TLS off, HBA 경로, 키 mount 부재가 추가된다. blocker가 있는 exit0는 운영 준비 완료를 뜻하지 않는다.

소스/이미지/DB identity·migration 불일치, 위험한 키 link/권한, 점검 중 입력·키 metadata·container 변경, Docker/HTTP/SQL 접근 실패는 status=failed/exit1이다. 실패 report가 이전 결과를 대체하며 raw stderr·예외 detail·token·DSN·키 본문을 기록하지 않는다. report 저장 자체가 불가능하면 stdout/stderr의 고정 오류 코드가 우선한다. 기존 권한·파일을 수리하지 않는다.

쓰기 범위는 var/camera/credential-supply-preflight.json(mode0600)과 공통 activation.lock뿐이다. 공통 private directory/lock은 없으면 기존 activation primitive로 생성한다. 키·authority·role·schema·HBA·환경·서비스·암호화 budget을 바꾸지 않고 backup/restore도 수행하지 않는다. DB query는 읽기 transaction 시점의 목록이며 운영 API의 다른 정상 업무 쓰기가 계속될 수 있다. 다른 관리자의 변경을 연속적으로 차단하거나 production restore fence를 대체하지 않는다.

## 검증과 다음 단위

Python failure-boundary 31개: 명령 차단, SQL 치환, secret-safe 실패, source 검사, key content 미읽기, symlink/hardlink/mode/size, 입력·키·container drift, private report와 재실행을 확인했다. 별도 로컬 PostgreSQL17.11에서 실제 migration1–7, 역할 부재/존재, READ ONLY identity, mutation 거부, schema/row 보존을 확인했다. 로컬 Docker가 없어 실제 Docker exec/socket 및 simsys4090 조회는 사용자 실행으로 확인한다. API/Go/Compose/SQL 원본은 변경하지 않아 기존 Go race/vet/native 인수를 유지한다.

사용자 서버의 checked_revision=effc214a66a3658058490310507d251ea0165fbd325392b9d7bfff0aa1fd1ab4에서 Python31개 OK와 inventory 완료를 인수했다. schema7/TLS off/credential roles·키 mount 부재, metadata_valid0700/0600, 실제 UID·binding 미검증을 확인했다. 실제 Docker exec/socket 조회는 이 서버 결과로 검증했으며 원래 로컬 검증의 Docker 부재 한계는 유지한다. 다음 [운영 공급 계획 계약](../contracts/camera-credential-supply.md)은 선언의 정적 검증까지만 제공한다. 실제 공급·전체 복원 fence·schema9 cutover 및 credential HTTP API는 후속 독립 단계이며 Streamlit browser acceptance는 deferred다.
