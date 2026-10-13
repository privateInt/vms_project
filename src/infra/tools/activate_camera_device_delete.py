#!/usr/bin/env python3
"""Activate the rehearsed schema-7 camera image with a quiescent schema-6 backup."""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from urllib.error import URLError

from camera_activation import (ActivationError, Docker, activation_lock, atomic_write,
                               backup_database, config_endpoint, private_directory, safe, sha)
from inspect_camera_device_delete import (ACCEPTANCE, InspectionDocker, MIGRATIONS, OLD_VERSION,
    TARGET_VERSION, EXPECTED_RUNTIME_GRANTS, READ_ONLY_SQL, SQL_ARGS, checked_manifest, inspect_upgrade, pinned_image,
    require, secret_hashes)
from camera_activation import request
from test_camera_device_delete_upgrade import (CHECKS, PREFIX, REPORT, SCOPE, get_source_list,
    migrate, recipe_fingerprint, verify_runtime_grants, verify_version)
from activate_camera_source_list import pin_environment
from activate_camera_sources import unchanged_except_camera

RECEIPT = 'var/camera/device-delete-activation.json'
ACTIVATION_SCOPE = 'camera_device_delete'
FINGERPRINT_TABLES = ('devices', 'device_create_requests', 'video_sources', 'stream_profiles',
                      'source_create_requests', 'device_update_requests', 'source_update_requests',
                      'source_delete_requests')
FINGERPRINT_FIELDS = ','.join(
    "'"+table+"',(SELECT md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text,'[]')) FROM camera."
    +table+' t)' for table in FINGERPRINT_TABLES)
READ_DB_SQL = READ_ONLY_SQL.replace(" AND usename<>'camera_runtime'", '').replace(
    "'non_runtime_clients'", "'other_clients'").replace(
    " 'database',current_database(),", " 'registry_fingerprint',json_build_object("+FINGERPRINT_FIELDS+"),\n 'database',current_database(),")
READ_DEVICE_DELETE_COUNT_SQL = """BEGIN READ ONLY;
SET LOCAL statement_timeout = '15000';
SET LOCAL lock_timeout = '3000';
SELECT count(*) FROM camera.device_delete_requests;
COMMIT;
"""
UP = ['up', '-d', '--no-deps', '--no-build', '--pull', 'never',
      '--wait', '--wait-timeout', '60', 'camera-api']


def check_receipt(root, docker):
    path = root/REPORT
    safe(path)
    require(path.is_file(), 'RUN_DEVICE_DELETE_REHEARSAL_FIRST')
    digest = sha(path)
    value = json.loads(path.read_text())
    require(value.get('status') == 'passed' and value.get('scope') == SCOPE
            and value.get('schema_version') == 7 and value.get('previous_schema_version') == 6
            and value.get('usage_policy') == 'registry-only-v1'
            and re.fullmatch(PREFIX+r'[0-9a-f]{12}', value.get('project', ''))
            and all(value.get(key) is True for key in (*CHECKS, 'isolated_resources_removed'))
            and value.get('production_services_modified') is False
            and value.get('device_delete_activated') is False
            and value.get('automatic_production_database_restore') is False
            and value.get('checked_revision') == checked_manifest(root)
            and value.get('recipe_sha256') == recipe_fingerprint(root)
            and value.get('docker_daemon') == docker.preflight(), 'MATCHING_DEVICE_DELETE_REHEARSAL_REQUIRED')
    for key in ('candidate_image', 'previous_camera_image', 'database_image'):
        image = pinned_image(value.get(key))
        require(docker.run(['image', 'inspect', '--format', '{{.Id}}', image]).decode().strip() == image,
                'REHEARSED_IMAGE_UNAVAILABLE')
    require(value['candidate_image'] != value['previous_camera_image'], 'NEW_CAMERA_IMAGE_REQUIRED')
    require(sha(path) == digest, 'REHEARSAL_RECEIPT_CHANGED')
    return {**value, 'receipt_sha256':digest}


def read_database(docker, database_id):
    return json.loads(docker.run(['exec', database_id, *SQL_ARGS, READ_DB_SQL], timeout=30))


