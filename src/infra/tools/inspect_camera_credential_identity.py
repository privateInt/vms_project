#!/usr/bin/env python3
"""Verify current container init identities using bounded, read-only procfs metadata.

Support full identity UID/GID maps only. Missing host visibility/permissions or
unrecognized cgroup layouts stay blocked. This is not a credential binding receipt.
No Docker exec, key material, process arguments or environment reads are added.
"""
import ctypes
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from urllib.error import URLError

import prepare_camera_credential_supply_review as review
from camera_activation import ActivationError, activation_lock, atomic_write, safe, sha

facts = review.facts
inventory = facts.inventory
require = facts.require
SCOPE = 'camera_credential_production_process_identity'
REPORT = 'var/camera/credential-identity-preflight.json'
ACCEPTED_REVIEW = '0670c667d5169780ec50e338f029ce118ef19e7ed79a245ff1eccb5f5d887326'
NO_CHANGES = {**review.NO_CHANGES, 'credential_runtime_binding_verified': False,
    'supply_review_modified': False, 'host_permissions_modified': False}
STAGES = (*facts.STAGES, 'host_procfs_visibility', 'current_init_identity',
    'process_identity_recheck', 'identity_input_recheck')
FULL_MAP = ((0, 0, 4294967295),)
LIMITS = {'stat': 4096, 'status': 65536, 'uid_map': 16384, 'gid_map': 16384, 'cgroup': 65536}


class IdentityBlocked(ActivationError):
    """Inspection completed without enough evidence; never a verified identity."""


def checked_source(root):
    revision = review.checked_source(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    require(manifest.get('credential_production_supply_review_server_verified') is True
        and manifest.get('validated_credential_production_supply_review_project_sha256') == ACCEPTED_REVIEW
        and manifest.get('credential_production_process_identity_implemented') is True,
        'ACCEPTED_SUPPLY_REVIEW_REQUIRED')
    require('src/infra/tools/inspect_camera_credential_identity.py' in manifest['files'],
        'PROCESS_IDENTITY_SOURCE_MANIFEST_INCOMPLETE')
    return revision


def ascii_lines(raw, limit, code):
    require(isinstance(raw, bytes) and 0 < len(raw) <= limit, code)
    try: return raw.decode('ascii').splitlines()
    except UnicodeError: raise ActivationError(code) from None


def numeric(value, maximum=4294967294):
    return bool(re.fullmatch(r'0|[1-9][0-9]{0,9}', value)) and int(value) <= maximum


def id_map(raw):
    lines = ascii_lines(raw, LIMITS['uid_map'], 'PROCESS_ID_MAP_INVALID')
    require(1 <= len(lines) <= 340, 'PROCESS_ID_MAP_INVALID')
    result = []
    for line in lines:
        fields = line.split()
        require(len(fields) == 3 and all(numeric(x, 4294967295) for x in fields), 'PROCESS_ID_MAP_INVALID')
        inside, outside, count = map(int, fields)
        require(count > 0 and inside+count <= 4294967295 and outside+count <= 4294967295,
            'PROCESS_ID_MAP_INVALID')
        result.append((inside, outside, count))
    for column in (0, 1):
        ordered = sorted((row[column], row[column]+row[2]) for row in result)
        require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), 'PROCESS_ID_MAP_INVALID')
    return tuple(result)


def status_ids(raw):
    lines = ascii_lines(raw, LIMITS['status'], 'PROCESS_STATUS_INVALID')
    result = {}
    for name in ('Uid', 'Gid'):
        matches = [line.split()[1:] for line in lines if line.startswith(name+':')]
        require(len(matches) == 1 and len(matches[0]) == 4 and all(numeric(x) for x in matches[0]),
            'PROCESS_STATUS_INVALID')
        result[name] = tuple(map(int, matches[0]))
    return result


