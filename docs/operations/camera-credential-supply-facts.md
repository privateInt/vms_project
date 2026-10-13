# 운영 공급 계획용 사실 조사 — 11-B3c3d4b

도구는 src/infra/tools/inspect_camera_credential_supply_facts.py다. d4a 정적 계약 서버 인수와 기존 d3 schema7 registry 점검을 전제로, 공급 계획 검토에 필요한 관찰값을 수집한다. SupplyPlan, approved profile/receipt, 운영 비밀·authority는 생성하지 않는다. 실행 명령은 전달 채팅에 제공한다.

| 조사 항목 | 보고되는 사실 | 미검증·미확정 경계 |
|---|---|---|
| 기존 운영 상태 | d3 점검을 새로 실행한 결과: 인수 image/API/schema7·READ ONLY DB·키 metadata | credential API·schema9·실제 key/endpoint/authority binding |
| 소스 키 | 기존 no-follow stat의 숫자 owner UID/GID·0700/0600 | 본문·hash·암호학적 무결성 미읽기; 누락 시 owner=null |
| 프로세스 | 정확한 container ID에 한정한 숫자 PID/EUID/EGID 조회의 두 관찰 시점; 보고서에는 PID 없이 UID/GID 목록·개수 | docker-daemon-host namespace의 관찰이며 container 내부 UID mapping/주 프로세스 identity 미검증 |
| daemon 보안 선언 | SecurityOptions의 rootless/userns 선언 여부, container UsernsMode | 매핑의 실제 확인·host 경로가 로컬 filesystem인지 여부 |
| DB data volume | 소유 volume·고정 container 경로·daemon이 선언한 절대 host 경로 | 경로 내부 미탐색; 실제 host mount/backup snapshot topology 미검증 |
| storage network | project 소유 internal bridge·subnet/gateway·API/DB의 현재 address/prefix·다른 peer 개수 | 현재 주소는 unpinned observation이며 미래 runtime/maintenance source나 endpoint 승인값이 아님 |

Docker top의 container process 필터에는 PID 열이 필요하므로 숫자 pid/euid/egid만 요청한다. parser는 정확한 header·세 숫자·범위·중복 PID·출력 크기를 검사하고 PID를 버린다. username·command line·환경은 top으로 요청하지 않는다. DB worker나 healthcheck가 프로세스 개수/UID 목록을 바꿀 수 있으므로 두 창의 개수·UID 목록과 일치 여부를 함께 보고한다. identity 목록이 달라도 실제 execution UID를 검증했다고 표시하지 않는다.

실행 Docker는 local Unix endpoint와 소유 project/container/volume를 확인한다. 기존 inventory allowlist 외에 검토된 exact container ID의 numeric top, 고정 SecurityOptions 조회, 두 peer가 같은 ID로 붙은 소유 network inspect만 추가 허용한다. 신규 exec·임의 ps column·전체 info·network create/connect·restart·환경 override·입력/출력 redirect는 거부한다. 기존 고정 READ ONLY SQL 이외의 DB query를 추가하지 않는다.

수집 전후 전체 source hash, 환경·step10 receipt hash, 키 metadata, daemon identity, 모든 project container snapshot을 비교한다. container의 data mount·network attachment·UsernsMode, network metadata·membership과 daemon 보안 선언도 다시 확인한다. 차이가 있으면 완료 결과를 폐기한다. 비교는 관찰 시점의 불일치를 찾는 것으로 외부 관리자의 변경을 계속 차단하거나 변경 후 원상 복귀를 모두 탐지하는 fence가 아니다.

성공은 status=inspected/inspection_completed=true/plan_state=incomplete/readiness=blocked/activation_allowed=false, exit0다. unresolved_inputs는 container UID mapping·maintenance UID/group·고정 접속 주소·PKI·DSN 공급·원본 키 무결성/사본·authority/lock receipt 위치·외부 HBA/control file 위치·snapshot roots/실제 backup topology를 남긴다. 경로·UID·IP를 fixture 값으로 채우거나 승인으로 승격하지 않는다.

조회 불가·소스/키/인수 불일치·위험한 metadata·topology 변경은 failed/exit1이다. 실패 report가 이전 결과를 대체하고 고정 code/failed_stage만 남기며 Docker stderr·raw 예외 detail·token/DSN/키·peer 이름은 출력하지 않는다. source와 key permission을 고치지 않는다.

쓰기 범위는 private var/camera/credential-supply-facts.json(mode0600)과 기존 activation.lock이다. 필요 시 기존 primitive로 private directory/lock을 만든다. d3의 기존 credential-supply-preflight.json은 덮어쓰지 않는다. 공급 계획·키/DSN/PKI 사본·authority·DB role/schema/HBA·환경·network·서비스를 바꾸지 않는다. 운영 schema7/API0.7 상태를 유지한다.

로컬 failure-boundary32개와 기존 inventory31개, 정적 계약57개를 통과했다. 실제 Linux numeric ps 형식도 확인했다. 로컬 Docker가 없어 새 top/network inspect 경로의 실제 서버 인수는 대기한다. 계약 자체와 기존 d3 Docker/DB 조회는 이전 서버 인수를 유지한다.

구현 확인 자료: [Docker top](https://docs.docker.com/reference/cli/docker/container/top/), [Moby top의 PID 필터](https://github.com/moby/moby/blob/master/daemon/top_unix.go), [network inspect](https://docs.docker.com/reference/cli/docker/network/inspect/), [userns UID remapping](https://docs.docker.com/engine/security/userns-remap/).
