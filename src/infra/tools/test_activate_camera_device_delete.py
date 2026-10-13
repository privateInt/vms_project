import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import activate_camera_device_delete as tool
from camera_activation import prepare_secrets

ROOT = Path(__file__).resolve().parents[3]
OLD, NEW, DB = ['sha256:'+c*64 for c in 'abc']
COUNTS = {'devices':2,'device_requests':2,'video_sources':2,'stream_profiles':4,'source_requests':2,'device_update_requests':1,'source_update_requests':1,'source_delete_requests':1}

OPENAPI = {'openapi':'3.1.0','info':{'version':tool.TARGET_VERSION},'paths':{
    '/api/v1/devices/{device_id}':{'delete':{'operationId':'deleteDevice'}},
    '/api/v1/sources/{source_id}':{'delete':{'operationId':'deleteSource'}}}}

class FakeDocker:
    def __init__(self, root):
        self.root, self.project, self.redact, self.calls = root, 'vms-project', [], []
        self.version, self.fail, self.clients = 6, None, 0
        self.counts = copy.deepcopy(COUNTS)
        self.fingerprints = {table: format(i,'032x') for i,table in enumerate(tool.FINGERPRINT_TABLES)}
        self.device_delete_count = 0
        self.state = {
            'camera-api':{'id':'old-api','image':OLD,'started_at':'old','running':True,'restarts':0},
            'camera-db':{'id':'db','image':DB,'started_at':'old','running':True,'restarts':0},
            'model-api':{'id':'model','image':'model','started_at':'old','running':True,'restarts':0}}

    def preflight(self): return 'daemon'
    def volume_exists(self): return True
    def snapshot(self): return copy.deepcopy(self.state)

    def database(self):
        names = tool.MIGRATIONS
        return {'database':'vms_camera','postgres_version_num':170011,'other_clients':self.clients,
                'migrations':[{'version':i+1,'name':'migrations/'+name,
                               'checksum':tool.sha(self.root/'src/platform/camera/internal/storage/migrations'/name)}
                              for i,name in enumerate(names[:self.version])],
                'device_delete_table':None if self.version == 6 else 'camera.device_delete_requests',
                'roles':[{'name':n,'superuser':False,'create_database':False,'create_role':False,'replication':False,'bypass_rls':False} for n in ('camera_migrator','camera_runtime')],
                'counts':copy.deepcopy(self.counts),'registry_fingerprint':copy.deepcopy(self.fingerprints),
                'runtime_grants':{**tool.EXPECTED_RUNTIME_GRANTS,'device_deleted_at_update':self.version==7}}

    def run(self, args, **kwargs):
        self.calls.append(args)
        if args[:2] == ['image','inspect']: return args[-1].encode()
        if args[:2] == ['exec','db']:
            if args[-1] == tool.READ_DEVICE_DELETE_COUNT_SQL:return str(self.device_delete_count).encode()
            assert args[-1] == tool.READ_DB_SQL
            return json.dumps(self.database()).encode()
        if args==['inspect','db']:
            return json.dumps([{'State':{'Health':{'Status':'healthy'}},'Mounts':[{'Type':'volume','Name':self.project+'_camera-data','Destination':'/var/lib/postgresql/data'}]}]).encode()
        if args[0]=='inspect' and args[1] in ('old-api','new-api'):
            return json.dumps([{'Mounts':[{'Type':'bind','Source':str(self.root/'var/camera/secrets/runtime-dsn'),'Destination':'/run/secrets/camera_runtime_dsn','RW':False}]}]).encode()
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
                'environment':{'VMS_API_TOKEN':'test-token-must-not-appear-in-receipts',
                               'CAMERA_DATABASE_URL_FILE':'/run/secrets/camera_runtime_dsn'}}}}).encode()
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
            self.version = 7
            if self.fail == 'migration': raise tool.ActivationError('INJECTED_COMMITTED_MIGRATION_FAILURE')
            return b'{"version":7,"applied":1}'
        if args[0] == 'up':
            assert args[-1] == 'camera-api' and '--no-deps' in args and '--no-build' in args
            self.state['camera-api'] = {'id':'new-api','image':NEW,'started_at':'new','running':True,'restarts':0}
            if self.fail == 'startup':
                self.counts['video_sources'] = 1
                raise tool.ActivationError('INJECTED_STARTUP_FAILURE_AFTER_WRITE')
            return b''
        raise AssertionError(args)


class DeviceDeleteActivationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'
        shutil.copytree(ROOT,self.root,ignore=shutil.ignore_patterns('var','build','.env','__pycache__'))
        self.original = ('VMS_API_TOKEN=existing-private-token\nVMS_CAMERA_COMPOSE_FILE=./src/platform/camera/compose.active.yaml\nVMS_CAMERA_IMAGE='+OLD+'\n').encode()
        (self.root/'.env').write_bytes(self.original)
        tool.private_directory(self.root/'var/camera')
        prepare_secrets(self.root,False)
        (self.root/tool.ACCEPTANCE).write_text('{"stage":"completed"}')
        self.native = {key:True for key in (*tool.CHECKS,'isolated_resources_removed')}
        self.native.update({'status':'passed','scope':tool.SCOPE,'schema_version':7,'previous_schema_version':6,'usage_policy':'registry-only-v1','project':tool.PREFIX+'a'*12,
                            'production_services_modified':False,'device_delete_activated':False,
                            'automatic_production_database_restore':False,
                            'checked_revision':tool.checked_manifest(self.root),'recipe_sha256':tool.recipe_fingerprint(self.root),
                            'docker_daemon':'daemon','candidate_image':NEW,'previous_camera_image':OLD,'database_image':DB})
        self.write_receipt()
        self.docker = FakeDocker(self.root)
        self.before = self.docker.snapshot()
        self.state = {'camera_image':OLD,'database_image':DB,'containers':self.before,
                      'endpoint':'http://127.0.0.1:18081','database_bytes':7902899,
                      'checked_revision':self.native['checked_revision'],'docker_daemon':'daemon',
                      'secret_sha256':tool.secret_hashes(self.root),'env_sha256':tool.sha(self.root/'.env'),
                      'step09_acceptance_sha256':tool.sha(self.root/tool.ACCEPTANCE)}

    def write_receipt(self):
        (self.root/tool.REPORT).write_text(json.dumps(self.native))

    def activate(self):
        with contextlib.redirect_stdout(io.StringIO()), \
             patch.object(tool,'inspect_upgrade',return_value=self.state), \
             patch.object(tool,'verify_runtime_grants'), patch.object(tool,'verify_version'), \
             patch.object(tool,'verify_reads'):
            return tool.activate(self.root,self.docker)

    def record(self): return json.loads((self.root/tool.RECEIPT).read_text())

    def test_success_pins_verified_image_and_preserves_non_camera_services(self):
        result = self.activate()
        self.assertEqual(result['status'],'activated')
        self.assertEqual(result['counts_before'],COUNTS)
        self.assertEqual(self.docker.version,7)
        self.assertEqual(self.docker.counts,COUNTS)
        self.assertTrue(tool.unchanged_except_camera(self.before,self.docker.snapshot()))
        self.assertEqual((self.root/'.env').read_bytes(),tool.pin_environment(self.original,OLD,NEW))
        self.assertEqual((Path(result['backup_directory'])/'env.before').read_bytes(),self.original)
        self.assertTrue(Path(result['backup']).read_bytes().startswith(b'PGDMP'))
        self.assertNotIn('existing-private-token',json.dumps(result))
        self.assertFalse(any(c[0] in ('down','build','rm') or '--volumes' in c for c in self.docker.calls))

    def test_stale_or_incomplete_native_receipt_rejected_before_mutation(self):
        for key,value in (('schema_upgrade_verified',False),('docker_daemon','wrong'),('recipe_sha256',{})):
            good = copy.deepcopy(self.native)
            self.native[key] = value
            self.write_receipt()
            with self.assertRaisesRegex(tool.ActivationError,'MATCHING_DEVICE_DELETE_REHEARSAL_REQUIRED'): self.activate()
            self.assertEqual(self.docker.state,self.before)
            self.native = good
        self.assertFalse((self.root/tool.RECEIPT).exists())

    def test_backup_failure_restarts_original_before_migration(self):
        self.docker.fail = 'backup'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertEqual(self.record()['recovery'],'previous_api_restarted_before_migration')
        self.assertEqual(self.docker.version,6)
        self.assertTrue(self.docker.state['camera-api']['running'])
        self.assertEqual((self.root/'.env').read_bytes(),self.original)
        self.assertFalse(any(c[0] == 'run' for c in self.docker.calls))

    def test_unknown_stop_outcome_recovers_same_container(self):
        self.docker.fail = 'stop'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertIn(['start','old-api'],self.docker.calls)
        self.assertEqual(self.docker.version,6)

    def test_other_database_client_blocks_migration(self):
        self.docker.clients = 1
        with self.assertRaisesRegex(tool.ActivationError,'DATABASE_CLIENTS_NOT_QUIESCED'): self.activate()
        self.assertFalse(any(c[0] == 'run' for c in self.docker.calls))
        self.assertTrue(self.docker.state['camera-api']['running'])

    def test_migration_failure_after_commit_never_restarts_old_or_restores(self):
        self.docker.fail = 'migration'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertEqual(self.docker.version,7)
        self.assertFalse(self.docker.state['camera-api']['running'])
        self.assertNotIn(['start','old-api'],self.docker.calls)
        self.assertIn('VMS_CAMERA_IMAGE='+NEW,(self.root/'.env').read_text())
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertTrue(all('--list' in c for c in self.docker.calls if 'pg_restore' in c))
        self.docker.calls.clear()
        with self.assertRaisesRegex(tool.ActivationError,'INCOMPLETE_DEVICE_DELETE_ACTIVATION_REQUIRES_REVIEW'): self.activate()
        self.assertFalse(any(c[0] in ('run','up','stop','start','exec') for c in self.docker.calls))

    def test_startup_failure_preserves_acknowledged_new_data(self):
        self.docker.fail = 'startup'
        with self.assertRaises(tool.ActivationError): self.activate()
        self.assertEqual(self.docker.counts['video_sources'],1)
        self.assertEqual(self.docker.state['camera-api']['image'],NEW)
        self.assertEqual(self.record()['stage'],'starting_device_delete_api')
        self.assertNotIn(['start','old-api'],self.docker.calls)
        self.assertTrue(Path(self.record()['backup']).exists())

    def test_concurrent_env_edit_is_preserved(self):
        self.docker.fail = 'env'
        with self.assertRaisesRegex(tool.ActivationError,'CONCURRENT_ENV_EDIT_PRESERVED'): self.activate()
        self.assertEqual((self.root/'.env').read_bytes(),self.original+b'# concurrent user edit\n')
        self.assertEqual(self.record()['recovery'],'manual_recovery_required')
        self.assertEqual(self.docker.version,6)

    def test_successful_reapply_only_verifies_without_restart(self):
        self.activate()
        self.docker.calls.clear()
        result = self.activate()
        self.assertEqual(result['status'],'already_activated')
        self.assertFalse(result['service_restart_performed'])
        self.assertFalse(any(c[0] in ('up','stop','run','start') for c in self.docker.calls))

    def test_environment_pin_rejects_existing_custom_configuration(self):
        for tail in (b'VMS_CAMERA_IMAGE=other\n',b'COMPOSE_FILE=other\n'):
            with self.assertRaises(tool.ActivationError): tool.pin_environment(self.original+tail,OLD,NEW)

    def test_read_probe_uses_only_get_and_checks_source_limit(self):
        import test_camera_device_delete_upgrade as rehearsal
        with patch.object(tool,'verify_version') as version, patch.object(rehearsal,'request',return_value=(200,{'items':[],'next_cursor':None},{})) as get, \
             patch.object(tool,'request',side_effect=[(200,{'items':[],'next_cursor':None},{}),(200,OPENAPI,{})]) as direct:
            tool.verify_reads('http://local','token')
            version.assert_called_once_with('http://local','token',tool.TARGET_VERSION)
            self.assertEqual(get.call_args.args,('http://local','/api/v1/sources?limit=1','token'))
            self.assertTrue(all(len(call.args)<=3 for call in direct.call_args_list))
            self.assertEqual(direct.call_args_list[-1].args,('http://local','/openapi.json'))
        with patch.object(tool,'verify_version'),patch.object(tool,'get_source_list',return_value={'items':[{},{}]}):
            with self.assertRaisesRegex(tool.ActivationError,'SOURCE_LIST_LIMIT_NOT_APPLIED'):tool.verify_reads('http://local','token')

    def test_pin_preserves_all_other_environment_bytes(self):
        value=self.original.replace(b'\n',b'\r\n')+b'# retain this\r\n'
        self.assertEqual(tool.pin_environment(value,OLD,NEW),value.replace(OLD.encode(),NEW.encode()))
        for value in (self.original.replace(OLD.encode(),DB.encode()),self.original+b'export VMS_CAMERA_IMAGE='+OLD.encode()+b'\n'):
            with self.assertRaises(tool.ActivationError):tool.pin_environment(value,OLD,NEW)

    def test_missing_image_or_changed_live_state_stops_before_stop(self):
        original_run=self.docker.run
        with patch.object(self.docker,'run',side_effect=lambda args,**kw: b'missing' if args[:2]==['image','inspect'] else original_run(args,**kw)):
            with self.assertRaisesRegex(tool.ActivationError,'REHEARSED_IMAGE_UNAVAILABLE'):self.activate()
        self.state['database_image']=OLD
        with self.assertRaisesRegex(tool.ActivationError,'LIVE_STATE_DIFFERS_FROM_REHEARSAL'):self.activate()
        self.assertFalse(any(c[0]=='stop' for c in self.docker.calls))

    def test_configuration_changes_other_than_image_are_rejected(self):
        original_compose=self.docker.compose
        def changed(args,**kwargs):
            data=original_compose(args,**kwargs)
            if args[0]=='config' and kwargs.get('image'):
                config=json.loads(data);config['services']['camera-api']['environment']['VMS_API_TOKEN']='changed'
                return json.dumps(config).encode()
            return data
        with patch.object(self.docker,'compose',side_effect=changed):
            with self.assertRaisesRegex(tool.ActivationError,'CANDIDATE_CONFIGURATION_CHANGED'):self.activate()
        self.assertFalse(any(c[0]=='stop' for c in self.docker.calls))

    def test_backup_count_drift_prevents_migration(self):
        original_compose=self.docker.compose
        def drift(args,**kwargs):
            result=original_compose(args,**kwargs)
            if 'pg_dump' in args:self.docker.counts['devices']+=1
            return result
        with patch.object(self.docker,'compose',side_effect=drift):
            with self.assertRaisesRegex(tool.ActivationError,'DATA_CHANGED_DURING_BACKUP'):self.activate()
        self.assertFalse(any(c[0]=='run' for c in self.docker.calls))
        self.assertEqual(self.docker.version,6)

    def test_schema_corruption_and_elevated_role_are_rejected(self):
        data=self.docker.database()
        data['migrations'][0]['checksum']='bad'
        with self.assertRaisesRegex(tool.ActivationError,'DATABASE_SCHEMA_CHANGED'):tool.check_schema(self.root,data,6)
        data=self.docker.database();data['device_delete_table']='camera.device_delete_requests'
        with self.assertRaisesRegex(tool.ActivationError,'DEVICE_DELETE_TABLE_MISMATCH'):tool.check_schema(self.root,data,6)
        data=self.docker.database();data['roles'][0]['superuser']=True
        with self.assertRaisesRegex(tool.ActivationError,'DATABASE_ROLE_CONFIGURATION_CHANGED'):tool.check_schema(self.root,data,6)

    def test_rehearsal_receipt_edit_is_preserved_and_blocks_migration(self):
        original_compose=self.docker.compose
        def changed(args,**kwargs):
            result=original_compose(args,**kwargs)
            if 'pg_dump' in args:(self.root/tool.REPORT).write_text('{"status":"changed"}')
            return result
        with patch.object(self.docker,'compose',side_effect=changed):
            with self.assertRaisesRegex(tool.ActivationError,'PROJECT_OR_RECEIPT_CHANGED'):self.activate()
        self.assertFalse(any(c[0]=='run' for c in self.docker.calls))
        self.assertEqual(json.loads((self.root/tool.REPORT).read_text()),{'status':'changed'})
        self.assertEqual(self.record()['recovery'],'manual_recovery_required')

    def test_non_camera_container_change_blocks_migration(self):
        original_compose=self.docker.compose
        def changed(args,**kwargs):
            result=original_compose(args,**kwargs)
            if 'pg_dump' in args:self.docker.state['model-api']['id']='external-recreate'
            return result
        with patch.object(self.docker,'compose',side_effect=changed):
            with self.assertRaisesRegex(tool.ActivationError,'NON_CAMERA_CONTAINERS_CHANGED'):self.activate()
        self.assertFalse(any(c[0]=='run' for c in self.docker.calls))
        self.assertEqual(self.docker.state['model-api']['id'],'external-recreate')

    def test_migration_interrupt_preserves_candidate_pin_and_records_failure(self):
        original_compose=self.docker.compose
        def interrupted(args,**kwargs):
            result=original_compose(args,**kwargs)
            if args[0]=='run':raise KeyboardInterrupt()
            return result
        with patch.object(self.docker,'compose',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):self.activate()
        self.assertEqual(self.docker.version,7)
        self.assertEqual(self.record()['status'],'failed')
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertNotIn(['start','old-api'],self.docker.calls)
        self.assertTrue(all('--list' in c for c in self.docker.calls if 'pg_restore' in c))

    def test_completion_requires_matching_stage_schema_and_receipt(self):
        self.activate();record=self.record()
        for key,value in (('stage','migration_requested'),('schema_version',6),('receipt_sha256','wrong')):
            (self.root/tool.RECEIPT).write_text(json.dumps({**record,key:value}))
            self.docker.calls.clear()
            with self.assertRaises(tool.ActivationError):self.activate()
            self.assertFalse(any(c[0] in ('up','stop','run','start') for c in self.docker.calls))

    def test_insufficient_backup_space_is_checked_before_stop(self):
        with patch.object(tool.shutil,'disk_usage',return_value=type('Usage',(),{'free':0})()):
            with self.assertRaisesRegex(tool.ActivationError,'INSUFFICIENT_BACKUP_SPACE'):self.activate()
        self.assertFalse(any(c[0]=='stop' for c in self.docker.calls))

    def test_private_records_and_backup_modes(self):
        result=self.activate()
        for path in (self.root/tool.RECEIPT,Path(result['backup']),Path(result['backup_directory'])/'result.json',Path(result['backup_directory'])/'env.before'):
            self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertEqual(Path(result['backup_directory']).stat().st_mode&0o777,0o700)

    def test_main_requires_explicit_apply_and_sanitizes_errors(self):
        with patch.object(tool.sys,'argv',['activate']),patch.object(tool,'Docker') as docker,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool.main(),2);docker.assert_not_called()
        with patch.object(tool.sys,'argv',['activate','--apply']),patch.object(tool,'activation_lock',return_value=contextlib.nullcontext()), \
             patch.object(tool,'activate',side_effect=tool.ActivationError('FAILED: secret-must-not-leak')),contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(tool.main(),1)
        self.assertNotIn('secret-must-not-leak',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['code'],'FAILED')

    def test_all_replay_and_schema6_restore_receipts_are_required(self):
        for key in ('source_delete_replay_verified','source_update_replay_verified','device_update_replay_verified','deletion_rows_preserved','registry_only_policy_verified','schema_6_restore_verified','device_delete_replay_verified','active_children_rejection_verified'):
            with self.subTest(key=key):
                self.native[key]=False;self.write_receipt()
                with self.assertRaisesRegex(tool.ActivationError,'MATCHING_DEVICE_DELETE_REHEARSAL_REQUIRED'):
                    self.activate()
                self.assertEqual(self.docker.snapshot(),self.before)
                self.assertFalse(any(c[0] in ('stop','run','up','start') for c in self.docker.calls))
                self.native[key]=True
        self.assertFalse((self.root/tool.RECEIPT).exists())

    def test_device_update_history_loss_blocks_start_and_preserves_candidate_state(self):
        original_compose=self.docker.compose
        def lost_history(args,**kwargs):
            result=original_compose(args,**kwargs)
            if args[0]=='run':self.docker.counts['device_update_requests']=0
            return result
        with patch.object(self.docker,'compose',side_effect=lost_history):
            with self.assertRaisesRegex(tool.ActivationError,'DATA_COUNTS_CHANGED_DURING_MIGRATION'):
                self.activate()
        self.assertEqual(self.docker.version,7)
        self.assertEqual(self.record()['counts_before']['device_update_requests'],1)
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertFalse(any(c[0] in ('up','start') for c in self.docker.calls))
        self.assertTrue(all('--list' in c for c in self.docker.calls if 'pg_restore' in c))


    def test_rehearsal_policy_and_all_deletion_evidence_are_required(self):
        for key,value in [('usage_policy',None),('usage_policy','registry-only-v2'),
                          ('device_delete_activated',True),('production_services_modified',True),
                          ('automatic_production_database_restore',True),('schema_version',6),
                          ('deletion_rows_preserved',False),('registry_only_policy_verified',False),
                          ('isolated_resources_removed',False)]:
            with self.subTest(key=key,value=value):
                good=copy.deepcopy(self.native);self.native[key]=value;self.write_receipt()
                with self.assertRaisesRegex(tool.ActivationError,'MATCHING_DEVICE_DELETE_REHEARSAL_REQUIRED'):self.activate()
                self.assertEqual(self.docker.snapshot(),self.before)
                self.assertFalse(any(call[0] in ('up','stop','start','run') for call in self.docker.calls))
                self.native=good
        self.assertFalse((self.root/tool.RECEIPT).exists())

    def test_schema6_source_update_history_loss_blocks_schema7_api_start(self):
        original_compose=self.docker.compose
        def lost_history(args,**kwargs):
            result=original_compose(args,**kwargs)
            if args[0]=='run':self.docker.counts['source_update_requests']=0
            return result
        with patch.object(self.docker,'compose',side_effect=lost_history):
            with self.assertRaisesRegex(tool.ActivationError,'DATA_COUNTS_CHANGED_DURING_MIGRATION'):self.activate()
        self.assertEqual(self.record()['counts_before']['source_update_requests'],1)
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertEqual(self.docker.version,7)
        self.assertFalse(any(call[0] in ('up','start') for call in self.docker.calls))

    def test_activation_read_sql_includes_old_source_updates_and_all_clients(self):
        self.assertTrue(tool.READ_DB_SQL.startswith('BEGIN READ ONLY;'))
        self.assertIn("'source_update_requests',(SELECT count(*) FROM camera.source_update_requests)",tool.READ_DB_SQL)
        self.assertIn("'device_delete_table',to_regclass('camera.device_delete_requests')::text",tool.READ_DB_SQL)
        self.assertIn("'other_clients'",tool.READ_DB_SQL)
        self.assertNotIn("usename<>'camera_runtime'",tool.READ_DB_SQL)
        self.assertNotIn('FROM camera.device_delete_requests',tool.READ_DB_SQL)
        for name in ('source_update_requests','device_update_requests'):
            data=self.docker.database();del data['counts'][name]
            with self.assertRaisesRegex(tool.ActivationError,'DATABASE_COUNTS_INVALID'):tool.check_schema(self.root,data,6)
        data=self.docker.database();data['other_clients']=1
        with self.assertRaisesRegex(tool.ActivationError,'DATABASE_CLIENTS_NOT_QUIESCED'):
            tool.check_schema(self.root,data,6,quiescent=True)

    def test_completed_policy_mismatch_never_restarts(self):
        self.activate();record=self.record()
        for value in (None,'runtime','registry-only-v2'):
            (self.root/tool.RECEIPT).write_text(json.dumps({**record,'usage_policy':value}))
            self.docker.calls.clear()
            with self.assertRaisesRegex(tool.ActivationError,'ACTIVATION_RECEIPT_MISMATCH'):self.activate()
            self.assertFalse(any(call[0] in ('up','stop','start','run') for call in self.docker.calls))

    def test_real_read_verifier_requires_exact_registry_only_capabilities(self):
        import test_camera_device_delete_upgrade as rehearsal
        capabilities={**rehearsal.OLD_CAPABILITIES,'device_delete':'implemented'}
        value={'version':tool.TARGET_VERSION,'stage':'P1_DEVICE_DELETE','capabilities':capabilities}
        with patch.object(rehearsal,'verify_api'),patch.object(rehearsal,'request',side_effect=[
            (200,value,{}),(200,{'items':[],'next_cursor':None},{})]) as request, \
             patch.object(tool,'request',side_effect=[(200,{'items':[],'next_cursor':None},{}),(200,OPENAPI,{})]):
            tool.verify_reads('http://local','token')
            self.assertTrue(all(len(call.args)==3 for call in request.call_args_list))
        for key in ('device_delete','source_delete','source_sessions','source_consumers','recording'):
            changed={**value,'capabilities':{**capabilities,key:'unexpected'}}
            with patch.object(rehearsal,'verify_api'),patch.object(rehearsal,'request',return_value=(200,changed,{})):
                with self.assertRaisesRegex(tool.ActivationError,'API_VERSION_OR_CAPABILITY_MISMATCH'):
                    tool.verify_reads('http://local','token')

    def test_read_acceptance_failure_keeps_candidate_and_never_restores_database(self):
        with contextlib.redirect_stdout(io.StringIO()),patch.object(tool,'inspect_upgrade',return_value=self.state), \
             patch.object(tool,'verify_runtime_grants'),patch.object(tool,'verify_version'), \
             patch.object(tool,'verify_reads',side_effect=tool.ActivationError('API_VERSION_OR_CAPABILITY_MISMATCH')):
            with self.assertRaises(tool.ActivationError):tool.activate(self.root,self.docker)
        self.assertEqual(self.docker.version,7)
        self.assertEqual(self.docker.state['camera-api']['image'],NEW)
        self.assertEqual(self.record()['status'],'failed')
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertFalse(self.record()['database_restore_performed'])
        self.assertNotIn(['start','old-api'],self.docker.calls)
        self.assertTrue(all('--list' in call for call in self.docker.calls if 'pg_restore' in call))

    def test_all_seventeen_rehearsal_checks_and_previous_schema_are_required(self):
        for key,value in [(key,False) for key in tool.CHECKS]+[('previous_schema_version',7)]:
            good=copy.deepcopy(self.native);self.native[key]=value;self.write_receipt()
            with self.subTest(key=key),self.assertRaisesRegex(tool.ActivationError,'MATCHING_DEVICE_DELETE_REHEARSAL_REQUIRED'):self.activate()
            self.assertFalse(any(call[0] in ('up','stop','run','start') for call in self.docker.calls));self.native=good
        self.assertFalse((self.root/tool.RECEIPT).exists())

    def test_same_count_row_change_during_backup_blocks_migration(self):
        original=self.docker.compose
        def changed(args,**kwargs):
            value=original(args,**kwargs)
            if 'pg_dump' in args:self.docker.fingerprints['source_delete_requests']='f'*32
            return value
        with patch.object(self.docker,'compose',side_effect=changed),self.assertRaisesRegex(tool.ActivationError,'ROWS_CHANGED_DURING_BACKUP'):self.activate()
        self.assertEqual(self.record()['recovery'],'previous_api_restarted_before_migration')
        self.assertFalse(any(call[0]=='run' for call in self.docker.calls));self.assertEqual(self.docker.counts,COUNTS)

    def test_same_count_row_change_during_migration_preserves_candidate(self):
        original=self.docker.compose
        def changed(args,**kwargs):
            value=original(args,**kwargs)
            if args[0]=='run':self.docker.fingerprints['stream_profiles']='f'*32
            return value
        with patch.object(self.docker,'compose',side_effect=changed),self.assertRaisesRegex(tool.ActivationError,'ROWS_CHANGED_DURING_MIGRATION'):self.activate()
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertFalse(any(call[0] in ('up','start') for call in self.docker.calls));self.assertEqual(self.docker.counts,COUNTS)

    def test_schema6_source_delete_history_loss_blocks_candidate_start(self):
        original=self.docker.compose
        def changed(args,**kwargs):
            value=original(args,**kwargs)
            if args[0]=='run':self.docker.counts['source_delete_requests']=0
            return value
        with patch.object(self.docker,'compose',side_effect=changed),self.assertRaisesRegex(tool.ActivationError,'DATA_COUNTS_CHANGED_DURING_MIGRATION'):self.activate()
        self.assertEqual(self.record()['counts_before']['source_delete_requests'],1)
        self.assertFalse(any(call[0] in ('up','start') for call in self.docker.calls))

    def test_new_delete_journal_must_be_empty_before_candidate_start(self):
        original=self.docker.compose
        def changed(args,**kwargs):
            value=original(args,**kwargs)
            if args[0]=='run':self.docker.device_delete_count=1
            return value
        with patch.object(self.docker,'compose',side_effect=changed),self.assertRaisesRegex(tool.ActivationError,'NEW_DEVICE_DELETE_JOURNAL_NOT_EMPTY'):self.activate()
        self.assertFalse(any(call[0] in ('up','start') for call in self.docker.calls))

    def test_schema_roles_grants_fingerprints_and_quiescence_use_strict_types(self):
        mutations=[('roles',[{**row,'bypass_rls':True} for row in self.docker.database()['roles']]),
                   ('roles',[{**row,'replication':True} for row in self.docker.database()['roles']]),
                   ('runtime_grants',{**tool.EXPECTED_RUNTIME_GRANTS,'device_deleted_at_update':True}),
                   ('runtime_grants',{**tool.EXPECTED_RUNTIME_GRANTS,'schema_usage':1}),
                   ('registry_fingerprint',{}),('registry_fingerprint',{**self.docker.fingerprints,'devices':'invalid'}),
                   ('other_clients',False)]
        for field,value in mutations:
            data=self.docker.database();data[field]=value
            with self.subTest(field=field),self.assertRaises(tool.ActivationError):tool.check_schema(self.root,data,6,quiescent=True)
        for value in (True,-1,'0',None):
            with patch.object(self.docker,'run',return_value=json.dumps(value).encode()),self.assertRaisesRegex(tool.ActivationError,'DEVICE_DELETE_COUNT_INVALID'):
                tool.read_device_delete_count(self.docker,'db')

    def test_running_openapi_and_device_list_must_match_verified_release(self):
        specs=[{**OPENAPI,'info':{'version':tool.OLD_VERSION}},
               {**OPENAPI,'paths':{**OPENAPI['paths'],'/api/v1/devices/{device_id}':{}}},
               {**OPENAPI,'paths':{**OPENAPI['paths'],'/api/v1/sources/{source_id}':{}}}]
        for spec in specs:
            with patch.object(tool,'verify_version'),patch.object(tool,'get_source_list',return_value={'items':[]}), \
                 patch.object(tool,'request',side_effect=[(200,{'items':[],'next_cursor':None},{}),(200,spec,{})]), \
                 self.assertRaisesRegex(tool.ActivationError,'DEVICE_DELETE_RUNNING_OPENAPI_MISMATCH'):tool.verify_reads('base','token')
        with patch.object(tool,'verify_version'),patch.object(tool,'get_source_list',return_value={'items':[]}), \
             patch.object(tool,'request',return_value=(200,{'items':[{},{}],'next_cursor':None},{})), \
             self.assertRaisesRegex(tool.ActivationError,'DEVICE_LIST_READ_FAILED'):tool.verify_reads('base','token')

    def test_completed_tool_change_blocks_reapply_without_writes(self):
        self.activate();self.docker.calls.clear()
        script=self.root/'src/infra/tools/activate_camera_device_delete.py';script.write_text(script.read_text()+'\n# concurrent edit\n')
        with self.assertRaisesRegex(tool.ActivationError,'ACTIVATION_TOOL_CHANGED'):self.activate()
        self.assertFalse(any(call[0] in ('up','stop','run','start') for call in self.docker.calls))

    def test_completed_reapply_accepts_legitimate_post_activation_writes(self):
        self.activate();self.docker.calls.clear();self.docker.counts['devices']+=1
        self.docker.device_delete_count=2;self.docker.fingerprints['devices']='f'*32
        result=self.activate();self.assertEqual(result['status'],'already_activated')
        self.assertEqual(self.docker.device_delete_count,2)
        self.assertFalse(any(call[0] in ('up','stop','run','start') for call in self.docker.calls))

    def test_previous_activation_record_edit_is_preserved(self):
        original=self.docker.compose
        def changed(args,**kwargs):
            value=original(args,**kwargs)
            if 'pg_dump' in args:(self.root/tool.ACCEPTANCE).write_text('{"status":"user-edited"}')
            return value
        with patch.object(self.docker,'compose',side_effect=changed),self.assertRaisesRegex(tool.ActivationError,'PROJECT_OR_RECEIPT_CHANGED'):self.activate()
        self.assertEqual(json.loads((self.root/tool.ACCEPTANCE).read_text()),{'status':'user-edited'})
        self.assertFalse(any(call[0] in ('run','up','start') for call in self.docker.calls))

    def test_public_success_output_excludes_private_row_fingerprints(self):
        result=self.activate()
        with patch.object(tool.sys,'argv',['activate','--apply']),patch.object(tool,'activation_lock',return_value=contextlib.nullcontext()), \
             patch.object(tool,'activate',return_value=result),contextlib.redirect_stdout(io.StringIO()) as output:self.assertEqual(tool.main(),0)
        public=json.loads(output.getvalue());self.assertNotIn('registry_fingerprint_before',public)
        self.assertTrue(public['existing_rows_preserved']);self.assertTrue(public['new_device_delete_journal_empty_at_cutover'])
        self.assertFalse(any(value in output.getvalue() for value in self.docker.fingerprints.values()))

    def test_backup_tamper_after_hash_blocks_migration(self):
        original=self.docker.run;reads=0
        def changed(args,**kwargs):
            nonlocal reads
            value=original(args,**kwargs)
            if args[:2]==['exec','db'] and args[-1]==tool.READ_DB_SQL:
                reads+=1
                if reads==2:
                    backup=next((self.root/'var/camera/device-delete-activation-backups').glob('*/camera.pgdump'))
                    backup.write_bytes(b'PGDMP-changed')
            return value
        with patch.object(self.docker,'run',side_effect=changed),self.assertRaisesRegex(tool.ActivationError,'BACKUP_CHANGED_BEFORE_MIGRATION'):self.activate()
        self.assertFalse(any(call[0]=='run' for call in self.docker.calls))
        self.assertEqual(self.record()['recovery'],'previous_api_restarted_before_migration')

    def test_completed_database_volume_and_secret_mount_drift_are_rejected(self):
        self.activate();original=self.docker.run
        for changed_id in ('db','new-api'):
            def changed(args,**kwargs):
                value=original(args,**kwargs)
                if args==['inspect',changed_id]:
                    data=json.loads(value);data[0]['Mounts']=[];return json.dumps(data).encode()
                return value
            self.docker.calls.clear()
            with patch.object(self.docker,'run',side_effect=changed),self.assertRaises(tool.ActivationError):self.activate()
            self.assertFalse(any(call[0] in ('up','stop','run','start') for call in self.docker.calls))

    def test_candidate_secret_mount_failure_retains_new_state(self):
        original=self.docker.run
        def changed(args,**kwargs):
            value=original(args,**kwargs)
            if args==['inspect','new-api']:
                data=json.loads(value);data[0]['Mounts'][0]['RW']=True;return json.dumps(data).encode()
            return value
        with patch.object(self.docker,'run',side_effect=changed),self.assertRaisesRegex(tool.ActivationError,'RUNNING_CAMERA_SECRET_MOUNT_MISMATCH'):self.activate()
        self.assertEqual(self.record()['recovery'],'candidate_state_retained_manual_recovery_required')
        self.assertNotIn(['start','old-api'],self.docker.calls)


if __name__ == '__main__':unittest.main(verbosity=2)
