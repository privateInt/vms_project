import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_camera_device_delete_upgrade as tool

ROOT = Path(__file__).resolve().parents[3]
PROJECT = tool.PREFIX+'a'*12
IMAGE = 'sha256:'+'a'*64
STATE = {'camera_image':IMAGE, 'database_image':'sha256:'+'b'*64, 'docker_daemon':'test-daemon', 'checked_revision':tool.checked_manifest(ROOT)}


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
    def run(self, args, **kwargs): return b''

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
            (root/'device-delete-test-project').write_text('other-project')
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
            def compose(self, *args, **kwargs): return b'{"version":5,"applied":1}'
        tool.migrate(MigrationDocker(), IMAGE, 5, 1)
        for version, applied in ((4,1),(5,0)):
            with self.assertRaisesRegex(tool.ActivationError, 'UNEXPECTED_MIGRATION_RESULT'):
                tool.migrate(MigrationDocker(), IMAGE, version, applied)

    def test_workspace_rejects_changed_revision_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'project'
            with self.assertRaisesRegex(tool.ActivationError,'PROJECT_REVISION_CHANGED'):
                tool.configure_workspace(ROOT,root,{**STATE,'checked_revision':'stale'},PROJECT)
            self.assertFalse(root.exists())

    def test_network_collision_is_not_cleaned(self):
        class NetworkCollision(FakeDocker):
            def run(self,*args,**kwargs):return b'existing-network'
        with patch.object(tool,'RehearsalDocker',NetworkCollision):
            with self.assertRaisesRegex(tool.ActivationError,'ISOLATED_PROJECT_ALREADY_EXISTS'):
                with tool.isolated_environment(ROOT,STATE,PROJECT):self.fail('must not yield')
        self.assertEqual(FakeDocker.instances[0].calls,[])

    def test_leftover_resources_fail_cleanup_and_retain_workspace(self):
        class Leftover(FakeDocker):
            def snapshot(self):return {'leftover':{}} if self.calls else {}
        root=None
        try:
            with patch.object(tool,'RehearsalDocker',Leftover),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(tool.ActivationError,'ISOLATED_RESOURCES_REMAIN'):
                    with tool.isolated_environment(ROOT,STATE,PROJECT) as (root,*_):pass
            self.assertTrue(root.exists())
        finally:
            if root:tool.shutil.rmtree(root.parent)

    def test_keyboard_interrupt_cleans_isolated_project(self):
        with patch.object(tool,'RehearsalDocker',FakeDocker):
            with self.assertRaises(KeyboardInterrupt):
                with tool.isolated_environment(ROOT,STATE,PROJECT) as (root,docker,*_):raise KeyboardInterrupt()
        self.assertEqual(len(docker.calls),1);self.assertFalse(root.parent.exists())

    def test_daemon_mismatch_does_not_clean_an_existing_project(self):
        with patch.object(tool,'RehearsalDocker',FakeDocker):
            with self.assertRaisesRegex(tool.ActivationError,'DOCKER_DAEMON_CHANGED'):
                with tool.isolated_environment(ROOT,{**STATE,'docker_daemon':'other'},PROJECT):self.fail('must not yield')
        self.assertEqual(FakeDocker.instances[0].calls,[])

    def test_schema_validation_checks_all_hashes_and_both_delete_tables(self):
        names=('0001_registry.sql','0002_device_idempotency.sql','0003_source_idempotency.sql',
               '0004_device_update.sql','0005_source_update.sql','0006_source_delete.sql','0007_device_delete.sql')
        def state(version):
            return {'migrations':[{'version':i,'name':'migrations/'+name,
                'checksum':tool.sha(ROOT/'src/platform/camera/internal/storage/migrations'/name)}
                for i,name in enumerate(names[:version],1)], 'has_update_table':True,
                'has_device_update_table':True,'has_delete_table':True,'has_device_delete_table':version==7}
        for version in (6,7):
            value=state(version)
            with patch.object(tool,'sql',return_value=json.dumps(value)):tool.check_schema(ROOT,object(),version)
            for field in ('has_delete_table','has_device_delete_table'):
                changed={**value,field:not value[field]}
                with patch.object(tool,'sql',return_value=json.dumps(changed)),self.assertRaises(tool.ActivationError):
                    tool.check_schema(ROOT,object(),version)
            value['migrations'][-1]['checksum']='wrong'
            with patch.object(tool,'sql',return_value=json.dumps(value)),self.assertRaisesRegex(tool.ActivationError,'ISOLATED_SCHEMA_MISMATCH'):
                tool.check_schema(ROOT,object(),version)
        for version in (5,8):
            with patch.object(tool,'sql') as query,self.assertRaises(tool.ActivationError):tool.check_schema(ROOT,object(),version)
            query.assert_not_called()

    def test_runtime_grants_do_not_accept_missing_permissions(self):
        roles='camera_migrator|f|f|f|f|f\ncamera_runtime|f|f|f|f|f'
        with patch.object(tool,'sql',side_effect=['t',roles]):tool.verify_runtime_grants(object())
        with patch.object(tool,'sql',return_value='f'),self.assertRaisesRegex(tool.ActivationError,'RUNTIME_GRANTS_INCORRECT'):tool.verify_runtime_grants(object())
        with patch.object(tool,'sql',side_effect=['t','camera_runtime|t|f|f']),self.assertRaisesRegex(tool.ActivationError,'ROLE_PRIVILEGES_INCORRECT'):tool.verify_runtime_grants(object())

    def test_patch_response_requires_exact_snapshot_and_metadata(self):
        device={'device_id':'upgrade-test','version':2}
        good=(200,{'device':device,'request_id':'req'}, {'Idempotency-Replayed':'true','X-Request-ID':'req'})
        with patch.object(tool,'patch_request',return_value=good):
            self.assertEqual(tool.patch_device('http://test','token',{},'key',True,device),device)
        for bad in ((201,*good[1:]),(200,good[1],{'Idempotency-Replayed':'false','X-Request-ID':'req'}),
                    (200,good[1],{**good[2],'Location':'/new'}),
                    (200,{'device':{'version':3},'request_id':'req'},good[2])):
            with patch.object(tool,'patch_request',return_value=bad),self.assertRaises(tool.ActivationError):
                tool.patch_device('http://test','token',{},'key',True,device)

    def test_conflict_must_be_the_expected_code(self):
        with patch.object(tool,'patch_request',return_value=(409,{'error':{'code':'SOURCE_VERSION_CONFLICT'}},{})):
            tool.expect_update_conflict('http://test','token',{},'key','SOURCE_VERSION_CONFLICT')
            with self.assertRaises(tool.ActivationError):tool.expect_update_conflict('http://test','token',{},'key','IDEMPOTENCY_CONFLICT')

    def test_post_snapshot_is_distinct_from_current_device(self):
        old={'version':1};current={'version':3}
        responses=[(200,{'device':current},{}),
                   (201,{'device':old},{'Idempotency-Replayed':'true'})]
        with patch.object(tool,'request',side_effect=responses):tool.verify_updated_device('http://test','token',current,old)
        responses[-1]=(201,{'device':current},{'Idempotency-Replayed':'true'})
        with patch.object(tool,'request',side_effect=responses),self.assertRaisesRegex(tool.ActivationError,'DEVICE_CREATE_REPLAY_CHANGED'):
            tool.verify_updated_device('http://test','token',current,old)

    def test_failed_run_and_interrupt_invalidate_old_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'var/camera').mkdir(parents=True,mode=0o700);receipt=root/tool.REPORT
            for error in (tool.ActivationError('FAILED: never-log-secret'),KeyboardInterrupt()):
                receipt.write_text('{"status":"passed"}')
                with patch.object(tool,'run_check',side_effect=error),self.assertRaises(type(error)):tool.execute(root,PROJECT)
                self.assertEqual(json.loads(receipt.read_text())['status'],'failed');self.assertNotIn('never-log-secret',receipt.read_text())
                self.assertEqual(receipt.stat().st_mode&0o777,0o600)

    def test_main_reports_only_error_code(self):
        with patch.object(tool,'execute',side_effect=tool.ActivationError('FAILED: never-log-secret')), \
             patch.object(tool.sys,'argv',['check']),contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(tool.main(),1)
        self.assertNotIn('never-log-secret',output.getvalue());self.assertEqual(json.loads(output.getvalue())['code'],'FAILED')

    def test_stable_production_is_required_but_data_counts_may_change(self):
        state={**STATE,'inspector_sha256':'recipe','containers':{'camera-api':{'id':'original'}},
               'env_sha256':'env','secret_sha256':{'runtime':'secret-hash'},'step09_acceptance_sha256':'accepted','counts':{'devices':0}}
        result={'candidate_image':'sha256:'+'c'*64,'schema_version':7,**{name:True for name in tool.CHECKS}}
        with patch.object(tool,'recipe_fingerprint',return_value='recipe'),patch.object(tool,'rehearse',return_value=result),contextlib.redirect_stdout(io.StringIO()):
            after={**state,'counts':{'devices':1}}
            with patch.object(tool,'inspect_upgrade',side_effect=[state,after]):
                passed=tool.run_check(ROOT,object(),PROJECT)
                self.assertEqual(passed['status'],'passed');self.assertFalse(passed['production_services_modified'])
            for key in ('containers','secret_sha256','checked_revision','step09_acceptance_sha256'):
                after={**state,key:'changed'}
                with patch.object(tool,'inspect_upgrade',side_effect=[state,after]),self.assertRaisesRegex(tool.ActivationError,'PRODUCTION_OR_RECIPE_CHANGED'):
                    tool.run_check(ROOT,object(),PROJECT)
            result[tool.CHECKS[0]]=False
            with patch.object(tool,'inspect_upgrade',side_effect=[state,state]),self.assertRaisesRegex(tool.ActivationError,'REHEARSAL_INCOMPLETE'):
                tool.run_check(ROOT,object(),PROJECT)

    def test_production_handle_cannot_start_or_restore(self):
        live=tool.InspectionDocker(ROOT)
        with patch.object(tool.Docker,'run') as run:
            for args in (['up','-d','camera-api'],['down','--volumes'],['run','--rm','camera-migrate'],
                         ['exec','-T','camera-db','pg_restore','-d','vms_camera']):
                with self.assertRaisesRegex(tool.ActivationError,'PRODUCTION_COMPOSE_WRITE_REJECTED'):live.compose(args)
            run.assert_not_called()

    def test_source_patch_requires_historical_snapshot_and_metadata(self):
        source={'source_id':'upgrade-source','version':2,'profiles':[{'profile_id':'main'}]}
        good=(200,{'source':source,'request_id':'req'}, {'Idempotency-Replayed':'true','X-Request-ID':'req'})
        with patch.object(tool,'patch_request',return_value=good):
            self.assertEqual(tool.patch_source('http://test','token',{},'key',True,source),source)
        invalid=[(201,*good[1:]),
                 (200,good[1],{'Idempotency-Replayed':'false','X-Request-ID':'req'}),
                 (200,good[1],{**good[2],'Location':'/new'}),
                 (200,good[1],{**good[2],'X-Request-ID':'different'}),
                 (200,{'source':{**source,'profiles':[]},'request_id':'req'},good[2]),
                 (200,{'source':{**source,'version':3},'request_id':'req'},good[2])]
        for bad in invalid:
            with patch.object(tool,'patch_request',return_value=bad),self.assertRaises(tool.ActivationError):
                tool.patch_source('http://test','token',{},'key',True,source)

    def test_rename_preserves_all_immutable_fields_and_ordered_profiles(self):
        before={'source_id':'source','device_id':'parent','channel_key':'ch1',
                'transport':'RTSP','input_mode':'PULL','motion_mode':'FIXED',
                'primary_profile_id':'main','profiles':[{'profile_id':'main'},{'profile_id':'sub'}],
                'version':1,'display_name':'before','created_at':'2026-10-01T00:00:00Z',
                'updated_at':'2026-10-01T00:00:00Z'}
        body={'expected_version':1,'display_name':'after'}
        after={**before,'version':2,'display_name':'after'}
        tool.verify_rename(before,after,body)
        for name in ('source_id','device_id','channel_key','transport','input_mode','motion_mode',
                     'primary_profile_id','created_at','version','display_name'):
            with self.subTest(name=name),self.assertRaises(tool.ActivationError):
                tool.verify_rename(before,{**after,name:'wrong'},body)
        for changed in ({**after,'profiles':list(reversed(after['profiles']))},
                        {**after,'updated_at':'2026-09-30T23:59:59Z'},
                        {key:value for key,value in after.items() if key!='profiles'}):
            with self.assertRaises(tool.ActivationError):tool.verify_rename(before,changed,body)

    def test_source_post_replay_does_not_return_latest_patch_state(self):
        original={'version':1};current={'version':3}
        good=[(200,{'source':current},{}),
              (201,{'source':original},{'Idempotency-Replayed':'true'})]
        with patch.object(tool,'request',side_effect=good):
            tool.verify_updated_source('http://test','token',current,original)
        for bad in ([(200,{'source':original},{}),good[1]],
                    [good[0],(201,{'source':current},{'Idempotency-Replayed':'true'})]):
            with patch.object(tool,'request',side_effect=bad),self.assertRaises(tool.ActivationError):
                tool.verify_updated_source('http://test','token',current,original)

    def test_source_page_rejects_extra_cursor_even_with_correct_items(self):
        with patch.object(tool,'get_source_list',return_value={'items':[],'next_cursor':None}):
            tool.verify_source_page('http://test','token','?device_id=missing',[],'BAD_PAGE')
        with patch.object(tool,'get_source_list',return_value={'items':[],'next_cursor':'unexpected'}), \
             self.assertRaisesRegex(tool.ActivationError,'BAD_PAGE'):
            tool.verify_source_page('http://test','token','?device_id=missing',[],'BAD_PAGE')

    def test_api_capabilities_require_registry_only_policy(self):
        with patch.object(tool,'verify_api'):
            for version in (tool.OLD_VERSION,tool.TARGET_VERSION):
                capabilities=dict(tool.OLD_CAPABILITIES)
                stage='P1_SOURCE_DELETE'
                if version==tool.TARGET_VERSION:
                    capabilities.update(device_delete='implemented')
                    stage='P1_DEVICE_DELETE'
                value={'version':version,'stage':stage,'capabilities':capabilities}
                with patch.object(tool,'request',return_value=(200,value,{})):tool.verify_version('base','token',version)
                for changed in ({**capabilities,'recording':'implemented'}, {**capabilities,'new_runtime':'implemented'},
                                {key:item for key,item in capabilities.items() if key!='source_update'}):
                    with patch.object(tool,'request',return_value=(200,{**value,'capabilities':changed},{})),self.assertRaises(tool.ActivationError):
                        tool.verify_version('base','token',version)

    def test_failure_diagnostics_identify_real_helper_without_exception_text(self):
        before={'version':1,'display_name':'old','updated_at':'2026-10-01T00:00:00Z'}
        after={**before,'version':2,'display_name':'new','updated_at':'never-log-secret'}
        try:
            tool.verify_rename(before,after,{'display_name':'new'})
        except tool.ActivationError as exc:
            details=tool.failure_details(exc)
        else:self.fail('invalid timestamp must fail')
        self.assertEqual(details['error_type'],'ActivationError')
        self.assertEqual(details['code'],'RENAME_TIMESTAMP_INVALID')
        self.assertEqual(details['failure_location']['file'],'test_camera_device_delete_upgrade.py')
        self.assertEqual(details['failure_location']['function'],'timestamp_order_key')
        self.assertGreater(details['failure_location']['line'],0)
        self.assertRegex(details['python_version'],r'^\d+\.\d+\.\d+$')
        self.assertNotIn('never-log-secret',json.dumps(details))
        self.assertNotIn(str(ROOT),json.dumps(details))

    def test_failure_diagnostics_use_only_fixed_types_and_safe_codes(self):
        errors=[(tool.URLError('https://never-log-secret@example.invalid'),'URLError'),
                (TimeoutError('never-log-secret'),'TimeoutError'),
                (KeyError('never-log-secret'),'KeyError'),
                (json.JSONDecodeError('never-log-secret','never-log-secret',0),'JSONDecodeError'),
                (KeyboardInterrupt('never-log-secret'),'KeyboardInterrupt'),
                (tool.ActivationError('FAILED: never-log-secret'),'ActivationError'),
                (tool.ActivationError('https://never-log-secret@example.invalid'),'ActivationError')]
        for exc,kind in errors:
            with self.subTest(kind=kind):
                details=tool.failure_details(exc)
                self.assertEqual(details['error_type'],kind)
                self.assertNotIn('never-log-secret',json.dumps(details))
                self.assertNotIn('failure_location',details)
                self.assertNotIn('args',details)

    def test_failure_receipt_and_public_output_include_safe_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'var/camera').mkdir(parents=True,mode=0o700)
            with patch.object(tool,'run_check',side_effect=KeyError('never-log-secret')):
                with self.assertRaises(KeyError) as caught:tool.execute(root,PROJECT)
            receipt=json.loads((root/tool.REPORT).read_text())
            self.assertEqual(receipt['status'],'failed')
            self.assertEqual(receipt['error_type'],'KeyError')
            self.assertEqual(receipt['failure_location']['function'],'execute')
            self.assertEqual((root/tool.REPORT).stat().st_mode&0o777,0o600)
            with patch.object(tool,'execute',side_effect=caught.exception),patch.object(tool.sys,'argv',['check']), \
                 contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(tool.main(),1)
            public=json.loads(output.getvalue())
            self.assertEqual(public['error_type'],'KeyError')
            self.assertEqual(public['python_version'],receipt['python_version'])
            self.assertFalse(public['production_services_modified'])
            self.assertFalse(public['device_delete_activated'])
            self.assertNotIn('never-log-secret',output.getvalue())
            self.assertNotIn('never-log-secret',json.dumps(receipt))

    def test_timestamp_accepts_zero_through_nine_fractional_digits(self):
        parse=tool.timestamp_order_key
        seconds=parse('2026-10-01T01:02:03Z')[0]
        for length in range(10):
            fraction='123456789'[:length]
            stamp='2026-10-01T01:02:03'+('.'+fraction if fraction else '')+'Z'
            with self.subTest(length=length):
                self.assertEqual(parse(stamp),(seconds,int(fraction.ljust(9,'0'))))
        self.assertEqual(parse('2026-10-01T01:02:03.12Z'),parse('2026-10-01T01:02:03.120000000Z'))

    def test_timestamp_offsets_and_second_boundaries_are_ordered(self):
        parse=tool.timestamp_order_key
        self.assertEqual(parse('2026-10-01T00:00:00.12345Z'),parse('2026-10-01T09:00:00.123450+09:00'))
        self.assertEqual(parse('2026-10-01T00:00:00Z'),parse('2026-09-30T19:00:00-05:00'))
        self.assertLess(parse('2026-09-30T23:59:59.999999999Z'),parse('2026-10-01T00:00:00Z'))

    def test_timestamp_rejects_malformed_calendar_and_timezone(self):
        bad_values=[None,123,[],{},'never-log-secret','2026-10-01',
                    '2026-10-01T00:00:00','2026-10-01T00:00:00.Z',
                    '2026-10-01T00:00:00.1234567890Z','2026-02-29T00:00:00Z',
                    '2026-10-01T24:00:00Z','2026-10-01T00:00:60Z',
                    '2026-10-01T00:00:00+24:00','2026-10-01T00:00:00+00:60',
                    '2026-10-01T00:00:00Z\n']
        for value in bad_values:
            with self.subTest(value=value),self.assertRaisesRegex(tool.ActivationError,'^RENAME_TIMESTAMP_INVALID$'):
                tool.timestamp_order_key(value)

    def test_rename_accepts_go_trimmed_and_nanosecond_timestamps(self):
        body={'display_name':'new'}
        for old_time,new_time in [('2026-10-01T01:02:03.12345Z','2026-10-01T01:02:03.123456Z'),
                                  ('2026-10-01T01:02:03.123456789Z','2026-10-01T01:02:03.123457Z'),
                                  ('2026-10-01T01:02:03.1Z','2026-10-01T01:02:03.100000000Z')]:
            before={'source_id':'source','version':1,'display_name':'old','updated_at':old_time}
            tool.verify_rename(before,{**before,'version':2,'display_name':'new','updated_at':new_time},body)

    def test_rename_rejects_one_nanosecond_regression(self):
        before={'source_id':'source','version':1,'display_name':'old','updated_at':'2026-10-01T01:02:03.123456789Z'}
        after={**before,'version':2,'display_name':'new','updated_at':'2026-10-01T01:02:03.123456788Z'}
        with self.assertRaisesRegex(tool.ActivationError,'RENAME_FIELDS_INVALID'):
            tool.verify_rename(before,after,{'display_name':'new'})


