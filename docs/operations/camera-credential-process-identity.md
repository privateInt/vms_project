# 현재 컨테이너 실행 identity 조사 — 11-B3c3d4d

src/infra/tools/inspect_camera_credential_identity.py는 d4c 서버 인수 후 camera-api와 camera-db의 현재 init process UID/GID를 검증한다. 기존 읽기 전용 운영 조사를 새로 수행하고 Docker가 지정한 PID를 실제 호스트 procfs metadata와 대조한다. 결과는 현재 프로세스의 관측 증거이며 향후 credential runtime의 보호된 binding 영수증이 아니다. 기존 공급 초안의 null이나 승인 설정은 변경하지 않는다. 실행 명령은 전달 채팅에서 제공한다.

| 검사 | 검증 범위 |
|---|---|
| accepted source·현재 운영 inventory | 전체 source hash·d4c 인수, API0.7.0-device-delete/schema7, 이전 활성화 receipt·image·기존 READ ONLY DB query |
| Docker init process | 프로젝트 소유 container ID/image·Running·StartedAt·State.Pid·독립 PID namespace(PidMode 빈 값), numeric top의 해당 PID/effective UID/GID |
| 실제 procfs와 검사자 | Linux fstatfs의 procfs magic, /proc/self PID view·실제 검사자 UID/GID·전체 identity mapping |
| 대상 metadata | status의 Pid/NSpid(init의 내부 PID1)·real/effective/saved/filesystem UID/GID, uid_map/gid_map, stat의 starttime·directory inode, cgroup의 전체 container ID component |
| 재검사 | 검사자/대상 metadata·PID·top identity·userns mode·프로젝트 container snapshot·daemon·source/env/receipt/key metadata 안정성 |

독립 PID namespace에서 NSpid의 마지막 값1을 요구해 같은 container의 worker를 init으로 채택하지 않는다. host/shared PID mode는 CONTAINER_PID_MODE_UNSUPPORTED, init namespace 증거 부족은 CONTAINER_INIT_PID_NAMESPACE_UNVERIFIED로 blocked 처리한다.

지원 범위는 검사자와 대상 모두 uid_map 및 gid_map이 단일 전체 identity mapping(0 0 4294967295)인 경우다. 일반 rootful Linux 호스트의 현재 숫자 ID를 확인한다. rootless/remapped/부분 mapping의 주소 변환을 추정하지 않는다. Docker cgroup v1의 전체 ID path component와 v2의 docker-<전체ID>.scope를 인식하며 custom cgroup layout/감춰진 host PID view는 검증 불충분으로 남긴다. 프로세스 inode/starttime와 Docker PID·container lifecycle을 두 창에서 비교해 다른 프로세스의 metadata를 채택하지 않는다. transient worker/healthcheck 수 변화 자체는 실패가 아니며 init process만 검증한다. supplementary groups/capabilities·모든 worker·loader origin·향후 key access는 검사 범위에 포함하지 않는다.

procfs root와 numeric PID directory를 descriptor로 열고, 허용한 다섯 metadata file만 크기 제한·NOFOLLOW·O_RDONLY로 읽는다. procfs임을 확인하기 전 self alias를 따르지 않는다. cmdline/environ/mem/root/exe/fd, key/CA/DSN 본문, Docker volume의 선언 host path를 읽지 않는다. PID·comm·starttime·inode·raw map/cgroup path는 보고서에 저장하지 않는다. key source는 기존 metadata 검사만 재사용한다.

정상 검사는 status=inspected/inspection_completed=true와 함께 identity_readiness를 표시한다. 두 대상이 모두 verified이면 verified_process_count=2이며 각 process의 container_uid_mapping_verified/actual_execution_uid_verified가 true다. 이 true는 identity_scope=current-container-init-process에 한정된다. effective_uid/effective_gid와 filesystem_uid/filesystem_gid를 분리해 출력한다. credential_runtime_binding_verified=false·production_supply_ready=false·activation_allowed=false는 유지한다.

권한 부족은 HOST_PROCESS_METADATA_PERMISSION_REQUIRED, 검사자 PID view 차이는 HOST_PROCFS_PID_VIEW_UNSUPPORTED, 부분 mapping은 OBSERVER_IDENTITY_MAP_UNSUPPORTED 또는 CONTAINER_IDENTITY_MAP_UNSUPPORTED, cgroup 소속 증거 부족은 HOST_CONTAINER_CGROUP_CORRELATION_UNAVAILABLE로 blocked 처리한다. 대상 한 개만 확인되면 다른 대상의 성공과 실패를 분리하고 전체 identity_readiness는 blocked로 남긴다. 비지원/권한 부족 조사가 끝나면 종료값0이며 증거가 부족한 UID는 null이다. 권한·mount·capability·UID를 자동 변경하거나 sudo로 재실행하지 않는다. 이미 확인한 metadata를 재검사하지 못하거나 UID/PID/starttime/source가 달라지면 status=failed와 고정 code/stage, 종료값1로 중단한다.

쓰기 범위는 공통 camera coordination lock과 private var/camera/credential-identity-preflight.json(mode0600)뿐이다. 실행 시작/실패 시 이전 성공 보고서를 대체해 stale success를 유지하지 않는다. 기존 preflight/facts/review 파일은 보존한다. 서비스 시작/재시작·Docker exec 추가·SQL/DB schema·역할·HBA/network·비밀·authority·환경 변경은 없다. 공급 위치 승인·PKI/DSN/키 사본·backup topology·schema9 전환·production restore fence·HTTP API는 후속 단위다.

검증은 새32개와 기존 공급90개를 통과했다. 합성 owned container 및 procfs records로 source gate, init/top/cgroup 연계, partial mapping·권한 부족, UID 불일치, PID/inode/starttime·관찰 drift, key 미읽기, report 보호를 확인한다. 실제 로컬 Linux procfs의 fstatfs/metadata IO도 검사했다. 로컬 환경은 제한된 user namespace와 다른 PID view이므로 host identity를 verified로 주장하지 않는다. 이후 simsys4090에서 같은32+90개와 실제 container 두 개 verified를 인수했다. 현재 API65532:65532, DB999:999이며 전체 mapping·cgroup·init PID namespace가 true다. [d4d 인수 기록](../progress/20261007-step11b3c3d4d-process-identity.md)을 따른다.

읽기 형식 근거는 [Linux user namespaces](https://man7.org/linux/man-pages/man7/user_namespaces.7.html), [proc pid status](https://man7.org/linux/man-pages/man5/proc_pid_status.5.html), [proc pid stat](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html), [kernel cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)다. map 숫자 동일성과 미래 보호된 공급 binding은 별도로 검증한다.
