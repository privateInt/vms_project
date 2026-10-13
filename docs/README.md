# 문서 목록

| 문서 | 내용 |
|---|---|
| [Codex 이관](development/codex-handoff.md) | 현재 상태·첫 오류·환경·보존 기준·자동 개발 범위 |
| [Codex backlog](development/codex-backlog.md) | H01~H12 선행 조건·완료 기준·플랫폼별 테스트 화면 시점 |
| [Codex 시작 지시문](development/codex-start-prompt.txt) | 기존 프로젝트에서 재개할 때 전달할 지시문 |
| [최신 이관 기록](progress/20261012-codex-handoff.md) | 정리 서버 인수·D1e Compose 실패·기능 개발 중단 |
| [서버 evidence](progress/20261012-codex-handoff-server-evidence.json) | 사용자 제출 JSON 기반의 비밀값 없는 요약 |
| [전체 계획](architecture/architecture-plan.md) | 플랫폼·CCTV/XR·모델·운영 범위, 단계와 완료 기준 |
| [11-D1e image pin 수정/정리](progress/20261012-step11d1e-image-pin-fix-and-cleanup.md) | 정상 고정 image 수정·정리 도구 구현 이력; 서버 정리 완료, 최신 결과는 이관 기록 |
| [생성 자료 정리 안내](operations/project-artifact-cleanup.md) | 백업·로그·캐시·선택 UI 환경 제거와 source-only 압축, 실행 입력 보존 |
| [11-D1e 운영 TLS 준비](progress/20261012-step11d1e-registry-tls-preparation.md) | D1c 공급 재검사·TLS DSN·외부 control 구성 구현, 첫 apply Compose secret 검사 실패 |
| [운영 TLS 준비 안내](operations/camera-registry-tls-preparation.md) | 현재 source/image/UID/network/data 보존·동일 준비 재실행·운영 미전환 |
| [운영 TLS 준비 ADR0025](architecture/decisions/0025-camera-registry-tls-production-preparation.md) | schema7 전환 준비와 실제 실행 분리, 기존 supply와 새 control의 RO 공급 |
| [11-D1d 서버 인수](progress/20261012-step11d1d-server-acceptance.md) | Python45개·policy race/vet·native peer3/transport5·전환10·HTTP 게시4, 운영 TLS 미전환 |
| [11-D1d schema7 TLS 리허설](progress/20261012-step11d1d-registry-tls-cutover.md) | 기존 운영 image·registry 이력·TLS 전환·재생성의 서버 격리 인수 완료 |
| [11-D1d HTTP network 수정](progress/20261012-step11d1d-http-network-fix.md) | API 전용 HTTP망·actual port/source 검사4개, 수정 후 서버 전체 리허설 통과 |
| [11-D1d HTTP fixture ID 수정](progress/20261012-step11d1d-http-fixture-id-fix.md) | 첫 서버 seed 실패·고정 ID helper 결함 수정, Python32개/실제 Go HTTP 검사·서버 재인수 대기 |
| [schema7 TLS 리허설 안내](operations/camera-registry-tls-cutover-check.md) | 합성 자원·read-only 운영 관찰·cert map·실패/정리·10개 전환/5개 transport phase |
| [schema7 TLS ADR0024](architecture/decisions/0024-camera-registry-schema7-tls-rehearsal.md) | 개발 schema8과 운영 schema7 image 분리, 기존 migrator 인증서 CN 매핑 |
| [11-D1c DB TLS 공급 준비](progress/20261012-step11d1c-database-tls-supply.md) | 인수 후보·별도 UID/RO 볼륨·고정 주소 자료의 서버 준비 인수 완료 |
| [11-D1c 서버 인수](progress/20261012-step11d1c-server-acceptance.md) | Python23개·공급 probe3/UID 거부6·같은 SHA/볼륨 보존, 운영 미전환 |
| [DB TLS 공급 안내](operations/camera-database-tls-supply.md) | 실제 공급 경로·UID/RO·재실행·비밀 비공개·서비스 미전환 |
| [TLS 공급 ADR0023](architecture/decisions/0023-camera-database-tls-supply-volumes.md) | 현재 caller 소유 후보와 runtime별 private volume의 분리 |
| [11-D1b PostgreSQL TLS 경계](progress/20261012-step11d1b-database-tls-boundary.md) | 로컬 진단과 서버 Docker TLS/role/source·UID/RO·재생성 인수 완료 |
| [11-D1b 서버 인수](progress/20261012-step11d1b-server-acceptance.md) | Python18개·필수 Go8개·native9개 단계·race/vet·정리, 운영 TLS 미전환 |
| [DB TLS 격리 검사 안내](operations/camera-database-tls-boundary-check.md) | 합성 PKI·필수8개/phase9·정확한 인증 실패·source/secret/cleanup 경계 |
| [TLS 격리 ADR0022](architecture/decisions/0022-camera-database-tls-isolated-boundary.md) | 기존 public opener·새 내부 network·별도 RO 공급·운영 후보 보존 |
| [11-D1a DB TLS 후보](progress/20261008-step11d1a-database-tls-candidate.md) | private PKI 후보·실제 로컬/서버 mTLS·재실행 보존 인수 완료 |
| [11-D1a 서버 인수](progress/20261008-step11d1a-server-acceptance.md) | Python23개·TLS1.3·동일 후보/공개 인증서 hash·권한 보존, 운영 미전환 |
| [DB TLS 후보 준비 안내](operations/camera-database-tls-candidate.md) | 생성 위치·권한·검증·미예약 endpoint·운영 미전환 경계 |
| [TLS 후보 ADR0021](architecture/decisions/0021-camera-database-tls-candidate.md) | staging PKI 후보와 운영 공급/승인의 분리 |
| [11-C3 승인 저장소 HTTP 통합](progress/20261008-step11c3-admitted-credential-http.md) | 실제 관리 정책·admitted store/HTTP 서버 격리 인수 완료, 운영 미활성 |
| [11-C3 서버 인수](progress/20261008-step11c3-server-acceptance.md) | Python9개·Go192/567·필수47개·8개 phase·race/vet·정리 PASS |
| [관리 정책 ADR0020](architecture/decisions/0020-camera-credential-management-policy.md) | mTLS exact leaf·scope/principal/device MANAGE·명시적 정책 교체 |
| [관리 HTTP 통합 계약](contracts/camera-credential-management-http.md) | concrete admitted store·전체 lease·현재 정책 재검증·운영 미등록 |
| [관리 HTTP 격리 검사](operations/camera-credential-management-check.md) | schema9·UID/RO·두 역할 TLS·실제 HTTP·8개 phase·필수47개 |
| [자격증명 조회·폐기 HTTP](contracts/camera-credential-versions-http.md) | 11-C2 exact version·MANAGE 조회·폐기 usage guard·safe receipt |
| [11-C2 진행 기록](progress/20261008-step11c2-credential-versions-http.md) | 로컬/서버 인수·synthetic와 실제 승인 저장소 통합 구분 |
| [11-C2 서버 인수](progress/20261008-step11c2-server-acceptance.md) | Python9개·Go185/567·필수40개 PASS, 실제 승인 저장소/HTTP 성공 통합은 후속 |
| [자격증명 생성·교체 HTTP](contracts/camera-credential-write-http.md) | 11-C1 서버 인수, TLS·권한·strict 입력·safe receipt, 실행 경로 미등록 |
| [11-C1 진행 기록](progress/20261008-step11c1-credential-write-http.md) | 백업 추가 검토 제외·로컬 검증/서버 인수·후속 조회/폐기 |
| [11-C1 서버 인수](progress/20261008-step11c1-server-acceptance.md) | Python7개·Go170/494·필수25개 PASS, synthetic HTTP 성공과 native 저장소를 구분 |
| [운영 공급 사전점검](operations/camera-credential-supply-preflight.md) | 읽기 전용 구성·키 metadata·schema7/TLS 목록, 준비 부족과 활성화 불가 명시 |
| [11-B3c3d3 기록](progress/20261007-step11b3c3d3-production-supply-preflight.md) | 운영 inventory 서버 인수 완료·준비 부족11개 |
| [공급 계획 계약](contracts/camera-credential-supply.md) | 비밀값 없는 review-only 계획·UID/source·키 사본·authority/HBA snapshot 경계 |
| [ADR0019](architecture/decisions/0019-camera-production-supply-plan.md) | 설치 계획과 실제 승인/관측 영수증의 신뢰 경계 |
| [11-B3c3d4a 기록](progress/20261007-step11b3c3d4a-production-supply-contract.md) | 정적 공급 계약 서버 인수57개·점검 회귀31개 |
| [운영 공급 계획용 사실 조사](operations/camera-credential-supply-facts.md) | 숫자 process identity·volume/network metadata·키 소유자, 승인값 미확정 |
| [11-B3c3d4b 기록](progress/20261007-step11b3c3d4b-production-supply-facts.md) | 조사63개·실제 운영 Docker/volume/network 조회 서버 인수 |
| [공급 검토 초안 생성](operations/camera-credential-supply-review.md) | 현재 사실과 계약 필드 연결·null40개·미검증 후보·private 버전 보존 |
| [11-B3c3d4c 기록](progress/20261007-step11b3c3d4c-production-supply-review.md) | 초안 저장·테스트90개 서버 인수·미확정40개 유지 |
| [현재 프로세스 identity 검사](operations/camera-credential-process-identity.md) | init UID/GID·전체 identity map·cgroup·drift/permission 경계, 미래 binding 미승인 |
| [11-B3c3d4d 기록](progress/20261007-step11b3c3d4d-process-identity.md) | 실제 두 init process UID/GID·mapping·cgroup·namespace와32+90개 서버 인수 |
| [DB 볼륨 마운트 대조](operations/camera-credential-storage-topology.md) | O_PATH·mountinfo/own fdinfo·실제 volume source, complete backup topology 후속 |
| [11-B3c3d4e 기록](progress/20261007-step11b3c3d4e-database-mount-topology.md) | 서버 파일 적용 후 native mountinfo 테스트 실패·실제 볼륨 조사 미실행 |
| [11-B3c3d4e 첫 mountinfo 수정](progress/20261007-step11b3c3d4e-mountinfo-fix.md) | 서버 파일8개 적용·native 테스트36개 중 root canonical 오류1개, 실제 조사 미실행 |
| [11-B3c3d4e root 메타데이터 수정](progress/20261007-step11b3c3d4e-root-metadata.md) | 서버43+122개 통과·mountinfo369개 집계 인수; 실제 volume 조사는 host metadata 권한 부족으로 blocked |
| [11-B3c3d4f 경로 접근 진단](progress/20261007-step11b3c3d4f-storage-access-diagnostics.md) | 서버50+122개 인수; volumes 접근 EACCES·부모 docker root:root/0710 확인, volume blocked |
| [11-B3c3d4g 제한된 디렉터리 관찰](progress/20261008-step11b3c3d4g-directory-observer.md) | 서버192개·실제 sudo/root sender·ext4 volume mount 인수 완료, 권한·서비스 미변경 |
| [실제 PostgreSQL 저장 경로 관찰](operations/camera-database-storage-layout.md) | 고정 READ ONLY SQL·UID999의 stat/readlink; 컨테이너 경로와 미확인 host 후보 구분 |
| [11-B3c3d4h 기록](progress/20261008-step11b3c3d4h-database-storage-layout.md) | 서버 파일9개·테스트233개 통과, 실제 카탈로그 OID JSON 형식 오류로 저장 경로 관찰 실패 |
| [11-B3c3d4h OID JSON 수정](progress/20261008-step11b3c3d4h-oid-json-fix.md) | 서버8개 적용·44개 통과, 컨테이너 재확인 오류로 실제 관찰 실패 |
| [11-B3c3d4h 마운트 재확인 수정](progress/20261008-step11b3c3d4h-mount-recheck-fix.md) | 순서만 바뀐5개 마운트로 이전 오류 재현·실제 변경 거부·서버52개와 실제 관찰 인수 |
| [11-B3c3d4h 서버 인수](progress/20261008-step11b3c3d4h-server-acceptance.md) | PGDATA/WAL은 현재 볼륨 안·외부 테이블스페이스 없음·당시 미완료였던 host 대응은 d4i에서 인수 |
| [PGDATA·WAL 호스트 물리 대응 검사](operations/camera-database-storage-mapping.md) | 고정 두 경로 O_PATH·실제 mount/장치/inode 대조, 전체 백업 범위와 구분 |
| [11-B3c3d4i 기록](progress/20261008-step11b3c3d4i-physical-storage-mapping.md) | 로컬 26+248개 통과·서버 26+21개와 두 고정 디렉터리의 실제 물리 대응 인수 |
| [11-B3c3d4i 서버 인수](progress/20261008-step11b3c3d4i-server-acceptance.md) | PGDATA·WAL host_path_verified=true·실제 sudo/root sender 확인·전체 백업과 공급은 blocked 유지 |
| [백업·복원 경계 검토 초안](operations/camera-credential-backup-review.md) | fresh PGDATA/WAL·코드 선언 위치 8곳·미확정 22개·외부 제어 파일과 전체 snapshot 범위 후속 |
| [11-B3c3d4j 기록](progress/20261008-step11b3c3d4j-backup-boundary-review.md) | 로컬 30+137개·서버 30+90개 통과·실제 private 초안 생성/재실행 인수 |
| [11-B3c3d4j 서버 인수](progress/20261008-step11b3c3d4j-server-acceptance.md) | fresh 저장 경로 확인·8곳 후보/22개 미확정·동일 초안 SHA 보존·전체 준비 blocked 유지 |
| [작업 기준](development/working-standards.md) | 사용자가 지정한 폴더 구조와 코드 소유권 |
| [ADR 0001](architecture/decisions/0001-project-layout.md) | 단일 저장소 안의 독립 플랫폼 구조 |
| [ADR 0002](architecture/decisions/0002-http-foundation.md) | P0-A의 Go HTTP 실행 기반과 현재 한계 |
| [계약 설명](contracts/README.md) | 현재 구현한 입력 검증과 후속 런타임 계약 |
| [로컬 실행](operations/local-development.md) | Docker·Go 실행, 인증과 종료, 확인 절차 |
| [P0-A 작업 기록](progress/20260929-p0-foundation.md) | 구현·검증 결과와 다음 단계 |
| [단위 01 작업 기록](progress/20260929-step01-registry-contract.md) | 단계별 진행 원칙·등록 계약 확정·다음 단위 |
| [카메라 등록 계약](contracts/camera-registry.md) | Device·VideoSource 관계와 후속 생성·조회 규칙 |
| [ADR 0003](architecture/decisions/0003-camera-registry-contract.md) | 장치와 영상 소스의 등록 입력 분리 |
| [ADR 0004](architecture/decisions/0004-camera-postgresql.md) | PostgreSQL·pgx·명시적 트랜잭션 마이그레이션 |
| [카메라 저장소](operations/camera-storage.md) | 저장소 모듈·격리 검사·운영 활성화 경계 |
| [단위 02 작업 기록](progress/20260930-step02-camera-storage.md) | 저장소 구현·PostgreSQL 17.11 서버 격리 검증 완료 |
| [장치 API 운영 안내](operations/camera-devices.md) | 생성·조회·이름 수정·논리 삭제·멱등 처리·DB 연결·활성화 경계 |
| [단위 03 작업 기록](progress/20260930-step03-device-api.md) | 장치 API·PostgreSQL 17.11 서버 격리 검증 완료 |
| [카메라 활성화 안내](operations/camera-activation.md) | 영속 DB·계정·비밀·백업·전환과 복구 |
| [단위 04 구현 기록](progress/20260930-step04-camera-activation.md) | 전달 당시 구현·검증 기록 |
| [단위 04 서버 인수](progress/20260930-step04-server-acceptance.md) | 격리 검사·실제 장치 API 활성화 완료 |
| [소스 등록·조회](operations/camera-sources.md) | 생성·단건/목록 조회·페이지 구분·장치 필터·멱등 처리 |
| [단위 05-A 작업 기록](progress/20260930-step05-source-registration.md) | 소스 API 구현·격리 검사 전달, 실제 반영은 05-B |
| [단위 05 서버 인수](progress/20260930-step05-server-acceptance.md) | 소스 등록·단건 조회 운영 활성화와 재실행 검증 완료 |
| [단위 06-A 작업 기록](progress/20260930-step06-source-list.md) | 소스 목록·페이지 구분 구현, 서버 격리 검사 대기 |
| [단위 06 서버 인수](progress/20260930-step06-server-acceptance.md) | 목록 조회 운영 활성화 완료, 완료 기록 서버 적용 확인 |
| [장치 수정 계약](contracts/camera-device-update.md) | 이름 수정·version 조건·멱등 재생·오류 계약 |
| [단위 07-A](progress/20260930-step07a-device-update-contract.md) | 계약과 예제 확정, 서버 파일 적용 확인 |
| [단위 07-B](progress/20260930-step07b-device-update-storage.md) | 수정 저장소·스키마 4·PostgreSQL 17.11 격리 검사 통과 |
| [단위 07-C](progress/20260930-step07c-device-update-http.md) | 장치 수정 HTTP API·엄격한 입력 검사·응답 재생, 서버 격리 검사 통과 |
| [단위 07 서버 인수](progress/20260930-step07-server-acceptance.md) | 장치 수정 API·스키마 4 운영 전환 및 완료 기록 적용 완료 |
| [소스 수정 계약](contracts/camera-source-update.md) | 표시 이름 수정·프로필 보존·version 조건·멱등 재생 |
| [단위 08-A](progress/20260930-step08a-source-update-contract.md) | 소스 수정 계약·예제와 서버 파일 적용 확인 |
| [단위 08-B](progress/20260930-step08b-source-update-storage.md) | 소스 수정 저장소·스키마 5·PostgreSQL 17.11 서버 격리 검사 통과 |
| [단위 08-C](progress/20261001-step08c-source-update-http.md) | 소스 PATCH HTTP·엄격한 입력·재생 구현 기록 |
| [단위 08 서버 인수](progress/20261001-step08-server-acceptance.md) | 소스 수정 API·스키마 5 운영 전환과 완료 기록 적용 완료 |
| [소스 삭제 계약](contracts/camera-source-delete.md) | 논리 삭제·이력 보존·버전/재시도·사용 관계 보호 |
| [단위 09-A](progress/20261001-step09a-source-delete-contract.md) | 삭제 계약·예제·정적 검사, 서버 파일 적용 완료 |
| [단위 09-B](progress/20261001-step09b-source-delete-storage.md) | 삭제 저장소·스키마 6, PostgreSQL 17.11 서버 격리 검사 통과 |
| [단위 09-C](progress/20261001-step09c-source-delete-http.md) | 삭제 HTTP·등록 전용 정책·재생 구현 기록 |