def read_device_delete_count(docker, database_id):
    value = json.loads(docker.run(['exec', database_id, *SQL_ARGS, READ_DEVICE_DELETE_COUNT_SQL], timeout=30))
    require(type(value) is int and value >= 0, 'DEVICE_DELETE_COUNT_INVALID')
    return value


def check_schema(root, database, version, *, quiescent=False):
    require(version in (6, 7), 'UNEXPECTED_SCHEMA_VERSION')
    expected = [{'version':i, 'name':'migrations/'+name,
                 'checksum':sha(root/'src/platform/camera/internal/storage/migrations'/name)}
                for i, name in enumerate(MIGRATIONS[:version], 1)]
    require(database.get('database') == 'vms_camera'
            and type(database.get('postgres_version_num')) is int
            and database['postgres_version_num']//10000 == 17
            and database.get('migrations') == expected, 'DATABASE_SCHEMA_CHANGED')
    require(database.get('device_delete_table') == (None if version == 6 else 'camera.device_delete_requests'),
            'DEVICE_DELETE_TABLE_MISMATCH')
    roles = database.get('roles') or []
    require([r['name'] for r in roles] == ['camera_migrator', 'camera_runtime']
            and all(r.get(k) is False for r in roles for k in ('superuser', 'create_database', 'create_role', 'replication', 'bypass_rls')),
            'DATABASE_ROLE_CONFIGURATION_CHANGED')
    counts = database.get('counts')
    require(isinstance(counts, dict) and set(counts) == {'devices', 'device_requests', 'video_sources',
            'stream_profiles', 'source_requests', 'device_update_requests', 'source_update_requests', 'source_delete_requests'} and all(type(n) is int and n >= 0 for n in counts.values()),
            'DATABASE_COUNTS_INVALID')
    expected_grants = {**EXPECTED_RUNTIME_GRANTS, 'device_deleted_at_update':version == 7}
    grants = database.get('runtime_grants')
    require(isinstance(grants, dict) and grants == expected_grants
            and all(type(value) is bool for value in grants.values()), 'DATABASE_RUNTIME_GRANTS_CHANGED')
    fingerprint = database.get('registry_fingerprint')
    require(isinstance(fingerprint, dict) and set(fingerprint) == set(FINGERPRINT_TABLES)
            and all(isinstance(value, str) and re.fullmatch('[0-9a-f]{32}', value) for value in fingerprint.values()),
            'DATABASE_FINGERPRINT_INVALID')
    if quiescent:
        require(type(database.get('other_clients')) is int and database['other_clients'] == 0,
                'DATABASE_CLIENTS_NOT_QUIESCED')


def verify_reads(base, token):
    # Only GET requests are used for live acceptance; DELETE/PATCH semantics were
    # checked in D2 against this exact image and disposable data.
    verify_version(base, token, TARGET_VERSION)
    value = get_source_list(base, token, '?limit=1')
    require(len(value['items']) <= 1, 'SOURCE_LIST_LIMIT_NOT_APPLIED')
    code, value, _ = request(base, '/api/v1/devices?limit=1', token)
    require(code == 200 and isinstance(value.get('items'), list) and len(value['items']) <= 1
            and 'next_cursor' in value, 'DEVICE_LIST_READ_FAILED')
    code, value, _ = request(base, '/openapi.json')
    paths = value.get('paths', {})
    require(code == 200 and value.get('openapi') == '3.1.0'
            and value.get('info', {}).get('version') == TARGET_VERSION
            and paths.get('/api/v1/devices/{device_id}', {}).get('delete', {}).get('operationId') == 'deleteDevice'
            and paths.get('/api/v1/sources/{source_id}', {}).get('delete', {}).get('operationId') == 'deleteSource',
            'DEVICE_DELETE_RUNNING_OPENAPI_MISMATCH')


