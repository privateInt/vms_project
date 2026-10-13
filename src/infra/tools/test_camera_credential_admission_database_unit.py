import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_admission_database as tool
from test_camera_credential_storage import EXPECTED_TESTS


def records():
    names = (*EXPECTED_TESTS, *tool.TESTS, tool.RESTORE_TEST)
    return ([{'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'} for name in names]
            + [{'Package': tool.PACKAGE, 'Action': 'pass'}])


class AdmissionDatabaseRunnerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'project'
        self.root.mkdir()
        files = {}
        for name in ('src/infra/tools/test_camera_credential_storage.py',
                     'src/infra/tools/test_camera_credential_admission_database.py',
                     'src/infra/postgresql/compose.credential-admission-database-test.yaml',
                     'src/platform/camera/internal/storage/foundation_test.go'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic reviewed fixture\n')
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest = {'storage_revision': 'step11b2-credential-storage-20261002',
                         'storage_schema_version': 8, 'credential_storage_implemented': True,
                         'credential_api_implemented': False, 'files': files,
                         'credential_admission_database_revision': tool.REVISION,
                         'credential_admission_database_schema_version': 9,
                         'credential_admission_database_implemented': True,
                         'credential_runtime_admission_guard_implemented': False}
        self.write_manifest()
        (self.root / '.env').write_bytes(b'SYNTHETIC_PROTECTED_ENV')
        secret = self.root / 'var/camera/credential-keys/key-bundle.json'
        secret.parent.mkdir(parents=True)
        secret.write_bytes(b'SYNTHETIC_PROTECTED_KEY')
        self.log = self.root / 'test.log'

    def write_manifest(self):
        (self.root / 'project-manifest.json').write_text(json.dumps(self.manifest))

    def write_log(self, rows):
        self.log.write_text('progress\n' + '\n'.join(json.dumps(x) for x in rows))

    def test_complete_transcript(self):
        self.write_log(records())
        self.assertEqual(tool.summarize_log(self.log)['required_admission_database_tests_passed'], 5)

    def test_missing_restore_rejected(self):
        self.write_log([r for r in records() if r.get('Test') != tool.RESTORE_TEST])
        with self.assertRaises(tool.VerificationError):
            tool.summarize_log(self.log)

    def test_skipped_or_wrong_package_rejected(self):
        for field, value in [('Action', 'skip'), ('Package', 'other')]:
            rows = records()
            rows[-2][field] = value
            self.write_log(rows)
            with self.assertRaises(tool.VerificationError):
                tool.summarize_log(self.log)

    def test_failure_cannot_be_hidden_by_retry(self):
        self.write_log([{'Package': tool.PACKAGE, 'Test': tool.RESTORE_TEST, 'Action': 'fail'}] + records())
        with self.assertRaises(tool.VerificationError):
            tool.summarize_log(self.log)

    def test_build_skip_then_real_restore_pass(self):
        self.write_log([{'Package': tool.PACKAGE, 'Test': tool.RESTORE_TEST, 'Action': 'skip'}] + records())
        self.assertTrue(tool.summarize_log(self.log)['native_database_dump_restore_verified'])

    def test_late_skip_rejected(self):
        self.write_log(records() + [{'Package': tool.PACKAGE, 'Test': tool.RESTORE_TEST, 'Action': 'skip'}])
        with self.assertRaises(tool.VerificationError):
            tool.summarize_log(self.log)

    def test_integrity_checked_before_any_command(self):
        p = self.root / 'src/platform/camera/internal/storage/foundation_test.go'
        p.write_bytes(b'user edit')
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                self.assertRaises(tool.VerificationError):
            tool.verify(self.root, run=lambda *a, **k: self.fail('executed before source check'))

    def test_future_guard_implementation_not_silently_accepted(self):
        self.manifest['credential_runtime_admission_guard_implemented'] = True
        self.write_manifest()
        with self.assertRaises(tool.VerificationError):
            tool.checked_revision(self.root)

    def mock_run(self, failed=None, cleanup=0, drift=False, timeout=False):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertIn('--env-file', args)
            self.assertTrue(args[3].startswith('vms-admission-db-test-'))
            self.assertEqual(args[3], calls[0][3])
            self.assertNotIn('COMPOSE_PROJECT_NAME', kwargs['env'])
            self.assertNotIn('CAMERA_TEST_DATABASE_URL', kwargs['env'])
            self.assertNotIn('PGSERVICE', kwargs['env'])
            if 'down' in args:
                return subprocess.CompletedProcess(args, cleanup)
            if 'run' in args:
                self.assertEqual(args[-4:], ['admission-build', 'sh', '-ec', tool.BUILD])
            if timeout:
                raise subprocess.TimeoutExpired(args, 1)
            if 'exec' in args:
                self.assertIn('CAMERA_TEST_ADMISSION_DUMP_RESTORE=1', args)
                kwargs['stdout'].write(('\n'.join(json.dumps(x) for x in records()) + '\n').encode())
                if drift:
                    (self.root / 'src/platform/camera/internal/storage/foundation_test.go').write_bytes(b'concurrent edit')
            return subprocess.CompletedProcess(args, 1 if failed == ('build' if 'run' in args else 'restore') else 0)
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                patch.dict(tool.os.environ, {'COMPOSE_PROJECT_NAME': 'vms-project',
                                            'CAMERA_TEST_DATABASE_URL': 'synthetic-prod',
                                            'PGSERVICE': 'synthetic-prod'}):
            result = tool.verify(self.root, run=run)
        self.assertEqual((self.root / '.env').read_bytes(), b'SYNTHETIC_PROTECTED_ENV')
        self.assertEqual((self.root / 'var/camera/credential-keys/key-bundle.json').read_bytes(), b'SYNTHETIC_PROTECTED_KEY')
        self.assertFalse(result['production_database_modified'])
        self.assertEqual(stat.S_IMODE(Path(result['report']).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(result['log']).stat().st_mode), 0o600)
        self.assertEqual(calls[-1][-5:], ['down', '--volumes', '--remove-orphans', '--timeout', '5'])
        return result

    def test_success_and_protected_files(self):
        self.assertEqual(self.mock_run()['status'], 'passed')

    def test_command_failure_stage_and_cleanup(self):
        for failed, stage in [('build', 'build_and_regression'), ('restore', 'native_dump_restore')]:
            result = self.mock_run(failed=failed)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failed_stage'], stage)
            self.assertTrue(result['isolated_resources_removed'])

    def test_timeout_and_cleanup(self):
        result = self.mock_run(timeout=True)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['isolated_resources_removed'])

    def test_source_drift_and_cleanup(self):
        self.assertEqual(self.mock_run(drift=True)['code'], 'PROJECT_FILE_CHANGED')

    def test_cleanup_failure(self):
        result = self.mock_run(cleanup=1)
        self.assertEqual(result['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertFalse(result['isolated_resources_removed'])


if __name__ == '__main__':
    unittest.main()
