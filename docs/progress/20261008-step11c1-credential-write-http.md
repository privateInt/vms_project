# 11-C1 자격증명 버전 생성·교체 HTTP

상태: 구현·로컬 검사·서버 패치/격리 검사 인수 완료 · 운영 활성화 전

## 기준과 순서 변경

사용자 서버의 11-B3c3d4j 인수 기록 패치는 written6/pending0으로 적용됐다. 이번 기준 manifest SHA는 f2f6806275fc20899e88a7a08220445589e533cbacec77405c60a998cc2b9244이며449개 파일을 기준으로 충돌을 검사한다. 서비스·schema 전환은 없었다.

2026-10-08 사용자가 백업을 고려하지 말라고 지시했다. 제안했던 11-B3c3d4k 백업 선언은 진행하지 않았고 추가 백업 설계·검토를 현재 후속 계획과 개발 선행 조건에서 제외했다. 과거 결과를 완료로 바꾸거나 복구 도구를 삭제하지 않았다. 실제 제품 경로인 자격증명 HTTP로 순서를 변경했다.

## 변경

별도 권한·TLS를 요구하는 POST credential versions를 구현했다. 생성/교체를 불변 버전 쓰기로 연결하고 expected_version·멱등 키·private target/secret을 엄격히 검사한다. concrete 저장소의 transactional authorizer·전체 작업 lease·암호화 예산·HMAC replay를 보존한다. 개발 principal fallback은 없다.

중복/escaped key·null/type·정수 정밀도·UTF-8/surrogate·본문 크기·헤더 순서를 검사한다. 공개 receipt와 allowlisted 오류만 응답하고 private DTO는 fmt/JSON으로 누출하지 않는다. 저장소의 대상 predicate를 계약 코드와 공유한다. SQL·역할·암호화 알고리즘은 변경하지 않았다.

현재 main에는 새 경로를 등록하지 않았다. credential_write_http_implemented는 true지만 전체 credential_api_implemented/credential_api_activated는 false다. 메타데이터 조회·폐기·IAM/runtime 공급이 남아 있으며 운영 API0.7.0·schema7·registry-only-v1의 인수와 이번 구성요소 구현을 구분한다.

## 로컬 검증

Go1.25.1 contracts/app race: 상위41개·하위268개 PASS. 새 입력/HTTP 필수12개가 포함된다. actual TLS·최초/재생/교체·권한 거부·unadmitted concrete store·불일치 receipt·오류와 private output 차단을 검사했다. 성공 writer는 synthetic이며 실제 admitted store와 새로운 HTTP 성공의 결합 검사는 후속이다.

storage/credentialcrypto race 회귀: DB 미지정 상위51개·하위88개 PASS. DB 의존 skip은 native 성공에 포함하지 않는다. disposable 로컬 PostgreSQL17.11에서는 관련 저장소 상위6개·하위3개를 실행해 암호화 저장·불변 버전/대상·HMAC 재생·권한 재확인·실제 least privilege 역할이 PASS했다. 로컬 구축본이며 대상 서버 Docker 인수와 구분한다.

Go vet 전체 모듈·네 플랫폼 make smoke·신규 Python runner7개·기존 runner12개가 PASS했다. API Schema/예제·패키지 기준 hash·재적용·보호 파일 보존·변경/새 파일 충돌도확인했다.

## 서버 인수 — 2026-10-08

사용자 제공 출력에서 패치17개 적용·Python7개 OK와 Docker status=passed를 확인했다. 검사 revision은 35844b90e22ccef2ebead29f7486a7dac1c20ab002be1b89c37250a6e116fe6c, Go 상위170개·하위494개와 race/vet가 PASS다. 필수 기존 credential13개·HTTP7개·계약5개 모두 PASS이고 격리 자원 정리도 true다.

HTTP success writer는 synthetic이며 native_admitted_store_http_writes_verified는 false다. 운영 서비스·DB·키·HTTP 활성화·business runtime은 변경하지 않았다. storage schema8은 격리 대상이며 운영 schema 전환 증거가 아니다. [서버 인수 기록](20261008-step11c1-server-acceptance.md)에 근거와 다음 단위를 남긴다.

## 전달·남은 작업

패치는 코드·계약·문서·manifest만 적용한다. 운영 재시작·DB 마이그레이션·역할 생성·키 활성화·네트워크/포트 변경은 없다. 서버 도구는 기존 disposable storage runner를 재사용하며 HTTP7개·계약5개·native credential13개 누락/skip을 성공으로 인정하지 않는다. 운영 비밀을 입력하거나 전송하지 않는다. 적용/검사 명령은 채팅에 제공한다.

다음 단위는 안전한 자격증명 버전 메타데이터 조회·폐기 HTTP다. 이후 실제 IAM·TLS·키/DSN·schema9/admission 공급을 연결해 native HTTP를 검증한다. ConnectionConfig·장치 연결·영상·플랫폼 UI 확장은 그 뒤에 진행한다. 백업 설계는 후속 목록에서 제외한다.

[HTTP 계약](../contracts/camera-credential-write-http.md) · [이전 서버 인수](20261008-step11b3c3d4j-server-acceptance.md)
