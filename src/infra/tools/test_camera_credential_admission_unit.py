import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_admission as tool


def rows_for(names, phase=None):
    rows = []
    for name in names:
        rows.append({'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'})
        if phase is not None:
            rows.append({'Package': tool.PACKAGE, 'Test': name, 'Action': 'output',
                         'Output': 'ADMISSION_NATIVE_PHASE_OK:' + phase + '\n'})
        rows.append({'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'})
    return rows


def transcript():
    return rows_for(sorted(tool.REQUIRED)) + rows_for([tool.NATIVE_TEST], 'prepare') + rows_for([tool.NATIVE_TEST], 'read')


class AdmissionRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'project-manifest.json').write_text(json.dumps({'credential_admission_foundation_revision': tool.REVISION}))
        self.calls = []

    def summary(self, rows):
        path = self.root / 'transcript.log'
        path.write_text('\n'.join(json.dumps(x) for x in rows) + '\n')
        return tool.summarize_log(path)

    def fake_run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        rows = []
        if 'admission-prepare' in command:
            rows = rows_for(sorted(tool.REQUIRED)) + rows_for([tool.NATIVE_TEST], 'prepare')
        elif 'admission-runtime' in command:
            rows = rows_for([tool.NATIVE_TEST], 'read')
        kwargs['stdout'].write(('\n'.join(json.dumps(x) for x in rows) + '\n').encode())
        return subprocess.CompletedProcess(command, 0)

    def verify(self, run=None, revisions=None):
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), patch.object(tool, 'checked_project', side_effect=revisions or ['hash', 'hash']):
            return tool.verify(self.root, run or self.fake_run)

    def test_complete_proof(self):
        result = self.summary(transcript())
        self.assertEqual(result['required_admission_tests_passed'], 17)
        self.assertTrue(result['public_reader_verified'])

    def test_incomplete_required_tests_or_native_phase(self):
        for rows in [transcript()[2:], rows_for(sorted(tool.REQUIRED)), transcript()[:-1]]:
            with self.assertRaises(tool.VerificationError):
                self.summary(rows)

    def test_missing_or_reordered_native_phase(self):
        for phases in [('read', 'prepare'), ('prepare', 'prepare'), ('read',)]:
            rows = rows_for(sorted(tool.REQUIRED))
            for phase in phases:
                rows += rows_for([tool.NATIVE_TEST], phase)
            with self.assertRaises(tool.VerificationError):
                self.summary(rows)

    def test_fail_and_skip_cannot_be_masked(self):
        for action in ('fail', 'skip'):
            with self.assertRaises(tool.VerificationError):
                self.summary(transcript() + [{'Action': action}])

    def test_marker_requires_running_native_test(self):
        rows = transcript()
        rows.insert(0, {'Package': tool.PACKAGE, 'Test': tool.NATIVE_TEST, 'Action': 'output', 'Output': 'ADMISSION_NATIVE_PHASE_OK:read'})
        with self.assertRaises(tool.VerificationError):
            self.summary(rows)

    def test_success_uses_isolation_and_private_report(self):
        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'production', 'VMS_ADMISSION_NATIVE_PHASE': 'read', 'CAMERA_PASSWORD': 'PRIVATE_SENTINEL'}):
            result = self.verify()
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['isolated_resources_removed'])
        self.assertEqual(len(self.calls), 3)
        for command, arguments in self.calls:
            self.assertIn('--env-file', command)
            self.assertIn(os.devnull, command)
            self.assertTrue(command[3].startswith('vms-credential-admission-test-'))
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(arguments['env']))
            self.assertNotIn('COMPOSE_PROJECT_NAME', arguments['env'])
        self.assertIn('--volumes', self.calls[-1][0])
        for field in ('production_services_modified', 'production_database_modified', 'production_keys_loaded', 'production_admission_state_created', 'credential_api_activated', 'production_restore_fence_implemented', 'business_runtime_ready'):
            self.assertFalse(result[field])
        self.assertEqual(stat.S_IMODE(Path(result['log']).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(result['report']).stat().st_mode), 0o600)

    def test_command_failure_reports_stage_and_cleans(self):
        def run(command, **kwargs):
            self.fake_run(command, **kwargs)
            return subprocess.CompletedProcess(command, 42 if 'admission-runtime' in command else 0)
        result = self.verify(run)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_stage'], 'read_only_runtime')
        self.assertEqual(result['last_completed_stage'], 'prepare_tools_and_fixture')
        self.assertEqual(result['failed_command_exit_code'], 42)
        self.assertTrue(result['isolated_resources_removed'])
        self.assertFalse(result['go_race_passed'])
        self.assertNotIn('public_reader_verified', result)

    def test_timeout_reports_no_invented_exit_and_cleans(self):
        def run(command, **kwargs):
            if 'admission-prepare' in command:
                raise subprocess.TimeoutExpired(command, 900)
            return self.fake_run(command, **kwargs)
        result = self.verify(run)
        self.assertEqual(result['failed_stage'], 'prepare_tools_and_fixture')
        self.assertNotIn('failed_command_exit_code', result)
        self.assertTrue(result['isolated_resources_removed'])

    def test_cleanup_failure_revokes_pass(self):
        def run(command, **kwargs):
            self.fake_run(command, **kwargs)
            return subprocess.CompletedProcess(command, 1 if 'down' in command else 0)
        result = self.verify(run)
        self.assertEqual(result['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertFalse(result['isolated_resources_removed'])
        self.assertFalse(result['go_vet_passed'])
        self.assertNotIn('public_reader_verified', result)

    def test_source_change_rejects_pass(self):
        result = self.verify(revisions=['hash', 'changed'])
        self.assertEqual(result['code'], 'PROJECT_CHANGED_DURING_CHECK')
        self.assertEqual(result['failed_stage'], 'verify_source')
        self.assertTrue(result['isolated_resources_removed'])

    def test_prepare_uses_real_standard_test2json_and_race_vet(self):
        self.assertIn('go build -o /exchange/test2json cmd/test2json', tool.PREPARE)
        self.assertIn('go test -race -c', tool.PREPARE)
        self.assertIn('go vet ./...', tool.PREPARE)
        self.assertNotIn('GOTOOLDIR', tool.PREPARE)
        self.assertNotIn('credential-keys', tool.PREPARE)


if __name__ == '__main__':
    unittest.main()
