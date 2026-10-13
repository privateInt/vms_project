# 로컬 실행과 확인

## 준비

Python 3.10 이상과 Docker Engine/Compose v2.20.0 이상, 또는 Go 1.25 이상이 필요하다. 단위 02부터 카메라 저장소에 pgx/v5 의존성이 추가되었다. Go 모듈과 checksum은 go.mod/go.sum으로 관리한다. Docker 빌드는 공식 Go builder 이미지를 다운로드하므로 이미지 저장소 접근이 필요하다. 제작 환경의 실측 검증은 Go 직접 실행이며 Docker 검증은 대상 환경에서 수행한다.

```bash
cd /home/shshin/workspace/vms_project
python3 src/infra/tools/setup_env.py
```

`.env`는 배타적으로 생성하며 기존 파일을 덮어쓰지 않는다. 파일 권한은 0600이고 토큰을 출력하지 않는다. `.env.example`을 직접 복사했다면 placeholder를 실제 무작위 토큰으로 교체해야 한다. 각 API는 24 byte 미만·placeholder·앞뒤 공백 토큰으로 실행되지 않는다.

## 전체 또는 단일 플랫폼 실행

```bash
docker compose --env-file .env up -d --build
docker compose --env-file .env ps
python3 src/infra/tools/smoke.py
docker compose --env-file .env down
```

특정 플랫폼만 독립 실행할 수 있다. 아래 카메라 단독 명령은 초기 DB 비활성 기반 검사에 사용한다. 단위 04 활성화 후 상시 DB를 사용하는 camera는 루트 vms-project 구성으로 관리한다. 전체 Compose와 같은 호스트 포트를 동시에 사용하지 않는다.

```bash
cd src/platform/camera
docker compose --env-file ../../../.env up -d --build
docker compose --env-file ../../../.env down
```

초기 기본 바인딩은 loopback이다. 원격 접근은 `.env`의 바인딩 주소·방화벽·TLS 종료 경로를 배포 환경에 맞춰 설정한다. 현재 토큰은 개발용이고 테넌트·권한·토큰 갱신·감사 체계는 아직 없다. 앱의 health·OpenAPI는 인증 없이 읽을 수 있다.

## Go 직접 검증·실행

```bash
make test
make vet
make smoke
make build
set -a
. ./.env
set +a
HTTP_ADDR=127.0.0.1:18081 ./build/camera-api
```

`Ctrl+C` 또는 SIGTERM으로 종료한다. API는 신규 업무 요청을 거부하며 최대 5초의 종료 시간을 준다. 빌드된 바이너리는 `--healthcheck` 옵션으로 해당 `HTTP_ADDR`의 readiness를 확인할 수 있다.

Go가 다른 경로에 있다면 `make test GO=/path/to/go`, `make smoke GO=/path/to/go`를 사용한다. race 검증에는 지원되는 플랫폼과 C toolchain이 필요하다. `smoke.py --launch`는 일회용 토큰을 별도로 생성하고 네 서비스의 임시 실행 후 종료까지 확인한다.

## API 예제 보내기

아래 명령은 `.env`를 읽어 토큰을 요청 헤더에 사용하고 응답만 출력한다. 입력 예제는 실장비 정보가 아니다.

```bash
python3 - <<'PY'
import importlib.util
from pathlib import Path
import json
spec = importlib.util.spec_from_file_location('smoke', Path('src/infra/tools/smoke.py'))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
env = smoke.read_env()
body = json.loads(Path('src/platform/camera/api/examples/source-xr.json').read_text())
status, result, _ = smoke.call('http://127.0.0.1:'+env.get('VMS_CAMERA_PORT','18081'),
    '/api/v1/sources/validate', env['VMS_API_TOKEN'], body)
print(status, json.dumps(result, ensure_ascii=False, indent=2))
PY
```

기본 Compose와 DB 미설정 모드의 health는 HTTP 기반만 확인한다. 단위 03부터 camera-api에 CAMERA_DATABASE_URL을 명시하면 장치 저장·조회와 DB 이력/권한 readiness를 사용한다. 단위 04 활성화 도구가 .env에 구성 선택자를 추가하면 루트 Compose는 DB 연결 모드를 유지한다. 아직 활성화하지 않은 초기 구성에서는 위 기본 명령만으로 장치 기능을 활성화하지 않는다. 서버 검사와 전환·복구 절차는 [활성화 안내](camera-activation.md)를 따른다. 세부 설정·권한·API 계약은 [장치 API 안내](camera-devices.md)를 따른다. 어떤 모드에서도 health는 실장비·영상·추론 준비를 보장하지 않는다. 직접 DB 통합 검사를 실행할 때는 패키지 순차 실행이 필요하며 Makefile과 격리 검사 도구에 이를 반영했다.
