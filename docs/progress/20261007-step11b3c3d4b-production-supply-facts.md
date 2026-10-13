# 단위 11-B3c3d4b — 운영 공급 계획용 사실 조사

작성일: 2026-10-07 · d4a 공급 계약 인수 완료 · 운영 사실 조사 서버 인수 완료

## 선행 인수

사용자 simsys4090/sh_test 로그에서 d4a patch written12/pending0, backup=var/patch-backups/step11b3c3d4a-n0lgq9a1, 계약57개(공급34+admission23)와 기존 공급 점검31개 OK를 인수했다. 서비스 재시작·runtime 활성화·schema 수정은 false다. 소스 SHA 8ab00aec97ebbc80d90f4536a9c2ad94304ac5d535c312ed0bffb6819e34b85f / tracked410개를 이번 delta 기준으로 사용한다. raw 서버 private report를 새로 읽었다는 주장은 하지 않는다.

최신 운영 사실은 d3 사용자 로그의 schema7/API0.7.0-device-delete/registry-only-v1, TLS off, credential roles·key mount 부재, key metadata_valid0700/0600이다. d4a는 계획의 정적 계약만 인수한 것이므로 이를 준비 완료나 운영 승인으로 표시하지 않는다.

## 이번 결과

[읽기 전용 조사](../operations/camera-credential-supply-facts.md)를 src/infra/tools에 추가했다. 기존 source/image/API/DB 점검을 재사용하면서 키 owner UID/GID, 두 시점의 daemon-host process UID/GID, data volume의 선언된 host 경로, 소유 internal network의 현재 subnet/address를 수집한다. 보안 선언·namespace와 미검증 mapping을 함께 기록한다. 원본 키/DB volume의 내용은 읽지 않고 정적 SupplyPlan 파일도 생성하지 않는다.

Moby 구현을 확인해 top 조회에 필요한 PID 열을 포함했고, 보고서에서는 PID·command·환경을 제외했다. 정상 healthcheck/worker가 process identity 목록을 바꿀 수 있어 두 창의 차이를 관찰로 남긴다. daemon UID를 container UID나 승인한 runtime UID로 자동 채택하지 않는다. volume 경로 문자열과 IP 관찰도 physical topology·고정 source 승인을 뜻하지 않는다.

private facts report는 기존 preflight report를 보존한다. 정상 완료는 inspected/plan_state=incomplete/readiness=blocked다. source/환경/receipt/key/container/volume/network 변경은 실패로 처리하며 고정 실패 stage와 code만 기록한다. production modification·키 material read/load·admission 생성·HBA 변경·credential API/업무 runtime 활성화는 모두 false다.

## 검증

새 failure-boundary32개 + 기존 inventory31개 = 63개 OK, 공급/admission 계약57개 회귀 OK다. exact read allowlist·추가 exec/network mutation 거부·PID header/숫자/range·소스 gate·키/volume 미읽기·IPv4/IPv6/peer/subnet 일치·metadata drift·transient healthcheck 관찰·누락 키 owner=null·secret-safe failure stage·private report/재실행/기존 report·입력 보존을 검증했다. 로컬 Linux ps의 실제 숫자 형식을 추가 확인했다. Python3.12/jsonschema4.26 환경이며 서버 Python3.10/jsonschema4.25 인수는 사용자 실행으로 확인한다. 새 의존성은 추가하지 않는다.

accepted baseline410개 전체와 payload hash, dry-run·백업 적용·재실행, 사용자 편집/새 경로 충돌 거부, protected env/key/authority sentinel 보존, helper8개를 패키지 검사에 포함한다. Go/API/SQL/Compose/기존 inventory/계약 원본은 변경하지 않아 기존 native/race/vet/복원/재개 인수를 유지한다. 로컬 Docker가 없어 새 운영 top/network/volume 관측 성공이나 실제 host UID·IP 값을 주장하지 않는다.

## 다음 단위

사용자 simsys4090/sh_test 실행에서 written8/pending0, backup=var/patch-backups/step11b3c3d4b-59qw5c59, 테스트63개 OK와 status=inspected/plan_state=incomplete/readiness=blocked/activation_allowed=false를 인수했다. source SHA는 0e8a55880d8a40e6802260f8b2791c7db046741c309c75f6ed2cd72610ec468e다. 실제 숫자 top·daemon 보안 선언·volume/network 조회는 이 서버 로그로 인수했다.

| 항목 | 서버 관찰 | 한계 |
|---|---|---|
| source key | owner1006:1007·0700/0600 | 본문/무결성 미읽기 |
| API process | daemon-host65532:65532·두 창 동일·각1개 | container UID mapping/actual execution receipt 미검증 |
| DB process | daemon-host999:999·두 창 동일·각7개 | server UID 승인값으로 자동 채택하지 않음 |
| daemon | rootless=false·userns remap=false·두 container UsernsMode 빈 문자열 | mapping/host topology 직접 증명 아님 |
| DB volume | vms-project_camera-data; /media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data | 선언 경로만 조회; 내부/실제 mount/backup topology 미검증 |
| storage network | internal·192.168.96.0/20·gateway192.168.96.1; API192.168.96.3/20·DB192.168.96.2/20·다른 peer0 | 현재 unpinned 관찰·source 승인 미완료 |

모든 production modification, key material read/load, admission 생성, HBA/environment/network 변경, credential API/업무 활성화는 false다. schema7/TLS off/credential roles·key mount 부재의 기존 blocker11개는 유지된다. raw private report를 직접 읽었다는 주장은 하지 않고 사용자 JSON을 근거로 기록한다.

다음 [d4c 검토 초안](20261007-step11b3c3d4c-production-supply-review.md)에서 현재 사실을 새로 조회해 계약 필드와 연결한다. 관측되지 않았거나 검증되지 않은 선택은 null/후보로 남긴다. runtime key/DSN/CA 사본, authority bootstrap/lock receipt, schema9 cutover, 전체 production restore fence, credential HTTP API·실장비/영상은 후속이다. Streamlit browser acceptance는 deferred이며 중계를 추가하지 않는다. 이번 patch/조회 명령은 채팅에서만 제공한다.
