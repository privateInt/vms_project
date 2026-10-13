# 영상 소스 논리 삭제 계약 — 단위 09-A

상태: 09-B 저장소 서버 검증 완료 · 09-C HTTP 구현·로컬 검증 완료 · 서버 HTTP 격리 검사·운영 활성화 전 · 2026-10-01

## 범위와 현재 상태

첫 삭제 범위는 camera 소유의 VideoSource 등록을 논리 삭제하는 것이다. 소스 행에 삭제 시각을 남기고 일반 조회에서 제외한다. 실제 행·프로필·요청 이력을 지우지 않으며, 장치 삭제·복원·영구 삭제·녹화 데이터 정리는 별도 기능으로 남긴다.

현재 운영은 API `0.5.0-source-update`·스키마 5다. 장치와 소스의 등록·조회·표시 이름 수정이 활성화됐다. 운영 이미지의 일반 소스 단건 경로 DELETE는 405/Allow: GET, PATCH다. 09-C 파일 적용만으로 운영 DELETE가 활성화되지 않는다. 현재 기준은 [08 완료 기록](../progress/20261001-step08-server-acceptance.md)과 [09-A 진행 기록](../progress/20261001-step09a-source-delete-contract.md)을 따른다.

기계 판독 계약은 `src/platform/camera/api/planned/source-delete.schema.json`이다. 루트는 SourceDelete 요청이고 `$defs/SourceDeleteResponse`는 별도의 삭제 결과 형식이다. 같은 폴더에 예제와 정적 검사를 둔다. 09-A 설계 기준은 보존하고 09-C의 실행 OpenAPI에는 별도 SourceDelete·SourceDeletion·SourceDeleteResponse를 추가했다. 기존 SourceResponse는 유지한다.

## 요청

| 항목 | 규칙 |
|---|---|
| 메서드·경로 | `DELETE /api/v1/sources/{source_id}` |
| 인증 | 기존 Bearer 인증과 안정된 개발용 공통 인증 주체 |
| 경로 ID | 기존 ASCII 1~64자 식별자 규칙. 정확한 소문자 `validate`는 예약 |
| 본문 | `schema_version: v1`, `expected_version` 두 필드 모두 필수 |
| Content-Type / 크기 | `application/json` / 기존 64 KiB 제한 |
| Idempotency-Key | 단일 필수 헤더, 1~128자 ASCII 표시 문자(0x21~0x7e) |
| 쿼리 | 빈 쿼리 구분자만 붙인 경우를 포함해 허용하지 않음 |
| 조건 헤더 | If-Match·If-None-Match·If-Unmodified-Since는 400. 본문의 version 조건 사용 |

```json
{
  "schema_version": "v1",
  "expected_version": 2
}
```

expected_version은 부모 장치가 아닌 소스 GET/목록의 version이다. 1~9223372036854775807 범위의 정확한 signed 64-bit JSON 정수 토큰을 받는다. 실수 표기 1.0·지수 표기 1e0·문자열·bool·null·범위 초과는 INVALID_JSON, 0·음수 정수와 필수 필드 누락은 CONTRACT_INVALID다. JSON 디코더는 필드 대소문자·중복 키·미지원 필드·잘못된 UTF-8·최상위 비객체·후행 JSON을 거부한다.

이 API는 DELETE에도 JSON 본문을 요구한다. 클라이언트·향후 프록시가 본문과 헤더를 그대로 전달하는지 HTTP 단계에서 확인한다. 본문이 없거나 전달 중 사라진 요청을 무조건 삭제로 해석하지 않는다. 빈 본문은 INVALID_JSON이다. source_id·version·deleted_at을 본문으로 직접 지정하거나 force·cascade·purge·skip_usage_check·녹화 삭제 옵션을 보내면 거부한다.

`/api/v1/sources/validate`는 기존 검증 API로 유지한다. 유효한 인증의 DELETE는 405/Allow: POST이며, 같은 예약 세그먼트로 해석되는 URL 이스케이프도 동일하다. `Validate`, `validate-1`은 일반 식별자다.

## 삭제 전 사용 관계 확인

