# 카메라 장치 API의 상시 DB 활성화

단위 04 서버 인수는 완료됐다. 이 문서는 단위 04 전용 도구의 운영 기록이다. 단위 05-A의 소스 API 패치에는 이 도구를 재사용하지 않으며 05-B에서 새 스키마 전환 절차를 별도로 전달한다.

단위 04는 장치 등록 API를 기존 camera 서비스에 연결하는 적용 단위다. 단위 03의 PostgreSQL 17.11 인수를 선행 조건으로 한다. 개발용 공유 Bearer 인증은 유지한다. 영상 입력·추론·관제 준비를 의미하지 않으며 business_runtime_ready=false를 유지한다.

진행은 04-A 패치·서버 격리 검사와 04-B 실제 활성화로 나눈다. 이번 전달은 04-A까지이며 서버 검사 결과를 확인한 다음 실제 전환을 진행한다. 아래 절차는 두 단계의 전체 운영 흐름을 설명한다.

## 구성과 범위

| 구성 | 역할 |
|---|---|
| camera-db | PostgreSQL 17.11, vms_camera DB, 프로젝트 소유 camera-data 영속 볼륨 |
| camera_admin | 최초 DB/역할 생성, 운영 도구의 DB 백업 |
| camera_migrator | camera 스키마 소유와 DDL, 플랫폼 전용 DB의 CONNECT/CREATE 권한 |
| camera_runtime | camera 스키마 USAGE, 이력 SELECT, devices/멱등 기록 SELECT·INSERT |
| camera-migrate | 별도 일회성 명령, 스키마 적용 후 고정 runtime 역할에 필요한 권한 부여 |
| camera-api | 기존 HTTP 주소·토큰을 유지하고 DB 파일 비밀을 읽어 장치 API 활성화 |

DB는 camera-storage 내부 Docker 네트워크만 사용하고 호스트 포트를 열지 않는다. camera API는 기존 기본 네트워크와 DB 네트워크에 연결된다. 다른 플랫폼은 DB 네트워크에 추가하지 않는다. 영속 볼륨의 기본 이름은 vms-project_camera-data다. 데이터와 역할은 PostgreSQL 공식 초기화 절차가 빈 볼륨에서 한 번 생성한다. 비어 있지 않은 DB를 자동 초기화하지 않는다.

camera Docker 이미지에 API와 별도 마이그레이션 바이너리를 포함한다. API 시작에는 DDL을 실행하지 않는다. 현재 스키마 버전은 2이며 기존 SQL 파일은 변경하지 않았다. 명시적 마이그레이션 성공 뒤 runtime 권한을 별도 트랜잭션으로 부여한다. 권한 부여 실패 시 이미 적용된 스키마를 자동 삭제하지 않고 활성화를 중단한다.

## 비밀과 설정 보존

도구는 var/camera/secrets에 관리자·마이그레이션·런타임 비밀번호와 두 DB URL을 생성한다. 비밀번호는 무작위 값이다. 이 폴더와 상위 camera 상태 폴더는 소유 사용자 전용 0700이다. 개별 마운트용 파일은 0444로 두어 UID 65532인 컨테이너 API가 읽을 수 있게 한다. 호스트의 다른 사용자는 비공개 부모 폴더를 통과할 수 없다. Compose의 파일 secret은 bind mount이므로 uid/gid/mode 재매핑에 의존하지 않는다.

API와 마이그레이션은 CAMERA_DATABASE_URL_FILE을 읽는다. 값·본문·DB URL을 로그에 출력하지 않는다. 기존 CAMERA_DATABASE_URL 직접 설정도 지원하지만 두 설정이 동시에 존재하면 중단한다. API 컨테이너에는 런타임 URL 파일만 전달하며 관리자/마이그레이션 비밀번호를 전달하지 않는다.

기존 비밀은 재생성하지 않는다. 일부 파일만 남았거나 권한·URL 조합이 다르면 중단한다. 기존 영속 볼륨에 대응하는 비밀이 없을 때도 새 비밀번호를 덮어넣지 않는다. 이 파일들은 DB dump와 함께 별도 보호·백업해야 한다. 비밀 교체·분실 복구는 이번 자동화 범위 밖이다.

기본 compose.yaml은 비활성 camera 구성으로 시작한다. 활성화 도구가 준비·백업·마이그레이션을 완료한 뒤 기존 .env의 토큰·포트·나머지 값을 보존하고 VMS_CAMERA_COMPOSE_FILE=./src/platform/camera/compose.active.yaml 한 줄을 추가한다. 이미 같은 설정이면 유지한다. 다른 Compose 경로·프로젝트·이미지 사용자 설정이나 override 파일이 발견되면 자동으로 덮어쓰지 않는다.

## 실행 순서와 검증

