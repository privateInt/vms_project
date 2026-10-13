#!/usr/bin/env python3
"""Back up existing camera keys privately; never restore, rotate or activate keys."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import prepare_camera_credential_keys as keys

BACKUP_DIRECTORY = 'credential-key-backups'
BACKUP_LOCK = '.backup.lock'
MANIFEST = 'backup-manifest.json'
SCOPE = 'camera_credential_key_backup'


def open_directory(path):
    path = Path(path).absolute()
    keys.require('..' not in path.parts, 'KEY_BACKUP_PATH_INVALID')
    descriptor = os.open('/', keys.DIRECTORY_FLAGS)
    try:
        for name in path.parts[1:]:
            opened = os.open(name, keys.DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = opened
        keys.check_owned(os.fstat(descriptor))
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_private(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        keys.check_owned(before, 0o600, regular=True)
        keys.require(0 < before.st_size <= keys.MAX_BYTES, 'KEY_BACKUP_FILE_INVALID')
        body = bytearray()
        while len(body) <= keys.MAX_BYTES:
            chunk = os.read(descriptor, keys.MAX_BYTES + 1 - len(body))
            if not chunk:
                break
            body.extend(chunk)
        keys.require(len(body) == before.st_size and identity(before) == identity(os.fstat(descriptor)),
                     'KEY_BACKUP_FILE_CHANGED')
        return bytes(body), identity(before)
    finally:
        os.close(descriptor)


def manifest_bytes(body, value):
    metadata = {'format_version': 1, 'purpose': SCOPE,
                'bundle_sha256': hashlib.sha256(body).hexdigest(),
                'encryption_key_ids': sorted(value['encryption']['keys']),
                'idempotency_key_ids': sorted(value['idempotency']['keys']),
                'active_encryption_key_id': value['encryption']['active_key_id'],
                'active_idempotency_key_id': value['idempotency']['active_key_id'],
                'database_backup_included': False,
                'restore_requires_fresh_encryption_key': True,
                'runtime_activation_allowed': False}
    return (json.dumps(metadata, indent=2, sort_keys=True) + '\n').encode()


def write_new_file(directory, name, body):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
    with os.fdopen(descriptor, 'wb') as stream:
        keys.check_owned(os.fstat(stream.fileno()), 0o600, regular=True)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def verify_snapshot(directory, name, body, metadata):
    snapshot = os.open(name, keys.DIRECTORY_FLAGS, dir_fd=directory)
    try:
        keys.check_owned(os.fstat(snapshot), 0o700)
        keys.require(set(os.listdir(snapshot)) == {keys.KEY_FILE, MANIFEST}, 'KEY_BACKUP_INCOMPLETE')
        try:
            saved, _ = read_private(snapshot, keys.KEY_FILE)
            receipt, _ = read_private(snapshot, MANIFEST)
        except FileNotFoundError:
            raise keys.KeyPreparationError('KEY_BACKUP_INCOMPLETE') from None
        keys.require(saved == body and receipt == metadata, 'KEY_BACKUP_MISMATCH')
        keys.require(set(os.listdir(snapshot)) == {keys.KEY_FILE, MANIFEST}, 'KEY_BACKUP_INCOMPLETE')
    finally:
        os.close(snapshot)


def check_source(root, source, body, original, lock_info):
    current, _ = keys.key_directory(root, False)
    try:
        a, b = os.fstat(source), os.fstat(current)
        keys.require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), 'KEY_SOURCE_PATH_CHANGED')
        keys.require(set(os.listdir(current)) == {keys.KEY_FILE, keys.LOCK_FILE}, 'KEY_DIRECTORY_CONTENTS_INVALID')
        present, info = read_private(current, keys.KEY_FILE)
        current_lock = read_lock_identity(current, keys.LOCK_FILE)
        keys.require(present == body and info == original and current_lock == lock_info, 'KEY_SOURCE_CHANGED')
    finally:
        os.close(current)


def read_lock_identity(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        keys.check_owned(info, 0o600, regular=True)
        return identity(info)
    finally:
        os.close(descriptor)


def backup(root, apply=False):
    source, path = keys.key_directory(root, False)
    source_lock = directory = backup_lock = None
    try:
        source_lock = os.open(keys.LOCK_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                              dir_fd=source)
        keys.check_owned(os.fstat(source_lock), 0o600, regular=True)
        lock_info = identity(os.fstat(source_lock))
        try:
            fcntl.flock(source_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise keys.KeyPreparationError('KEY_PREPARATION_LOCKED') from None
        keys.require(set(os.listdir(source)) == {keys.KEY_FILE, keys.LOCK_FILE}, 'KEY_DIRECTORY_CONTENTS_INVALID')
        body, original = read_private(source, keys.KEY_FILE)
        value = keys.validate_bundle(body)
        metadata = manifest_bytes(body, value)
        name = 'bundle-' + hashlib.sha256(body).hexdigest()
        destination = path.parent / BACKUP_DIRECTORY
        check_source(root, source, body, original, lock_info)
        result = {'status': 'not_backed_up', 'scope': SCOPE,
                  'backup_directory': str(destination / name),
                  'backup_ready': False, 'backup_matches_source': False,
                  'active_encryption_key_id': value['encryption']['active_key_id'],
                  'active_idempotency_key_id': value['idempotency']['active_key_id'],
                  'encryption_key_count': len(value['encryption']['keys']),
                  'idempotency_key_count': len(value['idempotency']['keys']),
                  'source_keys_unchanged': True, 'keys_activated_in_api': False,
                  'service_restart_performed': False, 'database_schema_modified': False,
                  'environment_modified': False, 'database_backup_included': False,
                  'restore_ready': False, 'restore_fence_implemented': False}
        parent = open_directory(path.parent)
        try:
            if apply:
                try:
                    os.mkdir(BACKUP_DIRECTORY, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            try:
                directory = os.open(BACKUP_DIRECTORY, keys.DIRECTORY_FLAGS, dir_fd=parent)
            except FileNotFoundError:
                keys.require(not apply, 'KEY_BACKUP_DIRECTORY_MISSING')
                return result
        finally:
            os.close(parent)
        keys.check_owned(os.fstat(directory), 0o700)
        flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        flags |= os.O_RDWR | os.O_CREAT if apply else os.O_RDONLY
        try:
            backup_lock = os.open(BACKUP_LOCK, flags, 0o600, dir_fd=directory)
        except FileNotFoundError:
            keys.require(not apply and not os.listdir(directory), 'KEY_BACKUP_INCOMPLETE')
            return result
        keys.check_owned(os.fstat(backup_lock), 0o600, regular=True)
        try:
            fcntl.flock(backup_lock, (fcntl.LOCK_EX if apply else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise keys.KeyPreparationError('KEY_BACKUP_LOCKED') from None
        keys.require(all(item == BACKUP_LOCK or re.fullmatch('bundle-[0-9a-f]{64}', item)
                         for item in os.listdir(directory)), 'KEY_BACKUP_DIRECTORY_CONTENTS_INVALID')
        created = False
        if apply:
            try:
                os.mkdir(name, 0o700, dir_fd=directory)
                created = True
            except FileExistsError:
                pass
        if created:
            # Publish the completion record last. A crash can leave a private
            # incomplete directory; retries must reject it, never repair/overwrite.
            snapshot = os.open(name, keys.DIRECTORY_FLAGS, dir_fd=directory)
            try:
                keys.check_owned(os.fstat(snapshot), 0o700)
                write_new_file(snapshot, keys.KEY_FILE, body)
                write_new_file(snapshot, MANIFEST, metadata)
                os.fsync(snapshot)
            finally:
                os.close(snapshot)
            os.fsync(directory)
        try:
            verify_snapshot(directory, name, body, metadata)
        except FileNotFoundError:
            keys.require(not apply, 'KEY_BACKUP_INCOMPLETE')
            return result
        check_source(root, source, body, original, lock_info)
        current = open_directory(destination)
        try:
            a, b = os.fstat(directory), os.fstat(current)
            keys.require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), 'KEY_BACKUP_PATH_CHANGED')
            keys.check_owned(b, 0o700)
            verify_snapshot(current, name, body, metadata)
        finally:
            os.close(current)
        result.update(status='backed_up' if created else 'already_backed_up' if apply else 'validated',
                      backup_ready=True, backup_matches_source=True,
                      directory_permissions='0700', file_permissions='0600')
        return result
    finally:
        for descriptor in (backup_lock, directory, source_lock, source):
            if descriptor is not None:
                os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = backup(args.project_root, args.apply)
        print(json.dumps(result))
        return 0 if result['backup_ready'] else 2
    except (keys.KeyPreparationError, OSError, ValueError, TypeError, RecursionError, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, keys.KeyPreparationError) else 'KEY_BACKUP_UNAVAILABLE'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code):
            code = 'KEY_BACKUP_UNAVAILABLE'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': code,
                          'keys_activated_in_api': False, 'service_restart_performed': False,
                          'database_schema_modified': False, 'restore_ready': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
