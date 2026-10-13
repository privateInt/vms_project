#!/usr/bin/env python3
"""Rehearse device-update schema 3 -> 4 and separate-DB recovery in disposable Docker.

Production is read-only; the successful candidate image is retained for a later
activation step. Cleanup removes only this random test project's runtime resources.
"""
import contextlib
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from camera_activation import (ACTIVE, ActivationError, Docker, activation_lock,
                               atomic_write, backup_database, config_endpoint,
                               prepare_secrets, private_directory, protected,
                               request, sha, verify_api)
from inspect_camera_device_update import (InspectionDocker, OLD_VERSION, TARGET_VERSION,
                                         checked_manifest, inspect_upgrade, pinned_image, require)
from test_camera_source_upgrade import (DEVICE, SOURCE, RESTORE_DB, unused_port,
                                       sql, migrate, start_api, verify_resource)

PREFIX = 'vms-device-update-test-'
SCOPE = 'camera_device_update_upgrade_native_docker'
REPORT = 'var/camera/device-update-upgrade-check.json'
CHECKS = ('schema_upgrade_verified', 'runtime_grants_verified',
          'device_and_source_replay_verified', 'device_update_replay_verified',
          'source_list_preserved', 'api_recreation_verified', 'schema_3_restore_verified',
          'old_api_on_restored_database_verified', 'post_upgrade_data_preserved',
          'protected_sentinels_unchanged', 'isolated_database_unchanged')

class RehearsalDocker(Docker):
    def __init__(self, root, project, production_root):
        require(re.fullmatch(PREFIX+r'[0-9a-f]{12}', project), 'ISOLATED_PROJECT_REQUIRED')
        require(root.resolve() != production_root.resolve()
                and production_root.resolve() not in root.resolve().parents,
                'SEPARATE_TEMPORARY_WORKSPACE_REQUIRED')
        require((root/'device-update-test-project').read_text() == project, 'WORKSPACE_MARKER_MISMATCH')
        super().__init__(root, project)


def configure_workspace(production_root, root, state, project):
    old_image = pinned_image(state['camera_image'])
    database_image = pinned_image(state['database_image'])
    require(checked_manifest(production_root) == state['checked_revision'], 'PROJECT_REVISION_CHANGED')
    root.mkdir()
    manifest = json.loads((production_root/'project-manifest.json').read_text())
    for name in [*manifest['files'], 'project-manifest.json']:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(production_root/name, target)
    require(checked_manifest(root) == state['checked_revision'], 'COPIED_PROJECT_REVISION_CHANGED')
    (root/'device-update-test-project').write_text(project)
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
        require(not candidate.snapshot() and not candidate.volume_exists()
                and not candidate.run(['network','ls','-q','--filter','label=com.docker.compose.project='+project]).strip()
                and not candidate.run(['image','ls','-q','--filter','reference='+project+'-camera:device-update']).strip(),
                'ISOLATED_PROJECT_ALREADY_EXISTS')
        docker = candidate
        docker.redact.extend([token, *values.values()])
        yield root, docker, token, base, restore_base
    finally:
        # Only this fresh random project can reach down --volumes. If cleanup
        # fails, retain bind-mounted secrets and the workspace for a safe retry.
        if docker is not None:
            try:
                docker.compose(['--profile','*','down','--volumes','--remove-orphans','--timeout','10'], timeout=120)
                require(not docker.snapshot() and not docker.volume_exists()
                        and not docker.run(['network','ls','-q','--filter','label=com.docker.compose.project='+project]).strip(),
                        'ISOLATED_RESOURCES_REMAIN')
            except BaseException:
                print(json.dumps({'status':'cleanup_failed','project':project,
                                  'retained_workspace':str(root)}), flush=True)
                raise
        shutil.rmtree(directory)


