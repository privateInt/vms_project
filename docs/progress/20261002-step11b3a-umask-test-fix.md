# 11-B3a — 권한 검사 fixture의 umask 영향 수정

작성일: 2026-10-02 · 수정·서버 재검사 인수 완료

## 서버 결과와 원인

사용자 로그에서 [11-B3a](20261002-step11b3a-key-file-backup.md) applied·written=12·pending=0과 백업 `var/patch-backups/step11b3a-16xisnu8`을 확인했다. service_restart_performed·runtime_activation_required·database_schema_modified는 false였다.

Python 42개 중 test_backup_base_symlink_or_wrong_permissions_are_rejected가 실제 mode 488과 기대 mode 493 차이로 실패했다. 각각 8진수 0750·0755다. 로컬 umask 0027에서 같은 실패를 재현했다. 테스트가 mkdir(mode=0755) 뒤 실제 생성 권한을 확정하지 않아 umask가 기대값에 영향을 줬다. 이는 서버 umask를 직접 조회한 증거는 아니며 제공 로그와 일치하는 재현 결과다.

테스트의 permissions 거부 호출은 성공했으나 보존 권한 assertion이 실패했다. set -e로 이후 native Docker 검사와 호스트 키 백업 두 호출은 실행되지 않았다. 이번 로그로 11-B3a native/백업 인수를 완료하지 않는다.

## 변경과 검증

실패한 테스트의 임시 디렉터리에 mkdir 직후 chmod(0755)를 추가해 부적합 권한 fixture를 정확하게 만든다. 프로세스/사용자 umask와 실제 호스트 키/백업 경로는 수정하지 않는다. 런타임 백업 도구·Go·SQL·Compose·API 코드의 바이트는 보존한다.

umask 0002·0022·0027·0077에서 기존 준비 20개와 백업 22개, 총 42개가 각각 통과했다. ResourceWarning을 오류로 처리했다. 패치 도구 8개와 최초 3개 파일 적용·재실행 0개·원본 백업·기존 파일/환경/키 보존·충돌 사전 거부를 확인했다. Python 3.10 문법·문서 링크·명세/압축 바이트도 검사했다.

기준 288개 파일 중 테스트와 프로젝트 명세 2개를 갱신하고 이 기록 1개를 추가한다. 기존 286개 파일은 보존한다. Go/실행 코드에 변화가 없으므로 Go race/vet·운영 smoke를 반복하지 않았다.

## 다음 인수

이번 수정 패치 뒤 Python 42개를 재검사하고, 중단된 native Docker 검사와 호스트 backed_up/already_backed_up을 실행해 결과를 확인한다. 이후 11-B3b 격리 키 공급·DB/키 복원 리허설로 진행한다. 운영 스키마 7·자격증명 API 미활성·restore_ready=false를 유지한다. 실행 명령은 채팅으로만 제공한다.

## 수정 후 인수

후속 사용자 로그에서 수정 패치 written=3·pending=0과 Python 42개 OK를 확인했다. 중단됐던 native 저장소/키 로더 검사도 passed였고 Go race·vet, 상위 114개·하위 310개·필수 자격증명 13개가 통과했다. 호스트 백업은 backed_up·already_backed_up, 원본 보존/백업 일치/0700·0600이었다. [11-B3a 인수 기록](20261002-step11b3a-key-file-backup.md)에 검증 hash와 범위를 남겼다. 다음 인수 절의 대기 조건은 충족됐으며 운영 키/API·DB 스키마 활성화는 수행하지 않았다.
