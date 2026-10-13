#!/usr/bin/env python3
"""Switch only camera to the rehearsed source-registry image; never restore a DB automatically."""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import stat
import sys
import tempfile
from urllib.error import URLError

from camera_activation import (ActivationError, Docker, activation_lock, atomic_write,
                               backup_database, config_endpoint, enabled_environment,
                               prepare_secrets, private_directory, request, safe, sha)
from inspect_camera_source_upgrade import READ_ONLY_SQL, checked_manifest, inspect_upgrade, require
from test_camera_source_upgrade import (migrate, pinned_image, recipe_fingerprint,
                                       verify_privileges, verify_version)

RECEIPT = 'var/camera/source-activation.json'
READ_DB_SQL = READ_ONLY_SQL.replace(" AND usename<>'camera_runtime'", '').replace(
    "'non_runtime_clients'", "'other_clients'")
CHECKS = ('schema_upgrade_verified','runtime_grants_verified','device_and_source_replay_verified',
          'api_recreation_verified','schema_2_restore_verified','old_api_on_restored_database_verified',
          'post_upgrade_data_preserved','protected_sentinels_unchanged','isolated_resources_removed')


def pin_environment(original, candidate):
    require(enabled_environment(original) == original, 'ALREADY_ACTIVE_CAMERA_CONFIGURATION_REQUIRED')
    return original+(b'\n' if not original.endswith(b'\n') else b'')+(
        'VMS_CAMERA_IMAGE='+pinned_image(candidate)+'\n').encode()


def check_receipt(root, docker):
    path = root/'var/camera/source-upgrade-check.json'
    safe(path)
    require(path.is_file(), 'RUN_SOURCE_UPGRADE_REHEARSAL_FIRST')
    receipt = json.loads(path.read_text())
    require(receipt.get('status') == 'passed'
            and receipt.get('scope') == 'camera_source_upgrade_native_docker'
            and all(receipt.get(key) is True for key in CHECKS)
            and receipt.get('production_services_modified') is False
            and receipt.get('source_api_activated') is False
            and receipt.get('automatic_production_database_restore') is False
            and receipt.get('checked_revision') == checked_manifest(root)
            and receipt.get('recipe_sha256') == recipe_fingerprint(root)
            and receipt.get('docker_daemon') == docker.preflight(), 'MATCHING_SOURCE_REHEARSAL_REQUIRED')
    for key in ('candidate_image','previous_camera_image','database_image'):
        image = pinned_image(receipt.get(key))
        require(docker.run(['image','inspect','--format','{{.Id}}',image]).decode().strip() == image,
                'REHEARSED_IMAGE_UNAVAILABLE')
    require(receipt['candidate_image'] != receipt['previous_camera_image'], 'NEW_CAMERA_IMAGE_REQUIRED')
    return receipt


def read_database(docker, database_id):
    return json.loads(docker.run(['exec',database_id,'psql','-X','-q','-A','-t',
                                  '-v','ON_ERROR_STOP=1','-U','camera_admin','-d','vms_camera',
                                  '-c',READ_DB_SQL], timeout=30))


def check_schema(root, database, version, *, quiescent=False):
    names = ('0001_registry.sql','0002_device_idempotency.sql','0003_source_idempotency.sql')
    expected = [{'version':i+1,'name':'migrations/'+name,
                 'checksum':sha(root/'src/platform/camera/internal/storage/migrations'/name)}
                for i,name in enumerate(names[:version])]
    require(database.get('database') == 'vms_camera'
            and database.get('postgres_version_num',0)//10000 == 17
            and database.get('migrations') == expected, 'DATABASE_SCHEMA_CHANGED')
    require(database.get('source_request_table') == (None if version == 2 else 'camera.source_create_requests'),
            'SOURCE_REQUEST_TABLE_MISMATCH')
    if quiescent:
        require(database.get('other_clients') == 0, 'DATABASE_CLIENTS_NOT_QUIESCED')


def unchanged_except_camera(before, after):
    return {k:v for k,v in before.items() if k != 'camera-api'} == {
        k:v for k,v in after.items() if k != 'camera-api'}


def verify_source_read(base, token):
    identifier = 'activation-read-'+secrets.token_hex(12)
    code, value, _ = request(base, '/api/v1/sources/'+identifier, token)
    require((code == 404 and value.get('error',{}).get('code') == 'SOURCE_NOT_FOUND')
            or (code == 200 and value.get('source',{}).get('source_id') == identifier),
            'SOURCE_READ_CHECK_FAILED')


def save_record(root, directory, record):
    data = (json.dumps(record,indent=2)+'\n').encode()
    atomic_write(directory/'result.json', data)
    atomic_write(root/RECEIPT, data)