def recipe_fingerprint(root):
    names = ('test_camera_device_update_upgrade.py', 'inspect_camera_device_update.py',
             'camera_activation.py', 'test_camera_source_upgrade.py', 'inspect_camera_source_upgrade.py')
    values = {name:sha(root/'src/infra/tools'/name) for name in names}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def check_schema(root, docker, version, database='vms_camera'):
    require(version in (3, 4), 'UNEXPECTED_TEST_SCHEMA')
    names = ('0001_registry.sql', '0002_device_idempotency.sql',
             '0003_source_idempotency.sql', '0004_device_update.sql')[:version]
    value = json.loads(sql(docker, """SELECT json_build_object(
 'migrations',(SELECT json_agg(json_build_object('version',version,'name',name,'checksum',checksum) ORDER BY version) FROM camera.schema_migrations),
 'has_update_table',to_regclass('camera.device_update_requests') IS NOT NULL);""", database))
    expected = [{'version':i, 'name':'migrations/'+name,
                 'checksum':sha(root/'src/platform/camera/internal/storage/migrations'/name)}
                for i, name in enumerate(names, 1)]
    require(value.get('migrations') == expected and value.get('has_update_table') is (version == 4),
            'ISOLATED_SCHEMA_MISMATCH')


def verify_runtime_grants(docker):
    checks = ["NOT has_schema_privilege('camera_runtime','camera','CREATE')",
              "has_table_privilege('camera_runtime','camera.schema_migrations','SELECT')"]
    for table in ('devices', 'device_create_requests', 'video_sources', 'stream_profiles',
                  'source_create_requests', 'device_update_requests'):
        for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
            prefix = '' if privilege in ('SELECT', 'INSERT') else 'NOT '
            checks.append(prefix+"has_table_privilege('camera_runtime','camera."+table+"','"+privilege+"')")
    for column in ('display_name', 'version', 'updated_at', 'device_id', 'device_kind', 'created_at', 'deleted_at'):
        prefix = '' if column in ('display_name', 'version', 'updated_at') else 'NOT '
        checks.append(prefix+"has_column_privilege('camera_runtime','camera.devices','"+column+"','UPDATE')")
    require(sql(docker, 'SELECT '+' AND '.join(checks)+';') == 't', 'RUNTIME_GRANTS_INCORRECT')
    require(sql(docker, "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles "
                       "WHERE rolname IN ('camera_migrator','camera_runtime') ORDER BY rolname;")
            == 'camera_migrator|f|f|f\ncamera_runtime|f|f|f', 'ROLE_PRIVILEGES_INCORRECT')


def verify_version(base, token, version):
    verify_api(base, token)
    code, value, _ = request(base, '/api/v1/platform', token)
    capabilities = ('device_registry', 'source_registry', 'source_list')
    if version == TARGET_VERSION:
        capabilities += ('device_update',)
    require(code == 200 and value.get('version') == version
            and all(value.get('capabilities', {}).get(name) == 'implemented' for name in capabilities),
            'API_VERSION_OR_CAPABILITY_MISMATCH')


def patch_request(base, token, body, key):
    req = Request(base+'/api/v1/devices/'+DEVICE['device_id'],
                  data=json.dumps(body, ensure_ascii=False).encode(), method='PATCH',
                  headers={'Authorization':'Bearer '+token, 'Content-Type':'application/json',
                           'Idempotency-Key':key})
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        response = build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=3)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.load(response), response.headers


def patch_device(base, token, body, key, replay, expected=None):
    code, value, headers = patch_request(base, token, body, key)
    device = value.get('device')
    require(code == 200 and isinstance(device, dict)
            and headers.get('Idempotency-Replayed') == ('true' if replay else 'false')
            and not headers.get('Location') and value.get('request_id')
            and value['request_id'] == headers.get('X-Request-ID'), 'DEVICE_UPDATE_RESPONSE_INVALID')
    if expected is not None:
        require(device == expected, 'DEVICE_UPDATE_REPLAY_CHANGED')
    return device


def expect_update_conflict(base, token, body, key, expected_code):
    code, value, _ = patch_request(base, token, body, key)
    require(code == 409 and value.get('error', {}).get('code') == expected_code,
            'DEVICE_UPDATE_CONFLICT_INVALID')


def seed(base, token, collection, body, key):
    code, value, _ = request(base, '/api/v1/'+collection, token, body, key)
    field = 'device' if collection == 'devices' else 'source'
    require(code == 201 and isinstance(value.get(field), dict), 'ISOLATED_SEED_FAILED')
    return value[field]


