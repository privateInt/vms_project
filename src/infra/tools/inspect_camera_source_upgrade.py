#!/usr/bin/env python3
"""Read the running step04 camera state before planning the schema-3 cutover.

No image build, container restart, migration, grant or data mutation is performed.
Only a private local report and the existing activation lock are written.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
from urllib.error import URLError

from camera_activation import (ActivationError, Docker, activation_lock,
                               atomic_write, config_endpoint, request, safe, sha)


READ_ONLY_SQL = """BEGIN READ ONLY;
SET LOCAL statement_timeout = '15000';
SELECT json_build_object(
 'database',current_database(),
 'postgres_version_num',current_setting('server_version_num')::integer,
 'database_bytes',pg_database_size(current_database()),
 'migrations',(SELECT json_agg(json_build_object('version',version,'name',name,'checksum',checksum) ORDER BY version) FROM camera.schema_migrations),
 'counts',json_build_object(
   'devices',(SELECT count(*) FROM camera.devices),
   'device_requests',(SELECT count(*) FROM camera.device_create_requests),
   'video_sources',(SELECT count(*) FROM camera.video_sources),
   'stream_profiles',(SELECT count(*) FROM camera.stream_profiles)),
 'source_request_table',to_regclass('camera.source_create_requests')::text,
 'non_runtime_clients',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend' AND pid<>pg_backend_pid() AND usename<>'camera_runtime'),
 'roles',(SELECT json_agg(json_build_object('name',rolname,'superuser',rolsuper,'create_database',rolcreatedb,'create_role',rolcreaterole) ORDER BY rolname) FROM pg_roles WHERE rolname IN ('camera_migrator','camera_runtime'))
);
COMMIT;
"""


def require(condition, code):
    if not condition:
        raise ActivationError(code)


def checked_manifest(root):
    safe(root)
    path = root/'project-manifest.json'
    safe(path)
    manifest = json.loads(path.read_text())
    require(manifest.get('storage_revision') == 'step05-source-idempotency-20260930'
            and manifest.get('activation_revision') == 'step05-source-registration-code-20260930',
            'STEP05_A_PROJECT_REQUIRED')
    require(isinstance(manifest.get('files'), dict) and manifest['files'], 'PROJECT_MANIFEST_INVALID')
    for relative, expected in manifest['files'].items():
        name = PurePosixPath(relative)
        require(not name.is_absolute() and '..' not in name.parts and '\\' not in relative,
                'PROJECT_MANIFEST_INVALID')
        item = root/relative
        safe(item)
        require(item.is_file() and sha(item) == expected, 'PROJECT_FILE_CHANGED: '+relative)
    return sha(path)


def inspect_upgrade(root, docker):
    revision = checked_manifest(root)
    daemon = docker.preflight()
    env = root/'.env'
    safe(env)
    env_digest = sha(env)
    before = docker.snapshot()
    for service in ('camera-api', 'camera-db'):
        require(service in before and before[service]['running'], 'CAMERA_SERVICES_MUST_BE_RUNNING')
    require(docker.volume_exists(), 'EXISTING_CAMERA_VOLUME_REQUIRED')
    # Read the configured project as-is; never force a different include or image.
    config = json.loads(docker.compose(['config', '--format', 'json'], active=False))
    require('camera-db' in config['services'], 'ACTIVE_CAMERA_COMPOSE_REQUIRED')
    base, token = config_endpoint(config)
    docker.redact.append(token)
    require(config['services']['camera-api'].get('environment', {}).get('CAMERA_DATABASE_URL_FILE')
            == '/run/secrets/camera_runtime_dsn', 'EXPECTED_FILE_SECRET_CONFIGURATION_REQUIRED')
    db_container = json.loads(docker.run(['inspect', before['camera-db']['id']]))[0]
    require(any(m.get('Type') == 'volume' and m.get('Name') == docker.project+'_camera-data'
                and m.get('Destination') == '/var/lib/postgresql/data'
                for m in db_container.get('Mounts', [])), 'RUNNING_DATABASE_VOLUME_MISMATCH')
    require(db_container['State'].get('Health', {}).get('Status') == 'healthy', 'DATABASE_NOT_HEALTHY')
    code, ready, _ = request(base, '/health/ready')
    require(code == 200 and ready.get('ready') is True and ready.get('scope') == 'camera_registry',
            'RUNNING_CAMERA_NOT_READY')
    code, api, _ = request(base, '/api/v1/platform', token)
    require(code == 200 and api.get('version') == '0.2.0-device-registry'
            and api.get('capabilities', {}).get('device_registry') == 'implemented',
            'EXPECTED_STEP04_RUNNING_API_REQUIRED')
    # The DB is addressed by the previously identified container ID. -q keeps
    # BEGIN/COMMIT tags out of the machine-readable single SELECT result.
    raw = docker.run(['exec', before['camera-db']['id'], 'psql', '-X', '-q', '-A', '-t',
                      '-v', 'ON_ERROR_STOP=1', '-U', 'camera_admin', '-d', 'vms_camera',
                      '-c', READ_ONLY_SQL], timeout=30)
    database = json.loads(raw)
    expected = []
    for version, filename in ((1, '0001_registry.sql'), (2, '0002_device_idempotency.sql')):
        expected.append({'version':version, 'name':'migrations/'+filename,
                         'checksum':sha(root/'src/platform/camera/internal/storage/migrations'/filename)})
    require(database.get('database') == 'vms_camera'
            and database.get('postgres_version_num', 0)//10000 == 17, 'EXPECTED_CAMERA_POSTGRESQL_17_REQUIRED')
    require(database.get('migrations') == expected and database.get('source_request_table') is None,
            'EXPECTED_SCHEMA_2_REQUIRED')
    roles = database.get('roles') or []
    require([r['name'] for r in roles] == ['camera_migrator','camera_runtime']
            and all(not r[k] for r in roles for k in ('superuser','create_database','create_role')),
            'DATABASE_ROLE_CONFIGURATION_CHANGED')
    require(database.get('non_runtime_clients') == 0, 'OTHER_DATABASE_CLIENTS_PRESENT')
    counts = database.get('counts')
    require(isinstance(counts,dict) and set(counts) == {'devices','device_requests','video_sources','stream_profiles'}
            and all(type(value) is int and value >= 0 for value in counts.values()), 'DATABASE_COUNTS_INVALID')
    after = docker.snapshot()
    require(before == after, 'PROJECT_CONTAINERS_CHANGED_DURING_INSPECTION')
    require(sha(env) == env_digest and checked_manifest(root) == revision,
            'PROJECT_CHANGED_DURING_INSPECTION')
    return {'status':'passed', 'scope':'camera_source_upgrade_preflight',
            'project':docker.project, 'endpoint':base, 'running_api_version':api['version'],
            'schema_version':2, 'target_schema_version':3, 'counts':counts,
            'database_bytes':database['database_bytes'],
            'host_backup_free_bytes':shutil.disk_usage(root/'var/camera').free,
            'camera_image':before['camera-api']['image'], 'database_image':before['camera-db']['image'],
            'checked_revision':revision, 'docker_daemon':daemon,
            'containers':before, 'production_services_modified':False,
            'source_api_activated':False, 'next_step':'prepare_and_verify_schema_3_cutover'}


def main():
    root = Path(__file__).resolve().parents[3]
    report_path = root/'var/camera/source-upgrade-preflight.json'
    # Command diagnostics are intentionally not printed: old custom Docker
    # settings may contain secrets. A failed check never authorizes a cutover.
    try:
        with activation_lock(root):
            atomic_write(report_path, b'{"status":"running"}\n')
            try:
                result = inspect_upgrade(root, Docker(root))
                result['inspector_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                atomic_write(report_path, (json.dumps(result,indent=2)+'\n').encode())
            except (ActivationError,OSError,ValueError,KeyError,TypeError,URLError):
                atomic_write(report_path, b'{"status":"failed"}\n')
                raise
        public = {k:v for k,v in result.items() if k not in {'checked_revision','docker_daemon','containers','inspector_sha256'}}
        public['report'] = str(report_path)
        print(json.dumps(public,ensure_ascii=False))
        return 0
    except (ActivationError,OSError,ValueError,KeyError,TypeError,URLError) as exc:
        code = str(exc).split(':',1)[0] if isinstance(exc,ActivationError) else 'UPGRADE_INSPECTION_UNAVAILABLE'
        print(json.dumps({'status':'failed','scope':'camera_source_upgrade_preflight','code':code,
                          'production_services_modified':False}),file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
