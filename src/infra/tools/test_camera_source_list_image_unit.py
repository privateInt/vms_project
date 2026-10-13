#!/usr/bin/env python3
"""Failure-boundary tests for the image check. Docker behavior needs a native run."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_camera_source_list_image as m

ROOT = Path(__file__).resolve().parents[3]
OLD = 'sha256:'+'1'*64
NEW = 'sha256:'+'2'*64
DB = 'sha256:'+'3'*64
PROJECT = m.PREFIX+'abcdef012345'


class Boundaries(unittest.TestCase):
    def test_manifest_accepts_exact_step06_and_rejects_modified_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'project'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('__pycache__', 'var', 'build'))
            m.checked_manifest(root)
            path = root/'src/platform/camera/internal/app/source_list.go'
            path.write_text(path.read_text()+'\n// unexpected edit\n')
            with self.assertRaisesRegex(m.ActivationError, 'PROJECT_FILE_CHANGED'):
                m.checked_manifest(root)

    def test_manifest_rejects_older_revision_and_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = json.loads((ROOT/'project-manifest.json').read_text())
            manifest['activation_revision'] = 'step05-source-registration-code-20260930'
            (root/'project-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(m.ActivationError, 'STEP06_A_PROJECT_REQUIRED'):
                m.checked_manifest(root)
            manifest['activation_revision'] = 'step06-source-list-code-20260930'
            manifest['files'] = {'../secret':'bad'}
            (root/'project-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(m.ActivationError, 'PROJECT_MANIFEST_INVALID'):
                m.checked_manifest(root)

    def test_production_handle_rejects_mutations_before_running_docker(self):
        live = m.InspectionDocker(ROOT)
        with patch.object(m.Docker, 'run') as run:
            for args in (['build', '.'], ['stop', 'camera'], ['rm', 'camera'],
                         ['volume', 'rm', 'data'], ['exec', 'db', 'psql', '-c', 'DELETE FROM camera.devices']):
                with self.assertRaisesRegex(m.ActivationError, 'PRODUCTION_DOCKER_WRITE_REJECTED'):
                    live.run(args)
            for args in (['up', '-d', 'camera-api'], ['down', '--volumes'], ['build', 'camera-api'],
                         ['run', '--rm', 'camera-migrate']):
                with self.assertRaisesRegex(m.ActivationError, 'PRODUCTION_COMPOSE_WRITE_REJECTED'):
                    live.compose(args)
            run.assert_not_called()
            run.return_value = b'{}'
            m.read_database(live, 'database-id')
            run.assert_called_once()

    def test_workspace_copies_only_verified_files_and_generates_new_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'isolated'
            state = {'checked_revision':m.checked_manifest(ROOT), 'database_image':DB}
            token, base, _ = m.configure_workspace(ROOT, root, state, PROJECT)
            config = json.loads((root/'compose.yaml').read_text())
            self.assertEqual(config, {'include':[{'path':m.ACTIVE}]})
            self.assertIn('127.0.0.1', base)
            self.assertGreater(len(token), 30)
            self.assertNotIn('VMS_CAMERA_IMAGE=', (root/'.env').read_text())
            self.assertIn(DB, (root/'src/infra/postgresql/compose.camera.yaml').read_text())
            self.assertFalse((root/'var/camera/source-activation.json').exists())
            self.assertEqual((root/'var/camera/secrets').stat().st_mode & 0o777, 0o700)
            # The checker itself is additive and outside the frozen step06-A manifest.
            self.assertFalse((root/'src/infra/tools/test_camera_source_list_image.py').exists())

    def test_isolated_handle_rejects_production_root_or_project(self):
        with self.assertRaisesRegex(m.ActivationError, 'ISOLATED_PROJECT_REQUIRED'):
            m.IsolatedDocker(ROOT, 'vms-project', ROOT)
        with self.assertRaisesRegex(m.ActivationError, 'SEPARATE_TEMPORARY_WORKSPACE_REQUIRED'):
            m.IsolatedDocker(ROOT, PROJECT, ROOT)
        with self.assertRaisesRegex(m.ActivationError, 'SEPARATE_TEMPORARY_WORKSPACE_REQUIRED'):
            m.IsolatedDocker(ROOT/'var/temp', PROJECT, ROOT)

    def cleanup_fixture(self, temporary):
        directory = Path(temporary)/'managed'
        directory.mkdir()
        root = directory/'project'
        def configure(*args):
            root.mkdir()
            return 'test-token', 'http://127.0.0.1:1234', {'dsn':'test-dsn'}
        docker = Mock()
        docker.preflight.return_value = 'daemon'
        docker.snapshot.return_value = {}
        docker.volume_exists.return_value = False
        docker.run.return_value = b''
        docker.redact = []
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(m.tempfile, 'mkdtemp', return_value=str(directory)))
        stack.enter_context(patch.object(m, 'configure_workspace', side_effect=configure))
        stack.enter_context(patch.object(m, 'IsolatedDocker', return_value=docker))
        return stack, directory, docker

    def test_build_failure_cleans_only_isolated_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            stack, directory, docker = self.cleanup_fixture(temporary)
            with stack, self.assertRaisesRegex(m.ActivationError, 'SIMULATED_BUILD_FAILURE'):
                with m.isolated_environment(ROOT, {'docker_daemon':'daemon'}, PROJECT):
                    raise m.ActivationError('SIMULATED_BUILD_FAILURE')
            docker.compose.assert_called_once_with(
                ['--profile', '*', 'down', '--volumes', '--remove-orphans', '--timeout', '10'])
            self.assertFalse(directory.exists())

    def test_cleanup_failure_preserves_workspace_and_cannot_return_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            stack, directory, docker = self.cleanup_fixture(temporary)
            docker.compose.side_effect = m.ActivationError('CLEANUP_FAILURE')
            with stack, contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(m.ActivationError, 'CLEANUP_FAILURE'):
                    with m.isolated_environment(ROOT, {'docker_daemon':'daemon'}, PROJECT):
                        pass
            self.assertTrue(directory.exists())
            self.assertIn('retained_workspace', output.getvalue())

    def test_daemon_change_prevents_resource_creation_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            stack, directory, docker = self.cleanup_fixture(temporary)
            with stack, self.assertRaisesRegex(m.ActivationError, 'DOCKER_DAEMON_CHANGED'):
                with m.isolated_environment(ROOT, {'docker_daemon':'other'}, PROJECT):
                    self.fail('must not yield')
            docker.compose.assert_not_called()
            self.assertFalse(directory.exists())

    def test_failed_run_invalidates_prior_pass_without_secret_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root/'src/infra/tools/test_camera_source_list_image.py'
            report = root/m.REPORT
            report.parent.mkdir(parents=True, mode=0o700)
            report.write_text('{"status":"passed"}')
            with patch.object(m, '__file__', str(script)), patch.object(m, 'run_check',
                    side_effect=m.ActivationError('BUILD_FAILED: secret-value')), \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(m.main(), 1)
            self.assertEqual(json.loads(report.read_text())['status'], 'failed')
            self.assertNotIn('secret-value', output.getvalue())

    def test_changed_production_state_prevents_passed_receipt(self):
        live = Mock()
        live.snapshot.return_value = {'camera-db':{'id':'changed'}}
        state = {'containers':{'camera-db':{'id':'original'}}}
        with patch.object(m, 'inspect_live', return_value=state), \
                patch.object(m, 'recipe_fingerprint', return_value='recipe'), \
                patch.object(m, 'rehearse', return_value={'candidate_image':NEW}), \
                contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaisesRegex(m.ActivationError, 'PRODUCTION_OR_RECIPE_CHANGED'):
            m.run_check(ROOT, live, PROJECT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