def verify_completed(root, docker, previous, native):
    require(previous.get('status') == 'activated', 'INCOMPLETE_SOURCE_ACTIVATION_REQUIRES_REVIEW')
    require(previous.get('candidate_image') == native['candidate_image']
            and previous.get('checked_revision') == native['checked_revision']
            and previous.get('docker_daemon') == native['docker_daemon'], 'ACTIVATION_RECEIPT_MISMATCH')
    before = docker.snapshot()
    require(before.get('camera-api',{}).get('image') == native['candidate_image']
            and before['camera-api']['running']
            and before.get('camera-db',{}).get('image') == native['database_image']
            and before['camera-db']['running'] and docker.volume_exists(), 'ACTIVATED_SERVICE_STATE_CHANGED')
    config = json.loads(docker.compose(['config','--format','json'], active=False))
    require(config['services']['camera-api']['image'] == native['candidate_image'], 'CANDIDATE_IMAGE_PIN_CHANGED')
    base, token = config_endpoint(config)
    docker.redact.append(token)
    check_schema(root, read_database(docker,before['camera-db']['id']), 3)
    verify_version(base, token, '0.3.0-source-registry')
    verify_source_read(base, token)
    require(docker.snapshot() == before, 'CONTAINERS_CHANGED_DURING_VERIFICATION')
    return {**previous, 'status':'already_activated','service_restart_performed':False}


