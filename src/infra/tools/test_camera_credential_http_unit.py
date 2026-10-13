import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_http as tool


class CredentialHTTPRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / 'synthetic.log'

    def rows(self):
        rows = []
        for package, tests in ((tool.storage.PACKAGE, tool.storage.EXPECTED_TESTS),
                               (tool.HTTP_PACKAGE, tool.HTTP_TESTS),
                               (tool.CONTRACT_PACKAGE, tool.CONTRACT_TESTS)):
            rows.extend({'Package': package, 'Test': name, 'Action': 'pass'} for name in tests)
            rows.append({'Package': package, 'Action': 'pass'})
        return rows

    def summarize(self, rows):
        self.log.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
        return tool.summarize_log(self.log)

    def test_requires_http_and_native_storage_passes(self):
        result = self.summarize(self.rows())
        self.assertEqual(result['required_credential_http_tests_passed'], 7)
        self.assertEqual(result['required_credential_contract_tests_passed'], 5)
        self.assertEqual(result['required_credential_tests_passed'], 13)
        self.assertTrue(result['actual_http_tls_verified'])
        self.assertTrue(result['http_writer_success_uses_synthetic_store'])
        self.assertFalse(result['native_admitted_store_http_writes_verified'])

    def test_missing_or_skipped_http_case_rejected(self):
        for action in (None, 'skip'):
            with self.subTest(action=action):
                rows = self.rows()
                index = next(i for i, row in enumerate(rows) if row.get('Test') == tool.HTTP_TESTS[-1])
                if action is None:
                    del rows[index]
                else:
                    rows[index]['Action'] = action
                with self.assertRaisesRegex(tool.storage.VerificationError, 'CREDENTIAL_HTTP_TESTS_REQUIRED'):
                    self.summarize(rows)

    def test_wrong_package_and_incomplete_package_rejected(self):
        for wrong in ('test', 'package'):
            with self.subTest(wrong=wrong):
                rows = self.rows()
                index = next(i for i, row in enumerate(rows) if row['Package'] == tool.CONTRACT_PACKAGE
                             and bool(row.get('Test')) == (wrong == 'test'))
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
                self.assertRaisesRegex(tool.storage.VerificationError, 'CREDENTIAL_WRITE_HTTP_PROJECT_REQUIRED'):
            tool.verify(self.root)
        verify.assert_not_called()

    def test_isolated_runner_reused_with_required_summary_and_scope(self):
        (self.root / 'project-manifest.json').write_text(json.dumps({'credential_write_http_implemented': True}))
        runner = lambda *args, **kwargs: subprocess.CompletedProcess(args, 0)
        with patch.object(tool.storage, 'checked_project', return_value='synthetic'), \
                patch.object(tool.storage, 'verify', return_value={'status': 'passed'}) as verify:
            self.assertEqual(tool.verify(self.root, run=runner)['status'], 'passed')
        verify.assert_called_once_with(self.root, run=runner, summarize=tool.summarize_log, scope=tool.SCOPE)


if __name__ == '__main__':
    unittest.main()
