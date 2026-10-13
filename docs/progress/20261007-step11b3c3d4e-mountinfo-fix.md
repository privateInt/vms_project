# 단위 11-B3c3d4e 수정 — 커널 mount root 표기

작성일: 2026-10-07 · 첫 수정 서버 파일 적용 확인/마운트 테스트 재실패

## 서버 재검사 결과

사용자 로그에서 첫 수정 written8/pending0, backup=var/patch-backups/step11b3c3d4e-fix-yguoyxty를 확인했다. native directory/fdinfo 테스트가 다시 실패했고 이번 고정 코드는 MOUNTINFO_ROOT_PATH_INVALID다. 36개 중 오류1개로 종료되어 이후 identity32개·공급90개·실제 DB volume inspector는 실행되지 않았다. root 필드의 canonical/삭제 표기 조건에서 실패한 사실만 확인됐으며 문제 원문이나 정확한 형태는 로그에 없다. //deleted 한 종류만 처리한 첫 수정은 충분하지 않았다.

[root 메타데이터 수정](20261007-step11b3c3d4e-root-metadata.md)에서 전역 root 파싱과 선택된 대조 경로 검증을 분리하고 원문 없는 진단을 추가했다. 아래 검증과 구현 내용은 첫 수정 전달 당시의 기록이다. 서버 볼륨 대조 성공으로 인수하지 않는다.

## 관찰과 범위

사용자 simsys4090/sh_test 로그의 d4e written9/pending0와 backup=var/patch-backups/step11b3c3d4e-s7kn8rvm을 확인했다. 새27개 중 native directory/fdinfo 테스트가 mount_path의 canonical 경로 규칙에서 MOUNTINFO_INVALID로 실패했다. 이후 identity32개·공급90개·실제 DB 볼륨 inspector는 set-e로 실행되지 않았다. 서버에 적용된 project manifest SHA6d4654e3dd0c2cab50e17020cd83c69c20f30a7dbf68a0741668a73f7208c3fb / tracked426개가 이번 delta 기준이다. d4d의 기존 identity 서버 인수와 schema7/API0.7.0-device-delete는 유지한다.

로그에는 실패한 mount root/mountpoint 원문이 없어 서버의 정확한 문제 경로를 확정하지 않는다. 커널 dentry_path는 삭제된 dentry에 //deleted를 붙인다. 합성 /unrelated/file//deleted root로 전달 버전의 MOUNTINFO_INVALID를 재현했다. 해당 정상 커널 표기를 처리하는 수정이며 같은 응답에서 공급 배치나 운영 전환으로 범위를 넓히지 않는다.

## 변경

- root 필드에서 canonical 경로 뒤의 정확한 //deleted 표기를 원형 그대로 파싱한다. mount record를 삭제하지 않고 mountpoint·parent tree를 보존한다.
- 실제 volume 대조에 선택된 host와 DB root는 별도로 canonical 검증한다. 삭제된 root를 정규화해 유효 경로로 채택하지 않는다. 상위 overmount와 nested WAL mount를 숨기지 않는다.
- LF/ASCII space를 정확한 커널 구분자로 사용해 파일명에 있는 Unicode 공백·CR 등의 byte를 보존한다. octal escape는 기존 네 종류만 한 번 해독한다.
- 다른 root/mountpoint/escape 오류를 원문 없는 고정 코드로 구분한다. 실제 검사 실패 보고서에도 해당 코드와 기존 stage가 남고 이전 성공을 대체한다.

DB file content·directory listing·원본 키·DSN·authority·archive에 대한 접근을 추가하지 않는다. Docker/SQL allowlist, O_PATH/NOFOLLOW, process·directory·mount·입력 drift 검사와 all-production-change=false·activation_allowed=false 경계는 유지한다. 전체 백업 topology나 실제 credential binding은 아직 검증되지 않았다.

## 검증

마운트36개, 기존 identity32개·공급90개를 로컬 Python3.12에서 통과했다. 추가9개는 삭제 표기 처리·선택 root 거부·상위/중첩 mount 보존·커널 구분자와 surrogate byte·escape 한 번 해독·잘못된 경로 유지 거부·고정 오류 보고서의 원문 비노출을 검사한다. 기존 실제 Linux O_PATH/own fdinfo/mountinfo 테스트를 유지해 통과했다. 새 의존성은 없으며 수정 Python 파일의 3.10 문법을 확인했다.

delta는 source/test·manifest·문서8개이며 전체 baseline426개 hash와 source427개를 관리한다. helper8개와 dry-run·적용·원본 백업·재실행·기존 사용자 편집/새 경로 충돌 거부·env/key/authority sentinel 보존을 검사한다. 적용된 파일에서36+32+90개도 검증한다. 기존 Go/SQL/Compose·상위 검사 소스는 byte 단위로 유지해 추가 Go/race/vet/실제 PG 검사를 반복하지 않는다. 운영 Docker와 서버 문제 경로가 로컬에 없어 실제 볼륨 대조 성공은 주장하지 않는다.

## 다음 완료 기준

서버에서 수정 패치를 적용하고 마운트36개·identity32개·공급90개 및 실제 topology inspector를 재실행한다. 다른 경로 문제라면 구분된 고정 오류를 기준으로 추가 조사한다. topology_readiness=verified 또는 blocked_stage와 blocker를 인수한 뒤 공급 위치와 complete backup roots 검토로 진행한다. 권한 부족을 자동 sudo/chmod/chown으로 복구하지 않는다. 실행 명령은 전달 채팅에서만 제공한다. Streamlit browser acceptance는 deferred이며 중계를 추가하지 않는다.
