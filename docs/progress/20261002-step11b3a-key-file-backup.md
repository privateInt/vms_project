# 단위 11-B3a — 보호된 키 파일 로더·호스트 백업 준비

작성일: 2026-10-02 · 서버 키 로더·호스트 백업 준비 인수 완료

## 선행 인수와 범위

[11-B2 기록](20261002-step11b2-credential-storage.md)에 사용자의 applied=25·Python 12개 OK·native PostgreSQL passed를 반영했다. 검증 source hash는 1d171e4820db56d569a7e665f83759710f3c7b88cd9f2ed88ea830bd576938b0이며 Go race·vet, 상위 108개·하위 310개·필수 자격증명 13개·native 권한/경쟁이 통과했다. 운영 서비스/DB/키/API는 미변경·미활성, 임시 자원 정리는 완료였다.

11-B3은 준비와 리허설로 나눴다. 이번 결과는 **Linux 키 파일 로더와 기존 호스트 키의 create-only 백업**이다. DB 연결·실제 read-only mount·쓰기 재개 fence·키 회전/복원·비밀 HTTP 입력은 포함하지 않는다.

신규 파일은 Go 로더/OS별 경계/검사 4개, 백업 도구/검사 2개, ADR/운영/진행 문서 3개의 9개다. 기존 279개 중 암호화 parser 주석·11-B2 진행 기록·프로젝트 명세의 3개를 변경한다. 나머지 기존 276개와 마이그레이션 SQL 1..8·저장소/HTTP 기능·실행 OpenAPI·Compose·키 준비 도구·다른 플랫폼은 보존한다.

Go 로더는 현재 EUID·private 부모/파일 mode·단일 link·일반 파일·모든 경로의 no-follow·bounded read·전후 inode/metadata를 검사한 뒤 불변 키 이력을 읽는다. 다른 OS는 고정 오류로 거부한다. 파일 생성/보정·키 export·API startup 연결은 없다.

호스트 백업 도구는 source shared lock과 destination exclusive lock을 잡고 정확한 원본 바이트·0600 키/완료 manifest·0700 디렉터리를 준비한다. 재실행 시 같은 백업을 검증하며 부분/충돌/링크/경로 교체를 거부한다. 키 원문은 private 백업에만 기록하고 공개 결과에는 키 ID/수·상태·권한·경로만 남긴다. 원본 키와 환경은 보존한다.

## 검증

| 검사 | 결과·범위 |
|---|---|
| camera credentialcrypto Go race | 상위 21개·하위 77개 통과, 실패/skip 0. 새 로더 상위 6개 포함 |
| 전체 Go vet | 통과. SQL·저장소 동작에는 변경 없음 |
| 백업·기존 키 준비 Python | 새 백업 22개 + 기존 준비 20개 = 42개 통과, ResourceWarning 오류 처리 포함 |
| 패치 도구 | 8개 통과. 기준 279개·payload 12개, 최초 12개/재실행 0개·원본 3개 백업·보호 파일 보존·충돌 사전 거부 |
| 전달 검사 | Python 3.10 문법·gofmt·문서 링크·명세 전체 hash·압축 경로/바이트 일치 |

로컬 Go 검사는 합성 키 파일과 UID stat로 권한 판단을 검사했다. 실제 다른 UID로 chown한 파일 거부는 서버 native Docker 검사에서 요구한다. 해당 서버 결과는 아래 인수 기록으로 확인했다. Python은 임시 합성 키의 정확한 백업·재실행·권한·이력·부분 기록·경합·키/경로 변경·비노출을 검사한 결과다. 실제 호스트 원본 키를 이 환경에서 읽지 않았다.

API 프로세스/라우팅 변경이 없어 smoke나 운영 이미지 전환은 실행하지 않았다. 기존 운영 기준은 camera 0.7.0-device-delete·스키마 7·business_runtime_ready=false다. 저장소 native 인수 hash와 새 키 로더 source 인수를 명세에서 분리한다. server 백업/Go 로더 인수는 완료했고 credential runtime activation은 대기다.

## 다음 완료 기준

이번 패치·서버 native 검사와 호스트 backed_up/already_backed_up 결과를 인수했다. 이후 **11-B3b 격리 키 공급·DB/키 복원 리허설**에서 private 디렉터리의 실제 read-only mount·실행 UID·별도 DSN·복원 전 쓰기 차단·옛 키 읽기 이력·새 독립 암호화 키 쓰기·중단 후 재시도를 검증한다. DB 스냅샷의 사용량 rewind를 막는 외부 admission은 아직 구현하지 않았다. 운영 key activation·IAM/비밀 HTTP·설정 CRUD·RTSP는 이후 독립 단위다. 적용 명령은 채팅으로만 제공한다.

## 서버 인수 — umask 수정 후

사용자 로그에서 수정 패치 applied·written=3·pending=0, Python 준비/백업 42개 OK를 확인했다. native 검사 source hash는 ff0bcb7a82f8f0d0e30d2f32dc980bc1007d6a5cd0683ff1b721dfae75a820f7이며, race·vet·상위 114개·하위 310개·필수 자격증명 13개·native 권한/경쟁이 통과했다. 실제 다른 UID 파일 거부를 포함한 Linux 키 로더 검사를 인수했다. 임시 자원 정리는 완료였다.

호스트 첫 백업은 backed_up, 재실행은 already_backed_up이었다. 원본 일치·원본 보존·backup_ready는 true, 디렉터리/파일 권한은 0700/0600이었다. 공개 키 ID enc-e36370d41ab57a7d·idem-5cf993c8fd7089ed와 각 이력 1개가 유지됐다. 백업 디렉터리는 bundle-5933274a60b21f31d856bc9b25a0349754683a4a834b2bb4d54d78c6e2366302다. 실제 키 원문은 전달받거나 읽지 않았다.

서비스·운영 DB·환경은 미변경이다. API 키 활성화·DB 백업 포함·restore_ready·restore_fence_implemented는 false다. 이는 11-B3a 준비 인수이며 운영 자격증명 기능/복구 인수가 아니다. 다음은 [11-B3b 격리 리허설](20261002-step11b3b-key-supply-restore-rehearsal.md)이다.
