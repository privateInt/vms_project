#!/usr/bin/env python3
"""Compare the current database volume with actual Linux mount metadata.

Only directory O_PATH descriptors and procfs mountinfo/own fdinfo are added.
No database contents, extra Docker exec, archive, key, or supply files are read.
This establishes one volume mount, never a complete backup/restore topology.
"""
import errno
import array
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import socket
import struct
import subprocess
import sys
from urllib.error import URLError

import inspect_camera_credential_identity as identity
from camera_activation import ActivationError, activation_lock, atomic_write, safe, sha
import camera_storage_directory_observer as directory_observer

facts, inventory = identity.facts, identity.inventory
require = identity.require
SCOPE = 'camera_credential_production_database_volume_mount'
DIAGNOSTIC_SCOPE = 'camera_credential_mountinfo_root_shapes'
REPORT = 'var/camera/credential-storage-topology.json'
ACCEPTED_IDENTITY = '8048bc6efcbfc0a227c2f10af225056fda294cf7b5b9ddc2dc9bd1c4786dcec3'
ACCEPTED_ACCESS_DIAGNOSTICS = 'c5c907d2ca09660e684d6e35b47a7854ce50272e65da11bfe01a186800e2e74c'
ACCEPTED_STORAGE_LAYOUT = '4151d24309168d3f0a31da870aed511f2d44cdf96f836431339187e4352c9062'
OBSERVER_SOURCE = 'src/infra/tools/camera_storage_directory_observer.py'
NO_CHANGES = {**identity.NO_CHANGES, 'database_file_contents_read': False,
    'database_directory_contents_listed': False, 'backup_created': False,
    'declared_snapshot_roots_created': False, 'backup_topology_verified': False}
STAGES = (*identity.STAGES, 'database_mount_metadata', 'host_database_directory',
    'volume_mount_comparison', 'volume_mount_recheck', 'topology_input_recheck')
MAX_MOUNTINFO = 1048576
SUPPORTED_FILESYSTEMS = {'ext4', 'xfs', 'btrfs'}
ROOT_SHAPES = ('canonical_absolute', 'deleted_suffix', 'relative_or_synthetic',
    'double_leading_slash', 'parent_component', 'dot_component', 'repeated_slash',
    'trailing_slash', 'other_noncanonical')
UNRESOLVED = ['ACTIVE_PGDATA_AND_EXTERNAL_WAL_TABLESPACE_LOCATIONS',
    'ALL_BACKUP_AND_RESTORE_SNAPSHOT_ROOTS_AND_DESTINATIONS',
    'EXTERNAL_AUTHORITY_LOCK_HBA_AND_PKI_PHYSICAL_EXCLUSION',
    'COORDINATED_DATABASE_AND_KEY_BACKUP_RESTORE_PROCEDURE']


def checked_source(root):
    revision = identity.checked_source(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    require(manifest.get('credential_production_process_identity_server_verified') is True
        and manifest.get('validated_credential_production_process_identity_project_sha256') == ACCEPTED_IDENTITY
        and manifest.get('credential_production_database_mount_topology_implemented') is True,
        'ACCEPTED_PROCESS_IDENTITY_REQUIRED')
    require('src/infra/tools/inspect_camera_credential_storage_topology.py' in manifest['files'],
        'STORAGE_TOPOLOGY_SOURCE_MANIFEST_INCOMPLETE')
    return revision


def canonical_mount_path(value):
    path = PurePosixPath(value)
    return '\x00' not in value and path.is_absolute() and not value.startswith('//') \
        and '..' not in path.parts and path.as_posix() == value


def mount_path(value, *, root=False):
    # Root is kernel-rendered metadata, not a lookup path. Preserve it exactly;
    # compare_volume validates the two selected roots before any path arithmetic.
    require(not any(c in value for c in ('\x00', '\t', '\n'))
        and not re.search(r'\\(?!040|011|012|134)', value), 'MOUNTINFO_PATH_ESCAPE_INVALID')
    value = re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), value)
    if root: require(bool(value), 'MOUNTINFO_ROOT_PATH_INVALID')
    else: require(canonical_mount_path(value), 'MOUNTINFO_MOUNTPOINT_PATH_INVALID')
    return value