def process_status(raw, pid):
    result = status_ids(raw)
    lines = ascii_lines(raw, LIMITS['status'], 'PROCESS_STATUS_INVALID')
    selected = {}
    for name in ('Pid', 'NSpid'):
        matches = [line.split()[1:] for line in lines if line.startswith(name+':')]
        require(len(matches) <= 1, 'PROCESS_STATUS_INVALID')
        selected[name] = matches[0] if matches else None
    require(selected['Pid'] == [str(pid)], 'PROCESS_STATUS_PID_MISMATCH')
    ns = selected['NSpid']
    if ns is not None:
        require(1 <= len(ns) <= 32 and all(numeric(x) and int(x) > 0 for x in ns)
            and int(ns[0]) == pid, 'PROCESS_STATUS_PID_MISMATCH')
    result['NSpid'] = tuple(map(int, ns)) if ns is not None else None
    return result


def start_time(raw, pid):
    require(isinstance(raw, bytes) and 0 < len(raw) <= LIMITS['stat']
        and raw.startswith(str(pid).encode()+b' ('), 'PROCESS_STAT_INVALID')
    # comm may contain spaces and parentheses; discard it, then index field 22.
    end = raw.rfind(b') ')
    require(end > 0, 'PROCESS_STAT_INVALID')
    try: fields = raw[end+2:].decode('ascii').split()
    except UnicodeError: raise ActivationError('PROCESS_STAT_INVALID') from None
    require(len(fields) >= 20 and len(fields[0]) == 1 and fields[0] not in ('Z', 'X', 'x')
        and re.fullmatch('[0-9]{1,20}', fields[19]) and int(fields[19]) > 0, 'PROCESS_STAT_INVALID')
    return int(fields[19])


def container_cgroup(raw, cid):
    require(isinstance(cid, str) and re.fullmatch('[0-9a-f]{64}', cid), 'CONTAINER_IDENTITY_MISMATCH')
    lines = ascii_lines(raw, LIMITS['cgroup'], 'PROCESS_CGROUP_INVALID')
    require(len(lines) <= 1024, 'PROCESS_CGROUP_INVALID')
    matched = False
    for line in lines:
        fields = line.split(':', 2)
        require(len(fields) == 3 and numeric(fields[0])
            and re.fullmatch('[a-zA-Z0-9_=,.-]*', fields[1]), 'PROCESS_CGROUP_INVALID')
        path = fields[2]; parts = PurePosixPath(path).parts
        require(path.startswith('/') and not path.startswith('//') and '..' not in parts
            and PurePosixPath(path).as_posix() == path
            and all(32 <= ord(c) < 127 for c in path), 'PROCESS_CGROUP_INVALID')
        matched |= cid in parts or 'docker-'+cid+'.scope' in parts
    return matched


def top_rows(raw):
    facts.process_identities(raw)  # Accepted bounded numeric format and duplicate checks.
    return {int(p): (int(u), int(g)) for p, u, g in (line.split() for line in raw.decode('ascii').splitlines()[1:])}


def procfs_fd(fd):
    # Linux statfs starts with a native long f_type. An oversized aligned buffer
    # avoids architecture-dependent layouts for the unused fields.
    libc = ctypes.CDLL(None, use_errno=True)
    call = libc.fstatfs; call.argtypes = [ctypes.c_int, ctypes.c_void_p]; call.restype = ctypes.c_int
    buffer = (ctypes.c_long*64)()
    if call(fd, ctypes.byref(buffer)) != 0:
        raise OSError(ctypes.get_errno(), 'procfs metadata unavailable')
    return buffer[0] == 0x9fa0  # PROC_SUPER_MAGIC


