import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_camera_source_upgrade as tool

ROOT = Path(__file__).resolve().parents[3]
PROJECT = tool.PREFIX+'a'*12
IMAGE = 'sha256:'+'a'*64
STATE = {'camera_image':IMAGE, 'database_image':'sha256:'+'b'*64, 'docker_daemon':'test-daemon'}


class FakeDocker:
    instances = []
    fail_cleanup = False
    occupied = False

    def __init__(self, root, project, production_root):
        self.root, self.project, self.redact, self.calls = root, project, [], []
        self.instances.append(self)

    def preflight(self): return 'test-daemon'
    def snapshot(self): return {'camera-db':{}} if self.occupied else {}
    def volume_exists(self): return False

    def compose(self, args, **kwargs):
        self.calls.append(args)
        if self.fail_cleanup: raise tool.ActivationError('CLEANUP_FAILED')
        return b''


class UpgradeCheckTest(unittest.TestCase):
    def setUp(self):
        FakeDocker.instances = []
        FakeDocker.fail_cleanup = FakeDocker.occupied = False

    def test_production_root_and_project_are_rejected(self):
        with self.assertRaisesRegex(tool.ActivationError, 'ISOLATED_PROJECT_REQUIRED'):
            tool.RehearsalDocker(ROOT, 'vms-project', ROOT)
        with self.assertRaisesRegex(tool.ActivationError, 'SEPARATE_TEMPORARY_WORKSPACE_REQUIRED'):
            tool.RehearsalDocker(ROOT, PROJECT, ROOT)
        with self.assertRaisesRegex(tool.ActivationError, 'SEPARATE_TEMPORARY_WORKSPACE_REQUIRED'):
            tool.RehearsalDocker(ROOT/'var/test', PROJECT, ROOT)

    def test_mutable_or_malformed_image_is_rejected(self):
        for image in ('postgres:17.11-bookworm', 'sha256:short', '', None):
            with self.assertRaises(tool.ActivationError): tool.pinned_image(image)
        self.assertEqual(tool.pinned_image(IMAGE), IMAGE)

    def test_workspace_excludes_runtime_and_pins_restore_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'project'
            before = tool.checked_manifest(ROOT)
            token, base, restore_base, _ = tool.configure_workspace(ROOT, root, STATE, PROJECT)
            self.assertNotEqual(base, restore_base)
            self.assertTrue(base.startswith('http://127.0.0.1:'))
            config = json.loads((root/'compose.yaml').read_text())
            restore = config['services']['camera-restore-check']
            self.assertEqual(restore['image'], IMAGE)
            self.assertEqual(restore['profiles'], ['recovery-tools'])
            self.assertIn('/vms_camera_restore?', (root/'var/camera/secrets/restore-dsn').read_text())
            self.assertIn('/vms_camera?', (root/'var/camera/secrets/runtime-dsn').read_text())
            self.assertIn(STATE['database_image'], (root/'src/infra/postgresql/compose.camera.yaml').read_text())
            self.assertFalse((root/'var/camera/source-upgrade-preflight.json').exists())
            self.assertNotIn('18081', (root/'.env').read_text())
            self.assertEqual(tool.checked_manifest(ROOT), before)
            self.assertEqual(tool.RehearsalDocker(root, PROJECT, ROOT).project, PROJECT)
            (root/'rehearsal-project').write_text('other-project')
            with self.assertRaisesRegex(tool.ActivationError, 'WORKSPACE_MARKER_MISMATCH'):
                tool.RehearsalDocker(root, PROJECT, ROOT)

    def test_failure_cleans_only_disposable_project(self):
        with patch.object(tool, 'RehearsalDocker', FakeDocker):
            with self.assertRaisesRegex(tool.ActivationError, 'INJECTED_TEST_FAILURE'):
                with tool.isolated_environment(ROOT, STATE, PROJECT) as (root, docker, *_):
                    raise tool.ActivationError('INJECTED_TEST_FAILURE')
        self.assertEqual(docker.project, PROJECT)
        self.assertEqual(docker.calls, [['--profile','*','down','--volumes','--remove-orphans','--timeout','10']])
        self.assertFalse(root.parent.exists())

    def test_collision_never_removes_existing_project(self):
        FakeDocker.occupied = True
        with patch.object(tool, 'RehearsalDocker', FakeDocker):
            with self.assertRaisesRegex(tool.ActivationError, 'ISOLATED_PROJECT_ALREADY_EXISTS'):
                with tool.isolated_environment(ROOT, STATE, PROJECT): self.fail('must not yield')
        self.assertEqual(FakeDocker.instances[0].calls, [])

    def test_cleanup_failure_retains_bound_secrets(self):
        FakeDocker.fail_cleanup = True
        root = None
        try:
            with patch.object(tool, 'RehearsalDocker', FakeDocker), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(tool.ActivationError, 'CLEANUP_FAILED'):
                    with tool.isolated_environment(ROOT, STATE, PROJECT) as (root, *_): pass
            self.assertTrue((root/'var/camera/secrets/runtime-dsn').is_file())
        finally:
            if root: tool.shutil.rmtree(root.parent)

    def test_migration_version_and_applied_count_must_match(self):
        class MigrationDocker:
            def compose(self, *args, **kwargs): return b'{"version":3,"applied":1}'
        tool.migrate(MigrationDocker(), IMAGE, 3, 1)
        for version, applied in ((2,1),(3,0)):
            with self.assertRaisesRegex(tool.ActivationError, 'UNEXPECTED_MIGRATION_RESULT'):
                tool.migrate(MigrationDocker(), IMAGE, version, applied)

    def test_replay_must_preserve_original_body_and_header(self):
        original = {'device_id':'upgrade-test','created_at':'original'}
        good = [(200,{'device':original},{}), (201,{'device':original},{'Idempotency-Replayed':'true'})]
        with patch.object(tool, 'request', side_effect=good):
            tool.verify_resource('http://test', 'token', 'devices', tool.DEVICE, 'key', original)
        for response in ((201,{'device':original},{}), (201,{'device':{'device_id':'upgrade-test'}},
                                                      {'Idempotency-Replayed':'true'})):
            with patch.object(tool, 'request', side_effect=[good[0],response]):
                with self.assertRaisesRegex(tool.ActivationError, 'IDEMPOTENT_RESPONSE_NOT_PRESERVED'):
                    tool.verify_resource('http://test', 'token', 'devices', tool.DEVICE, 'key', original)


if __name__ == '__main__': unittest.main()