def root_shape(value):
    """Classify rendering only; the result never authorizes a lookup path."""
    if canonical_mount_path(value): return 'canonical_absolute'
    if value.endswith('//deleted') and canonical_mount_path(value[:-9]): return 'deleted_suffix'
    if not value.startswith('/'): return 'relative_or_synthetic'
    if value.startswith('//'): return 'double_leading_slash'
    parts = value.split('/')
    if '..' in parts: return 'parent_component'
    if '.' in parts: return 'dot_component'
    if '//' in value: return 'repeated_slash'
    if value.endswith('/'): return 'trailing_slash'
    return 'other_noncanonical'


def root_shape_counts(records):
    counts = dict.fromkeys(ROOT_SHAPES, 0)
    for record in records.values(): counts[root_shape(record['root'])] += 1
    return counts


def mountinfo(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_MOUNTINFO, 'MOUNTINFO_INVALID')
    # Only LF and ASCII space delimit kernel records/fields. Other whitespace
    # (including Unicode whitespace and CR) may be literal filename bytes.
    rows = raw.decode('utf-8', 'surrogateescape').split('\n')
    if rows[-1] == '': rows.pop()
    require(0 < len(rows) <= 16384, 'MOUNTINFO_INVALID')
    result = {}
    for row in rows:
        fields = row.split(' '); separator = fields.index('-') if '-' in fields else -1
        require(separator >= 6 and len(fields) == separator+4
            and identity.numeric(fields[0]) and int(fields[0]) > 0
            and identity.numeric(fields[1]), 'MOUNTINFO_INVALID')
        device = fields[2].split(':')
        require(len(device) == 2 and all(identity.numeric(v) for v in device)
            and re.fullmatch('[A-Za-z0-9_.-]{1,64}', fields[separator+1]), 'MOUNTINFO_INVALID')
        mid = int(fields[0]); require(mid not in result, 'MOUNTINFO_INVALID')
        options = fields[5].split(',')
        require(('rw' in options) != ('ro' in options), 'MOUNTINFO_INVALID')
        result[mid] = {'id': mid, 'parent': int(fields[1]), 'device': tuple(map(int, device)),
            'root': mount_path(fields[3], root=True), 'point': mount_path(fields[4]),
            'filesystem': fields[separator+1], 'read_only': 'ro' in options}
    return result


def below(path, parent):
    p, base = PurePosixPath(path), PurePosixPath(parent)
    return p == base or base in p.parents


def visible_mount(path, records):
    """Walk visible mount parents; a nearer overmount hides old descendants."""
    roots = [v for v in records.values() if v['point'] == '/']
    bases = [v for v in roots if v['parent'] == v['id'] or v['parent'] not in records]
    require(len(bases) == 1, 'MOUNT_NAMESPACE_ROOT_AMBIGUOUS')
    current = bases[0]; seen = set()
    while True:
        require(current['id'] not in seen, 'MOUNT_NAMESPACE_TREE_INVALID'); seen.add(current['id'])
        children = [v for v in records.values() if v['parent'] == current['id']
            and v['id'] != current['id'] and below(path, v['point'])]
        if not children: return current
        depth = min(len(PurePosixPath(v['point']).parts) for v in children)
        nearest = [v for v in children if len(PurePosixPath(v['point']).parts) == depth]
        require(len(nearest) == 1 and below(nearest[0]['point'], current['point']),
            'MOUNT_NAMESPACE_TREE_INVALID')
        current = nearest[0]


def fd_mount(raw, inode):
    rows = identity.ascii_lines(raw, 4096, 'DIRECTORY_FDINFO_INVALID')
    values = {}
    for name in ('mnt_id', 'ino'):
        matches = [r.split()[1:] for r in rows if r.startswith(name+':')]
        require(len(matches) == 1 and len(matches[0]) == 1
            and re.fullmatch('[0-9]{1,20}', matches[0][0]), 'DIRECTORY_FDINFO_INVALID')
        values[name] = int(matches[0][0])
    require(0 < values['mnt_id'] < 4294967295 and values['ino'] == inode, 'DIRECTORY_FDINFO_INVALID')
    return values['mnt_id']


class StorageAccessDenied(OSError):
    """Fixed operation and descriptor metadata; never retain OS error text."""
    def __init__(self, error, operation, attempted_path, observed=None):
        super().__init__(error, 'HOST_STORAGE_METADATA_PERMISSION_REQUIRED')
        self.operation, self.attempted_path = operation, attempted_path
        self.observed = observed


def observed_directory(path, value):
    return {'path': path, 'owner_uid': value.st_uid, 'owner_gid': value.st_gid,
        'permissions': format(stat.S_IMODE(value.st_mode), '04o')}