계약의 기계 판독 원본은 `src/platform/<owner>/api`에 있다. 이 폴더에는 설명과 플랫폼 간 사용 원칙을 둔다.

| 문서 | 최신 진행 상태 |
|---|---|
| [단위 09 서버 인수](progress/20261001-step09-server-acceptance.md) | 소스 삭제·스키마 6 운영 전환 완료 |
| [장치 삭제 계약](contracts/camera-device-delete.md) | 자식·동시성·보존·오류·사용 관계 보호 규칙 |
| [단위 10-A](progress/20261001-step10a-device-delete-contract.md) | 계약·예제·정적 검사, 파일 적용 완료 |
| [단위 10-B](progress/20261001-step10b-device-delete-storage.md) | 장치 삭제 저장소·스키마 7, PostgreSQL 17.11 서버 격리 검사 통과 |
| [단위 10-C](progress/20261002-step10c-device-delete-http.md) | 장치 DELETE HTTP·등록 전용 정책·회귀 검사; 서버 HTTP 격리 인수·운영 전환 대기 |

| 문서 | 최신 추가 단계 |
|---|---|
| [11-B3b 키/DB 복원 리허설](progress/20261002-step11b3b-key-supply-restore-rehearsal.md) | 수정 후 native 8 phase 인수 완료, 운영 키/API 미활성 |
| [자격증명 복원 차단 계약](contracts/camera-credential-admission.md) | 11-B3c1 서버 인수, 11-B3c2 외부 상태/lease 기반 로컬 구현 |
| [ADR 0010](architecture/decisions/0010-camera-credential-admission.md) | 단일 호스트 외부 권위와 작업 구간 lease 선택 |
| [11-B3c1 진행 기록](progress/20261002-step11b3c1-admission-contract.md) | 정적 형태/예제 검사와 다음 외부 상태 구현 기준 |

