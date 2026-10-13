# ADR0019 — 운영 공급 계획과 실제 승인 영수증

상태: 채택 · 2026-10-07 · 11-B3c3d4a 정적 계약

## 문제와 선택

11-B3c3d3 서버 조회는 schema7·TLS off·자격증명 역할/키 mount 없음, authority/endpoint 미검토를 확인했다. 기존 protected key loader는 현재 EUID가 소유한 private file/directory와 실제 RO mount를 요구하고, authority는 다른 maintenance UID와 runtime GID의 0750/0640 정책을 요구한다. 호스트에서 준비한 source key를 runtime UID로 chown하면 기존 준비/백업 경로의 소유권을 깨뜨린다.

비밀값 없는 review-only SupplyPlan 계약을 추가한다. source key의 기존 ownership을 보존하고 exact byte의 별도 runtime UID 사본을 RO directory mount로 공급할 계획을 선언한다. maintenance/runtime source와 UID를 구분하고, authority·stable lock receipt와 DB HBA/PKI 파일은 project/DB/key/declared snapshot 범위 밖에 둔다. runtime 두 역할, maintenance mTLS와 single-IP verify-full endpoint는 기존 제품 primitive의 계약을 유지한다.

## 신뢰 경계

SupplyPlan parser의 성공은 선언의 일관성만 확인한다. 실제 파일/CA/key digest, process UID, RO mount, TLS/source, migration/marker/budget/grants, authority lock device/inode는 후속 protected receipt로 확인해야 한다. plan 자체에서 generation/OPEN/bypass/lock identity를 지정하거나 누락 상태를 자동 repair하지 못하게 한다. bootstrap은 empty first deployment를 별도 확인한 후 FENCED로 시작하며 stable identity를 생성 결과에서 한 번 pin한다. 복원은 기존 fresh candidate와 whole-operation guard를 유지한다.

운영값을 test fixture에서 복사하거나 관측하지 않은 UID/IP/CA/경로를 자동 선택하지 않는다. 합성 example만 코드에 두며 실제 protected plan/receipt와 비밀 파일은 source package에 넣지 않는다. lexical 경로 검사는 실제 symlink/volume/전체 백업 topology 증명이 아니므로 배포 probe에서 별도로 확인한다. HBA 정책은 PostgreSQL 신규 인증 경계이고 network packet filter를 입증하지 않는다.

## 영향과 검증

계약/schema/examples/pure parser/tests와 문서만 추가한다. 현재 registry API0.7.0/schema7, Go/SQL/Compose·credential API/runtime 공급·전체 production restore fence는 미변경이다. shape/raw parsing·UID/source/mount/backup 관계·fixed secret-safe error를 검증한다. 실제 운영 공급 준비와 activation은 다음 독립 단위다. 상세 사항은 [공급 계약](../../contracts/camera-credential-supply.md)을 따른다.