def access_diagnostics(exc, host_path):
    """Bind an allowlisted denial to this declared path, not arbitrary exceptions."""
    if type(exc) is not StorageAccessDenied: return None
    code = 'STORAGE_ACCESS_DIAGNOSTICS_INVALID'
    require(exc.errno in (errno.EACCES, errno.EPERM), code)
    attempted, operation, observed = exc.attempted_path, exc.operation, exc.observed
    require(type(operation) is str and type(attempted) is str and canonical_mount_path(attempted)
        and below(host_path, attempted), code)
    if operation == 'open_filesystem_root':
        require(attempted == '/' and observed is None, code)
    else:
        require(operation in ('open_directory_component', 'read_own_directory_fdinfo')
            and type(observed) is dict
            and set(observed) == {'path', 'owner_uid', 'owner_gid', 'permissions'}, code)
        expected = str(PurePosixPath(attempted).parent) if operation == 'open_directory_component' else host_path
        require((operation != 'open_directory_component' or attempted != '/')
            and (operation != 'read_own_directory_fdinfo' or attempted == host_path)
            and type(observed['path']) is str and observed['path'] == expected, code)
        require(all(type(observed[k]) is int and 0 <= observed[k] < 4294967295
            for k in ('owner_uid', 'owner_gid'))
            and type(observed['permissions']) is str
            and re.fullmatch('[0-7]{4}', observed['permissions']), code)
    return {'operation': operation, 'attempted_path': attempted,
        'error': 'EACCES' if exc.errno == errno.EACCES else 'EPERM',
        'observed_directory': dict(observed) if observed is not None else None,
        'metadata_basis': 'already-open-directory-descriptor' if observed is not None else 'none',
        'path_binding_rechecked': False, 'permission_policy_cause_proven': False}


class MountReader(identity.ProcReader):
    def proc_metadata(self, directory, name, limit):
        require((name == 'mountinfo' and limit == MAX_MOUNTINFO)
            or (isinstance(name, str) and name.isdecimal() and limit == 4096), 'MOUNT_METADATA_READ_REJECTED')
        fd = os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=directory)
        try:
            require(stat.S_ISREG(os.fstat(fd).st_mode) and identity.procfs_fd(fd), 'MOUNT_METADATA_FILE_INVALID')
            chunks, size = [], 0
            while size <= limit:
                chunk = os.read(fd, min(4096, limit+1-size))
                if not chunk: break
                chunks.append(chunk); size += len(chunk)
            require(0 < size <= limit, 'MOUNT_METADATA_FILE_INVALID')
            return b''.join(chunks)
        finally: os.close(fd)

    def pid_directory(self, pid):
        require(type(pid) is int and 0 < pid < 4294967295, 'CONTAINER_PROCESS_PID_INVALID')
        return os.open(str(pid), os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=self.fd)

    def mounts(self, pid):
        fd = self.pid_directory(pid)
        try: return mountinfo(self.proc_metadata(fd, 'mountinfo', MAX_MOUNTINFO))
        finally: os.close(fd)

    def descriptor_mount(self, descriptor, inode):
        pid = int(os.readlink('self', dir_fd=self.fd))
        process = self.pid_directory(pid)
        directory = None
        try:
            directory = os.open('fdinfo', os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC, dir_fd=process)
            return fd_mount(self.proc_metadata(directory, str(descriptor), 4096), inode)
        finally:
            if directory is not None: os.close(directory)
            os.close(process)

    def directory(self, path):
        facts.canonical_host_path(path)
        flags = os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        try: initial = os.open('/', flags)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise StorageAccessDenied(exc.errno, 'open_filesystem_root', '/') from None
            raise
        fds, chain, current = [initial], [], PurePosixPath('/')
        try:
            for name in PurePosixPath(path).parts[1:]:
                try: fd = os.open(name, flags, dir_fd=fds[-1])
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        raise ActivationError('DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED') from None
                    if exc.errno in (errno.EACCES, errno.EPERM):
                        raise StorageAccessDenied(exc.errno, 'open_directory_component', str(current/name),
                            observed_directory(str(current), os.fstat(fds[-1]))) from None
                    raise
                fds.append(fd); value = os.fstat(fd)
                require(stat.S_ISDIR(value.st_mode), 'DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED')
                chain.append((value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode))
                current /= name
            final = os.fstat(fds[-1])
            try: mount_id = self.descriptor_mount(fds[-1], final.st_ino)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EPERM):
                    raise StorageAccessDenied(exc.errno, 'read_own_directory_fdinfo', path,
                        observed_directory(path, final)) from None
                raise
            return {'signature': tuple(chain), 'device': (os.major(final.st_dev), os.minor(final.st_dev)),
                'mount_id': mount_id,
                'owner_uid': final.st_uid, 'owner_gid': final.st_gid,
                'mode': format(stat.S_IMODE(final.st_mode), '04o')}
        finally:
            for fd in reversed(fds): os.close(fd)


