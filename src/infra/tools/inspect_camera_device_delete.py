#!/usr/bin/env python3
"""Read the accepted step09 runtime before rehearsing the schema-7 cutover.

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

SCOPE = 'camera_device_delete_preflight'
REPORT = 'var/camera/device-delete-preflight.json'
ACCEPTANCE = 'var/camera/source-delete-activation.json'
OLD_VERSION = '0.6.0-source-delete'
TARGET_VERSION = '0.7.0-device-delete'
MIGRATIONS = ('0001_registry.sql', '0002_device_idempotency.sql',
              '0003_source_idempotency.sql', '0004_device_update.sql',
              '0005_source_update.sql', '0006_source_delete.sql', '0007_device_delete.sql')
# Reviewed step09 installs metadata routes only. New/enabled usage features
# invalidate this registry-only cutover and require a separate admission review.
OLD_CAPABILITIES = {
    **{name: 'implemented' for name in ('device_registry', 'device_update',
       'source_contract_validation', 'source_registry', 'source_list',
       'source_update', 'source_delete')},
    **{name: 'planned' for name in ('onvif_ptz', 'rtsp_ingest',
       'webrtc_signaling_ingest', 'recording', 'source_sessions', 'source_consumers')},
}
EXPECTED_RUNTIME_GRANTS = {
    'schema_usage': True, 'schema_create': False, 'migration_select': True,
    'registration_select_insert': True, 'device_update_columns': True,
    'source_update_columns': True, 'device_deleted_at_update': False,
    'table_mutations': False, 'device_immutable_update': False,
    'source_immutable_update': False,
}

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
   'source_requests',(SELECT count(*) FROM camera.source_create_requests),
   'device_update_requests',(SELECT count(*) FROM camera.device_update_requests),
   'source_update_requests',(SELECT count(*) FROM camera.source_update_requests),
   'source_delete_requests',(SELECT count(*) FROM camera.source_delete_requests)),
 'device_delete_table',to_regclass('camera.device_delete_requests')::text,
 'non_runtime_clients',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend' AND pid<>pg_backend_pid() AND usename<>'camera_runtime'),
 'roles',(SELECT json_agg(json_build_object('name',rolname,'superuser',rolsuper,'create_database',rolcreatedb,'create_role',rolcreaterole,'replication',rolreplication,'bypass_rls',rolbypassrls) ORDER BY rolname) FROM pg_roles WHERE rolname IN ('camera_migrator','camera_runtime')),
 'runtime_grants',json_build_object(
   'schema_usage',has_schema_privilege('camera_runtime','camera','USAGE'),
   'schema_create',has_schema_privilege('camera_runtime','camera','CREATE'),
   'migration_select',has_table_privilege('camera_runtime','camera.schema_migrations','SELECT'),
   'registration_select_insert',NOT EXISTS (
      SELECT 1 FROM (VALUES ('devices'),('device_create_requests'),('video_sources'),('stream_profiles'),('source_create_requests'),('device_update_requests'),('source_update_requests'),('source_delete_requests')) t(name)
      WHERE NOT has_table_privilege('camera_runtime','camera.'||name,'SELECT')
         OR NOT has_table_privilege('camera_runtime','camera.'||name,'INSERT')),
   'device_update_columns',NOT EXISTS (
      SELECT 1 FROM (VALUES ('display_name'),('version'),('updated_at')) c(name)
      WHERE NOT has_column_privilege('camera_runtime','camera.devices',name,'UPDATE')),
   'source_update_columns',NOT EXISTS (
      SELECT 1 FROM (VALUES ('display_name'),('version'),('updated_at'),('deleted_at')) c(name)
      WHERE NOT has_column_privilege('camera_runtime','camera.video_sources',name,'UPDATE')),
   'device_deleted_at_update',has_column_privilege('camera_runtime','camera.devices','deleted_at','UPDATE'),
   'table_mutations',EXISTS (
      SELECT 1 FROM (VALUES ('devices'),('device_create_requests'),('video_sources'),('stream_profiles'),('source_create_requests'),('device_update_requests'),('source_update_requests'),('source_delete_requests'),('schema_migrations')) t(name)
      WHERE has_table_privilege('camera_runtime','camera.'||name,'UPDATE')
         OR has_table_privilege('camera_runtime','camera.'||name,'DELETE')
         OR has_table_privilege('camera_runtime','camera.'||name,'TRUNCATE')),
   'device_immutable_update',EXISTS (
      SELECT 1 FROM (VALUES ('device_id'),('device_kind'),('created_at')) c(name)
      WHERE has_column_privilege('camera_runtime','camera.devices',name,'UPDATE')),
   'source_immutable_update',EXISTS (
      SELECT 1 FROM (VALUES ('source_id'),('device_id'),('channel_key'),('transport'),('input_mode'),('motion_mode'),('primary_profile_id'),('created_at')) c(name)
      WHERE has_column_privilege('camera_runtime','camera.video_sources',name,'UPDATE')))
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
            and data.get('activation_revision') == 'step10c-device-delete-http-code-20261002'
            and data.get('storage_revision') == 'step10b-device-delete-storage-20261001'
            and data.get('source_delete_api_implemented') is True
            and data.get('device_delete_storage_implemented') is True
            and data.get('device_delete_api_implemented') is True
            and data.get('device_delete_usage_policy') == 'registry-only-v1'
            and data.get('storage_schema_version') == 7
            and data.get('source_delete_usage_policy') == 'registry-only-v1'
            and data.get('business_runtime_implemented') is False, 'STEP10_C_PROJECT_REQUIRED')
    files = data.get('files')
    required = {'src/infra/tools/camera_activation.py', 'src/platform/camera/api/openapi.json',
                'src/platform/camera/internal/app/source_delete_policy.go',
                'src/platform/camera/internal/app/source_delete.go',
                'src/platform/camera/internal/app/app.go',
                'src/platform/camera/cmd/camera-api/main.go',
                'src/platform/camera/internal/app/device_delete.go',
                'src/platform/camera/internal/app/device_delete_policy.go',
                'src/platform/camera/internal/contracts/device_delete.go',
                'src/platform/camera/internal/storage/device_delete.go',
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
    # Added Go initializers or embedded SQL can change the candidate even if
    # all listed files still match. Only the reviewed implementation is allowed.
    for item in (root/'src/platform').rglob('*'):
        if item.suffix in ('.go', '.sql'):
            safe(item)
            require(item.is_file() and str(item.relative_to(root)) in files,
                    'UNREVIEWED_PLATFORM_CODE_PRESENT')
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


def read_api(base, path, token=None):
    require(path in ('/health/ready', '/api/v1/platform', '/openapi.json',
                     '/api/v1/devices?limit=1', '/api/v1/sources?limit=1'),
            'PRODUCTION_HTTP_WRITE_REJECTED')
    # The shared primitive performs GET only when body is omitted; no mutation
    # body, key or method is accepted by this wrapper.
    return request(base, path, token)


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
    require(receipt_path.is_file(), 'STEP09_ACTIVATION_RECORD_REQUIRED')
    receipt_digest = sha(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get('status') == 'activated' and receipt.get('stage') == 'completed'
            and receipt.get('scope') == 'camera_source_delete' and receipt.get('project') == docker.project
            and receipt.get('schema_version') == 6 and receipt.get('source_delete_activated') is True
            and receipt.get('candidate_image') == camera_image
            and receipt.get('database_image') == database_image, 'STEP09_ACTIVATION_RECORD_MISMATCH')
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
    code, ready, _ = read_api(base, '/health/ready')
    require(code == 200 and ready.get('ready') is True and ready.get('scope') == 'camera_registry'
            and ready.get('business_runtime_ready') is False, 'RUNNING_CAMERA_NOT_READY')
    code, api, _ = read_api(base, '/api/v1/platform', token)
    require(code == 200 and api.get('version') == OLD_VERSION and api.get('stage') == 'P1_SOURCE_DELETE'
            and api.get('capabilities') == OLD_CAPABILITIES,
            'EXPECTED_STEP09_RUNNING_API_REQUIRED')
    code, specification, _ = read_api(base, '/openapi.json')
    paths = specification.get('paths', {})
    source = paths.get('/api/v1/sources/{source_id}', {})
    device = paths.get('/api/v1/devices/{device_id}', {})
    require(code == 200 and specification.get('openapi') == '3.1.0'
            and specification.get('info', {}).get('version') == OLD_VERSION
            and source.get('delete', {}).get('operationId') == 'deleteSource'
            and {'get', 'patch'} <= device.keys() and 'delete' not in device,
            'EXPECTED_STEP09_RUNNING_OPENAPI_REQUIRED')
    code, listing, _ = read_api(base, '/api/v1/devices?limit=1', token)
    require(code == 200 and isinstance(listing.get('items'), list) and len(listing['items']) <= 1
            and 'next_cursor' in listing, 'DEVICE_LIST_READ_FAILED')
    code, listing, _ = read_api(base, '/api/v1/sources?limit=1', token)
    require(code == 200 and isinstance(listing.get('items'), list) and len(listing['items']) <= 1
            and 'next_cursor' in listing, 'SOURCE_LIST_READ_FAILED')
    database = json.loads(docker.run(['exec', before['camera-db']['id'], *SQL_ARGS, READ_ONLY_SQL], timeout=30))
    expected = [{'version':i, 'name':'migrations/'+name,
                 'checksum':sha(root/'src/platform/camera/internal/storage/migrations'/name)}
                for i, name in enumerate(MIGRATIONS[:6], 1)]
    require(database.get('database') == 'vms_camera' and type(database.get('postgres_version_num')) is int
            and database['postgres_version_num']//10000 == 17, 'EXPECTED_CAMERA_POSTGRESQL_17_REQUIRED')
    require(database.get('migrations') == expected and database.get('device_delete_table') is None,
            'EXPECTED_SCHEMA_6_REQUIRED')
    roles = database.get('roles') or []
    require([r['name'] for r in roles] == ['camera_migrator', 'camera_runtime']
            and all(r.get(k) is False for r in roles for k in ('superuser', 'create_database', 'create_role', 'replication', 'bypass_rls')),
            'DATABASE_ROLE_CONFIGURATION_CHANGED')
    grants = database.get('runtime_grants')
    require(isinstance(grants, dict) and grants == EXPECTED_RUNTIME_GRANTS
            and all(type(value) is bool for value in grants.values()),
            'EXPECTED_SCHEMA_6_RUNTIME_GRANTS_REQUIRED')
    require(type(database.get('non_runtime_clients')) is int
            and database['non_runtime_clients'] == 0, 'OTHER_DATABASE_CLIENTS_PRESENT')
    counts = database.get('counts')
    require(isinstance(counts, dict) and set(counts) == {'devices', 'device_requests', 'video_sources',
            'stream_profiles', 'source_requests', 'device_update_requests', 'source_update_requests', 'source_delete_requests'} and all(type(n) is int and n >= 0 for n in counts.values()),
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
            'target_usage_policy':'registry-only-v1', 'running_openapi_verified':True,
            'runtime_grants':grants,
            'schema_version':6, 'target_schema_version':7, 'counts':counts,
            'database_bytes':size, 'host_backup_free_bytes':free, 'minimum_backup_free_bytes':minimum,
            'camera_image':camera_image, 'database_image':database_image,
            'checked_revision':revision, 'inspector_sha256':inspector_digest,
            'docker_daemon':daemon, 'containers':before, 'env_sha256':env_digest,
            'secret_sha256':hashes, 'step09_acceptance_sha256':receipt_digest,
            'production_services_modified':False, 'device_delete_activated':False,
            'next_step':'prepare_and_verify_schema_7_cutover'}


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
            'env_sha256', 'secret_sha256', 'step09_acceptance_sha256'}}
        public['report'] = str(root/REPORT)
        print(json.dumps(public, ensure_ascii=False))
        return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, URLError, KeyboardInterrupt) as exc:
        code = str(exc).split(':', 1)[0] if isinstance(exc, ActivationError) else 'DEVICE_DELETE_INSPECTION_UNAVAILABLE'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code):
            code = 'DEVICE_DELETE_INSPECTION_UNAVAILABLE'
        print(json.dumps({'status':'failed', 'scope':SCOPE, 'code':code,
                          'production_services_modified':False, 'device_delete_activated':False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