삭제 완료는 **관리 대상의 소비 관계가 없고, 세션 정리도 끝났다고 확인한 경우**에만 허용한다. 활성·시작 중·종료 중인 세션, 사용 임대나 정리 대기 관계가 있으면 409 SOURCE_IN_USE다. 확인 정보가 없거나 오래됐거나 조회에 실패하면 503 SOURCE_USAGE_UNAVAILABLE이며 소스를 변경하지 않는다. 이 API는 사용 관계를 강제로 끊거나 비동기 정리를 시작하지 않는다. 호출자는 별도 종료 절차가 완료된 후 다시 요청한다.

09의 첫 구현·활성화는 SourceSession·소비 관계·입력 어댑터 생성 기능 자체가 없는 **등록 전용 릴리스**로 한정한다. 그 릴리스의 코드·구성에서 관리되는 사용 관계가 생길 수 없다는 전제를 검증하고 기록해야 한다. 단순히 소스 건수가 0이거나 business_runtime_ready=false라는 응답만으로 안전을 판단하지 않는다. 실제 사용 기능이 연결된 환경은 이 전제로 허용하지 않는다.

후속 연결·분석 기능은 삭제 검사와 새 사용 관계 생성 사이의 경쟁을 차단하는 계약을 먼저 구현해야 한다. 사용 시작과 삭제가 같은 소스 잠금 또는 동등한 원자적 입장 제어를 공유하고, 삭제된 소스의 새 사용은 거부한다. 원격 상태를 잠깐 조회한 뒤 무조건 삭제하거나 항상 ‘미사용’을 반환하는 대체 검사로 연결 기능을 활성화하지 않는다. 다른 플랫폼 DB를 직접 검사·수정하지 않으며, 관계 확인은 소유 플랫폼의 명시적 API·임대 계약으로 연결한다.

## 성공 결과와 보존할 데이터

새 삭제 성공은 HTTP 200과 SourceDeleteResponse다. 완료된 삭제 결과를 돌려주므로 202·204·201이나 Location 헤더를 사용하지 않는다.

```json
{
  "deletion": {
    "schema_version": "v1",
    "source_id": "camera-001-main",
    "version": 3,
    "deleted_at": "2026-10-01T04:00:00.123456Z"
  },
  "registration_state": "DELETED",
  "runtime_verified": false,
  "request_id": "example-source-delete-001"
}
```

Idempotency-Replayed는 최초 성공 false, 같은 성공 재생 true다. request_id는 현재 요청의 X-Request-ID와 같으며 매 재시도에서 달라질 수 있다. deletion과 나머지 성공 의미는 최초 결과를 유지한다. 이 응답은 등록 삭제 확인이며 미디어 수신·추론이나 영구 데이터 삭제 검증을 뜻하지 않는다.

| 대상 | 새 삭제 성공 후 |
|---|---|
| 소스 version | 정확히 1 증가. 최댓값에서는 409 SOURCE_VERSION_EXHAUSTED |
| deleted_at / updated_at | 동일한 서버 UTC 시각 T. T는 삭제 직전 updated_at보다 과거로 내려가지 않음 |
| created_at·식별자·부모·채널·이름·전송 선언 | 보존 |
| 프로필·배열 순서·position·primary_profile_id | 보존. 프로필 FK를 끊거나 행을 삭제하지 않음 |
| 부모 장치·형제 소스 | 값·version·수정 시각 보존 |
| 기존 생성·수정 성공 기록 | 보존. 소스 삭제 결과 때문에 스냅샷을 다시 쓰지 않음 |
| 녹화·분석 결과·비밀값 | 삭제하거나 수정하지 않음. 이번 API에서 반환하지 않음 |

소스 행과 `(device_id, channel_key)`의 유일성 제약은 그대로 남는다. 새 생성 키로 삭제된 source_id를 재사용하면 SOURCE_EXISTS, 다른 ID로 같은 장치/채널을 사용하면 SOURCE_CHANNEL_EXISTS다. 이전 생성 성공 키의 재전송은 아래 재생 규칙을 따른다. 자동 복원·ID/채널 재사용을 추가하지 않는다. 부모 장치 삭제의 자식 판정 규칙은 해당 계약에서 별도로 확정하며 이 작업에서 완화하지 않는다.

