#!/usr/bin/env python3
"""Activate the rehearsed source-list image only. No database changes or image builds."""
import argparse
import json
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.error import URLError

from camera_activation import (ActivationError, Docker, activation_lock, atomic_write,
                               config_endpoint, prepare_secrets, private_directory, safe, sha)
from inspect_camera_source_upgrade import require
from activate_camera_sources import check_schema, read_database, unchanged_except_camera
from test_camera_source_upgrade import pinned_image, verify_version
from test_camera_source_list_image import (InspectionDocker, OLD_VERSION, REPORT, SCOPE,
                                           checked_manifest, get_list, inspect_live,
                                           recipe_fingerprint, verify_candidate)

RECEIPT = 'var/camera/source-list-activation.json'
CHECKS = ('source_list_verified', 'api_recreation_verified', 'image_only_rollback_verified',
          'post_switch_data_preserved', 'isolated_database_unchanged', 'isolated_resources_removed')
UP = ['up', '-d', '--no-deps', '--no-build', '--pull', 'never',
      '--wait', '--wait-timeout', '60', 'camera-api']


class CameraSwitchDocker(InspectionDocker):
    """Allow one camera-only image switch in addition to read-only inspection."""
    def compose(self, args, *, active=False, image=None, **kwargs):
        require(active is False and args in (['config', '--format', 'json'], UP),
                'CAMERA_ONLY_COMPOSE_REQUIRED')
        if image is not None:
            pinned_image(image)
        require(args != UP or image is not None, 'PINNED_IMAGE_REQUIRED')
        return Docker.compose(self, args, active=False, image=image, **kwargs)

    def run(self, args, **kwargs):
        compose_prefix = ['compose', '--project-name', self.project, '--project-directory', str(self.root),
                          '--env-file', str(self.root/'.env'), '--file', str(self.root/'compose.yaml')]
        if args == compose_prefix+UP:
            extra = kwargs.get('extra') or {}
            require(set(extra) == {'VMS_CAMERA_IMAGE'}, 'CAMERA_IMAGE_OVERRIDE_REQUIRED')
            pinned_image(extra['VMS_CAMERA_IMAGE'])
            return Docker.run(self, args, **kwargs)
        if args[:4] == ['image', 'inspect', '--format', '{{.Id}}'] and len(args) == 5:
            pinned_image(args[4])
            return Docker.run(self, args, **kwargs)
        return super().run(args, **kwargs)


def pin_environment(original, previous, candidate):
    """Replace the single canonical pin written by step05; preserve all other bytes."""
    previous, candidate = pinned_image(previous).encode(), pinned_image(candidate).encode()
    require(not re.search(rb'(?m)^[ \t]*(?:export[ \t]+)?COMPOSE_(?:FILE|PROJECT_NAME)[ \t]*=', original),
            'CUSTOM_COMPOSE_CONFIGURATION_REQUIRES_REVIEW')
    assignments = re.findall(rb'(?m)^[ \t]*(?:export[ \t]+)?VMS_CAMERA_IMAGE[ \t]*=', original)
    matches = list(re.finditer(rb'(?m)^VMS_CAMERA_IMAGE=(sha256:[0-9a-f]{64})\r?$', original))
    require(len(assignments) == 1 and len(matches) == 1
            and matches[0].group(1) == previous, 'EXPECTED_SINGLE_CAMERA_IMAGE_PIN_REQUIRED')
    start, end = matches[0].span(1)
    return original[:start]+candidate+original[end:]


def check_receipt(root, docker):
    path = root/REPORT
    safe(path)
    require(path.is_file(), 'RUN_SOURCE_LIST_IMAGE_CHECK_FIRST')
    digest = sha(path)
    result = json.loads(path.read_text())
    require(result.get('status') == 'passed' and result.get('scope') == SCOPE
            and result.get('schema_version') == 3
            and all(result.get(key) is True for key in CHECKS)
            and result.get('production_services_modified') is False
            and result.get('source_list_activated') is False
            and result.get('automatic_production_database_restore') is False
            and result.get('checked_revision') == checked_manifest(root)
            and result.get('recipe_sha256') == recipe_fingerprint(root)
            and result.get('docker_daemon') == docker.preflight(), 'MATCHING_SOURCE_LIST_IMAGE_CHECK_REQUIRED')
    for key in ('candidate_image', 'previous_camera_image', 'database_image'):
        image = pinned_image(result.get(key))
        require(docker.run(['image', 'inspect', '--format', '{{.Id}}', image]).decode().strip() == image,
                'REHEARSED_IMAGE_UNAVAILABLE')
    require(result['candidate_image'] != result['previous_camera_image'], 'NEW_CAMERA_IMAGE_REQUIRED')
    require(sha(path) == digest, 'IMAGE_CHECK_RECEIPT_CHANGED')
    return {**result, 'receipt_sha256':digest}


