import io
import json
from pathlib import Path
import tempfile
import unittest

import prepare_camera_test_environment as tool


class EnvironmentTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        self.shared = dict(prefix=tool.SHARED_PREFIX, base_prefix=tool.SHARED_PREFIX, versions=dict(tool.AFTER))
        self.calls = []

    def execute(self, args, log, timeout=300):
        self.calls.append([str(x) for x in args])
        if 'download' in args:
            target = Path(args[args.index('--dest') + 1])
            (target / 'synthetic.whl').write_bytes(b'synthetic wheel')
        return ''

    def test_shared_restore_rejects_wrong_environment_or_unobserved_versions(self):
        for state in ({**self.shared, 'prefix': '/other/env'}, {**self.shared, 'base_prefix': '/base'},
                      {**self.shared, 'versions': {**tool.AFTER, 'protobuf': '6.0.0'}},
                      {**self.shared, 'versions': {**tool.AFTER, 'streamlit': None}}):
            with self.subTest(state=state), self.assertRaises(tool.SetupError):
                tool.shared_plan(state)
        self.assertFalse((self.root / 'var').exists())

    def test_already_restored_never_calls_package_tools(self):
        state = {**self.shared, 'versions': dict(tool.BEFORE)}
        result = tool.restore_shared(self.root, state, io.BytesIO(), self.execute, lambda _: state)
        self.assertEqual(result['status'], 'already_restored')
        self.assertEqual(self.calls, [])

    def test_failed_download_never_installs_into_shared_environment(self):
        def failure(args, log):
            self.execute(args, log)
            raise tool.SetupError('DOWNLOAD_FAILED')
        with self.assertRaises(tool.SetupError):
            tool.restore_shared(self.root, self.shared, io.BytesIO(), failure, lambda _: self.shared)
        self.assertTrue(self.calls)
        self.assertFalse(any('install' in args for args in self.calls))

    def test_version_change_during_download_prevents_restore(self):
        changed = {**self.shared, 'versions': {**tool.AFTER, 'protobuf': '6.0.0'}}
        with self.assertRaisesRegex(tool.SetupError, 'SHARED_ENVIRONMENT_CHANGED'):
            tool.restore_shared(self.root, self.shared, io.BytesIO(), self.execute, lambda _: changed)
        self.assertEqual(len(self.calls), 2)

    def test_download_backup_then_exact_restore_without_dependency_changes(self):
        final = {**self.shared, 'versions': dict(tool.BEFORE)}
        states = iter([self.shared, final])
        result = tool.restore_shared(self.root, self.shared, io.BytesIO(), self.execute, lambda _: next(states))
        self.assertEqual(result['status'], 'restored')
        self.assertFalse(result['shared_dependency_consistency_claimed'])
        self.assertEqual([args[6] for args in self.calls], ['download', 'download', 'install'])
        self.assertIn('--no-deps', self.calls[-1])
        self.assertIn('--no-index', self.calls[-1])
        self.assertNotIn('grpcio-tools', ' '.join(self.calls[-1]))
        receipt = json.loads((Path(result['backup']) / 'receipt.json').read_text())
        self.assertEqual(receipt['before_versions'], tool.AFTER)
        self.assertEqual(receipt['status'], 'restored')
        self.assertEqual(len(receipt['files']), 2)

    def test_restore_failure_receipt_does_not_claim_success(self):
        def failure(args, log):
            self.execute(args, log)
            if 'install' in args:
                raise tool.SetupError('INSTALL_FAILED')
            return ''
        with self.assertRaises(tool.SetupError):
            tool.restore_shared(self.root, self.shared, io.BytesIO(), failure, lambda _: self.shared)
        receipt = next((self.root / 'var/test-streamlit-recovery').glob('*/receipt.json'))
        self.assertEqual(json.loads(receipt.read_text())['status'], 'restore_failed')

    def requirements(self):
        p = self.root / 'src/platform/camera/test_streamlit/requirements.txt'
        p.parent.mkdir(parents=True)
        p.write_bytes(b'streamlit==1.45.1\n')

    def test_existing_unmanaged_directory_and_symlink_are_preserved(self):
        self.requirements()
        home = self.root / 'var/test-streamlit'
        home.mkdir(parents=True)
        (home / 'user-file').write_bytes(b'preserve')
        with self.assertRaisesRegex(tool.SetupError, 'NOT_MANAGED'):
            tool.prepare(self.root, io.BytesIO(), self.execute)
        self.assertEqual((home / 'user-file').read_bytes(), b'preserve')
        redirected = self.root / 'redirected'
        redirected.symlink_to(home, target_is_directory=True)
        with self.assertRaises(tool.SetupError):
            tool.safe(redirected / 'python')
        self.assertEqual(self.calls, [])

    def test_shared_site_packages_and_incomplete_ui_tests_are_rejected(self):
        self.requirements()
        home = self.root / 'var/test-streamlit'
        home.mkdir(parents=True)
        digest = tool.hashlib.sha256(b'streamlit==1.45.1\n').hexdigest()
        tool.atomic_json(home / 'owner.json', dict(format_version=1, owner='vms-camera-test-ui', requirements_sha256=digest))
        venv = home / 'python';venv.mkdir()
        cfg = venv / 'pyvenv.cfg';cfg.write_text('include-system-site-packages = true\n')
        with self.assertRaisesRegex(tool.SetupError, 'NOT_ISOLATED'):
            tool.prepare(self.root, io.BytesIO(), self.execute)
        cfg.write_text('include-system-site-packages = false\n')
        state = dict(prefix=str(venv), base_prefix='/base', versions=dict(tool.AFTER))
        with self.assertRaisesRegex(tool.SetupError, 'COMPLETE_UI_TESTS_REQUIRED'):
            tool.prepare(self.root, io.BytesIO(), self.execute, lambda _: state)


if __name__ == '__main__':
    unittest.main()
