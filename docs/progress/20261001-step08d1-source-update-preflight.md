# 단위 08-D1 — 소스 수정 운영 전환 사전점검

작성일: 2026-10-01 · 사전점검 도구·로컬 검증 완료 · 실제 서버 점검 결과 대기

## 08-C 서버 격리 검사 인수

사용자 로그에서 08-C 패치 applied/written=22를 확인했다. 백업은 `var/patch-backups/step08c-fheqyhhb`이며 서비스 재시작·운영 활성화는 수행하지 않았다.

`vms-storage-test-d48350257cbc`의 PostgreSQL 17.11에서 Go race 검사와 vet가 통과했다. 소스 PATCH의 엄격한 입력·정수 토큰·헤더·오류 순서·예약 경로, 전체 소스/프로필 응답, 버전·키 충돌·버전 소진·tombstone을 확인했다. 부모/형제 소스·POST 및 장치 PATCH 재생·목록/cursor/필터가 유지됐다.

실제 API 프로세스 재시작·토큰 교체 후 과거 성공 응답 재생과 최신 상태 보존, runtime 권한 회수 시 PATCH/readiness 503·전체 롤백·권한 복구 후 같은 키 재시도가 통과했다. 기존 저장소의 스키마 업그레이드·열 단위 권한·동시 요청 및 장치/소스 API 회귀도 통과했다.

최종 결과는 status=passed, scope=camera_source_update_http_native_postgresql, production_services_modified=false다. 시험 DB 컨테이너와 네트워크 정리를 확인했다. [08-C 기록](20261001-step08c-source-update-http.md)의 전달 당시 서버 검사 대기는 이 결과로 해소됐다. 운영 전환을 수행한 결과는 아니며 운영 기준은 마지막으로 인수한 07의 `0.4.0-device-update`와 스키마 4다.

## 이번 범위

새 `src/infra/tools/inspect_camera_source_update.py`는 운영 상태를 읽기 전용으로 점검한다. 이번 패치는 도구·해당 Python 테스트·이 문서의 3개 파일만 추가한다. 서버에서 검사한 08-C 프로젝트 명세와 기존 모든 파일의 해시를 유지하며 새 파일은 패치 명세로 검증한다. 보고서에는 점검 도구 자신의 해시도 기록한다.

Docker는 프로젝트·컨테이너·볼륨 조회, 현재 Compose 구성 조회와 고정 READ ONLY SQL만 허용한다. HTTP는 readiness·platform·소스 목록 GET만 사용한다. 빌드·컨테이너 생성/정지/재시작·마이그레이션·권한 부여·DB 백업/복원·API 변경 요청을 실행하지 않는다.

로컬 쓰기는 앞선 전환 도구와 공유하는 activation 잠금 및 `var/camera/source-update-preflight.json` 보고서다. 기존 환경·비밀 파일을 생성하거나 고치지 않는다.

## 확인 항목

- 08-C 코드 버전 0.5.0-source-update, 스키마 5 저장소 리비전, 소스 수정 구현 표시와 프로젝트 명세에 기록된 모든 파일의 SHA-256.
- 로컬 Unix Docker, vms-project의 실행 중인 camera API/DB, 기존 영속 볼륨의 소유권과 실제 마운트·DB health.
- 07 완료 기록 `device-update-activation.json`의 activated/completed·스키마 4·device_update_activated 및 현재 API/DB 이미지 일치. 현재 Compose의 camera 이미지도 실행 중인 ID로 고정돼 있어야 한다.
- 기존 비밀 디렉터리/파일 소유권·권한·DSN 형식, 실제 camera 컨테이너의 읽기 전용 runtime DSN 마운트.
- 운영 API 0.4.0-device-update, P1_DEVICE_UPDATE 단계와 장치/소스 등록·소스 목록·장치 수정 기능 표시, readiness·목록 GET 성공.
- PostgreSQL 17, 기존 마이그레이션 0001~0004의 이름·순서·체크섬 일치, source_update_requests 테이블 부재. 이미 스키마 5이거나 중간 상태이면 중단한다.
- migrator/runtime 역할의 관리자 권한 여부와 runtime 외 동시 DB 클라이언트. 장치·장치 생성 기록·소스·프로필·소스 생성 기록·장치 수정 기록의 6개 건수를 수집한다.
- DB 크기와 호스트 백업 경로 여유 공간. 최소 기준은 DB 크기의 2배와 64 MiB 중 큰 값이며 실제 덤프 크기나 복원 성공을 보장하는 값은 아니다.
- 점검 전후 컨테이너 ID/이미지/시작 시각/재시작 횟수, 환경·비밀·07 완료 기록·08-C 명세·점검 도구의 해시 일치.

건수는 업무 요청이 계속 가능한 상태에서 조회한 값이다. 이 단계는 운영 쓰기를 차단하거나 백업을 만들지 않는다. 이름·프로필 원문·토큰·DSN·비밀번호를 보고서나 표준 출력에 남기지 않는다. 환경/비밀 해시·컨테이너/데몬 식별자는 0600 개인 보고서에만 저장한다.

잠금을 획득하면 이전 보고서를 running으로 바꾸고 실패·중단 시 failed로 무효화한다. 다른 작업이 잠금을 잡고 있으면 보고서를 덮어쓰지 않는다. 오류는 상세 Docker 출력 대신 고정 코드로 표시한다. 성공 보고서만으로 운영 전환을 허가하지 않으며 후속 검증에서 상태를 다시 확인한다.

## 로컬 검증

- Python 검사 25개 통과: 허용된 읽기 명령만 실행, 빌드/재시작/삭제/임의 SQL 차단, 스키마 4 이력·체크섬·API·완료 기록·이미지·마운트·역할·다른 클라이언트·6개 건수·여유 공간 불일치 시 중단.
- 점검 도중 환경·비밀·컨테이너 변경, 코드 변경·심볼릭 링크, 공유 잠금 충돌, 이전 성공 보고서의 실패/중단 무효화, 보고서 0600, 출력에서 비밀/개인 해시 제외를 확인했다.
- 임시 PGlite의 스키마 4에서 고정 읽기 전용 SQL을 실행해 마이그레이션 4개·건수 필드 6개·소스 수정 테이블 부재의 결과 구조를 확인했다. 실제 PostgreSQL 17/Docker의 운영 사전점검은 서버 실행 결과로 인수한다.
- 실제 08-C 프로젝트 명세 검사 통과. 패치 적용·재적용·충돌 시 사전 중단·새 파일/압축본 무결성과 기존 코드·명세·환경·운영 활성화 기록 보존을 확인했다.

Go·HTTP·DB 마이그레이션 코드를 변경하지 않아 이미 통과한 전체 Go/DB 검사와 smoke를 반복하지 않았다. 운영 이미지 빌드·서비스 전환도 수행하지 않았다.

## 서버 결과와 다음 단위

성공 scope는 camera_source_update_preflight다. running_api_version=0.4.0-device-update, target_api_version=0.5.0-source-update, schema_version=4, target_schema_version=5, production_services_modified=false, source_update_activated=false를 확인한다. 현재 건수·공간·이미지는 사용자 서버 실행 결과로 확정한다.

통과 후 다음 단위는 **08-D2: 스키마 5 업그레이드·복구 격리 리허설**이다. 운영 DB 변경과 이미지 전환은 리허설 이후 별도 단계다. 기존 스키마 4 이미지만 되돌리는 복귀나 자동 운영 DB 복원은 가정하지 않는다. 적용·실행 명령은 채팅으로만 전달한다.
