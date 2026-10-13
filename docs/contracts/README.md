# 구현 계약 범위

계약 원본과 입력 예제는 다음 경로에 있다.

| 소유자 | OpenAPI | JSON Schema·예제 |
|---|---|---|
| camera | `src/platform/camera/api/openapi.json` | `api/schemas/SourceSpec.schema.json`, `api/examples/source-cctv.json`, `api/examples/source-xr.json` |
| analysis | `src/platform/analysis/api/openapi.json` | `api/schemas/AnalysisJobSpec.schema.json`, `api/examples/analysis-job-xr.json` |
| model | `src/platform/model/api/openapi.json` | 현재 health·manifest만 제공 |
| operation | `src/platform/operation/api/openapi.json` | 현재 health·manifest만 제공 |

## VideoSource 입력

`source_id`는 영상 소스의 안정된 식별자, `device_id`는 장치 식별자다. 재연결마다 생길 `source_session_id`와 구분한다. 현재 예제는 세션을 생성하지 않는다. 하나의 소스는 여러 스트림 프로필을 선언할 수 있고 프로필 ID는 소스 안에서 유일해야 한다.

이번 v1 입력 계약은 RTSP/PULL과 WEBRTC/PUSH를 지원 대상으로 정했다. 프로토콜 자체의 모든 사용 방식을 설명하는 제한은 아니다. XR은 `device_kind: SMART_GLASSES`, `motion_mode: MOVING`을 쓸 수 있으며 ONVIF나 PTZ를 요구하지 않는다. ONVIF·PTZ는 장치 기능이고 실제 지원 여부는 후속 어댑터가 검증한다. capabilities 객체는 필수이며 생략된 개별 boolean은 false로 해석한다.

코덱·해상도·FPS는 현재 선언값이다. 실제 SDP·RTSP 협상 결과, 디코더 지원, 대역폭 검증 결과가 아니다. 소스 검증 요청에는 URL·장치 비밀번호·ICE 자격 증명을 넣지 않는다. 후속 등록 API에서 인증 정보 참조와 어댑터별 연결 설정을 별도 계약으로 정의한다.

## AnalysisJob 입력

작업은 source와 stream profile, 고정된 template version과 model version을 참조한다. 역할별 deployment reference는 한 개로 제한한다. `desired_state`는 RUNNING/STOPPED이며 observed state나 워커 상태와 구분한다. `generation`은 1 이상이고 실제 서버의 단조 증가·동시 수정 규칙은 저장소와 조정 루프를 구현할 때 강제한다.

현재 검증 API는 참조 ID의 형식만 확인한다. 소스·모델 존재, deployment에 고정 버전이 실제 배치됐는지, 모델 입출력·이동 카메라 템플릿 호환성, target FPS의 실행 가능성은 검증하지 않는다. 성공 응답에 `resource_created`, `references_verified`, `runtime_verified`를 모두 false로 표시한다.

## 응답과 제한

검증 성공은 200, 알려지지 않은 JSON 필드·잘못된 타입·여러 JSON 값은 400, 인증 실패는 401, 본문 64 KiB 초과는 413, Content-Type 오류는 415, 의미상 계약 오류는 422다. 오류 응답에는 error code·message와 request ID, 필요한 경우 필드별 details가 있다. 알려진 필드에 대한 검증은 Go 코드가 수행하며 완전한 JSON Schema 해석기를 포함하지 않는다. 공백 이름, 중복 profile ID·역할 등 추가 의미 규칙도 서버에서 확인한다.

위 validate API는 저장·제어 명령이 없는 stateless 경로다. 장치 API는 단위 03부터 별도로 저장·조회·멱등 처리를 제공한다. 07-C는 [표시 이름 수정](camera-device-update.md)의 version 조건과 멱등 재생을 구현했다. 장치 논리 삭제의 현재 상태는 아래 10-C 설명을 따른다. source session, frame reference, timestamp/timebase, analysis run/lease, event, model deployment의 계약은 아직 구현되지 않았다.

