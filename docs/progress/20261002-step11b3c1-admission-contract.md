# 단위 11-B3c1 — camera 복원 차단·쓰기 허용 계약

작성일: 2026-10-02 · 계획 계약·합성 예제·정적 검사 서버 인수 완료

## 선행 인수

사용자 로그에서 11-B3b test2json 수정 패치 applied·written=4·pending=0, Python 17개 OK, native passed를 확인했다. source hash는 b00516b1d169377f1c0dd98eadcf2b161d7d173246aafd21265c5a183390afb3다. Go race/vet와 8 phase의 실제 read-only 키 mount·UID·별도 role DSN·DB/키 복원·3→1 budget rewind·옛 암호문/HMAC replay·옛 키 쓰기 거부·새 키 쓰기·중단 재시도·프로세스 재생성이 모두 통과했다. 임시 자원과 합성 입력 정리도 완료였다.

운영 서비스/DB/키/API는 미변경·미활성이며 production_restore_fence_implemented·business_runtime_ready=false다. [11-B3b 인수 기록](20261002-step11b3b-key-supply-restore-rehearsal.md)과 수정 기록에 결과를 반영했다. 처음 실패한 명령은 상세 로그를 받지 않아 소급 확정하지 않는다.

## 이번 완료 기준과 범위

11-B3c는 계약 → 외부 state/lease 구현 → native DB/key/marker/쓰기 guard 결합 → 운영 준비/전환으로 나눈다. 이번 결과는 **11-B3c1 계획 계약**이다. DB/키 백업과 별도인 외부 유지보수 권위·FENCED/PREPARED/OPEN·generation/CAS·키 ID의 단조 이력·새 키 규칙·쓰기 전체 lease·복원/재시도 조건을 고정했다.

신규 6개는 camera api/planned의 schema/examples/test 3개, 계약 설명·ADR 0010·이 진행 문서 3개다. 기존 297개 중 11-B3b 진행/수정 기록·ADR 0009·격리 운영 문서·문서 목록·프로젝트 명세의 6개를 갱신해 payload는 12개다. 나머지 기존 291개와 Go·SQL 1..8·OpenAPI·Compose·운영/검사 도구의 바이트·권한을 보존한다.

기록은 비밀 원문/DSN/주소/경로/force/ready 필드 없이 공개 식별자·hash·phase를 담는다. 미래 DB schema 9 marker를 계약에 명시했지만 실제 schema9 SQL은 추가하지 않았다. JSON Schema가 검사하지 못하는 membership/전이/키 재사용/rollback을 형식상 유효하지만 의미상 거부할 예제로 분리했다. 계획 shape 검사만으로 fence 구현/운영 준비를 표시하지 않는다.

## 검증

| 검사 | 결과·범위 |
|---|---|
| 새 계약 정적 검사 | Python 23개 통과. 로컬 reference·필수/미지원 필드·상태/binding·role·UUID/keyID·int64/UTC/hash·seen 집합 경계·예제 값/전이 일치 |
| 기존 접속 설정 계약 | Python 21개 통과 |
| 의존성 | 기존 api/planned/requirements-test.txt의 jsonschema 2020-12 validator를 사용. requirements 변경 없음 |
| 패치/전달 | 적용 도구 8개, 최초 12개/재실행 0개·원본 6개 백업·보호된 합성 환경/키/운영 이력 보존·변경 충돌 사전 거부·완전한 manifest·Python3.10/문서 링크·tar 경로/바이트 검사 |

정적 검사에는 host state/키/DB/Docker/실장비 IO가 없다. raw JSON 정수/중복 원문, lock/동시성·fsync/atomic replace·실제 runtime identity·실제 marker/권한·키 material fresh 여부는 후속 구현에서 검사한다. Go/SQL/프로세스/라우팅이 변경되지 않아 race/vet/smoke와 이미 인수한 native 복원 검사를 반복하지 않았다.

## 다음 단위

11-B3c2에서 strict parser와 외부 state·stable sidecar lease·create-only FENCED·expected generation/operation CAS, 원자 기록·권한/링크/경로 교체·중단/재시도·여러 프로세스 경쟁을 구현하고 인수한다. 이후 DB marker와 protected key loader 영수증·CredentialStore 전 구간 guard를 결합해 native 검사한다. 실제 운영 준비/키 공급/DB 전환은 별도 인수다.

현재 운영은 camera 0.7.0-device-delete·schema7·registry-only-v1이며 저장소 검사 대상은 schema8이다. credential_runtime_key_supply_verified·credential_restore_fencing_implemented·credential_api_implemented는 false다. 이번 계약 파일 적용은 실행 상태 전환이 아니다. 명령은 채팅에만 제공한다.

## 11-B3c1 서버 인수

사용자 로그에서 패치 applied·written=12·pending=0과 Python3.10/jsonschema4.25.1의 계약 검사 23개 OK를 확인했다. 서버 적용 기준 manifest SHA-256은 d74f1564a3e865a38cc382740bd5956c40fd853ded39e3ef316f016089eb3ece다. 서비스 재시작·DB 변경은 없었다. 다음 구현은 [11-B3c2 외부 상태/lease](20261002-step11b3c2-external-state-and-leases.md)다.