## 조회·재시도·경쟁 규칙

처리 순서는 인증·요청 검증 → 성공한 멱등 요청 조회 → 활성 소스 확인 → expected_version 비교 → 버전 소진 확인 → 사용 가능 여부 확인 → 삭제와 성공 결과의 원자적 저장이다. 활성 소스 확인부터 변경 완료까지 이름 수정과 동일한 소스 행 잠금으로 보호한다. 사용 관계가 도입되면 앞 절의 입장 제어도 이 경계에 결합해야 한다.

멱등 범위는 인증 주체 + DELETE + 해석된 유효 source_id로 만든 정규 경로 + 키다. PATCH·생성 POST·다른 소스의 DELETE와 키 공간은 독립이다. 토큰 교체 후에도 기존 공통 인증 주체를 유지한다. schema_version·expected_version을 명시적으로 정규 직렬화해 비교하며 객체 키 순서·동등한 문자열 이스케이프만 무시한다. 키 원문 대신 해시를 저장한다.

| 상황 | 결과 |
|---|---|
| 같은 범위·같은 유효 요청 재시도 | 최초 삭제 결과를 200으로 재생. version·시각 추가 변경 없음 |
| 같은 범위의 성공 키에 다른 expected_version | 409 IDEMPOTENCY_CONFLICT. 현재 삭제 상태보다 성공 기록을 먼저 검사 |
| 성공 기록이 없는 새 요청에서 소스 없음·이미 삭제 | 404 SOURCE_NOT_FOUND. 삭제 버전·시각을 새로 만들지 않음 |
| 활성 소스의 version 불일치 | 409 SOURCE_VERSION_CONFLICT |
| 다른 키로 같은 소스를 동시 삭제 | 하나만 성공. 이후 잠금을 얻은 요청은 404 SOURCE_NOT_FOUND |
| PATCH와 DELETE가 같은 version으로 경쟁, PATCH 먼저 성공 | DELETE는 409 SOURCE_VERSION_CONFLICT |
| 같은 경쟁에서 DELETE 먼저 성공 | 새 PATCH는 404 SOURCE_NOT_FOUND |
| 같은 키로 동시 삭제 | 한 번만 변경하고 나머지는 같은 성공 결과 재생 |
| 삭제 결과 저장 실패 | deleted_at·version·updated_at과 성공 기록을 함께 롤백 |

성공 기록만 저장하고 자동 만료시키지 않는다. 실패 응답은 저장하지 않으므로 SOURCE_IN_USE가 해소되면 같은 키·본문으로 다시 판단할 수 있다. 응답 유실·타임아웃·503에는 같은 키·같은 본문으로 재시도한다. 버전 충돌은 현재 GET 결과를 검토한 뒤 새 version·새 키로 요청한다. 서버가 최신 버전으로 자동 보정하지 않는다. 정상 성공 재생은 사용 상태를 다시 확인하거나 삭제를 다시 수행하지 않지만 인증과 요청 검증은 항상 수행한다.

삭제 후 새 GET은 404이며 목록은 삭제된 소스를 제외한다. include_deleted 조회나 복원 경로는 제공하지 않는다. 목록의 ID 정렬·부모 필터·limit과 cursor 규칙을 유지한다. 이전 cursor가 가리킨 소스가 삭제돼도 그 ID 이후부터 탐색하며, 페이지 사이의 스냅샷 일관성은 보장하지 않는다.

삭제 후에도 기존 POST 성공은 생성 당시 스냅샷을 201로, 기존 PATCH 성공은 수정 당시 스냅샷을 200으로 재생한다. 그 과거 응답의 REGISTERED는 당시 결과이며 현재 생존 상태가 아니다. 재생은 소스를 복원하지 않는다. 현재 존재 여부는 GET/목록으로 판단한다.

## 오류 계약

기존 error: {code, message, details}와 request_id 구조를 사용한다. 원본 키·비밀·내부 세션 정보를 오류에 노출하지 않는다.

