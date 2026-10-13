# 운영 자격증명 공급 계획 계약 v1 — 11-B3c3d4a

상태: planned · 정적 검증 구현/로컬 검증 완료 · 실제 운영값·공급·활성화는 미완료

계약 원본은 src/platform/camera/api/planned/credential-supply.schema.json, 합성 예제는 credential-supply.examples.json이다. credential_supply_contract.py의 parse_supply_profile은 UTF8 bytes를 최대32768로 제한하고 shape·관계를 검증한다. 성공 결과는 intent=review-only인 설치 계획이며 approved binding, admission Record, bootstrap receipt, runtime configuration 또는 activation authorization이 아니다. 현재 HTTP API에 연결하지 않는다.

## 계획의 구성

| 영역 | 필수 선언 | 후속 실제 검증 |
|---|---|---|
| inventory_basis | 관측 source SHA·API0.7.0·schema7 | 현재 조회 영수증·코드·image·DB와의 일치; 과거 관측만으로 전환 허용 불가 |
| database | vms_camera·schema9 목표·canonical 단일 IP/port·host/container data path·server UID·HBA/server cert/key RO file mount | 실제 volume/process UID·권한·TLS·schema/grants·HBA 설치/reload 및 신규 인증 |
| tls | verify-full·TLS1.2 이상·server name·단일 CA file과 exact PEM 예상 SHA | 기존 Go constructor가 실제 한 CA 인증서를 파싱/해시하고 실제 peer/chain/name을 확인; caller hash 대입 금지 |
| maintenance | 별도 UID/source IP·camera_maintenance·postgres control DB·target/control DSN 및 client cert/key file 참조·CN=camera_maintenance | 실제 관리 인증·권한·source·같은 endpoint의 대상 DB/관리 DB 접속 |
| runtime | nonroot UID/GID·별도 source IP·고정 writer/budget 역할의 두 DSN file·RO rootfs·capabilities 없음·no-new-privileges·PG 환경 거부 | 실제 EUID/GID/capabilities/namespace/source·두 TLS pool·public whole-operation lease |
| key_supply | 기존 source file/owner UID/예상 SHA·별도 runtime directory RO mount·runtime UID 소유 0500/0400 정책 | 기존 파일 보존·exact byte 사본·owner/mode/no-link/실제 RO mount·protected loader receipt 및 hash 일치 |
| authority | 별도 host/container directory·관리 UID 소유/런타임 GID·0750/0640·runtime RO/maintenance RW·최초 FENCED bootstrap·독립 lock receipt file | 실제 local filesystem/no-follow/권한/안정 lock; 단 한 번 얻은 device/inode를 별도 신뢰 설정에 pin |
| declared_snapshot_roots | 검토한 추가 backup/restore 포함 경로들 | 실제 백업 대상·destination·volume·mount/symlink topology와 복원 도구의 포함 범위 검토 |

DSN·password·token·PEM·private/encryption/HMAC key bytes는 계획에 넣지 않는다. 역할별 DSN의 내용은 이후 protected file에서 읽고 기존 Go opener의 정확한 role/password/address/port/database/sslmode 비교를 사용한다. 현재 camera_runtime DSN을 두 자격증명 역할의 DSN으로 재사용하지 않는다. 파일 참조는 해당 container의 RO mount에만 연결하고 runtime 파일은 runtime UID, 관리 DSN/client private key는 maintenance UID의 private 파일로 준비한다. server private key는 검토한 server UID/권한에 맞춘다. 실제 파일 생성 도구는 아직 없다.

## 정적 제약과 실패 코드

모든 object는 unknown field를 거부한다. UUID/record generation/OPEN state/lock inode/activation flags를 계획에서 지정하지 않는다. decimal/exponent/non-finite 숫자와 duplicate/escaped-alias field를 raw parser에서 거부하고, direct object validator도 integer field의 정확한 int type을 확인한다. 입력 원문이나 schema error detail을 반환하지 않고 SUPPLY_* 고정 코드만 반환한다.

IP는 canonical IPv4/IPv6 하나이며 DNS·다중 target·zone·unspecified·multicast·IPv4-mapped IPv6를 허용하지 않는다. 두 source는 서로 다르고 endpoint와 같은 address family다. TLS server identity는 기존 constructor와 같은 lowercase DNS 또는 canonical IP 형태를 따른다. DNS server identity와 접속 IP는 별개 선언이며 실제 certificate 검증은 후속 단계다.

경로는 canonical absolute Linux path이며 URI·공백/control character·dot/parent segment·중복 slash를 거부한다. source key와 runtime key directory가 겹치면 기존 파일을 chown/retag할 수 있으므로 거부한다. authority와 별도 lock receipt는 project/data/source-key/runtime-key/declared-snapshot 범위 양방향 밖이어야 한다. lock receipt를 authority directory 안에 넣지 않는다. DB의 HBA/CA/server cert/key는 host에서 같은 snapshot 범위 밖, container에서 data directory 밖이어야 한다.

같은 container의 mount parent/child 중첩과 서로 다른 비밀 파일의 host alias/경로 중첩을 거부한다. shared CA와 authority는 서로 다른 container에서만 같은 참조를 공유한다. 단순 문자열 prefix가 아니라 경로 component의 ancestry를 비교한다. maintenance UID=runtime UID, authority owner≠maintenance UID, authority group≠runtime GID를 거부한다.

이 검사는 실제 경로를 열거나 symlink/mount·파일 ownership·해시·TLS·프로세스·DB·백업을 확인하지 않는다. declared_snapshot_roots가 실제 모든 snapshot을 포함한다는 보장도 없다. static hash와 read_only=true는 검토할 주장이고 실제 영수증을 대신하지 않는다. 환경·파일·키·승인 상태·서비스·DB를 수정하지 않는다.

## 예제와 운영 연결

예제의 documentation IP, example 경로, UID999/1000/65532, dummy hash는 운영값으로 선택한 것이 아니다. schema 검사만으로 예제를 설치하거나 복사하지 않는다. 11-B3c3d3에서 관측한 configured_uid65532도 actual EUID 인수가 아니며, 현재 source key의 숫자 UID·DB process UID·source IP·CA·authority 경로는 새로 검토해야 한다.

후속 공급 준비는 현재 원본 bundle과 DB의 상태를 보호된 read-only probe로 확인한 뒤 계획을 채우고 검토한다. 최초 빈 deployment인지 확인한 다음 외부 authority를 FENCED로 bootstrap하고 안정 lock 영수증을 pin한다. runtime용 키/DSN/CA 공급 및 실제 mount·UID·TLS/source·DB/marker/grants를 검증한 뒤 별도 schema9 rehearsal/cutover와 credential API 통합을 진행한다. OPEN 의도와 실제 역할/업무 재개 순서는 기존 d2c primitive를 유지한다. 복원 이후에는 새 독립 key/incarnation/budget 및 변경된 binding의 통제된 검토가 필요하다. 자동 bootstrap·기존 budget reset·automatic restore를 허용하지 않는다.
