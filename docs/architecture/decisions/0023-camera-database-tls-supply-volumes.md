# ADR0023 — TLS 후보와 프로세스별 전용 공급 볼륨

상태: 채택 · 2026-10-12 · 11-D1c

## 결정

사용자 소유의 0700/0600 D1a 후보를 그대로 UID999/65532 컨테이너에 디렉터리로 연결하면 읽을 수 없다. 원본 권한을 넓히거나 호스트 파일을 chown하지 않고 DB/runtime/maintenance용 파일만 전용 local named volume으로 복사한다. 소유권은 각각999:999, 65532:65532, 10002:10002이며 볼륨 root0700·파일0400으로 제한한다. 현재 API/DB process의 full UID/GID map·실제 실행 UID를 다시 확인하며 maintenance10002는 새 공급용 지정 identity다.

DB에는 ca.pem/server.pem/server.key, runtime에는 ca.pem, maintenance에는 ca.pem/maintenance.pem/maintenance.key만 공급한다. CA signing key·credential encryption key·DSN·API token·authority·HBA·PGDATA는 이 복사에 포함하지 않는다. 현재 DB의 immutable image ID를 사용한 network none·read-only 일회용 검사 프로세스에서 exact bytes·UID/GID map·소유권/권한·실제 EROFS와 다른 두 UID의 디렉터리 접근 거부를 검증한다. 초기 복사 helper에만 CHOWN/DAC_OVERRIDE를 추가하며 새 전용 볼륨 밖의 쓰기 경로는 없다.

공급 파일과 볼륨은 인수된 후보 receipt 및 공개 인증서 hash에 묶는다. 기존 이름의 볼륨은 label·local driver·options·identity와 실제 내용이 일치해야 한다. 기존 완전한 공급은 재검사하고 덮어쓰지 않는다. 중단으로 남은 불완전 파일/볼륨은 자동 수리하지 않는다. 일회용 helper는 정확한 이름과 소유 label을 확인해 제거하며 준비한 세 볼륨은 후속 전환에 재사용하도록 보존한다.

## 고정 주소 구성과 실행 경계

현재 프로젝트 소유의 IPv4 internal storage network를 읽고 D1a의 DB/runtime 제안 주소가 실제 두 컨테이너 주소와 같은지 확인한다. maintenance 제안 주소는 현재 peer·gateway·auxiliary reservation과 충돌하지 않아야 한다. 미래 recipe는 external network와 ipv4_address 및 세 외부 공급 볼륨을 명시한다. 현재 network의 주소를 예약하거나 컨테이너를 연결하지 않는다. 이는 현재 시점 관찰이며 이후 전환 직전에 다시 확인해야 한다.

생성한 Compose recipe는 /bin/true로 종료하는 구성 전용 서비스와 opt-in profile만 포함한다. 실제 camera 이미지·PGDATA·DSN·API/HBA 구성은 없으며 운영 배포 파일이 아니다. 도구는 Compose config만 호출하고 up/restart/network connect는 호출하지 않는다. 현재 .env·Compose·기존 서비스·DB schema·운영 TLS는 바꾸지 않는다. 현재 API0.7/schema7/TLS off 상태와 source/candidate/network/service identity를 전후 재검사한다.

## 검증과 후속

로컬 실제 합성 OpenSSL/SSL 및 파일·오류·재실행·Docker orchestration unit23개와 Python3.10/shell syntax를 검사했다. 로컬 Docker/별도 UID/RO 인수는 수행하지 못했고 서버 준비 도구의 native 결과를 받아야 한다. 공급 probe는 실제 PostgreSQL 인증·운영 runtime mount·고정 주소 예약·schema9·HTTP 활성화 인수가 아니다.

서버 공급 인수 이후 11-D1d에서 현재 schema7/registry 경로와 TLS 전환의 격리 리허설을 준비한다. 백업 추가 설계·검토는 사용자 요청에 따라 제외한다.

[공급 안내](../../operations/camera-database-tls-supply.md) · [진행 기록](../../progress/20261012-step11d1c-database-tls-supply.md)
