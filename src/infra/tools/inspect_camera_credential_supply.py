#!/usr/bin/env python3
"""Inventory the accepted registry runtime; never authorize credential activation.

Only the private report and the existing camera coordination lock are written.
Credential key contents, arbitrary authority files and backup archives are not read.
"""
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from urllib.error import URLError
from urllib.parse import urlsplit

from camera_activation import (ActivationError, Docker, activation_lock, atomic_write,
                               config_endpoint, request, safe, sha)

SCOPE = 'camera_credential_production_supply_inventory'
REPORT = 'var/camera/credential-supply-preflight.json'
RECEIPT = 'var/camera/device-delete-activation.json'
KEY = 'var/camera/credential-keys/key-bundle.json'
VERSION = '0.7.0-device-delete'
MIGRATIONS = ('0001_registry.sql', '0002_device_idempotency.sql',
              '0003_source_idempotency.sql', '0004_device_update.sql',
              '0005_source_update.sql', '0006_source_delete.sql', '0007_device_delete.sql')
ROLES = ('camera_credential_budget', 'camera_credential_writer', 'camera_maintenance')
CAPABILITIES = {
    **{name: 'implemented' for name in ('device_registry', 'device_update', 'device_delete',
        'source_contract_validation', 'source_registry', 'source_list', 'source_update', 'source_delete')},
    **{name: 'planned' for name in ('onvif_ptz', 'rtsp_ingest', 'webrtc_signaling_ingest',
        'recording', 'source_sessions', 'source_consumers')},
}
# Discard inherited PG* settings and use the official image's local socket.
# Environment defaults cannot redirect inspection to another DB or change role.
SQL_ARGS = ['env', '-i', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'psql', '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
            '-h', '/var/run/postgresql', '-p', '5432', '-U', 'camera_admin', '-d', 'vms_camera', '-c']
# One fixed SELECT, under READ ONLY. No ciphertext, HMAC, password, DSN or key ID.
READ_ONLY_SQL = """BEGIN READ ONLY;
SET LOCAL statement_timeout = '15000';
SET LOCAL lock_timeout = '3000';
SET LOCAL search_path = pg_catalog;
SELECT json_build_object(
 'database',current_database(), 'session_user',session_user, 'current_user',current_user,
 'transaction_read_only',current_setting('transaction_read_only')='on',
 'postgres_version_num',current_setting('server_version_num')::integer,
 'tls_enabled',current_setting('ssl')='on',
 'hba_path_lexically_outside_data',
    left(current_setting('hba_file'),1)='/' AND left(current_setting('data_directory'),1)='/'
    AND current_setting('hba_file')<>current_setting('data_directory')
    AND left(current_setting('hba_file'),length(rtrim(current_setting('data_directory'),'/'))+1)
        <>rtrim(current_setting('data_directory'),'/')||'/',
 'migrations',(SELECT json_agg(json_build_object('version',version,'name',name,'checksum',checksum)
                ORDER BY version) FROM camera.schema_migrations),
 'credential_storage_present',to_regclass('camera.credentials') IS NOT NULL,
 'credential_roles',COALESCE((SELECT json_agg(json_build_object(
    'name',rolname, 'login',rolcanlogin, 'superuser',rolsuper,
    'create_database',rolcreatedb, 'create_role',rolcreaterole,
    'replication',rolreplication, 'bypass_rls',rolbypassrls) ORDER BY rolname)
    FROM pg_roles WHERE rolname IN
      ('camera_credential_budget','camera_credential_writer','camera_maintenance')),'[]'::json)
);
COMMIT;
"""
NO_CHANGES = dict(production_services_modified=False, service_restart_performed=False,
    production_database_modified=False, database_schema_modified=False,
    production_key_material_read=False, production_keys_loaded=False,
    production_admission_state_created=False, production_hba_modified=False,
    environment_modified=False, credential_api_activated=False,
    production_restore_fence_implemented=False, business_runtime_ready=False)


def require(condition, code):
    if not condition:
        raise ActivationError(code)