| 문서 | 추가 상태 |
|---|---|
| [11-B3c2 외부 state/lease](progress/20261002-step11b3c2-external-state-and-leases.md) | strict parser·CAS·고정 lock·기록 내구성·다중 process 검사, 서버 mount 인수 완료 |
| [외부 admission 격리 검사](operations/camera-credential-admission-check.md) | 임시 Linux metadata volume·별도 UID·실제 RO reader, DB/키/운영 미변경 |
| [ADR 0011](architecture/decisions/0011-platform-streamlit-test-pages.md) | 플랫폼별 독립 API 테스트 화면·첫 Camera 페이지·확장 순서 |
| [Camera Streamlit 안내](operations/camera-streamlit-test.md) | 등록 CRUD·재시도·버전·서버 인수 기준 |
| [11-UI1 작업 기록](progress/20261007-step11ui1-camera-streamlit.md) | 외부 admission native 인수·첫 테스트 화면·서버 자동 검사·브라우저 보류 |
| [11-UI1a 작업 기록](progress/20261007-step11ui1a-python-environment.md) | UI 전용 venv·관찰된 공용 버전 복구·실제 pip 리허설·다음 통합 |
| [ADR 0012](architecture/decisions/0012-camera-admission-database-target.md) | 스키마8 유지·명시적 스키마9 표식·canonical migration hash |
| [Admission DB 격리 검사](operations/camera-credential-admission-database-check.md) | 실제 두 계정·표식/권한/이력·native dump 복원 |
| [11-B3c3a 기록](progress/20261007-step11b3c3a-admission-database.md) | DB 표식 준비·검증 범위·후속 키/profile/작업 구간 통합 |
| [ADR 0013](architecture/decisions/0013-camera-credential-endpoint-bindings.md) | 실제 키/단일 IP·TLS 영수증과 승인 값 비교 |
| [키·접속 binding 검사](operations/camera-credential-binding-check.md) | 임시 PKI·UID10001·RO bundle·두 계정의 실제 TLS 비교 |
| [11-B3c3b 기록](progress/20261007-step11b3c3b-key-endpoint-bindings.md) | DB native 인수·키/profile 비교·다음 작업 구간 lease |
| [작업 lease ADR](architecture/decisions/0014-camera-credential-operation-leases.md) | 최초 업무 DB IO부터 반환까지 같은 외부 승인 lease |
| [작업 lease 격리 검사](operations/camera-credential-operation-check.md) | 실제 UID/RO authority/TLS·maintenance drain/process death/fence |
| [11-B3c3c 기록](progress/20261007-step11b3c3c-credential-operation-leases.md) | B native 인수·전 작업 guard·다음 유지보수 복원 리허설 |
| [유지보수 DB 차단 ADR](architecture/decisions/0015-camera-maintenance-database-fence.md) | 외부 FENCED 아래 privileged DB gate·비협력 세션·prepared transaction 경계 |
| [유지보수 DB 차단 검사](operations/camera-credential-maintenance-check.md) | 새 control connection/lease 재시도와 native4개/7 phase 인수 기준 |
| [11-B3c3d1 기록](progress/20261007-step11b3c3d1-maintenance-database-fence.md) | C native 인수·DB 접속 차단 기반·다음 실제 복원 통합 |
| [유지보수 HBA 경계 ADR](architecture/decisions/0016-camera-maintenance-hba-boundary.md) | complete deny 정책·exact source/role·상호 TLS·실제 신규 인증 |
| [유지보수 접속 경계 검사](operations/camera-credential-boundary-check.md) | 서로 다른 source·UID10001/RO probe·필수5개/8 phase |
| [11-B3c3d2a 기록](progress/20261007-step11b3c3d2a-maintenance-hba-boundary.md) | d1 서버 인수·HBA 경계 검증·다음 실제 복원 통합 |
| [11-B3c3d2a 시작 수정](progress/20261007-step11b3c3d2a-startup-fix.md) | 공식 default socket 호환·TCP readiness·실패 peer logs 보존·서버 인수 완료 |

| [복원 후보 ADR](architecture/decisions/0017-camera-boundary-restore-candidate.md) | 독립 키·durable PREPARED·새 budget/marker 원자 반영·사용된 후보 reset 거부 |
| [경계 아래 실제 복원 검사](operations/camera-credential-boundary-restore-check.md) | 실제 TLS pg_dump/pg_restore·exact key 복원·15 phase·PREPARED 종료 |
| [11-B3c3d2b 기록](progress/20261007-step11b3c3d2b-boundary-restore-candidate.md) | d2a 서버 인수·이번 복원 후보 준비·후속 업무 재개 기준 |

| [11-B3c3d2b 환경 수정](progress/20261007-step11b3c3d2b-owner-environment-fix.md) | PG image defaults/strict opener 충돌 재현·명시적 owner 환경·서버 재검사 |
