# 소스 목록 운영 이미지 전환 — 단위 06-B2

## 전제와 범위

06-A 코드와 06-B1 이미지 검사를 마친 상태에서만 수행한다. `var/camera/source-list-image-check.json`의 통과 결과, 코드 명세·검사 도구 해시, Docker 데몬, candidate·이전 camera·DB 이미지 ID를 모두 확인한다. 필요한 이미지가 없거나 검사 결과가 현재 코드와 다르면 운영 변경 전에 중단한다. 새 빌드나 이미지 다운로드를 수행하지 않는다.

운영 camera의 현재 버전은 `0.3.0-source-registry`, 전환 대상은 `0.3.1-source-list`다. 두 이미지 모두 동일한 스키마 3을 사용하며 06-B1에서 같은 DB를 유지한 이미지 복귀와 새 데이터 보존을 검증했다. 운영 DB의 마이그레이션·권한 변경·복원·재시작은 수행하지 않는다. 기존 데이터 건수는 전제하지 않으며 검사 중 정상적인 사용자 등록도 허용한다.

변경은 `.env`의 기존 camera 이미지 ID 한 곳과 camera API 컨테이너에 한정한다. 환경 파일의 다른 바이트와 권한은 유지한다. 이전 단계가 기록한 단일 이미지 설정 형식과 다르거나 중복 설정·다른 Compose 프로젝트 설정이 있으면 임의로 재작성하지 않는다. DB·model·analysis·operation 컨테이너는 변경 대상이 아니다.

## 전환 절차

도구는 명시적인 적용 옵션이 있을 때만 실행하고 기존 camera 활성화 잠금을 획득한다. 현재 서비스·환경·비밀 파일·스키마를 조회한 뒤 새로운 이미지 설정으로 해석한 API 주소와 토큰이 같은지 확인한다.

`var/camera/source-list-activation-backups/step06b2-*`에 원래 환경 파일과 컨테이너 상태, 단계별 결과를 소유자 전용으로 보관한다. 이 디렉터리는 **설정 전환 기록**이며 DB 덤프를 새로 생성하는 백업이 아니다. 기존 05 단계의 DB 백업·보고서·활성화 기록은 보존한다.

검증된 이미지 ID로 환경 파일을 갱신하고 camera API만 의존 서비스 재기동 없이 전환한다. API 교체 동안 camera 요청이 잠시 중단될 수 있다. 이후 readiness·버전·source_list capability와 실제 목록 GET 응답을 확인한다. 운영 DB에 시험 장치·소스를 만들지 않는다.

완료 전에는 DB 및 다른 서비스의 컨테이너 ID·기동 시각·재시작 횟수, 비밀 파일·코드·검사 결과, 스키마 3이 유지됐는지 다시 확인한다. 결과는 `var/camera/source-list-activation.json`과 해당 전환 기록 디렉터리의 `result.json`에 저장한다.

## 실패와 재실행

전환 요청 이후 오류가 나면 이전/새 이미지 외의 상태가 끼어들지 않았고 환경·비밀·코드·DB 스키마·다른 서비스 상태가 유지됐는지 확인한다. 이 조건이 맞으면 원래 환경 설정과 이전 camera 이미지만 복구한다. DB를 복원하지 않으므로 새 이미지가 정상 응답한 등록 데이터도 그대로 남는다. 이전 이미지의 readiness·버전까지 확인한 경우에만 `recovery=previous_image_restored`를 기록한다.

동시에 환경 파일을 수정했거나 DB·다른 서비스·코드가 변경된 경우, 또는 이전 이미지 기동 자체가 실패한 경우에는 추측해서 덮어쓰지 않는다. `recovery=manual_review_required`와 상태를 보존한다. 이때 `source_list_activated=null`은 현재 목록 API 활성 상태가 확정되지 않았다는 뜻이다. 자동 DB 복원은 모든 경우에 금지한다.

완료된 결과로 도구를 다시 실행하면 현재 이미지·스키마·목록 API를 읽기 전용으로 확인하고 `status=already_activated`, `service_restart_performed=false`를 반환한다. 재실행 응답의 백업 경로·최초 전환 정보는 이전 성공 기록이다. 환경을 다시 쓰거나 API를 다시 기동하지 않는다.

`failed` 또는 `running` 기록이 있으면 반복 전환을 차단한다. 강제 종료나 호스트 중단 후에도 기록을 임의로 지우고 다시 실행하지 않고 해당 결과와 실제 상태를 먼저 확인한다. 정상적인 실패에서 자동 이미지 복귀에 성공했더라도 실패 원인 확인 없이 반복 전환하지 않는다.

## 완료 기준

`status=activated` 또는 재실행의 `already_activated`, `scope=camera_source_list`, `source_list_activated=true`, `schema_version=3`, `migration_applied=0`, `database_container_unchanged=true`, `other_services_unchanged=true`를 확인한다. `business_runtime_ready=false`는 여전히 영상 입력·세션·분석 런타임이 이번 범위에 포함되지 않았다는 뜻이다.