def checked_manifest(root):
    safe(root)
    path = root/'project-manifest.json'
    safe(path)
    data = json.loads(path.read_text())
    require(data.get('version') == VERSION and data.get('storage_schema_version') == 8
        and data.get('credential_boundary_resume_native_verified') is True
        and data.get('validated_credential_boundary_resume_project_sha256') ==
            '7d3168b40749aa886f6c359cf12a1bd43e0dda634188fdd1e2998a554669e277'
        and data.get('credential_boundary_resume_production_orchestration_implemented') is False
        and data.get('business_runtime_implemented') is False, 'ACCEPTED_RESUME_SOURCE_REQUIRED')
    files = data.get('files')
    required = {'src/infra/tools/inspect_camera_credential_supply.py',
        'src/infra/tools/camera_activation.py', 'src/platform/camera/api/openapi.json',
        'src/platform/camera/internal/app/app.go', 'src/platform/camera/compose.active.yaml',
        'src/infra/postgresql/compose.camera.yaml'}
    required.update('src/platform/camera/internal/storage/migrations/'+name for name in MIGRATIONS)
    require(isinstance(files, dict) and required <= files.keys(), 'SOURCE_MANIFEST_INCOMPLETE')
    for relative, digest in files.items():
        require(isinstance(relative, str) and isinstance(digest, str)
            and re.fullmatch('[0-9a-f]{64}', digest), 'SOURCE_MANIFEST_INVALID')
        p = PurePosixPath(relative)
        require(not p.is_absolute() and p.as_posix() == relative
            and not any(x in ('..', 'var', 'build', '.git', '.env', '__pycache__') for x in p.parts),
            'SOURCE_MANIFEST_PATH_INVALID')
        target = root/relative
        safe(target)
        require(target.is_file() and sha(target) == digest, 'SOURCE_FILE_CHANGED')
    for target in (root/'src/platform').rglob('*'):
        if target.suffix in ('.go', '.sql'):
            safe(target)
            require(target.is_file() and target.relative_to(root).as_posix() in files,
                    'UNREVIEWED_PLATFORM_SOURCE_PRESENT')
    return sha(path)


class InventoryDocker(Docker):
    """Only this container's fixed read-only SQL may execute in production."""
    database_id = None

    def compose(self, args, *, active=False, **kwargs):
        require(args == ['config', '--format', 'json'] and active is False and not kwargs,
                'PRODUCTION_COMPOSE_WRITE_REJECTED')
        return super().compose(args, active=False)

    def run(self, args, **kwargs):
        valid_id = lambda v: isinstance(v, str) and re.fullmatch('[0-9a-f]{12,64}', v)
        prefix = ['compose', '--project-name', self.project, '--project-directory', str(self.root),
            '--env-file', str(self.root/'.env'), '--file', str(self.root/'compose.yaml')]
        volume = self.project+'_camera-data'
        allowed = args in (['context', 'inspect'], ['info', '--format', '{{.ID}}'],
            ['ps', '-aq', '--filter', 'label=com.docker.compose.project='+self.project],
            ['volume', 'ls', '--format', '{{.Name}}', '--filter', 'name=^'+volume+'$'],
            ['volume', 'inspect', volume], prefix+['config', '--format', 'json'])
        allowed = allowed or (len(args) >= 2 and args[0] == 'inspect'
            and all(valid_id(v) for v in args[1:]))
        allowed = allowed or (valid_id(self.database_id)
            and args == ['exec', self.database_id, *SQL_ARGS, READ_ONLY_SQL])
        require(allowed and not (kwargs.keys()-{'input', 'stdout', 'timeout', 'extra'})
            and kwargs.get('input') is None and kwargs.get('stdout') is None
            and not kwargs.get('extra'), 'PRODUCTION_DOCKER_WRITE_REJECTED')
        try:
            return super().run(args, **kwargs)
        except ActivationError:
            # Docker stderr can contain resolved environment/DSN values.
            raise ActivationError('READ_ONLY_DOCKER_COMMAND_UNAVAILABLE') from None


def read_api(base, path, token=None):
    url = urlsplit(base)
    require(url.scheme == 'http' and url.path == '' and not url.query and not url.fragment
        and url.username is None and url.password is None
        and ipaddress.ip_address(url.hostname).is_loopback, 'LOCAL_CAMERA_ENDPOINT_REQUIRED')
    require(path in ('/health/ready', '/api/v1/platform', '/openapi.json'),
            'PRODUCTION_HTTP_WRITE_REJECTED')
    return request(base, path, token)