class DeleteEvidenceTest(unittest.TestCase):
    def response(self, replay=False, request_id='new'):
        receipt={'schema_version':'v1','source_id':tool.SOURCE['source_id'],
                 'version':4,'deleted_at':'2026-10-01T01:02:03.123456Z'}
        value={'deletion':receipt,'registration_state':'DELETED','runtime_verified':False,'request_id':request_id}
        headers={'X-Request-ID':request_id,'Idempotency-Replayed':str(replay).lower(),'Cache-Control':'no-store'}
        return 200,value,headers

    def test_delete_receipt_is_minimal_and_replay_id_is_fresh(self):
        good=self.response(True)
        with patch.object(tool,'delete_request',return_value=good):
            got=tool.delete_source('base','token',{},'key',True,good[1]['deletion'],'old')
            self.assertEqual(got,good[1])
            with self.assertRaises(tool.ActivationError):tool.delete_source('base','token',{},'key',True,good[1]['deletion'],'new')
            with self.assertRaisesRegex(tool.ActivationError,'SOURCE_DELETE_REPLAY_CHANGED'):
                tool.delete_source('base','token',{},'key',True,{**good[1]['deletion'],'version':5})

    def test_delete_rejects_extra_snapshots_wrong_time_version_and_headers(self):
        variants=[]
        for field,item in [('source',{}),('runtime_verified',True),('registration_state','REGISTERED'),('request_id','')]:
            response=copy.deepcopy(self.response());response[1][field]=item;variants.append(response)
        for field,item in [('profiles',[]),('schema_version','v2'),('source_id','other'),('version',True),
                           ('version',1),('version',9223372036854775808),('deleted_at','2026-10-01T00:00:00+00:00'),
                           ('deleted_at','2026-02-29T00:00:00Z')]:
            response=copy.deepcopy(self.response());response[1]['deletion'][field]=item;variants.append(response)
        for field,item in [('Location','/source'),('X-Request-ID','wrong'),('Cache-Control','public'),('Idempotency-Replayed','true')]:
            response=copy.deepcopy(self.response());response[2][field]=item;variants.append(response)
        variants.append((201,*self.response()[1:]))
        for response in variants:
            with self.subTest(response=response),patch.object(tool,'delete_request',return_value=response),self.assertRaises(tool.ActivationError):
                tool.delete_source('base','token',{},'key',False)

    def test_error_responses_cannot_contain_success_headers(self):
        good=(404,{'error':{'code':'SOURCE_NOT_FOUND'},'request_id':'req'}, {'X-Request-ID':'req','Cache-Control':'no-store'})
        tool.expect_error(good,404,'SOURCE_NOT_FOUND')
        for response in ((409,*good[1:]),(404,good[1],{**good[2],'Idempotency-Replayed':'false'}),
                         (404,good[1],{**good[2],'Location':'/new'}),(404,good[1],{})):
            with self.assertRaises(tool.ActivationError):tool.expect_error(response,404,'SOURCE_NOT_FOUND')

    def test_tombstone_matches_version_time_and_one_journal(self):
        before={'version':3,'updated_at':'2026-10-01T01:02:03.12345Z'}
        receipt=self.response()[1]['deletion']
        with patch.object(tool,'sql',side_effect=['1','1']) as sql:
            tool.verify_tombstone(object(),before,receipt,journal_count=1)
            self.assertIn('deleted_at=updated_at',sql.call_args_list[0].args[1])
        for changed in ({**receipt,'version':5},{**receipt,'deleted_at':'2026-10-01T01:02:03.123449999Z'}):
            with patch.object(tool,'sql') as sql,self.assertRaises(tool.ActivationError):
                tool.verify_tombstone(object(),before,changed)
            sql.assert_not_called()
        for rows in (['0'],['1','2']):
            with patch.object(tool,'sql',side_effect=rows),self.assertRaises(tool.ActivationError):
                tool.verify_tombstone(object(),before,receipt,journal_count=1)

    def test_fingerprint_only_excludes_exact_synthetic_tombstone_metadata(self):
        tables=['devices','device_create_requests','video_sources','stream_profiles','source_create_requests',
                'device_update_requests','source_update_requests']
        options=[{}, {'database':tool.RESTORE_DB},{'include_device_delete':True},
                 {'ignore_device_metadata':True},{'ignore_source_metadata':True,'include_source_delete':False}]
        for opts in options:
            expected={table:'a'*32 for table in tables+
                      (['source_delete_requests'] if opts.get('include_source_delete',True) else [])+
                      (['device_delete_requests'] if opts.get('include_device_delete') else [])}
            with patch.object(tool,'sql',return_value=json.dumps(expected)) as query:
                self.assertEqual(tool.registry_fingerprint(object(),**opts),expected)
            statement=query.call_args.args[1]
            self.assertEqual(query.call_args.args[2],opts.get('database','vms_camera'))
            self.assertEqual('camera.source_delete_requests' in statement,opts.get('include_source_delete',True))
            self.assertEqual('camera.device_delete_requests' in statement,bool(opts.get('include_device_delete')))
            self.assertEqual("CASE WHEN device_id='upgrade-test'" in statement,bool(opts.get('ignore_device_metadata')))
            self.assertEqual("source_id IN ('upgrade-source','upgrade-z-source')" in statement,bool(opts.get('ignore_source_metadata')))
            self.assertNotIn('UPDATE ',statement);self.assertNotIn('DELETE ',statement)
        for invalid in ({},{**expected,'extra':'b'*32},{**expected,'devices':'malformed'}):
            with patch.object(tool,'sql',return_value=json.dumps(invalid)),self.assertRaises(tool.ActivationError):
                tool.registry_fingerprint(object())

    def test_mutation_transport_sends_delete_json_without_proxy_or_redirect(self):
        class Response:
            status=200
            headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{}'
        body={'schema_version':'v1','expected_version':3}
        with patch.object(tool,'build_opener') as opener:
            opener.return_value.open.return_value=Response()
            tool.delete_request('http://127.0.0.1:12345','token',body,'key')
            req=opener.return_value.open.call_args.args[0]
            self.assertEqual(req.method,'DELETE');self.assertEqual(json.loads(req.data),body)
            self.assertEqual(req.full_url,'http://127.0.0.1:12345/api/v1/sources/upgrade-source')
            self.assertEqual(req.get_header('Idempotency-key'),'key')
            self.assertEqual(opener.call_args.args[0].proxies,{})
            self.assertIsNone(opener.call_args.args[1].redirect_request(None,None,None,None,None,None))
        for method,collection in [('POST','sources'),('PUT','devices'),('PATCH','other')]:
            with self.assertRaises(tool.ActivationError):tool.mutation_request('base','token',body,'key',collection,method)

    def test_grants_allow_device_tombstone_only_in_schema7_and_pin_restore_db(self):
        roles='camera_migrator|f|f|f|f|f\ncamera_runtime|f|f|f|f|f'
        for version,database in ((6,tool.RESTORE_DB),(7,'vms_camera')):
            with patch.object(tool,'sql',side_effect=['t',roles]) as query:
                tool.verify_runtime_grants(object(),version,database)
            statement=query.call_args_list[0].args[1]
            self.assertEqual(query.call_args_list[0].args[2],database)
            self.assertIn("NOT has_table_privilege('camera_runtime','camera.source_delete_requests','UPDATE')",statement)
            self.assertIn("has_column_privilege('camera_runtime','camera.video_sources','deleted_at','UPDATE')",statement)
            self.assertIn(("NOT " if version==6 else "AND ")+"has_column_privilege('camera_runtime','camera.devices','deleted_at','UPDATE')",statement)
            self.assertEqual('camera.device_delete_requests' in statement,version==7)
            self.assertIn('rolreplication,rolbypassrls',query.call_args_list[1].args[1])

