# 자격증명 버전 메타데이터 조회·폐기 HTTP

상태: 11-C2 구성요소 구현·로컬/서버 격리 검증 인수 완료 · 현재 실행 API 미등록

## 경로와 권한

계약 원본은 [credential-versions.openapi.json](../../src/platform/camera/api/planned/credential-versions.openapi.json)이다. GET과 DELETE는 `/api/v1/credentials/{credential_id}/versions/{credential_version}`을 공유한다. ID는 1~64 ASCII 기존 형식이며 버전은 1~9223372036854775807의 정확한 양수 십진 경로 토큰이다. 0·부호·선행0·소수·지수·latest·overflow를 거부하고 float로 변환하지 않는다.

Bearer 인증 뒤 실제 TLS1.2 이상 handshake와 trusted principal의 비밀 관리 권한을 요구한다. scope/principal 헤더를 신뢰하지 않는다. 메타데이터는 공개 readiness API가 아니며 REFERENCE 권한만으로 조회하지 못한다. 저장소는 실제 scope에 속한 credential의 불변 device_id를 조회하고 exact version에 대한 MANAGE 권한을 같은 트랜잭션에서 확인한다. 다른 scope·미허용·미존재는 구분하지 않는다.

명시적 RegisterCredentialVersions는 concrete CredentialStore·trusted principal resolver·transactional authorizer·폐기 usage guard를 모두 요구한다. nil guard를 unused로 치환하지 않는다. 현재 main과 active OpenAPI에는 등록하지 않는다. 개발 registry 토큰에 비밀 관리 권한을 자동 부여하지 않는다.

| 요청 | 입력 | 성공 |
|---|---|---|
| GET | 본문 없음, query/조건 헤더 없음; 멱등 키 불필요 | 200·지정 버전의 안전한 메타데이터 |
| DELETE | application/json, 단일 Idempotency-Key, 정확한 v1/device_id 본문 | 200·폐기 메타데이터, Idempotency-Replayed true/false |

## 조회와 이력

GET은 credential_id·device_id·credential_version·created_at·폐기된 경우 revoked_at, envelope의 request_id만 반환한다. 주소·사용자명·비밀번호·암호문·키·HMAC·대상 정책·current/latest 여부·연결 준비 여부는 반환하지 않는다. 폐기된 버전과 부모 논리 삭제 후에도 권한 있는 관리자는 보존된 버전 이력을 조회할 수 있다. 이 조회는 참조 허용·복호화·비밀 전송·연결 성공을 뜻하지 않는다.

GetVersionMetadata는 전체 작업 admission lease와 별도 writer 데이터 역할 검증을 유지한다. 구현은 안전한 메타데이터 SELECT만 수행하고 비밀/요청 journal을 읽거나 암호화 예산을 예약하지 않는다. SQL READ ONLY 트랜잭션을 강제했다는 주장은 하지 않는다. trusted authorizer는 기존 계약대로 트랜잭션 변경·commit/rollback을 해서는 안 된다. 오류·panic·취소에서도 트랜잭션과 lease를 해제한다.

GET body·chunked body·query·If-* 조건 헤더를 거부한다. 별도 Content-Type이나 Idempotency-Key는 요구하지 않는다. JSON 응답의 revoked_at은 폐기되지 않은 경우 생략하며 created_at보다 이른 폐기 시각 등 불일치 receipt를 반환하지 않는다.

## 폐기 보호와 재생

DELETE 본문은 schema_version=v1과 device_id만 받는다. 64 KiB·정확한 unique key·UTF-8·짝 없는 surrogate·trailing JSON을 검사한다. force/unused/version/scope/principal/secret을 추가하면 거부한다. request 종료 시 비밀을 조회하거나 반환하지 않는다.

기존 RevokeVersion을 호출해 장치 → 자격증명 lock 순서, 실제 장치·정확한 버전 권한, 논리 폐기와 request journal, 재생을 유지한다. 신규 폐기는 supplied trusted guard가 관리 참조·예약·사용의 해제를 확인해야 한다. 사용 중이면409, 확인 불가 또는 guard 오류는503이며 강제 폐기 경로는 없다. 이미 성공한 요청의 재생은 현재 권한/admission을 다시 확인하고 원래 revoked_at을 보존한다. 실행 중 사용자는 guard 계약에 따라 같은 장치/자격증명 lock 순서를 공유해야 한다.

동일 폐기 결과 재생에서 usage guard를 다시 적용해 과거 성공을 실패로 바꾸지 않는 기존 저장소 의미를 유지한다. GET은 활성 이력과 폐기 이력을 모두 읽고 DELETE 성공 receipt는 일치하는 device/version과 revoked_at을 요구한다. 실제 managed-reference 구현은 후속이며 이 구성요소가 모든 운영 사용 관계를 발견했다고 표시하지 않는다.

## 오류와 검증 범위

| HTTP | 의미 |
|---|---|
| 400 / 413 / 415 / 422 | strict 요청·크기·media·ID/version/본문 의미 검사 실패 |
| 401 / 403 / 405 | 인증·TLS/관리 권한·허용 메서드 검사 실패 |
| GET404 / DELETE409 | 미존재·미허용·다른 scope를 CREDENTIAL_UNAVAILABLE로 통합 |
| 409 | CREDENTIAL_IN_USE·IDEMPOTENCY_CONFLICT 등 기존 폐기 충돌 |
| 503 | 권한/admission/usage/store 확인 불가·불일치 receipt |

허용한 code와 고정 message만 응답하며 private DB 오류는 버린다. no-store·request_id·nosniff를 유지한다. 모든 저장소 요청은 최대8초로 제한한다.

HTTP 성공/재생은 synthetic manager이며 실제 TLS socket과 concrete 미승인 저장소 거부를 검사했다. 실제 PostgreSQL의 새 메타데이터 검사와 기존 폐기 보호를 별도로 통과했다. 새 metadata native 검사는 schema8의 테스트 전용 synthetic admission guard와 실제 writer/budget 역할을 사용한다. schema9 실제 admitted store와 새 HTTP 성공의 결합은 미검증이다. 서로 다른 증거를 전체 운영 HTTP 통합 완료로 합치지 않는다.

서버 도구는 C2 HTTP8개·계약3개·메타데이터4개와 C1 HTTP7개·계약5개·기존 credential13개를 모두 요구한다. 필요한 native 검사의 누락/skip은 성공이 아니다. 사용자 제공 서버 출력에서 Python9개·Go185/567과 이 필수40개가 PASS했고 race/vet·격리 정리도 true다. HTTP 성공과 metadata test admission은 synthetic이며 native_admitted_store_version_http_verified는 false다. production services/DB/keys/API는 변경하지 않았다. [서버 인수 기록](../progress/20261008-step11c2-server-acceptance.md)을 따른다. 백업 추가 설계·검토는 사용자 지시에 따라 제외한다. [진행 기록](../progress/20261008-step11c2-credential-versions-http.md)을 따른다.
