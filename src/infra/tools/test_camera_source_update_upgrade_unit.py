import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_camera_source_update_upgrade as tool

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
            (root/'source-update-test-project').write_text('other-project')
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

    def test_schema_validation_checks_all_hashes_and_update_table(self):
        names=('0001_registry.sql','0002_device_idempotency.sql',
               '0003_source_idempotency.sql','0004_device_update.sql','0005_source_update.sql')
        def state(version):
            return {'migrations':[{'version':i,'name':'migrations/'+name,
                'checksum':tool.sha(ROOT/'src/platform/camera/internal/storage/migrations'/name)}
                for i,name in enumerate(names[:version],1)], 'has_update_table':version==5,'has_device_update_table':True}
        for version in (4,5):
            value=state(version)
            with patch.object(tool,'sql',return_value=json.dumps(value)):
                tool.check_schema(ROOT,object(),version)
            value['migrations'][-1]['checksum']='wrong'
            with patch.object(tool,'sql',return_value=json.dumps(value)),self.assertRaisesRegex(tool.ActivationError,'ISOLATED_SCHEMA_MISMATCH'):
                tool.check_schema(ROOT,object(),version)
        value=state(4);value['has_update_table']=True
        with patch.object(tool,'sql',return_value=json.dumps(value)),self.assertRaises(tool.ActivationError):tool.check_schema(ROOT,object(),4)

    def test_runtime_grants_do_not_accept_missing_permissions(self):
        roles='camera_migrator|f|f|f\ncamera_runtime|f|f|f'
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
        responses=[(200,{'device':current},{}),(200,{'items':[current],'next_cursor':None},{}),
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
               'env_sha256':'env','secret_sha256':{'runtime':'secret-hash'},'step07_acceptance_sha256':'accepted','counts':{'devices':0}}
        result={'candidate_image':'sha256:'+'c'*64,'schema_version':5,**{name:True for name in tool.CHECKS}}
        with patch.object(tool,'recipe_fingerprint',return_value='recipe'),patch.object(tool,'rehearse',return_value=result),contextlib.redirect_stdout(io.StringIO()):
            after={**state,'counts':{'devices':1}}
            with patch.object(tool,'inspect_upgrade',side_effect=[state,after]):
                passed=tool.run_check(ROOT,object(),PROJECT)
                self.assertEqual(passed['status'],'passed');self.assertFalse(passed['production_services_modified'])
            for key in ('containers','secret_sha256','checked_revision','step07_acceptance_sha256'):
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

    def test_new_api_requires_source_update_but_old_api_still_requires_device_update(self):
        capabilities={key:'implemented' for key in ('device_registry','source_registry','source_list','device_update')}
        with patch.object(tool,'verify_api'):
            for version in (tool.OLD_VERSION,tool.TARGET_VERSION):
                value={'version':version,'capabilities':dict(capabilities)}
                if version==tool.TARGET_VERSION:value['capabilities']['source_update']='implemented'
                with patch.object(tool,'request',return_value=(200,value,{})):tool.verify_version('base','token',version)
                missing='source_update' if version==tool.TARGET_VERSION else 'device_update'
                del value['capabilities'][missing]
                with patch.object(tool,'request',return_value=(200,value,{})),self.assertRaises(tool.ActivationError):
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
        self.assertEqual(details['failure_location']['file'],'test_camera_source_update_upgrade.py')
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
            self.assertFalse(public['source_update_activated'])
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


if __name__=='__main__':unittest.main(verbosity=2)