def verify_updated_device(base, token, current, original):
    code, value, _ = request(base, '/api/v1/devices/'+DEVICE['device_id'], token)
    require(code == 200 and value.get('device') == current, 'CURRENT_DEVICE_NOT_PRESERVED')
    code, value, _ = request(base, '/api/v1/devices?limit=1', token)
    require(code == 200 and value.get('items') == [current] and value.get('next_cursor') is None,
            'DEVICE_LIST_NOT_PRESERVED')
    code, value, headers = request(base, '/api/v1/devices', token, DEVICE, 'upgrade-device-key')
    require(code == 201 and value.get('device') == original
            and headers.get('Idempotency-Replayed') == 'true', 'DEVICE_CREATE_REPLAY_CHANGED')


def get_source_list(base, token, query=''):
    code, value, _ = request(base, '/api/v1/sources'+query, token)
    require(code == 200 and isinstance(value.get('items'), list) and 'next_cursor' in value,
            'SOURCE_LIST_INVALID')
    return value


def rehearse(production_root, state, project):
    with isolated_environment(production_root, state, project) as (root, docker, token, base, restore_base):
        tag = project+'-camera:device-update'
        print('device update check: build candidate image in the isolated project', flush=True)
        docker.compose(['build', 'camera-api'], image=tag, timeout=900)
        new_image = pinned_image(docker.run(['image', 'inspect', '--format', '{{.Id}}', tag]).decode().strip())
        old_image = pinned_image(state['camera_image'])
        require(new_image != old_image, 'NEW_CAMERA_IMAGE_REQUIRED')
        config = json.loads(docker.compose(['config', '--format', 'json'], image=new_image))
        require(not config['services']['camera-db'].get('ports')
                and config['networks']['camera-storage'].get('internal') is True
                and config_endpoint(config) == (base, token), 'ISOLATED_NETWORK_CONFIGURATION_REQUIRED')
        print('device update check: seed isolated schema 3 with the running old image', flush=True)
        docker.compose(['up', '-d', '--no-deps', '--wait', '--wait-timeout', '90',
                        'camera-db', 'model-api', 'analysis-api', 'operation-api'], image=old_image, timeout=180)
        snapshot = docker.snapshot()
        sentinels, database = protected(snapshot), snapshot['camera-db']
        require(len(sentinels) == 3, 'THREE_SENTINELS_REQUIRED')
        migrate(docker, old_image, 3, 3)
        check_schema(root, docker, 3)
        start_api(docker, old_image)
        verify_version(base, token, OLD_VERSION)
        device = seed(base, token, 'devices', DEVICE, 'upgrade-device-key')
        source = seed(base, token, 'sources', SOURCE, 'upgrade-source-key')
        second_body = {**SOURCE, 'source_id':'upgrade-z-source', 'channel_key':'ch2'}
        second_source = seed(base, token, 'sources', second_body, 'upgrade-second-source-key')
        page = get_source_list(base, token, '?limit=1')
        require(page['items'] == [source] and isinstance(page['next_cursor'], str) and page['next_cursor'],
                'SOURCE_CURSOR_SEED_FAILED')
        cursor_query = '?limit=1&cursor='+page['next_cursor']
        print('device update check: stop test API, back up, migrate and grant schema 4', flush=True)
        docker.compose(['stop', '--timeout', '15', 'camera-api'], image=old_image)
        require(sql(docker, "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                            "AND backend_type='client backend' AND pid<>pg_backend_pid();") == '0',
                'DATABASE_WRITERS_NOT_QUIESCED')
        backup_dir = root/'var/camera/upgrade-backup'
        private_directory(backup_dir)
        backup = backup_database(docker, backup_dir)
        backup_digest = sha(backup)
        migrate(docker, new_image, 4, 1)
        migrate(docker, new_image, 4, 0)
        check_schema(root, docker, 4)
        verify_runtime_grants(docker)
        start_api(docker, new_image)
        verify_version(base, token, TARGET_VERSION)
        verify_resource(base, token, 'devices', DEVICE, 'upgrade-device-key', device)
        verify_resource(base, token, 'sources', SOURCE, 'upgrade-source-key', source)
        resumed = get_source_list(base, token, cursor_query)
        require(resumed['items'] == [second_source] and resumed['next_cursor'] is None, 'SOURCE_CURSOR_NOT_PRESERVED')
        print('device update check: verify rename, conflicts, durable replay and API recreation', flush=True)
        first_body = {'schema_version':'v1', 'expected_version':1, 'display_name':'전환 후 수정 장치'}
        first = patch_device(base, token, first_body, 'upgrade-device-key', False)
        old_time = datetime.fromisoformat(device['updated_at'].replace('Z', '+00:00'))
        new_time = datetime.fromisoformat(first['updated_at'].replace('Z', '+00:00'))
        require(first['version'] == 2 and first['display_name'] == first_body['display_name']
                and first['created_at'] == device['created_at'] and first['device_id'] == device['device_id']
                and first['device_kind'] == device['device_kind'] and new_time >= old_time,
                'DEVICE_UPDATE_FIELDS_INVALID')
        patch_device(base, token, first_body, 'upgrade-device-key', True, first)
        expect_update_conflict(base, token, {**first_body, 'display_name':'다른 요청'},
                               'upgrade-device-key', 'IDEMPOTENCY_CONFLICT')
        expect_update_conflict(base, token, first_body, 'stale-update-key', 'DEVICE_VERSION_CONFLICT')
        second_update = {**first_body, 'expected_version':2, 'display_name':'최신 장치 이름'}
        latest = patch_device(base, token, second_update, 'second-update-key', False)
        require(latest['version'] == 3 and latest['display_name'] == second_update['display_name'],
                'SECOND_DEVICE_UPDATE_INVALID')
        post_body = {**SOURCE, 'source_id':'upgrade-after-source', 'channel_key':'ch3'}
        post_source = seed(base, token, 'sources', post_body, 'upgrade-after-source-key')
        start_api(docker, new_image)
        verify_version(base, token, TARGET_VERSION)
        patch_device(base, token, first_body, 'upgrade-device-key', True, first)
        patch_device(base, token, second_update, 'second-update-key', True, latest)
        verify_updated_device(base, token, latest, device)
        for body, key, original in ((SOURCE, 'upgrade-source-key', source),
                                    (second_body, 'upgrade-second-source-key', second_source),
                                    (post_body, 'upgrade-after-source-key', post_source)):
            verify_resource(base, token, 'sources', body, key, original)
        require(get_source_list(base, token, cursor_query)['items'] == [second_source], 'CURSOR_AFTER_RECREATE_CHANGED')
        current_list = get_source_list(base, token)
        require(current_list['items'] == [post_source, source, second_source]
                and current_list['next_cursor'] is None, 'SOURCE_LIST_AFTER_UPDATE_INVALID')
        print('device update check: restore schema 3 in a separate test database and verify old API', flush=True)
        docker.compose(['exec', '-T', 'camera-db', 'createdb', '-U', 'camera_admin', '-T', 'template0', RESTORE_DB])
        sql(docker, 'REVOKE ALL ON DATABASE '+RESTORE_DB+' FROM PUBLIC; '
                    'GRANT CONNECT, CREATE ON DATABASE '+RESTORE_DB+' TO camera_migrator; '
                    'GRANT CONNECT ON DATABASE '+RESTORE_DB+' TO camera_runtime;')
        docker.compose(['exec', '-T', 'camera-db', 'pg_restore', '--exit-on-error', '-U', 'camera_admin',
                        '-d', RESTORE_DB], input=backup.read_bytes(), timeout=180)
        check_schema(root, docker, 3, RESTORE_DB)
        start_api(docker, old_image, 'camera-restore-check')
        verify_version(restore_base, token, OLD_VERSION)
        verify_resource(restore_base, token, 'devices', DEVICE, 'upgrade-device-key', device)
        verify_resource(restore_base, token, 'sources', SOURCE, 'upgrade-source-key', source)
        verify_resource(restore_base, token, 'sources', second_body, 'upgrade-second-source-key', second_source)
        require(get_source_list(restore_base, token)['items'] == [source, second_source], 'RESTORED_SOURCE_LIST_INVALID')
        code, value, _ = request(restore_base, '/api/v1/sources/'+post_body['source_id'], token)
        require(code == 404 and value.get('error', {}).get('code') == 'SOURCE_NOT_FOUND', 'RESTORE_CONTAINS_POST_UPGRADE_DATA')
        # Separate restoration must not replace or rewind acknowledged schema-4 data.
        verify_updated_device(base, token, latest, device)
        patch_device(base, token, first_body, 'upgrade-device-key', True, first)
        verify_resource(base, token, 'sources', post_body, 'upgrade-after-source-key', post_source)
        final_list = get_source_list(base, token)
        require(final_list['items'] == current_list['items'] and final_list['next_cursor'] is None,
                'POST_UPGRADE_SOURCE_LIST_CHANGED')
        require(sha(backup) == backup_digest, 'BACKUP_WAS_CHANGED')
        check_schema(root, docker, 4)
        docker.compose(['rm', '--stop', '--force', 'camera-restore-check'], image=old_image)
        final = docker.snapshot()
        require(protected(final) == sentinels, 'PROTECTED_SENTINELS_CHANGED')
        require(final['camera-db'] == database, 'ISOLATED_DATABASE_CONTAINER_CHANGED')
        return {'candidate_image':new_image, 'candidate_image_tag':tag, 'schema_version':4,
                **{name:True for name in CHECKS}}


def run_check(root, live, project):
    print('device update check: read production state without changing services', flush=True)
    state = inspect_upgrade(root, live)
    recipe = recipe_fingerprint(root)
    result = rehearse(root, state, project)
    after = inspect_upgrade(root, live)
    stable = ('checked_revision', 'inspector_sha256', 'docker_daemon', 'containers',
              'env_sha256', 'secret_sha256', 'step06_acceptance_sha256', 'camera_image', 'database_image')
    require(all(after[key] == state[key] for key in stable) and recipe_fingerprint(root) == recipe,
            'PRODUCTION_OR_RECIPE_CHANGED_DURING_CHECK')
    require(all(result.get(name) is True for name in CHECKS), 'REHEARSAL_INCOMPLETE')
    return {**result, 'status':'passed', 'scope':SCOPE, 'project':project,
            'checked_revision':state['checked_revision'], 'docker_daemon':state['docker_daemon'],
            'recipe_sha256':recipe, 'previous_camera_image':state['camera_image'],
            'database_image':state['database_image'], 'production_services_modified':False,
            'device_update_activated':False, 'isolated_resources_removed':True,
            'automatic_production_database_restore':False}


def execute(root, project):
    path = root/REPORT
    with activation_lock(root):
        atomic_write(path, json.dumps({'status':'running', 'project':project}).encode())
        try:
            result = run_check(root, InspectionDocker(root), project)
            atomic_write(path, (json.dumps(result, indent=2)+'\n').encode())
        except BaseException:
            atomic_write(path, json.dumps({'status':'failed', 'project':project}).encode())
            raise
    return result


def main():
    root = Path(__file__).resolve().parents[3]
    project = PREFIX+secrets.token_hex(6)
    try:
        require(len(sys.argv) == 1, 'NO_ARGUMENTS_EXPECTED')
        result = execute(root, project)
        public = {k:v for k,v in result.items() if k not in {'checked_revision', 'docker_daemon', 'recipe_sha256'}}
        public['report'] = str(root/REPORT)
        print(json.dumps(public, ensure_ascii=False))
        return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, URLError, KeyboardInterrupt) as exc:
        code = str(exc).split(':',1)[0] if isinstance(exc, ActivationError) else 'DEVICE_UPDATE_CHECK_UNAVAILABLE'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code):
            code = 'DEVICE_UPDATE_CHECK_UNAVAILABLE'
        print(json.dumps({'status':'failed', 'scope':SCOPE, 'project':project, 'code':code,
                          'production_services_modified':False, 'device_update_activated':False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
