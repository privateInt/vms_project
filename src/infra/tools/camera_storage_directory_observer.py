#!/usr/bin/env python3
"""One of two fixed O_PATH directory observations over an anonymous socket.

Standalone standard-library source, executed by isolated system Python. No
project imports, procfs, directory listings, DB files, keys, Docker or writes.
"""
import array
import errno
import json
import os
from pathlib import PurePosixPath
import socket
import signal
import stat
import sys

SCOPE = 'camera_storage_directory_descriptor_v1'
HOST_PATH = '/media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data'
MAX_PACKET = 4096


class ObservationError(Exception): pass


def require(condition, code):
    if not condition: raise ObservationError(code)


def allowed_path(path):
    return path in (HOST_PATH, HOST_PATH+'/pg_wal')


def open_directory(path):
    require(allowed_path(path), 'PRIVILEGED_DIRECTORY_PATH_NOT_ALLOWED')
    flags = os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    descriptors, chain = [], []
    try:
        descriptors.append(os.open('/', flags))
        for name in PurePosixPath(path).parts[1:]:
            descriptors.append(os.open(name, flags, dir_fd=descriptors[-1]))
            value = os.fstat(descriptors[-1])
            require(stat.S_ISDIR(value.st_mode), 'PRIVILEGED_DIRECTORY_TYPE_REJECTED')
            chain.append((value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode))
        return descriptors, chain
    except BaseException:
        for fd in reversed(descriptors): os.close(fd)
        raise


def serve(channel):
    descriptors = []
    try:
        require(len(sys.argv) == 1 and sys.platform.startswith('linux'), 'PRIVILEGED_DIRECTORY_INVOCATION_REJECTED')
        require(os.getuid() == os.geteuid() == os.getgid() == os.getegid() == 0,
            'PRIVILEGED_DIRECTORY_ROOT_REQUIRED')
        require(channel.family == socket.AF_UNIX and channel.type == socket.SOCK_SEQPACKET,
            'PRIVILEGED_DIRECTORY_SOCKET_REJECTED')
        signal.alarm(10)
        channel.settimeout(8)
        raw, ancillary, flags, _ = channel.recvmsg(MAX_PACKET, 0)
        require(not flags and not ancillary and 0 < len(raw) < MAX_PACKET, 'PRIVILEGED_DIRECTORY_REQUEST_REJECTED')
        request = json.loads(raw)
        require(type(request) is dict and set(request) == {'scope', 'path'}
            and request['scope'] == SCOPE and allowed_path(request['path']),
            'PRIVILEGED_DIRECTORY_REQUEST_REJECTED')
        descriptors, chain = open_directory(request['path'])
        message = json.dumps({'scope': SCOPE, 'path': request['path'], 'status': 'observed', 'chain': chain}).encode()
        require(len(message) < MAX_PACKET, 'PRIVILEGED_DIRECTORY_RESPONSE_TOO_LARGE')
        sent = channel.sendmsg([message], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
            array.array('i', [descriptors[-1]]))])
        require(sent == len(message), 'PRIVILEGED_DIRECTORY_SEND_FAILED')
        return 0
    except (ObservationError, OSError, ValueError, TypeError, KeyError) as exc:
        if type(exc) is ObservationError: code = str(exc)
        elif isinstance(exc, OSError) and exc.errno in (errno.ELOOP, errno.ENOTDIR):
            code = 'PRIVILEGED_DIRECTORY_TYPE_REJECTED'
        elif isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM):
            code = 'PRIVILEGED_DIRECTORY_PERMISSION_DENIED'
        else: code = 'PRIVILEGED_DIRECTORY_OBSERVER_FAILED'
        try: channel.send(json.dumps({'scope': SCOPE, 'status': 'failed', 'code': code}).encode())
        except OSError: pass
        return 1
    finally:
        for fd in reversed(descriptors): os.close(fd)
        signal.alarm(0)


def main():
    # fd 0 survives sudo's normal close-from policy. Never accept another fd/path
    # argument, use a filesystem socket, or load a project module as root.
    try:
        with socket.socket(fileno=os.dup(0)) as channel: return serve(channel)
    except (OSError, ValueError): return 1


if __name__ == '__main__': sys.exit(main())
