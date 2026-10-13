#!/usr/bin/env python3
"""Exercise activation, persistence, least privilege and restore in an isolated Docker project."""
import contextlib
import io
import json
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile

from camera_activation import (ActivationError, DATABASE_IMAGE, Docker, activate, activation_lock,
                               atomic_write, config_endpoint, private_directory, protected,
                               request, verify_api, verify_project)


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def check(condition, code):
    if not condition:
        raise ActivationError(code)


def main():
    root=Path(__file__).resolve().parents[3]
    receipt_path=root/'var/camera/activation-check.json'
    project='vms-activation-test-'+secrets.token_hex(6)
    try:
        revision=verify_project(root)
        daemon=Docker(root).preflight()
        private_directory(receipt_path.parent)
        atomic_write(receipt_path,json.dumps({'status':'running','revision':revision}).encode())
        print('activation check: native Go/API/storage regression tests',flush=True)
        native=subprocess.run([sys.executable,'-B',str(root/'src/infra/tools/test_camera_storage.py')],timeout=1020)
        check(native.returncode==0,'NATIVE_STORAGE_REGRESSION_FAILED')
        with tempfile.TemporaryDirectory(prefix='vms-activation-') as temporary:
            test_root=Path(temporary)/'project'
            shutil.copytree(root,test_root,ignore=shutil.ignore_patterns('.env','var','build','.git','__pycache__'))
            token=secrets.token_urlsafe(36)
            atomic_write(test_root/'.env',('VMS_API_TOKEN='+token+'\nVMS_BIND_ADDR=127.0.0.1\nVMS_CAMERA_PORT='+str(unused_port())+'\n').encode())
            # Sentinels prove container identity/start time protection without
            # starting a second copy of unrelated application logic or services.
            for name in ('model','analysis','operation'):
                definition={'services':{name+'-api':{'image':DATABASE_IMAGE,'entrypoint':['sleep'],'command':['infinity']}}}
                (test_root/'src/platform'/name/'compose.yaml').write_text(json.dumps(definition))
            docker=Docker(test_root,project)
            docker.redact.append(token)
            try:
                print('activation check: start three protected sentinel containers',flush=True)
                docker.compose(['up','-d','--no-deps','model-api','analysis-api','operation-api'],active=False,timeout=300)
                before=protected(docker.snapshot())
                check(len(before)==3,'THREE_SENTINELS_REQUIRED')
                with activation_lock(test_root):
                    first=activate(test_root,docker)
                config=json.loads(docker.compose(['config','--format','json']))
                base,token=config_endpoint(config)
                check(not config['services']['camera-db'].get('ports'),'DATABASE_PORT_EXPOSED')
                check(config['networks']['camera-storage'].get('internal') is True,'DATABASE_NETWORK_NOT_INTERNAL')
                runtime_env=config['services']['camera-api']['environment']
                check('CAMERA_DATABASE_URL' not in runtime_env and runtime_env.get('CAMERA_DATABASE_URL_FILE'),'SECRET_FILE_NOT_USED')
                body={'schema_version':'v1','device_id':'activation-test','display_name':'격리 검증 장치','device_kind':'TEST'}
                code,created,_=request(base,'/api/v1/devices',token,body,'activation-test-key')
                check(code==201,'CREATE_FAILED')
                # Native permissions: test the exact fixed roles and grants deployed
                # by the bootstrap + migration image rather than test-only roles.
                sql="SELECT rolname,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname IN ('camera_migrator','camera_runtime') ORDER BY rolname;"
                roles=docker.compose(['exec','-T','camera-db','psql','-X','-A','-t','-U','camera_admin','-d','vms_camera','-c',sql]).decode().strip()
                check(roles=='camera_migrator|f|f|f\ncamera_runtime|f|f|f','ROLE_PRIVILEGES_INCORRECT')
                privileges="SELECT has_schema_privilege('camera_runtime','camera','CREATE'),has_table_privilege('camera_runtime','camera.devices','UPDATE'),has_table_privilege('camera_runtime','camera.devices','DELETE'),has_table_privilege('camera_runtime','camera.video_sources','SELECT');"
                allowed=docker.compose(['exec','-T','camera-db','psql','-X','-A','-t','-U','camera_admin','-d','vms_camera','-c',privileges]).decode().strip()
                check(allowed=='f|f|f|f','RUNTIME_EXCESS_PRIVILEGE')
                # Reapply creates a consistent dump containing the test device.
                with activation_lock(test_root):
                    second=activate(test_root,docker)
                check(first['migration_applied']==2 and second['migration_applied']==0,'MIGRATION_REAPPLY_INCORRECT')
                print('activation check: inject a switch failure and verify camera rollback',flush=True)
                class FailSwitchOnce(Docker):
                    injected=False
                    def compose(self,args,**kwargs):
                        value=super().compose(args,**kwargs)
                        if args[0]=='up' and args[-1]=='camera-api' and not kwargs.get('image') and not self.injected:
                            self.injected=True
                            raise ActivationError('EXPECTED_TEST_SWITCH_FAILURE')
                        return value
                prior_env=(test_root/'.env').read_bytes()
                prior_image=docker.snapshot()['camera-api']['image']
                backups=test_root/'var/camera/activation-backups'
                prior_backups=set(backups.iterdir())
                try:
                    with activation_lock(test_root),contextlib.redirect_stdout(io.StringIO()):
                        activate(test_root,FailSwitchOnce(test_root,project))
                except ActivationError as exc:
                    check(str(exc)=='EXPECTED_TEST_SWITCH_FAILURE','UNEXPECTED_ROLLBACK_TEST_ERROR')
                else:
                    raise ActivationError('FAILURE_INJECTION_DID_NOT_RUN')
                new_backups=set(backups.iterdir())-prior_backups
                check(len(new_backups)==1,'ROLLBACK_RECORD_MISSING')
                recovery=json.loads((new_backups.pop()/'result.json').read_text())
                check(recovery.get('recovery')=='previous_camera_configuration_restored','CAMERA_ROLLBACK_INCOMPLETE')
                check((test_root/'.env').read_bytes()==prior_env and docker.snapshot()['camera-api']['image']==prior_image,'CAMERA_ROLLBACK_CHANGED_ORIGINAL')
                verify_api(base,token)
                print('activation check: replace DB and API containers; keep the named volume',flush=True)
                docker.compose(['up','-d','--no-deps','--force-recreate','--wait','--wait-timeout','90','camera-db'],timeout=150)
                docker.compose(['up','-d','--no-deps','--no-build','--force-recreate','--wait','--wait-timeout','60','camera-api'],timeout=100)
                verify_api(base,token)
                code,value,_=request(base,'/api/v1/devices/activation-test',token)
                check(code==200 and value.get('device')==created.get('device'),'DATABASE_RECREATE_LOST_DEVICE')
                code,value,headers=request(base,'/api/v1/devices',token,body,'activation-test-key')
                check(code==201 and value.get('device')==created.get('device') and headers.get('Idempotency-Replayed')=='true','DATABASE_RECREATE_LOST_REPLAY')
                print('activation check: restore backup into a separate temporary database',flush=True)
                docker.compose(['exec','-T','camera-db','createdb','-U','camera_admin','vms_camera_restore'])
                docker.compose(['exec','-T','camera-db','pg_restore','--exit-on-error','-U','camera_admin','-d','vms_camera_restore'],input=Path(second['backup']).read_bytes())
                count=docker.compose(['exec','-T','camera-db','psql','-X','-A','-t','-U','camera_admin','-d','vms_camera_restore','-c',"SELECT count(*) FROM camera.devices WHERE device_id='activation-test';"]).decode().strip()
                check(count=='1','BACKUP_RESTORE_LOST_DEVICE')
                check(protected(docker.snapshot())==before,'PROTECTED_CONTAINERS_CHANGED')
            finally:
                # This random project belongs only to this check. Live activation
                # never uses down, remove-orphans or volume deletion.
                docker.compose(['down','--volumes','--remove-orphans','--timeout','10'],timeout=90)
        result={'status':'passed','scope':'camera_activation_native_docker','revision':revision,
                'docker_daemon':daemon,'project':project,'production_services_modified':False,
                'database_container_recreated':True,'backup_restore_verified':True,'camera_rollback_verified':True,'protected_sentinels_unchanged':True}
        atomic_write(receipt_path,json.dumps(result,indent=2).encode())
        print(json.dumps({k:v for k,v in result.items() if k not in {'revision','docker_daemon'}},ensure_ascii=False))
        return 0
    except (ActivationError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        if receipt_path.parent.is_dir():
            atomic_write(receipt_path,json.dumps({'status':'failed','project':project}).encode())
        print(json.dumps({'status':'failed','scope':'camera_activation_native_docker','project':project,'code':str(exc)}),file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
