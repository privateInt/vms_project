# 자격증명 저장소 코드와 격리 검사

상태: 11-B2 코드·로컬 격리 검사 완료 · native 서버 인수·운영 적용 전

현재 작업 순서는 [11-C1](../progress/20261008-step11c1-credential-write-http.md)을 따른다. 2026-10-08 사용자 요청으로 추가 백업 설계·검토를 개발 선행 조건에서 제외했다. 아래 복구 관련 내용은 기존 단위의 설계·검증 이력이며 현재 다음 작업은 자격증명 메타데이터 조회·폐기 HTTP다.

## 이번 전달과 실행 경계

패치는 저장소 Go/검사, 추가 마이그레이션 0008, 부모 삭제 보호, 서버 검사 도구·문서·명세를 설치한다. 스키마 8 SQL을 운영 DB에 실행하거나 역할/키를 만들지 않는다. 기존 운영 서비스·환경·호스트 키 파일은 보존한다. 실행 명령은 채팅으로 제공한다.

운영 인수 기준은 camera 0.7.0-device-delete·스키마 7이다. 새 소스로 빌드하면 storage readiness는 스키마 8과 새 predicate grant를 요구한다. **이 단계에서 이미지를 새로 빌드해 운영 API를 재시작하거나 migrate 명령을 실행하지 않는다.** 새 운영 전환은 보호된 키 공급·복구·HTTP/IAM 구현과 새로운 preflight/리허설 증거를 마련한 뒤 별도 진행한다.

project-manifest.json의 storage revision과 대상 스키마를 갱신한다. 10-D의 기존 inspector/rehearsal/activation 도구는 옛 revision·스키마·receipt를 요구하므로 새 소스에서는 거부하는 것이 정상이다. 이전 운영 인수 기록은 역사적 증거로 보존하고 hash를 고쳐 재사용하지 않는다.

## native 검사 도구

`src/infra/tools/test_camera_credential_storage.py`는 명세/전체 소스 hash를 확인한 뒤 별도 `vms-credential-storage-test-` 프로젝트를 만든다. 기존 disposable compose의 tmpfs PostgreSQL과 Go 테스트 컨테이너만 사용한다. 운영 compose/DB/키/DSN 파일·장비 API에 접근하지 않는다. 호스트 키 디렉터리를 컨테이너에 mount하지 않는다.

테스트 비밀번호와 비밀/키는 일회성 합성 값이다. Docker 환경에는 운영 Compose 변수를 넘기지 않고 환경 파일은 빈 경로를 사용한다. 테스트 DB 이름과 명시적 reset 허용을 확인한 Go 검사만 DROP camera schema를 실행한다. 운영 DB에 마이그레이션을 적용한 결과로 해석하지 않는다.

전체 Go race·vet를 실행하고 필수 자격증명 상위 검사 13개, 그중 native 역할/경쟁 검사 4개의 pass를 요구한다. native 검사 skip·누락·다른 package·테스트/vet 실패·소스 변경·격리 자원 정리 실패를 성공으로 표시하지 않는다. 실행 실패/중단 뒤에도 만든 프로젝트에 대해서만 정리를 시도한다.

결과와 로그는 `var/camera/credential-storage-checks`에 현재 계정 소유 0700 디렉터리·0600 파일로 기록한다. 공개 JSON에는 상태·현재 소스 revision·통과 수·격리 project·보고서/로그 경로와 운영 무변경/미활성 상태만 있다. 실패 상세 출력은 private 로그에 남기고 JSON에 원문 DB 오류를 복사하지 않는다. 정리가 실패하면 그 프로젝트와 isolated_resources_removed=false를 기록한다.

## 계정·키·복구의 남은 인수

운영에는 camera_credential_writer와 camera_credential_budget 역할을 아직 만들거나 연결하지 않는다. DB 구조 준비와 실제 비밀 취급을 구분한다. 실제 authorizer/IAM, 보호된 비밀 제출, key loader·읽기 전용 mount·역할별 DSN 공급·키/DB identity 관리·교체/백업 복구는 후속 인수 대상이다.

현재 CheckReference는 정확한 버전·scope/device·미폐기·동일 protocol/host/port를 검사하고 주소/원문 없는 메타데이터만 반환한다. 이는 별도 트랜잭션의 조회이며 실제 키 가독성·네트워크 승인·접속 성공·사용 예약을 증명하지 않는다. 후속 설정 저장은 metadata 조회 결과를 오래 보관해 쓰지 않고 같은 저장 트랜잭션/허용 경계에 참조 확인을 결합해야 한다. 실제 plaintext resolve API는 아직 제공하지 않는다.

RevokeVersion의 guard는 설정 참조와 준비/사용/정리 상태를 같은 장치/credential 잠금에서 증명해야 한다. 지금 production 패키지에는 기본 unused guard가 없다. tests의 합성 guard를 운영 기본값으로 옮기지 않는다. 비밀 버전 폐기는 원문/암호문/백업 파기나 실행 중 세션 중단을 뜻하지 않는다.

pg_dump에는 호스트 키가 포함되지 않는다. 또한 복원한 사용량을 그대로 재개하면 전역 예산을 되돌릴 수 있다. 복원 이전에 쓰기를 차단하고 새 독립 암호화 키를 선택하는 검증된 절차가 필요하다. 현재 DisableCredentialEncryption은 기존 키의 새 쓰기를 중단하고 이전 암호문은 키 이력으로 읽을 수 있도록 설계된 owner 작업이다. 외부 fence·보호된 운영 키 백업·새 키 준비·복원 리허설이 없으므로 운영 비밀 API는 계속 미활성 상태다.

[ADR 0007](../architecture/decisions/0007-camera-credential-storage.md), [키 문서](camera-credential-keys.md), [11-B2 진행 기록](../progress/20261002-step11b2-credential-storage.md)에 범위와 다음 조건을 기록한다.