패치 적용 명령과 실제 실행 명령은 채팅에서 제공한다. 구현 파일은 src/infra/tools에 있다.

1. test_camera_activation.py가 정확한 프로젝트 파일 해시와 로컬 Docker 연결을 확인한다. 먼저 기존 Go/API/DB 일반 PostgreSQL 검사를 실행한다.
2. 별도 임시 디렉터리·무작위 Compose 프로젝트·포트·토큰·DB 볼륨에서 활성화와 재적용을 수행한다. 다른 세 플랫폼 대신 검사 전용 컨테이너를 두어 ID·시작 시각이 유지되는지 확인한다.
3. 의도적으로 camera 전환 실패를 주입해 이전 설정·이미지 복구를 확인한다. 테스트 장치를 생성하고 DB와 API 컨테이너를 교체한 뒤 같은 장치·멱등 응답이 남는지 확인한다. DB dump를 같은 임시 PostgreSQL의 별도 DB에 복원해 장치가 존재하는지 검사한다.
4. 임시 프로젝트와 볼륨을 제거한 뒤 성공 증빙을 var/camera/activation-check.json에 기록한다. 이미지/빌드 캐시는 재사용을 위해 남는다. 실패·정리 미완료는 성공으로 기록하지 않는다.
5. activate_camera_registry.py는 apply 옵션과 동일 코드·Docker 서버의 검사 성공 기록이 있어야 실행된다. 활성화 잠금으로 중복 실행을 막고 기존 프로젝트 컨테이너의 소유 경로를 확인한다.
6. camera 이미지만 빌드하고 camera DB만 시작한다. API 전환 전에 DB custom-format dump를 생성하고 pg_restore로 목록을 읽어 파일 형식을 확인한다. 마이그레이션·권한 부여 후 camera API만 재생성해 readiness·인증 조회·기능 상태를 확인한다.

활성화 도구는 기존 camera HTTP 주소·토큰을 사용한다. HTTP 확인은 프록시와 리다이렉트를 사용하지 않는다. 최초 이미지/모듈 다운로드·빌드는 시간이 걸릴 수 있다. 실제 camera 전환 중에는 해당 API에 잠깐의 중단이 있을 수 있다. 모델·분석·운영 서비스의 시작/재시작 명령은 실행하지 않으며 전후 컨테이너 ID·이미지·시작 시각·재시작 횟수를 비교한다.

## 백업과 실패 복구

var/camera/activation-backups/step04-*에 변경 전 .env, 컨테이너 식별 정보, camera.pgdump와 결과를 보관한다. 폴더는 0700, 백업 파일은 0600이다. DB dump는 해당 DB의 일관된 스냅샷이며 전역 역할·비밀번호·컨테이너 이미지 백업은 아니다. 비밀 파일과 프로젝트 코드/이미지 정보를 별도로 보존한다.

전환 실패 시 기존 camera 이미지 ID로 이미지 태그와 camera 설정을 복구한다. 도구가 쓴 .env 이후 사용자 수정이 확인되면 그 파일을 덮어쓰지 않고 manual_recovery_required로 중단한다. camera가 원래 없었다면 도구가 만든 camera API 컨테이너만 제거한다. 기존 DB 데이터·새 영속 볼륨·비밀은 실패해도 남긴다. 자동 DB 복원이나 운영 볼륨 삭제는 수행하지 않는다.

복구 결과는 previous_camera_configuration_restored 또는 manual_recovery_required로 기록한다. 전자는 이미지·실행 상태 복구 확인이며 과거 애플리케이션의 모든 기능을 재검증했다는 뜻은 아니다. 수동 복구가 필요하면 기록의 백업 디렉터리와 오류를 기준으로 원인을 확인한다. 재적용은 같은 비밀을 사용하고 적용된 마이그레이션을 건너뛴다.

## 현재 검증 경계

단위 03의 서버 인수는 완료됐다. 단위 04는 제작 환경에서 Go·WASM 통합, Python 실패 복구/보존 검사, 공식 Compose 구성 해석을 검증했다. Docker 엔진이 없어 실제 이미지 빌드·초기 DB 역할 생성·볼륨 재생성·백업 복원·운영 전환은 사용자 서버의 위 검사와 활성화 결과가 필요하다. 호스트 재부팅·정기 백업 스케줄·외부 DB 복원 자동화는 포함하지 않는다. 운영 활성화 후에는 루트 vms-project Compose 구성을 기준으로 관리한다.

참고: Docker 공식 [include](https://docs.docker.com/compose/how-tos/multiple-compose-files/include/), [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/), [서비스 secret 속성](https://docs.docker.com/reference/compose-file/services/). 실제 선택·권한·검증 범위는 이 프로젝트의 구성과 진행 기록을 따른다.
