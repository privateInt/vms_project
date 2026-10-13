#!/usr/bin/env python3
"""Rehearse schema 2 -> 3 and backup recovery in a disposable Docker project.

The production project is inspected only. This is not the live cutover tool.
"""
import contextlib
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import sys
import tempfile
from urllib.error import URLError

from camera_activation import (ACTIVE, ActivationError, Docker, activation_lock,
                               atomic_write, backup_database, config_endpoint,
                               prepare_secrets, private_directory, protected,
                               request, sha, verify_api)
from inspect_camera_source_upgrade import checked_manifest, inspect_upgrade, require

PREFIX = 'vms-source-upgrade-test-'
RESTORE_DB = 'vms_camera_restore'
DEVICE = {'schema_version':'v1', 'device_id':'upgrade-test',
          'display_name':'전환 검증 장치', 'device_kind':'TEST'}
SOURCE = {'schema_version':'v1', 'source_id':'upgrade-source', 'device_id':'upgrade-test',
          'channel_key':'ch1', 'display_name':'전환 검증 소스', 'transport':'RTSP',
          'input_mode':'PULL', 'motion_mode':'FIXED', 'profiles':[
              {'profile_id':'main','codec':'H264','width':1920,'height':1080,'fps':30},
              {'profile_id':'sub','codec':'H264','width':640,'height':360,'fps':15}]}


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def pinned_image(value):
    require(isinstance(value, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value),
            'PINNED_IMAGE_REQUIRED')
    return value


class RehearsalDocker(Docker):
    def __init__(self, root, project, production_root):
        require(re.fullmatch(PREFIX+r'[0-9a-f]{12}', project), 'ISOLATED_PROJECT_REQUIRED')
        require(root.resolve() != production_root.resolve()
                and production_root.resolve() not in root.resolve().parents,
                'SEPARATE_TEMPORARY_WORKSPACE_REQUIRED')
        require((root/'rehearsal-project').read_text() == project, 'WORKSPACE_MARKER_MISMATCH')
        super().__init__(root, project)


def configure_workspace(production_root, root, state, project):
    old_image = pinned_image(state['camera_image'])
    database_image = pinned_image(state['database_image'])
    checked_manifest(production_root)
    root.mkdir()
    manifest = json.loads((production_root/'project-manifest.json').read_text())
    for name in [*manifest['files'], 'project-manifest.json']:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(production_root/name, target)
    (root/'rehearsal-project').write_text(project)
    token = secrets.token_urlsafe(36)
    port, restore_port = unused_port(), unused_port()
    while port == restore_port:
        restore_port = unused_port()
    atomic_write(root/'.env', ('VMS_API_TOKEN='+token+'\nVMS_BIND_ADDR=127.0.0.1\n'
                              'VMS_CAMERA_PORT='+str(port)+'\n').encode())
    private_directory(root/'var/camera')
    values = prepare_secrets(root, False)
    restore_dsn = values['runtime-dsn'].replace('/vms_camera?', '/'+RESTORE_DB+'?')
    atomic_write(root/'var/camera/secrets/restore-dsn', (restore_dsn+'\n').encode(), 0o444)
    # The test uses the exact running PostgreSQL image, never a moving tag.
    db_compose = root/'src/infra/postgresql/compose.camera.yaml'
    definition = db_compose.read_text()
    require(definition.count('image: postgres:17.11-bookworm') == 1, 'DATABASE_DEFINITION_CHANGED')
    db_compose.write_text(definition.replace('image: postgres:17.11-bookworm', 'image: '+database_image))
    for owner in ('model', 'analysis', 'operation'):
        (root/'src/platform'/owner/'compose.yaml').write_text(json.dumps({'services':{
            owner+'-api':{'image':database_image,'entrypoint':['sleep'],'command':['infinity']}}}))
    # An explicit, separately published test service reads the restored DB. It
    # never replaces vms_camera or rewrites the runtime DSN used by the new API.
    (root/'compose.yaml').write_text(json.dumps({
        'include':[{'path':ACTIVE}, *[{'path':'./src/platform/'+p+'/compose.yaml'}
                                     for p in ('model','analysis','operation')]],
        'services':{'camera-restore-check':{
            'image':old_image, 'environment':{'HTTP_ADDR':':8080','VMS_API_TOKEN':token,
                'CAMERA_DATABASE_URL_FILE':'/run/secrets/camera_restore_dsn'},
            'secrets':['camera_restore_dsn'], 'networks':['default','camera-storage'],
            'ports':['127.0.0.1:'+str(restore_port)+':8080'], 'profiles':['recovery-tools'],
            'healthcheck':{'test':['CMD','/vms-api','--healthcheck'],
                           'interval':'2s','timeout':'3s','retries':15},
            'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],
            'restart':'no','stop_grace_period':'10s'}},
        'secrets':{'camera_restore_dsn':{'file':str(root/'var/camera/secrets/restore-dsn')}}}))
    return token, 'http://127.0.0.1:'+str(port), 'http://127.0.0.1:'+str(restore_port), values


