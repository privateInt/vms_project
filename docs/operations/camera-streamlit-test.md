# Camera Streamlit 테스트 화면

상태: 11-UI1 서버 설치·자동 검사·기동 확인 완료 · 외부 작업으로 브라우저 인수 보류 · 11-UI1a 전용 환경 분리 준비

## 실행 전제

`src/platform/camera/test_streamlit/camera.py`는 독립 Streamlit 스크립트다. 같은 폴더 requirements.txt의 Streamlit 1.45.1과 Python 3.10 이상을 사용한다. 전용 venv는 var/test-streamlit/python에 생성하며 system-site-packages를 사용하지 않는다. 공용 sh_test나 Jupyter 실행 환경에 UI requirements를 설치하지 않는다. 적용·설치·검사·실행 명령은 패치 전달 채팅에 제공한다. 운영 API의 재빌드·재시작·DB 마이그레이션은 필요하지 않다.

화면 프로세스는 서버의 127.0.0.1:18501, Camera API 기본 주소는 127.0.0.1:18081을 사용한다. 원격 PC에서는 SSH 포트 전달로 화면에 접근한다. API 호출은 브라우저가 아니라 Streamlit 서버에서 나간다. 개발 테스트용이며 외부 공개·다중 사용자 인증·운영 IAM/TLS는 인수하지 않았다. 로그 수준은 warning으로 실행하며 debug 수준의 widget 기록에 토큰이 포함될 수 있으므로 사용하지 않는다.

## 연결과 화면 사용

1. 사이드바에 Camera API 주소와 기존 VMS_API_TOKEN을 입력하고 연결 확인을 누른다. 토큰은 password 입력이며 화면 세션에서만 사용한다. 환경 파일이나 실제 키 파일을 읽어 자동으로 채우지 않는다.
2. 정확한 공개 명세 digest, camera_registry readiness, 인증된 camera 버전 0.7.0-device-delete를 확인해야 CRUD가 활성화된다. API 주소·토큰 변경 시 기존 조회와 연결 확인 상태를 비운다.
3. 장치 또는 영상 소스를 선택한다. 목록은 개수·소스의 부모 장치 필터를 지원한다. 다음 페이지는 최초 조회의 필터·개수와 서버가 반환한 cursor를 사용한다. 새 조건은 목록 조회로 시작한다.
4. 신규 등록 ID는 세션별로 자동 생성하며 수정할 수 있다. 최근 장치/소스 ID를 기억한다. 소스는 부모 장치, 채널, 전송·촬영 방식, 1~8개 프로필을 입력한다. RTSP/PULL·WEBRTC/PUSH 조합을 전송한다. URL·비밀번호·영상 연결 입력은 없다.
5. 상세 조회 후 이름을 수정하거나 등록을 삭제한다. 버전은 int64를 정확히 전송하기 위해 텍스트로 표시한다. 삭제에는 조회한 ID 재입력과 체크가 필요하다. 장치에 미삭제 소스가 있으면 API가 거부하며 소스부터 개별 삭제한다.

## 변경 요청과 재시도

모든 변경은 폼 제출에서만 전송하며 자동 재시도하지 않는다. 직전 변경 영수증에는 origin·method·path·Idempotency-Key·JSON 본문을 표시한다. 토큰은 영수증에 포함하지 않는다. timeout·응답 유실·해석 실패·5xx는 결과 불명확 상태로 유지한다. 같은 요청의 재제출이나 직전 요청 그대로 재시도는 같은 키·본문을 사용한다. 불명확한 동안 다른 변경은 차단한다.

실제 API 응답·HTTP 상태·error code·request_id·Idempotency-Replayed를 확인한다. 성공 시 현재 조회 cache를 비운다. 과거 성공 응답이 재생되어도 삭제된 리소스가 현재 존재한다고 표시하지 않는다. 현재 상태는 상세/목록 조회로 확인한다. 409 버전 충돌은 상세를 새로 조회해 새 버전으로 제출한다. 실패 4xx는 API 계약상 성공 영수증을 만들지 않으며 동일 요청 재시도가 가능하다.

API 주소가 달라지면 원래 요청 재시도는 비활성화한다. 주소가 같아도 새 연결 확인이 필요하다. 직전 요청 종료는 현재 상태 확인 체크 후 명시적으로 실행한다. 재시도 기록은 세션 메모리에만 있으므로 브라우저 새로고침·세션 종료·프로세스 재시작 전에 필요한 영수증을 별도로 보관해야 한다. 이 화면에 디스크 저장·자동 복구 기능은 없다.

## 서버 인수 기준

Python 3.10 환경의 화면/HTTP 테스트 22개 통과와 Streamlit 프로세스 기동을 확인한다. 브라우저에서 연결·장치 TEST 등록/조회/이름 수정, 자식 소스가 있는 부모 삭제 거부, 소스 삭제 후 부모 삭제, 목록 제외·상세 404와 최초 요청 재생을 확인한다. 테스트 등록은 실제 운영 등록 DB에 저장되므로 자동 smoke가 운영 데이터를 생성하지 않는다. 삭제한 ID와 성공 이력은 API의 논리 삭제 정책에 따라 보존된다.

이번 패치 적용만으로 credential API·production admission·복원 차단·영상 runtime 준비 상태는 바뀌지 않는다.

## Python 환경 분리·복구

src/infra/tools/prepare_camera_test_environment.py는 적용 전 계획을 출력하며, apply 실행 시 전용 venv 생성·의존성 검사·화면/HTTP22개 검사를 수행한다. 기존 경로가 도구 관리 대상이 아니거나 symlink·공유 site-packages·다른 Streamlit 버전이면 덮어쓰지 않는다. 준비 로그와 보고서는 var/test-streamlit-setup.log와 var/test-streamlit-environment.json에 둔다. 이 도구는 UI를 계속 실행하거나 Jupyter/운영 서비스를 재시작하지 않는다.

restore-shared 옵션은 사용자 로그의 /home/shshin/miniforge3/envs/sh_test에서만 허용한다. 대상 세 패키지는 Streamlit1.45.1→1.50.0, cachetools5.5.2→6.2.1, protobuf6.33.6→7.36.0이다. 각각 이미 이전 버전이면 변경하지 않고, 다른 버전/환경이면 적용을 거부한다. 전용 UI 환경의 22개 검사가 끝나야 공용 환경 복구를 시작한다. 현재/이전 세 wheel을 모두 다운로드·hash 기록하고 환경을 재확인한 뒤 no-deps/no-index로 해당 버전만 복구한다. 다른 패키지는 resolver로 변경하지 않는다.

이전 Streamlit1.50.0도 protobuf<7을 요구한다. 기존 protobuf7.36.0과의 조합은 이미 불일치였으므로, 위 절차는 로그에 확인된 이전 버전 복구이지 공용 환경 전체 pip check 성공을 의미하지 않는다. UI는 별도 venv의 pip check 통과 상태를 사용한다. qwen-tts/transformers 등 기존 충돌은 이번에 변경하지 않는다.

공용 환경을 사용하는 Streamlit은 Ctrl+C로 종료한 뒤 복구한다. 복구 파일·영수증은 var/test-streamlit-recovery/step11ui1a-임의값 아래 보존한다. 패키지 설치 자체는 원자적이지 않아 중단/실패 시 일부만 반영될 수 있다. 실패를 성공으로 표시하지 않으며 실제 변경 여부가 확인되지 않으면 unknown으로 보고한다. 준비한 wheel과 receipt·private log로 재확인한다. 자동 package rollback이나 운영 DB 복원을 수행하지 않는다.
