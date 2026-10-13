"""Descriptor transport, privilege boundary and failure cleanup, no production."""
import array
import errno
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import camera_storage_directory_observer as observer
import inspect_camera_credential_storage_topology as topology
import test_inspect_camera_credential_storage_topology as legacy

TOKEN = legacy.TOKEN


class Channel:
    def __init__(self, raw, ancillary=(), flags=0): self.packet = (raw, list(ancillary), flags, None)
    def recvmsg(self, *args): return self.packet


class DescriptorObserverTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)/'database'; self.directory.mkdir()
        self.path = str(self.directory)
        changed = patch.object(observer, 'HOST_PATH', self.path); changed.start(); self.addCleanup(changed.stop)
        self.reader = Mock(); self.reader.descriptor_mount.return_value = 123

    def descriptor_packet(self, *, read=False):
        descriptors, chain = observer.open_directory(self.path)
        self.addCleanup(lambda: [os.close(fd) for fd in descriptors])
        final = os.open(self.directory, os.O_RDONLY|os.O_DIRECTORY) if read else os.dup(descriptors[-1])
        raw = json.dumps({'scope': observer.SCOPE, 'path': self.path, 'status': 'observed', 'chain': chain}).encode()
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [final]).tobytes()),
            (socket.SOL_SOCKET, socket.SCM_CREDENTIALS, struct.pack('3i', 42, 0, 0))]
        return raw, ancillary, final

    def assert_closed(self, fd):
        with self.assertRaises(OSError) as caught: os.fstat(fd)
        self.assertEqual(caught.exception.errno, errno.EBADF)

    def test_allowlisted_path_only_and_symlink_or_file_rejected(self):
        with patch.object(os, 'open') as opened:
            for path in ('/', self.path+'/extra', '/'+TOKEN):
                with self.assertRaises(observer.ObservationError): observer.open_directory(path)
            opened.assert_not_called()
        actual = self.directory/'target'; actual.mkdir(); alias = self.directory/'alias'; alias.symlink_to(actual)
        for path in (alias, alias/'subdir'):
            with patch.object(observer, 'HOST_PATH', str(path)), self.assertRaises(OSError):
                observer.open_directory(str(path))

    def test_native_walk_opens_only_directories_without_contents_or_mutations(self):
        (self.directory/'SECRET').write_text(TOKEN)
        opened, original = [], os.open
        def track(path, flags, *args, **kwargs):
            opened.append((str(path), flags)); return original(path, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=track), \
            patch.object(os, 'listdir', side_effect=AssertionError('listing')), \
            patch.object(os, 'scandir', side_effect=AssertionError('listing')), \
            patch.object(os, 'read', side_effect=AssertionError('contents')), \
            patch.object(os, 'chmod', side_effect=AssertionError('chmod')), \
            patch.object(os, 'chown', side_effect=AssertionError('chown')):
            descriptors, chain = observer.open_directory(self.path)
            try: self.assertEqual(chain[-1][1], self.directory.stat().st_ino)
            finally:
                for fd in descriptors: os.close(fd)
        self.assertNotIn('SECRET', [name for name, _ in opened])
        self.assertTrue(all(flags & os.O_PATH and flags & os.O_NOFOLLOW for _, flags in opened))

    def test_fixed_wal_child_only_and_native_symlink_rejection(self):
        wal = self.directory/'pg_wal'; wal.mkdir()
        descriptors, chain = observer.open_directory(str(wal))
        try: self.assertEqual(chain[-1][1], wal.stat().st_ino)
        finally:
            for fd in descriptors: os.close(fd)
        with patch.object(os, 'open') as opened:
            for path in (str(wal)+'/extra', self.path+'/postgresql.conf', self.path+'/../other', str(wal)+'/'):
                with self.assertRaises(observer.ObservationError): observer.open_directory(path)
            opened.assert_not_called()
        wal.rmdir(); target = self.directory/'outside'; target.mkdir(); wal.symlink_to(target)
        with self.assertRaises(OSError): observer.open_directory(str(wal))

    def test_wal_receiver_authenticates_requested_child_and_closes_descriptor(self):
        wal = self.directory/'pg_wal'; wal.mkdir()
        descriptors, chain = observer.open_directory(str(wal))
        try:
            fd = os.dup(descriptors[-1])
            raw = json.dumps({'scope': observer.SCOPE, 'path': str(wal), 'status': 'observed', 'chain': chain}).encode()
            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]).tobytes()),
                (socket.SOL_SOCKET, socket.SCM_CREDENTIALS, struct.pack('3i', 42, 0, 0))]
            result = topology.receive_directory(Channel(raw, ancillary), str(wal), self.reader)
            self.assertTrue(result['privileged_sender_uid_verified']); self.assert_closed(fd)
            fd = os.dup(descriptors[-1]); ancillary[0] = (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]).tobytes())
            with self.assertRaises(topology.ActivationError):
                topology.receive_directory(Channel(raw, ancillary), self.path, self.reader)
            self.assert_closed(fd)
        finally:
            for fd in descriptors: os.close(fd)

    def test_wal_launcher_requires_accepted_layout_and_mapping_source(self):
        root = self.directory/'project'; root.mkdir(); legacy.fixture(root)
        path = root/'project-manifest.json'; manifest = json.loads(path.read_text())
        manifest.update(credential_production_storage_access_diagnostics_server_verified=True,
            validated_credential_production_storage_access_diagnostics_project_sha256=topology.ACCEPTED_ACCESS_DIAGNOSTICS)
        path.write_text(json.dumps(manifest))
        with patch.object(topology.subprocess, 'Popen') as launched:
            with self.assertRaisesRegex(topology.ActivationError, '^ACCEPTED_STORAGE_LAYOUT_REQUIRED$'):
                topology.privileged_directory(root, self.path+'/pg_wal', self.reader)
            launched.assert_not_called()

    def test_isolated_wal_helper_transfers_the_requested_child_with_kernel_credentials(self):
        wal = self.directory/'pg_wal'; wal.mkdir()
        source = Path(observer.__file__).read_text().replace(
            "HOST_PATH = '/media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data'",
            'HOST_PATH = '+repr(self.path))
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET); process = None
        try:
            left.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1); left.settimeout(5)
            process = subprocess.Popen(['/usr/bin/python3', '-I', '-B', '-c', source],
                stdin=right, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd='/', env={})
            right.close(); left.send(json.dumps({'scope': observer.SCOPE, 'path': str(wal)}).encode())
            with topology.MountReader() as reader:
                if os.getuid() == os.getgid() == 0:
                    value = topology.receive_directory(left, str(wal), reader)
                    self.assertTrue(value['privileged_sender_uid_verified'])
                    self.assertEqual(value['signature'][-1][1], wal.stat().st_ino)
                else:
                    with self.assertRaisesRegex(topology.ActivationError, '^PRIVILEGED_DIRECTORY_SENDER_NOT_ROOT$'):
                        topology.receive_directory(left, str(wal), reader)
            output, errors = process.communicate(timeout=3)
            self.assertEqual(output, b''); self.assertEqual(errors, b'')
            self.assertEqual(process.returncode, 0 if os.getuid() == os.getgid() == 0 else 1)
        finally:
            left.close(); right.close()
            if process is not None and process.poll() is None: process.kill(); process.wait(timeout=3)

    def test_failed_walk_closes_all_previously_opened_descriptors(self):
        original, opened = os.open, []
        def denied(path, *args, **kwargs):
            if str(path) == 'database': raise OSError(errno.EACCES, TOKEN)
            fd = original(path, *args, **kwargs); opened.append(fd); return fd
        with patch.object(os, 'open', side_effect=denied), self.assertRaises(OSError): observer.open_directory(self.path)
        for fd in opened: self.assert_closed(fd)

    def test_receiver_checks_actual_descriptor_and_closes_it_after_metadata(self):
        raw, ancillary, fd = self.descriptor_packet()
        value = topology.receive_directory(Channel(raw, ancillary), self.path, self.reader)
        self.assertEqual(value['mount_id'], 123); self.assertTrue(value['privileged_sender_uid_verified'])
        self.assertEqual(value['owner_uid'], os.getuid()); self.assert_closed(fd)
        self.assertNotIn('signature', json.dumps({k: v for k, v in value.items() if k != 'signature'}))

    def test_nonroot_sender_and_truncated_packet_are_rejected_and_fds_closed(self):
        for uid, gid, flags in ((1006, 0, 0), (0, 1007, 0), (0, 0, socket.MSG_CTRUNC), (0, 0, socket.MSG_TRUNC)):
            raw, ancillary, fd = self.descriptor_packet()
            ancillary[1] = (socket.SOL_SOCKET, socket.SCM_CREDENTIALS, struct.pack('3i', 42, uid, gid))
            with self.assertRaises(topology.ActivationError):
                topology.receive_directory(Channel(raw, ancillary, flags), self.path, self.reader)
            self.assert_closed(fd)

    def test_read_capable_descriptor_or_changed_inode_not_accepted(self):
        raw, ancillary, fd = self.descriptor_packet(read=True)
        with self.assertRaisesRegex(topology.ActivationError, '^PRIVILEGED_DIRECTORY_DESCRIPTOR_MISMATCH$'):
            topology.receive_directory(Channel(raw, ancillary), self.path, self.reader)
        self.assert_closed(fd)
        raw, ancillary, fd = self.descriptor_packet(); value = json.loads(raw); value['chain'][-1][1] += 1
        with self.assertRaises(topology.ActivationError):
            topology.receive_directory(Channel(json.dumps(value).encode(), ancillary), self.path, self.reader)
        self.assert_closed(fd)

    def test_unrelated_path_invalid_chain_and_extra_descriptor_rejected_without_leak(self):
        for mutation in ('path', 'chain', 'extra_fd', 'boolean', 'extra_key', 'raw'):
            raw, ancillary, fd = self.descriptor_packet(); value = json.loads(raw); extra = None
            if mutation == 'path': value['path'] = '/'+TOKEN
            elif mutation == 'chain': value['chain'].pop()
            elif mutation == 'boolean': value['chain'][-1][2] = True
            elif mutation == 'extra_key': value['extra'] = TOKEN
            elif mutation == 'extra_fd':
                extra = os.dup(fd); ancillary[0] = (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd, extra]).tobytes())
            raw = TOKEN.encode() if mutation == 'raw' else json.dumps(value).encode()
            with self.assertRaises(topology.ActivationError) as caught:
                topology.receive_directory(Channel(raw, ancillary), self.path, self.reader)
            self.assertNotIn(TOKEN, str(caught.exception)); self.assert_closed(fd)
            if extra is not None: self.assert_closed(extra)

    def test_metadata_reader_error_still_closes_received_descriptor(self):
        raw, ancillary, fd = self.descriptor_packet(); self.reader.descriptor_mount.side_effect = OSError(errno.EACCES, TOKEN)
        with self.assertRaises(OSError): topology.receive_directory(Channel(raw, ancillary), self.path, self.reader)
        self.assert_closed(fd)

    def test_failure_and_empty_response_never_become_success(self):
        credentials = [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS, struct.pack('3i', 42, 0, 0))]
        raw = json.dumps({'scope': observer.SCOPE, 'status': 'failed', 'code': 'PRIVILEGED_DIRECTORY_PERMISSION_DENIED'}).encode()
        with self.assertRaises(topology.identity.IdentityBlocked): topology.receive_directory(Channel(raw, credentials), self.path, self.reader)
        with self.assertRaises(topology.identity.IdentityBlocked): topology.receive_directory(Channel(b''), self.path, self.reader)

    def test_native_socket_transfers_path_descriptor_and_kernel_sender_credentials(self):
        descriptors, chain = observer.open_directory(self.path)
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            left.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            raw = json.dumps({'scope': observer.SCOPE, 'path': self.path, 'status': 'observed', 'chain': chain}).encode()
            right.sendmsg([raw], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [descriptors[-1]]))])
            packet = left.recvmsg(observer.MAX_PACKET, 256, socket.MSG_CMSG_CLOEXEC)
            credential = next(data for level, kind, data in packet[1] if kind == socket.SCM_CREDENTIALS)
            self.assertEqual(struct.unpack('3i', credential)[1:], (os.getuid(), os.getgid()))
            forwarded = Channel(*packet[:3])
            if os.getuid() == os.getgid() == 0:
                result = topology.receive_directory(forwarded, self.path, self.reader)
                self.assertTrue(result['privileged_sender_uid_verified'])
            else:
                with self.assertRaisesRegex(topology.ActivationError, '^PRIVILEGED_DIRECTORY_SENDER_NOT_ROOT$'):
                    topology.receive_directory(forwarded, self.path, self.reader)
        finally:
            left.close(); right.close()
            for fd in descriptors: os.close(fd)

    def test_isolated_system_python_uses_private_stdin_without_project_imports(self):
        source = Path(observer.__file__).read_text().replace(
            "HOST_PATH = '/media/simsys/SSD_EXT4/docker/volumes/vms-project_camera-data/_data'",
            'HOST_PATH = '+repr(self.path))
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        process = None
        try:
            left.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1); left.settimeout(5)
            process = subprocess.Popen(['/usr/bin/python3', '-I', '-B', '-c', source],
                stdin=right, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd='/', env={})
            right.close(); left.send(json.dumps({'scope': observer.SCOPE, 'path': self.path}).encode())
            with topology.MountReader() as reader:
                if os.getuid() == os.getgid() == 0:
                    value = topology.receive_directory(left, self.path, reader)
                    self.assertTrue(value['privileged_sender_uid_verified'])
                    records = reader.mounts(int(os.readlink('self', dir_fd=reader.fd)))
                    self.assertIn(value['mount_id'], records)
                    self.assertEqual(value['owner_uid'], self.directory.stat().st_uid)
                else:
                    with self.assertRaisesRegex(topology.ActivationError, '^PRIVILEGED_DIRECTORY_SENDER_NOT_ROOT$'):
                        topology.receive_directory(left, self.path, reader)
            output, errors = process.communicate(timeout=3)
            self.assertEqual(output, b''); self.assertEqual(errors, b'')
            self.assertEqual(process.returncode, 0 if os.getuid() == os.getgid() == 0 else 1)
        finally:
            left.close(); right.close()
            if process is not None and process.poll() is None: process.kill(); process.wait(timeout=3)

    def test_launcher_timeout_terminates_owned_process_and_stays_blocked(self):
        root = self.directory/'project'; root.mkdir(); legacy.fixture(root)
        manifest = json.loads((root/'project-manifest.json').read_text())
        manifest.update(credential_production_storage_access_diagnostics_server_verified=True,
            validated_credential_production_storage_access_diagnostics_project_sha256=topology.ACCEPTED_ACCESS_DIAGNOSTICS)
        (root/'project-manifest.json').write_text(json.dumps(manifest))
        process = Mock(); process.poll.return_value = None; peers = []
        original = socket.socketpair
        def pair(*args):
            a, b = original(*args); peers.append(b.dup()); return a, b
        try:
            with patch.object(socket, 'socketpair', side_effect=pair), \
                patch.object(topology.subprocess, 'Popen', return_value=process), \
                patch.object(topology, 'receive_directory', side_effect=socket.timeout(TOKEN)):
                with self.assertRaises(topology.identity.IdentityBlocked) as caught:
                    topology.privileged_directory(root, self.path, self.reader)
                self.assertNotIn(TOKEN, str(caught.exception)); process.kill.assert_called_once()
                process.wait.assert_called_once_with(timeout=2)
        finally:
            for peer in peers: peer.close()

    def test_assisted_reader_only_falls_back_for_directory_search_permission(self):
        reader = topology.AssistedMountReader(Path('/synthetic'))
        with patch.object(topology.MountReader, 'directory', side_effect=topology.StorageAccessDenied(errno.EACCES,
            'open_directory_component', self.path)), patch.object(topology, 'privileged_directory', return_value={'ok': True}) as fallback:
            self.assertEqual(reader.directory(self.path), {'ok': True}); fallback.assert_called_once()
        for error in (OSError(errno.ENOENT, TOKEN), topology.StorageAccessDenied(errno.EACCES, 'read_own_directory_fdinfo', self.path)):
            with patch.object(topology.MountReader, 'directory', side_effect=error), patch.object(topology, 'privileged_directory') as fallback:
                with self.assertRaises(OSError): reader.directory(self.path)
                fallback.assert_not_called()

    def test_privileged_launcher_requires_accepted_d4f_and_source_before_process(self):
        root = self.directory/'project'; root.mkdir(); legacy.fixture(root)
        with patch.object(topology.subprocess, 'Popen') as launched:
            with self.assertRaisesRegex(topology.ActivationError, '^ACCEPTED_STORAGE_ACCESS_DIAGNOSTICS_REQUIRED$'):
                topology.privileged_directory(root, self.path, self.reader)
            launched.assert_not_called()
        manifest = json.loads((root/'project-manifest.json').read_text())
        manifest.update(credential_production_storage_access_diagnostics_server_verified=True,
            validated_credential_production_storage_access_diagnostics_project_sha256=topology.ACCEPTED_ACCESS_DIAGNOSTICS)
        (root/'project-manifest.json').write_text(json.dumps(manifest))
        (root/topology.OBSERVER_SOURCE).write_text(TOKEN)
        with patch.object(topology.subprocess, 'Popen') as launched, self.assertRaises(topology.ActivationError):
            topology.privileged_directory(root, self.path, self.reader)
        launched.assert_not_called()

    def test_launcher_has_fixed_isolated_command_private_stdin_and_unavailable_is_blocked(self):
        root = self.directory/'project'; root.mkdir(); legacy.fixture(root)
        manifest = json.loads((root/'project-manifest.json').read_text())
        manifest.update(credential_production_storage_access_diagnostics_server_verified=True,
            validated_credential_production_storage_access_diagnostics_project_sha256=topology.ACCEPTED_ACCESS_DIAGNOSTICS)
        (root/'project-manifest.json').write_text(json.dumps(manifest))
        process = Mock(); process.poll.return_value = 0; process.wait.return_value = 0
        def launch(command, **kwargs):
            self.assertEqual(command[:7], ['/usr/bin/sudo', '-n', '--', '/usr/bin/python3', '-I', '-B', '-c'])
            self.assertEqual(command[7], (root/topology.OBSERVER_SOURCE).read_text())
            self.assertEqual(kwargs['cwd'], '/'); self.assertEqual(kwargs['env'], {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            self.assertEqual(kwargs['stdin'].family, socket.AF_UNIX)
            self.assertEqual(kwargs['stdin'].type, socket.SOCK_SEQPACKET)
            return process
        with patch.object(topology.subprocess, 'Popen', side_effect=launch), \
            patch.object(topology, 'receive_directory', return_value={'observed': True}):
            # A duplicated child socket keeps the test send endpoint connected.
            original = socket.socketpair; peers = []
            def pair(*args):
                a, b = original(*args); peers.append(b.dup()); return a, b
            with patch.object(socket, 'socketpair', side_effect=pair):
                self.assertEqual(topology.privileged_directory(root, self.path, self.reader), {'observed': True})
            for peer in peers: peer.close()
        with patch.object(topology.subprocess, 'Popen', side_effect=OSError(errno.EACCES, TOKEN)):
            with self.assertRaisesRegex(topology.identity.IdentityBlocked, '^PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE$') as caught:
                topology.privileged_directory(root, self.path, self.reader)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_helper_bad_request_or_uid_is_sanitized_and_does_not_open_path(self):
        for uid, request in ((1006, {'scope': observer.SCOPE, 'path': self.path}),
            (0, {'scope': observer.SCOPE, 'path': '/'+TOKEN}),
            (0, {'scope': observer.SCOPE, 'path': self.path, 'extra': TOKEN})):
            channel = Mock(); channel.family = socket.AF_UNIX; channel.type = socket.SOCK_SEQPACKET
            channel.recvmsg.return_value = (json.dumps(request).encode(), [], 0, None)
            with patch.object(sys, 'argv', ['-c']), patch.object(os, 'getuid', return_value=uid), \
                patch.object(os, 'geteuid', return_value=uid), patch.object(os, 'getgid', return_value=uid), \
                patch.object(os, 'getegid', return_value=uid), patch.object(signal, 'alarm'), \
                patch.object(observer, 'open_directory') as opened:
                self.assertEqual(observer.serve(channel), 1); opened.assert_not_called()
            self.assertNotIn(TOKEN, channel.send.call_args.args[0].decode())

    def test_helper_failure_closes_opened_fds_and_does_not_emit_os_error_text(self):
        channel = Mock(); channel.family = socket.AF_UNIX; channel.type = socket.SOCK_SEQPACKET
        channel.recvmsg.return_value = (json.dumps({'scope': observer.SCOPE, 'path': self.path}).encode(), [], 0, None)
        channel.sendmsg.side_effect = OSError(errno.EIO, TOKEN)
        descriptors = []
        original = observer.open_directory
        def track(path):
            values, chain = original(path); descriptors.extend(values); return values, chain
        with patch.object(sys, 'argv', ['-c']), patch.object(os, 'getuid', return_value=0), \
            patch.object(os, 'geteuid', return_value=0), patch.object(os, 'getgid', return_value=0), \
            patch.object(os, 'getegid', return_value=0), patch.object(signal, 'alarm'), \
            patch.object(observer, 'open_directory', side_effect=track):
            self.assertEqual(observer.serve(channel), 1)
        self.assertNotIn(TOKEN, channel.send.call_args.args[0].decode())
        for fd in descriptors: self.assert_closed(fd)


if __name__ == '__main__': unittest.main()