class ProcReader:
    """Only /proc plus five exact metadata names; no injectable host root."""
    def __enter__(self):
        if not sys.platform.startswith('linux'): raise IdentityBlocked('HOST_PROCFS_UNAVAILABLE')
        self.fd = os.open('/proc', os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            if not procfs_fd(self.fd): raise IdentityBlocked('HOST_PROCFS_UNAVAILABLE')
        except BaseException:
            os.close(self.fd); raise
        return self

    def __exit__(self, *exc): os.close(self.fd)

    def read(self, directory, name):
        require(name in LIMITS, 'PROCESS_METADATA_READ_REJECTED')
        fd = os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=directory)
        try:
            require(stat.S_ISREG(os.fstat(fd).st_mode) and procfs_fd(fd), 'PROCESS_METADATA_FILE_INVALID')
            limit = LIMITS[name]; chunks = []; length = 0
            while length <= limit:
                block = os.read(fd, min(4096, limit+1-length))
                if not block: break
                chunks.append(block); length += len(block)
            require(0 < length <= limit, 'PROCESS_METADATA_FILE_INVALID')
            return b''.join(chunks)
        finally: os.close(fd)

    def process(self, pid):
        require(type(pid) is int and 0 < pid < 4294967295, 'CONTAINER_PROCESS_PID_INVALID')
        fd = os.open(str(pid), os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=self.fd)
        try:
            meta = os.fstat(fd)
            first = start_time(self.read(fd, 'stat'), pid)
            result = {'ids': process_status(self.read(fd, 'status'), pid),
                'uid_map': id_map(self.read(fd, 'uid_map')), 'gid_map': id_map(self.read(fd, 'gid_map')),
                'cgroup': self.read(fd, 'cgroup'), 'signature': (meta.st_dev, meta.st_ino, first)}
            require(start_time(self.read(fd, 'stat'), pid) == first, 'PROCESS_CHANGED_DURING_INSPECTION')
            return result
        finally: os.close(fd)

    def observer(self):
        # Only this kernel-generated alias is followed, after procfs verification.
        alias = os.readlink('self', dir_fd=self.fd)
        if alias != str(os.getpid()): raise IdentityBlocked('HOST_PROCFS_PID_VIEW_UNSUPPORTED')
        value = self.process(os.getpid())
        require(value['ids']['Uid'][1] == os.geteuid() and value['ids']['Gid'][1] == os.getegid(),
            'OBSERVER_PROCESS_IDENTITY_MISMATCH')
        if value['uid_map'] != FULL_MAP or value['gid_map'] != FULL_MAP:
            raise IdentityBlocked('OBSERVER_IDENTITY_MAP_UNSUPPORTED')
        return value


def blocked_code(exc):
    if isinstance(exc, IdentityBlocked): return inventory.failure_code(exc)
    if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM):
        return 'HOST_PROCESS_METADATA_PERMISSION_REQUIRED'
    if isinstance(exc, OSError) and exc.errno in (errno.ENOENT, errno.ESRCH):
        return 'HOST_PROCESS_METADATA_UNAVAILABLE'
    raise exc


def init_pid(container, baseline):
    state = container.get('State', {})
    require(state.get('Running') is True and state.get('StartedAt') == baseline['started_at'],
        'CONTAINER_PROCESS_STATE_MISMATCH')
    pid = state.get('Pid')
    require(type(pid) is int and 0 < pid < 4294967295, 'CONTAINER_PROCESS_PID_INVALID')
    return pid


def process_result(record, cid, effective):
    if record['uid_map'] != FULL_MAP or record['gid_map'] != FULL_MAP:
        raise IdentityBlocked('CONTAINER_IDENTITY_MAP_UNSUPPORTED')
    if not container_cgroup(record['cgroup'], cid):
        raise IdentityBlocked('HOST_CONTAINER_CGROUP_CORRELATION_UNAVAILABLE')
    ids = record['ids']
    if not ids['NSpid'] or ids['NSpid'][-1] != 1:
        raise IdentityBlocked('CONTAINER_INIT_PID_NAMESPACE_UNVERIFIED')
    require((ids['Uid'][1], ids['Gid'][1]) == effective, 'PROCESS_EFFECTIVE_IDENTITY_MISMATCH')
    return {'status': 'verified', 'container_uid_mapping_verified': True,
        'actual_execution_uid_verified': True, 'container_cgroup_match_verified': True,
        'container_init_pid_namespace_verified': True,
        'effective_uid': effective[0], 'effective_gid': effective[1],
        'filesystem_uid': ids['Uid'][3], 'filesystem_gid': ids['Gid'][3]}


