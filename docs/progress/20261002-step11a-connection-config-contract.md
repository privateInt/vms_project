# 단위 11-A — 카메라 접속 설정·자격증명 참조 계약

작성일: 2026-10-02 · 계획 계약·예제·정적 검사 완료 · HTTP/DB/비밀 저장/실제 연결 미구현

## 선행 서버 결과 인수

사용자 로그에서 단위 10 완료 기록 패치 applied·written=1·pending=0, 백업 `var/patch-backups/step10-notes-vn4cprva`를 확인했다. service_restart_performed·runtime_activation_required·database_schema_modified는 모두 false다. [10 인수 기록](20261002-step10-server-acceptance.md)의 완료 문서 서버 반영 대기가 해소됐다.

운영 camera는 앞서 인수한 0.7.0-device-delete·P1_DEVICE_DELETE·스키마 7이며 최초 전환 activated와 재실행 already_activated를 마쳤다. 장치·소스 등록 관리와 양쪽 논리 삭제는 완료했고 실제 영상 수신·SourceSession·모델 실행·관제 UI는 아직 구현하지 않았다. 이번 로그는 문서 파일 적용 결과이며 새 운영 상태를 직접 조회한 결과로 확대하지 않는다.

## 이번 범위와 변경

작업 기준의 작은 단위 원칙에 따라 RTSP_PULL의 접속 메타데이터·고정 자격증명 참조 계약을 확정한다. 실제 장비 연결·ONVIF·XR·세션·비밀 backend·DB/HTTP 구현을 한 번에 묶지 않는다.

새 파일은 6개다.

- `src/platform/camera/api/planned/connection-config.schema.json`: 생성·전체 교체·삭제·안전한 메타데이터/최소 삭제 응답 스키마
- `src/platform/camera/api/planned/connection-config.examples.json`: 사설 IPv4·문서용 DNS/IPv6, NONE/고정 참조·생성 재생·교체/삭제의 합성 예제
- `src/platform/camera/api/planned/test_connection_config_contract.py`: 정적 계약 검사 21개
- `docs/contracts/camera-connection-config.md`: 소유권·필드·계획 API·멱등/version·비밀/대상 제한·교체/삭제 보호·후속 인수 기준
- `docs/architecture/decisions/0005-camera-connection-config.md`: 등록/접속/비밀 분리와 대안·영향
- 이 문서

기존 252개 파일과 프로젝트 명세·실행 OpenAPI·Go/SQL·Compose·운영 도구를 보존한다. 이전 명세의 전달 당시 검증/대기 필드는 그대로 두고 이후 서버 인수는 진행 기록으로 구분한다. 파일 패치는 서비스·DB·이미지·환경·운영 기록을 변경하지 않는다.

## 확정한 핵심 규칙

ConnectionConfig는 미삭제 source_id+profile_id당 1개, 별도 ID·version을 갖는다. 부모 장치는 소스에서 도출한다. 기존 Device/Source DTO에 접속 정보를 추가하지 않는다. 첫 adapter는 RTSP_PULL·TCP이며 입력 URL 대신 제한된 host/port/path를 사용한다. ONVIF·RTSPS/UDP·XR는 후속 확장이다.

auth는 명시적 NONE 또는 camera 내부 opaque credential_id+불변 credential_version이다. 원문 비밀·username/password·latest·외부 provider URI·키 경로·헤더·우회 옵션을 받지 않는다. 비밀은 부모 Device 권한뿐 아니라 비밀 관리 권한으로 정한 접속 대상에만 전달할 수 있다. 새 비밀/대상은 새 버전이고 기존 설정이 자동 교체되지 않는다.

일반 조회/성공 재생은 endpoint 없는 안전한 메타데이터만 반환하며 CONFIGURED·runtime_verified=false다. PUT은 endpoint/auth 전체 교체, DELETE는 사용 해제 후 논리 삭제다. 미삭제 설정은 부모 소스 삭제를 막고 실제 사용 시작은 준비 예약부터 같은 장치/소스/설정 허용 경계에 참여해야 한다. 새 기능 배포 시 기존 registry-only-v1 guard를 그대로 재사용하지 않는다.

형식 검사를 실제 연결 권한 검사로 취급하지 않는다. DNS/허용망·비밀 대상/정확한 버전·socket 고정·redirect 제한·비밀 비노출은 실제 어댑터 구현의 인수 기준이다. 멱등 지문 키·암호화/원문 입력·비밀 backend·키 교체/복원은 후속 저장소 단위의 완료 조건이다.

## 검증

- Python 정적 검사 21개 통과. $defs 참조·생성/교체/삭제/재생 예제·기존 ID 규칙·source validate 예약·명시적 인증 mode와 고정 버전·int64/port 경계·UTC calendar를 확인했다.
- 원문 비밀/URL/헤더·provider/file 경로·latest·미지원 adapter·부모/런타임/우회 필드, host userinfo/URL/zone/희귀 IPv4 표현·path query/percent escape/dot segment·응답 endpoint/비밀 주입을 거부하는 형태를 확인했다.
- 기존 실행 OpenAPI에 새 접속/자격증명 경로가 없고 현재 API 버전이 유지됨을 확인했다. 정적 검사에는 DNS·HTTP·DB·장비·비밀 resolve IO가 없다.
- JSON Schema 2020-12와 기존 requirements-test의 jsonschema 의존성을 사용했다. Python 3.10 문법·Markdown 상대 링크·신규 6개/기존 252개 바이트 보존을 확인했다.
- 패치 적용 도구 검사 8개와 전체 패키지 적용 6개/재적용 0개·기준 충돌 시 쓰기 없음, 기존 파일/환경/운영 기록의 내용·권한 보존, 프로젝트 명세·10-D2 recipe·10-D3 도구 해시 보존, payload/압축본 경로·해시를 확인했다.

Go·라우팅·SQL·운영 구성 변경이 없어 전체 Go/race/vet/smoke·Docker 리허설은 반복하지 않았다. 정적 Schema는 실수/지수 원문과 중복 JSON·인증/부모/비밀 실존·권한·암호화/HMAC·트랜잭션 경쟁·네트워크 대상/연결·실장비 호환을 검증하지 못한다. 모의 비밀 backend나 연결 성공을 인수했다고 기록하지 않는다.

## 남은 작업과 다음 단위

이번 단위는 계획 계약 전달이며 서버 파일 적용 결과는 아직 받기 전이다. 새 접속 API와 자격증명 저장/암호화·설정 영속화·사용 guard·실제 수신은 미완료다. business_runtime_ready=false를 유지한다.

다음 작은 단위는 **11-B: camera 자격증명 저장소·키 관리 기반**이다. 보호된 키 공급/분리·장치/대상 범위·불변 비밀 버전·폐기·비밀 원문 비노출·멱등 비교 키·장애/교체/백업 복원을 먼저 준비하고 격리 검증하는 것이 완료 기준이다. 설정 CRUD·운영 전환·실제 연결은 이후 독립 단위로 나눈다. 적용 명령은 채팅으로만 제공한다.
