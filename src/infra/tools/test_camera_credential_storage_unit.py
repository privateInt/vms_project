import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_storage as tool


def native_records():
    rows = [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'}
            for name in tool.EXPECTED_TESTS]
    rows.append({'Package': tool.PACKAGE, 'Action': 'pass'})
    return rows


class CredentialNativeRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir(mode=0o700)
        files = {}
        for name in ('src/infra/tools/test_camera_credential_storage.py',
                     'src/infra/postgresql/compose.test.yaml',
                     'src/platform/camera/internal/storage/foundation_test.go'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic reviewed fixture\n')
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root / 'project-manifest.json').write_text(json.dumps({
            'storage_revision': 'step11b2-credential-storage-20261002',
            'storage_schema_version': 8, 'credential_storage_implemented': True,
            'credential_api_implemented': False, 'files': files}))
        (self.root / '.env').write_bytes(b'SYNTHETIC_ENV_ONLY\n')
        private = self.root / 'var/camera/credential-keys'
        private.mkdir(parents=True, mode=0o700)
        (private / 'key-bundle.json').write_bytes(b'SYNTHETIC_KEY_SENTINEL_ONLY\n')
        self.log = self.root / 'synthetic.log'

    def write_log(self, rows):
        self.log.write_text('Docker progress\n' + '\n'.join(json.dumps(row) for row in rows) + '\n')

    def test_requires_complete_native_tests(self):
        self.write_log(native_records())
        result = tool.summarize_log(self.log)
        self.assertEqual(result['required_credential_tests_passed'], len(tool.EXPECTED_TESTS))
        self.assertTrue(result['native_roles_and_concurrency_verified'])

    def test_missing_native_case_rejected(self):
        self.write_log(native_records()[1:])
        with self.assertRaisesRegex(tool.VerificationError, 'NATIVE_CREDENTIAL_TESTS_REQUIRED'):
            tool.summarize_log(self.log)

    def test_skipped_native_case_rejected(self):
        rows = native_records()
        rows[-2]['Action'] = 'skip'
        self.write_log(rows)
        with self.assertRaises(tool.VerificationError):
            tool.summarize_log(self.log)

    def test_wrong_package_rejected(self):
        rows = native_records()
        rows[0]['Package'] = 'other/package'
        self.write_log(rows)
        with self.assertRaises(tool.VerificationError):
            tool.summarize_log(self.log)

    def test_any_failure_is_not_hidden_by_later_pass(self):
        rows = [{'Package': tool.PACKAGE, 'Test': tool.EXPECTED_TESTS[0], 'Action': 'fail'}] + native_records()
        self.write_log(rows)
        with self.assertRaisesRegex(tool.VerificationError, 'GO_TEST_FAILED'):
            tool.summarize_log(self.log)

    def test_package_completion_required(self):
        self.write_log(native_records()[:-1])
        with self.assertRaises(tool.VerificationError):
            tool.summarize_log(self.log)

    def test_source_integrity_checked_before_run(self):
        (self.root / 'src/platform/camera/internal/storage/foundation_test.go').write_bytes(b'user edit\n')
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                self.assertRaisesRegex(tool.VerificationError, 'PROJECT_FILE_CHANGED'):
            tool.verify(self.root, run=lambda *args, **kwargs: self.fail('run before review'))

    def run_mock(self, *, code=0, cleanup=0, drift=False, timeout=False):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            self.assertNotIn('COMPOSE_PROJECT_NAME', kwargs['env'])
            self.assertIn('--env-file', command)
            self.assertIn('/dev/null', command)
            self.assertTrue(command[3].startswith('vms-credential-storage-test-'))
            self.assertNotEqual(command[3], 'vms-project')
            if 'run' in command:
                self.assertEqual(command[-4:], ['camera-storage-test', 'sh', '-ec', tool.GO_COMMAND])
                if timeout:
                    raise subprocess.TimeoutExpired(command, 900)
                kwargs['stdout'].write(('\n'.join(json.dumps(row) for row in native_records()) + '\n').encode())
                if drift:
                    (self.root / 'src/platform/camera/internal/storage/foundation_test.go').write_bytes(b'concurrent user edit\n')
                return subprocess.CompletedProcess(command, code)
            self.assertEqual(command[-5:], ['down', '--volumes', '--remove-orphans', '--timeout', '5'])
            return subprocess.CompletedProcess(command, cleanup)
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                patch.dict(tool.os.environ, {'COMPOSE_PROJECT_NAME': 'vms-project'}):
            result = tool.verify(self.root, run=run)
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.root / '.env').read_bytes(), b'SYNTHETIC_ENV_ONLY\n')
        self.assertEqual((self.root / 'var/camera/credential-keys/key-bundle.json').read_bytes(), b'SYNTHETIC_KEY_SENTINEL_ONLY\n')
        self.assertFalse(result['production_keys_loaded'])
        self.assertFalse(result['production_database_modified'])
        self.assertEqual(stat.S_IMODE(Path(result['report']).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(result['log']).stat().st_mode), 0o600)
        return result

    def test_mock_success_preserves_protected_files(self):
        self.assertEqual(self.run_mock()['status'], 'passed')

    def test_test_failure_still_cleans_owned_project(self):
        result = self.run_mock(code=1)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['isolated_resources_removed'])

    def test_timeout_still_cleans_owned_project(self):
        result = self.run_mock(timeout=True)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['isolated_resources_removed'])

    def test_source_drift_rejects_receipt(self):
        result = self.run_mock(drift=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['code'], 'PROJECT_FILE_CHANGED')

    def test_cleanup_failure_identifies_owned_project(self):
        result = self.run_mock(cleanup=1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertFalse(result['isolated_resources_removed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
