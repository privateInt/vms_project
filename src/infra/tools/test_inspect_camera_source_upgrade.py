import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import inspect_camera_source_upgrade as tool


class ReadOnlyDocker:
    project = 'vms-project'

    def __init__(self, root):
        self.root=root;self.redact=[];self.commands=[];self.snapshots=0;self.changed=False
        self.state={name:{'id':name+'-id','image':'sha256:'+name,'running':True,'started_at':'before','restarts':0}
                    for name in ('camera-api','camera-db','model-api')}
        self.database={'database':'vms_camera','postgres_version_num':170011,'database_bytes':8000000,
                       'migrations':[],'counts':{'devices':3,'device_requests':3,'video_sources':0,'stream_profiles':0},
                       'source_request_table':None,'non_runtime_clients':0,
                       'roles':[{'name':r,'superuser':False,'create_database':False,'create_role':False}
                                for r in ('camera_migrator','camera_runtime')]}
        for i,name in enumerate(('0001_registry.sql','0002_device_idempotency.sql'),1):
            self.database['migrations'].append({'version':i,'name':'migrations/'+name,
                'checksum':tool.sha(root/'src/platform/camera/internal/storage/migrations'/name)})

    def preflight(self):return 'test-daemon'
    def volume_exists(self):return True
    def snapshot(self):
        self.snapshots+=1
        value=copy.deepcopy(self.state)
        if self.changed and self.snapshots>1:value['model-api']['restarts']=1
        return value
    def compose(self,args,**kwargs):
        if args!=['config','--format','json'] or kwargs!={'active':False}:raise AssertionError('unexpected Compose operation')
        return json.dumps({'services':{'camera-db':{},'camera-api':{'ports':[{'target':8080,'published':'18081','host_ip':'127.0.0.1'}],
            'environment':{'VMS_API_TOKEN':'never-output-this-test-secret','CAMERA_DATABASE_URL_FILE':'/run/secrets/camera_runtime_dsn'}}}}).encode()
    def run(self,args,**kwargs):
        self.commands.append(args)
        if args==['inspect','camera-db-id']:
            return json.dumps([{'State':{'Health':{'Status':'healthy'}},'Mounts':[{'Type':'volume','Name':'vms-project_camera-data','Destination':'/var/lib/postgresql/data'}]}]).encode()
        if args==['exec','camera-db-id','psql','-X','-q','-A','-t','-v','ON_ERROR_STOP=1','-U','camera_admin','-d','vms_camera','-c',tool.READ_ONLY_SQL]:
            return json.dumps(self.database).encode()
        raise AssertionError('unexpected Docker operation')


class InspectionTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        directory=self.root/'src/platform/camera/internal/storage/migrations';directory.mkdir(parents=True)
        for name in ('0001_registry.sql','0002_device_idempotency.sql'):(directory/name).write_text('-- '+name)
        manifest={'storage_revision':'step05-source-idempotency-20260930','activation_revision':'step05-source-registration-code-20260930',
                  'files':{p.relative_to(self.root).as_posix():tool.sha(p) for p in directory.iterdir()}}
        (self.root/'project-manifest.json').write_text(json.dumps(manifest))
        (self.root/'.env').write_text('keep-existing-settings')
        (self.root/'var/camera').mkdir(parents=True)
        self.docker=ReadOnlyDocker(self.root)
        self.api_version='0.2.0-device-registry'
        mock=patch.object(tool,'request',side_effect=self.request);mock.start();self.addCleanup(mock.stop)

    def request(self,base,path,token=None):
        if path=='/health/ready':return 200,{'ready':True,'scope':'camera_registry'},{}
        if path=='/api/v1/platform':return 200,{'version':self.api_version,'capabilities':{'device_registry':'implemented'}},{}
        raise AssertionError('only read-only health and platform requests allowed')

    def test_read_only_report_preserves_project_and_secret(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=tool.inspect_upgrade(self.root,self.docker)
        self.assertEqual(result['status'],'passed');self.assertFalse(result['source_api_activated'])
        self.assertEqual(result['counts']['devices'],3)
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertNotIn('never-output-this-test-secret',json.dumps(result))
        self.assertTrue(tool.READ_ONLY_SQL.startswith('BEGIN READ ONLY;'))

    def test_schema_drift_is_rejected(self):
        self.docker.database['migrations'][1]['checksum']='wrong'
        with self.assertRaisesRegex(tool.ActivationError,'EXPECTED_SCHEMA_2_REQUIRED'):tool.inspect_upgrade(self.root,self.docker)

    def test_already_migrated_database_is_rejected(self):
        self.docker.database['source_request_table']='camera.source_create_requests'
        with self.assertRaisesRegex(tool.ActivationError,'EXPECTED_SCHEMA_2_REQUIRED'):tool.inspect_upgrade(self.root,self.docker)

    def test_unexpected_running_api_is_rejected(self):
        self.api_version='0.3.0-source-registry'
        with self.assertRaisesRegex(tool.ActivationError,'EXPECTED_STEP04_RUNNING_API_REQUIRED'):tool.inspect_upgrade(self.root,self.docker)

    def test_concurrent_container_change_is_rejected(self):
        self.docker.changed=True
        with self.assertRaisesRegex(tool.ActivationError,'PROJECT_CONTAINERS_CHANGED'):tool.inspect_upgrade(self.root,self.docker)

    def test_other_database_client_is_rejected(self):
        self.docker.database['non_runtime_clients']=1
        with self.assertRaisesRegex(tool.ActivationError,'OTHER_DATABASE_CLIENTS_PRESENT'):tool.inspect_upgrade(self.root,self.docker)

    def test_changed_project_is_rejected_before_docker(self):
        (self.root/'src/platform/camera/internal/storage/migrations/0001_registry.sql').write_text('changed')
        with self.assertRaisesRegex(tool.ActivationError,'PROJECT_FILE_CHANGED'):tool.inspect_upgrade(self.root,self.docker)
        self.assertEqual(self.docker.commands,[])


if __name__=='__main__':unittest.main()
