# 단위 06-B1 — 소스 목록 이미지 빌드·교체 검사 준비

작성일: 2026-09-30 · 도구·로컬 검증 완료 · 서버 이미지 검사 대기

## 인수한 선행 결과

사용자가 제공한 06-A 서버 로그에서 패치 19개 적용과 실제 PostgreSQL 17.11 기반 격리 검사의 통과를 확인했다. 패치 백업은 `var/patch-backups/step06-8rsicnia`, 시험 프로젝트는 `vms-storage-test-8bc7712a6533`이다. 마지막 결과는 `status=passed`, `scope=camera_source_list_and_registry_native_postgresql`, `production_services_modified=false`다.

소스 목록의 정렬·전체 프로필·페이지 구분·장치 필터·기본 50/최대 200·재시작 및 토큰 교체 후 cursor, stream_profiles SELECT 회수 시 503 및 복구 후 200 검사가 통과했다. 기존 장치·소스의 원자성·멱등성·동시성·스키마 검사와 Go race 검사 및 vet도 통과했다. 시험 리소스 정리 결과를 확인했다. 이는 사용자 서버 로그에 근거하며 이번 로컬 환경에서 native Docker 검사를 실행했다는 뜻이 아니다.

운영 camera는 아직 05의 `0.3.0-source-registry` 이미지, 스키마 3이다. 06-A는 코드와 격리 검사를 반영했으며 운영 이미지 전환은 하지 않았다.

## 이번 작업 단위

작업 기준의 단계 분리 원칙에 따라 06-B를 **06-B1: candidate 이미지 빌드·격리 교체 검사**, **06-B2: 검사 결과 확인 후 운영 camera 이미지 전환**으로 나눈다. 이번에는 06-B1 도구와 필수 검증·문서·패치만 전달한다. 새 기능이나 DB 스키마 변경은 없다.

- `test_camera_source_list_image.py`: 06-A 코드 일치 확인, 운영 읽기 전용 점검, 별도 프로젝트 빌드·목록 API 검사, 같은 스키마 3에서 이미지 복귀와 데이터 보존 검사, 리소스 정리, 다음 전환용 보고서.
- `test_camera_source_list_image_unit.py`: 운영 변경 차단, 수정된 코드·다른 단계 거부, 격리 경로·비밀 생성, 빌드 실패 시 정리, 정리 실패 시 보존, 데몬 변경 거부, 오래된 성공 보고서 무효화, 운영 상태 변경 시 성공 차단.
- 운영 안내와 이 진행 기록을 추가한다. 기존 코드·Compose·마이그레이션·프로젝트 명세 및 이전 인수 기록은 바꾸지 않는다. 추가 도구는 별도 해시로 보고서에 묶는다.

초기 스키마 생성과 시험 데이터 등록은 임시 DB에서만 수행한다. 운영에서는 DB 조회와 GET 요청만 사용한다. 운영의 이미지 고정 설정, 비밀, 데이터, 기존 보고서·백업을 보존하며 다른 플랫폼 서비스에 작업하지 않는다.

## 로컬 검증

- 새 Python 도구의 실패 경계 테스트 10개 통과.
- Compose 5.5.1의 오프라인 구성 해석 통과: camera API·DB·migrate만 포함, 시험 루프백 포트, 비공개 DB 네트워크, 시험 전용 볼륨·비밀 경로, 검증된 소스의 빌드 경로 확인.
- 새 파일 4개 패치의 적용·재적용과 기존 코드 명세·환경·이전 활성화 보고서 보존 확인.
- 이번 변경은 Go 코드나 서비스 라우팅을 수정하지 않으므로 이미 통과한 06-A 전체 Go 검사를 반복하지 않는다.

현재 로컬 환경에는 Docker 엔진이 없어 실제 이미지 빌드·컨테이너 기동·이미지 복귀 검사는 실행하지 못했다. 서버에서 이번 도구의 결과를 확인해야 한다. 도구의 성공 경로를 실제 Docker에서 검증한 것으로 표시하지 않는다.

## 다음 완료 기준

서버 보고서의 `status=passed`, `scope=camera_source_list_image_native_docker`, `source_list_verified=true`, `image_only_rollback_verified=true`, `post_switch_data_preserved=true`, `isolated_resources_removed=true`와 운영 변경 없음이 확인되면 06-B2를 진행한다. 06-B2는 이 보고서의 정확한 candidate 이미지와 코드 일치를 다시 검증한 뒤 camera API만 전환한다. 스키마 3을 유지하며 운영 마이그레이션·권한 변경·DB 복구는 필요하지 않다. 실패하면 이번 이미지 검사 범위에서 먼저 해결한다.

운영 세부 사항은 [소스 목록 이미지 검사](../operations/camera-source-list-image-check.md)를 따른다. 패치 적용 명령은 작업 원칙에 따라 문서에 넣지 않고 채팅에서 별도로 전달한다.