@contextlib.contextmanager
def isolated_environment(production_root, state, project):
    directory = Path(tempfile.mkdtemp(prefix=project+'-'))
    root = directory/'project'
    docker = None
    try:
        token, base, restore_base, values = configure_workspace(production_root, root, state, project)
        candidate = RehearsalDocker(root, project, production_root)
        require(candidate.preflight() == state['docker_daemon'], 'DOCKER_DAEMON_CHANGED')
        require(not candidate.snapshot() and not candidate.volume_exists(), 'ISOLATED_PROJECT_ALREADY_EXISTS')
        docker = candidate
        docker.redact.extend([token, *values.values()])
        yield root, docker, token, base, restore_base
    finally:
        # Only this fresh random project can reach down --volumes. If cleanup
        # fails, retain bind-mounted secrets and the workspace for a safe retry.
        if docker is not None:
            try:
                docker.compose(['--profile','*','down','--volumes','--remove-orphans','--timeout','10'], timeout=120)
            except BaseException:
                print(json.dumps({'status':'cleanup_failed','project':project,
                                  'retained_workspace':str(root)}), flush=True)
                raise
        shutil.rmtree(directory)


def sql(docker, statement, database='vms_camera'):
    require(database in ('vms_camera', RESTORE_DB), 'UNEXPECTED_TEST_DATABASE')
    return docker.compose(['exec','-T','camera-db','psql','-X','-q','-A','-t',
                           '-v','ON_ERROR_STOP=1','-U','camera_admin','-d',database,
                           '-c',statement], timeout=30).decode().strip()


def migrate(docker, image, version, applied):
    result = json.loads(docker.compose(['run','--rm','--no-deps','camera-migrate'],
                                      image=pinned_image(image), timeout=90))
    require(result.get('version') == version and result.get('applied') == applied,
            'UNEXPECTED_MIGRATION_RESULT')


def start_api(docker, image, service='camera-api'):
    require(service in ('camera-api','camera-restore-check'), 'UNEXPECTED_TEST_SERVICE')
    docker.compose(['up','-d','--no-deps','--no-build','--force-recreate',
                    '--wait','--wait-timeout','60',service], image=pinned_image(image), timeout=100)


def verify_version(base, token, version):
    verify_api(base, token)
    code, value, _ = request(base, '/api/v1/platform', token)
    require(code == 200 and value.get('version') == version, 'API_VERSION_MISMATCH')
    if version == '0.3.0-source-registry':
        require(value.get('capabilities', {}).get('source_registry') == 'implemented',
                'SOURCE_CAPABILITY_NOT_ENABLED')


def verify_resource(base, token, collection, body, key, expected):
    kind, identity = ('device','device_id') if collection == 'devices' else ('source','source_id')
    path = '/api/v1/'+collection
    code, value, _ = request(base, path+'/'+body[identity], token)
    require(code == 200 and value.get(kind) == expected, 'RESOURCE_NOT_PRESERVED')
    code, value, headers = request(base, path, token, body, key)
    require(code == 201 and value.get(kind) == expected
            and headers.get('Idempotency-Replayed') == 'true', 'IDEMPOTENT_RESPONSE_NOT_PRESERVED')