def key_metadata(root):
    """Descriptor-relative lstat; no open/read/hash of the key file, even if unsafe."""
    safe(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fds = [os.open(root, flags)]
    snapshot = []
    def fingerprint(s):
        return (s.st_dev, s.st_ino, s.st_uid, s.st_gid, s.st_mode, s.st_nlink,
                s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    try:
        for name in ('var', 'camera', 'credential-keys'):
            try:
                s = os.stat(name, dir_fd=fds[-1], follow_symlinks=False)
            except FileNotFoundError:
                return {'status': 'missing', 'metadata_checked': True,
                    'key_material_integrity_verified': False}, tuple(snapshot)+((name, 'missing'),)
            require(stat.S_ISDIR(s.st_mode), 'KEY_DIRECTORY_SYMLINK_OR_TYPE_REJECTED')
            if name != 'var':
                require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700,
                        'KEY_DIRECTORY_OWNER_OR_MODE_REJECTED')
            fd = os.open(name, flags, dir_fd=fds[-1]); fds.append(fd)
            require(fingerprint(os.fstat(fd)) == fingerprint(s), 'KEY_DIRECTORY_CHANGED')
            # camera report writes must not be mistaken for key directory drift.
            snapshot.append((name, fingerprint(s) if name == 'credential-keys' else fingerprint(s)[:6]))
        try:
            s = os.stat('key-bundle.json', dir_fd=fds[-1], follow_symlinks=False)
        except FileNotFoundError:
            return {'status': 'missing', 'metadata_checked': True,
                'key_material_integrity_verified': False}, tuple(snapshot)+(('key-bundle.json', 'missing'),)
        require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, 'KEY_FILE_LINK_OR_TYPE_REJECTED')
        require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o600,
                'KEY_FILE_OWNER_OR_MODE_REJECTED')
        require(0 < s.st_size <= 32768, 'KEY_FILE_SIZE_REJECTED')
        return {'status': 'metadata_valid', 'metadata_checked': True,
            'directory_permissions': '0700', 'file_permissions': '0600',
            'key_material_integrity_verified': False}, tuple(snapshot)+(('key-bundle.json', fingerprint(s)),)
    finally:
        for fd in reversed(fds):
            os.close(fd)


