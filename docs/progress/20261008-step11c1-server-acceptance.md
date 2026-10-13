# 11-C1 서버 인수: 자격증명 생성·교체 HTTP 구성요소

상태: 패치 적용·서버 격리 검사 인수 완료 · 운영 HTTP 활성화 전

## 근거

2026-10-08 사용자가 제공한 simsys4090/sh_test 실행 출력에 근거한다. 11-C1 패치는 applied·written17·pending0이며 서비스 재시작·runtime 활성화·DB schema 변경은 없었다. 적용 이력은 var/patch-backups/step11c1-v5y8j1v6이다. 새 백업 검토는 추가하지 않았다.

검사 대상 manifest SHA는 `35844b90e22ccef2ebead29f7486a7dac1c20ab002be1b89c37250a6e116fe6c`다. 서버 Python runner unit7개가 OK였다. native Docker 검사는 status=passed, scope=camera_credential_write_http_native_postgresql, project=vms-credential-storage-test-f0f750ddf7ee로 끝났다.

| 결과 | 서버 증거 |
|---|---|
| Go race / vet | 둘 다 true |
| Go 상위 / 하위 검사 | 170 / 494 PASS |
| 필수 기존 자격증명 검사 | 13 PASS, native 역할·동시성 true |
| 필수 HTTP / 입력 계약 검사 | 7 / 5 PASS |
| actual HTTP TLS / strict secret input | true / true |
| 안전한 receipt·오류 / unadmitted store 거부 | true / true |
| 암묵적 route 활성화 거부 | true |
| 격리 자원 정리 | true |

170/494는 격리 환경에서 실행한 전체 Go 검사 수이며 HTTP 업무 기능 개수나 실장비 검증 수가 아니다. Python7개와 로컬 검사 수는 별도로 기록한다. make smoke를 서버에서 다시 실행했다는 증거는 없으며 이전 로컬 smoke 결과만 유지한다.

## 검증 범위

http_writer_success_uses_synthetic_store=true다. 생성·교체·성공 재생은 합성 writer를 사용했고 실제 TLS socket·권한/입력 거부·unadmitted concrete 저장소의 실패를 확인했다. 기존 저장소 native 검사도 통과했지만 이 두 결과가 새로운 HTTP 요청과 actual admitted store 성공의 결합을 증명하지는 않는다. native_admitted_store_http_writes_verified=false를 그대로 유지한다.

storage_schema_version=8은 격리 저장소 검사의 대상이다. 운영 DB의 schema9 전환이나 API 활성화를 뜻하지 않는다. production_services_modified·production_database_modified·production_keys_loaded·credential_api_activated·business_runtime_ready는 모두 false다. 기존 운영 인수는 API0.7.0-device-delete/schema7/registry-only-v1이며 새 HTTP 경로는 main에 미등록이다.

서버 private 결과 경로는 var/camera/credential-storage-checks/vms-credential-storage-test-f0f750ddf7ee.json, 로그는 같은 디렉터리의 vms-credential-storage-test-f0f750ddf7ee-6v1335x7.log다. 사용자 제공 JSON의 pass와 flag를 근거로 기록하며 원격 파일을 직접 읽거나 운영 상태를 재검사했다고 표시하지 않는다.

## 이번 기록 패치와 다음 단위

이번 패치는 README·계약·작업 기록·문서 목록·manifest만 갱신한다. src·SQL·Compose·환경·키·서비스는 변경하지 않는다. 인수한 manifest SHA를 보존하며 이번 문서 패치 이후 SHA가 달라졌다는 이유로 기존 영수증을 새 revision의 실행 증거로 바꾸지 않는다.

다음 단위는 자격증명 버전의 안전한 메타데이터 조회·폐기 HTTP다. 이후 actual IAM·TLS·키/역할·schema9/admission 공급과 native HTTP 통합을 검증한 뒤 운영 경로를 활성화한다. 백업 추가 설계는 사용자 요청에 따라 후속 목록에서 제외한다.

[구현 기록](20261008-step11c1-credential-write-http.md) · [HTTP 계약](../contracts/camera-credential-write-http.md)