| HTTP | code | 조건 |
|---|---|---|
| 400 | QUERY_INVALID | 쿼리 제출·인코딩 오류 |
| 400 | PRECONDITION_HEADER_UNSUPPORTED | 미지원 조건 헤더 |
| 400 | IDEMPOTENCY_KEY_INVALID | 키 누락·중복·형식 오류 |
| 400 | INVALID_JSON | 구문·타입·원문 정수 표기/범위·중복/미지원 필드·null·빈 본문·후행 JSON 오류 |
| 401 | UNAUTHORIZED | 인증 실패 |
| 404 | SOURCE_NOT_FOUND | 새 요청에서 소스 없음·삭제됨 |
| 405 | METHOD_NOT_ALLOWED | 구현 후 일반 단건 경로의 GET/PATCH/DELETE 외 메서드. Allow: GET, PATCH, DELETE |
| 409 | SOURCE_VERSION_CONFLICT | 활성 소스의 expected_version 불일치 |
| 409 | SOURCE_VERSION_EXHAUSTED | 일치한 version이 최댓값 |
| 409 | IDEMPOTENCY_CONFLICT | 같은 성공 키에 다른 유효 요청 |
| 409 | SOURCE_IN_USE | 관리 대상 세션·소비 관계 또는 미완료 정리 존재 |
| 413 | BODY_TOO_LARGE | 64 KiB 초과 |
| 415 | UNSUPPORTED_MEDIA_TYPE | application/json이 아님 |
| 422 | CONTRACT_INVALID | 필수 필드 누락·schema_version/경로 ID 오류·0/음수 version |
| 503 | SOURCE_USAGE_UNAVAILABLE | 미사용 상태 확인 불가·등록 전용 적용 전제 불충족 |
| 503 | REGISTRY_DISABLED / DATABASE_UNAVAILABLE | 저장소 미설정 / DB·트랜잭션 이용 실패 |

일반 경로의 검사 순서는 기존 인증 계층 다음 메서드 → 쿼리 → 경로 ID → 조건 헤더 → 키 → Content-Type·JSON → 필드 의미 → 저장소다. validate 예약 경로는 기존 라우팅을 유지한다. 저장소의 동시 오류 우선순위는 앞 절의 처리 순서를 따른다.

## 저장소·배포와 후속 완료 기준

09-B에서는 기존 deleted_at 열을 활용하고 신규 마이그레이션 0006·스키마 6에 별도 `camera.source_delete_requests` 성공 기록을 추가한다. 기존 마이그레이션이나 POST/PATCH 기록을 다시 쓰지 않는다. 추가 runtime 권한은 video_sources.deleted_at의 열 UPDATE와 삭제 요청 기록의 SELECT/INSERT로 제한하고, 기존 version·updated_at 수정 권한을 사용한다. 물리 DELETE·DDL·프로필 UPDATE/DELETE 권한은 부여하지 않는다.

삭제와 version·시각·성공 스냅샷을 같은 트랜잭션에 저장한다. 기록은 대상 행에 연쇄 삭제되는 FK를 갖지 않으며, 응답 request_id는 매 HTTP 요청에서 만든다. 등록 전용 전제 및 이후 사용 관계 보호의 확장 경계를 저장소·호출자 계약에 명시한다.

09-B 완료 기준은 실제 최소 권한으로의 논리 삭제·재생·실패 롤백, 서로 다른 삭제/수정 요청의 다중 연결 경쟁, version 최대·시각 역행 방지, 부모/형제·프로필·POST/PATCH 이력 보존, ID/채널 재사용 거부, GET/목록/cursor와 API 재시작 후 보존이다. 확인 불가·사용 중 조건에서 아무 데이터도 바꾸지 않는 검사도 필요하다. 정적 예제 통과로 이 동작을 검증했다고 간주하지 않는다.

09-C HTTP 연결 이후 별도 사전점검·이미지 리허설·운영 전환으로 나눈다. 스키마 6에서 스키마 5 이미지로만 되돌릴 수 있다고 가정하지 않으며 백업·복원과 전환 후 데이터 보존을 검증한다. 자동 운영 DB 복원은 사용하지 않는다. 이번 09-A에는 마이그레이션·권한·라우팅·실행 OpenAPI 변경이 없다.

