# 보호된 키 파일 읽기와 호스트 백업 준비

상태: 11-B3a 서버 키 로더·호스트 백업 준비 인수 완료

## 이번 결과

11-B2 native 서버 검사 passed를 인수했다. 이번 패치는 Go 키 파일 로더와 호스트 백업 도구를 설치한다. 운영 DB 기준은 스키마 7이며 임시 저장소 검사 대상은 스키마 8이다. SQL·실행 앱·OpenAPI·Compose·DSN은 이번 단위에서 바뀌지 않는다.

기존 `var/camera/credential-keys/key-bundle.json`은 이미 준비한 키다. 백업 도구는 키를 새로 생성하거나 변경하지 않고 읽어 검증한다. 실행 명령은 채팅에서 제공한다. 도구 기본 호출은 읽기 검사이며 백업이 없으면 not_backed_up으로 끝난다. --apply를 지정하면 백업 준비를 수행한다.

## 백업과 재실행

`src/infra/tools/prepare_camera_credential_key_backup.py`는 현재 계정 소유 0700 `var/camera/credential-key-backups` 아래에 원본 바이트의 hash에 해당하는 bundle 디렉터리를 준비한다. 그 안에 원본과 같은 0600 key-bundle.json, 키 원문 없는 0600 backup-manifest.json을 기록한다. 디렉터리와 파일 생성은 기존 경로를 대체하지 않는다.

최초 성공은 backed_up, 같은 바이트의 --apply 재실행은 already_backed_up, 기존 백업 읽기 검사는 validated다. 성공에는 backup_ready·backup_matches_source·source_keys_unchanged가 true이며 키 ID·이력 수·권한·경로만 표시한다. keys_activated_in_api·service_restart_performed·database_schema_modified·environment_modified·database_backup_included·restore_ready·restore_fence_implemented는 false다.

KEY_BACKUP_INCOMPLETE는 완료 기록/구성 누락, KEY_BACKUP_MISMATCH는 바이트/완료 기록 충돌이다. preparation/backup lock 경합도 별도 코드로 거부한다. 원문 OS 오류와 비밀 내용을 stdout에 출력하지 않는다. 부분 백업을 기존 키의 대체물로 쓰거나 성공 이력을 수동 작성하지 않는다. 실패한 디렉터리는 도구가 자동 덮어쓰기·삭제·복원을 수행하지 않는다.

## Go 로더와 이후 공급

LoadKeyBundleFile은 Linux의 명시적 절대 경로를 읽으며 현재 EUID·단일 link·엄격한 파일/부모 권한·경로/파일 안정성과 키 형식을 확인한다. 키 이력도 함께 보존한다. API에는 아직 연결하지 않았다. 파일 소유권을 맞추기 위해 이번 도구가 chmod/chown을 자동 수행하지 않는다.

향후 runtime은 이 로더가 읽을 private 디렉터리를 읽기 전용으로 mount하고 호스트 키 소유권과 실행 UID를 맞춰야 한다. 일반 `/run/secrets`의 넓은 부모 권한을 자동 허용하는 예외는 없다. 실제 mount·별도 writer/budget DSN·원본/백업/DB identity·복원 후 새 키 쓰기 허용은 11-B3b 인수 대상이다.

서버에서 기존 native 저장소 검사 도구를 다시 실행하면 현재 프로젝트 전체 hash에 고정한 Go race·vet와 Linux 로더 검사도 실행한다. 실제 외부 UID 파일 거부 검사는 native Docker에서 수행한다. 이 도구는 호스트 원본/백업 키를 mount하거나 읽지 않고 합성 키만 사용한다. 실제 호스트 백업 일치 여부는 위 host-only 도구 결과로 별도 인수한다.

현재 백업은 같은 호스트 파일 복사이며 원격 보관이나 운영 DB·키 복구 완료를 의미하지 않는다. 복원 시 새 암호화 키를 선택하는 외부 fence가 준비되기 전까지 운영 비밀 API는 미활성이다. [ADR 0008](../architecture/decisions/0008-camera-protected-key-files.md)과 [11-B3a 기록](../progress/20261002-step11b3a-key-file-backup.md)을 따른다.

## 후속 인수와 리허설

11-B3a 수정 후 Python 42개·native Go race/vet·호스트 backed_up/already_backed_up 인수를 완료했다. 원본 키/서비스/DB/환경은 보존됐다. 운영 키/API는 미활성이고 restore_ready=false다. [11-B3b 리허설](camera-credential-restore-rehearsal.md)에서 합성 키와 독립 임시 Docker 프로젝트만 사용한다. 리허설 계정의 NOLOGIN·예전 DB CONNECT 차단은 해당 임시 클러스터의 절차이며 production admission 구현은 아니다.
