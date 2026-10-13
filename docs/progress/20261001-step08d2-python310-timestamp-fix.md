# 단위 08-D2 보완 — Python 3.10 시간 비교 호환성

작성일: 2026-10-01 · 수정·로컬 검증 완료 · 서버 재실행 결과 대기

## 진단 결과 인수

사용자 서버의 진단 패치는 already_applied/written=0이었다. 시험 프로젝트 `vms-source-update-test-0d4f99d4e9f5`는 소스 수정 검증 구간에서 실패했다. 결과는 error_type=ValueError, python_version=3.10.19, failure_location=`test_camera_source_update_upgrade.py`의 verify_rename 266행이다. production_services_modified=false, source_update_activated=false다.

해당 행은 수정 전 응답의 updated_at을 datetime.fromisoformat으로 읽는 부분이다. Python 3.10은 소수 초가 없는 형식과 3자리·6자리 형식을 지원하지만, Go의 시간 JSON 표현에서 가능한 나머지 소수 자릿수를 모두 지원하지 않는다. PostgreSQL 시각도 끝의 0이 생략되면 1·2·4·5자리로 표현될 수 있다. 예를 들어 `.12345Z`를 `.12345+00:00`으로 바꿔도 이 제약은 해결되지 않는다.

서버의 실제 시각 값은 진단 정보에 포함하지 않았으므로 정확히 몇 자리였는지는 기록하지 않는다. 확인된 실패 지점과 Python 버전에 해당하는 파싱 호환성을 수정한다. 참고: [Python 3.10 datetime.fromisoformat 문서](https://docs.python.org/3.10/library/datetime.html#datetime.datetime.fromisoformat).

## 이번 수정

리허설 도구의 verify_rename에서 fromisoformat 의존을 제거했다. 날짜·시·분·초를 검증하고 소수 초 1~9자리를 정수 나노초로 보존한다. UTC Z 및 숫자 시차를 같은 기준으로 변환한 초·나노초 쌍으로 비교한다. 소수 초를 잘라내거나 반올림하지 않으므로 1ns의 시간 역행도 통과시키지 않는다. 잘못된 날짜·시간대·형식에는 고정 오류 RENAME_TIMESTAMP_INVALID를 반환한다.

이 수정은 장치·소스 이름 수정 검사에 함께 적용된다. 버전 증가·이름·불변 필드·프로필·과거 응답 재생 등 기존 조건과 오류 진단은 유지한다. 서버 Python 업그레이드나 새 Python 패키지 설치는 필요하지 않다.

패치는 검사 도구와 단위 테스트를 수정하고 이 문서를 추가하는 3개 파일 범위다. 제품 Go 코드·마이그레이션·운영 Compose·프로젝트 명세는 변경하지 않는다. 운영 API·DB 변경이나 08-D3 활성화는 이번 범위에 포함하지 않는다. 이전 진단 패치를 적용한 상태를 기준으로 기존 파일 해시를 확인한다.

## 검증

- 로컬 Python 3.12에서 기존 안전장치·진단 검사를 포함한 단위 테스트 34개 통과.
- 소수 초 0~9자리, 5자리·9자리 수정 전 시각, 자릿수가 다른 동일 시각, UTC 시차 및 날짜 경계 비교 확인.
- 잘못된 날짜·시각·시차·10자리 소수 초·잘못된 타입 거부. 1ns 시간 역행을 탐지하며 입력 원문을 오류에 노출하지 않음.
- 변경하지 않은 Go camera API와 PGlite 임시 DB로 해당 리허설의 실제 HTTP 구간 통과: 등록·장치 수정·소스 수정·충돌·재생·API 프로세스 재시작·GET·목록·필터·cursor. 이번 수정된 Python 검사 함수를 사용함.
- 패치 적용 전 검사·적용·재적용·충돌 시 쓰기 중단 통과. 기존 환경·실행 기록 및 프로젝트 명세의 179개 파일 해시 유지.

로컬에 Python 3.10 실행 환경과 Docker 엔진은 없다. 따라서 서버 Python 3.10 단위 테스트와 native Docker 스키마 업그레이드·덤프 복원은 재실행 결과로 확인한다. 채팅 명령은 단위 테스트를 먼저 수행하고 통과한 경우 격리 리허설을 실행하도록 제공한다.

## 남은 작업

08-D2는 아직 서버 인수 완료가 아니다. 새 무작위 시험 프로젝트에서 리허설을 다시 수행해 status=passed, schema_version=5, schema_4_restore_verified=true, isolated_resources_removed=true를 확인한다. production_services_modified=false와 source_update_activated=false도 유지돼야 한다.

그 결과를 받은 뒤 다음 단위인 08-D3 운영 전환 준비를 진행한다. 이번 적용·재실행 명령은 작업 기준에 따라 채팅에서만 제공한다.
