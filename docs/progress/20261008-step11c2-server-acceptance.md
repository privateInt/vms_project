# 11-C2 서버 인수: 자격증명 버전 조회·폐기 HTTP

상태: 서버 패치 적용·격리 검사 인수 완료 · 운영 활성화 전

## 근거

2026-10-08 사용자가 제공한 simsys4090/sh_test 출력에 근거한다. 적용 도구는 already_applied·written0·pending0이었다. 파일이 이미 적용된 상태임을 확인한 결과이며, 이번 출력에 없는 최초 적용 시각·변경 파일 수·적용 이력 경로를 새로 추정하지 않는다. 서비스 재시작·runtime 활성화·DB schema 변경은 없었다.

검사 대상 manifest SHA는 `a17f3daca8e876352e30df43e350771a90aef0b4660804d3ebb7baaf5587ef2d`다. Python runner unit9개가 OK였고 native Docker 검사는 status=passed, scope=camera_credential_version_metadata_revoke_http_native_postgresql, project=vms-credential-storage-test-db1185633e07로 완료됐다.

| 서버 검사 | 결과 |
|---|---|
| Go race / vet | 둘 다 true |
| Go 상위 / 하위 검사 | 185 / 567 PASS |
| 기존 자격증명 저장소 | 필수13개 PASS, native 역할·동시성 true |
| C1 생성·교체 HTTP / 입력 계약 | 필수7개 / 5개 PASS |
| C2 조회·폐기 HTTP / 폐기 계약 / 메타데이터 | 필수8개 / 3개 / 4개 PASS |
| 실제 HTTP TLS / 엄격한 비밀 입력 / 안전한 응답·오류 | 모두 true |
| 정확한 버전·폐기 이력·조회 예산 비소비 | 모두 true |
| 조회 MANAGE 권한 / 실제 DB 역할·권한 회수 | 둘 다 true |
| 폐기 guard 전달 / HTTP 폐기 재생 | 둘 다 true |
| 미승인 저장소 거부 / 암묵적 경로 활성화 거부 | 둘 다 true |
| 격리 자원 정리 | true |

필수40개는 위의 13+7+5+8+3+4개이며 전체 Go185/567 안에 포함된다. 이 수는 실장비 기능 수나 업무 경로 수가 아니다. Python9개·기존 로컬 검증 결과와 구분한다. 서버에서 make smoke를 재실행했다는 증거는 없으며 기존 로컬62개 결과를 유지한다.

## 인수 범위와 남은 경계

HTTP 성공은 version_http_success_uses_synthetic_store=true, http_writer_success_uses_synthetic_store=true다. 실제 TLS socket을 검사했지만 HTTP 성공 manager/writer는 합성 구현이다. native_admitted_store_version_http_verified와 native_admitted_store_http_writes_verified는 false다. 실제 승인 저장소와 새로운 HTTP 요청의 성공 결합을 인수했다고 표시하지 않는다.

metadata_store_test_admission_uses_synthetic_guard=true다. 새 메타데이터 native 검사는 실제 PostgreSQL 역할을 사용하지만 admission은 schema8 테스트 전용 guard다. 정확한 버전·폐기 이력·관리 권한·grant 회수·예산 비소비 인수와 schema9 실제 admission 통합을 구분한다.

storage_schema_version=8은 격리 검사 대상이며 운영 schema9 전환 증거가 아니다. production_services_modified·production_database_modified·production_keys_loaded·credential_api_activated·business_runtime_ready는 모두 false다. 운영 인수 기준은 API0.7.0-device-delete/schema7/registry-only-v1이며 이번 도구는 운영 상태를 재조사하지 않았다.

서버 결과 경로는 var/camera/credential-storage-checks/vms-credential-storage-test-db1185633e07.json, 로그는 같은 디렉터리의 vms-credential-storage-test-db1185633e07-efn7prkz.log다. 사용자 제공 JSON을 근거로 기록하며 원격 파일을 직접 읽었다고 표시하지 않는다.

## 이번 기록 패치와 다음 단위

README·조회/폐기 계약 설명·진행 기록·문서 목록·manifest에 서버 인수 결과를 반영한다. src·SQL·Compose·환경·키·서비스 변경은 없다. 인수한 원래 revision을 보존하며 기록 패치의 새 SHA를 이전 서버 실행 증거로 바꾸지 않는다.

다음 단위는 11-C3: 실제 권한 정책·승인 저장소와 credential HTTP의 격리 통합이다. 생성/교체·메타데이터·폐기 HTTP가 실제 admission/역할/키/권한을 거쳐 성공하고 거부 조건·재생을 유지하는 것이 완료 기준이다. 운영 활성화는 이후 별도 단위다. 백업 추가 설계·검토는 사용자 지시에 따라 제외하고 Streamlit 브라우저 인수는 보류한다.

[구현 기록](20261008-step11c2-credential-versions-http.md) · [조회·폐기 계약](../contracts/camera-credential-versions-http.md)
