import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_management as tool


class CredentialManagementRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / 'test.log'

    def rows(self):
        rows, seen = [], set()
        groups = ((tool.storage.PACKAGE, tool.storage.EXPECTED_TESTS),
                  (tool.versions.write.HTTP_PACKAGE, tool.versions.write.HTTP_TESTS),
                  (tool.versions.write.CONTRACT_PACKAGE, tool.versions.write.CONTRACT_TESTS),
                  (tool.versions.HTTP_PACKAGE, tool.versions.HTTP_TESTS),
                  (tool.versions.CONTRACT_PACKAGE, tool.versions.CONTRACT_TESTS),
                  (tool.storage.PACKAGE, tool.versions.METADATA_TESTS),
                  (tool.PACKAGE, tool.POLICY_TESTS))
        for package, names in groups:
            rows.extend({'Package': package, 'Test': name, 'Action': 'pass'} for name in names)
            if package not in seen:
                rows.append({'Package': package, 'Action': 'pass'})
                seen.add(package)
        # A normal whole-module regression skips the explicitly enabled native
        # fixture; that skip must never count as the later integration success.
        rows.extend([{'Package': tool.PACKAGE, 'Test': tool.NATIVE_TEST, 'Action': 'run'},
                     {'Package': tool.PACKAGE, 'Test': tool.NATIVE_TEST, 'Action': 'skip'},
                     {'Package': tool.PACKAGE, 'Test': tool.NATIVE_TEST, 'Action': 'run'}])
        rows.extend({'Package': tool.PACKAGE, 'Test': tool.NATIVE_TEST, 'Action': 'output',
                     'Output': tool.PREFIX + name + '\n'} for name in tool.PHASES)
        rows.extend([{'Package': tool.PACKAGE, 'Test': tool.NATIVE_TEST, 'Action': 'pass'},
                     {'Package': tool.PACKAGE, 'Action': 'pass'}])
        return rows

    def summarize(self, rows):
        self.log.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        return tool.summarize_log(self.log)

    def test_complete_native_transcript_and_component_regression_required(self):
        result = self.summarize(self.rows())
        self.assertEqual(result['required_management_policy_tests_passed'], 6)
        self.assertEqual(result['native_management_phases_passed'], 8)
        self.assertTrue(result['native_admitted_store_http_writes_verified'])
        self.assertTrue(result['native_admitted_store_version_http_verified'])
        self.assertFalse(result['production_managed_reference_usage_guard_implemented'])
        self.assertFalse(result['enterprise_iam_integration_verified'])
        self.assertTrue(result['usage_guard_success_is_fixture_only'])

    def test_component_test_skip_and_missing_policy_rejected(self):
        for name in (tool.storage.EXPECTED_TESTS[0], tool.versions.HTTP_TESTS[0], tool.POLICY_TESTS[0]):
            for action in (None, 'skip'):
                with self.subTest(name=name, action=action):
                    rows = self.rows()
                    item = next(r for r in rows if r.get('Test') == name)
                    if action is None:
                        rows.remove(item)
                    else:
                        item['Action'] = action
                    with self.assertRaises(tool.storage.VerificationError):
                        self.summarize(rows)

    def test_native_missing_skip_or_unfinished_is_not_success(self):
        for action in (None, 'skip'):
            rows = self.rows()
            item = next(r for r in rows if r.get('Test') == tool.NATIVE_TEST and r['Action'] == 'pass')
            if action is None:
                rows.remove(item)
            else:
                item['Action'] = action
            with self.assertRaises(tool.storage.VerificationError):
                self.summarize(rows)

    def test_phase_missing_duplicate_reorder_and_unrelated_output_rejected(self):
        for change in ('missing', 'duplicate', 'order', 'package', 'test', 'unattributed'):
            rows = self.rows()
            items = [r for r in rows if r.get('Action') == 'output']
            first = items[0]
            if change == 'missing': rows.remove(first)
            elif change == 'duplicate': rows.insert(rows.index(first), dict(first))
            elif change == 'order': first['Output'], items[1]['Output'] = items[1]['Output'], first['Output']
            elif change == 'package': first['Package'] = 'unrelated/package'
            elif change == 'test': first['Test'] = tool.POLICY_TESTS[0]
            else: rows.remove(next(r for r in reversed(rows) if r.get('Test') == tool.NATIVE_TEST and r['Action'] == 'run'))
            with self.subTest(change=change), self.assertRaises(tool.storage.VerificationError):
                self.summarize(rows)

    def test_failure_before_later_pass_cannot_be_hidden(self):
        with self.assertRaisesRegex(tool.storage.VerificationError, 'GO_TEST_FAILED'):
            self.summarize([{'Package': 'other', 'Action': 'fail'}] + self.rows())

    def test_source_gate_precedes_docker_or_output_creation(self):
        (self.root / 'project-manifest.json').write_text('{}')
        with patch.object(tool.storage, 'checked_project', return_value='test'), \
                patch.object(tool.shutil, 'which') as which, \
                self.assertRaisesRegex(tool.storage.VerificationError, 'CREDENTIAL_MANAGEMENT_PROJECT_REQUIRED'):
            tool.verify(self.root)
        which.assert_not_called()
        self.assertFalse((self.root / 'var').exists())

    def run_fixture(self, fail=None, timeout=None, cleanup_fail=False):
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs['env']))
            if timeout is not None and timeout in command:
                raise subprocess.TimeoutExpired(command, 1)
            if '-test.run=^' + tool.NATIVE_TEST + '$' in command:
                kwargs['stdout'].write(('\n'.join(json.dumps(r) for r in self.rows()) + '\n').encode())
            code = 1 if (fail is not None and fail in command) or (cleanup_fail and 'down' in command) else 0
            return subprocess.CompletedProcess(command, code)
        with patch.object(tool, 'checked_revision', return_value='test-revision'), \
                patch.object(tool.shutil, 'which', return_value='docker'), \
                patch.dict(tool.os.environ, {'CAMERA_TEST_DATABASE_URL': 'PRIVATE_OWNER', 'PGPASSWORD': 'PRIVATE_PG',
                                              'COMPOSE_FILE': 'PRIVATE_COMPOSE', 'VMS_HOST_SECRET': 'PRIVATE_VMS'}):
            result = tool.verify(self.root, run=run)
        return result, calls

    def test_disposable_commands_env_cleanup_and_roles_report(self):
        result, calls = self.run_fixture()
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['isolated_resources_removed'])
        self.assertTrue(result['native_admitted_store_version_http_verified'])
        for field in ('production_services_modified', 'production_database_modified', 'production_keys_loaded',
                      'credential_api_activated', 'business_runtime_ready'):
            self.assertFalse(result[field])
        self.assertEqual(result['management_database_schema_version'], 9)
        for cmd, env in calls:
            self.assertIn('--project-name', cmd)
            self.assertNotIn('ports', cmd)
            self.assertFalse(any(key.startswith(('CAMERA_', 'PG', 'COMPOSE_')) for key in env))
            self.assertFalse(any(key.startswith('VMS_') and key != 'VMS_BINDINGS_TEST_PASSWORD' for key in env))
        self.assertIn('down', calls[-1][0])
        self.assertIn('--volumes', calls[-1][0])
        self.assertEqual(Path(result['report']).stat().st_mode & 0o777, 0o600)

    def test_command_failure_clears_native_claims_and_cleans(self):
        result, calls = self.run_fixture(fail='management-owner')
        self.assertEqual(result['code'], 'ISOLATED_MANAGEMENT_COMMAND_FAILED')
        self.assertEqual(result['failed_stage'], 'admitted_management_http')
        self.assertEqual(result['last_completed_stage'], 'regression')
        self.assertFalse(result['go_race_passed'])
        self.assertNotIn('native_admitted_store_http_writes_verified', result)
        self.assertIn('down', calls[-1][0])

    def test_timeout_and_cleanup_failure_reported_without_success(self):
        result, calls = self.run_fixture(timeout='bindings-build', cleanup_fail=True)
        self.assertEqual(result['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertFalse(result['isolated_resources_removed'])
        self.assertNotIn('native_management_phases_passed', result)
        self.assertIn('down', calls[-1][0])


if __name__ == '__main__':
    unittest.main()
