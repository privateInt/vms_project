# 단위 09-B — 소스 논리 삭제 저장소와 스키마 6

작성일: 2026-10-01 · 코드·로컬 및 서버 PostgreSQL 격리 검사 완료

## 선행 단계와 이번 범위

사용자 로그에서 09-A 계약 패치 applied/written=5, 백업 `var/patch-backups/step09a-s5m6nnd9`를 확인했다. service_restart_performed=false, runtime_activation_required=false다. 계약 파일의 서버 적용 대기는 이 결과로 해소됐다.

AGENTS.md·작업 원칙·09-A 기록을 확인하고 **소스 논리 삭제 저장소·스키마 6·격리 검사**에 한정했다. HTTP DELETE와 엄격한 본문 디코더, 이미지 리허설·운영 활성화는 후속 단위다. 기존 운영은 `0.5.0-source-update`·스키마 5이며 단위 08의 이미지·백업·완료 기록을 유지한다.

## 변경

- SourceDelete의 내부 입력 타입·의미 검증과 SourceDeletion 결과 타입, `DeleteSource` 저장소 메서드를 추가했다. HTTP 요청에 연결하지 않았으며 기본 JSON 디코더를 DELETE API에 사용하는 것도 허용하지 않는다. 원문 숫자·중복 키 등 엄격한 HTTP 검사는 09-C의 완료 조건이다.
- 인증 주체·DELETE·정규 경로·키의 잠금과 성공 기록 조회 이후, 활성 소스를 이름 수정과 같은 행 잠금으로 보호한다. expected_version·최댓값·사용 상태를 검사하고 version+1·동일한 deleted_at/updated_at·성공 결과를 한 트랜잭션에 저장한다. 시각은 이전 updated_at보다 과거로 내려가지 않는다.
- `SourceDeleteGuard`는 잠긴 소스와 같은 트랜잭션을 받는 서버 내부 검사다. nil·unknown·잘못된 상태·오류는 SOURCE_USAGE_UNAVAILABLE, 사용 중은 SOURCE_IN_USE다. 불확실한 검사를 통과로 취급하지 않는다. 검사 및 성공 기록 저장 실패 시 부분 변경을 취소한다.
- 운영용 기본 미사용 검사·자동 승인·클라이언트 force 옵션은 추가하지 않았다. 실제 세션·소비 관계 구현도 없다. 테스트의 사용 상태는 통제된 입력이다. 다음 HTTP 단계는 등록 전용 릴리스의 전제를 확인하고 서버 내부 정책을 연결해야 하며, 연결 기능 도입 시 원자적 사용 입장 제어가 선행돼야 한다.
- 신규 마이그레이션 `0006_source_delete.sql`에 독립된 성공 기록을 추가했다. 기존 0001~0005는 바이트와 체크섬을 유지한다. runtime 권한은 소스 deleted_at의 열 UPDATE와 새 기록의 SELECT/INSERT를 추가한다. 프로필 변경·물리 DELETE·DDL 권한은 주지 않는다.
- readiness·권한 부여 및 기존 검사 fixture를 스키마 6에 맞췄다. 새 코드로 빌드한 API는 스키마 6과 새 최소 권한을 요구한다. 실행 API 버전·라우팅·OpenAPI에는 삭제 기능을 표시하지 않는다. 기존 동작의 HTTP 검사는 새 임시 DB 기준으로 수행한다.
- 서버 검사 도구의 scope는 camera_source_delete_storage_native_postgresql이다. 기존 시험 Compose를 사용하며 운영 Compose·환경·이미지 고정·기존 전환 도구는 변경하지 않는다. 프로젝트 명세와 현재 안내 문서는 이번 코드 기준으로 갱신했다.

## 검증 결과와 한계

