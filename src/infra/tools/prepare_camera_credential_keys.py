#!/usr/bin/env python3
"""Prepare independent camera credential keys; never change services, DB or env."""
import argparse
import base64
import binascii
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

MAX_BYTES = 32768
KEY_DIRECTORY = ('var', 'camera', 'credential-keys')
KEY_FILE = 'key-bundle.json'
LOCK_FILE = '.prepare.lock'
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class KeyPreparationError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise KeyPreparationError(code)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'KEY_BUNDLE_INVALID')
        result[key] = value
    return result


def reject_constant(value):
    raise KeyPreparationError('KEY_BUNDLE_INVALID')


def validate_bundle(body):
    require(0 < len(body) <= MAX_BYTES, 'KEY_BUNDLE_INVALID')
    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
        require(isinstance(value, dict) and set(value) == {'format_version', 'encryption', 'idempotency'}
                and type(value['format_version']) is int and value['format_version'] == 1,
                'KEY_BUNDLE_INVALID')
        seen = set()
        for purpose, prefix in (('encryption', 'enc-'), ('idempotency', 'idem-')):
            part = value[purpose]
            require(isinstance(part, dict) and set(part) == {'active_key_id', 'keys'}
                    and isinstance(part['keys'], dict) and 1 <= len(part['keys']) <= 16,
                    'KEY_BUNDLE_INVALID')
            for name, encoded in part['keys'].items():
                require(isinstance(name, str) and re.fullmatch(prefix + '[0-9a-f]{16}', name)
                        and isinstance(encoded, str), 'KEY_BUNDLE_INVALID')
                raw = base64.b64decode(encoded, validate=True)
                require(len(raw) == 32 and base64.b64encode(raw).decode() == encoded
                        and raw not in seen, 'KEY_BUNDLE_INVALID')
                seen.add(raw)
            require(isinstance(part['active_key_id'], str)
                    and part['active_key_id'] in part['keys'], 'KEY_BUNDLE_INVALID')
        return value
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError):
        raise KeyPreparationError('KEY_BUNDLE_INVALID') from None


def check_owned(info, mode=None, *, regular=False):
    require(info.st_uid == os.getuid(), 'KEY_PATH_OWNER_INVALID')
    if regular:
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'KEY_FILE_TYPE_INVALID')
    else:
        require(stat.S_ISDIR(info.st_mode), 'KEY_DIRECTORY_TYPE_INVALID')
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode, 'KEY_PATH_PERMISSIONS_INVALID')


def key_directory(root, create):
    root = Path(root).absolute()
    require('..' not in root.parts, 'PROJECT_ROOT_INVALID')
    descriptor = os.open('/', DIRECTORY_FLAGS)
    try:
        for name in root.parts[1:]:
            opened = os.open(name, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = opened
        check_owned(os.fstat(descriptor))
        for index, name in enumerate(KEY_DIRECTORY):
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            opened = os.open(name, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = opened
            check_owned(os.fstat(descriptor), 0o700 if index == 2 else None)
        return descriptor, root.joinpath(*KEY_DIRECTORY)
    except BaseException:
        os.close(descriptor)
        raise


def read_bundle(directory):
    descriptor = os.open(KEY_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        check_owned(before, 0o600, regular=True)
        require(0 < before.st_size <= MAX_BYTES, 'KEY_BUNDLE_INVALID')
        chunks, remaining = [], MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'KEY_FILE_CHANGED')
        return validate_bundle(b''.join(chunks))
    finally:
        os.close(descriptor)


def new_bundle():
    encryption = secrets.token_bytes(32)
    idempotency = secrets.token_bytes(32)
    while idempotency == encryption:
        idempotency = secrets.token_bytes(32)
    def part(prefix, raw):
        identity = prefix + secrets.token_hex(8)
        return {'active_key_id': identity, 'keys': {identity: base64.b64encode(raw).decode()}}
    return {'format_version': 1, 'encryption': part('enc-', encryption),
            'idempotency': part('idem-', idempotency)}


def write_new_bundle(directory, value):
    # Atomic create-only publication. Never replace an existing bundle, even
    # if an uncooperative writer creates the destination while we hold the lock.
    temporary = '.key-bundle-' + secrets.token_hex(8) + '.tmp'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write((json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, KEY_FILE, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=directory)
    os.fsync(directory)


def prepare(root, apply=False):
    try:
        directory, path = key_directory(root, apply)
    except FileNotFoundError:
        if not apply:
            return {'status': 'not_prepared', 'code': 'EXPLICIT_APPLY_REQUIRED',
                    'service_restart_performed': False, 'database_schema_modified': False}
        raise
    lock = None
    try:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
        if apply:
            flags |= os.O_CREAT
        lock = os.open(LOCK_FILE, flags, 0o600, dir_fd=directory)
        check_owned(os.fstat(lock), 0o600, regular=True)
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if apply else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise KeyPreparationError('KEY_PREPARATION_LOCKED') from None
        require(set(os.listdir(directory)) <= {KEY_FILE, LOCK_FILE}, 'KEY_DIRECTORY_CONTENTS_INVALID')
        try:
            value = read_bundle(directory)
            status = 'already_prepared' if apply else 'validated'
        except FileNotFoundError:
            if not apply:
                return {'status': 'not_prepared', 'code': 'EXPLICIT_APPLY_REQUIRED',
                        'service_restart_performed': False, 'database_schema_modified': False}
            value = new_bundle()
            validate_bundle(json.dumps(value).encode())
            write_new_bundle(directory, value)
            value = read_bundle(directory)
            status = 'prepared'
        current, _ = key_directory(root, False)
        try:
            original, present = os.fstat(directory), os.fstat(current)
            require((original.st_dev, original.st_ino) == (present.st_dev, present.st_ino)
                    and read_bundle(current) == value
                    and set(os.listdir(current)) <= {KEY_FILE, LOCK_FILE}, 'KEY_PATH_CHANGED')
        finally:
            os.close(current)
        return {'status': status, 'scope': 'camera_credential_key_bundle', 'key_file': str(path / KEY_FILE),
                'format_version': 1, 'directory_permissions': '0700', 'file_permissions': '0600',
                'encryption_key_count': len(value['encryption']['keys']),
                'idempotency_key_count': len(value['idempotency']['keys']),
                'active_encryption_key_id': value['encryption']['active_key_id'],
                'active_idempotency_key_id': value['idempotency']['active_key_id'],
                'keys_activated_in_api': False, 'service_restart_performed': False,
                'database_schema_modified': False, 'environment_modified': False}
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        value = prepare(args.project_root, args.apply)
        print(json.dumps(value))
        return 2 if value['status'] == 'not_prepared' else 0
    except (KeyPreparationError, OSError, ValueError, TypeError, RecursionError) as exc:
        code = str(exc) if isinstance(exc, KeyPreparationError) else 'KEY_PREPARATION_UNAVAILABLE'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code):
            code = 'KEY_PREPARATION_UNAVAILABLE'
        print(json.dumps({'status': 'failed', 'scope': 'camera_credential_key_bundle',
                          'code': code, 'keys_activated_in_api': False,
                          'service_restart_performed': False, 'database_schema_modified': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
