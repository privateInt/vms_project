# 11-C2 자격증명 버전 메타데이터 조회·폐기 HTTP

상태: 구현·로컬 검증·서버 파일 적용/격리 검사 인수 완료 · 운영 활성화 전

## 기준

사용자 제공 simsys4090/sh_test 출력에서 11-C1 인수 기록 패치 applied/written6/pending0을 확인했다. 서비스 재시작·runtime 활성화·DB schema 변경은 없었고 적용 이력은 var/patch-backups/step11c1-notes-9zlwd4su다. 이번 패치는 manifest SHA `c1203ea00b17c1622ad0ba28c45fc23f5a17c147dcba256c729a100c9b262604`와459개 기준 파일을 사용한다.

기존 C1 native Docker 인수 revision `35844b90e22ccef2ebead29f7486a7dac1c20ab002be1b89c37250a6e116fe6c`의 Go170/494·Python7 PASS를 유지한다. 새 C2 소스가 그때 실행됐다고 표시하지 않는다. 백업 추가 설계·검토를 제외하라는 사용자 결정을 유지한다.

## 변경

GET/DELETE exact credential version 경로를 명시적 통합 구성요소로 구현했다. TLS·trusted management principal·transactional MANAGE authorizer·concrete CredentialStore·usage guard를 모두 요구하고 현재 main과 active OpenAPI에는 등록하지 않는다.

새 GetVersionMetadata는 실제 scope/device와 지정한 버전에 대한 MANAGE 권한을 검사하며 안전한 메타데이터만 SELECT한다. active/revoked 이력과 부모 논리 삭제 후 이력을 읽되 참조·복호화·연결 허용 상태를 주장하지 않는다. 전체 작업 lease·실제 writer 역할/접속 binding 확인을 보존하고 예산을 예약하지 않는다.

DELETE는 기존 RevokeVersion의 lock·사용 보호·논리 폐기·재생을 유지한다. nil guard·force override·자동 unused 구현은 없다. exact int64 경로·strict v1/device JSON·idempotency·query/조건 헤더·8초 제한·safe receipt/errors를 검사했다. C1 쓰기의 TLS/주체 확인을 같은 내부 helper로 공유했고 C1 회귀 검사를 유지했다. SQL·schema·역할 권한·암호화 알고리즘·Compose는 변경하지 않았다.

## 로컬 검증 — 2026-10-08

| 검사 | 결과·범위 |
|---|---|
| 전체 Go 모듈 race | 상위130개·하위510개 PASS, DB/특수 native fixture 미설정 skip90개는 native 성공으로 세지 않음 |
| 관련 app / contracts | 29/263 · 23/76 PASS, 새 HTTP8개·계약3개 포함 |
| 관련 storage, DB 미지정 | 28/7 PASS; native 저장소 성공은 아래 별도 검사 |
| 실제 로컬 PostgreSQL17.11 저장소 race | 상위6개·하위5개 PASS, 메타데이터 native3개·lease 거부1개·기존 폐기 보호/최소 권한2개 |
| Python runner·관련 회귀 | 신규9개, 관련 credential runner 전체213개 PASS |
| Go vet | 전체 모듈 PASS |
| 네 플랫폼 make smoke | 62개 PASS, 임시 프로세스 정리; business runtime 검증 아님 |
| planned OpenAPI | offline schema·조회/폐기 receipt·비공개/추가 필드 거부·active 경로 미등록 확인 |

native 메타데이터 검사는 exact 버전·revoked/부모 삭제 이력·MANAGE 권한·다른 scope/principal·grant 회수·역할 오배치 거부·panic/취소 해제·예산/행 보존을 확인했다. 테스트 전용 schema8 synthetic admission guard를 사용했고 실제 writer/budget DB 역할을 검증했다. 서버 Docker 인수나 schema9 actual admitted store와 새로운 HTTP 성공 결합의 증거로 사용하지 않는다.

HTTP는 실제 TLS socket을 사용했지만 성공 manager는 synthetic이다. HTTP guard forwarding·in-use/확인불가 오류·재생·private output·미승인 concrete store의 DB IO 전 거부를 검사했다. version_http_success_uses_synthetic_store=true, metadata_store_test_admission_uses_synthetic_guard=true, native_admitted_store_version_http_verified=false를 명시한다.

## 패키지와 서버 완료 기준

코드·planned 계약·문서·manifest만 적용하는 독립 패치다. 기존 운영 API0.7.0-device-delete/schema7/registry-only-v1·키·DB·서비스·포트는 변경하지 않는다. 적용 도구는 기준 파일/새 파일 충돌을 쓰기 전에 검사하고 사용자 환경·실행 데이터를 보존한다. 패치 기준 검사·dry run/적용/재적용·보호 파일·사용자 SQL 수정/새 파일 충돌·payload hash·Python3.10 문법·개별 helper8개를 검증한다. 적용/검사 명령은 채팅에서 제공한다.

서버 검사는 기존 disposable storage runner를 재사용한다. C2 HTTP8개·계약3개·metadata4개, C1 HTTP7개·계약5개, 기존 native credential13개가 모두 PASS해야 한다. 필수 검사의 누락/skip·package 미완료·실패 후 pass는 거부한다. 전체 Go race/vet·isolated cleanup 결과를 요구하며 production services/DB/keys/API activation은 false다. 서버 도구/report의 scope는 camera_credential_version_metadata_revoke_http_native_postgresql이지만 successful native admitted HTTP 통합을 뜻하지 않는다.

## 서버 인수 — 2026-10-08

사용자 제공 출력에서 already_applied/written0/pending0·Python9개 OK와 native Docker status=passed를 확인했다. 검사 revision은 a17f3daca8e876352e30df43e350771a90aef0b4660804d3ebb7baaf5587ef2d이며 Go 상위185개·하위567개와 race/vet가 통과했다. C2 필수 HTTP8개·계약3개·metadata4개와 C1 HTTP7개·계약5개·기존 credential13개 모두 PASS다. 정확한 버전·폐기 이력·MANAGE 권한·예산 비소비·실제 역할/권한 회수·guard 전달·폐기 재생과 격리 정리를 인수했다.

HTTP 성공은 synthetic이고 메타데이터 테스트 admission도 synthetic이다. native_admitted_store_version_http_verified/native_admitted_store_http_writes_verified는 false이며 운영 서비스·DB·키·API 활성화·business runtime 변경도 false다. schema8 격리 결과를 운영 전환 증거로 사용하지 않는다. 최초 패치 적용 이력은 이번 already_applied 출력에 없으므로 추정하지 않는다. [서버 인수 기록](20261008-step11c2-server-acceptance.md)에 근거·경계·서버 결과 경로를 보존한다.

다음 단위는 11-C3: 실제 권한 정책·admitted 저장소와 credential HTTP의 격리 통합이다. 그 뒤 운영 TLS/키/역할/schema9/admission과 실행 경로 전환, ConnectionConfig·실장비 연결·영상으로 진행한다. Streamlit 브라우저 인수는 계속 보류하고 백업 추가 설계는 범위에서 제외한다.

[조회·폐기 계약](../contracts/camera-credential-versions-http.md) · [C1 서버 인수](20261008-step11c1-server-acceptance.md)
