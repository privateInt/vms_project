import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_versions as tool


class CredentialVersionsRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / 'synthetic.log'

    def rows(self):
        rows = []
        for package, tests in ((tool.storage.PACKAGE, tool.storage.EXPECTED_TESTS),
                               (tool.write.HTTP_PACKAGE, tool.write.HTTP_TESTS),
                               (tool.write.CONTRACT_PACKAGE, tool.write.CONTRACT_TESTS),
                               (tool.HTTP_PACKAGE, tool.HTTP_TESTS),
                               (tool.CONTRACT_PACKAGE, tool.CONTRACT_TESTS),
                               (tool.storage.PACKAGE, tool.METADATA_TESTS)):
            rows.extend({'Package': package, 'Test': name, 'Action': 'pass'} for name in tests)
            rows.append({'Package': package, 'Action': 'pass'})
        unique = []
        package_passes = set()
        for row in rows:
            if 'Test' not in row:
                if row['Package'] in package_passes:
                    continue
                package_passes.add(row['Package'])
            unique.append(row)
        return unique

    def summarize(self, rows):
        self.log.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
        return tool.summarize_log(self.log)

    def test_requires_http_and_native_storage_passes(self):
        result = self.summarize(self.rows())
        self.assertEqual(result['required_credential_version_http_tests_passed'], 8)
        self.assertEqual(result['required_credential_revoke_contract_tests_passed'], 3)
        self.assertEqual(result['required_credential_metadata_tests_passed'], 4)
        self.assertEqual(result['required_credential_tests_passed'], 13)
        self.assertTrue(result['actual_http_tls_verified'])
        self.assertTrue(result['version_http_success_uses_synthetic_store'])
        self.assertTrue(result['metadata_store_test_admission_uses_synthetic_guard'])
        self.assertFalse(result['native_admitted_store_version_http_verified'])
        self.assertFalse(result['native_admitted_store_http_writes_verified'])

    def test_missing_or_skipped_metadata_and_contract_case_rejected(self):
        for name in (tool.METADATA_TESTS[-1], tool.CONTRACT_TESTS[-1]):
            for action in (None, 'skip'):
                with self.subTest(name=name, action=action):
                    rows = self.rows()
                    index = next(i for i, row in enumerate(rows) if row.get('Test') == name)
                    if action is None:
                        del rows[index]
                    else:
                        rows[index]['Action'] = action
                    with self.assertRaisesRegex(tool.storage.VerificationError, 'CREDENTIAL_VERSION_HTTP_TESTS_REQUIRED'):
                        self.summarize(rows)

    def test_write_http_regression_required(self):
        rows = self.rows()
        rows = [row for row in rows if row.get('Test') != tool.write.HTTP_TESTS[0]]
        with self.assertRaisesRegex(tool.storage.VerificationError, 'CREDENTIAL_HTTP_TESTS_REQUIRED'):
            self.summarize(rows)

    def test_missing_or_skipped_http_case_rejected(self):
        for action in (None, 'skip'):
            with self.subTest(action=action):
                rows = self.rows()
                index = next(i for i, row in enumerate(rows) if row.get('Test') == tool.HTTP_TESTS[-1])
                if action is None:
                    del rows[index]
                else:
                    rows[index]['Action'] = action
                with self.assertRaisesRegex(tool.storage.VerificationError, 'CREDENTIAL_VERSION_HTTP_TESTS_REQUIRED'):
                    self.summarize(rows)

    def test_wrong_package_and_incomplete_package_rejected(self):
        for wrong in ('test', 'package'):
            with self.subTest(wrong=wrong):
                rows = self.rows()
                index = next(i for i, row in enumerate(rows) if row['Package'] == tool.CONTRACT_PACKAGE
                             and (row.get('Test') in tool.CONTRACT_TESTS if wrong == 'test' else not row.get('Test')))
                rows[index]['Package'] = 'unrelated/package'
                with self.assertRaises(tool.storage.VerificationError):
                    self.summarize(rows)

    def test_native_storage_skip_rejected(self):
        rows = self.rows()
        rows[0]['Action'] = 'skip'
        with self.assertRaisesRegex(tool.storage.VerificationError, 'NATIVE_CREDENTIAL_TESTS_REQUIRED'):
            self.summarize(rows)

    def test_failure_cannot_be_hidden_by_later_pass(self):
        rows = [{'Package': tool.HTTP_PACKAGE, 'Test': tool.HTTP_TESTS[0], 'Action': 'fail'}] + self.rows()
        with self.assertRaisesRegex(tool.storage.VerificationError, 'GO_TEST_FAILED'):
            self.summarize(rows)

    def test_unimplemented_project_rejected_before_execution(self):
        (self.root / 'project-manifest.json').write_text('{}')
        with patch.object(tool.storage, 'checked_project', return_value='synthetic'), \
                patch.object(tool.storage, 'verify') as verify, \
                self.assertRaisesRegex(tool.storage.VerificationError, 'CREDENTIAL_VERSION_HTTP_PROJECT_REQUIRED'):
            tool.verify(self.root)
        verify.assert_not_called()

    def test_isolated_runner_reused_with_required_summary_and_scope(self):
        (self.root / 'project-manifest.json').write_text(json.dumps({'credential_write_http_implemented': True, 'credential_version_http_implemented': True}))
        runner = lambda *args, **kwargs: subprocess.CompletedProcess(args, 0)
        with patch.object(tool.storage, 'checked_project', return_value='synthetic'), \
                patch.object(tool.storage, 'verify', return_value={'status': 'passed'}) as verify:
            self.assertEqual(tool.verify(self.root, run=runner)['status'], 'passed')
        verify.assert_called_once_with(self.root, run=runner, summarize=tool.summarize_log, scope=tool.SCOPE)


if __name__ == '__main__':
    unittest.main()