def verify_bound_storage(root, docker, containers, config):
    environment = config['services']['camera-api'].get('environment', {})
    require(environment.get('CAMERA_DATABASE_URL_FILE') == '/run/secrets/camera_runtime_dsn'
            and 'CAMERA_DATABASE_URL' not in environment, 'EXPECTED_FILE_SECRET_CONFIGURATION_REQUIRED')
    database = json.loads(docker.run(['inspect', containers['camera-db']['id']]))[0]
    require(database['State'].get('Health', {}).get('Status') == 'healthy', 'DATABASE_NOT_HEALTHY')
    require(any(m.get('Type') == 'volume' and m.get('Name') == docker.project+'_camera-data'
                and m.get('Destination') == '/var/lib/postgresql/data' for m in database.get('Mounts', [])),
            'RUNNING_DATABASE_VOLUME_MISMATCH')
    camera = json.loads(docker.run(['inspect', containers['camera-api']['id']]))[0]
    require(any(m.get('Type') == 'bind' and m.get('Source') == str(root/'var/camera/secrets/runtime-dsn')
                and m.get('Destination') == '/run/secrets/camera_runtime_dsn' and m.get('RW') is False
                for m in camera.get('Mounts', [])), 'RUNNING_CAMERA_SECRET_MOUNT_MISMATCH')


def save_record(root, directory, record):
    body = (json.dumps(record, indent=2)+'\n').encode()
    atomic_write(directory/'result.json', body)
    atomic_write(root/RECEIPT, body)


def verify_completed(root, docker, record, native):
    require(record.get('status') == 'activated' and record.get('stage') == 'completed',
            'INCOMPLETE_DEVICE_DELETE_ACTIVATION_REQUIRES_REVIEW')
    require(record.get('scope') == ACTIVATION_SCOPE and record.get('project') == docker.project
            and record.get('schema_version') == 7 and record.get('device_delete_activated') is True
            and record.get('usage_policy') == 'registry-only-v1',
            'ACTIVATION_RECEIPT_MISMATCH')
    for key in ('candidate_image', 'previous_camera_image', 'database_image',
                'checked_revision', 'docker_daemon', 'recipe_sha256', 'receipt_sha256'):
        require(record.get(key) == native[key], 'ACTIVATION_RECEIPT_MISMATCH')
    tool_digest = sha(root/'src/infra/tools/activate_camera_device_delete.py')
    require(record.get('activation_tool_sha256') == tool_digest, 'ACTIVATION_TOOL_CHANGED')
    before = docker.snapshot()
    require(before.get('camera-api', {}).get('image') == native['candidate_image']
            and before['camera-api']['running']
            and before.get('camera-db', {}).get('image') == native['database_image']
            and before['camera-db']['running'] and docker.volume_exists(), 'ACTIVATED_SERVICE_STATE_CHANGED')
    safe(root/'.env')
    env_digest = sha(root/'.env')
    hashes = secret_hashes(root)
    config = json.loads(docker.compose(['config', '--format', 'json'], active=False))
    require(config['services']['camera-api']['image'] == native['candidate_image'], 'CANDIDATE_IMAGE_PIN_CHANGED')
    base, token = config_endpoint(config)
    require(base == record['endpoint'], 'CAMERA_ENDPOINT_CHANGED')
    docker.redact.append(token)
    verify_bound_storage(root, docker, before, config)
    check_schema(root, read_database(docker, before['camera-db']['id']), 7)
    read_device_delete_count(docker, before['camera-db']['id'])
    verify_runtime_grants(docker)
    verify_reads(base, token)
    require(docker.snapshot() == before and sha(root/'.env') == env_digest
            and secret_hashes(root) == hashes and checked_manifest(root) == native['checked_revision']
            and recipe_fingerprint(root) == native['recipe_sha256']
            and sha(root/REPORT) == native['receipt_sha256']
            and sha(root/'src/infra/tools/activate_camera_device_delete.py') == tool_digest,
            'PROJECT_CHANGED_DURING_VERIFICATION')
    return {**record, 'status':'already_activated', 'service_restart_performed':False}