def inspect_identity(root, docker, reader_factory=ProcReader):
    docker.inspection_stage = 'accepted_source'
    revision = checked_source(root)
    paths = [root/'.env', root/inventory.RECEIPT]
    for path in paths: safe(path)
    inputs = [sha(path) for path in paths]
    key_before = inventory.key_metadata(root)[1]
    daemon, before = docker.preflight(), docker.snapshot()
    observation = facts.inspect_facts(root, docker)
    require(observation['checked_revision'] == revision, 'INSPECTION_INPUT_CHANGED')
    docker.inspection_stage = 'current_init_identity'
    containers = facts.inspected_containers(docker, before)
    pids = {s: init_pid(v, before[s]) for s, v in containers.items()}
    effective = {}
    for service in containers:
        rows = top_rows(docker.run(['top', before[service]['id'], '-eo', 'pid,euid,egid']))
        require(pids[service] in rows, 'CONTAINER_INIT_PROCESS_NOT_IN_TOP')
        effective[service] = rows[pids[service]]
    processes, records, observer, observer_block = {}, {}, None, None
    docker.inspection_stage = 'host_procfs_visibility'
    try:
        with reader_factory() as reader:
            try: observer = reader.observer()
            except (IdentityBlocked, OSError) as exc: observer_block = blocked_code(exc)
            docker.inspection_stage = 'current_init_identity'
            for service in containers:
                try:
                    if observer_block: raise IdentityBlocked(observer_block)
                    if containers[service].get('HostConfig', {}).get('PidMode') != '':
                        raise IdentityBlocked('CONTAINER_PID_MODE_UNSUPPORTED')
                    record = reader.process(pids[service])
                    processes[service] = process_result(record, before[service]['id'], effective[service])
                    records[service] = record
                except (IdentityBlocked, OSError) as exc:
                    processes[service] = {'status': 'blocked', 'code': blocked_code(exc),
                        'container_uid_mapping_verified': False, 'actual_execution_uid_verified': False,
                        'container_cgroup_match_verified': False, 'container_init_pid_namespace_verified': False,
                        'effective_uid': None, 'effective_gid': None}
            docker.inspection_stage = 'process_identity_recheck'
            try:
                if observer is not None:
                    require(reader.observer() == observer, 'OBSERVER_PROCESS_CHANGED_DURING_INSPECTION')
                for service, record in records.items():
                    require(reader.process(pids[service]) == record, 'PROCESS_CHANGED_DURING_INSPECTION')
            except (IdentityBlocked, OSError):
                raise ActivationError('PROCESS_METADATA_UNAVAILABLE_DURING_RECHECK') from None
    except (IdentityBlocked, OSError) as exc:
        code = blocked_code(exc)
        observer_block = code
        processes = {s: {'status': 'blocked', 'code': code,
            'container_uid_mapping_verified': False, 'actual_execution_uid_verified': False,
            'container_cgroup_match_verified': False, 'container_init_pid_namespace_verified': False,
            'effective_uid': None, 'effective_gid': None} for s in containers}
    for service, value in processes.items():
        value.update(identity_scope='current-container-init-process', pids_retained=False,
            credential_runtime_binding_verified=False)
    docker.inspection_stage = 'process_identity_recheck'
    last = facts.inspected_containers(docker, before)
    require({s: init_pid(v, before[s]) for s, v in last.items()} == pids,
        'PROCESS_CHANGED_DURING_INSPECTION')
    require({s: v['HostConfig']['UsernsMode'] for s, v in last.items()} ==
        {s: v['HostConfig']['UsernsMode'] for s, v in containers.items()}
        and {s: v['HostConfig'].get('PidMode') for s, v in last.items()} ==
        {s: v['HostConfig'].get('PidMode') for s, v in containers.items()}, 'PROCESS_NAMESPACE_MODE_CHANGED')
    for service in containers:
        rows = top_rows(docker.run(['top', before[service]['id'], '-eo', 'pid,euid,egid']))
        require(rows.get(pids[service]) == effective[service], 'PROCESS_CHANGED_DURING_INSPECTION')
    docker.inspection_stage = 'identity_input_recheck'
    for path in paths: safe(path)
    require(checked_source(root) == revision and [sha(path) for path in paths] == inputs, 'INSPECTION_INPUT_CHANGED')
    require(inventory.key_metadata(root)[1] == key_before, 'KEY_METADATA_CHANGED_DURING_INSPECTION')
    require(docker.preflight() == daemon and docker.snapshot() == before,
        'PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')
    verified = sum(v['status'] == 'verified' for v in processes.values())
    return {'status': 'inspected', 'scope': SCOPE, 'inspection_completed': True,
        'project': docker.project, 'checked_revision': revision,
        'identity_readiness': 'verified' if verified == 2 else 'blocked', 'verified_process_count': verified,
        'observer_identity_mapping_verified': observer is not None and observer_block is None,
        'supported_mapping': 'full-identity-uid-and-gid-maps-only', 'processes': processes,
        'blockers': sorted({v['code'] for v in processes.values() if v['status'] == 'blocked'}),
        'running_api_version': observation['inventory']['running_api_version'],
        'schema_version': observation['inventory']['database']['schema_version'],
        'readiness': 'blocked', 'production_supply_ready': False, 'activation_allowed': False,
        'next_step': 'review_supply_locations_and_backup_topology' if verified == 2 else 'review_host_process_visibility',
        **NO_CHANGES}


