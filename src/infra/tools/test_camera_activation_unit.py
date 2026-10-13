import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import camera_activation as tool


class FakeDocker:
    def __init__(self,root,fail=None):
        self.root=root;self.project='vms-project';self.redact=[];self.calls=[];self.fail=fail
        self.state={'camera-api':{'id':'old','image':'sha256:old','started_at':'before','running':True,'restarts':0},
                    'model-api':{'id':'protected','image':'model','started_at':'before','running':True,'restarts':0}}
    def snapshot(self):return copy.deepcopy(self.state)
    def volume_exists(self):return 'camera-db' in self.state
    def run(self,args,**kwargs):self.calls.append(args);return b''
    def compose(self,args,**kwargs):
        self.calls.append(args)
        if args[0]=='config':
            return json.dumps({'services':{'camera-api':{'image':'vms-project-camera-control:step04','ports':[{'target':8080,'published':'18081','host_ip':'127.0.0.1'}],'environment':{'VMS_API_TOKEN':'test-token-12345678901234567890'}}}}).encode()
        if args[0]=='up' and args[-1]=='camera-db':
            self.state['camera-db']={'id':'db','image':'postgres','started_at':'now','running':True,'restarts':0}
        if args[0]=='exec' and 'pg_dump' in args:
            kwargs['stdout'].write(b'PGDMP-test-backup')
        if args[0]=='run':
            if self.fail=='migration':raise tool.ActivationError('INJECTED_MIGRATION_FAILURE')
            return b'{"applied":2,"version":2}'
        if args[0]=='up' and args[-1]=='camera-api':
            self.state['camera-api']={'id':'switched','image':kwargs.get('image','sha256:new'),'started_at':'now','running':True,'restarts':0}
            if not kwargs.get('image'):
                if self.fail=='concurrent_env':
                    with (self.root/'.env').open('ab') as f:f.write(b'# concurrent user edit\n')
                    raise tool.ActivationError('INJECTED_SWITCH_FAILURE')
                if self.fail=='api':raise tool.ActivationError('INJECTED_SWITCH_FAILURE')
                if self.fail=='other':self.state['model-api']['started_at']='external-change'
        return b''


class ActivationTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.original=b'VMS_API_TOKEN=test-token-12345678901234567890\nVMS_CAMERA_PORT=18081\n'
        (self.root/'.env').write_bytes(self.original)
        tool.private_directory(self.root/'var/camera')

    def activate(self,fake):
        with contextlib.redirect_stdout(io.StringIO()),patch.object(tool,'verify_api'):
            with tool.activation_lock(self.root):return tool.activate(self.root,fake)

    def test_secret_modes_and_reuse_under_umask_0002(self):
        previous=os.umask(0o002)
        try:first=tool.prepare_secrets(self.root,False);second=tool.prepare_secrets(self.root,True)
        finally:os.umask(previous)
        self.assertEqual(first,second)
        self.assertEqual(stat.S_IMODE((self.root/'var/camera/secrets').stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((self.root/'var/camera/secrets/runtime-dsn').stat().st_mode),0o444)

    def test_existing_volume_without_secrets_refused(self):
        with self.assertRaises(tool.ActivationError):tool.prepare_secrets(self.root,True)
        self.assertFalse((self.root/'var/camera/secrets').exists())

    def test_incomplete_secret_set_refused_without_regeneration(self):
        first=tool.prepare_secrets(self.root,False)
        (self.root/'var/camera/secrets/runtime-dsn').unlink()
        with self.assertRaises(tool.ActivationError):tool.prepare_secrets(self.root,False)
        self.assertEqual((self.root/'var/camera/secrets/runtime-password').read_text().strip(),first['runtime-password'])

    def test_symlink_refused(self):
        (self.root/'var/camera/secrets').symlink_to(self.root)
        with self.assertRaises(tool.ActivationError):tool.prepare_secrets(self.root,False)

    def test_activation_lock_excludes_second_writer(self):
        with tool.activation_lock(self.root):
            with self.assertRaises(tool.ActivationError):
                with tool.activation_lock(self.root):pass

    def test_enable_preserves_token_and_is_idempotent(self):
        result=tool.enabled_environment(self.original)
        self.assertTrue(result.startswith(self.original))
        self.assertEqual(result,tool.enabled_environment(result))
        for tail in (b'VMS_CAMERA_COMPOSE_FILE=custom.yaml\n', b'COMPOSE_FILE=custom.yaml\n',b'VMS_CAMERA_IMAGE=foreign\n'):
            with self.assertRaises(tool.ActivationError):tool.enabled_environment(self.original+tail)

    def test_success_changes_only_camera_services(self):
        fake=FakeDocker(self.root);before=tool.protected(fake.snapshot())
        result=self.activate(fake)
        self.assertTrue(result['other_services_unchanged'])
        self.assertEqual(tool.protected(fake.snapshot()),before)
        self.assertEqual((Path(result['backup']).parent/'env.before').read_bytes(),self.original)
        self.assertTrue((self.root/'.env').read_bytes().startswith(self.original))
        self.assertFalse(any('down' in c or '--volumes' in c for c in fake.calls))

    def test_migration_failure_keeps_env_and_api(self):
        fake=FakeDocker(self.root,'migration')
        with self.assertRaises(tool.ActivationError):self.activate(fake)
        self.assertEqual((self.root/'.env').read_bytes(),self.original)
        self.assertEqual(fake.state['camera-api']['id'],'old')
        self.assertIn(['image','tag','sha256:old','vms-project-camera-control:step04'],fake.calls)
        self.assertIn('camera-db',fake.state)

    def test_switch_failure_restores_env_and_old_image(self):
        fake=FakeDocker(self.root,'api')
        with self.assertRaises(tool.ActivationError):self.activate(fake)
        self.assertEqual((self.root/'.env').read_bytes(),self.original)
        self.assertEqual(fake.state['camera-api']['image'],'sha256:old')
        self.assertIn('camera-db',fake.state)

    def test_concurrent_user_env_edit_is_preserved(self):
        fake=FakeDocker(self.root,'concurrent_env')
        with self.assertRaises(tool.ActivationError):self.activate(fake)
        self.assertIn(b'# concurrent user edit',(self.root/'.env').read_bytes())
        result=json.loads(next((self.root/'var/camera/activation-backups').glob('*/result.json')).read_text())
        self.assertEqual(result['recovery'],'manual_recovery_required')

    def test_external_change_is_detected_without_modifying_other_service(self):
        fake=FakeDocker(self.root,'other')
        with self.assertRaises(tool.ActivationError):self.activate(fake)
        self.assertEqual(fake.state['model-api']['started_at'],'external-change')
        self.assertFalse(any(c[-1:] == ['model-api'] for c in fake.calls))


if __name__=='__main__':unittest.main()
