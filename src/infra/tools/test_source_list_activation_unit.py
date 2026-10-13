#!/usr/bin/env python3
"""Test cutover failure boundaries with controlled Docker/HTTP substitutes."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import unittest
import tempfile
from unittest.mock import patch

import activate_camera_source_list as a
import test_camera_source_list_image as image_check
from camera_activation import atomic_write, prepare_secrets, private_directory, sha
from activate_camera_sources import READ_DB_SQL

ROOT = Path(__file__).resolve().parents[3]
OLD, NEW, DB = ['sha256:'+character*64 for character in '123']


class FakeDocker:
    project = 'vms-project'

    def __init__(self, root):
        self.root, self.redact, self.actions = root, [], []
        self.on_switch = None
        self.missing_image = None
        self.containers = {}
        for service, image in (('camera-api', OLD), ('camera-db', DB), ('model-api', 'model'),
                               ('analysis-api', 'analysis'), ('operation-api', 'operation')):
            self.containers[service] = {'id':service+'-original', 'image':image, 'started_at':'original',
                                        'running':True, 'restarts':0}
        names = ('0001_registry.sql','0002_device_idempotency.sql','0003_source_idempotency.sql')
        self.database = {'database':'vms_camera', 'postgres_version_num':170011,
            'migrations':[{'version':i+1, 'name':'migrations/'+name,
                'checksum':sha(root/'src/platform/camera/internal/storage/migrations'/name)}
                for i,name in enumerate(names)], 'source_request_table':'camera.source_create_requests'}

    def preflight(self):
        return 'test-daemon'

    def volume_exists(self):
        return True

    def snapshot(self):
        return copy.deepcopy(self.containers)

    def run(self, args, **kwargs):
        if args[:4] == ['image', 'inspect', '--format', '{{.Id}}']:
            if args[4] == self.missing_image:
                raise a.ActivationError('IMAGE_MISSING')
            return args[4].encode()
        assert args == ['exec', 'camera-db-original', 'psql', '-X', '-q', '-A', '-t', '-v',
                        'ON_ERROR_STOP=1', '-U', 'camera_admin', '-d', 'vms_camera', '-c', READ_DB_SQL], args
        return json.dumps(self.database).encode()

    def compose(self, args, *, image=None, **kwargs):
        if args == ['config', '--format', 'json']:
            pin = [line.split('=',1)[1] for line in (self.root/'.env').read_text().splitlines()
                   if line.startswith('VMS_CAMERA_IMAGE=')][0]
            return json.dumps({'services':{'camera-db':{'image':DB}, 'camera-api':{
                'image':image or pin, 'ports':[{'target':8080, 'published':'18081', 'host_ip':'127.0.0.1'}],
                'environment':{'VMS_API_TOKEN':'test-token'}}}}).encode()
        assert args == a.UP, args
        self.actions.append(image)
        self.containers['camera-api'] = {'id':'camera-'+str(len(self.actions)), 'image':image,
                                         'started_at':'switched', 'running':True, 'restarts':0}
        if self.on_switch:
            self.on_switch(image)
        return b''


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)/'project'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('__pycache__', 'var', 'build', '.env'))
        private_directory(self.root/'var/camera')
        prepare_secrets(self.root, False)
        self.original = ('# keep settings\nVMS_API_TOKEN=test-token\nVMS_CAMERA_IMAGE='+OLD+'\n').encode()
        atomic_write(self.root/'.env', self.original, 0o640)
        self.native = {key:True for key in a.CHECKS}
        self.native.update({'status':'passed', 'scope':a.SCOPE, 'schema_version':3,
            'production_services_modified':False, 'source_list_activated':False,
            'automatic_production_database_restore':False, 'candidate_image':NEW,
            'previous_camera_image':OLD, 'database_image':DB,
            'checked_revision':a.checked_manifest(self.root), 'recipe_sha256':a.recipe_fingerprint(self.root),
            'docker_daemon':'test-daemon'})
        atomic_write(self.root/a.REPORT, json.dumps(self.native).encode())
        self.docker = FakeDocker(self.root)
        self.before = self.docker.snapshot()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(image_check, 'verify_version'))
        self.verify = self.stack.enter_context(patch.object(a, 'verify_list'))
        self.old_verify = self.stack.enter_context(patch.object(a, 'verify_version'))

    def record(self):
        return json.loads((self.root/a.RECEIPT).read_text())

    def assert_protected(self):
        self.assertTrue(a.unchanged_except_camera(self.before, self.docker.snapshot()))
        self.assertEqual(self.docker.database['migrations'][-1]['version'], 3)

    def test_success_then_reapply_has_no_second_switch(self):
        result = a.activate(self.root, self.docker)
        self.assertEqual(result['status'], 'activated')
        self.assertEqual(result['migration_applied'], 0)
        self.assertEqual(self.docker.actions, [NEW])
        self.assertEqual((self.root/'.env').read_bytes(), self.original.replace(OLD.encode(), NEW.encode()))
        self.assertEqual((self.root/'.env').stat().st_mode & 0o777, 0o640)
        backup = Path(result['backup_directory'])
        self.assertEqual((backup/'env.before').read_bytes(), self.original)
        self.assertEqual((backup/'env.before').stat().st_mode & 0o777, 0o600)
        again = a.activate(self.root, self.docker)
        self.assertEqual(again['status'], 'already_activated')
        self.assertFalse(again['service_restart_performed'])
        self.assertEqual(self.docker.actions, [NEW])
        self.assert_protected()

    def test_unverified_or_stale_receipt_stops_before_change(self):
        for changes in ({'status':'running'}, {'recipe_sha256':'wrong'}, {'checked_revision':'wrong'},
                        {'docker_daemon':'other'}, {'image_only_rollback_verified':False}):
            with self.subTest(changes=changes):
                atomic_write(self.root/a.REPORT, json.dumps({**self.native, **changes}).encode())
                with self.assertRaisesRegex(a.ActivationError, 'MATCHING_SOURCE_LIST_IMAGE_CHECK_REQUIRED'):
                    a.activate(self.root, self.docker)
                self.assertEqual(self.docker.actions, [])
                self.assertEqual((self.root/'.env').read_bytes(), self.original)

    def test_missing_rollback_image_prevents_switch(self):
        self.docker.missing_image = OLD
        with self.assertRaisesRegex(a.ActivationError, 'IMAGE_MISSING'):
            a.activate(self.root, self.docker)
        self.assertEqual(self.docker.actions, [])

    def test_failed_candidate_health_restores_old_image_and_environment(self):
        self.verify.side_effect = a.ActivationError('CANDIDATE_NOT_READY')
        with self.assertRaisesRegex(a.ActivationError, 'CANDIDATE_NOT_READY'):
            a.activate(self.root, self.docker)
        self.assertEqual(self.docker.actions, [NEW, OLD])
        self.assertEqual((self.root/'.env').read_bytes(), self.original)
        self.assertEqual(self.record()['recovery'], 'previous_image_restored')
        self.assertFalse(self.record()['database_restore_performed'])
        self.assert_protected()

    def test_compose_failure_after_recreation_rolls_back(self):
        def fail(image):
            if image == NEW:
                raise a.ActivationError('COMPOSE_TIMEOUT')
        self.docker.on_switch = fail
        with self.assertRaisesRegex(a.ActivationError, 'COMPOSE_TIMEOUT'):
            a.activate(self.root, self.docker)
        self.assertEqual(self.docker.actions, [NEW, OLD])
        self.assertEqual(self.record()['recovery'], 'previous_image_restored')
        self.assert_protected()

    def test_concurrent_environment_edit_is_preserved_and_blocks_rollback(self):
        def edit(image):
            if image == NEW:
                with (self.root/'.env').open('ab') as stream:
                    stream.write(b'USER_SETTING=keep\n')
        self.docker.on_switch = edit
        with self.assertRaisesRegex(a.ActivationError, 'CONCURRENT_ENV_EDIT_PRESERVED'):
            a.activate(self.root, self.docker)
        self.assertEqual(self.docker.actions, [NEW])
        self.assertTrue((self.root/'.env').read_bytes().endswith(b'USER_SETTING=keep\n'))
        self.assertEqual(self.record()['recovery'], 'manual_review_required')
        self.assertIsNone(self.record()['source_list_activated'])

    def test_database_restart_blocks_success_and_automatic_rollback(self):
        self.docker.on_switch = lambda image: self.docker.containers['camera-db'].update(started_at='external-restart')
        with self.assertRaisesRegex(a.ActivationError, 'NON_CAMERA_CONTAINERS_CHANGED'):
            a.activate(self.root, self.docker)
        self.assertEqual(self.docker.actions, [NEW])
        self.assertEqual(self.record()['recovery'], 'manual_review_required')

    def test_schema_change_blocks_success_and_rollback(self):
        self.docker.on_switch = lambda image: self.docker.database.update(migrations=[])
        with self.assertRaisesRegex(a.ActivationError, 'DATABASE_SCHEMA_CHANGED'):
            a.activate(self.root, self.docker)
        self.assertEqual(self.docker.actions, [NEW])
        self.assertEqual(self.record()['recovery'], 'manual_review_required')

    def test_rollback_failure_records_manual_review_without_database_restore(self):
        self.verify.side_effect = a.ActivationError('CANDIDATE_NOT_READY')
        def fail(image):
            if image == OLD:
                raise a.ActivationError('OLD_IMAGE_START_FAILED')
        self.docker.on_switch = fail
        with self.assertRaisesRegex(a.ActivationError, 'CANDIDATE_NOT_READY'):
            a.activate(self.root, self.docker)
        self.assertEqual(self.record()['recovery'], 'manual_review_required')
        self.assertFalse(self.record()['database_restore_performed'])
        self.assert_protected()

    def test_failed_or_interrupted_receipt_blocks_unattended_repeat(self):
        for status in ('failed', 'running'):
            atomic_write(self.root/a.RECEIPT, json.dumps({'status':status}).encode())
            with self.assertRaisesRegex(a.ActivationError, 'INCOMPLETE_SOURCE_LIST_ACTIVATION_REQUIRES_REVIEW'):
                a.activate(self.root, self.docker)
        self.assertEqual(self.docker.actions, [])

    def test_failure_after_pin_before_switch_restores_pin_without_restart(self):
        original_write = a.atomic_write
        def fail_stage(path, data, *args):
            if path == self.root/a.RECEIPT and json.loads(data).get('stage') == 'switch_requested' \
                    and json.loads(data).get('status') == 'running':
                raise OSError('journal failure')
            return original_write(path, data, *args)
        with patch.object(a, 'atomic_write', side_effect=fail_stage):
            with self.assertRaisesRegex(OSError, 'journal failure'):
                a.activate(self.root, self.docker)
        self.assertEqual((self.root/'.env').read_bytes(), self.original)
        self.assertEqual(self.docker.actions, [])
        self.assertEqual(self.record()['recovery'], 'previous_image_restored')

    def test_pin_edit_preserves_unrelated_bytes_and_rejects_ambiguous_values(self):
        body = b'# unchanged\r\nVMS_CAMERA_IMAGE='+OLD.encode()+b'\r\nVALUE=keep'
        self.assertEqual(a.pin_environment(body, OLD, NEW), body.replace(OLD.encode(), NEW.encode()))
        for bad in (self.original+b'VMS_CAMERA_IMAGE='+OLD.encode()+b'\n',
                    self.original.replace(OLD.encode(), DB.encode()),
                    self.original+b'COMPOSE_PROJECT_NAME=custom\n'):
            with self.assertRaises(a.ActivationError):
                a.pin_environment(bad, OLD, NEW)

    def test_docker_gate_blocks_build_db_actions_and_unpinned_switches(self):
        docker = a.CameraSwitchDocker(self.root)
        with patch.object(a.Docker, 'run', return_value=b'') as run:
            for args in (['build', 'camera-api'], ['down', '--volumes'], ['restart', 'camera-db'],
                         ['run', '--rm', 'camera-migrate']):
                with self.assertRaises(a.ActivationError):
                    docker.compose(args)
            with self.assertRaises(a.ActivationError):
                docker.compose(a.UP, image='latest')
            with self.assertRaises(a.ActivationError):
                docker.run(['exec','db','psql','-c','DROP SCHEMA camera CASCADE'])
            run.assert_not_called()
            docker.compose(a.UP, image=NEW)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[1][-len(a.UP):], a.UP)


if __name__ == '__main__':
    unittest.main(verbosity=2)
