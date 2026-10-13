# 운영 공급 검토 초안 — 11-B3c3d4c

src/infra/tools/prepare_camera_credential_supply_review.py는 공급 계약의 모든 required field를 보여 주는 불완전 worksheet를 만든다. d4b 서버 인수 후 실행하며 기존 read-only 사실 조사를 새로 수행한다. 저장된 preflight/facts report를 현재의 관측이나 승인 영수증으로 사용하지 않는다. 실행 명령은 전달 채팅에서 제공한다.

| 초안 분류 | 처리 | 승인·공급 의미 |
|---|---|---|
| 계약 정책42개 | schema의 const와 강제된 빈 capabilities 배열을 연결 | verify-full·역할·RO 정책·FENCED bootstrap 등의 선언만 표시 |
| host/source metadata4개 | checked source SHA·project root·현재 source key path/owner UID | 기존 metadata만 연결; 키 본문/hash와 supply binding 미검증 |
| 미검증 관찰 후보7개 | daemon-host UID/GID 목록·volume 선언 경로·현재 network IP | partial plan에는 자동 선택하지 않고 별도 후보로 기록 |
| 미확정40개 필드 | null과 unresolved_fields 목록 | UID mapping·고정 주소·PKI·보호 파일 위치·authority·snapshot 입력 후속 검토 |
| 후속 확인5개 범주 | UID/키 사본/actual binding/physical topology/최초 전환 조건 | 모두 필요하며 초안 성공으로 완료되지 않음 |

키 metadata가 누락되면 path/owner도 null로 남아 미확정 필드가42개가 된다. source key/CA hash에 dummy hash를 넣지 않고, maintenance UID/IP·TLS name·authority·snapshot 경로도 자동 생성/선택하지 않는다. source 원본을 chown/복사/로드하지 않는다. database.server_uid·runtime.uid/gid·authority.runtime_gid, 현재 volume 경로와 IP는 실제 mapping/physical/pinning 미검증으로 null을 유지한다. 이름이나 field가 확인됐다는 이유로 인증서·DSN·HBA·mount 파일을 생성하지 않는다.

문서 kind는 camera-credential-supply-review, intent는 review-only-incomplete다. partial_supply_plan은 모든 required field를 포함하지만 null이 있어 기존 SupplyPlan parser가 거부한다. worksheet 전체도 SupplyPlan이 아니다. review_is_deployable=false/supply_plan_created=false/activation_allowed=false를 항상 표시한다. manually edited worksheet나 완성된 static declaration을 runtime authorization으로 읽는 loader는 제공하지 않는다.

기본 실행은 status=planned로 검토 항목만 출력하며 초안 파일을 만들지 않는다. apply 옵션은 private var/camera/credential-supply-reviews(mode0700)의 review-<내용SHA>.json(mode0600)에 worksheet만 저장한다. 신규 내용은 prepared, 동일 내용 재실행은 already_prepared다. transient worker count와 PID는 초안에 포함하지 않는다. source revision이나 실제 후보 관찰이 달라지면 별도 내용SHA 파일이 생기며 이전 초안을 보존한다. UID 후보 목록은 두 창을 합쳐 기록하므로 healthcheck가 다른 UID를 추가한 경우 새 후보 관찰로 남을 수 있다.

publication은 private temporary file을 fsync한 뒤 link로 생성하며 기존 파일을 overwrite하지 않는다. 동일 목적지의 사용자 편집, 권한/소유권·symlink/hardlink·크기·읽는 중 metadata 변경은 고정 오류로 중단한다. directory/file permission을 자동 repair하지 않는다. 프로세스가 publication 중 강제 종료되어 hardlink/temp가 남는 경우도 자동 수리하지 않고 다시 검토한다. 유효한 이전 초안을 현재 승인으로 승격하지 않는다.

쓰기 범위는 공통 private directory/activation.lock과 초안 directory/file뿐이다. 기존 preflight/facts reports, key/environment/step10 receipt를 보존한다. source gate는 accepted contract·facts 인수와 전체 tracked source hash를 요구한다. DB 조회·Docker/HTTP allowlist는 d4b를 재사용하며 새로운 production exec/SQL/network operation을 추가하지 않는다. schema/API/role/HBA/network·PKI/DSN·authority를 수정하지 않고 실제 공급이나 cutover를 수행하지 않는다.

새 검증27개는 정책/required field 추출, null/후보 경계, 기존 SupplyPlan 거부, no key/volume content IO, 새 관찰과 old report 미사용, acceptance/source gate, metadata drift, private mode/idempotency, 사용자 편집/link/mode/size·publication race 거부와 버전 보존을 포함한다. d3/d4b 기존63개 회귀도 통과했다. JSON Schema 테스트 의존성은 기존 requirements와 서버 설치 상태를 사용하며 새 패키지를 추가하지 않는다. 사용자 서버 로그에서 테스트90개와 private 초안 prepared 저장을 인수했다. 내용 SHAe496c0142a0c8100c7ff1022d2bdbb1b2bcea46714d6a9ead36fe9b04d32b4d9이며 미확정40개를 유지한다. 상세는 [d4c 인수 기록](../progress/20261007-step11b3c3d4c-production-supply-review.md)에 있다.

후속은 생성 결과를 기준으로 supply 위치·유지보수 실행 identity/source·PKI·snapshot 범위를 구체화하고 실제 UID mapping/physical topology 확인을 진행하는 것이다. 검토되지 않은 null을 일괄 fixture 값으로 대체하지 않는다. 현재 credential HTTP API·full production restore fence·business runtime·schema9는 활성화하지 않는다.