def verify_list(base, token):
    verify_candidate(base, token)
    value = get_list(base, token, limit=1)
    require(len(value['items']) <= 1, 'SOURCE_LIST_LIMIT_NOT_APPLIED')
    # Production acceptance uses GET only. No test records or idempotency keys.


def save_record(root, directory, record):
    body = (json.dumps(record, indent=2)+'\n').encode()
    atomic_write(directory/'result.json', body)
    atomic_write(root/RECEIPT, body)


def verify_completed(root, docker, record, native):
    require(record.get('status') == 'activated', 'INCOMPLETE_SOURCE_LIST_ACTIVATION_REQUIRES_REVIEW')
    for key in ('candidate_image', 'previous_camera_image', 'database_image',
                'checked_revision', 'docker_daemon', 'recipe_sha256', 'receipt_sha256'):
        require(record.get(key) == native[key], 'ACTIVATION_RECEIPT_MISMATCH')
    before = docker.snapshot()
    require(before.get('camera-api', {}).get('image') == native['candidate_image']
            and before['camera-api']['running']
            and before.get('camera-db', {}).get('image') == native['database_image']
            and before['camera-db']['running'] and docker.volume_exists(), 'ACTIVATED_SERVICE_STATE_CHANGED')
    safe(root/'.env')
    env_digest = sha(root/'.env')
    values = prepare_secrets(root, True)
    docker.redact.extend(values.values())
    hashes = {name:sha(root/'var/camera/secrets'/name) for name in values}
    config = json.loads(docker.compose(['config', '--format', 'json']))
    require(config['services']['camera-api']['image'] == native['candidate_image'], 'CANDIDATE_IMAGE_PIN_CHANGED')
    base, token = config_endpoint(config)
    docker.redact.append(token)
    check_schema(root, read_database(docker, before['camera-db']['id']), 3)
    verify_list(base, token)
    require(docker.snapshot() == before and sha(root/'.env') == env_digest
            and all(sha(root/'var/camera/secrets'/name) == value for name,value in hashes.items())
            and checked_manifest(root) == native['checked_revision']
            and recipe_fingerprint(root) == native['recipe_sha256']
            and sha(root/REPORT) == native['receipt_sha256'], 'PROJECT_CHANGED_DURING_VERIFICATION')
    return {**record, 'status':'already_activated', 'service_restart_performed':False}