def receive_directory(channel, path, reader):
    """Authenticate the actual sender, validate and close every received fd."""
    descriptors = []
    try:
        itemsize = array.array('i').itemsize
        raw, ancillary, flags, _ = channel.recvmsg(directory_observer.MAX_PACKET,
            socket.CMSG_SPACE(16*itemsize)+socket.CMSG_SPACE(struct.calcsize('3i')),
            socket.MSG_CMSG_CLOEXEC)
        credentials, unknown = [], False
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array('i'); values.frombytes(data[:len(data)-len(data)%itemsize])
                descriptors.extend(values); unknown |= len(data)%itemsize != 0
            elif level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS:
                if len(data) == struct.calcsize('3i'): credentials.append(struct.unpack('3i', data))
                else: unknown = True
            else: unknown = True
        if not raw: raise identity.IdentityBlocked('PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE')
        allowed_flags = socket.MSG_CMSG_CLOEXEC|socket.MSG_EOR
        require(not flags & ~allowed_flags and not unknown and len(credentials) == 1 and credentials[0][0] > 0
            and credentials[0][1:] == (0, 0), 'PRIVILEGED_DIRECTORY_SENDER_NOT_ROOT')
        try: value = json.loads(raw)
        except (ValueError, UnicodeError): raise ActivationError('PRIVILEGED_DIRECTORY_RESPONSE_INVALID') from None
        require(type(value) is dict and value.get('scope') == directory_observer.SCOPE,
            'PRIVILEGED_DIRECTORY_RESPONSE_INVALID')
        if value.get('status') == 'failed':
            require(not descriptors and set(value) == {'scope', 'status', 'code'},
                'PRIVILEGED_DIRECTORY_RESPONSE_INVALID')
            if value['code'] == 'PRIVILEGED_DIRECTORY_PERMISSION_DENIED':
                raise identity.IdentityBlocked('PRIVILEGED_DIRECTORY_PERMISSION_DENIED')
            raise ActivationError('PRIVILEGED_DIRECTORY_OBSERVER_FAILED')
        require(set(value) == {'scope', 'path', 'status', 'chain'} and value['status'] == 'observed'
            and value['path'] == path and directory_observer.allowed_path(path) and len(descriptors) == 1,
            'PRIVILEGED_DIRECTORY_RESPONSE_INVALID')
        chain = value['chain']
        require(type(chain) is list and len(chain) == len(PurePosixPath(path).parts)-1
            and all(type(row) is list and len(row) == 5
                and all(type(n) is int and 0 <= n < 2**64 for n in row)
                and row[1] > 0 and row[2] < 4294967295 and row[3] < 4294967295
                and stat.S_ISDIR(row[4]) and row[4] < 65536 for row in chain),
            'PRIVILEGED_DIRECTORY_RESPONSE_INVALID')
        descriptor = descriptors[0]; os.set_inheritable(descriptor, False)
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        required = os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW
        meta = os.fstat(descriptor)
        require(flags & required == required
            and tuple(chain[-1]) == (meta.st_dev, meta.st_ino, meta.st_uid, meta.st_gid, meta.st_mode),
            'PRIVILEGED_DIRECTORY_DESCRIPTOR_MISMATCH')
        return {'signature': tuple(tuple(row) for row in chain),
            'device': (os.major(meta.st_dev), os.minor(meta.st_dev)),
            'mount_id': reader.descriptor_mount(descriptor, meta.st_ino),
            'owner_uid': meta.st_uid, 'owner_gid': meta.st_gid,
            'mode': format(stat.S_IMODE(meta.st_mode), '04o'),
            'privileged_directory_observer_used': True, 'privileged_sender_uid_verified': True}
    finally:
        for fd in descriptors: os.close(fd)


