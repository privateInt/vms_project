"""Real OpenSSL/TLS and private synthetic fixtures; no production access."""
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import stat
import subprocess
import tempfile
import unittest
import warnings
from unittest.mock import patch

import prepare_camera_database_tls_candidate as tool


class DatabaseTLSCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='vms-tls-unit-')
        cls.template = Path(cls.temporary.name) / 'template'
        cls.template.mkdir(mode=0o700)
        cls.first = tool.prepare(cls.template, True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix='vms-tls-case-')
        self.addCleanup(fixture.cleanup)
        self.parent = Path(fixture.name)
        self.root = self.parent / 'project'
        shutil.copytree(self.template, self.root)
        self.directory = self.root.joinpath(*tool.DIRECTORY)
        self.candidate = self.directory / tool.CANDIDATE
        self.sentinels = {'.env': b'PRIVATE_ENV_SENTINEL',
                          'var/camera/credential-keys/key-bundle.json': b'PRIVATE_KEY_SENTINEL',
                          'var/control/authority.json': b'PRIVATE_AUTHORITY_SENTINEL'}
        for name, body in self.sentinels.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body); path.chmod(0o600)

    def bodies(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                for p in self.candidate.iterdir()}

    @contextlib.contextmanager
    def opened(self):
        fd = os.open(self.candidate, tool.DIR_FLAGS)
        try: yield fd
        finally: os.close(fd)

    def test_generated_private_profile_actual_mtls_and_proposals(self):
        value = self.first
        self.assertEqual(value['status'], 'prepared')
        self.assertTrue(value['actual_socketpair_mtls_verified'])
        self.assertTrue(value['wrong_hostname_rejected'])
        self.assertTrue(value['untrusted_ca_rejected'])
        self.assertTrue(value['missing_client_certificate_rejected'])
        self.assertEqual(value['endpoint_state'], 'proposal-unreserved')
        for flag in tool.NO_CHANGES: self.assertIs(value[flag], False)
        receipt = json.loads((self.candidate / 'candidate.json').read_bytes())
        self.assertEqual(receipt['endpoint_proposal']['sslmode'], 'verify-full')
        self.assertNotEqual(receipt['endpoint_proposal']['runtime_source_ip'],
                            receipt['endpoint_proposal']['maintenance_source_ip'])
        for file in self.candidate.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.candidate.stat().st_mode), 0o700)

    def test_repeat_and_read_only_validation_preserve_all_bytes_modes_and_mtimes(self):
        before = self.bodies()
        again = tool.prepare(self.root, True)
        read_only = tool.prepare(self.root)
        self.assertEqual(again['status'], 'already_prepared')
        self.assertEqual(read_only['status'], 'validated')
        self.assertEqual(again['candidate_sha256'], self.first['candidate_sha256'])
        self.assertEqual(before, self.bodies())
        for name, body in self.sentinels.items(): self.assertEqual((self.root / name).read_bytes(), body)

    def test_without_apply_creates_nothing(self):
        root = self.parent / 'empty'; root.mkdir(mode=0o700)
        self.assertEqual(tool.prepare(root)['status'], 'not_prepared')
        self.assertEqual(list(root.iterdir()), [])

    def test_read_only_missing_candidate_does_not_create_it(self):
        shutil.rmtree(self.candidate)
        self.assertEqual(tool.prepare(self.root)['status'], 'not_prepared')
        self.assertFalse(self.candidate.exists())

    def test_umask_027_still_produces_private_files(self):
        root = self.parent / 'umask'; root.mkdir(mode=0o700)
        previous = os.umask(0o027)
        try: result = tool.prepare(root, True)
        finally: os.umask(previous)
        self.assertEqual(result['status'], 'prepared')
        for path in root.joinpath(*tool.DIRECTORY, tool.CANDIDATE).iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_lock_contention_preserves_candidate(self):
        before = self.bodies()
        with (self.directory / tool.LOCK).open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(tool.CandidateError, 'TLS_PREPARATION_LOCKED'):
                tool.prepare(self.root, True)
        self.assertEqual(before, self.bodies())

    def test_wrong_directory_file_and_lock_permissions_are_not_repaired(self):
        for path in (self.directory, self.candidate, self.candidate / 'server.key', self.directory / tool.LOCK):
            original = stat.S_IMODE(path.stat().st_mode)
            path.chmod(0o755 if path.is_dir() else 0o644)
            with self.assertRaisesRegex(tool.CandidateError, 'TLS_PATH_PERMISSIONS_INVALID'):
                tool.prepare(self.root, True)
            self.assertNotEqual(stat.S_IMODE(path.stat().st_mode), original)
            path.chmod(original)

    def test_symlink_project_parent_candidate_file_and_lock_are_rejected(self):
        alias = self.parent / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): tool.prepare(alias, True)
        for path in (self.candidate / 'server.key', self.directory / tool.LOCK):
            body = path.read_bytes(); path.unlink()
            target = self.parent / ('outside-' + path.name); target.write_bytes(body)
            path.symlink_to(target)
            with self.assertRaises(OSError): tool.prepare(self.root, True)
            self.assertEqual(target.read_bytes(), body)
            path.unlink(); path.write_bytes(body); path.chmod(0o600)
        moved = self.parent / 'moved'; self.candidate.rename(moved)
        self.candidate.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(OSError): tool.prepare(self.root, True)

    def test_hardlink_fifo_and_foreign_owner_are_rejected(self):
        path = self.candidate / 'server.key'; body = path.read_bytes()
        extra = self.parent / 'hardlink'; os.link(path, extra)
        with self.assertRaisesRegex(tool.CandidateError, 'TLS_PATH_TYPE_INVALID'):
            tool.prepare(self.root, True)
        extra.unlink(); path.unlink(); os.mkfifo(path, 0o600)
        with self.assertRaisesRegex(tool.CandidateError, 'TLS_PATH_TYPE_INVALID'):
            tool.prepare(self.root, True)
        path.unlink(); path.write_bytes(body); path.chmod(0o600)
        with patch.object(tool.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaisesRegex(tool.CandidateError, 'TLS_PATH_OWNER_INVALID'):
                tool.prepare(self.root, True)

    def test_missing_or_unknown_file_blocks_regeneration(self):
        path = self.candidate / 'server.pem'; body = path.read_bytes(); path.unlink()
        with patch.object(tool, 'generate') as generate:
            with self.assertRaisesRegex(tool.CandidateError, 'INCOMPLETE'):
                tool.prepare(self.root, True)
            generate.assert_not_called()
        path.write_bytes(body); path.chmod(0o600)
        (self.candidate / 'unreviewed').write_bytes(b'fixture')
        with self.assertRaisesRegex(tool.CandidateError, 'INCOMPLETE'):
            tool.prepare(self.root, True)

    def test_tampered_or_duplicate_json_receipt_and_corrupt_pem_rejected(self):
        path = self.candidate / 'candidate.json'; body = path.read_bytes()
        for invalid in (body + b' ', b'{"format_version":1,"format_version":1}',
                        body.replace(b'candidate-only', b'production-approved')):
            path.write_bytes(invalid)
            with self.assertRaisesRegex(tool.CandidateError, 'RECEIPT_MISMATCH'):
                tool.prepare(self.root, True)
        path.write_bytes(body)
        (self.candidate / 'ca.pem').write_bytes(b'INVALID_PRIVATE_FIXTURE')
        with self.assertRaisesRegex(tool.CandidateError, 'RECEIPT_MISMATCH'):
            tool.prepare(self.root, True)

    def test_mismatched_key_rejected_even_if_receipt_hash_is_updated(self):
        (self.candidate / 'server.key').write_bytes((self.candidate / 'maintenance.key').read_bytes())
        with self.opened() as fd:
            (self.candidate / 'candidate.json').write_bytes(tool.encoded(tool.receipt(fd)))
        with self.assertRaisesRegex(tool.CandidateError, 'CERTIFICATE_KEY_MISMATCH'):
            tool.prepare(self.root, True)

    def test_invalid_pem_is_rejected_by_openssl_even_with_matching_receipt(self):
        (self.candidate / 'server.pem').write_bytes(b'PRIVATE_INVALID_PEM_SENTINEL')
        with self.opened() as fd:
            (self.candidate / 'candidate.json').write_bytes(tool.encoded(tool.receipt(fd)))
        with self.assertRaisesRegex(tool.CandidateError, '^TLS_OPENSSL_CHECK_FAILED$'):
            tool.prepare(self.root, True)

    def test_create_only_file_publication_preserves_user_race_content(self):
        with self.opened() as fd:
            before = (self.candidate / 'server.key').read_bytes()
            with self.assertRaises(FileExistsError): tool.write_new(fd, 'server.key', b'NEW_PRIVATE_SENTINEL')
            self.assertEqual((self.candidate / 'server.key').read_bytes(), before)

    def test_actual_expired_certificate_fails_without_repair(self):
        with self.opened() as fd:
            tool.openssl(fd, ['req', '-new', '-key', 'server.key', '-subj', '/CN=' + tool.SERVER_NAME,
                              '-out', 'expired.csr'])
            tool.write_new(fd, 'expired.cnf', ('[leaf]\nbasicConstraints=critical,CA:FALSE\n'
                           'keyUsage=critical,digitalSignature,keyEncipherment\n'
                           'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:' + tool.SERVER_NAME + '\n'
                           'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n').encode())
            tool.openssl(fd, ['x509', '-req', '-in', 'expired.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
                              '-set_serial', '56789', '-days', '0', '-sha256', '-extfile', 'expired.cnf',
                              '-extensions', 'leaf', '-out', 'server.pem'])
            for name in ('expired.cnf', 'expired.csr'): os.unlink(name, dir_fd=fd)
            (self.candidate / 'candidate.json').write_bytes(tool.encoded(tool.receipt(fd)))
        before = self.bodies()
        with self.assertRaisesRegex(tool.CandidateError, '^TLS_OPENSSL_CHECK_FAILED$'):
            tool.prepare(self.root, True)
        self.assertEqual(before, self.bodies())

    def test_server_certificate_cannot_authenticate_as_client(self):
        with self.opened() as fd:
            server, client = tool.contexts(fd)
            path = '/proc/self/fd/' + str(fd) + '/'
            client.load_cert_chain(path + 'server.pem', path + 'server.key')
            result = tool.exchange(server, client)
            self.assertTrue(result.get('client_failed'))
            self.assertTrue(result.get('server_failed'))

    def test_tls12_works_and_tls11_downgrade_is_denied(self):
        with self.opened() as fd:
            server, client = tool.contexts(fd)
            client.maximum_version = ssl.TLSVersion.TLSv1_2
            self.assertEqual(tool.exchange(server, client)['tls_version'], 'TLSv1.2')
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                client.minimum_version = ssl.TLSVersion.TLSv1_1
                client.maximum_version = ssl.TLSVersion.TLSv1_1
            client.set_ciphers('ALL:@SECLEVEL=0')
            self.assertTrue(tool.exchange(server, client).get('client_failed'))

    def test_partial_generation_remains_blocked_and_never_automatic_rotates(self):
        root = self.parent / 'interrupted'; root.mkdir(mode=0o700)
        def interrupted(fd):
            tool.write_new(fd, 'server.key', b'PRIVATE_PARTIAL_SENTINEL')
            raise tool.CandidateError('TLS_OPENSSL_CHECK_FAILED')
        with patch.object(tool, 'generate', side_effect=interrupted):
            with self.assertRaises(tool.CandidateError): tool.prepare(root, True)
        with patch.object(tool, 'generate') as generate:
            with self.assertRaisesRegex(tool.CandidateError, 'INCOMPLETE'): tool.prepare(root, True)
            generate.assert_not_called()
        self.assertEqual(root.joinpath(*tool.DIRECTORY, tool.CANDIDATE, 'server.key').read_bytes(),
                         b'PRIVATE_PARTIAL_SENTINEL')

    def test_new_directory_race_does_not_overwrite_existing_user_candidate(self):
        root = self.parent / 'race'; root.mkdir(mode=0o700)
        original = tool.os.mkdir
        def concurrent(name, *args, **kwargs):
            if name == tool.CANDIDATE:
                original(name, *args, **kwargs)
                original('user-sentinel', 0o700, dir_fd=kwargs['dir_fd'])
                raise FileExistsError('synthetic race')
            return original(name, *args, **kwargs)
        with patch.object(tool.os, 'mkdir', side_effect=concurrent):
            with self.assertRaises(FileExistsError): tool.prepare(root, True)
        self.assertTrue(root.joinpath(*tool.DIRECTORY, 'user-sentinel').is_dir())

    def test_replaced_candidate_directory_during_probe_is_rejected(self):
        real = tool.probe
        def replace(fd, snapshot):
            result = real(fd, snapshot)
            self.candidate.rename(self.parent / 'old')
            shutil.copytree(self.parent / 'old', self.candidate)
            return result
        with patch.object(tool, 'probe', side_effect=replace):
            with self.assertRaisesRegex(tool.CandidateError, 'PATH_CHANGED'): tool.prepare(self.root, True)

    def test_public_result_has_no_private_keys_or_private_hashes(self):
        output = json.dumps(tool.prepare(self.root, True))
        for name in ('ca.key', 'server.key', 'maintenance.key'):
            body = (self.candidate / name).read_bytes()
            self.assertNotIn(body.decode(), output)
            self.assertNotIn(tool.sha(body), output)
        self.assertNotIn('PRIVATE KEY', output)

    def test_openssl_failure_and_timeout_do_not_expose_stderr(self):
        with self.opened() as fd:
            failure = subprocess.CompletedProcess([], 1, b'', b'PRIVATE_ERROR_SENTINEL')
            with patch.object(tool.subprocess, 'run', return_value=failure) as run:
                with self.assertRaisesRegex(tool.CandidateError, '^TLS_OPENSSL_CHECK_FAILED$'):
                    tool.openssl(fd, ['version'])
                self.assertEqual(run.call_args.kwargs['env']['OPENSSL_CONF'], '/dev/null')
                self.assertEqual(run.call_args.kwargs['umask'], 0o077)
            with patch.object(tool.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 30)):
                with self.assertRaisesRegex(tool.CandidateError, '^TLS_OPENSSL_UNAVAILABLE$'):
                    tool.openssl(fd, ['version'])

    def test_failed_cli_suppresses_arbitrary_exception_details(self):
        output = io.StringIO()
        with patch.object(tool.sys, 'argv', ['prepare', '--project-root', str(self.root)]), \
             patch.object(tool, 'checked_revision', side_effect=ValueError('PRIVATE_EXCEPTION_SENTINEL')), \
             contextlib.redirect_stderr(output):
            self.assertEqual(tool.main(), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result['code'], 'TLS_CANDIDATE_UNAVAILABLE')
        self.assertNotIn('PRIVATE_EXCEPTION_SENTINEL', output.getvalue())
        for flag in tool.NO_CHANGES: self.assertIs(result[flag], False)


if __name__ == '__main__':
    unittest.main()
