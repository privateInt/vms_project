# 단위 10-A — 장치 논리 삭제 계약

작성일: 2026-10-01 · 계약·예제·정적 검사 완료 · 저장소/HTTP 구현 및 운영 활성화 전

## 선행 단계 인수

사용자 서버 로그에서 09 완료 기록 패치 applied/written=1, 백업 `var/patch-backups/step09-notes-p_7gxko_`, service_restart_performed=false, runtime_activation_required=false를 확인했다. 단위 09의 소스 논리 삭제 구현·검사·운영 전환·완료 기록 반영까지 인수를 마쳤다. [09 완료 기록](20261001-step09-server-acceptance.md)의 문서 서버 적용 대기는 이번 로그로 해소됐다.

현재 운영 API는 0.6.0-source-delete·스키마 6이며 소스 삭제가 활성화돼 있다. 장치 삭제·업무 런타임은 미구현이다. 운영 이미지·백업·검증 범위는 09 완료 기록을 따른다. 이번 단계는 AGENTS.md·작업 원칙에 따라 장치 삭제 계약 하나로 제한했다.

## 확정한 내용

- DELETE /api/v1/devices/{device_id}에 schema_version·장치 expected_version과 Idempotency-Key를 요구한다. 최소 삭제 결과를 200으로 반환하며 새 성공에서 version+1과 동일 UTC deleted_at/updated_at을 기록한다.
- 미삭제 자식 소스가 하나라도 있으면 DEVICE_HAS_ACTIVE_SOURCES로 거부한다. 영상 수신 여부와 관계없이 미삭제 등록 행을 센다. 자식이 없거나 모두 논리 삭제됐을 때만 사용 관계 검사 후 장치를 삭제할 수 있다.
- force·cascade·자식 자동 삭제·복원·영구 삭제를 허용하지 않는다. 장치 행, 삭제된 자식 소스·프로필, ID/채널 예약과 모든 성공 이력을 보존한다.
- 장치 version은 자식 목록 버전이 아니다. 기존 CreateSource의 장치별 advisory transaction lock을 장치 삭제에서도 사용하고, 잠금 획득 후 활성 자식을 새로 조회한다. 장치 행 FOR UPDATE로 기존 장치 PATCH와도 직렬화한다.
- 소스 생성이 먼저 커밋하면 부모 삭제는 자식 존재로 거부된다. 장치 삭제가 먼저 커밋하면 새 소스 생성은 기존 409 DEVICE_UNAVAILABLE이며 새 행·성공 이력을 남기지 않는다. 등록에 있던 잠금을 무시하고 별도 잠금만 추가하지 않는다.
- 장치 ID validate는 기존처럼 유효하다. 소스 validate 예약 규칙을 장치에 적용하지 않는다.
- 성공 DELETE 재생, 다른 본문 키 충돌, 삭제 후 새 PATCH/DELETE의 404, 과거 장치/소스 POST/PATCH/DELETE 결과 보존과 복원 없는 재생, GET/목록/cursor 규칙을 명시했다.
- 등록 전용 릴리스에서만 최초 활성화를 허용한다. 실제 사용/정리 중은 DEVICE_IN_USE, 확인 불가는 DEVICE_USAGE_UNAVAILABLE이다. 향후 사용 시작과 삭제가 같은 원자적 허용 경계에 참여해야 한다.
- 후속 HTTP 단계에서 device_delete capability를 추가할 때 기존 소스 삭제 정책의 정확한 허용 목록도 함께 검토한다. 소스 삭제 기능이 계속 동작하는지를 회귀 검사에 포함한다.

상세 순서·응답·오류·동시성 기준은 [장치 삭제 계약](../contracts/camera-device-delete.md)에 기록했다. 기계 판독 스키마·예제·검사는 camera 소유의 `src/platform/camera/api/planned`에 추가했다.

## 검증과 한계

- Python 3.12.14와 기존 requirements-test.txt 범위의 jsonschema 4.26.0으로 새 정적 검사 8개가 통과했다. 요청 예제·필수 필드·int64 경계·강제 삭제/직접 자식 상태/비밀 입력 거부, 장치 ID와 validate 호환, 최소 삭제 결과·동일 성공 재생 예제·헤더, 응답 필수값·버전·UTC 달력/소수초를 확인했다.
- 날짜 검사는 표준 라이브러리로 달력 유효성을 확인한다. Python 3.10 문법 파싱도 통과했다. 이번 단계에서 사용자 서버 Python으로 검사를 실행한 결과는 아직 받지 않았다.
- JSON Schema 검사는 파싱된 값의 형태를 확인한다. 1.0/1e0 원문, 중복 JSON 키, 실제 HTTP 헤더·인증·삭제·부모/자식 잠금·사용 관계·DB 권한·원자성은 정적 검사 대상이 아니며 후속 구현 검사로 남긴다.
- 기존 CreateSource·장치 PATCH·장치 ID 검증·소스 HTTP 오류 매핑과 정책 코드를 읽어 계약 호환성을 검토했다. Go 코드를 변경하거나 새로운 동작을 실행한 것은 아니다.
- 새 파일은 계약 문서·스키마·예제·정적 검사·이 진행 기록의 5개다. 기존 210개 명세 파일과 전체 기존 파일의 바이트/권한, 실행 OpenAPI·Go·Compose·마이그레이션·프로젝트 명세·09 전환 도구를 유지한다.
- 패치 사전점검·5개 적용·재적용 무변경·충돌 시 사전 중단, payload/압축본 경로·해시와 기존 환경·운영 기록 보존을 확인했다. 관련 없는 이전 단계 전체 검사·Go/vet/smoke·DB 시험·이미지 빌드·서비스 재시작·마이그레이션은 반복하지 않았다.

이번 계약 패치의 서버 적용 결과는 아직 받기 전이다. 실행 OpenAPI와 장치 단건 라우트에 DELETE를 추가하지 않았으며, 운영 0.6.0-source-delete·스키마 6·registry-only-v1과 business_runtime_ready=false를 유지한다. 적용 명령은 채팅에서 따로 제공한다.

## 다음 단위

**10-B: 장치 논리 삭제 저장소·스키마 7와 격리 테스트**다. 별도 device_delete_requests, devices.deleted_at 최소 열 권한, 기존 장치별 잠금과의 소스 생성 경쟁 보호, 활성/삭제된 자식 판정·사용 확인 거부·원자적 롤백, 장치/소스/프로필/과거 응답 보존을 구현·검증한다. HTTP 연결과 운영 사전점검·리허설·전환은 그 뒤 별도로 진행한다. 연결·분석·UI는 이번 계약에 포함하지 않는다.