class DeviceDeleteEvidenceTest(unittest.TestCase):
    def response(self, replay=False):
        response=list(DeleteEvidenceTest().response(replay))
        receipt=response[1]['deletion'];receipt.pop('source_id');receipt['device_id']=tool.DEVICE['device_id']
        return tuple(response)

    def test_device_receipt_requires_minimal_snapshot_and_fresh_request_id(self):
        good=self.response(True)
        with patch.object(tool,'delete_request',return_value=good):
            self.assertEqual(tool.delete_device('base','token',{},'key',True,good[1]['deletion'],'old'),good[1])
            with self.assertRaises(tool.ActivationError):tool.delete_device('base','token',{},'key',True,good[1]['deletion'],'new')
            with self.assertRaises(tool.ActivationError):tool.delete_device('base','token',{},'key',True,{**good[1]['deletion'],'version':5})
        variants=[]
        for field,item in [('device',{}),('source',{}),('runtime_verified',True),('registration_state','REGISTERED'),('request_id','')]:
            response=copy.deepcopy(self.response());response[1][field]=item;variants.append(response)
        for field,item in [('source_id','upgrade-source'),('profiles',[]),('schema_version','v2'),('device_id','other'),
                           ('version',True),('version',1),('version',9223372036854775808),
                           ('deleted_at','2026-10-01T00:00:00+00:00'),('deleted_at','2026-02-29T00:00:00Z')]:
            response=copy.deepcopy(self.response());response[1]['deletion'][field]=item;variants.append(response)
        for field,item in [('Location','/device'),('X-Request-ID','wrong'),('Cache-Control','public'),('Idempotency-Replayed','true')]:
            response=copy.deepcopy(self.response());response[2][field]=item;variants.append(response)
        for response in variants:
            with patch.object(tool,'delete_request',return_value=response),self.assertRaises(tool.ActivationError):
                tool.delete_device('base','token',{},'key',False)

    def test_device_tombstone_time_version_journal_and_safe_sql_identity(self):
        before={'version':3,'updated_at':'2026-10-01T01:02:03.12345Z'};receipt=self.response()[1]['deletion']
        with patch.object(tool,'sql',side_effect=['1','1']) as query:tool.verify_tombstone(object(),before,receipt,'devices',1)
        self.assertIn("camera.devices WHERE device_id='upgrade-test'",query.call_args_list[0].args[1])
        self.assertIn('camera.device_delete_requests',query.call_args_list[1].args[1])
        for changed in ({**receipt,'version':True},{**receipt,'device_id':"x'; SELECT 1; --"},
                        {**receipt,'version':5},{**receipt,'deleted_at':'2026-10-01T01:02:03.123449999Z'}):
            with patch.object(tool,'sql') as query,self.assertRaises(tool.ActivationError):tool.verify_tombstone(object(),before,changed,'devices',1)
            query.assert_not_called()

    def test_device_mutation_transport_and_resource_allowlist(self):
        with patch.object(tool,'mutation_request',return_value='response') as transport:
            self.assertEqual(tool.delete_request('base','token',{},'key','devices'),'response')
            self.assertEqual(transport.call_args.args[-3:],('devices','DELETE',None))
        for collection,identifier in [('devices','vms-project'),('sources','other-source')]:
            with patch.object(tool,'build_opener') as opener,self.assertRaises(tool.ActivationError):
                tool.mutation_request('base','token',{},'key',collection,'DELETE',identifier)
            opener.assert_not_called()

    def test_device_page_rejects_resurrection_and_stale_cursor(self):
        with patch.object(tool,'request',return_value=(200,{'items':[],'next_cursor':None},{})):tool.verify_device_page('base','token','',[],'BAD_PAGE')
        for page in ({'items':[{'device_id':'upgrade-test'}],'next_cursor':None},{'items':[],'next_cursor':'extra'}):
            with patch.object(tool,'request',return_value=(200,page,{})),self.assertRaises(tool.ActivationError):tool.verify_device_page('base','token','',[],'BAD_PAGE')

    def test_no_apply_option_and_private_provenance_excluded(self):
        with patch.object(tool.sys,'argv',['check','--apply']),patch.object(tool,'execute') as execute,contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(tool.main(),1);execute.assert_not_called()
        result={'status':'passed','checked_revision':'private-revision','docker_daemon':'private-daemon','recipe_sha256':'private-recipe'}
        with patch.object(tool.sys,'argv',['check']),patch.object(tool,'execute',return_value=result),contextlib.redirect_stdout(io.StringIO()) as output:self.assertEqual(tool.main(),0)
        self.assertFalse(any(value in output.getvalue() for value in ('private-revision','private-daemon','private-recipe')))


