# 11-C3: 실제 관리 정책·승인 저장소와 자격증명 HTTP 통합

상태: 코드·대상 서버 native HTTP 격리 인수 완료 · 운영 활성화 전

## 시작 상태와 이번 단위

사용자 제공 로그로 11-C2 인수 기록 패치 applied·written6·pending0을 확인했다. 해당 적용 이력은 var/patch-backups/step11c2-notes-mzck4gvn이다. 서비스 재시작·runtime 활성화·DB schema 변경은 없었다. 잘못 붙여 넣었다고 정정한 agent_project 로그는 이 프로젝트의 근거로 사용하지 않는다. 이번 기준 manifest SHA는 6a6e604c545e9b28a1889e228f510aa941abdc33365782787413691398a2fbd4이며 추적 파일471개를 보존한다.

이번 결과는 C1/C2 credential HTTP를 실제 주체·장치 관리 정책과 concrete admitted store로 연결할 수 있는 명시적 구성요소와 Docker native 검사다. [ADR0020](../architecture/decisions/0020-camera-credential-management-policy.md)에 따라 검증된 mTLS leaf DER hash를 scope/principal/device MANAGE 허용 목록에 연결했다. 빈/미등록 정책 거부·권한 교체·진행 중 snapshot 재검증을 구현했다. main 등록·운영 전환·기업 IAM·새 ConnectionConfig 업무는 포함하지 않는다.

## 격리 검사

schema9·writer/budget TLS 계정·synthetic key·OPEN authority를 owner가 준비하고, owner DSN 없이 UID10001의 새 process를 시작한다. 실제 RO key/authority와 concrete admission guard를 사용하며 성공용 synthetic storage guard를 주입하지 않는다. 임시 직접 mTLS HTTP로 생성·교체·조회·폐기·HMAC 재생과 실제 권한/marker 상실·FENCED·process 재생성을 검사한다. 폐기 guard 대기 중 maintenance lease가 차단되고 요청 뒤 정상 drain되는지 확인한다.

사용 관계 guard의 InUse/Unknown/Unused 상태는 fixture 전용이다. 운영의 관리 참조·reservation·사용 해제 경로는 미구현이며 default unused guard는 제공하지 않는다. 이 경계를 report에도 명시한다. 기존 C1/C2 필수40개·정책6개·native 부모1개와 정확한8개 phase를 요구하며 누락/skip/중복/순서/실패 은폐를 거부한다. 운영 서비스·DB·키·admission·API activation·business runtime은 false다.

## 로컬 검증 — 실제 범위

| 검사 | 결과와 범위 |
|---|---|
| Go 전체 모듈 race, DB 미설정 | 상위136개·하위510개 PASS, native/DB 조건 skip92개는 인수로 세지 않음 |
| 마지막 app 변경 후 race | app 상위35개·하위263개 PASS, skip3개; 새 정책 필수6개 포함 |
| 실제 mTLS 관리 정책 | CA-valid 미등록 leaf·인증서 없음·빈 정책 거부, 헤더 주장 미사용 |
| 새 Python runner unit | 9개 PASS, transcript·source gate·오류/timeout·환경 제거·cleanup 검사 |
| credential runner 회귀 | 222개 PASS, 위9개 포함 |
| 임시 PostgreSQL17.11의 storage/contracts/app race | 상위141개·하위403개 PASS, 기존 필수40개 PASS; C3 native UID/RO 부모 검사는 활성화하지 않음 |
| 전체 Go vet | PASS |
| 네 API 실제 process smoke | 62개 PASS, 자격증명 경로 미등록 유지 |

전체 모듈을 임시 native PostgreSQL과 함께 실행한 별도 시도는 기존 TestPrivateKeyFileAcceptsReadOnlyModesAndRejectsForeignUID의 실제 chown에서 EINVAL로 실패했다. 현재 실행 환경은 UID/GID0만 매핑되고 다른 UID/RO mount를 만들 권한이 없다. 상위190개·하위567개 PASS가 있었어도 전체 성공으로 표시하지 않는다. 이후 storage/contracts/app만 새 임시 cluster에서 실행해 위의141/403 PASS를 확인했다. 기존 foreign-UID 검사나 admission 안전 조건을 약화하지 않았다.

C3 실제 admitted HTTP 성공은 로컬에서 실행하지 못했으며 대상 서버 Docker 검사가 필수다. code 작성/컴파일과 native 성공을 구분한다. 최초 local Go 전면 결과 이후 바뀐 app 검사만 다시 실행했고 최종 전체 vet를 확인했다. PostgreSQL cluster/process는 종료했다. package 검증은 기준·payload hash, dry run/적용/재적용, 사용자 변경·새 파일 충돌·보호 파일, Python3.10 문법, helper8개를 확인한다.

## 서버 인수 — 2026-10-08

사용자 제공 출력에서 applied·written14·pending0, Python9개 OK, Docker status=passed를 확인했다. 인수 revision은 0b2891f179dddca6d3e43a09e253c915b7babd32b8a437fc6d61b5d3f4dd50aa이며 Go 상위192개·하위567개, 필수47개, 8개 native phase, race/vet·격리 정리가 통과했다. 실제 schema9·별도 UID·RO key/authority·두 TLS 역할·관리 정책을 사용하는 admitted store/HTTP 성공을 인수했다. 운영 서비스·DB·키·admission·API 활성화·business runtime 변경은 모두 false다.

native_admitted_store_http_writes_verified/native_admitted_store_version_http_verified는 이번 C3 native 검사에서 true다. 과거 C1/C2의 synthetic 회귀 결과와 로컬 UID 제한 이력은 그대로 보존한다. 운영 usage guard와 기업 IAM은 미구현이다. [서버 인수 기록](20261008-step11c3-server-acceptance.md)에 근거와 남은 경계를 기록했다.

## 남은 일과 다음 완료 기준

다음 단위는 운영 TLS·고정 endpoint/source 공급의 준비와 격리 검증이다. 실제 후보 설정과 공급 계획을 검토 가능하게 만들되 운영 서비스 전환은 분리한다.

그 뒤 운영 TLS/endpoint/source·키/역할 DSN·authority 공급을 작은 준비/격리 단계로 나누고, schema9 전환과 실행 경로 활성화를 별도 인수한다. 기업 IAM과 실제 관리 사용 관계는 아직 남아 있다. ConnectionConfig·SourceSession·실장비 RTSP/ONVIF/PTZ/XR·영상 및 model/analysis/operation 업무 경로는 후속이다. 사용자 지시에 따라 백업의 추가 설계/검토는 개발 선행 조건에서 제외한다. Streamlit 브라우저 인수는 보류하며 Jupyter 중계는 만들지 않는다.

[통합 계약](../contracts/camera-credential-management-http.md) · [검사 안내](../operations/camera-credential-management-check.md) · [C2 서버 인수](20261008-step11c2-server-acceptance.md)
