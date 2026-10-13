# 단위 11-B3c2 — 외부 admission state·stable lease 기반

작성일: 2026-10-02 · 코드·로컬 검증 완료 · 서버 native mount 인수 완료(2026-10-07 반영)

## 선행 인수

사용자 로그에서 11-B3c1 패치 applied·written=12·pending=0, Python3.10/jsonschema4.25.1의 정적 검사 23개 OK를 확인했다. 운영 restart/DB 변경은 없었다. 기준 manifest SHA-256은 d74f1564a3e865a38cc382740bd5956c40fd853ded39e3ef316f016089eb3ece다. 11-B3b의 실제 native 복원 8 phase와 B3a 키 백업 인수 이력은 보존한다.

## 이번 결과

camera/internal/credentialadmission의 별도 package에 strict raw parser·상태 전이와 Linux 외부 파일/lease를 구현했다. create-only 최초 FENCED, exact Record CAS, generation+1/new operation, fresh encryption ID/fresh DB incarnation, append-only seen 이력, PREPARED/OPEN 동일 작업 재확인을 제공한다. 정수 token·raw duplicate/escaped fields·unknown/missing·UTF-8·calendar UTC·활성 키 membership을 추가 검사한다. key material 독립성이나 DB budget 준비는 아직 검사하지 않는다.

외부 directory0750/file0640·owner/runtime GID·no-follow·일반 파일/single link·size·metadata/path 안정성과 local FS 종류를 확인한다. 각 lease는 독립 lock descriptor를 사용한다. Bootstrap의 lock device/inode 영수증을 trusted Policy에 고정해 새 process의 lock 교체도 거부한다. 영수증/운영 UID·경로의 실제 공급 도구는 후속 작업이며 권위 유실 시 자동 재발견/재초기화를 제공하지 않는다.

Commit은 file fsync·rename·부모 fsync·재확인으로 끝낸다. 중단/불명확한 IO는 현재 lease를 사용 불가로 만든다. 새 lease의 같은 기록 재시도도 fsync를 재확인한다. 공개 read lease는 실제 RO mount와 유지보수 owner와 다른 runtime UID·정확한 expected OPEN 기록을 요구한다. deadline은 lease 획득에만 적용하고 작업 중 자동 해제하지 않는다. DB/키 준비 확인과 실제 쓰기 보호는 이 package 호출부에서 후속 구현한다.

## 검증과 한계

| 검사 | 결과·범위 |
|---|---|
| 새 admission Go race | 19 top-level·83 subtest 통과. helper/phase selector 2개는 로컬 native mount 증명이 아니며 실제 핵심 검사는 17개 |
| 기존 credentialcrypto race | 21 top-level·77 subtest 통과. 기존 private key 파일 정책 보존 |
| 전체 Go vet | 전체 module 통과 |
| Python 검사 도구 unit | 11개 통과. transcript 불완전/skip/fail·phase 순서·권한·격리·timeout·stage·cleanup·source 변경 실패 처리 |
| 기존 정적 admission 계약 | 23개 통과. schema/examples/requirements 원본 보존 |
| 전달 | 적용 도구 검사·최초/재실행·원본 백업·합성 보호 파일 보존·충돌 사전 거부·manifest/패키지 경로/바이트 검사 |

실제 파일/flock·여러 process·kill·fault injection을 Linux overlay에서 확인했다. 전원 장애·실제 disk IO 실패·허용된 모든 FS·root/admin 우회·host 전체 rollback을 인수한 것은 아니다. 공개 reader의 실제 RO volume/UID positive 검사는 Docker가 없는 로컬 환경에서 실행하지 못했다. 이를 [격리 검사 도구](../operations/camera-credential-admission-check.md)로 서버에서 실행해 결과를 인수한다. DB/키/HTTP 프로세스·routing 변경이 없어 기존 DB 복원 리허설과 product smoke를 반복하지 않았다.

## 미완료와 다음 단위

2026-10-07 사용자 로그에서 Python11개와 native Linux 핵심17개·두 phase·race/vet·실제 RO mount·별도 UID·cleanup의 passed를 확인했다. 검증된 manifest SHA-256은 5cc861915dedf583fa51cf6bdfaea6f5f843683fef39735988886701ff940ea4다. 상세 근거는 [11-UI1 기록](20261007-step11ui1-camera-streamlit.md)에 기록했다. 아래 다음 단계 문장은 최초 전달 시 계획이며, 서버 native 인수 조건은 충족됐다.

서버 native Linux 검사 17개·prepare/read 두 phase·race/vet·cleanup 인수를 먼저 확인한다. 이후 11-B3c3에서 schema9 marker/정규 profile hash/actual key loader 영수증과 CredentialStore 전체 작업 구간 admission을 결합하고 native DB/key 복원을 검증한다. 운영 경로/권위 준비·DB 전환·실제 키/API 활성화는 별도 단계다.

현재 운영 camera0.7.0-device-delete·schema7·registry-only-v1, 저장소 구현 schema8을 보존한다. production_restore_fence_implemented·credential_runtime_key_supply_verified·credential_api_implemented·business_runtime_ready=false다. 외부 state 기반 구현 완료와 운영 복원 차단 완료를 구분한다. 명령은 채팅에만 제공한다.
