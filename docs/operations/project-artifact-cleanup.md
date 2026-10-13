# 프로젝트 생성 자료 정리

cleanup_project_artifacts.py는 manifest의 source hash와 프로젝트 소유권을 확인한 뒤 정리 대상을 보고한다. apply가 없으면 제거하지 않는다. apply는 새 백업을 만들지 않으며 API/DB·Docker·공유 Conda 환경을 조작하지 않는다.

| 제거 대상 | 보존 대상 |
|---|---|
| var/patch-backups, 과거 camera activation/key 백업 | 원본 .env·현재 registry DSN/password·credential key |
| test-streamlit-recovery·credential-backup-reviews | 현재 TLS 후보/공급/준비와 authority |
| 격리 검사 폴더의 .log·src __pycache__·build | 검사 .json·활성화 receipt·src/docs와 사용자 자료 |
| remove-ui-environment 지정 시 전용 UI 환경/상태/설치 log | UI 코드·requirements·Conda sh_test·Jupyter |

Streamlit 전용 환경을 제거하면 해당 UI를 다시 실행하기 전에 기존 환경 준비 도구로 재생성해야 한다. 공유 Python 환경에 설치된 패키지는 제거하지 않는다. 과거 백업 파일은 새 복사본을 만들지 않고 제거하므로 그 파일을 이용한 롤백/복구는 남지 않는다.

현재 source·선택한 대상 metadata가 계획과 달라지면 중단한다. mountpoint 또는 그 안의 선택 경로·상위/최상위 symlink·특수 파일을 거부한다. 삭제는 no-follow descriptor를 사용하고 내부 symlink는 링크만 제거한다. UI 프로세스 확인과 같은 camera coordination lock으로 작업 중 충돌을 줄인다. sudo·chmod·서비스 중지로 검사 조건을 자동 우회하지 않는다.

planned는 후보 파일 bytes/count를, cleaned는 제거한 대상 수를, already_clean은 더 제거할 대상이 없음을 표시한다. bytes는 파일의 논리적 크기이며 filesystem의 실제 회수량 측정값이 아니다. 실패에 removed_target_count가0보다 크면 이미 완료된 대상은 제거된 상태이고 후속 대상은 다시 검사해야 한다.

선택적으로 source-archive는 manifest에 기록된 소스만 압축한다. 목적 파일이 이미 있으면 덮어쓰지 않는다. .env·var·build·캐시·Python 환경을 공유 압축에 넣지 않으며 source bytes/hash를 다시 확인한다. 명령은 전달 채팅을 따른다.

[분석/수정 기록](../progress/20261012-step11d1e-image-pin-fix-and-cleanup.md)
