import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_operations as tool
import test_camera_credential_bindings as binding
from test_camera_credential_storage import EXPECTED_TESTS


def phase(name, value):
    return [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'},
            {'Package': tool.PACKAGE, 'Test': name, 'Action': 'output',
             'Output': 'CREDENTIAL_BINDING_PHASE_OK:' + value + '\n'},
            {'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'},
            {'Package': tool.PACKAGE, 'Action': 'pass'}]


def regression():
    return ([{'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'}
             for name in (*EXPECTED_TESTS, *binding.TESTS[:-1], *tool.TESTS[:-1])]
            + [{'Package': binding.CRYPTO_PACKAGE, 'Test': name, 'Action': 'pass'} for name in binding.CRYPTO_TESTS]
            + [{'Package': binding.CRYPTO_PACKAGE, 'Action': 'pass'},
               {'Package': tool.PACKAGE, 'Action': 'pass'}])


def operations():
    return ([{'Package': tool.PACKAGE, 'Test': tool.TESTS[-1], 'Action': 'run'}]
            + [{'Package': tool.PACKAGE, 'Test': tool.TESTS[-1], 'Action': 'output',
                'Output': 'CREDENTIAL_OPERATION_PHASE_OK:' + value + '\n'} for value in tool.PHASES]
            + [{'Package': tool.PACKAGE, 'Test': tool.TESTS[-1], 'Action': 'pass'},
               {'Package': tool.PACKAGE, 'Action': 'pass'}])


def complete():
    return phase(tool.FIXTURE_TEST, 'prepare') + regression() + phase(binding.TESTS[-1], 'runtime') + operations()


class CredentialOperationRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        files = {}
        for name in ('src/infra/tools/test_camera_credential_storage.py',
                     'src/infra/tools/test_camera_credential_operations.py',
                     'src/infra/postgresql/compose.credential-operation-test.yaml',
                     'src/platform/camera/internal/storage/foundation_test.go'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic reviewed fixture\n')
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest = {'storage_revision': 'step11b2-credential-storage-20261002',
                         'storage_schema_version': 8, 'credential_storage_implemented': True,
                         'credential_api_implemented': False, 'files': files,
                         'credential_operation_revision': tool.REVISION,
                         'credential_operation_diagnostic_revision': tool.DIAGNOSTIC_REVISION,
                         'credential_binding_native_verified': True,
                         'credential_operation_native_verified': False,
                         'credential_key_receipt_implemented': True,
                         'credential_endpoint_profile_implemented': True,
                         'credential_admission_database_native_verified': True,
                         'credential_runtime_admission_guard_implemented': True}
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
        self.assertEqual(result['native_operation_phases_passed'], 9)
        self.assertEqual(result['required_operation_tests_passed'], 5)
        self.assertEqual(result['required_key_receipt_tests_passed'], 2)

    def test_operation_order_missing_duplicate_or_wrong_parent_rejected(self):
        prefix = phase(tool.FIXTURE_TEST, 'prepare') + regression() + phase(binding.TESTS[-1], 'runtime')
        for mode in ('missing', 'order', 'duplicate', 'wrong_parent'):
            rows = operations()
            if mode == 'missing':
                rows.pop(1)
            elif mode == 'order':
                rows[1], rows[2] = rows[2], rows[1]
            elif mode == 'duplicate':
                rows.insert(1, rows[1].copy())
            else:
                rows[1]['Test'] = 'TestSelectorWithoutNativeWork'
            with self.assertRaises(tool.VerificationError):
                self.summarize(prefix + rows)

    def test_operation_skip_or_failure_cannot_be_hidden(self):
        for action in ('skip', 'fail'):
            rows = complete()
            rows[-2]['Action'] = action
            with self.assertRaises(tool.VerificationError):
                self.summarize(rows)

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
        variants = [phase(binding.TESTS[-1], 'runtime') + regression() + phase(tool.FIXTURE_TEST, 'prepare'),
                    phase(tool.FIXTURE_TEST, 'prepare') + complete(),
                    [{'Package': tool.PACKAGE, 'Action': 'fail'}] + complete()]
        for rows in variants:
            with self.assertRaises(tool.VerificationError):
                self.summarize(rows)

    def test_missing_crypto_or_package_proof_rejected(self):
        for absent in ((binding.CRYPTO_PACKAGE, binding.CRYPTO_TESTS[0]), (binding.CRYPTO_PACKAGE, None)):
            with self.assertRaises(tool.VerificationError):
                self.summarize([x for x in complete() if (x.get('Package'), x.get('Test')) != absent])

    def test_standard_regression_skips_do_not_fake_native_work(self):
        skipped = []
        for name in (tool.FIXTURE_TEST, binding.TESTS[-1]):
            skipped += [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'},
                        {'Package': tool.PACKAGE, 'Test': name, 'Action': 'skip'}]
        rows = phase(tool.FIXTURE_TEST, 'prepare') + regression() + skipped + phase(binding.TESTS[-1], 'runtime')
        self.assertEqual(self.summarize(rows + operations())['native_operation_phases_passed'], 9)

    def test_manifest_guard_and_source_integrity(self):
        self.manifest['credential_binding_native_verified'] = False
        self.write_manifest()
        with self.assertRaises(tool.VerificationError):
            tool.checked_revision(self.root)
        self.manifest['credential_binding_native_verified'] = True
        self.write_manifest()
        (self.root / 'src/platform/camera/internal/storage/foundation_test.go').write_bytes(b'user edit')
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                self.assertRaises(tool.VerificationError):
            tool.verify(self.root, run=lambda *a, **k: self.fail('command before integrity check'))

    def test_accepted_manifest_can_repeat_the_same_operation_check(self):
        self.manifest['credential_operation_native_verified'] = True
        self.write_manifest()
        self.assertEqual(tool.checked_revision(self.root), hashlib.sha256(
            (self.root / 'project-manifest.json').read_bytes()).hexdigest())

    def mock_run(self, fail_stage=None, cleanup=0, drift=False, timeout=False, native_component=None):
        stages = ('build_tools', 'prepare_fixture', 'own_tls_key', 'start_tls_database', 'regression', 'runtime_tls_bindings', 'runtime_operation_leases')
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertTrue(args[3].startswith('vms-credential-operations-test-'))
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
                    else phase(binding.TESTS[-1], 'runtime') if stage == 'runtime_tls_bindings'
                    else operations() if stage == 'runtime_operation_leases' else [])
            kwargs['stdout'].write(('\n'.join(json.dumps(x) for x in rows) + '\n').encode())
            if native_component is not None and stage == 'runtime_operation_leases':
                kwargs['stdout'].write((json.dumps({'Package': tool.PACKAGE,
                    'Test': tool.TESTS[-1], 'Action': 'output',
                    'Output': tool.FAILURE_PREFIX + native_component + '\n'}) + '\n').encode())
            if drift and stage == 'runtime_operation_leases':
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
        self.assertTrue(result['runtime_admission_guard_implemented'])
        for field in ('log', 'report'):
            self.assertEqual(stat.S_IMODE(Path(result[field]).stat().st_mode), 0o600)
        self.assertEqual(calls[-1][-5:], ['down', '--volumes', '--remove-orphans', '--timeout', '5'])
        return result

    def test_success_keeps_protected_files(self):
        self.assertEqual(self.mock_run()['status'], 'passed')

    def test_every_failed_phase_stops_and_cleans(self):
        for stage in ('build_tools', 'prepare_fixture', 'own_tls_key', 'start_tls_database', 'regression', 'runtime_tls_bindings', 'runtime_operation_leases'):
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

    def test_safe_native_component_propagates_on_command_failure(self):
        result = self.mock_run(fail_stage='runtime_operation_leases', native_component='owner_signal')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_native_component'], 'owner_signal')
        self.assertTrue(result['isolated_resources_removed'])

    def test_unreviewed_component_cannot_expose_private_value(self):
        private = 'postgres://synthetic-private-user:synthetic-private-password@private.invalid/db'
        result = self.mock_run(fail_stage='runtime_operation_leases', native_component=private)
        self.assertNotIn('failed_native_component', result)
        self.assertNotIn(private, json.dumps(result))

    def test_failure_receipt_cannot_be_hidden_by_pass(self):
        result = self.mock_run(native_component='child_ready')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['code'], 'NATIVE_OPERATION_FAILURE_REPORTED')

    def test_failure_from_wrong_package_or_test_is_not_attributed(self):
        for package, name in (('unrelated', tool.TESTS[-1]), (tool.PACKAGE, 'TestUnrelated')):
            self.log.write_text(json.dumps({'Package': package, 'Test': name, 'Action': 'output',
                'Output': tool.FAILURE_PREFIX + 'owner_signal\n'}))
            self.assertIsNone(tool.native_failure_component(self.log))


if __name__ == '__main__':
    unittest.main()