def database_inventory(root, value):
    require(isinstance(value, dict) and value.get('database') == 'vms_camera'
        and value.get('session_user') == value.get('current_user') == 'camera_admin'
        and value.get('transaction_read_only') is True
        and type(value.get('postgres_version_num')) is int
        and value['postgres_version_num']//10000 == 17, 'READ_ONLY_DATABASE_IDENTITY_MISMATCH')
    expected = [{'version': i, 'name': 'migrations/'+name,
        'checksum': sha(root/'src/platform/camera/internal/storage/migrations'/name)}
        for i, name in enumerate(MIGRATIONS, 1)]
    require(value.get('migrations') == expected, 'ACCEPTED_SCHEMA_7_REQUIRED')
    for field in ('tls_enabled', 'hba_path_lexically_outside_data', 'credential_storage_present'):
        require(type(value.get(field)) is bool, 'DATABASE_INVENTORY_INVALID')
    require(value['credential_storage_present'] is False, 'UNREVIEWED_CREDENTIAL_TABLE_PRESENT')
    roles = value.get('credential_roles')
    fields = {'name', 'login', 'superuser', 'create_database', 'create_role', 'replication', 'bypass_rls'}
    require(isinstance(roles, list) and len(roles) <= 3, 'DATABASE_ROLE_INVENTORY_INVALID')
    seen = []
    for role in roles:
        require(isinstance(role, dict) and set(role) == fields and role['name'] in ROLES
            and all(type(role[k]) is bool for k in fields-{'name'}), 'DATABASE_ROLE_INVENTORY_INVALID')
        seen.append(role['name'])
    require(seen == sorted(set(seen)), 'DATABASE_ROLE_INVENTORY_INVALID')
    return {'schema_version': 7, 'target_schema_version': 9,
        'read_only_transaction_verified': True, 'tls_enabled': value['tls_enabled'],
        'hba_path_lexically_outside_data': value['hba_path_lexically_outside_data'],
        'hba_topology_verified': False, 'active_hba_authentication_verified': False,
        'credential_roles': roles, 'missing_credential_roles': sorted(set(ROLES)-set(seen))}


def inspect_supply(root, docker):
    revision = checked_manifest(root)
    docker.preflight()
    env = root/'.env'; safe(env); env_digest = sha(env)
    before = docker.snapshot()
    require(all(before.get(s, {}).get('running') for s in ('camera-api', 'camera-db'))
        and docker.volume_exists(), 'RUNNING_CAMERA_DATABASE_REQUIRED')
    for service in ('camera-api', 'camera-db'):
        require(re.fullmatch('sha256:[0-9a-f]{64}', before[service]['image']), 'PINNED_IMAGE_REQUIRED')
    receipt_path = root/RECEIPT; safe(receipt_path)
    receipt_digest = sha(receipt_path); receipt = json.loads(receipt_path.read_text())
    require(receipt.get('status') in ('activated', 'already_activated')
        and receipt.get('stage') == 'completed' and receipt.get('scope') == 'camera_device_delete'
        and receipt.get('project') == docker.project and receipt.get('schema_version') == 7
        and receipt.get('device_delete_activated') is True
        and receipt.get('candidate_image') == before['camera-api']['image']
        and receipt.get('database_image') == before['camera-db']['image'], 'DEVICE_DELETE_ACCEPTANCE_MISMATCH')
    key, key_before = key_metadata(root)
    config = json.loads(docker.compose(['config', '--format', 'json']))
    service = config['services']['camera-api']
    require(service.get('image') == before['camera-api']['image'], 'ACTIVE_PINNED_CAMERA_REQUIRED')
    environment = service.get('environment', {})
    require(environment.get('CAMERA_DATABASE_URL_FILE') == '/run/secrets/camera_runtime_dsn'
        and 'CAMERA_DATABASE_URL' not in environment, 'REGISTRY_FILE_DSN_CONFIGURATION_REQUIRED')
    base, token = config_endpoint(config)
    require(isinstance(token, str) and len(token) >= 24 and not token.startswith('CHANGE_ME'),
            'EXISTING_API_TOKEN_REQUIRED')
    camera = json.loads(docker.run(['inspect', before['camera-api']['id']]))[0]
    db = json.loads(docker.run(['inspect', before['camera-db']['id']]))[0]
    require(camera['Id'] == before['camera-api']['id'] and db['Id'] == before['camera-db']['id'],
            'CONTAINER_IDENTITY_MISMATCH')
    require(db['State'].get('Health', {}).get('Status') == 'healthy', 'DATABASE_NOT_HEALTHY')
    require(any(m.get('Type') == 'volume' and m.get('Name') == docker.project+'_camera-data'
        and m.get('Destination') == '/var/lib/postgresql/data' for m in db.get('Mounts', [])),
        'DATABASE_VOLUME_MISMATCH')
    mounts = camera.get('Mounts', [])
    require(any(m.get('Type') == 'bind' and m.get('Source') == str(root/'var/camera/secrets/runtime-dsn')
        and m.get('Destination') == '/run/secrets/camera_runtime_dsn' and m.get('RW') is False
        for m in mounts), 'REGISTRY_DSN_MOUNT_MISMATCH')
    env_list = camera['Config'].get('Env', [])
    require('CAMERA_DATABASE_URL_FILE=/run/secrets/camera_runtime_dsn' in env_list
        and not any(e.startswith('CAMERA_DATABASE_URL=') for e in env_list), 'RUNNING_REGISTRY_DSN_MISMATCH')
    code, ready, _ = read_api(base, '/health/ready')
    require(code == 200 and ready.get('ready') is True and ready.get('scope') == 'camera_registry'
        and ready.get('business_runtime_ready') is False, 'REGISTRY_API_NOT_READY')
    code, api, _ = read_api(base, '/api/v1/platform', token)
    require(code == 200 and api.get('version') == VERSION and api.get('stage') == 'P1_DEVICE_DELETE'
        and api.get('capabilities') == CAPABILITIES, 'ACCEPTED_REGISTRY_API_REQUIRED')
    code, specification, _ = read_api(base, '/openapi.json')
    require(code == 200 and specification == json.loads((root/'src/platform/camera/api/openapi.json').read_text()),
            'ACCEPTED_REGISTRY_OPENAPI_REQUIRED')
    docker.database_id = before['camera-db']['id']
    database = database_inventory(root, json.loads(docker.run(
        ['exec', docker.database_id, *SQL_ARGS, READ_ONLY_SQL], timeout=30)))
    configured_user = camera['Config'].get('User', '')
    uid = int(configured_user.split(':')[0]) if re.fullmatch('[0-9]+(?::[0-9]+)?', configured_user) else None
    runtime = {'configured_uid': uid, 'actual_execution_uid_verified': False,
        'read_only_rootfs': camera['HostConfig'].get('ReadonlyRootfs') is True,
        'credential_key_bind_mount_present': any(m.get('Type') == 'bind' and m.get('Source') == str(root/KEY) for m in mounts),
        'credential_key_supply_verified': False, 'approved_authority_binding': 'not_reviewed',
        'approved_endpoint_and_source_binding': 'not_reviewed',
        'credential_runtime_environment_entries': sum(bool(re.search('CREDENTIAL|ADMISSION', e.split('=', 1)[0])) for e in env_list)}
    blockers = ['SCHEMA_9_CUTOVER_NOT_PERFORMED', 'APPROVED_AUTHORITY_BINDING_NOT_REVIEWED',
        'APPROVED_ENDPOINT_AND_SOURCE_BINDING_NOT_REVIEWED', 'RUNTIME_KEY_SUPPLY_NOT_VERIFIED',
        'MAINTENANCE_HBA_BOUNDARY_NOT_VERIFIED', 'PRODUCTION_RESTORE_FENCE_NOT_IMPLEMENTED',
        'CREDENTIAL_API_NOT_IMPLEMENTED']
    if key['status'] == 'missing': blockers.append('HOST_KEY_BUNDLE_MISSING')
    if database['missing_credential_roles']: blockers.append('CREDENTIAL_DATABASE_ROLES_MISSING')
    if not database['tls_enabled']: blockers.append('DATABASE_TLS_DISABLED')
    if not database['hba_path_lexically_outside_data']: blockers.append('HBA_PATH_NOT_LEXICALLY_OUTSIDE_DATA')
    if not runtime['credential_key_bind_mount_present']: blockers.append('CREDENTIAL_KEY_MOUNT_MISSING')
    require(checked_manifest(root) == revision and sha(env) == env_digest
        and sha(receipt_path) == receipt_digest, 'INSPECTION_INPUT_CHANGED')
    require(key_metadata(root)[1] == key_before, 'KEY_METADATA_CHANGED_DURING_INSPECTION')
    require(docker.snapshot() == before, 'PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')
    return {'status': 'inspected', 'scope': SCOPE, 'inspection_completed': True,
        'readiness': 'blocked', 'production_supply_ready': False, 'activation_allowed': False,
        'project': docker.project, 'checked_revision': revision, 'endpoint': base,
        'running_api_version': VERSION, 'usage_policy': 'registry-only-v1',
        'camera_image': before['camera-api']['image'], 'database_image': before['camera-db']['image'],
        'host_key_bundle': key, 'database': database, 'runtime': runtime,
        'blockers': sorted(blockers), 'next_step': 'review_production_supply_plan', **NO_CHANGES}


def failure_code(exc):
    code = str(exc).split(':', 1)[0] if isinstance(exc, ActivationError) else 'SUPPLY_INSPECTION_UNAVAILABLE'
    return code if re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code) else 'SUPPLY_INSPECTION_UNAVAILABLE'


def run_inspection(root):
    with activation_lock(root):
        atomic_write(root/REPORT, json.dumps({'status': 'running', 'scope': SCOPE, **NO_CHANGES}).encode()+b'\n')
        try:
            value = inspect_supply(root, InventoryDocker(root))
        except BaseException as exc:
            atomic_write(root/REPORT, json.dumps({'status': 'failed', 'scope': SCOPE,
                'inspection_completed': False, 'production_supply_ready': False,
                'activation_allowed': False, 'code': failure_code(exc), **NO_CHANGES}).encode()+b'\n')
            raise
        atomic_write(root/REPORT, (json.dumps(value, indent=2)+'\n').encode())
    return value


def main():
    root = Path(__file__).resolve().parents[3]
    try:
        require(len(sys.argv) == 1, 'NO_ARGUMENTS_EXPECTED')
        result = run_inspection(root)
        print(json.dumps({**result, 'report': str(root/REPORT)}, ensure_ascii=False))
        return 0  # Completed inventory, even with expected supply blockers.
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError,
            AttributeError, URLError, KeyboardInterrupt) as exc:
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': failure_code(exc),
            'inspection_completed': False, 'production_supply_ready': False,
            'activation_allowed': False, **NO_CHANGES}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