def activate(root, docker):
    """Caller holds activation_lock. Failed/interrupted attempts require review."""
    native = check_receipt(root, docker)
    record_path = root/RECEIPT
    safe(record_path)
    if record_path.exists():
        return verify_completed(root, docker, json.loads(record_path.read_text()), native)
    state = inspect_upgrade(root, InspectionDocker(root))
    require(state['camera_image'] == native['previous_camera_image']
            and state['database_image'] == native['database_image']
            and state['checked_revision'] == native['checked_revision']
            and state['docker_daemon'] == native['docker_daemon'], 'LIVE_STATE_DIFFERS_FROM_REHEARSAL')
    env = root/'.env'
    safe(env)
    original, mode = env.read_bytes(), stat.S_IMODE(env.stat().st_mode)
    desired = pin_environment(original, native['previous_camera_image'], native['candidate_image'])
    config = json.loads(docker.compose(['config', '--format', 'json'], active=False))
    candidate_config = json.loads(docker.compose(['config', '--format', 'json'], active=False,
                                                image=native['candidate_image']))
    base, token = config_endpoint(config)
    docker.redact.append(token)
    expected_config = copy.deepcopy(config)
    for service in ('camera-api', 'camera-migrate'):
        if service in expected_config['services']:
            expected_config['services'][service]['image'] = native['candidate_image']
    require(candidate_config == expected_config and base == state['endpoint'], 'CANDIDATE_CONFIGURATION_CHANGED')
    require(shutil.disk_usage(root/'var/camera').free >= max(64*1024*1024, state['database_bytes']*2),
            'INSUFFICIENT_BACKUP_SPACE')
    before, old = state['containers'], state['containers']['camera-api']
    db_id = before['camera-db']['id']
    script = root/'src/infra/tools/activate_camera_device_delete.py'
    script_digest = sha(script)
    backup_root = root/'var/camera/device-delete-activation-backups'
    private_directory(backup_root)
    directory = Path(tempfile.mkdtemp(prefix='step10d3-', dir=backup_root))
    atomic_write(directory/'env.before', original)
    atomic_write(directory/'containers.before.json', json.dumps(before, indent=2).encode())
    record = {key:native[key] for key in ('candidate_image', 'previous_camera_image', 'database_image',
                'checked_revision', 'docker_daemon', 'recipe_sha256', 'receipt_sha256')}
    record.update({'status':'running', 'scope':ACTIVATION_SCOPE, 'project':docker.project,
                   'stage':'prepared', 'endpoint':base, 'backup_directory':str(directory),
                   'activation_tool_sha256':script_digest,
                   'automatic_database_restore':False, 'business_runtime_ready':False,
                   'usage_policy':'registry-only-v1'})
    save_record(root, directory, record)
    stop_requested = migration_requested = False

    def stage(value):
        record['stage'] = value
        save_record(root, directory, record)

    def guard(expected_env, *, stopped=False):
        safe(env)
        require(env.read_bytes() == expected_env, 'CONCURRENT_ENV_EDIT_PRESERVED')
        require(checked_manifest(root) == native['checked_revision']
                and recipe_fingerprint(root) == native['recipe_sha256']
                and sha(root/REPORT) == native['receipt_sha256']
                and sha(root/ACCEPTANCE) == state['step09_acceptance_sha256']
                and sha(script) == script_digest, 'PROJECT_OR_RECEIPT_CHANGED')
        require(secret_hashes(root) == state['secret_sha256'], 'DATABASE_SECRETS_CHANGED')
        current = docker.snapshot()
        require(unchanged_except_camera(before, current), 'NON_CAMERA_CONTAINERS_CHANGED')
        if stopped:
            require(current.get('camera-api', {}).get('id') == old['id']
                    and current['camera-api']['image'] == old['image']
                    and current['camera-api']['running'] is False, 'OLD_CAMERA_NOT_STOPPED')
        return current

    try:
        require(guard(original) == before and sha(env) == state['env_sha256'], 'STATE_CHANGED_BEFORE_STOP')
        stage('stopping_old_api')
        print('device delete activation: stop camera API and verify database writers are gone', flush=True)
        stop_requested = True
        docker.compose(['stop', '--timeout', '15', 'camera-api'], active=False)
        guard(original, stopped=True)
        database = read_database(docker, db_id)
        check_schema(root, database, 6, quiescent=True)
        record['counts_before'] = database['counts']
        record['registry_fingerprint_before'] = database['registry_fingerprint']
        stage('creating_backup')
        print('device delete activation: back up the existing schema 6 database', flush=True)
        backup = backup_database(docker, directory)
        record.update({'backup':str(backup), 'backup_sha256':sha(backup)})
        database = read_database(docker, db_id)
        check_schema(root, database, 6, quiescent=True)
        require(database['counts'] == record['counts_before'], 'DATA_CHANGED_DURING_BACKUP')
        require(database['registry_fingerprint'] == record['registry_fingerprint_before'], 'ROWS_CHANGED_DURING_BACKUP')
        guard(original, stopped=True)
        atomic_write(env, desired, mode)
        guard(desired, stopped=True)
        require(sha(backup) == record['backup_sha256'], 'BACKUP_CHANGED_BEFORE_MIGRATION')
        stage('migration_requested')
        # An error may arrive after DDL has committed. Preserve the database
        # and candidate pin from this boundary, including on interruption.
        migration_requested = True
        print('device delete activation: apply schema 7 and device delete runtime grants', flush=True)
        migrate(docker, native['candidate_image'], 7, 1)
        verify_runtime_grants(docker)
        database = read_database(docker, db_id)
        check_schema(root, database, 7, quiescent=True)
        require(database['counts'] == record['counts_before'], 'DATA_COUNTS_CHANGED_DURING_MIGRATION')
        require(database['registry_fingerprint'] == record['registry_fingerprint_before'], 'ROWS_CHANGED_DURING_MIGRATION')
        require(read_device_delete_count(docker, db_id) == 0, 'NEW_DEVICE_DELETE_JOURNAL_NOT_EMPTY')
        guard(desired, stopped=True)
        stage('starting_device_delete_api')
        print('device delete activation: start the verified camera API image', flush=True)
        docker.compose(UP, active=False, image=native['candidate_image'], timeout=100)
        verify_reads(base, token)
        check_schema(root, read_database(docker, db_id), 7)
        current = guard(desired)
        require(current.get('camera-api', {}).get('image') == native['candidate_image']
                and current['camera-api']['running'], 'CANDIDATE_IMAGE_NOT_RUNNING')
        verify_bound_storage(root, docker, current, candidate_config)
        record.update({'status':'activated', 'stage':'completed', 'schema_version':7, 'migration_applied':1,
                       'other_services_unchanged':True, 'database_container_unchanged':True,
                       'device_delete_activated':True, 'service_restart_performed':True,
                       'existing_rows_preserved':True, 'new_device_delete_journal_empty_at_cutover':True})
        save_record(root, directory, record)
        return record
    except BaseException:
        recovery = 'candidate_state_retained_manual_recovery_required' if migration_requested else 'no_service_change'
        if stop_requested and not migration_requested:
            recovery = 'manual_recovery_required'
            try:
                safe(env)
                actual = env.read_bytes()
                require(actual in (original, desired), 'CONCURRENT_ENV_EDIT_PRESERVED')
                current = guard(actual)
                check_schema(root, read_database(docker, db_id), 6)
                require(current.get('camera-api', {}).get('id') == old['id']
                        and current['camera-api']['image'] == old['image'], 'ORIGINAL_CONTAINER_CHANGED')
                if actual == desired:
                    atomic_write(env, original, mode)
                if not current['camera-api']['running']:
                    docker.run(['start', old['id']])
                verify_version(base, token, OLD_VERSION)
                recovery = 'previous_api_restarted_before_migration'
            except BaseException:
                pass
        record.update({'status':'failed', 'recovery':recovery,
                       'device_delete_activated':None if migration_requested else False,
                       'database_restore_performed':False, 'database_and_secrets_retained':True})
        save_record(root, directory, record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({'status':'not_applied', 'code':'EXPLICIT_APPLY_REQUIRED'}))
        return 2
    root = Path(__file__).resolve().parents[3]
    try:
        with activation_lock(root):
            result = activate(root, Docker(root))
        private = {'checked_revision', 'docker_daemon', 'recipe_sha256', 'receipt_sha256', 'activation_tool_sha256',
                   'registry_fingerprint_before'}
        print(json.dumps({k:v for k,v in result.items() if k not in private}, ensure_ascii=False))
        return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, URLError, KeyboardInterrupt) as exc:
        code = str(exc).split(':', 1)[0] if isinstance(exc, ActivationError) else 'DEVICE_DELETE_ACTIVATION_UNAVAILABLE'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code):
            code = 'DEVICE_DELETE_ACTIVATION_UNAVAILABLE'
        print(json.dumps({'status':'failed', 'scope':ACTIVATION_SCOPE, 'code':code,
                          'report':str(root/RECEIPT), 'automatic_database_restore':False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