def activate_sources(root, docker):
    """Caller holds the camera activation lock. No rebuild, DB restart or data reset."""
    native = check_receipt(root, docker)
    record_path = root/RECEIPT
    safe(record_path)
    if record_path.exists():
        return verify_completed(root, docker, json.loads(record_path.read_text()), native)
    state = inspect_upgrade(root, docker)
    require(state['camera_image'] == native['previous_camera_image']
            and state['database_image'] == native['database_image'], 'RUNNING_IMAGES_DIFFER_FROM_REHEARSAL')
    env_path = root/'.env'
    original = env_path.read_bytes()
    mode = stat.S_IMODE(env_path.stat().st_mode)
    desired = pin_environment(original, native['candidate_image'])
    values = prepare_secrets(root, True)
    docker.redact.extend(values.values())
    secret_hashes = {name:sha(root/'var/camera/secrets'/name) for name in values}
    # Resolve candidate configuration before stopping any service. The only
    # persistent configuration change later is the camera image pin in .env.
    config = json.loads(docker.compose(['config','--format','json'], image=native['candidate_image']))
    base, token = config_endpoint(config)
    require(base == state['endpoint'], 'CAMERA_ENDPOINT_CHANGED')
    require(config['services']['camera-api']['image'] == native['candidate_image'], 'CANDIDATE_IMAGE_CONFIG_MISMATCH')
    docker.redact.append(token)
    require(shutil.disk_usage(root/'var/camera').free >= max(64*1024*1024, state['database_bytes']*2),
            'INSUFFICIENT_BACKUP_SPACE')
    before = state['containers']
    old = before['camera-api']
    db_id = before['camera-db']['id']
    backup_root = root/'var/camera/source-activation-backups'
    private_directory(backup_root)
    directory = Path(tempfile.mkdtemp(prefix='step05b3-',dir=backup_root))
    atomic_write(directory/'env.before', original)
    atomic_write(directory/'containers.before.json', json.dumps(before,indent=2).encode())
    record = {'status':'running','scope':'camera_source_registry','project':docker.project,
              'stage':'prepared','endpoint':base,'candidate_image':native['candidate_image'],
              'previous_camera_image':native['previous_camera_image'],
              'database_image':native['database_image'],'checked_revision':native['checked_revision'],
              'docker_daemon':native['docker_daemon'],'backup_directory':str(directory),
              'automatic_database_restore':False,'business_runtime_ready':False}
    save_record(root, directory, record)
    stop_requested = migration_requested = False

    def stage(value):
        record['stage'] = value
        save_record(root, directory, record)

    def unchanged(expected_env, *, stopped=False):
        require(env_path.read_bytes() == expected_env, 'CONCURRENT_ENV_EDIT_PRESERVED')
        require(checked_manifest(root) == native['checked_revision']
                and recipe_fingerprint(root) == native['recipe_sha256'], 'PROJECT_CHANGED_DURING_ACTIVATION')
        require(all(sha(root/'var/camera/secrets'/name) == digest for name,digest in secret_hashes.items()),
                'DATABASE_SECRETS_CHANGED')
        current = docker.snapshot()
        require(unchanged_except_camera(before,current), 'NON_CAMERA_CONTAINERS_CHANGED')
        if stopped:
            require(current.get('camera-api',{}).get('id') == old['id']
                    and current['camera-api']['running'] is False, 'OLD_CAMERA_NOT_STOPPED')
        return current

    try:
        require(docker.snapshot() == before, 'CONTAINERS_CHANGED_BEFORE_STOP')
        unchanged(original)
        stage('stopping_old_api')
        print('source activation: stop camera API and verify database writers are gone', flush=True)
        stop_requested = True
        docker.compose(['stop','--timeout','15','camera-api'], active=False)
        unchanged(original, stopped=True)
        database = read_database(docker, db_id)
        check_schema(root,database,2,quiescent=True)
        record['counts_before'] = database['counts']
        stage('creating_backup')
        print('source activation: back up the existing database', flush=True)
        backup = backup_database(docker,directory)
        record.update({'backup':str(backup),'backup_sha256':sha(backup)})
        database = read_database(docker,db_id)
        check_schema(root,database,2,quiescent=True)
        require(database['counts'] == record['counts_before'], 'DATA_CHANGED_DURING_BACKUP')
        unchanged(original,stopped=True)
        atomic_write(env_path,desired,mode)
        stage('migration_requested')
        # From this point a failed command may already have committed DDL.
        # Never restart the old image or automatically restore the old backup.
        migration_requested = True
        print('source activation: apply schema 3 and source runtime grants', flush=True)
        migrate(docker,native['candidate_image'],3,1)
        verify_privileges(docker)
        database = read_database(docker,db_id)
        check_schema(root,database,3,quiescent=True)
        require(database['counts'] == record['counts_before'], 'DATA_COUNTS_CHANGED_DURING_MIGRATION')
        unchanged(desired,stopped=True)
        stage('starting_source_api')
        print('source activation: start the verified source API image', flush=True)
        docker.compose(['up','-d','--no-deps','--no-build','--wait','--wait-timeout','60','camera-api'],
                       active=False, image=native['candidate_image'], timeout=100)
        verify_version(base,token,'0.3.0-source-registry')
        verify_source_read(base,token)
        current = unchanged(desired)
        require(current.get('camera-api',{}).get('image') == native['candidate_image']
                and current['camera-api']['running'], 'CANDIDATE_IMAGE_NOT_RUNNING')
        record.update({'status':'activated','stage':'completed','schema_version':3,'migration_applied':1,
                       'other_services_unchanged':True,'database_container_unchanged':True,
                       'source_api_activated':True,'service_restart_performed':True})
        save_record(root,directory,record)
        return record
    except BaseException:
        recovery = 'candidate_state_retained_manual_recovery_required' if migration_requested else 'no_service_change'
        if stop_requested and not migration_requested:
            recovery = 'manual_recovery_required'
            try:
                # Before any migration request, an exact schema-2 check permits
                # restarting the same old container without rebuilding it.
                require(env_path.read_bytes() in (original,desired), 'CONCURRENT_ENV_EDIT_PRESERVED')
                check_schema(root,read_database(docker,db_id),2)
                current = docker.snapshot()
                require(unchanged_except_camera(before,current)
                        and current.get('camera-api',{}).get('id') == old['id']
                        and current['camera-api']['image'] == old['image'], 'ORIGINAL_CONTAINER_CHANGED')
                require(all(sha(root/'var/camera/secrets'/name) == digest for name,digest in secret_hashes.items()),
                        'DATABASE_SECRETS_CHANGED')
                if env_path.read_bytes() == desired:
                    atomic_write(env_path,original,mode)
                if not current['camera-api']['running']:
                    docker.run(['start',old['id']])
                verify_version(base,token,'0.2.0-device-registry')
                recovery = 'previous_api_restarted_before_migration'
            except BaseException:
                pass
        record.update({'status':'failed','recovery':recovery,'database_and_secrets_retained':True})
        save_record(root,directory,record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({'status':'not_applied','code':'EXPLICIT_APPLY_REQUIRED'}))
        return 2
    root = Path(__file__).resolve().parents[3]
    try:
        with activation_lock(root):
            result = activate_sources(root,Docker(root))
        public = {k:v for k,v in result.items() if k not in {'checked_revision','docker_daemon'}}
        print(json.dumps(public,ensure_ascii=False))
        return 0
    except (ActivationError,OSError,ValueError,KeyError,TypeError,URLError) as exc:
        code = str(exc).split(':',1)[0] if isinstance(exc,ActivationError) else 'SOURCE_ACTIVATION_UNAVAILABLE'
        print(json.dumps({'status':'failed','scope':'camera_source_registry','code':code,
                          'report':str(root/RECEIPT),'automatic_database_restore':False}),file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