def privileged_directory(root, path, reader):
    require(directory_observer.allowed_path(path), 'PRIVILEGED_DIRECTORY_PATH_NOT_ALLOWED')
    checked_source(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    if path != directory_observer.HOST_PATH:
        require(manifest.get('camera_database_storage_layout_server_verified') is True
            and manifest.get('validated_camera_database_storage_layout_project_sha256') == ACCEPTED_STORAGE_LAYOUT
            and manifest.get('camera_database_storage_mapping_implemented') is True
            and 'src/infra/tools/inspect_camera_database_storage_mapping.py' in manifest['files'],
            'ACCEPTED_STORAGE_LAYOUT_REQUIRED')
    require(manifest.get('credential_production_storage_access_diagnostics_server_verified') is True
        and manifest.get('validated_credential_production_storage_access_diagnostics_project_sha256') == ACCEPTED_ACCESS_DIAGNOSTICS,
        'ACCEPTED_STORAGE_ACCESS_DIAGNOSTICS_REQUIRED')
    require(OBSERVER_SOURCE in manifest['files'], 'DIRECTORY_OBSERVER_SOURCE_REQUIRED')
    source = (root/OBSERVER_SOURCE).read_bytes()
    require(hashlib.sha256(source).hexdigest() == manifest['files'][OBSERVER_SOURCE], 'SOURCE_FILE_CHANGED')
    # Copy the verified bytes into -c. sudo never imports/opens user project
    # files, and fd 0 is a private socket rather than a filesystem endpoint.
    process = None
    client, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    with client, child:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1); client.settimeout(10)
        try:
            process = subprocess.Popen(['/usr/bin/sudo', '-n', '--', '/usr/bin/python3', '-I', '-B',
                '-c', source.decode('utf-8')], stdin=child, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, cwd='/', env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, close_fds=True)
            child.close()
            client.send(json.dumps({'scope': directory_observer.SCOPE, 'path': path}).encode())
            value = receive_directory(client, path, reader)
            require(process.wait(timeout=2) == 0, 'PRIVILEGED_DIRECTORY_OBSERVER_FAILED')
            return value
        except (OSError, subprocess.TimeoutExpired):
            raise identity.IdentityBlocked('PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE') from None
        finally:
            client.close()
            if process is not None and process.poll() is None:
                try:
                    process.kill(); process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired): pass


class AssistedMountReader(MountReader):
    def __init__(self, root): self.root = root
    def directory(self, path):
        try: return super().directory(path)
        except StorageAccessDenied as exc:
            if exc.operation not in ('open_filesystem_root', 'open_directory_component'): raise
            return privileged_directory(self.root, path, self)


def compare_volume(host_path, container_path, host, runtime, directory):
    require(directory['mount_id'] in host, 'HOST_DIRECTORY_MOUNT_NOT_FOUND')
    selected_host = host[directory['mount_id']]
    require(below(host_path, selected_host['point']) and directory['device'] == selected_host['device'],
        'HOST_DIRECTORY_MOUNT_MISMATCH')
    # The fd selects the live host mount even with stacked or bind mounts.
    require(visible_mount(host_path, host)['id'] == selected_host['id'], 'HOST_DIRECTORY_MOUNT_MISMATCH')
    selected_db = visible_mount(container_path, runtime)
    require(selected_db['point'] == container_path, 'DATABASE_VOLUME_MOUNT_NOT_VISIBLE')
    require(canonical_mount_path(selected_host['root']) and canonical_mount_path(selected_db['root']),
        'DATABASE_MOUNT_ROOT_NOT_CANONICAL')
    relative = PurePosixPath(host_path).relative_to(selected_host['point'])
    expected_root = (PurePosixPath(selected_host['root'])/relative).as_posix()
    require(selected_db['device'] == selected_host['device'] and selected_db['root'] == expected_root
        and selected_db['filesystem'] == selected_host['filesystem'], 'DATABASE_MOUNT_SOURCE_MISMATCH')
    require(selected_db['read_only'] is False, 'DATABASE_VOLUME_UNEXPECTED_READ_ONLY')
    if selected_db['filesystem'] not in SUPPORTED_FILESYSTEMS:
        raise identity.IdentityBlocked('DATABASE_FILESYSTEM_REVIEW_REQUIRED')
    nested = sum(v['point'] != container_path and below(v['point'], container_path) for v in runtime.values())
    if nested: raise identity.IdentityBlocked('DATABASE_NESTED_MOUNTS_REQUIRE_REVIEW')
    result = {'status': 'verified', 'database_volume_mount_verified': True,
        'host_path_without_symlinks_verified': True, 'local_host_path_verified': True,
        'host_filesystem_mountpoint': selected_host['point'],
        'filesystem_type': selected_db['filesystem'], 'directory_owner_uid': directory['owner_uid'],
        'directory_owner_gid': directory['owner_gid'], 'directory_permissions': directory['mode'],
        'nested_database_mount_count': 0, 'backup_topology_verified': False,
        'privileged_directory_observer_used': directory.get('privileged_directory_observer_used', False),
        'privileged_sender_uid_verified': directory.get('privileged_sender_uid_verified', False)}
    return result, (selected_host, selected_db)


