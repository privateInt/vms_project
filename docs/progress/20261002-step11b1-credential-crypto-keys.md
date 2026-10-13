# 단위 11-B1 — 자격증명 암호화·키 준비 기반

작성일: 2026-10-02 · 독립 코드·호스트 도구 검증 완료 · 서버 파일/키 준비 인수 전

## 선행 서버 결과 인수

사용자 로그에서 11-A 패치 applied·written=6·pending=0, 백업 `var/patch-backups/step11a-3dynxyi_`를 확인했다. service_restart_performed·runtime_activation_required·database_schema_modified는 false다. [11-A 계약](20261002-step11a-connection-config-contract.md)의 서버 파일 적용 대기가 해소됐다.

직전 운영 인수는 camera 0.7.0-device-delete·P1_DEVICE_DELETE·스키마 7·registry-only-v1이다. device-delete 최초 전환 activated·재실행 already_activated를 확인했고 business_runtime_ready=false였다. 이번 11-A 파일 적용 로그를 새 런타임 직접 조회나 접속 기능 활성화로 확대하지 않는다.

## 이번 구현

11-B를 B1 암호화/키 기반과 B2 DB 영속화로 나눴다. 이번에는 다음 신규 9개 파일과 프로젝트 명세 1개 변경을 전달한다.

- camera 내부 credentialcrypto의 keyring.go·crypto.go와 관련 Go 검사 2개
- 호스트 키 준비 도구와 Python 검사 1개씩
- ADR 0006·키 운영 문서·이 진행 기록

기존 258개 중 project-manifest.json만 갱신하고 나머지 257개 파일의 바이트를 보존한다. 파일 명세에는 새 Go/도구/문서와 후속 서버 인수 기록을 포함한다. 버전·stage·기존 storage/HTTP revision·스키마 7은 유지하고 전달 단계·검증된 이전 서버 버전과 기능 미구현 상태를 명시한다.

AES-256-GCM random nonce·자원/버전/대상 정책/사용 순번의 AAD 결합·정확한 이전 키 선택을 구현했다. 멱등 비교는 별도 키의 HMAC-SHA256과 주체·Method·Path·멱등 키 hash·canonical 요청 의미를 결합한다. 비밀/키의 일반 포맷은 redacted이고 JSON 직렬화는 거부한다. 기본 파싱은 중복/별칭/알 수 없는 키·잘못된 형식/키 이력/목적 재사용을 거부한다.

키 준비 도구는 소유자 전용 파일·디렉터리, 링크/타입/경쟁 검사, 원자적 최초 생성만 구현한다. 재실행 시 기존 키를 그대로 확인한다. 서비스·DB·환경 파일·기존 운영 기록을 변경하지 않으며 API에서 아직 이 모듈을 import하거나 키를 읽지 않는다.

## 검증 증거

| 검증 | 결과·범위 |
|---|---|
| Go 1.25 관련 race 검사 | 상위 검사 15개·하위 사례 77개 통과, 암호화/HMAC·키 파싱·변조/컨텍스트 교환·동시 호출 |
| 전체 Go vet | src/platform의 전체 패키지 통과 |
| Python 키 준비 검사 | 20개 통과, 생성/재실행·바이트/권한 보존·symlink/hardlink/FIFO·경쟁/중단·유효 이력·복원·비밀 없는 오류 |
| Python→Go 상호운용 | 임시 준비 키를 Go가 파싱하고 합성 암호문/HMAC을 기록, 복사한 키와 별도 프로세스로 복원 검증 |
| 패치 적용 도구 | 8개 통과, 충돌/변조/링크 거부·중간 실패 원복·백업/재적용 |
| 전체 패치 격리 적용 | 기준 258개·변경 10개, 최초 10개/재실행 0개, 원본 명세 백업·기존 파일/합성 환경/운영 기록의 바이트·권한 보존 |
| 정적 전달 검사 | Python 3.10 문법·gofmt·문서 상대 링크·명세 전체 hash·압축본 payload/경로 일치 |

암호화 검사에는 fake 키와 합성 비밀만 사용했다. 최대 길이의 JSON escape 입력도 복호화된다. 키 부재는 다른 키로 대체하지 않고 실패하며 잘못된 인증에 원문 비밀을 반환하지 않는다. 키 이력을 유지한 primitive 교체/rewrap과 격리 복원을 검증했지만 운영 키 교체·DB pg_dump 복원을 인수한 것은 아니다.

기존 HTTP/SQL/프로세스 경계에 변화가 없어 기존 Docker 전환·DB 리허설·smoke를 반복하지 않았다. 새 스키마·DB 자격증명 저장·런타임 loader·인증/대상 승인·HTTP 원문 비밀 입력·키별 전역 사용량 기록은 미구현이다. 이번 패치는 서비스/DB/환경을 활성화하지 않는다.

## 인수 경계와 다음 단위

호스트 키 파일은 아직 API에 mount되지 않는다. 현재 키 준비 성공은 준비 파일의 검사이며 비밀 저장·장비 연결 가능 상태가 아니다. Secret 힙 완전 제거, 호스트 전체 침해 방어, 실제 네트워크/장비 인증도 보장하지 않는다.

새 Go 파일을 명세에 포함하면서 checked_revision이 달라진다. 10-D2/10-D3 당시 기록은 역사적 증거로 보존하고 새 소스의 재활성화 증거로 사용하지 않는다. 자세한 보존 규칙은 [키 운영 문서](../operations/camera-credential-keys.md)에 기록했다.

다음 작은 단위는 **11-B2 자격증명 DB 저장소**다. 불변 비밀 버전·장치/대상 범위·권한·폐기와 부모 삭제 보호, 비밀 없는 성공 journal, canonical DTO 지문, durable 키 사용량 예약과 복원 후 고수위/새 키 정책, 보호된 키 loader를 먼저 구현·격리 검증한다. 운영 교체·보호된 백업 복구와 API/접속 설정 연결은 후속 단위로 진행한다. business_runtime_ready=false를 유지한다. 이번 서버 적용/키 준비 결과는 아직 대기 중이며 실행 명령은 채팅으로만 제공한다.
