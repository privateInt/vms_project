#!/usr/bin/env python3
"""Remove reviewed generated project artifacts without backups; retain code and runtime inputs."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile

from camera_activation import activation_lock

SCOPE = 'vms_project_generated_artifact_cleanup'
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
DIRECTORIES = ('build', 'var/patch-backups', 'var/test-streamlit-recovery',
    'var/camera/activation-backups', 'var/camera/source-activation-backups',
    'var/camera/source-list-activation-backups', 'var/camera/device-update-activation-backups',
    'var/camera/source-update-activation-backups', 'var/camera/source-delete-activation-backups',
    'var/camera/device-delete-activation-backups', 'var/camera/credential-key-backups',
    'var/camera/credential-backup-reviews')
CHECK_DIRECTORIES = tuple('var/camera/' + name for name in (
    'credential-storage-checks', 'credential-restore-checks', 'credential-admission-checks',
    'credential-admission-database-checks', 'credential-binding-checks', 'credential-operation-checks',
    'credential-maintenance-checks', 'credential-boundary-checks', 'credential-boundary-restore-checks',
    'credential-boundary-resume-checks', 'credential-management-checks', 'database-tls-checks', 'registry-tls-checks'))
UI_TARGETS = ('var/test-streamlit', 'var/test-streamlit-environment.json', 'var/test-streamlit-setup.log')
FLAGS = {'backup_created': False, 'service_restart_performed': False,
         'production_database_modified': False, 'environment_modified': False,
         'credential_keys_modified': False, 'tls_supply_modified': False,
         'docker_resources_modified': False}


class CleanupError(Exception):
    pass


def require(value, code):
    if not value: raise CleanupError(code)


def open_directory(root):
    root = Path(root).absolute()
    require('..' not in root.parts, 'CLEANUP_ROOT_INVALID')
    fd = os.open('/', DIR_FLAGS)
    try:
        for name in root.parts[1:]:
            child = os.open(name, DIR_FLAGS, dir_fd=fd); os.close(fd); fd = child
        require(os.fstat(fd).st_uid == os.getuid(), 'CLEANUP_ROOT_OWNER_INVALID')
        return fd
    except BaseException:
        os.close(fd); raise


def parent(fd, relative):
    p = PurePosixPath(relative)
    require(not p.is_absolute() and '..' not in p.parts and p.as_posix() == relative,
            'CLEANUP_PATH_INVALID')
    current = os.dup(fd)
    try:
        for name in p.parts[:-1]:
            child = os.open(name, DIR_FLAGS, dir_fd=current); os.close(current); current = child
        return current, p.name
    except BaseException:
        os.close(current); raise


def metadata(info):
    return tuple(getattr(info, name) for name in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid',
                                                 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def describe(fd, name):
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    rows = [('', metadata(info))]; size = info.st_size if stat.S_ISREG(info.st_mode) else 0
    files = int(stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode))
    if stat.S_ISDIR(info.st_mode):
        child = os.open(name, DIR_FLAGS, dir_fd=fd)
        try:
            require((info.st_dev, info.st_ino) == (os.fstat(child).st_dev, os.fstat(child).st_ino),
                    'CLEANUP_DIRECTORY_CHANGED')
            for item in sorted(os.listdir(child)):
                sub = describe(child, item); size += sub['bytes']; files += sub['files']
                rows += [(item + ('/' + path if path else ''), value) for path, value in sub['rows']]
        finally: os.close(child)
    else: require(stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode), 'CLEANUP_SPECIAL_FILE_REJECTED')
    digest = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
    return {'bytes': size, 'files': files, 'fingerprint': digest, 'rows': rows}


def verify_source(root):
    manifest = root / 'project-manifest.json'
    require(not manifest.is_symlink(), 'CLEANUP_SOURCE_SYMLINK_REJECTED')
    value = json.loads(manifest.read_bytes()); files = value.get('files')
    require(value.get('project_artifact_cleanup_implemented') is True and isinstance(files, dict),
            'CLEANUP_PROJECT_SOURCE_REQUIRED')
    fd = open_directory(root)
    try:
        for relative, digest in files.items():
            p = PurePosixPath(relative)
            require(not p.is_absolute() and p.as_posix() == relative
                    and not any(v in ('..', 'var', 'build', '.env', '.git', '__pycache__') for v in p.parts)
                    and re.fullmatch('[0-9a-f]{64}', digest), 'CLEANUP_SOURCE_MANIFEST_INVALID')
            current, name = parent(fd, relative)
            try:
                file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
                with os.fdopen(file, 'rb') as stream:
                    require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'CLEANUP_SOURCE_CHANGED')
                    hashed = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(65536), b''): hashed.update(chunk)
                    require(hashed.hexdigest() == digest, 'CLEANUP_SOURCE_CHANGED')
            finally: os.close(current)
    finally: os.close(fd)
    return hashlib.sha256(manifest.read_bytes()).hexdigest(), files


def targets(fd, remove_ui):
    result = list(DIRECTORIES)
    if remove_ui: result += list(UI_TARGETS)
    for directory in CHECK_DIRECTORIES:
        try:
            current, name = parent(fd, directory)
            try: child = os.open(name, DIR_FLAGS, dir_fd=current)
            finally: os.close(current)
        except FileNotFoundError: continue
        try: result += [directory + '/' + n for n in os.listdir(child) if n.endswith('.log')]
        finally: os.close(child)
    def caches(current, prefix):
        for name in sorted(os.listdir(current)):
            info = os.stat(name, dir_fd=current, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode): continue
            relative = prefix + '/' + name
            if name == '__pycache__': result.append(relative); continue
            child = os.open(name, DIR_FLAGS, dir_fd=current)
            try: caches(child, relative)
            finally: os.close(child)
    try: child = os.open('src', DIR_FLAGS, dir_fd=fd)
    except FileNotFoundError: child = None
    if child is not None:
        try: caches(child, 'src')
        finally: os.close(child)
    plan = []
    for relative in sorted(set(result)):
        try:
            current, name = parent(fd, relative)
            try:
                info = os.stat(name, dir_fd=current, follow_symlinks=False)
                require(not stat.S_ISLNK(info.st_mode), 'CLEANUP_TARGET_SYMLINK_REJECTED')
                row = describe(current, name)
            finally: os.close(current)
        except FileNotFoundError: continue
        plan.append({'path': relative, 'bytes': row['bytes'], 'files': row['files'], 'fingerprint': row['fingerprint']})
    return plan


def protected_files(fd, plan):
    removed = tuple(v['path'] for v in plan); result = {}
    def walk(current, prefix=''):
        for name in os.listdir(current):
            relative = prefix + '/' + name if prefix else name
            if relative == '.git' or any(relative == v or relative.startswith(v + '/') for v in removed): continue
            info = os.stat(name, dir_fd=current, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, DIR_FLAGS, dir_fd=current)
                try: walk(child, relative)
                finally: os.close(child)
            else: result[relative] = metadata(info)
    walk(fd); return result


def assert_ui_idle(root, proc=Path('/proc')):
    key = os.fsencode(str(root / 'var/test-streamlit'))
    require(proc.is_dir(), 'CLEANUP_UI_PROCESS_CHECK_UNAVAILABLE')
    for entry in proc.iterdir():
        if not entry.name.isdecimal(): continue
        try:
            if entry.stat().st_uid != os.getuid(): continue
            with (entry / 'cmdline').open('rb') as stream: body = stream.read(1024 * 1024 + 1)
            require(len(body) <= 1024 * 1024, 'CLEANUP_UI_PROCESS_CHECK_INCOMPLETE')
            require(key not in body, 'CLEANUP_UI_ENVIRONMENT_IN_USE')
            if b'streamlit' in body.split(b'\0'):
                cwd = Path(os.readlink(entry / 'cwd'))
                require(cwd != root and root not in cwd.parents, 'CLEANUP_UI_ENVIRONMENT_IN_USE')
            # Some unrelated same-UID non-dumpable processes deny maps access.
            # Their readable command lines are still checked; maps are an extra observation.
            try:
                with (entry / 'maps').open('rb') as stream: mapped = stream.read(4 * 1024 * 1024)
            except PermissionError: mapped = b''
            require(key not in mapped, 'CLEANUP_UI_ENVIRONMENT_IN_USE')
        except (FileNotFoundError, ProcessLookupError): continue
        except PermissionError: raise CleanupError('CLEANUP_UI_PROCESS_CHECK_PERMISSION_REQUIRED') from None


def assert_no_mounts(root, plan):
    try: text = Path('/proc/self/mountinfo').read_text()
    except OSError: raise CleanupError('CLEANUP_MOUNT_CHECK_UNAVAILABLE') from None
    points = []
    for line in text.splitlines():
        fields = line.split()
        require(len(fields) >= 10 and '-' in fields, 'CLEANUP_MOUNT_METADATA_INVALID')
        value = re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), fields[4])
        points.append(Path(value))
    for row in plan:
        target = root / row['path']
        require(not any(point == target or target in point.parents for point in points),
                'CLEANUP_MOUNT_BOUNDARY_REJECTED')


def remove_entry(fd, name):
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
        child = os.open(name, DIR_FLAGS, dir_fd=fd)
        try:
            require((info.st_dev, info.st_ino) == (os.fstat(child).st_dev, os.fstat(child).st_ino),
                    'CLEANUP_DIRECTORY_CHANGED')
            for item in sorted(os.listdir(child)): remove_entry(child, item)
            now = os.stat(name, dir_fd=fd, follow_symlinks=False)
            require((now.st_dev, now.st_ino) == (info.st_dev, info.st_ino), 'CLEANUP_DIRECTORY_CHANGED')
        finally: os.close(child)
        os.rmdir(name, dir_fd=fd)
    else:
        require(stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode), 'CLEANUP_SPECIAL_FILE_REJECTED')
        os.unlink(name, dir_fd=fd)


def source_archive(root, destination, files):
    destination = Path(destination).absolute()
    require(destination.name.endswith('.tar.gz') and not destination.exists() and not destination.is_symlink(),
            'CLEANUP_SOURCE_ARCHIVE_DESTINATION_INVALID')
    revision, current_files = verify_source(root)
    require(current_files == files, 'CLEANUP_SOURCE_CHANGED')
    # O_EXCL never replaces an existing user file. Export verified bytes through no-follow descriptors.
    root_fd = open_directory(root)
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for relative in sorted({*files, 'project-manifest.json'}):
                current, name = parent(root_fd, relative)
                try:
                    file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
                    with os.fdopen(file, 'rb') as content:
                        info = os.fstat(content.fileno())
                        require(stat.S_ISREG(info.st_mode), 'CLEANUP_SOURCE_ARCHIVE_FILE_INVALID')
                        body = content.read()
                finally: os.close(current)
                require(hashlib.sha256(body).hexdigest() == files.get(relative, revision), 'CLEANUP_SOURCE_CHANGED')
                entry = tarfile.TarInfo('vms_project/' + relative)
                entry.size = len(body); entry.mode = stat.S_IMODE(info.st_mode); entry.mtime = 0
                archive.addfile(entry, io.BytesIO(body))
    finally: os.close(root_fd)
    return str(destination)


def cleanup(root, apply=False, remove_ui=False, archive=None):
    root = Path(root).absolute(); removed = []
    revision, files = verify_source(root)
    require(archive is None or apply, 'CLEANUP_SOURCE_ARCHIVE_REQUIRES_APPLY')
    with activation_lock(root):
        fd = open_directory(root)
        try:
            plan = targets(fd, remove_ui)
            assert_no_mounts(root, plan)
            before = protected_files(fd, plan)
            if remove_ui and any(v['path'] == UI_TARGETS[0] for v in plan): assert_ui_idle(root)
            if apply:
                require(verify_source(root)[0] == revision, 'CLEANUP_SOURCE_CHANGED')
                for row in plan:
                    current, name = parent(fd, row['path'])
                    try: require(describe(current, name)['fingerprint'] == row['fingerprint'], 'CLEANUP_TARGET_CHANGED')
                    finally: os.close(current)
                try:
                    for row in plan:
                        current, name = parent(fd, row['path'])
                        try: remove_entry(current, name)
                        finally: os.close(current)
                        removed.append(row['path'])
                except BaseException as exc:
                    exc.cleanup_removed_count = len(removed); raise
                require(protected_files(fd, plan) == before and verify_source(root)[0] == revision,
                        'CLEANUP_PROTECTED_FILES_CHANGED')
            result = {'status': 'cleaned' if apply and removed else ('already_clean' if apply else 'planned'),
                'scope': SCOPE, 'checked_revision': revision, 'target_count': len(plan),
                'candidate_file_bytes': sum(v['bytes'] for v in plan), 'candidate_file_count': sum(v['files'] for v in plan),
                'removed_target_count': len(removed), 'targets': [{k: v for k, v in row.items() if k != 'fingerprint'} for row in plan],
                'streamlit_environment_removal_requested': remove_ui,
                'streamlit_environment_removed': UI_TARGETS[0] in removed,
                'source_and_runtime_inputs_preserved': True, 'test_json_reports_preserved': True, **FLAGS}
            if archive is not None: result['source_archive'] = source_archive(root, archive, files)
            return result
        except BaseException as exc:
            exc.cleanup_removed_count = len(removed); raise
        finally: os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--remove-ui-environment', action='store_true')
    parser.add_argument('--source-archive', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(cleanup(args.project_root, args.apply, args.remove_ui_environment, args.source_archive), ensure_ascii=False)); return 0
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc) if isinstance(exc, CleanupError) else 'CLEANUP_FAILED'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code): code = 'CLEANUP_FAILED'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': code,
            'removed_target_count': getattr(exc, 'cleanup_removed_count', 0), **FLAGS}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