def failure_code(exc):
    return inventory.failure_code(exc) if isinstance(exc, ActivationError) else 'PROCESS_IDENTITY_INSPECTION_UNAVAILABLE'


def run_inspection(root):
    with activation_lock(root):
        atomic_write(root/REPORT, json.dumps({'status': 'running', 'scope': SCOPE,
            'activation_allowed': False, **NO_CHANGES}).encode()+b'\n')
        docker = facts.FactsDocker(root)
        try: value = inspect_identity(root, docker)
        except BaseException as exc:
            stage = getattr(docker, 'inspection_stage', 'accepted_source')
            if stage not in STAGES: stage = 'accepted_source'
            exc.inspection_stage = stage
            atomic_write(root/REPORT, json.dumps({'status': 'failed', 'scope': SCOPE,
                'inspection_completed': False, 'identity_readiness': 'blocked', 'activation_allowed': False,
                'production_supply_ready': False,
                'code': failure_code(exc), 'failed_stage': stage, **NO_CHANGES}).encode()+b'\n')
            raise
        atomic_write(root/REPORT, (json.dumps(value, indent=2)+'\n').encode())
    return value


def main():
    root = Path(__file__).resolve().parents[3]
    try:
        require(len(sys.argv) == 1, 'NO_ARGUMENTS_EXPECTED')
        value = run_inspection(root)
        print(json.dumps({**value, 'report': str(root/REPORT)}, ensure_ascii=False)); return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError,
            AttributeError, URLError, UnicodeError, KeyboardInterrupt) as exc:
        stage = getattr(exc, 'inspection_stage', 'accepted_source')
        if stage not in STAGES: stage = 'accepted_source'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': failure_code(exc),
            'failed_stage': stage, 'inspection_completed': False, 'activation_allowed': False,
            'production_supply_ready': False,
            **NO_CHANGES}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
