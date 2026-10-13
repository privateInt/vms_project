import copy
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest.mock import patch

import inspect_camera_source_update as tool

API_ID, DB_ID, OTHER_ID = 'a'*64, 'b'*64, 'c'*64
API_IMAGE, DB_IMAGE = 'sha256:'+'d'*64, 'sha256:'+'e'*64
TOKEN = 'never-output-this-test-token-1234567890'


class ReadOnlyDocker:
    project = 'vms-project'

    def __init__(self, root):
        self.root=root;self.redact=[];self.commands=[];self.snapshots=0;self.on_after=None
        self.state={name:{'id':identity,'image':image,'running':True,'started_at':'before','restarts':0}
                    for name,identity,image in (('camera-api',API_ID,API_IMAGE),('camera-db',DB_ID,DB_IMAGE),('model-api',OTHER_ID,DB_IMAGE))}
        self.database={'database':'vms_camera','postgres_version_num':170011,'database_bytes':8000000,
                       'migrations':[],'counts':{'devices':3,'device_requests':4,'video_sources':2,'stream_profiles':4,'source_requests':3,'device_update_requests':2},
                       'source_update_table':None,'non_runtime_clients':0,
                       'roles':[{'name':r,'superuser':False,'create_database':False,'create_role':False}
                                for r in ('camera_migrator','camera_runtime')]}
        for i,name in enumerate(tool.MIGRATIONS[:4],1):
            self.database['migrations'].append({'version':i,'name':'migrations/'+name,
                'checksum':tool.sha(root/'src/platform/camera/internal/storage/migrations'/name)})
        self.config={'services':{'camera-db':{},'camera-api':{'image':API_IMAGE,
            'ports':[{'target':8080,'published':'18081','host_ip':'127.0.0.1'}],
            'environment':{'VMS_API_TOKEN':TOKEN,'CAMERA_DATABASE_URL_FILE':'/run/secrets/camera_runtime_dsn'}}}}
        self.db_inspect={'State':{'Health':{'Status':'healthy'}},'Mounts':[{'Type':'volume','Name':'vms-project_camera-data','Destination':'/var/lib/postgresql/data'}]}
        self.camera_inspect={'Mounts':[{'Type':'bind','Source':str(root/'var/camera/secrets/runtime-dsn'),'Destination':'/run/secrets/camera_runtime_dsn','RW':False}]}

    def preflight(self):return 'test-daemon'
    def volume_exists(self):return True
    def snapshot(self):
        self.snapshots+=1
        if self.snapshots==2 and self.on_after:self.on_after()
        return copy.deepcopy(self.state)
    def compose(self,args,**kwargs):
        if args!=['config','--format','json'] or kwargs:raise AssertionError('unexpected Compose operation')
        return json.dumps(self.config).encode()
    def run(self,args,**kwargs):
        self.commands.append(args)
        if args==['inspect',DB_ID]:return json.dumps([self.db_inspect]).encode()
        if args==['inspect',API_ID]:return json.dumps([self.camera_inspect]).encode()
        if args==['exec',DB_ID,*tool.SQL_ARGS,tool.READ_ONLY_SQL]:return json.dumps(self.database).encode()
        raise AssertionError('unexpected Docker operation')


class InspectionTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        names=['src/infra/tools/camera_activation.py','src/platform/camera/api/openapi.json',
               *('src/platform/camera/internal/storage/migrations/'+name for name in tool.MIGRATIONS)]
        files={}
        for name in names:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('-- '+name);files[name]=tool.sha(path)
        manifest={'version':tool.TARGET_VERSION,'activation_revision':'step08c-source-update-http-code-20261001',
                  'storage_revision':'step08b-source-update-storage-20260930','source_update_api_implemented':True,
                  'storage_schema_version':5,'files':files}
        (self.root/'project-manifest.json').write_text(json.dumps(manifest))
        (self.root/'.env').write_text('existing-configuration-with-private-token')
        (self.root/'var/camera').mkdir(parents=True,mode=0o700)
        directory=self.root/'var/camera/secrets';directory.mkdir(mode=0o700)
        password='f'*64
        values={name:password for name in ('admin-password','migration-password','runtime-password')}
        values.update({'migration-dsn':'postgres://camera_migrator:'+password+'@camera-db:5432/vms_camera?sslmode=disable',
            'runtime-dsn':'postgres://camera_runtime:'+password+'@camera-db:5432/vms_camera?sslmode=disable',
            'identity.json':json.dumps({'format':1,'database':'vms_camera'})})
        for name,value in values.items():
            path=directory/name;path.write_text(value+'\n');path.chmod(0o600 if name=='identity.json' else 0o444)
        (self.root/tool.ACCEPTANCE).write_text(json.dumps({'status':'activated','stage':'completed','scope':'camera_device_update',
            'project':'vms-project','schema_version':4,'device_update_activated':True,'candidate_image':API_IMAGE,'database_image':DB_IMAGE}))
        self.docker=ReadOnlyDocker(self.root)
        self.api={'version':tool.OLD_VERSION,'stage':'P1_DEVICE_UPDATE','capabilities':{c:'implemented' for c in ('device_registry','source_registry','source_list','device_update')}}
        mock=patch.object(tool,'request',side_effect=self.request);mock.start();self.addCleanup(mock.stop)
        disk=patch.object(tool.shutil,'disk_usage',return_value=types.SimpleNamespace(free=10**10));disk.start();self.addCleanup(disk.stop)

    def request(self,base,path,token=None):
        if path=='/health/ready':return 200,{'ready':True,'scope':'camera_registry','business_runtime_ready':False},{}
        if path=='/api/v1/platform':return 200,self.api,{}
        if path=='/api/v1/sources?limit=1':return 200,{'items':[{'source_id':'private-name-never-report'}],'next_cursor':None},{}
        raise AssertionError('only expected read-only requests allowed')

    def inspect(self):return tool.inspect_upgrade(self.root,self.docker)
    def reject(self,code):
        with self.assertRaisesRegex(tool.ActivationError,code):self.inspect()

    def test_read_only_result_and_private_data_not_reported(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.inspect()
        self.assertEqual(result['status'],'passed');self.assertEqual(result['schema_version'],4);self.assertEqual(result['target_schema_version'],5)
        self.assertFalse(result['source_update_activated']);self.assertFalse(result['production_services_modified'])
        self.assertEqual(result['counts']['devices'],3);self.assertEqual(result['minimum_backup_free_bytes'],64*1024*1024)
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        encoded=json.dumps(result)
        for value in (TOKEN,'f'*64,'postgres://','private-name-never-report','existing-configuration-with-private-token'):self.assertNotIn(value,encoded)
        self.assertTrue(tool.READ_ONLY_SQL.startswith('BEGIN READ ONLY;'))

    def test_schema_and_checksum_drift(self):
        self.docker.database['migrations'][3]['checksum']='wrong';self.reject('EXPECTED_SCHEMA_4_REQUIRED')

    def test_already_migrated(self):
        self.docker.database['source_update_table']='camera.source_update_requests';self.reject('EXPECTED_SCHEMA_4_REQUIRED')

    def test_missing_migration(self):
        self.docker.database['migrations'].pop();self.reject('EXPECTED_SCHEMA_4_REQUIRED')

    def test_unexpected_api_or_capability(self):
        self.api['version']=tool.TARGET_VERSION;self.reject('EXPECTED_STEP07_RUNNING_API_REQUIRED')
        self.api['version']=tool.OLD_VERSION;self.api['capabilities']['source_list']='disabled';self.reject('EXPECTED_STEP07_RUNNING_API_REQUIRED')

    def test_receipt_or_pin_mismatch(self):
        self.docker.config['services']['camera-api']['image']='moving:tag';self.reject('ACTIVE_PINNED_CAMERA_REQUIRED')
        self.docker.config['services']['camera-api']['image']=API_IMAGE
        path=self.root/tool.ACCEPTANCE;record=json.loads(path.read_text());record['candidate_image']=DB_IMAGE;path.write_text(json.dumps(record))
        self.reject('STEP07_ACTIVATION_RECORD_MISMATCH')

    def test_unhealthy_or_wrong_volume(self):
        self.docker.db_inspect['State']['Health']['Status']='unhealthy';self.reject('DATABASE_NOT_HEALTHY')
        self.docker.db_inspect['State']['Health']['Status']='healthy';self.docker.db_inspect['Mounts'][0]['Name']='other-data';self.reject('RUNNING_DATABASE_VOLUME_MISMATCH')

    def test_wrong_secret_mount(self):
        self.docker.camera_inspect['Mounts'][0]['RW']=True;self.reject('RUNNING_CAMERA_SECRET_MOUNT_MISMATCH')

    def test_missing_secrets_not_created(self):
        path=self.root/'var/camera/secrets/runtime-dsn';path.unlink();self.reject('SECRET_FILE_STATE_INVALID');self.assertFalse(path.exists())

    def test_role_or_other_client(self):
        self.docker.database['roles'][1]['superuser']=True;self.reject('DATABASE_ROLE_CONFIGURATION_CHANGED')
        self.docker.database['roles'][1]['superuser']=False;self.docker.database['non_runtime_clients']=1;self.reject('OTHER_DATABASE_CLIENTS_PRESENT')

    def test_invalid_counts_and_size(self):
        self.docker.database['counts']['devices']=-1;self.reject('DATABASE_COUNTS_INVALID')
        self.docker.database['counts']['devices']=True;self.reject('DATABASE_COUNTS_INVALID')
        self.docker.database['counts']['devices']=3;self.docker.database['database_bytes']=0;self.reject('DATABASE_SIZE_INVALID')

    def test_device_update_journal_count_required(self):
        del self.docker.database['counts']['device_update_requests']
        self.reject('DATABASE_COUNTS_INVALID')

    def test_public_success_omits_private_fingerprints(self):
        result=self.inspect()
        output=io.StringIO()
        with patch.object(tool,'run_inspection',return_value=result), patch.object(tool.sys,'argv',['inspect']), patch.object(tool.sys,'stdout',output):
            self.assertEqual(tool.main(),0)
        public=json.loads(output.getvalue())
        self.assertEqual(public['scope'],'camera_source_update_preflight')
        self.assertEqual(public['counts']['device_update_requests'],2)
        for name in ('checked_revision','inspector_sha256','docker_daemon','containers','env_sha256','secret_sha256','step07_acceptance_sha256'):
            self.assertNotIn(name,public)

    def test_insufficient_backup_space(self):
        with patch.object(tool.shutil,'disk_usage',return_value=types.SimpleNamespace(free=1024)):self.reject('BACKUP_SPACE_INSUFFICIENT')

    def test_container_changed_during_inspection(self):
        self.docker.on_after=lambda:self.docker.state['model-api'].update(restarts=1)
        self.reject('PROJECT_CONTAINERS_CHANGED_DURING_INSPECTION')

    def test_environment_changed_during_inspection(self):
        self.docker.on_after=lambda:(self.root/'.env').write_text('concurrent edit')
        self.reject('PROJECT_CHANGED_DURING_INSPECTION')
        self.assertEqual((self.root/'.env').read_text(),'concurrent edit')

    def test_secret_changed_during_inspection(self):
        path=self.root/'var/camera/secrets/admin-password'
        def change():path.chmod(0o600);path.write_text('a'*64);path.chmod(0o444)
        self.docker.on_after=change;self.reject('PROJECT_CHANGED_DURING_INSPECTION')

    def test_changed_code_rejected_before_docker(self):
        (self.root/'src/platform/camera/internal/storage/migrations/0001_registry.sql').write_text('edited')
        self.reject('PROJECT_FILE_CHANGED');self.assertEqual(self.docker.commands,[])

    def test_invalid_manifest_path(self):
        path=self.root/'project-manifest.json';value=json.loads(path.read_text());value['files']['../outside']='0'*64;path.write_text(json.dumps(value))
        self.reject('PROJECT_MANIFEST_INVALID')

    def test_symlink_rejected(self):
        path=self.root/'.env';path.unlink();path.symlink_to(self.root/'project-manifest.json');self.reject('SYMLINK_PATH_REJECTED')

    def test_report_replaces_old_pass_on_failure_and_interrupt(self):
        report=self.root/tool.REPORT
        for error in (tool.ActivationError('DOCKER_COMMAND_FAILED: '+TOKEN), KeyboardInterrupt()):
            report.write_text('{"status":"passed"}')
            with patch.object(tool,'inspect_upgrade',side_effect=error):
                with self.assertRaises(type(error)):tool.run_inspection(self.root)
            self.assertEqual(json.loads(report.read_text()),{'status':'failed'})
            self.assertEqual(stat.S_IMODE(report.stat().st_mode),0o600)
            self.assertNotIn(TOKEN,report.read_text())

    def test_success_report_and_shared_lock(self):
        with patch.object(tool,'InspectionDocker',return_value=self.docker):
            result=tool.run_inspection(self.root)
        self.assertEqual(json.loads((self.root/tool.REPORT).read_text()),result)
        self.assertEqual(stat.S_IMODE((self.root/tool.REPORT).stat().st_mode),0o600)
        with tool.activation_lock(self.root):
            with self.assertRaisesRegex(tool.ActivationError,'ANOTHER_ACTIVATION_IS_RUNNING'):tool.run_inspection(self.root)
        self.assertEqual(json.loads((self.root/tool.REPORT).read_text()),result)

    def test_main_diagnostic_does_not_expose_secret(self):
        output=io.StringIO()
        with patch.object(tool,'run_inspection',side_effect=tool.ActivationError('DOCKER_COMMAND_FAILED: '+TOKEN)), patch.object(tool.sys,'argv',['inspect']), patch.object(tool.sys,'stderr',output):
            self.assertEqual(tool.main(),1)
        self.assertNotIn(TOKEN,output.getvalue());self.assertEqual(json.loads(output.getvalue())['code'],'DOCKER_COMMAND_FAILED')


class CommandGuardTest(unittest.TestCase):
    def test_mutations_and_arbitrary_sql_are_blocked_before_execution(self):
        docker=tool.InspectionDocker(Path('/test/project'))
        with patch.object(tool.Docker,'run',return_value=b'') as underlying:
            for args in (['restart',API_ID],['build','.'],['stop',API_ID],['rm',API_ID],['volume','rm','vms-project_camera-data'],
                         ['exec',DB_ID,*tool.SQL_ARGS,'SELECT 1'],['exec',DB_ID,*tool.SQL_ARGS,tool.READ_ONLY_SQL+'DROP TABLE camera.devices;']):
                with self.subTest(command=args[:2]),self.assertRaisesRegex(tool.ActivationError,'PRODUCTION_DOCKER_WRITE_REJECTED'):docker.run(args)
            for args,kwargs in ((['up','-d'],{}),(['config','--format','json'],{'active':True}),(['config','--format','json'],{'image':API_IMAGE})):
                with self.assertRaisesRegex(tool.ActivationError,'PRODUCTION_COMPOSE_WRITE_REJECTED'):docker.compose(args,**kwargs)
            underlying.assert_not_called()

    def test_exact_read_commands_are_allowed(self):
        docker=tool.InspectionDocker(Path('/test/project'))
        with patch.object(tool.Docker,'run',return_value=b'') as underlying:
            for args in (['context','inspect'],['info','--format','{{.ID}}'],['ps','-aq','--filter','label=com.docker.compose.project=vms-project'],
                         ['inspect',API_ID,DB_ID],['volume','ls','--format','{{.Name}}','--filter','name=^vms-project_camera-data$'],
                         ['volume','inspect','vms-project_camera-data'],['exec',DB_ID,*tool.SQL_ARGS,tool.READ_ONLY_SQL]):docker.run(args)
            docker.compose(['config','--format','json']);self.assertEqual(underlying.call_count,8)
            # Exercise compose's inherited dispatch through the new run guard.
            self.assertEqual(underlying.call_args.args[0][-3:],['config','--format','json'])


if __name__=='__main__':unittest.main()
