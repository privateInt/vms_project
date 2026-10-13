# camera 자격증명 키 공급·DB/키 복원 격리 검사

상태: 11-B3b native 서버 격리 인수 완료

## 대상과 결과

전용 도구 test_camera_credential_restore.py는 프로젝트 파일 hash와 단계가 일치할 때만 실행한다. 별도 Compose 파일 compose.credential-rehearsal.yaml과 고유 vms-credential-restore-test 접두 프로젝트를 사용한다. Docker/Compose와 기존 검사에서 사용한 Go/PostgreSQL 이미지가 필요하다. 실제 실행 명령은 채팅에서 제공한다.

호스트 원본 키/백업·운영 DB·.env·운영 서비스는 읽거나 변경하지 않는다. 호스트 private 임시 입력에는 새 합성 키만 만들고, 전용 Docker 키/백업/검사 볼륨과 tmpfs DB를 사용한다. 포트·production network·기존 volume·고정 container name은 없다. source mount는 src/platform뿐이다. 키 볼륨은 UID 10001·private 권한으로 준비하고 검사 프로세스에서 read-only로 읽는다.

검사는 seed → 백업 → advance → 로그인/세션 차단 → 다른 DB 복원/옛 키 비활성 → 키 복원 → blocked 두 프로세스 → 새 키 enrolled 두 프로세스 → LOGIN 재개 → resumed → recreated 순으로 진행한다. 단일 DB custom dump는 role을 복원하지 않으며 리허설은 같은 임시 클러스터의 NOLOGIN을 유지한다. 모든 Go phase는 race 검사 바이너리로 실행하고 전체 Go vet도 준비 단계에서 수행한다.

성공은 8개 phase의 실제 Go pass와 marker 순서를 모두 요구한다. skip·누락·과거 pass 뒤 실패·순서 변경·source drift·명령 실패·timeout·정리 실패는 passed가 되지 않는다. 원본/새 암호문·HMAC 영수증·quota·누락 역사 키·로그인/이전 DB 차단·프로세스 재생성을 검사한다. source hash는 보고서 checked_revision으로 남긴다.

## 보고서와 실패

var/camera/credential-restore-checks에 private 0600 로그/JSON을 남긴다. 보고서에는 공개 상태/검사 범위/자원명/경로만 있고 key material·DSN·password는 없다. 성공 시 database_and_key_restore_verified 등은 합성 격리 범위의 값이며 production_restore_fence_implemented·production_keys_loaded·credential_api_activated·business_runtime_ready는 false다.

모든 실패 경로에서 해당 프로젝트만 down/volumes 정리를 시도한다. 합성 호스트 임시 입력은 제거한다. ISOLATED_CLEANUP_INCOMPLETE이면 보고서의 project에 남은 자원이 있을 수 있으며 성공/자동 복구 완료로 취급하지 않는다. 도구 재실행은 새 임시 프로젝트로 시작하고 production 복원은 수행하지 않는다. 중단 후 재시도 검사는 하나의 리허설 안에서 동일 복원본을 새 프로세스로 다시 검사한 결과다.

이 도구는 운영 DB·role·키 복원 도구가 아니다. 실제 호스트 키 백업의 restore_ready=false와 운영 스키마 7/API 미활성 상태는 그대로다. 다음은 외부 복원 fence와 runtime key admission 구현이며 별도 서버 인수가 필요하다. [ADR 0009](../architecture/decisions/0009-camera-credential-restore-rehearsal.md)를 따른다.

## 서버 인수 완료

수정 후 source hash b00516b1d169377f1c0dd98eadcf2b161d7d173246aafd21265c5a183390afb3의 native 검사에서 8 phase·Go race/vet·키/DB 복원·재시도·프로세스 재생성과 정리가 모두 passed였다. 운영 기능/production restore fence는 미활성·미구현이다. 상세 범위는 11-B3b 진행 기록의 서버 인수를 따른다. 다음 외부 admission 계약/구현은 별도 인수한다.
