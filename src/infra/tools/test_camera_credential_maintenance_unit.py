import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_maintenance as tool
from test_camera_credential_storage import EXPECTED_TESTS


def transcript():
    rows = [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'}
            for name in (*EXPECTED_TESTS, tool.UNIT_TEST)]
    for name, phases in tool.PHASES.items():
        rows.append({'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'})
        rows += [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'output',
                  'Output': 'fixture.go:1: ' + tool.PREFIX + phase + '\n'} for phase in phases]
        rows.append({'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'})
    rows.append({'Package': tool.PACKAGE, 'Action': 'pass'})
    return rows


class CredentialMaintenanceRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        files = {}
        for name in ('src/infra/tools/test_camera_credential_storage.py',
                     'src/infra/tools/test_camera_credential_maintenance.py',
                     'src/infra/postgresql/compose.credential-maintenance-test.yaml',
                     'src/platform/camera/internal/storage/maintenance_fixture.go'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic source\n')
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest = {'storage_revision': 'step11b2-credential-storage-20261002',
                         'storage_schema_version': 8, 'credential_storage_implemented': True,
                         'credential_api_implemented': False, 'files': files,
                         'credential_maintenance_revision': tool.REVISION,
                         'credential_operation_native_verified': True,
                         'validated_credential_operation_project_sha256':
                             '0765dfb6560779e289c129f96d1a656b6da3cc79c7e31ed64ffc74678aff28f0',
                         'credential_maintenance_database_fence_implemented': True,
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

    def test_complete_proof(self):
        result = self.summarize(transcript())
        self.assertEqual(result['native_maintenance_phases_passed'], 7)
        self.assertEqual(result['required_maintenance_tests_passed'], 4)
        self.assertEqual(result['required_credential_tests_passed'], 13)

    def test_missing_order_duplicate_phase_rejected(self):
        for mode in ('missing', 'order', 'duplicate'):
            rows = transcript()
            i = next(i for i, r in enumerate(rows) if r.get('Action') == 'output')
            if mode == 'missing': rows.pop(i)
            elif mode == 'order': rows[i], rows[i+1] = rows[i+1], rows[i]
            else: rows.insert(i, rows[i].copy())
            with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_wrong_test_and_package_markers_rejected(self):
        for field, value in (('Test', 'TestSyntheticSelector'), ('Package', 'private.invalid/package')):
            rows = transcript()
            next(r for r in rows if r.get('Action') == 'output')[field] = value
            with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_skip_failure_and_truncation_rejected(self):
        for action in ('skip', 'fail'):
            rows = transcript()
            next(r for r in rows if r.get('Test') in tool.PHASES and r.get('Action') == 'pass')['Action'] = action
            with self.assertRaises(tool.VerificationError): self.summarize(rows)
        with self.assertRaises(tool.VerificationError): self.summarize(transcript()[:-2])

    def test_duplicate_native_run_cannot_override_previous(self):
        rows = transcript()
        name = next(iter(tool.PHASES))
        rows += [r.copy() for r in rows if r.get('Test') == name]
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_output_before_run_rejected(self):
        rows = transcript()
        i = next(i for i, r in enumerate(rows) if r.get('Action') == 'run')
        rows[i], rows[i+1] = rows[i+1], rows[i]
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_missing_legacy_test_or_package_cannot_pass(self):
        for absent in (EXPECTED_TESTS[0], None, tool.UNIT_TEST):
            with self.assertRaises(tool.VerificationError):
                self.summarize([r for r in transcript() if r.get('Test') != absent])

    def test_earlier_failure_cannot_be_hidden_by_later_pass(self):
        rows = [{'Package': tool.PACKAGE, 'Test': 'TestEarlier', 'Action': 'fail'}] + transcript()
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_manifest_requires_accepted_operation_revision(self):
        for name, value in (('credential_operation_native_verified', False),
                            ('validated_credential_operation_project_sha256', 'wrong'),
                            ('credential_maintenance_revision', 'wrong')):
            original = self.manifest[name]
            self.manifest[name] = value
            self.write_manifest()
            with self.assertRaises(tool.VerificationError): tool.checked_revision(self.root)
            self.manifest[name] = original
        self.write_manifest()

    def test_source_edit_prevents_any_docker_call(self):
        (self.root / 'src/platform/camera/internal/storage/maintenance_fixture.go').write_bytes(b'user edit')
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), self.assertRaises(tool.VerificationError):
            tool.verify(self.root, run=lambda *a, **k: self.fail('command before integrity check'))

    def mock_run(self, fail_stage=None, cleanup=0, drift=False, timeout=False, malformed=False):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertTrue(args[3].startswith('vms-credential-maintenance-test-'))
            self.assertEqual(args[3], calls[0][3])
            self.assertEqual(args[5], '/dev/null')
            for key in ('COMPOSE_PROJECT_NAME', 'CAMERA_TEST_DATABASE_URL', 'PGPASSWORD', 'VMS_PRODUCTION_PASSWORD'):
                self.assertNotIn(key, kwargs['env'])
            if 'down' in args: return subprocess.CompletedProcess(args, cleanup)
            stage = 'go_vet' if len(calls) == 1 else 'native_maintenance_and_regression'
            if timeout: raise subprocess.TimeoutExpired(args, 1)
            if stage == 'native_maintenance_and_regression':
                rows = transcript() if not malformed else transcript()[:-2]
                if fail_stage == stage:
                    rows.append({'Package': tool.PACKAGE, 'Test': next(iter(tool.PHASES)), 'Action': 'fail'})
                kwargs['stdout'].write(('\n'.join(json.dumps(r) for r in rows) + '\n').encode())
                if drift:
                    (self.root / 'src/platform/camera/internal/storage/maintenance_fixture.go').write_bytes(b'concurrent edit')
            return subprocess.CompletedProcess(args, 1 if stage == fail_stage else 0)
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), patch.dict(tool.os.environ,
            {'COMPOSE_PROJECT_NAME': 'vms-project', 'CAMERA_TEST_DATABASE_URL': 'synthetic-production',
             'PGPASSWORD': 'synthetic-private', 'VMS_PRODUCTION_PASSWORD': 'synthetic-private'}):
            result = tool.verify(self.root, run=run)
        self.assertEqual((self.root / '.env').read_bytes(), b'SYNTHETIC_ENV_SENTINEL')
        self.assertEqual((self.root / 'var/camera/credential-keys/key-bundle.json').read_bytes(), b'SYNTHETIC_KEY_SENTINEL')
        for field in ('production_services_modified', 'production_database_modified', 'production_keys_loaded',
                      'production_admission_state_created', 'credential_api_activated', 'production_restore_fence_implemented',
                      'business_runtime_ready', 'database_and_key_restore_performed', 'network_fence_verified'):
            self.assertFalse(result[field])
        for field in ('log', 'report'):
            self.assertEqual(stat.S_IMODE(Path(result[field]).stat().st_mode), 0o600)
        self.assertEqual(calls[-1][-5:], ['down', '--volumes', '--remove-orphans', '--timeout', '5'])
        return result

    def test_success_and_protected_files(self):
        result = self.mock_run()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['native_maintenance_phases_passed'], 7)

    def test_vet_failure_stops_and_cleans(self):
        result = self.mock_run(fail_stage='go_vet')
        self.assertEqual(result['failed_stage'], 'go_vet')
        self.assertFalse(result['go_vet_passed'])
        self.assertTrue(result['isolated_resources_removed'])

    def test_native_failure_has_fixed_safe_test_name(self):
        result = self.mock_run(fail_stage='native_maintenance_and_regression')
        self.assertEqual(result['failed_native_test'], next(iter(tool.PHASES)))
        self.assertFalse(result['go_race_passed'])
        self.assertTrue(result['go_vet_passed'])
        self.assertNotIn('native_maintenance_phases_passed', result)

    def test_timeout_cleans(self):
        result = self.mock_run(timeout=True)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['isolated_resources_removed'])

    def test_incomplete_transcript_cancels_command_success(self):
        self.assertEqual(self.mock_run(malformed=True)['status'], 'failed')

    def test_source_drift_cancels_pass(self):
        self.assertEqual(self.mock_run(drift=True)['code'], 'PROJECT_FILE_CHANGED')

    def test_cleanup_failure_cancels_pass(self):
        result = self.mock_run(cleanup=1)
        self.assertEqual(result['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertNotIn('native_maintenance_phases_passed', result)

    def test_untrusted_test_label_is_not_reported(self):
        rows = [{'Package': tool.PACKAGE, 'Test': 'postgres://synthetic-private', 'Action': 'fail'},
                {'Package': 'private.invalid', 'Test': next(iter(tool.PHASES)), 'Action': 'fail'}]
        self.log.write_text('\n'.join(json.dumps(r) for r in rows))
        self.assertIsNone(tool.failed_native_test(self.log))
        self.log.write_text('\n'.join(json.dumps({'Package': tool.PACKAGE, 'Test': name, 'Action': 'fail'}) for name in tool.PHASES))
        self.assertIsNone(tool.failed_native_test(self.log))


if __name__ == '__main__':
    unittest.main()
