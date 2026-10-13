# ADR 0008 — 보호된 camera 키 파일 읽기와 호스트 백업

날짜: 2026-10-02 · 상태: 11-B3a 서버 준비 인수 완료

## 단계와 결정

[자격증명 저장소](0007-camera-credential-storage.md)의 native 서버 인수를 완료했다. 키의 운영 공급과 복원은 독립적인 완료 기준이 있으므로 11-B3a 파일 읽기·호스트 백업 준비, 11-B3b 읽기 전용 공급·DB/키 복원 리허설로 나눈다. 이번 단위는 기존 API에 키를 연결하거나 운영 Compose/DB/역할/DSN을 변경하지 않는다.

Go LoadKeyBundleFile은 camera 내부 암호화 패키지에서 Linux 절대 경로의 키를 읽는다. 모든 경로 구성요소를 디렉터리 descriptor를 기준으로 O_NOFOLLOW로 열고, 최종 파일도 같은 규칙을 적용한다. 즉시 부모는 현재 EUID 소유·0700 또는 0500, 파일은 현재 EUID 소유·0600 또는 0400·단일 hardlink·일반 파일이어야 한다. setuid 등의 추가 mode bit는 허용하지 않는다. 다른 OS는 검토된 구현이 마련될 때까지 고정 오류로 거부한다.

파일 크기를 제한하고 읽기 전후 inode·크기·소유권·권한·mtime/ctime을 확인한 뒤 전체 경로를 다시 열어 같은 부모/파일인지 확인한다. 기존 strict parser로 형식·중복 필드·키 이력·독립 key material을 검사한다. 결과는 키를 export/JSON으로 반환하지 않는 불변 Keyring이다. 오류는 경로/원문/OS 오류 cause를 포함하지 않는 고정 코드다. 로더는 파일 생성·권한 보정·교체를 하지 않는다.

이 검사에서 일반 파일을 읽었다는 사실은 read-only bind mount, DB identity, 실제 writer/budget 역할 분리, 복원 admission을 증명하지 않는다. 같은 소유권을 가진 운영 관리자의 키 교체/경로 변경과 이후 쓰기를 영구 감시하지도 않는다. 현재 API startup은 이 로더를 호출하지 않는다.

## 백업의 완료 기준

호스트 도구는 준비된 원본 키에 shared preparation lock을 잡고 strict 형식·소유권·0600/0700·단일 link·내용 안정성을 확인한다. 목적지에는 별도 exclusive backup lock을 잡는다. 백업 이름은 원본 전체 바이트의 SHA-256을 사용하며, 같은 원본은 검증 후 재사용한다. 바이트/활성 키/이력이 달라지면 별도 백업이 생긴다. 이 도구가 원본을 회전하거나 수정하지는 않는다.

백업은 별도 0700 디렉터리에 정확한 key-bundle.json과 0600 완료 manifest를 create-only로 기록하고 파일·디렉터리를 fsync한다. 완료 manifest는 마지막에 기록한다. 둘 다 일치해야 인수하며, 중단으로 생긴 부분 디렉터리·알 수 없는 파일·내용/권한/경로 충돌은 자동 보정·덮어쓰기 없이 거부한다. SHA-256은 우발 변경을 검사하는 값이며 공격자의 재작성에 대한 서명 증명은 아니다.

manifest에는 hash·공개 키 ID·후속 복원 조건만 있다. 실제 key material은 private 백업 파일에만 보관하고 보고서/로그에 넣지 않는다. 도구 성공은 현재 원본에 해당하는 백업을 읽고 비교한 결과다. 과거 모든 백업의 감사나 복원/원격 보관 인수는 아니다.

## 복원과 운영 공급의 선행 조건

같은 호스트의 별도 디렉터리 백업이며, off-host 보관·백업 암호화·보관 정책·키 교체/폐기를 구현하지 않았다. DB 백업도 포함하지 않는다. 이 키 백업만으로 restore_ready를 true로 하지 않는다.

DB 스냅샷은 암호화 사용량을 되돌릴 수 있다. 별도로 보호된 외부 fence/운영 절차로 복원 전에 쓰기·트래픽을 막고, 옛 암호화 키를 읽기 전용 이력으로 남기며 새 독립 키를 선택해야 한다. 이번 manifest의 복원 조건은 안내 메타데이터이며 실제 fence가 아니다. 11-B3b는 합성 키와 임시 DB에서 쓰기 차단·새 키 등록·옛 암호문/멱등 지문 복구·중단 후 재시도를 입증해야 한다. 실제 API 활성화는 이후 새로운 인수로 진행한다.

[운영 문서](../../operations/camera-credential-key-backup.md)와 [진행 기록](../../progress/20261002-step11b3a-key-file-backup.md)에 검사·인수 상태를 기록한다.

## 후속 인수와 리허설

11-B3a 수정 후 Python 42개·native Go race/vet·호스트 backed_up/already_backed_up 인수를 완료했다. 원본 키/서비스/DB/환경은 보존됐다. 운영 키/API는 미활성이고 restore_ready=false다. [11-B3b 리허설](../../operations/camera-credential-restore-rehearsal.md)에서 합성 키와 독립 임시 Docker 프로젝트만 사용한다. 리허설 계정의 NOLOGIN·예전 DB CONNECT 차단은 해당 임시 클러스터의 절차이며 production admission 구현은 아니다.