def verify_privileges(docker):
    checks = ["NOT has_schema_privilege('camera_runtime','camera','CREATE')"]
    for table in ('devices','device_create_requests','video_sources','stream_profiles','source_create_requests'):
        for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
            prefix = '' if privilege in ('SELECT','INSERT') else 'NOT '
            checks.append(prefix+"has_table_privilege('camera_runtime','camera."+table+"','"+privilege+"')")
    require(sql(docker, 'SELECT '+' AND '.join(checks)+';') == 't', 'RUNTIME_GRANTS_INCORRECT')
    require(sql(docker, "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles "
                       "WHERE rolname IN ('camera_migrator','camera_runtime') ORDER BY rolname;")
            == 'camera_migrator|f|f|f\ncamera_runtime|f|f|f', 'ROLE_PRIVILEGES_INCORRECT')


def rehearse(production_root, state, project):
    with isolated_environment(production_root, state, project) as (root, docker, token, base, restore_base):
        tag = project+'-camera:source'
        print('source upgrade check: build candidate image in the isolated project', flush=True)
        docker.compose(['build','camera-api'], image=tag, timeout=900)
        new_image = pinned_image(docker.run(['image','inspect','--format','{{.Id}}',tag]).decode().strip())
        old_image = pinned_image(state['camera_image'])
        print('source upgrade check: start isolated schema 2 with the running old image', flush=True)
        docker.compose(['up','-d','--no-deps','--wait','--wait-timeout','90',
                        'camera-db','model-api','analysis-api','operation-api'], image=old_image, timeout=180)
        sentinels = protected(docker.snapshot())
        require(len(sentinels) == 3, 'THREE_SENTINELS_REQUIRED')
        config = json.loads(docker.compose(['config','--format','json'], image=new_image))
        require(not config['services']['camera-db'].get('ports')
                and config['networks']['camera-storage'].get('internal') is True, 'DATABASE_ISOLATION_REQUIRED')
        require(config_endpoint(config) == (base,token), 'TEST_ENDPOINT_MISMATCH')
        migrate(docker, old_image, 2, 2)
        start_api(docker, old_image)
        verify_version(base, token, '0.2.0-device-registry')
        code, created, _ = request(base, '/api/v1/devices', token, DEVICE, 'upgrade-device-key')
        require(code == 201 and isinstance(created.get('device'),dict), 'DEVICE_SEED_FAILED')
        device = created['device']
        print('source upgrade check: stop the old API, back up, migrate and grant schema 3', flush=True)
        docker.compose(['stop','--timeout','15','camera-api'], image=old_image)
        require(sql(docker, "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                            "AND backend_type='client backend' AND pid<>pg_backend_pid();") == '0',
                'DATABASE_WRITERS_NOT_QUIESCED')
        backup_dir = root/'var/camera/upgrade-backup'
        private_directory(backup_dir)
        backup = backup_database(docker, backup_dir)
        backup_digest = sha(backup)
        migrate(docker, new_image, 3, 1)
        migrate(docker, new_image, 3, 0)
        verify_privileges(docker)
        start_api(docker, new_image)
        verify_version(base, token, '0.3.0-source-registry')
        verify_resource(base, token, 'devices', DEVICE, 'upgrade-device-key', device)
        code, created, _ = request(base, '/api/v1/sources', token, SOURCE, 'upgrade-source-key')
        require(code == 201 and isinstance(created.get('source'),dict), 'SOURCE_CREATE_FAILED')
        source = created['source']
        verify_resource(base, token, 'sources', SOURCE, 'upgrade-source-key', source)
        start_api(docker, new_image)
        verify_version(base, token, '0.3.0-source-registry')
        verify_resource(base, token, 'devices', DEVICE, 'upgrade-device-key', device)
        verify_resource(base, token, 'sources', SOURCE, 'upgrade-source-key', source)
        print('source upgrade check: restore schema 2 separately and verify the old API', flush=True)
        docker.compose(['exec','-T','camera-db','createdb','-U','camera_admin','-T','template0',RESTORE_DB])
        sql(docker, 'REVOKE ALL ON DATABASE '+RESTORE_DB+' FROM PUBLIC; '
                    'GRANT CONNECT, CREATE ON DATABASE '+RESTORE_DB+' TO camera_migrator; '
                    'GRANT CONNECT ON DATABASE '+RESTORE_DB+' TO camera_runtime;')
        docker.compose(['exec','-T','camera-db','pg_restore','--exit-on-error','-U','camera_admin',
                        '-d',RESTORE_DB], input=backup.read_bytes(), timeout=180)
        require(sql(docker, "SELECT count(*)=2 AND max(version)=2 FROM camera.schema_migrations;", RESTORE_DB) == 't'
                and sql(docker, "SELECT to_regclass('camera.source_create_requests') IS NULL;", RESTORE_DB) == 't',
                'RESTORED_SCHEMA_NOT_VERSION_2')
        start_api(docker, old_image, 'camera-restore-check')
        verify_version(restore_base, token, '0.2.0-device-registry')
        verify_resource(restore_base, token, 'devices', DEVICE, 'upgrade-device-key', device)
        # Acknowledged post-upgrade data must still exist in the schema-3 DB.
        # Restoring a backup is never permission to overwrite that database.
        verify_resource(base, token, 'sources', SOURCE, 'upgrade-source-key', source)
        require(sha(backup) == backup_digest, 'BACKUP_WAS_CHANGED')
        docker.compose(['rm','--stop','--force','camera-restore-check'], image=old_image)
        require(protected(docker.snapshot()) == sentinels, 'PROTECTED_SENTINELS_CHANGED')
        return {'candidate_image':new_image, 'candidate_image_tag':tag,
                'schema_upgrade_verified':True, 'runtime_grants_verified':True,
                'device_and_source_replay_verified':True, 'api_recreation_verified':True,
                'schema_2_restore_verified':True, 'old_api_on_restored_database_verified':True,
                'post_upgrade_data_preserved':True, 'protected_sentinels_unchanged':True}


def recipe_fingerprint(root):
    return {name:sha(root/'src/infra/tools'/name) for name in (
        'test_camera_source_upgrade.py','inspect_camera_source_upgrade.py','camera_activation.py')}


def main():
    root = Path(__file__).resolve().parents[3]
    receipt = root/'var/camera/source-upgrade-check.json'
    project = PREFIX+secrets.token_hex(6)
    try:
        with activation_lock(root):
            atomic_write(receipt, json.dumps({'status':'running','project':project}).encode())
            try:
                print('source upgrade check: read current production state without changing services', flush=True)
                live = Docker(root)
                state = inspect_upgrade(root, live)
                env_digest, recipe = sha(root/'.env'), recipe_fingerprint(root)
                result = rehearse(root, state, project)
                require(live.snapshot() == state['containers'] and sha(root/'.env') == env_digest
                        and checked_manifest(root) == state['checked_revision']
                        and recipe_fingerprint(root) == recipe, 'PRODUCTION_OR_RECIPE_CHANGED_DURING_CHECK')
                result.update({'status':'passed','scope':'camera_source_upgrade_native_docker',
                               'project':project,'checked_revision':state['checked_revision'],
                               'docker_daemon':state['docker_daemon'],'recipe_sha256':recipe,
                               'previous_camera_image':state['camera_image'],
                               'database_image':state['database_image'], 'production_services_modified':False,
                               'source_api_activated':False, 'isolated_resources_removed':True,
                               'automatic_production_database_restore':False})
                atomic_write(receipt, (json.dumps(result,indent=2)+'\n').encode())
            except BaseException:
                atomic_write(receipt, json.dumps({'status':'failed','project':project}).encode())
                raise
        public = {k:v for k,v in result.items() if k not in {'checked_revision','docker_daemon','recipe_sha256'}}
        public['report'] = str(receipt)
        print(json.dumps(public, ensure_ascii=False))
        return 0
    except (ActivationError,OSError,ValueError,KeyError,TypeError,URLError) as exc:
        code = str(exc).split(':',1)[0] if isinstance(exc,ActivationError) else 'SOURCE_UPGRADE_CHECK_UNAVAILABLE'
        print(json.dumps({'status':'failed','scope':'camera_source_upgrade_native_docker',
                          'project':project,'code':code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