## 장치 등록·조회와 후속 소스 계약

[카메라 등록 계약](camera-registry.md)의 Device 생성·조회·목록을 단위 03에서 구현했다. 실행 명세는 camera OpenAPI의 DeviceCreate/Device/DeviceResponse/DeviceList다. `api/planned`에는 초기 설계 기준을 보관한다. 소스 생성·단건 조회는 05, 목록 조회는 06에서 운영 활성화했다. 기존 validate API 요청·응답은 유지하며, 실제 등록은 별도 경로를 사용한다. 연결 설정·세션·프로필 수정은 후속 단위다. 소스 논리 삭제는 아래 09-C 상태를 따른다. [장치 API 안내](../operations/camera-devices.md)에 응답·오류·DB 연결 기준을 기록했다.

## 소스 표시 이름 수정

08-A의 [소스 수정 계약](camera-source-update.md)은 display_name만 변경하고 부모 관계·전송 선언·프로필을 보존한다. 08-B의 스키마 5 저장소는 PostgreSQL 17.11에서 검증됐다. 08-C는 엄격한 SourceUpdate 디코더와 PATCH 라우팅·응답을 연결했다. 새 코드의 명세는 camera OpenAPI의 SourceUpdate/SourceResponse이며 `api/planned`에는 설계 기준을 보관한다. 08-C 코드의 버전은 0.5.0-source-update다. 08-D3 전환과 완료 기록 적용을 마쳐 이후 단위 09 운영 전환을 마쳐 현재 운영은 0.6.0-source-delete·스키마 6다.

## 소스 논리 삭제

09-A의 [삭제 계약](camera-source-delete.md)은 소스·프로필·이력을 보존하는 논리 삭제와 버전·재시도·사용 관계 보호 규칙을 정의한다. 09-B는 저장소·스키마 6·필수 사용 검사 경계를 구현했다. 저장소의 PostgreSQL 17.11 격리 검사는 통과했다. 09-C는 엄격한 DELETE 입력·응답·등록 전용 사용 정책과 HTTP 검사를 연결했다. 새 코드 버전은 0.6.0-source-delete이며 실행 OpenAPI에 SourceDelete/SourceDeletion/SourceDeleteResponse를 추가했다. 서버 HTTP 격리 검사와 운영 전환을 완료했다. 최신 근거는 [09 인수 기록](../progress/20261001-step09-server-acceptance.md)이다.

## 장치 논리 삭제

10-A의 [장치 삭제 계약](camera-device-delete.md)에 따라 10-B에서 DeviceDelete·DeviceDeletion·DeleteDevice 저장소와 스키마 7을 추가했다. PostgreSQL 17.11 서버 격리 검사는 통과했다. 10-C는 DELETE /api/v1/devices/{device_id}·엄격한 원문 JSON/헤더 검사·최소 삭제 응답·오류·등록 전용 사용 정책을 연결했다. 미삭제 자식 확인과 소스 생성의 공통 잠금, 성공 이력 재생과 원자적 삭제는 10-B 구현을 사용한다. 장치 ID validate는 일반 ID이며 소스 예약 경로 규칙과 다르다.

개발 버전은 0.7.0-device-delete·스키마 7이다. 실행 OpenAPI의 DeviceDelete/DeviceDeletion/DeviceDeleteResponse와 계약 예제의 정적 검사, 실제 로컬 API 프로세스·임시 DB의 직렬 흐름과 소스 삭제 회귀 검사를 통과했다. 장치/소스 삭제는 동일한 정확한 등록 전용 capability 허용 목록을 사용한다. 새 기능·미확인 사용 상태는 거부하며 실제 관리 사용 관계를 도입하면 잠금과 결합된 입장 제어로 교체해야 한다.

대상 서버의 10-C HTTP 격리 인수는 대기 중이다. 파일 적용으로 운영 0.6.0-source-delete·스키마 6이나 검증된 09 이미지가 바뀌지 않는다. [10-C 기록](../progress/20261002-step10c-device-delete-http.md)을 따른다.
