#!/usr/bin/env python3
"""Read the accepted step06 runtime before rehearsing the schema-4 cutover.

Only a private local report and the shared activation lock are written.
No build, restart, migration, grant, backup or API mutation is performed.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from urllib.error import URLError

from camera_activation import (ActivationError, Docker, activation_lock,
                               atomic_write, config_endpoint, request, safe, sha)

SCOPE = 'camera_device_update_preflight'
REPORT = 'var/camera/device-update-preflight.json'
ACCEPTANCE = 'var/camera/source-list-activation.json'
OLD_VERSION = '0.3.1-source-list'
TARGET_VERSION = '0.4.0-device-update'
MIGRATIONS = ('0001_registry.sql', '0002_device_idempotency.sql',
              '0003_source_idempotency.sql', '0004_device_update.sql')
SQL_ARGS = ['psql', '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
            '-U', 'camera_admin', '-d', 'vms_camera', '-c']
READ_ONLY_SQL = """BEGIN READ ONLY;
SET LOCAL statement_timeout = '15000';
SET LOCAL lock_timeout = '3000';
SELECT json_build_object(
 'database',current_database(),
 'postgres_version_num',current_setting('server_version_num')::integer,
 'database_bytes',pg_database_size(current_database()),
 'migrations',(SELECT json_agg(json_build_object('version',version,'name',name,'checksum',checksum) ORDER BY version) FROM camera.schema_migrations),
 'counts',json_build_object(
   'devices',(SELECT count(*) FROM camera.devices),
   'device_requests',(SELECT count(*) FROM camera.device_create_requests),
   'video_sources',(SELECT count(*) FROM camera.video_sources),
   'stream_profiles',(SELECT count(*) FROM camera.stream_profiles),
   'source_requests',(SELECT count(*) FROM camera.source_create_requests)),
 'device_update_table',to_regclass('camera.device_update_requests')::text,
 'non_runtime_clients',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend' AND pid<>pg_backend_pid() AND usename<>'camera_runtime'),
 'roles',(SELECT json_agg(json_build_object('name',rolname,'superuser',rolsuper,'create_database',rolcreatedb,'create_role',rolcreaterole) ORDER BY rolname) FROM pg_roles WHERE rolname IN ('camera_migrator','camera_runtime'))
);
COMMIT;
"""


def require(condition, code):
    if not condition:
        raise ActivationError(code)


def pinned_image(value):
    require(isinstance(value, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value),
            'PINNED_IMAGE_REQUIRED')
    return value


def checked_manifest(root):
    safe(root)
    path = root/'project-manifest.json'
    safe(path)
    data = json.loads(path.read_text())
    require(data.get('version') == TARGET_VERSION
            and data.get('activation_revision') == 'step07c-device-update-http-code-20260930'
            and data.get('storage_revision') == 'step07b-device-update-storage-20260930'
            and data.get('device_update_api_implemented') is True
            and data.get('storage_schema_version') == 4, 'STEP07_C_PROJECT_REQUIRED')
    files = data.get('files')
    required = {'src/infra/tools/camera_activation.py', 'src/platform/camera/api/openapi.json',
                *('src/platform/camera/internal/storage/migrations/'+name for name in MIGRATIONS)}
    require(isinstance(files, dict) and required <= files.keys(), 'PROJECT_MANIFEST_INVALID')
    for relative, expected in files.items():
        name = PurePosixPath(relative)
        require(not name.is_absolute() and '..' not in name.parts and '\\' not in relative
                and str(name) == relative and name.parts
                and name.parts[0] not in ('.env', '.git', 'var', 'build')
                and isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected),
                'PROJECT_MANIFEST_INVALID')
        item = root/relative
        safe(item)
        require(item.is_file() and sha(item) == expected, 'PROJECT_FILE_CHANGED')
    return sha(path)


class InspectionDocker(Docker):
    """Allow only the precise inspection commands used by this tool."""
    def compose(self, args, *, active=False, **kwargs):
        require(args == ['config', '--format', 'json'] and active is False and not kwargs,
                'PRODUCTION_COMPOSE_WRITE_REJECTED')
        return super().compose(args, active=False)

    def run(self, args, **kwargs):
        container_id = lambda value: isinstance(value, str) and re.fullmatch('[0-9a-f]{12,64}', value)
        prefix = ['compose', '--project-name', self.project, '--project-directory', str(self.root),
                  '--env-file', str(self.root/'.env'), '--file', str(self.root/'compose.yaml')]
        volume = self.project+'_camera-data'
        readonly = (args in (['context', 'inspect'], ['info', '--format', '{{.ID}}'],
                    ['ps', '-aq', '--filter', 'label=com.docker.compose.project='+self.project],
                    ['volume', 'ls', '--format', '{{.Name}}', '--filter', 'name=^'+volume+'$'],
                    ['volume', 'inspect', volume], prefix+['config', '--format', 'json'])
                    or (len(args) >= 2 and args[0] == 'inspect' and all(container_id(x) for x in args[1:]))
                    or (len(args) == 15 and args[0] == 'exec' and container_id(args[1])
                        and args[2:] == SQL_ARGS+[READ_ONLY_SQL]))
        require(readonly and not kwargs.get('input') and not kwargs.get('stdout')
                and not kwargs.get('extra'), 'PRODUCTION_DOCKER_WRITE_REJECTED')
        return super().run(args, **kwargs)


def secret_hashes(root):
    """Validate the existing file-secret set without creating or repairing it."""
    directory = root/'var/camera/secrets'
    safe(directory)
    require(directory.is_dir() and directory.stat().st_uid == os.getuid()
            and stat.S_IMODE(directory.stat().st_mode) == 0o700, 'EXISTING_PRIVATE_SECRETS_REQUIRED')
    values, hashes = {}, {}
    for name in ('admin-password', 'migration-password', 'runtime-password',
                 'migration-dsn', 'runtime-dsn', 'identity.json'):
        path = directory/name
        safe(path)
        mode = 0o600 if name == 'identity.json' else 0o444
        require(path.is_file() and path.stat().st_uid == os.getuid()
                and stat.S_IMODE(path.stat().st_mode) == mode, 'SECRET_FILE_STATE_INVALID')
        values[name] = path.read_text().strip()
        hashes[name] = sha(path)
    require(json.loads(values['identity.json']) == {'format':1, 'database':'vms_camera'},
            'SECRET_IDENTITY_MISMATCH')
    for name in ('admin-password', 'migration-password', 'runtime-password'):
        require(re.fullmatch('[0-9a-f]{64}', values[name]), 'SECRET_VALUE_INVALID')
    for prefix, role in (('migration', 'camera_migrator'), ('runtime', 'camera_runtime')):
        require(values[prefix+'-dsn'] == 'postgres://'+role+':'+values[prefix+'-password']
                +'@camera-db:5432/vms_camera?sslmode=disable', 'SECRET_DSN_MISMATCH')
    return hashes


def inspect_upgrade(root, docker):
    revision = checked_manifest(root)
    inspector_digest = sha(Path(__file__))
    daemon = docker.preflight()
    safe(root/'.env')
    env_digest = sha(root/'.env')
    before = docker.snapshot()
    require(all(before.get(s, {}).get('running') for s in ('camera-api', 'camera-db'))
            and docker.volume_exists(), 'RUNNING_CAMERA_AND_DATABASE_REQUIRED')
    camera_image = pinned_image(before['camera-api']['image'])
    database_image = pinned_image(before['camera-db']['image'])
    receipt_path = root/ACCEPTANCE
    safe(receipt_path)
    require(receipt_path.is_file(), 'STEP06_ACTIVATION_RECORD_REQUIRED')
    receipt_digest = sha(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get('status') == 'activated' and receipt.get('stage') == 'completed'
            and receipt.get('scope') == 'camera_source_list' and receipt.get('project') == docker.project
            and receipt.get('schema_version') == 3 and receipt.get('source_list_activated') is True
            and receipt.get('candidate_image') == camera_image
            and receipt.get('database_image') == database_image, 'STEP06_ACTIVATION_RECORD_MISMATCH')
    hashes = secret_hashes(root)
    config = json.loads(docker.compose(['config', '--format', 'json']))
    services = config['services']
    require('camera-db' in services and services['camera-api'].get('image') == camera_image,
            'ACTIVE_PINNED_CAMERA_REQUIRED')
    environment = services['camera-api'].get('environment', {})
    require(environment.get('CAMERA_DATABASE_URL_FILE') == '/run/secrets/camera_runtime_dsn'
            and 'CAMERA_DATABASE_URL' not in environment, 'EXPECTED_FILE_SECRET_CONFIGURATION_REQUIRED')
    base, token = config_endpoint(config)
    docker.redact.append(token)
    db = json.loads(docker.run(['inspect', before['camera-db']['id']]))[0]
    require(db['State'].get('Health', {}).get('Status') == 'healthy', 'DATABASE_NOT_HEALTHY')
    require(any(m.get('Type') == 'volume' and m.get('Name') == docker.project+'_camera-data'
                and m.get('Destination') == '/var/lib/postgresql/data' for m in db.get('Mounts', [])),
            'RUNNING_DATABASE_VOLUME_MISMATCH')
    camera = json.loads(docker.run(['inspect', before['camera-api']['id']]))[0]
    require(any(m.get('Type') == 'bind' and m.get('Source') == str(root/'var/camera/secrets/runtime-dsn')
                and m.get('Destination') == '/run/secrets/camera_runtime_dsn' and m.get('RW') is False
                for m in camera.get('Mounts', [])), 'RUNNING_CAMERA_SECRET_MOUNT_MISMATCH')
    code, ready, _ = request(base, '/health/ready')
    require(code == 200 and ready.get('ready') is True and ready.get('scope') == 'camera_registry'
            and ready.get('business_runtime_ready') is False, 'RUNNING_CAMERA_NOT_READY')
    code, api, _ = request(base, '/api/v1/platform', token)
    require(code == 200 and api.get('version') == OLD_VERSION and api.get('stage') == 'P1_SOURCE_LISTING'
            and all(api.get('capabilities', {}).get(c) == 'implemented'
                    for c in ('device_registry', 'source_registry', 'source_list')),
            'EXPECTED_STEP06_RUNNING_API_REQUIRED')
    code, listing, _ = request(base, '/api/v1/sources?limit=1', token)
    require(code == 200 and isinstance(listing.get('items'), list) and len(listing['items']) <= 1
            and 'next_cursor' in listing, 'SOURCE_LIST_READ_FAILED')
    database = json.loads(docker.run(['exec', before['camera-db']['id'], *SQL_ARGS, READ_ONLY_SQL], timeout=30))
    expected = [{'version':i, 'name':'migrations/'+name,
                 'checksum':sha(root/'src/platform/camera/internal/storage/migrations'/name)}
                for i, name in enumerate(MIGRATIONS[:3], 1)]
    require(database.get('database') == 'vms_camera' and type(database.get('postgres_version_num')) is int
            and database['postgres_version_num']//10000 == 17, 'EXPECTED_CAMERA_POSTGRESQL_17_REQUIRED')
    require(database.get('migrations') == expected and database.get('device_update_table') is None,
            'EXPECTED_SCHEMA_3_REQUIRED')
    roles = database.get('roles') or []
    require([r['name'] for r in roles] == ['camera_migrator', 'camera_runtime']
            and all(r.get(k) is False for r in roles for k in ('superuser', 'create_database', 'create_role')),
            'DATABASE_ROLE_CONFIGURATION_CHANGED')
    require(database.get('non_runtime_clients') == 0, 'OTHER_DATABASE_CLIENTS_PRESENT')
    counts = database.get('counts')
    require(isinstance(counts, dict) and set(counts) == {'devices', 'device_requests', 'video_sources',
            'stream_profiles', 'source_requests'} and all(type(n) is int and n >= 0 for n in counts.values()),
            'DATABASE_COUNTS_INVALID')
    size = database.get('database_bytes')
    require(type(size) is int and size > 0, 'DATABASE_SIZE_INVALID')
    free = shutil.disk_usage(root/'var/camera').free
    minimum = max(size*2, 64*1024*1024)
    require(free >= minimum, 'BACKUP_SPACE_INSUFFICIENT')
    require(docker.snapshot() == before, 'PROJECT_CONTAINERS_CHANGED_DURING_INSPECTION')
    require(sha(root/'.env') == env_digest and secret_hashes(root) == hashes
            and sha(receipt_path) == receipt_digest and checked_manifest(root) == revision
            and sha(Path(__file__)) == inspector_digest, 'PROJECT_CHANGED_DURING_INSPECTION')
    return {'status':'passed', 'scope':SCOPE, 'project':docker.project, 'endpoint':base,
            'running_api_version':OLD_VERSION, 'target_api_version':TARGET_VERSION,
            'schema_version':3, 'target_schema_version':4, 'counts':counts,
            'database_bytes':size, 'host_backup_free_bytes':free, 'minimum_backup_free_bytes':minimum,
            'camera_image':camera_image, 'database_image':database_image,
            'checked_revision':revision, 'inspector_sha256':inspector_digest,
            'docker_daemon':daemon, 'containers':before, 'env_sha256':env_digest,
            'secret_sha256':hashes, 'step06_acceptance_sha256':receipt_digest,
            'production_services_modified':False, 'device_update_activated':False,
            'next_step':'prepare_and_verify_schema_4_cutover'}


def run_inspection(root):
    report_path = root/REPORT
    with activation_lock(root):
        atomic_write(report_path, b'{"status":"running"}\n')
        try:
            result = inspect_upgrade(root, InspectionDocker(root))
            atomic_write(report_path, (json.dumps(result, indent=2)+'\n').encode())
        except BaseException:
            atomic_write(report_path, b'{"status":"failed"}\n')
            raise
    return result


def main():
    root = Path(__file__).resolve().parents[3]
    try:
        require(len(sys.argv) == 1, 'NO_ARGUMENTS_EXPECTED')
        result = run_inspection(root)
        public = {key:value for key,value in result.items() if key not in {
            'checked_revision', 'inspector_sha256', 'docker_daemon', 'containers',
            'env_sha256', 'secret_sha256', 'step06_acceptance_sha256'}}
        public['report'] = str(root/REPORT)
        print(json.dumps(public, ensure_ascii=False))
        return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, URLError, KeyboardInterrupt) as exc:
        code = str(exc).split(':', 1)[0] if isinstance(exc, ActivationError) else 'DEVICE_UPDATE_INSPECTION_UNAVAILABLE'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code):
            code = 'DEVICE_UPDATE_INSPECTION_UNAVAILABLE'
        print(json.dumps({'status':'failed', 'scope':SCOPE, 'code':code,
                          'production_services_modified':False, 'device_update_activated':False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