JSON Schema 검사는 파싱된 요청/응답의 형태와 예제만 확인한다. 1.0/1e0 원문 표기, 중복 JSON 키, HTTP 전송·인증·오류 순서, 실제 사용 여부·재생·동시성·DB 권한·원자성은 후속 구현 검사 대상이다.

## 09-B 저장소 구현 상태

`DeleteSource`와 스키마 6의 source_delete_requests를 구현했다. 성공 기록은 소스 삭제 결과만 저장하며 HTTP의 request_id·헤더는 후속 09-C에서 만든다. 소스 행 잠금 안에서 호출되는 서버 내부 `SourceDeleteGuard`를 필수 검사 경계로 둔다. 검사 생략(nil)·알 수 없는 결과·검사 오류는 SOURCE_USAGE_UNAVAILABLE, 사용 중은 SOURCE_IN_USE로 종료하며 트랜잭션을 취소한다. 성공 재생은 이 검사를 재호출하지 않는다.

이번 저장소 코드에는 항상 미사용을 반환하는 운영용 기본 검사나 클라이언트 우회 옵션이 없다. 테스트의 미사용/사용 중 결과는 시나리오 입력이며 실제 세션 관측 결과가 아니다. 09-C에서 등록 전용 코드·구성 전제를 확인하고 명시적인 서버 내부 정책을 연결해야 DELETE를 노출할 수 있다. 실제 사용 관계가 있는 환경으로의 확장은 별도 계약·입장 제어 구현이 선행돼야 한다.

로컬 검증과 이후 서버에서 통과한 실제 PostgreSQL 계정 권한·동시 접속 검사는 [09-B 기록](../progress/20261001-step09b-source-delete-storage.md)에 구분했다. 이번 파일 적용과 격리 검사는 운영 스키마 5·이미지·환경을 변경하지 않는다.

## 09-C HTTP 구현 상태

실행 코드는 0.6.0-source-delete·스키마 6을 요구한다. DELETE의 엄격한 입력·오류 순서·논리 삭제 결과·최초 성공 재생과 no-store/요청 ID/멱등 헤더를 구현했다. 일반 단건 경로 Allow는 GET, PATCH, DELETE이며 validate 예약 경로는 POST를 유지한다. 실수·지수·int64 초과, 중복 키·타입·미지 필드·무효 UTF-8·후행 JSON은 400이며 필수값 누락·0/음수는 422다.

등록 전용 정책은 `NewWithStore`에서 서버 코드로만 선택한다. 현재 cmd/camera-api와 app 생성자는 등록 메타데이터·검증 경로만 설치하며, SourceSession·consumer·RTSP/WEBRTC·녹화·ONVIF 어댑터를 생성하는 구현이나 활성화 설정이 없다. 이 검토 결과를 `registry-only-v1`과 고정 capability 허용 목록으로 제한한다. 모든 런타임 기능은 planned이고 등록 기능은 implemented여야 하며, 항목 누락·추가·값 변경·미확인 모드는 미사용으로 판단하지 않는다. 클라이언트·환경 변수는 정책을 선택하거나 force로 우회할 수 없다.

이 정책은 외부 장비나 미디어 사용 상태를 감지하는 기능이 아니다. SourceSession·consumer·어댑터 생성자를 추가하는 변경은 이 등록 전용 전제를 폐기하고 저장소와 같은 소스 행 잠금에 참여하는 사용 입장 제어를 구현해야 한다. capability 표기만 바꾸거나 원격 관측만 추가해서 삭제를 허용하지 않는다. 사용 중 오류는 409 SOURCE_IN_USE, 불확실한 사용 상태는 503 SOURCE_USAGE_UNAVAILABLE로 유지한다.

[09-C 기록](../progress/20261001-step09c-source-delete-http.md)에 로컬 검사와 아직 남은 서버 검사를 구분했다. 운영 0.5.0·스키마 5에서의 전환은 사전점검·이미지 리허설·활성화로 나눈다.