- 로컬 Go 전체 패키지 race 검사와 go vet 통과. DB 설정 없는 실행의 통합 검사 skip을 DB 검증으로 계산하지 않았다.
- 별도 임시 PGlite 18.3에서 storage 최상위 검사 24개 통과, native 전용 9개 skip. 새 삭제 검사는 스키마 5→6·재적용·이력 보존, 삭제 결과·프로필·부모/형제 보존, GET/목록/cursor 제외, ID/채널 재사용 차단, 저장소 연결 재생성 후 삭제/POST/PATCH 응답 재생, 키·버전 충돌·최댓값·시각 역행, 사용 상태 거부·원자적 롤백·동일 키 재시도·성공 기록 제약을 확인했다.
- 별도 임시 PGlite에서 기존 app 통합 검사 통과. 장치/소스 등록·조회·목록·이름 수정, 실제 API 프로세스 재시작·토큰 교체 후 재생 등 기존 회귀를 확인했다. 삭제 API의 실제 HTTP·프로세스 재시작 검증은 아직 수행할 구현이 없으므로 09-C 이후에 진행한다.
- 실제 PostgreSQL 17.11 역할 인증·열 권한·권한 상실 후 롤백/재시도와 다중 연결 동시성은 로컬에서 실행하지 못했다. 새 native 검사는 같은 키 동시 삭제, 다른 키 동시 삭제, PATCH/DELETE 경쟁, 실제 최소 권한·물리 삭제 거부, 필요한 열/기록 권한 상실을 검증한다. 서버 Docker 검사에서는 해당 검사를 실행한다.
- 시험 Compose의 호스트 포트 미공개·tmpfs·소스 읽기 전용 구성을 확인했다. 패치 적용·재적용·충돌 시 부분 쓰기 중단, payload/압축본 해시와 기존 환경·운영 기록 보존을 확인했다.

HTTP 라우팅·프로세스 실행 구성을 바꾸지 않아 별도 smoke·운영 이미지 빌드·서비스 재시작·운영 마이그레이션을 수행하지 않았다. 기존 09-A에서 확인한 planned 검사 1건의 과거 전제 불일치는 별도 정비 항목으로 유지하며 이번 저장소 작업에서 변경하지 않았다.

## 서버 인수와 다음 단위

서버 파일 적용 후 별도 임시 Docker 프로젝트에서 검사한다. 성공 기준은 status=passed, scope=camera_source_delete_storage_native_postgresql, production_services_modified=false 및 시험 자원 정리 완료다. 아직 서버 실행 결과를 받기 전이며 이 패치 적용만으로 운영 스키마 6이나 DELETE가 활성화되지 않는다. 과거 04~08 전환 도구는 해당 리비전 전용이므로 이번 명세로 재사용하지 않는다. 명령은 채팅으로만 전달한다.

격리 검사 통과 후 다음 단위는 **09-C: 소스 삭제 HTTP 연결**이다. 엄격한 JSON·인증/키/조건 헤더·응답·오류·예약 경로와 등록 전용 사용 정책, 삭제 후 과거 응답 재생 및 재시작 보존을 연결·검증한다. 그 뒤 사전점검·이미지 리허설·실제 운영 전환으로 나눈다. 장치 삭제·세션·실장비·분석·UI는 이번에 시작하지 않는다.

## 서버 결과 인수 — 2026-10-01

사용자 실행 로그에서 09-B 패치 applied/written=23, 백업 `var/patch-backups/step09b-m7ed6end`, 재시작·활성화 없음이 확인됐다. PostgreSQL 17.11의 임시 프로젝트 `vms-storage-test-4736c14c0293`에서 status=passed, scope=camera_source_delete_storage_native_postgresql, production_services_modified=false로 종료했다. 시험 DB 컨테이너와 네트워크 제거도 확인됐다.

실제 최소 runtime 권한·권한 상실 시 롤백/동일 키 재시도, 같은/다른 키 동시 삭제·PATCH/DELETE 경쟁, 스키마 5→6/재적용·이력·프로필 보존·사용 상태 거부·시각/버전·성공 기록 제약, 기존 API 회귀·재시작·토큰 교체와 전체 race/vet 검사가 통과했다. 앞 절의 실제 PostgreSQL 미검증 항목은 이 결과로 해소됐다. DELETE HTTP는 이 검사 시점에 미연결이었으므로 해당 서버 결과를 HTTP 삭제 검증으로 간주하지 않는다.

다음 단위는 09-C HTTP 연결이며, 운영은 여전히 0.5.0-source-update·스키마 5다.
