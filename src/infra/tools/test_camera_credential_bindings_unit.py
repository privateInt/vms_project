import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_bindings as tool
from test_camera_credential_storage import EXPECTED_TESTS


def phase(name, value):
    return [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'},
            {'Package': tool.PACKAGE, 'Test': name, 'Action': 'output',
             'Output': 'CREDENTIAL_BINDING_PHASE_OK:' + value + '\n'},
            {'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'},
            {'Package': tool.PACKAGE, 'Action': 'pass'}]


def regression():
    return ([{'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'}
             for name in (*EXPECTED_TESTS, *tool.TESTS[:-1])]
            + [{'Package': tool.CRYPTO_PACKAGE, 'Test': name, 'Action': 'pass'} for name in tool.CRYPTO_TESTS]
            + [{'Package': tool.CRYPTO_PACKAGE, 'Action': 'pass'},
               {'Package': tool.PACKAGE, 'Action': 'pass'}])


def complete():
    return phase(tool.FIXTURE_TEST, 'prepare') + regression() + phase(tool.TESTS[-1], 'runtime')


class CredentialBindingRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        files = {}
        for name in ('src/infra/tools/test_camera_credential_storage.py',
                     'src/infra/tools/test_camera_credential_bindings.py',
                     'src/infra/postgresql/compose.credential-bindings-test.yaml',
                     'src/platform/camera/internal/storage/foundation_test.go'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic reviewed fixture\n')
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest = {'storage_revision': 'step11b2-credential-storage-20261002',
                         'storage_schema_version': 8, 'credential_storage_implemented': True,
                         'credential_api_implemented': False, 'files': files,
                         'credential_binding_revision': tool.REVISION,
                         'credential_key_receipt_implemented': True,
                         'credential_endpoint_profile_implemented': True,
                         'credential_admission_database_native_verified': True,
                         'credential_runtime_admission_guard_implemented': False}
        self.write_manifest()
        (self.root / '.env').write_bytes(b'SYNTHETIC_ENV_SENTINEL')
        p = self.root / 'var/camera/credential-keys/key-bundle.json'
        p.parent.mkdir(parents=True)
        p.write_bytes(b'SYNTHETIC_KEY_SENTINEL')
        self.log = self.root / 'fixture.log'

    def write_manifest(self):
        (self.root / 'project-manifest.json').write_text(json.dumps(self.manifest))

    def summarize(self, rows):
        self.log.write_text('build progress\n' + '\n'.join(json.dumps(x) for x in rows))
        return tool.summarize_log(self.log)

    def test_complete_native_proof(self):
        result = self.summarize(complete())
        self.assertEqual(result['native_binding_phases_passed'], 2)
        self.assertEqual(result['required_binding_tests_passed'], 5)
        self.assertEqual(result['required_key_receipt_tests_passed'], 2)

    def test_marker_missing_or_wrong_test_rejected(self):
        for mode in ('missing', 'wrong_test'):
            rows = complete()
            if mode == 'missing':
                rows = [x for x in rows if x.get('Action') != 'output']
            else:
                rows[1]['Test'] = 'TestSelectorWithoutNativeWork'
            with self.assertRaises(tool.VerificationError):
                self.summarize(rows)

    def test_skipped_or_incomplete_phase_rejected(self):
        rows = complete()
        rows[-2]['Action'] = 'skip'
        with self.assertRaises(tool.VerificationError):
            self.summarize(rows)
        with self.assertRaises(tool.VerificationError):
            self.summarize(complete()[:-2])

    def test_wrong_order_duplicate_and_failure_not_hidden(self):
        variants = [phase(tool.TESTS[-1], 'runtime') + regression() + phase(tool.FIXTURE_TEST, 'prepare'),
                    phase(tool.FIXTURE_TEST, 'prepare') + complete(),
                    [{'Package': tool.PACKAGE, 'Action': 'fail'}] + complete()]
        for rows in variants:
            with self.assertRaises(tool.VerificationError):
                self.summarize(rows)

    def test_missing_crypto_or_package_proof_rejected(self):
        for absent in ((tool.CRYPTO_PACKAGE, tool.CRYPTO_TESTS[0]), (tool.CRYPTO_PACKAGE, None)):
            with self.assertRaises(tool.VerificationError):
                self.summarize([x for x in complete() if (x.get('Package'), x.get('Test')) != absent])

    def test_standard_regression_skips_do_not_fake_native_work(self):
        skipped = []
        for name in (tool.FIXTURE_TEST, tool.TESTS[-1]):
            skipped += [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'},
                        {'Package': tool.PACKAGE, 'Test': name, 'Action': 'skip'}]
        rows = phase(tool.FIXTURE_TEST, 'prepare') + regression() + skipped + phase(tool.TESTS[-1], 'runtime')
        self.assertEqual(self.summarize(rows)['native_binding_phases_passed'], 2)

    def test_manifest_guard_and_source_integrity(self):
        self.manifest['credential_admission_database_native_verified'] = False
        self.write_manifest()
        with self.assertRaises(tool.VerificationError):
            tool.checked_revision(self.root)
        self.manifest['credential_admission_database_native_verified'] = True
        self.write_manifest()
        (self.root / 'src/platform/camera/internal/storage/foundation_test.go').write_bytes(b'user edit')
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                self.assertRaises(tool.VerificationError):
            tool.verify(self.root, run=lambda *a, **k: self.fail('command before integrity check'))

    def mock_run(self, fail_stage=None, cleanup=0, drift=False, timeout=False):
        stages = ('build_tools', 'prepare_fixture', 'own_tls_key', 'start_tls_database', 'regression', 'runtime_tls_bindings')
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertTrue(args[3].startswith('vms-credential-bindings-test-'))
            self.assertEqual(args[3], calls[0][3])
            for key in ('COMPOSE_PROJECT_NAME', 'CAMERA_TEST_DATABASE_URL', 'PGSERVICE'):
                self.assertNotIn(key, kwargs['env'])
            if 'down' in args:
                return subprocess.CompletedProcess(args, cleanup)
            stage = stages[len(calls) - 1]
            if timeout:
                raise subprocess.TimeoutExpired(args, 1)
            rows = (phase(tool.FIXTURE_TEST, 'prepare') if stage == 'prepare_fixture'
                    else regression() if stage == 'regression'
                    else phase(tool.TESTS[-1], 'runtime') if stage == 'runtime_tls_bindings' else [])
            kwargs['stdout'].write(('\n'.join(json.dumps(x) for x in rows) + '\n').encode())
            if drift and stage == 'runtime_tls_bindings':
                (self.root / 'src/platform/camera/internal/storage/foundation_test.go').write_bytes(b'concurrent edit')
            return subprocess.CompletedProcess(args, 1 if stage == fail_stage else 0)
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                patch.dict(tool.os.environ, {'COMPOSE_PROJECT_NAME': 'vms-project',
                                            'CAMERA_TEST_DATABASE_URL': 'synthetic-production',
                                            'PGSERVICE': 'synthetic-production'}):
            result = tool.verify(self.root, run=run)
        self.assertEqual((self.root / '.env').read_bytes(), b'SYNTHETIC_ENV_SENTINEL')
        self.assertEqual((self.root / 'var/camera/credential-keys/key-bundle.json').read_bytes(), b'SYNTHETIC_KEY_SENTINEL')
        self.assertFalse(result['production_keys_loaded'])
        self.assertFalse(result['runtime_admission_guard_implemented'])
        for field in ('log', 'report'):
            self.assertEqual(stat.S_IMODE(Path(result[field]).stat().st_mode), 0o600)
        self.assertEqual(calls[-1][-5:], ['down', '--volumes', '--remove-orphans', '--timeout', '5'])
        return result

    def test_success_keeps_protected_files(self):
        self.assertEqual(self.mock_run()['status'], 'passed')

    def test_every_failed_phase_stops_and_cleans(self):
        for stage in ('build_tools', 'prepare_fixture', 'own_tls_key', 'start_tls_database', 'regression', 'runtime_tls_bindings'):
            result = self.mock_run(fail_stage=stage)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failed_stage'], stage)
            self.assertTrue(result['isolated_resources_removed'])

    def test_timeout_cleans(self):
        self.assertTrue(self.mock_run(timeout=True)['isolated_resources_removed'])

    def test_source_drift_cancels_pass(self):
        self.assertEqual(self.mock_run(drift=True)['code'], 'PROJECT_FILE_CHANGED')

    def test_cleanup_failure_cancels_pass(self):
        self.assertEqual(self.mock_run(cleanup=1)['code'], 'ISOLATED_CLEANUP_INCOMPLETE')


if __name__ == '__main__':
    unittest.main()
