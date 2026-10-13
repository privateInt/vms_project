# ADR 0020: 자격증명 HTTP의 명시적 관리 주체·장치 권한

날짜: 2026-10-08 · 상태: 통합 구성요소 구현, 운영 미활성

## 배경과 선택

11-C1/C2의 HTTP는 신뢰된 principal resolver·transaction authorizer를 요구하지만 성공 테스트는 synthetic 구현이었다. 현재 실행 API의 공유 Bearer 토큰은 서비스를 보호할 뿐 사용자나 자격증명 관리 주체를 식별하지 못한다. 이번 11-C3는 실제 승인 저장소와 HTTP를 결합할 때 사용할 구체적인 로컬 서비스 클라이언트 정책을 추가한다.

직접 mTLS가 검증한 leaf 인증서 DER의 SHA256을 명시적인 scope·principal·device 허용 목록에 연결한다. Bearer는 기존 API의 별도 접근 조건으로 유지한다. 인증서 CN·요청 헤더·JSON의 주장으로 주체를 생성하지 않는다. 인증서만 CA 검증을 통과해도 등록된 exact leaf가 아니면 거부한다. 권한은 해당 장치의 자격증명 MANAGE에 한정하며 REFERENCE·복호화·장치 접속 권한을 포함하지 않는다.

단일 개발 주체의 무조건 허용이나 test callback을 실제 구성에 넣는 방식은 채택하지 않았다. 기업 IAM을 이번 단위에 구현하는 방식도 별도 배포·정책 계약이 필요하므로 후속으로 둔다. 현재 정책은 서비스 클라이언트용 로컬 허용 목록이며 사용자 로그인·기업 IAM·인증서 폐기 목록 검증의 대체물이 아니다.

## 구현 경계

CredentialManagementPolicy는 입력을 복사하고 중복 leaf·장치·wildcard·잘못된 식별자를 거부한다. 빈 목록은 모두 거부한다. 신뢰된 관리 코드의 Replace는 revision을 증가시키며 진행 중 요청의 이전 주체 snapshot을 무효화한다. 잘못된 교체는 이전 정책을 보존한다. 교체용 HTTP 경로는 없다. 기존 TLS 연결도 다음 요청부터 새 정책을 적용한다.

RegisterCredentialManagement는 구체적인 CredentialStore와 필수 usage guard를 받아 반환한 wrapper에 검증된 peer context를 봉인한다. 반환 handler를 신뢰된 직접 TLS listener에서 사용해야 한다. authorizer는 저장소가 전달한 실제 transaction과 요청 주체·scope·device·MANAGE·현재 정책 revision을 검사한다. 입장 확인과 데이터/예산 단계의 기존 재검증을 유지하며 미승인 저장소는 성공할 수 없다. 정책 교체와 이미 확인을 마친 DB commit 사이의 전역 원자성은 제공하지 않는다. 예산 예약 이후 권한 상실은 소비한 예산을 되돌리지 않는다.

main·현재 OpenAPI·운영 Compose·스키마·포트·키 공급은 변경하지 않는다. 자동 키 로딩·authority bootstrap·기본 unused guard는 없다. 운영 TLS/DSN/키/authority 공급, 기업 IAM, 관리된 참조·사용 관계의 실제 폐기 guard는 후속이다.

## 검증

단위·race 검사는 실제 mTLS socket과 CA-valid 미등록 leaf 거부, 인증서 없는 연결 거부, scope/device/MANAGE 제한, 정책 교체·동시 조회·입력 별칭 보호를 포함한다. 별도 native 검사는 disposable schema9·두 TLS 역할·UID10001·실제 RO key/authority·concrete admitted store에 같은 정책을 연결한다. native 성공은 전체 단계 transcript와 PASS·정리를 함께 확인한 뒤에만 인정한다. 현재 로컬의 제한된 UID/mount 환경은 native 성공 증거로 사용하지 않는다.

[통합 계약](../../contracts/camera-credential-management-http.md) · [진행 기록](../../progress/20261008-step11c3-admitted-credential-http.md)
