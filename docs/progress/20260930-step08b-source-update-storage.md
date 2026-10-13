# 단위 08-B — 소스 이름 수정 저장소와 스키마 5

작성일: 2026-09-30 · 2026-10-01 서버 PostgreSQL 17.11 격리 검사 통과 확인

## 선행 단계 인수와 이번 범위

사용자 로그에서 08-A 계약 패치 applied, written=5를 확인했다. 백업은 `var/patch-backups/step08a-n5aq1_d_`, service_restart_performed=false, runtime_activation_required=false다. 08-A의 서버 파일 적용 대기는 해소됐다.

작업 시작 시 AGENTS.md·작업 원칙·최신 진행 기록을 확인했다. 이번 단위는 소스 표시 이름 수정 저장소·스키마 5·격리 검사 패키지로 한정했다. HTTP 연결과 운영 전환은 포함하지 않는다. 현재 운영 기준은 07에서 인수한 camera `0.4.0-device-update`와 스키마 4다.

## 구현한 내용

- SourceUpdate의 typed 입력과 이름·버전 검증을 추가했다. 원문 JSON 정수 표기·중복 키·미지 필드 등을 검사할 HTTP 디코더는 08-C에서 구현한다.
- UpdateSource는 멱등 범위를 먼저 잠그고 성공 기록을 재생한다. 새 수정은 활성 소스 행 잠금과 expected_version 조건으로 이름·version·updated_at을 변경하고 전체 소스 응답을 같은 트랜잭션에 기록한다.
- 동일 키의 다른 요청, 버전 충돌, 삭제·미존재, 버전 최댓값을 구분한다. 같은 이름의 새 명령도 version을 증가시킨다. 실패한 명령은 성공 기록을 남기지 않으며 같은 키로 재시도할 수 있다.
- 부모·형제 소스·불변 필드·프로필 순서·primary_profile_id·생성 시각을 보존한다. 기존 POST와 장치 PATCH 재생, 소스 GET/목록·필터·cursor도 유지한다.
- 0005_source_update.sql로 source_update_requests를 추가했다. 0001~0004 원본은 변경하지 않았다. 스키마 5 readiness와 새 기록 SELECT/INSERT, video_sources의 세 열 UPDATE만 추가하는 권한 부여를 구현했다.
- 기존 마이그레이션 검사의 최신 버전 기대값을 5로 맞췄다. 미래 버전 거부 검사는 6으로 옮겼다. 기존 권한 검사는 새로 허용된 소스 이름 대신 불변 열 변경 거부를 확인한다.
- 서버 검사 도구의 범위를 camera_source_update_storage_native_postgresql로 변경했다. 임시 PostgreSQL 이미지는 운영 인수 버전과 같은 17.11 태그를 사용한다. 운영 Compose·HTTP 라우팅·실행 OpenAPI는 변경하지 않았다.

## 검증 결과와 한계

- Go 전체 패키지 race 검사와 go vet 통과. DB 설정 없이 수행한 실행에서는 DB 통합 검사가 건너뛰어졌으므로 이를 PostgreSQL 검사 결과로 취급하지 않았다.
- 임시 PGlite 18.3에서 기존 app 통합 검사 통과: 장치 PATCH와 등록·소스 생성/조회/목록·재시작·토큰 교체·재생·롤백 회귀를 확인했다.
- 별도 임시 PGlite에서 storage 통합 검사 통과: 스키마 4→5 및 재적용, 이력 보존, 소스 수정·재생·키 범위·버전/키 충돌·원자적 실패와 재시도·tombstone·시각 역행/버전 최댓값·성공 기록 제약·부모/형제/프로필 보존을 확인했다.
- 최초 storage 검사에서 미래 버전 fixture가 새 버전 5와 겹친 문제를 수정했다. 같은 초기 실행의 로컬 WASM 통신 연결 초기화 오류는 새 임시 DB의 storage 검사 재실행으로 해소됐다. 운영 DB에서 관찰한 오류가 아니다.
- 실제 PostgreSQL 역할 인증·열 권한·권한 상실 후 롤백과 다중 연결 동시성은 PGlite에서 검증하지 않았다. 해당 검사를 건너뛰지 않는 서버 Docker 검사 도구와 테스트를 포함했다. 서버 결과를 받기 전까지 통과로 표시하지 않는다.
- 시험 Compose 설정의 버전·tmpfs·호스트 포트 미공개·소스 읽기 전용 구성을 검사했다. 패치 적용·재적용, 압축본/파일 해시와 기존 환경·운영 기록 보존을 확인했다.

프로세스·HTTP 라우팅을 변경하지 않아 별도 smoke 검사나 운영 이미지 빌드·서비스 작업은 반복하지 않았다. 소스 PATCH는 현재 405 상태다. 이 패치만으로 운영 스키마가 5가 되거나 API가 활성화되지 않는다. 기존 이미지 고정·환경·운영 데이터는 유지한다.

## 서버 인수 기준과 다음 단위

서버 격리 검사에서 status=passed, scope=camera_source_update_storage_native_postgresql, production_services_modified=false를 확인해야 한다. 검사는 별도 프로젝트·tmpfs DB만 사용하고 종료 시 정리한다. 사용자 실행 명령은 채팅으로만 전달한다.

서버 검사 통과 후 **08-C: 소스 표시 이름 수정 HTTP 연결**을 진행한다. 엄격한 원문 JSON 검증·인증/멱등 헤더·성공 및 오류 응답·예약 경로·재시작 재생을 계약과 연결하는 단위다. 운영 전환은 이후 사전점검·격리 리허설·활성화로 나눈다. 프로필 수정·삭제·장치 연결·UI는 이번에 시작하지 않는다.

## 서버 인수 — 2026-10-01 확인

사용자 로그에서 08-B applied/written=24, 백업 `var/patch-backups/step08b-inoz1s8s`를 확인했다. 파일 적용은 서비스 재시작·운영 활성화를 수행하지 않았다.

검사 프로젝트는 `vms-storage-test-7b812c2ab795`, 실제 DB 엔진은 PostgreSQL 17.11이다. 최종 status=passed, scope=camera_source_update_storage_native_postgresql, production_services_modified=false다. 임시 DB 컨테이너와 네트워크 정리도 확인했다.

소스 runtime 역할의 열 단위 권한·불변 필드/프로필 보호·권한 상실 후 롤백/재시도, 스키마 4→5 이력 보존, 동일/다른 키 동시 수정, 버전·키 충돌·tombstone·최댓값·기록 제약이 모두 통과했다. 기존 장치 PATCH·소스 생성/조회/목록·실제 API 재시작/토큰 교체 회귀 및 전체 Go race/vet 실행도 통과했다. 본문에 기록한 전달 당시 서버 대기는 이 결과로 해소됐다. 운영 스키마 5 활성화를 뜻하지 않는다.

다음은 08-C 소스 PATCH HTTP 연결이며 [08-C 기록](20261001-step08c-source-update-http.md)을 따른다.