def unavailable(exc):
    if isinstance(exc, identity.IdentityBlocked): return inventory.failure_code(exc)
    if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM):
        return 'HOST_STORAGE_METADATA_PERMISSION_REQUIRED'
    if isinstance(exc, OSError) and exc.errno in (errno.ENOENT, errno.ESRCH):
        return 'HOST_STORAGE_METADATA_UNAVAILABLE'
    raise exc


def inspect_topology(root, docker, reader_factory=MountReader):
    docker.inspection_stage = 'accepted_source'; revision = checked_source(root)
    paths = [root/'.env', root/inventory.RECEIPT]
    for path in paths: safe(path)
    inputs = [sha(path) for path in paths]; key_before = inventory.key_metadata(root)[1]
    daemon, before = docker.preflight(), docker.snapshot()
    proof = identity.inspect_identity(root, docker, reader_factory)
    require(proof['checked_revision'] == revision, 'INSPECTION_INPUT_CHANGED')
    docker.inspection_stage = 'database_mount_metadata'
    containers = facts.inspected_containers(docker, before)
    db = containers['camera-db']; pid = identity.init_pid(db, before['camera-db'])
    volume = facts.database_volume(db, docker.project)
    host_path, target = volume['daemon_declared_host_data_directory'], volume['container_data_directory']
    try:
        if proof['identity_readiness'] != 'verified':
            raise identity.IdentityBlocked('CURRENT_PROCESS_IDENTITY_NOT_VERIFIED')
        with reader_factory() as reader:
            observer, process = reader.observer(), reader.process(pid)
            identity.process_result(process, before['camera-db']['id'],
                (proof['processes']['camera-db']['effective_uid'], proof['processes']['camera-db']['effective_gid']))
            host_mounts, db_mounts = reader.mounts(os.getpid()), reader.mounts(pid)
            docker.inspection_stage = 'host_database_directory'
            directory = reader.directory(host_path)
            docker.inspection_stage = 'volume_mount_comparison'
            result, selected = compare_volume(host_path, target, host_mounts, db_mounts, directory)
            docker.inspection_stage = 'volume_mount_recheck'
            try:
                require(reader.directory(host_path) == directory, 'DATABASE_DIRECTORY_CHANGED_DURING_INSPECTION')
                final, selected_after = compare_volume(host_path, target,
                    reader.mounts(os.getpid()), reader.mounts(pid), directory)
                require(final == result and selected_after == selected, 'DATABASE_MOUNT_CHANGED_DURING_INSPECTION')
                require(reader.observer() == observer and reader.process(pid) == process,
                    'PROCESS_CHANGED_DURING_INSPECTION')
            except (identity.IdentityBlocked, OSError):
                raise ActivationError('STORAGE_METADATA_UNAVAILABLE_DURING_RECHECK') from None
    except (identity.IdentityBlocked, OSError) as exc:
        result = {'status': 'blocked', 'code': unavailable(exc), 'database_volume_mount_verified': False,
            'blocked_stage': docker.inspection_stage, 'host_path_without_symlinks_verified': False,
            'backup_topology_verified': False}
        if docker.inspection_stage == 'host_database_directory':
            diagnostic = access_diagnostics(exc, host_path)
            if diagnostic is not None: result['access_diagnostics'] = diagnostic
    docker.inspection_stage = 'topology_input_recheck'
    last = facts.inspected_containers(docker, before)
    require(identity.init_pid(last['camera-db'], before['camera-db']) == pid
        and facts.database_volume(last['camera-db'], docker.project) == volume
        and last['camera-db']['HostConfig'] == db['HostConfig'], 'DATABASE_CONTAINER_CHANGED_DURING_INSPECTION')
    for path in paths: safe(path)
    require(checked_source(root) == revision and [sha(path) for path in paths] == inputs, 'INSPECTION_INPUT_CHANGED')
    require(inventory.key_metadata(root)[1] == key_before, 'KEY_METADATA_CHANGED_DURING_INSPECTION')
    require(docker.preflight() == daemon and docker.snapshot() == before, 'PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')
    return {'status': 'inspected', 'scope': SCOPE, 'inspection_completed': True,
        'project': docker.project, 'checked_revision': revision, 'topology_readiness': result['status'],
        'current_process_identity_verified': proof['identity_readiness'] == 'verified',
        'volume': {**volume, **result}, 'blockers': [result['code']] if result['status'] == 'blocked' else [],
        'unresolved_backup_topology': UNRESOLVED, 'readiness': 'blocked', 'production_supply_ready': False,
        'activation_allowed': False, 'next_step': 'review_supply_locations_and_complete_backup_roots', **NO_CHANGES}