def activate(root, docker):
    """Caller holds activation_lock; failed/interrupted attempts require inspection."""
    native = check_receipt(root, docker)
    path = root/RECEIPT
    safe(path)
    if path.exists():
        return verify_completed(root, docker, json.loads(path.read_text()), native)
    state = inspect_live(root, docker)
    require(state['camera_image'] == native['previous_camera_image']
            and state['database_image'] == native['database_image']
            and state['checked_revision'] == native['checked_revision']
            and state['docker_daemon'] == native['docker_daemon'], 'LIVE_STATE_DIFFERS_FROM_IMAGE_CHECK')
    before = state['containers']
    env = root/'.env'
    original = env.read_bytes()
    mode = stat.S_IMODE(env.stat().st_mode)
    desired = pin_environment(original, native['previous_camera_image'], native['candidate_image'])
    config = json.loads(docker.compose(['config', '--format', 'json']))
    candidate_config = json.loads(docker.compose(['config', '--format', 'json'], image=native['candidate_image']))
    base, token = config_endpoint(config)
    docker.redact.append(token)
    require(config_endpoint(candidate_config) == (base, token)
            and candidate_config['services']['camera-api']['image'] == native['candidate_image'],
            'CANDIDATE_CONFIGURATION_CHANGED')
    script = root/'src/infra/tools/activate_camera_source_list.py'
    script_digest = sha(script)
    backup_root = root/'var/camera/source-list-activation-backups'
    private_directory(backup_root)
    directory = Path(tempfile.mkdtemp(prefix='step06b2-', dir=backup_root))
    atomic_write(directory/'env.before', original)
    atomic_write(directory/'containers.before.json', json.dumps(before, indent=2).encode())
    record = {key:native[key] for key in ('candidate_image', 'previous_camera_image', 'database_image',
               'checked_revision', 'docker_daemon', 'recipe_sha256', 'receipt_sha256')}
    record.update({'status':'running', 'scope':'camera_source_list', 'project':docker.project,
                   'stage':'prepared', 'endpoint':base, 'backup_directory':str(directory),
                   'activation_tool_sha256':script_digest, 'schema_version':3, 'migration_applied':0,
                   'automatic_database_restore':False, 'business_runtime_ready':False})
    save_record(root, directory, record)
    pin_requested = switch_requested = False

    def guard(expected_env):
        safe(env)
        require(env.read_bytes() == expected_env, 'CONCURRENT_ENV_EDIT_PRESERVED')
        require(checked_manifest(root) == native['checked_revision']
                and recipe_fingerprint(root) == native['recipe_sha256']
                and sha(root/REPORT) == native['receipt_sha256']
                and sha(script) == script_digest, 'PROJECT_OR_RECEIPT_CHANGED')
        for name, digest in state['secret_sha256'].items():
            secret = root/'var/camera/secrets'/name
            safe(secret)
            require(sha(secret) == digest, 'DATABASE_SECRETS_CHANGED')
        current = docker.snapshot()
        require(unchanged_except_camera(before, current), 'NON_CAMERA_CONTAINERS_CHANGED')
        check_schema(root, read_database(docker, before['camera-db']['id']), 3)
        return current

    def stage(name):
        record['stage'] = name
        save_record(root, directory, record)

    try:
        require(guard(original) == before and sha(env) == state['env_sha256'], 'STATE_CHANGED_BEFORE_SWITCH')
        stage('image_pin_requested')
        pin_requested = True
        atomic_write(env, desired, mode)
        require(guard(desired) == before, 'CAMERA_CHANGED_BEFORE_SWITCH')
        stage('switch_requested')
        switch_requested = True
        print('source list activation: switch camera API to the verified image', flush=True)
        docker.compose(UP, image=native['candidate_image'], timeout=100)
        verify_list(base, token)
        current = guard(desired)
        require(current.get('camera-api', {}).get('image') == native['candidate_image']
                and current['camera-api']['running'], 'CANDIDATE_IMAGE_NOT_RUNNING')
        record.update({'status':'activated', 'stage':'completed', 'source_list_activated':True,
                       'service_restart_performed':True, 'database_container_unchanged':True,
                       'other_services_unchanged':True})
        save_record(root, directory, record)
        return record
    except BaseException:
        recovery = 'no_service_change' if not pin_requested else 'manual_review_required'
        if pin_requested:
            try:
                # Both images use exactly schema 3. Only restore the image and
                # its single .env pin; all committed DB data remains in place.
                safe(env)
                actual = env.read_bytes()
                require(actual in (original, desired), 'CONCURRENT_ENV_EDIT_PRESERVED')
                current = guard(actual)
                camera = current.get('camera-api')
                require(camera is None or camera['image'] in (
                    native['previous_camera_image'], native['candidate_image']), 'UNEXPECTED_CAMERA_IMAGE')
                if not switch_requested:
                    require(camera == before['camera-api'], 'CAMERA_CHANGED_BEFORE_SWITCH')
                if actual != original:
                    atomic_write(env, original, mode)
                if switch_requested and not (camera and camera['image'] == native['previous_camera_image']
                                              and camera['running']):
                    print('source list activation: restore previous camera image without restoring the database', flush=True)
                    docker.compose(UP, image=native['previous_camera_image'], timeout=100)
                verify_version(base, token, OLD_VERSION)
                restored = guard(original)
                require(restored.get('camera-api', {}).get('image') == native['previous_camera_image']
                        and restored['camera-api']['running'], 'PREVIOUS_IMAGE_NOT_RUNNING')
                recovery = 'previous_image_restored'
            except BaseException:
                pass
        record.update({'status':'failed', 'source_list_activated':(
                           False if recovery in ('no_service_change', 'previous_image_restored') else None),
                       'recovery':recovery,
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
            result = activate(root, CameraSwitchDocker(root))
        private = {'checked_revision', 'docker_daemon', 'recipe_sha256', 'receipt_sha256', 'activation_tool_sha256'}
        print(json.dumps({k:v for k,v in result.items() if k not in private}, ensure_ascii=False))
        return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, URLError) as exc:
        code = str(exc).split(':', 1)[0] if isinstance(exc, ActivationError) else 'SOURCE_LIST_ACTIVATION_UNAVAILABLE'
        print(json.dumps({'status':'failed', 'scope':'camera_source_list', 'code':code,
                          'report':str(root/RECEIPT), 'automatic_database_restore':False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
