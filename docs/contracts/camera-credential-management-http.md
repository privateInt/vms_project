# 자격증명 관리 HTTP의 승인 저장소 통합

11-C3는 [생성·교체](camera-credential-write-http.md)와 [버전 조회·폐기](camera-credential-versions-http.md)의 입력·상태 코드·safe receipt를 유지하면서 명시적 관리 정책을 연결한다. 실행 main에는 경로가 등록되지 않는다. 운영 인수 기준은 기존 API0.7.0-device-delete/schema7/registry-only-v1이다.

## 주체와 권한

직접 TLS1.2 이상·검증된 client certificate·등록된 exact DER leaf hash·별도 Bearer 토큰이 필요하다. 정책은 scope ID·principal ID·device ID 목록을 신뢰된 서비스 설정으로 제공한다. 외부 요청의 주체 헤더·CN·본문으로 설정을 덮어쓰지 않는다. TLS off·미검증 peer·만료 인증서·미등록 leaf·빈 정책은 거부한다. 인증서 없는 클라이언트는 mTLS handshake에서 거부된다.

허용된 장치의 자격증명 생성·교체·정확한 버전 메타데이터·폐기에는 MANAGE를 부여한다. device 권한은 credential ID wildcard 설정과 다르며 저장소의 실제 scope/device 결합을 함께 확인한다. 다른 장치·scope의 이력은 공개하지 않는다. 미등록 주체는 403, 저장소 내부 대상 권한 거부는 기존 C1/C2 계약에 따라 mutation409/metadata404다. 성공 재생도 현재 정책과 admission을 다시 확인한다.

정책 교체는 신뢰된 코드의 명시적 호출이다. 진행 중 주체 snapshot의 revision이 바뀌면 다음 authorizer 호출이 거부한다. 기존 TLS session도 새 요청에는 새 정책을 적용한다. 빈 교체는 모두 거부하며 잘못된 교체는 이전 정책을 유지한다. 정책 교체가 이미 권한 확인을 마친 transaction의 commit과 전역 원자적으로 결합되지는 않는다.

## 실제 저장소와 폐기 보호

RegisterCredentialManagement는 concrete admitted store와 명시적인 usage guard를 요구한다. 실제 key file receipt·RO authority·고정 lock·schema9 marker·migration history·writer/budget 역할·verify-full endpoint를 기존 저장소가 확인하며 전체 작업 lease를 유지한다. marker/역할/권한 상실이나 FENCED 상태에서는 생성·재생·조회·폐기를 거부한다. 초기 admission 실패는 새 행이나 암호화 예산을 만들지 않는다. 예산 예약 후 중단은 기존의 소비 보존 규칙을 따른다.

이번 native 테스트의 usage guard는 fixture의 InUse/Unknown/Unused 상태만 제공한다. 실제 폐기·재생·잠금 경로는 concrete store지만 운영의 참조·reservation·사용 해제 조회는 구현하지 않았다. default unused guard는 제공하지 않는다. 기업 IAM, 운영 인증서 수명·폐기 정책, ConnectionConfig와 관리 사용 관계는 후속이다.

## 서버 인수 — 2026-10-08

대상 서버에서 Python9개·Go192/567·필수47개·8개 native phase·race/vet·격리 정리가 통과했다. 실제 schema9·UID10001·RO key/authority·writer/budget TLS 역할과 concrete admitted store를 사용하는 관리 HTTP 성공 및 권한/marker/FENCED 차단을 인수했다. native_admitted_store_http_writes_verified/native_admitted_store_version_http_verified는 C3 범위에서 true다. C1/C2 synthetic 회귀의 표시와 과거 인수 revision은 유지한다.

운영 서비스·DB·키·admission·HTTP 활성화는 없으며 운영 usage guard·기업 IAM은 미구현이다. [C3 서버 인수](../progress/20261008-step11c3-server-acceptance.md)가 이번 근거와 범위를 설명한다.

[ADR0020](../architecture/decisions/0020-camera-credential-management-policy.md) · [검사 안내](../operations/camera-credential-management-check.md)