def failure_code(exc):
    return inventory.failure_code(exc) if isinstance(exc, ActivationError) else 'STORAGE_TOPOLOGY_INSPECTION_UNAVAILABLE'


def run_mountinfo_diagnostics(root):
    """Read own procfs metadata only; emit aggregate shapes, never raw paths."""
    revision = checked_source(root)
    try:
        with MountReader() as reader:
            pid = int(os.readlink('self', dir_fd=reader.fd))
            records = reader.mounts(pid)
    except BaseException as exc:
        exc.inspection_stage = 'database_mount_metadata'
        raise
    return {'status': 'inspected', 'scope': DIAGNOSTIC_SCOPE, 'inspection_completed': True,
        'checked_revision': revision, 'diagnostic_only': True, 'mount_count': len(records),
        'root_shapes': root_shape_counts(records), 'raw_paths_emitted': False,
        'database_volume_mount_verified': False, 'activation_allowed': False,
        'production_supply_ready': False, 'report_modified': False, **NO_CHANGES}


def run_inspection(root, *, privileged=False):
    if privileged: require(os.geteuid() != 0, 'RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER')
    with activation_lock(root):
        atomic_write(root/REPORT, json.dumps({'status': 'running', 'scope': SCOPE, 'activation_allowed': False,
            **NO_CHANGES}).encode()+b'\n')
        docker = facts.FactsDocker(root)
        try:
            result = inspect_topology(root, docker, lambda: AssistedMountReader(root)) if privileged else inspect_topology(root, docker)
            result['privileged_directory_observer_requested'] = privileged
        except BaseException as exc:
            stage = getattr(docker, 'inspection_stage', 'accepted_source')
            if stage not in STAGES: stage = 'accepted_source'
            exc.inspection_stage = stage
            atomic_write(root/REPORT, json.dumps({'status': 'failed', 'scope': SCOPE,
                'inspection_completed': False, 'activation_allowed': False, 'production_supply_ready': False,
                'code': failure_code(exc), 'failed_stage': stage, **NO_CHANGES}).encode()+b'\n')
            raise
        atomic_write(root/REPORT, (json.dumps(result, indent=2)+'\n').encode())
    return result


def main():
    root = Path(__file__).resolve().parents[3]
    diagnostic = sys.argv[1:] == ['--mountinfo-diagnostics']
    privileged = sys.argv[1:] == ['--privileged-directory-metadata']
    scope = DIAGNOSTIC_SCOPE if diagnostic else SCOPE
    try:
        require(len(sys.argv) == 1 or diagnostic or privileged, 'NO_ARGUMENTS_EXPECTED')
        result = run_mountinfo_diagnostics(root) if diagnostic else (
            run_inspection(root, privileged=True) if privileged else run_inspection(root))
        output = result if diagnostic else {**result, 'report': str(root/REPORT)}
        print(json.dumps(output, ensure_ascii=False)); return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, URLError,
        KeyboardInterrupt) as exc:
        stage = getattr(exc, 'inspection_stage', 'accepted_source')
        if stage not in STAGES: stage = 'accepted_source'
        print(json.dumps({'status': 'failed', 'scope': scope, 'code': failure_code(exc), 'failed_stage': stage,
            'inspection_completed': False, 'activation_allowed': False, 'production_supply_ready': False,
            **({'diagnostic_only': True, 'raw_paths_emitted': False, 'report_modified': False} if diagnostic else {}),
            **NO_CHANGES}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
