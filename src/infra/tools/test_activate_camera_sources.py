import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import activate_camera_sources as tool

ROOT = Path(__file__).resolve().parents[3]
OLD, NEW, DB = ['sha256:'+c*64 for c in 'abc']
COUNTS = {'devices':2,'device_requests':2,'video_sources':0,'stream_profiles':0}


class FakeDocker:
    def __init__(self, root):
        self.root, self.project, self.redact, self.calls = root, 'vms-project', [], []
        self.version, self.fail, self.clients = 2, None, 0
        self.counts = copy.deepcopy(COUNTS)
        self.state = {
            'camera-api':{'id':'old-api','image':OLD,'started_at':'old','running':True,'restarts':0},
            'camera-db':{'id':'db','image':DB,'started_at':'old','running':True,'restarts':0},
            'model-api':{'id':'model','image':'model','started_at':'old','running':True,'restarts':0}}

    def preflight(self): return 'daemon'
    def volume_exists(self): return True
    def snapshot(self): return copy.deepcopy(self.state)

    def database(self):
        names = ('0001_registry.sql','0002_device_idempotency.sql','0003_source_idempotency.sql')
        return {'database':'vms_camera','postgres_version_num':170011,'other_clients':self.clients,
                'migrations':[{'version':i+1,'name':'migrations/'+name,
                               'checksum':tool.sha(self.root/'src/platform/camera/internal/storage/migrations'/name)}
                              for i,name in enumerate(names[:self.version])],
                'source_request_table':None if self.version == 2 else 'camera.source_create_requests',
                'counts':copy.deepcopy(self.counts)}

    def run(self, args, **kwargs):
        self.calls.append(args)
        if args[:2] == ['image','inspect']: return args[-1].encode()
        if args[:2] == ['exec','db']:
            assert args[-1] == tool.READ_DB_SQL
            return json.dumps(self.database()).encode()
        if args == ['start','old-api']:
            self.state['camera-api']['running'] = True
            self.state['camera-api']['started_at'] = 'restarted'
            return b'old-api'
        raise AssertionError(args)

    def compose(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == 'config':
            image = kwargs.get('image')
            if not image: image = NEW if ('VMS_CAMERA_IMAGE='+NEW) in (self.root/'.env').read_text() else OLD
            return json.dumps({'services':{'camera-api':{
                'image':image,'ports':[{'target':8080,'published':'18081','host_ip':'127.0.0.1'}],
                'environment':{'VMS_API_TOKEN':'test-token-must-not-appear-in-receipts'}}}}).encode()
        if args[0] == 'stop':
            self.state['camera-api']['running'] = False
            if self.fail == 'stop': raise tool.ActivationError('INJECTED_STOP_FAILURE')
            return b''
        if args[0] == 'exec' and 'pg_dump' in args:
            if self.fail == 'backup': raise tool.ActivationError('INJECTED_BACKUP_FAILURE')
            kwargs['stdout'].write(b'PGDMP-synthetic-test-backup')
            if self.fail == 'env':
                with (self.root/'.env').open('ab') as stream: stream.write(b'# concurrent user edit\n')
            return b''
        if args[0] == 'exec' and 'pg_restore' in args:
            assert '--list' in args
            return b''
        if args[0] == 'run':
            assert kwargs['image'] == NEW
            self.version = 3
            if self.fail == 'migration': raise tool.ActivationError('INJECTED_COMMITTED_MIGRATION_FAILURE')
            return b'{"version":3,"applied":1}'
        if args[0] == 'up':
            assert args[-1] == 'camera-api' and '--no-deps' in args and '--no-build' in args
            self.state['camera-api'] = {'id':'new-api','image':NEW,'started_at':'new','running':True,'restarts':0}
            if self.fail == 'startup':
                self.counts['video_sources'] = 1
                raise tool.ActivationError('INJECTED_STARTUP_FAILURE_AFTER_WRITE')
            return b''
        raise AssertionError(args)


class SourceActivationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'
        shutil.copytree(ROOT,self.root,ignore=shutil.ignore_patterns('var','build','.env','__pycache__'))
        self.original = b'VMS_API_TOKEN=existing-private-token\nVMS_CAMERA_COMPOSE_FILE=./src/platform/camera/compose.active.yaml\n'
        (self.root/'.env').write_bytes(self.original)
        tool.private_directory(self.root/'var/camera')
        tool.prepare_secrets(self.root,False)
        self.native = {key:True for key in tool.CHECKS}
        self.native.update({'status':'passed','scope':'camera_source_upgrade_native_docker',
                            'production_services_modified':False,'source_api_activated':False,
                            'automatic_production_database_restore':False,
                            'checked_revision':tool.checked_manifest(self.root),'recipe_sha256':tool.recipe_fingerprint(self.root),
                            'docker_daemon':'daemon','candidate_image':NEW,'previous_camera_image':OLD,'database_image':DB})
        self.write_receipt()
        self.docker = FakeDocker(self.root)
        self.before = self.docker.snapshot()
        self.state = {'camera_image':OLD,'database_image':DB,'containers':self.before,
                      'endpoint':'http://127.0.0.1:18081','database_bytes':7902899}

    def write_receipt(self):
        (self.root/'var/camera/source-upgrade-check.json').write_text(json.dumps(self.native))

    def activate(self):
        with contextlib.redirect_stdout(io.StringIO()), \
             patch.object(tool,'inspect_upgrade',return_value=self.state), \
             patch.object(tool,'verify_privileges'), patch.object(tool,'verify_version'), \
             patch.object(tool,'verify_source_read'):
            return tool.activate_sources(self.root,self.docker)

    def record(self): return json.loads((self.root/tool.RECEIPT).read_text())

    def test_success_pins_verified_image_and_preserves_non_camera_services(self):
        result = self.activate()
        self.assertEqual(result['status'],'activated')
        self.assertEqual(result['counts_before'],COUNTS)
        self.assertEqual(self.docker.version,3)
        self.assertEqual(self.docker.counts,COUNTS)
        self.assertTrue(tool.unchanged_except_camera(self.before,self.docker.snapshot()))
        self.assertEqual((self.root/'.env').read_bytes(),self.original+('VMS_CAMERA_IMAGE='+NEW+'\n').encode())
        self.assertEqual((Path(result['backup_directory'])/'env.before').read_bytes(),self.original)
        self.assertTrue(Path(result['backup']).read_bytes().startswith(b'PGDMP'))
        self.assertNotIn('existing-private-token',json.dumps(result))
        self.assertFalse(any(c[0] in ('down','build','rm') or '--volumes' in c for c in self.docker.calls))

    def test_stale_or_incomplete_native_receipt_rejected_before_mutation(self):
        for key,value in (('schema_upgrade_verified',False),('docker_daemon','wrong'),('recipe_sha256',{})):
            good = copy.deepcopy(self.native)
            self.native[key] = value
            self.write_receipt()
            with self.assertRaisesRegex(tool.ActivationError,'MATCHING_SOURCE_REHEARSAL_REQUIRED'): self.activate()
            self.assertEqual(self.docker.state,self.before)
            self.native = good
        self.assertFalse((self.root/tool.RECEIPT).exists())

    def test_backup_failure_restarts_original_before_migration(self):
        self.docker.fail = 'backup'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertEqual(self.record()['recovery'],'previous_api_restarted_before_migration')
        self.assertEqual(self.docker.version,2)
        self.assertTrue(self.docker.state['camera-api']['running'])
        self.assertEqual((self.root/'.env').read_bytes(),self.original)
        self.assertFalse(any(c[0] == 'run' for c in self.docker.calls))

    def test_unknown_stop_outcome_recovers_same_container(self):
        self.docker.fail = 'stop'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertIn(['start','old-api'],self.docker.calls)
        self.assertEqual(self.docker.version,2)

    def test_other_database_client_blocks_migration(self):
        self.docker.clients = 1
        with self.assertRaisesRegex(tool.ActivationError,'DATABASE_CLIENTS_NOT_QUIESCED'): self.activate()
        self.assertFalse(any(c[0] == 'run' for c in self.docker.calls))
        self.assertTrue(self.docker.state['camera-api']['running'])

    def test_migration_failure_after_commit_never_restarts_old_or_restores(self):
        self.docker.fail = 'migration'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertEqual(self.docker.version,3)
        self.assertFalse(self.docker.state['camera-api']['running'])
        self.assertNotIn(['start','old-api'],self.docker.calls)
        self.assertIn('VMS_CAMERA_IMAGE='+NEW,(self.root/'.env').read_text())
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertTrue(all('--list' in c for c in self.docker.calls if 'pg_restore' in c))
        self.docker.calls.clear()
        with self.assertRaisesRegex(tool.ActivationError,'INCOMPLETE_SOURCE_ACTIVATION_REQUIRES_REVIEW'): self.activate()
        self.assertFalse(any(c[0] in ('run','up','stop','start','exec') for c in self.docker.calls))

    def test_startup_failure_preserves_acknowledged_new_data(self):
        self.docker.fail = 'startup'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertEqual(self.docker.counts['video_sources'],1)
        self.assertEqual(self.docker.state['camera-api']['image'],NEW)
        self.assertEqual(self.record()['stage'],'starting_source_api')
        self.assertNotIn(['start','old-api'],self.docker.calls)
        self.assertTrue(Path(self.record()['backup']).exists())

    def test_concurrent_env_edit_is_preserved(self):
        self.docker.fail = 'env'
        with self.assertRaisesRegex(tool.ActivationError,'CONCURRENT_ENV_EDIT_PRESERVED'): self.activate()
        self.assertEqual((self.root/'.env').read_bytes(),self.original+b'# concurrent user edit\n')
        self.assertEqual(self.record()['recovery'],'manual_recovery_required')
        self.assertEqual(self.docker.version,2)

    def test_successful_reapply_only_verifies_without_restart(self):
        self.activate()
        self.docker.calls.clear()
        result = self.activate()
        self.assertEqual(result['status'],'already_activated')
        self.assertFalse(result['service_restart_performed'])
        self.assertFalse(any(c[0] in ('up','stop','run','start') for c in self.docker.calls))

    def test_environment_pin_rejects_existing_custom_configuration(self):
        for tail in (b'VMS_CAMERA_IMAGE=other\n',b'COMPOSE_FILE=other\n'):
            with self.assertRaises(tool.ActivationError): tool.pin_environment(self.original+tail,NEW)

    def test_source_probe_uses_only_authenticated_get(self):
        with patch.object(tool,'request',return_value=(404,{'error':{'code':'SOURCE_NOT_FOUND'}},{})) as request:
            tool.verify_source_read('http://local','token')
            args = request.call_args.args
            self.assertEqual(len(args),3)
            self.assertTrue(args[1].startswith('/api/v1/sources/activation-read-'))
        with patch.object(tool,'request',return_value=(401,{'error':{'code':'UNAUTHORIZED'}},{})):
            with self.assertRaises(tool.ActivationError): tool.verify_source_read('http://local','token')


if __name__ == '__main__': unittest.main()