class RehearsalSequenceTest(unittest.TestCase):
    """Simulated IO tests order and failure gates, not native Docker acceptance."""
    def run_sequence(self, fault=None):
        events=[];phase={'schema':None,'active':set(),'parent_deleted':False,'source_deletes':0,
                        'restored':False,'requests':0,'failed_keys':[],'post':False}
        candidate='sha256:'+'c'*64;stamp='2026-10-01T01:02:03.123456Z'
        def error(code,status=409):return status,{'error':{'code':code},'request_id':'error'},{'X-Request-ID':'error','Cache-Control':'no-store'}
        class SequenceDocker:
            def run(self,args,**kwargs):return candidate.encode()
            def snapshot(self):return {key:{'id':key} for key in ('camera-db','model-api','analysis-api','operation-api')}
            def compose(self,args,**kwargs):
                events.append(('compose',args,kwargs))
                if args[0]=='config':return json.dumps({'services':{'camera-db':{}},'networks':{'camera-storage':{'internal':True}}}).encode()
                if 'pg_restore' in args:
                    assert args[-2:]==['-d',tool.RESTORE_DB] and kwargs['input']==b'PGDMP-test';phase['restored']=True
                return b''
        docker=SequenceDocker()
        def migrate(_,image,version,applied):events.append(('migrate',image,version,applied));phase['schema']=version
        def schema(root,_,version,database='vms_camera'):
            events.append(('schema',version,database));self.assertEqual(version,6 if database==tool.RESTORE_DB else phase['schema'])
            if database==tool.RESTORE_DB:self.assertTrue(phase['restored'])
        def seed(base,token,collection,body,key):
            identifier=body.get('source_id',body.get('device_id'));events.append(('seed',identifier,phase['schema']))
            if collection=='sources' and body['device_id']==tool.DEVICE['device_id']:phase['active'].add(identifier)
            if identifier==tool.POST_DEVICE['device_id']:phase['post']=True
            return {**body,'version':1,'updated_at':stamp}
        def patch_resource(base,token,body,key,replay,expected=None):
            events.append(('patch',base,body['expected_version'],replay,phase['schema']))
            if replay:return expected
            return {**(tool.DEVICE if '장치' in body['display_name'] else tool.SOURCE),'display_name':body['display_name'],'version':body['expected_version']+1,'updated_at':stamp}
        def fingerprint(_,include_device_delete=False,ignore_device_metadata=False,ignore_source_metadata=False,include_source_delete=True,database='vms_camera'):
            if database==tool.RESTORE_DB:return {'state':'bad' if fault=='bad-restore' else 'old'}
            if ignore_device_metadata:return {'state':'damaged' if fault=='parent-deletes-child' and phase['parent_deleted'] else 'parent-protected'}
            if not include_source_delete:return {'state':'damaged' if fault=='child-deletes-profiles' and phase['source_deletes']>1 else 'source-protected'}
            if include_device_delete:
                value=str((phase['source_deletes'],phase['parent_deleted'],phase['post']))
                if fault=='failed-key-journal' and phase['failed_keys']:value+='failed-journal'
                if fault=='replay-writes' and phase['parent_deleted'] and phase['requests']>5:value+='rewritten'
                if fault=='restore-rewinds-new' and phase['restored']:value='rewound'
                return {'state':value}
            return {'state':'changed' if fault=='migration-rows' and phase['schema']==7 else 'old'}
        def deleted(base,token,body,key,replay,expected=None,prior_request_id=None,identifier=None):
            identifier=identifier or tool.SOURCE['source_id']
            if not replay:
                self.assertIn(identifier,phase['active']);phase['active'].remove(identifier);phase['source_deletes']+=1
                self.assertEqual(phase['schema'],6 if identifier==tool.ARCHIVE_SOURCE['source_id'] else 7)
            phase['requests']+=1
            return {'deletion':expected or {'schema_version':'v1','source_id':identifier,'version':body['expected_version']+1,'deleted_at':stamp},'request_id':str(phase['requests'])}
        def parent_deleted(base,token,body,key,replay,expected=None,prior_request_id=None):
            self.assertEqual(phase['schema'],7);self.assertFalse(phase['active'])
            if not replay:self.assertEqual(phase['failed_keys'],['upgrade-device-key','upgrade-device-key']);phase['parent_deleted']=True
            phase['requests']+=1
            return {'deletion':expected or {'schema_version':'v1','device_id':tool.DEVICE['device_id'],'version':4,'deleted_at':stamp},'request_id':str(phase['requests'])}
        def backup(_,directory):
            events.append(('backup',phase['schema']));self.assertEqual(phase['schema'],6)
            self.assertEqual(phase['source_deletes'],1);self.assertEqual(len(phase['active']),2)
            path=directory/'camera.pgdump';path.write_bytes(b'PGDMP-test');return path
        def delete_request(base,token,body,key,collection='sources',identifier=None):
            if base=='restore':return 405,{}, {'Allow':'GET, PATCH'}
            if collection=='devices' and not phase['parent_deleted']:
                if body['expected_version']!=3:return error('DEVICE_VERSION_CONFLICT')
                if phase['active']:phase['failed_keys'].append(key);return error('DEVICE_HAS_ACTIVE_SOURCES')
            if key=='upgrade-device-key':return error('IDEMPOTENCY_CONFLICT')
            return error('DEVICE_NOT_FOUND' if collection=='devices' else 'SOURCE_NOT_FOUND',404)
        def request(base,path,token=None,body=None,key=None):
            if path=='/api/v1/devices?limit=1':return 200,{'items':[{**tool.DEVICE,'display_name':'전환 전 수정 장치','version':2,'updated_at':stamp}],'next_cursor':'device+cursor'},{}
            if body is not None:return error('DEVICE_EXISTS' if path.endswith('devices') else 'DEVICE_UNAVAILABLE')
            return error('DEVICE_NOT_FOUND' if '/devices/' in path else 'SOURCE_NOT_FOUND',404)
        current={**tool.SOURCE,'display_name':'전환 전 수정 소스','version':2,'updated_at':stamp}
        with tempfile.TemporaryDirectory() as directory,contextlib.ExitStack() as stack:
            root=Path(directory)
            @contextlib.contextmanager
            def isolated(*args):yield root,docker,'token','base','restore'
            replacements={'isolated_environment':isolated,'config_endpoint':lambda config:('base','token'),'migrate':migrate,'check_schema':schema,
                'verify_runtime_grants':lambda *args:events.append(('grants',args[1:])),'verify_version':lambda *args:None,'seed':seed,
                'patch_device':patch_resource,'patch_source':patch_resource,'get_source_list':lambda *args:{'items':[current],'next_cursor':'a+b/c='},
                'registry_fingerprint':fingerprint,'backup_database':backup,'sql':lambda *args:'0','delete_source':deleted,'delete_device':parent_deleted,
                'delete_request':delete_request,'verify_tombstone':lambda *args,**kwargs:None,'request':request,
                'patch_request':lambda *args:error('DEVICE_NOT_FOUND' if len(args)>4 else 'SOURCE_NOT_FOUND',404),
                **{name:(lambda *args,**kwargs:None) for name in ('verify_updated_device','verify_updated_source','verify_source_page','verify_device_page','verify_deleted_history','verify_resource')}}
            for name,value in replacements.items():stack.enter_context(patch.object(tool,name,side_effect=value))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()));result=tool.rehearse(ROOT,STATE,PROJECT)
        return result,events

    def test_schema6_history_cutover_and_separate_restore_sequence(self):
        result,events=self.run_sequence();candidate='sha256:'+'c'*64
        self.assertEqual([event for event in events if event[0]=='migrate'],[('migrate',IMAGE,6,6),('migrate',candidate,7,1),('migrate',candidate,7,0)])
        backup_index=events.index(('backup',6));self.assertIn(('seed','upgrade-source',6),events[:backup_index]);self.assertIn(('seed','upgrade-after-device',7),events[backup_index:])
        commands=[event[1] for event in events if event[0]=='compose'];restores=[args for args in commands if 'pg_restore' in args]
        self.assertEqual(len(restores),1);self.assertEqual(restores[0][-1],tool.RESTORE_DB)
        self.assertEqual([args[-1] for args in commands if '--force-recreate' in args],['camera-api','camera-api','camera-api','camera-restore-check'])
        self.assertIn(('grants',(6,tool.RESTORE_DB)),events);self.assertEqual(result['schema_version'],7);self.assertEqual(result['previous_schema_version'],6)
        self.assertTrue(all(result[name] is True for name in tool.CHECKS))

    def test_preservation_failures_never_return_a_passing_rehearsal(self):
        cases=[('migration-rows','MIGRATION_CHANGED_EXISTING_ROWS'),('child-deletes-profiles','SOURCE_DELETE_CHANGED_PROTECTED_ROWS'),
               ('parent-deletes-child','DEVICE_DELETE_CHANGED_PROTECTED_ROWS'),('failed-key-journal','FAILED_DELETE_CHANGED_ROWS'),
               ('replay-writes','REPLAY_OR_REJECTED_COMMAND_CHANGED_ROWS'),('bad-restore','RESTORED_REGISTRY_ROWS_CHANGED'),
               ('restore-rewinds-new','REPLAY_OR_REJECTED_COMMAND_CHANGED_ROWS')]
        for fault,code in cases:
            with self.subTest(fault=fault),self.assertRaisesRegex(tool.ActivationError,code):self.run_sequence(fault)


if __name__=='__main__':unittest.main(verbosity=2)
