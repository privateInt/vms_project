#!/usr/bin/env python3
"""Build and check the step06 image in a disposable project; never switch production."""
import contextlib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sys
import tempfile
from urllib.error import URLError
from urllib.parse import urlencode

from camera_activation import (ACTIVE, ActivationError, Docker, activation_lock,
                               atomic_write, config_endpoint, prepare_secrets,
                               private_directory, request, safe, sha)
from inspect_camera_source_upgrade import require
from activate_camera_sources import READ_DB_SQL, check_schema, read_database
from test_camera_source_upgrade import (DEVICE, SOURCE, migrate, pinned_image,
                                       start_api, unused_port, verify_privileges,
                                       verify_resource, verify_version)

PREFIX = 'vms-source-list-test-'
SCOPE = 'camera_source_list_image_native_docker'
REPORT = 'var/camera/source-list-image-check.json'
OLD_VERSION = '0.3.0-source-registry'
NEW_VERSION = '0.3.1-source-list'


def checked_manifest(root):
    safe(root)
    path = root/'project-manifest.json'
    safe(path)
    manifest = json.loads(path.read_text())
    require(manifest.get('activation_revision') == 'step06-source-list-code-20260930'
            and manifest.get('storage_revision') == 'step05-source-idempotency-20260930'
            and manifest.get('version') == NEW_VERSION, 'STEP06_A_PROJECT_REQUIRED')
    require(isinstance(manifest.get('files'), dict) and manifest['files'], 'PROJECT_MANIFEST_INVALID')
    for relative, expected in manifest['files'].items():
        name = PurePosixPath(relative)
        require(not name.is_absolute() and '..' not in name.parts and '\\' not in relative
                and str(name) == relative and name.parts
                and name.parts[0] not in ('.env', '.git', 'var', 'build'), 'PROJECT_MANIFEST_INVALID')
        item = root/relative
        safe(item)
        require(item.is_file() and sha(item) == expected, 'PROJECT_FILE_CHANGED: '+relative)
    return sha(path)


def recipe_fingerprint(root):
    names = ('test_camera_source_list_image.py', 'camera_activation.py',
             'inspect_camera_source_upgrade.py', 'activate_camera_sources.py',
             'test_camera_source_upgrade.py')
    values = {}
    for name in names:
        path = root/'src/infra/tools'/name
        safe(path)
        values[name] = sha(path)
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


class InspectionDocker(Docker):
    """The production handle cannot build, stop, migrate, grant or remove resources."""
    def compose(self, args, *, active=False, **kwargs):
        require(args == ['config', '--format', 'json'] and active is False and not kwargs,
                'PRODUCTION_COMPOSE_WRITE_REJECTED')
        return super().compose(args, active=False)

    def run(self, args, **kwargs):
        readonly = (args[:1] in (['info'], ['ps'], ['inspect'])
                    or args[:2] in (['context', 'inspect'], ['volume', 'ls'], ['volume', 'inspect'])
                    or (args[:1] == ['compose'] and args[-3:] == ['config', '--format', 'json'])
                    or (len(args) == 15 and args[:1] == ['exec'] and args[2:] == [
                        'psql', '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                        '-U', 'camera_admin', '-d', 'vms_camera', '-c', READ_DB_SQL]))
        require(readonly, 'PRODUCTION_DOCKER_WRITE_REJECTED')
        return super().run(args, **kwargs)


def inspect_live(root, docker):
    revision = checked_manifest(root)
    daemon = docker.preflight()
    safe(root/'.env')
    env_digest = sha(root/'.env')
    before = docker.snapshot()
    require(all(before.get(s, {}).get('running') for s in ('camera-api', 'camera-db'))
            and docker.volume_exists(), 'RUNNING_CAMERA_AND_DATABASE_REQUIRED')
    config = json.loads(docker.compose(['config', '--format', 'json']))
    require(config['services']['camera-api']['image'] == pinned_image(before['camera-api']['image'])
            and 'camera-db' in config['services'], 'ACTIVE_PINNED_CAMERA_REQUIRED')
    base, token = config_endpoint(config)
    docker.redact.append(token)
    values = prepare_secrets(root, True)
    docker.redact.extend(values.values())
    secret_hashes = {name:sha(root/'var/camera/secrets'/name) for name in values}
    verify_version(base, token, OLD_VERSION)
    check_schema(root, read_database(docker, before['camera-db']['id']), 3)
    require(docker.snapshot() == before and sha(root/'.env') == env_digest
            and checked_manifest(root) == revision, 'PRODUCTION_CHANGED_DURING_INSPECTION')
    return {'checked_revision':revision, 'docker_daemon':daemon, 'containers':before,
            'camera_image':pinned_image(before['camera-api']['image']),
            'database_image':pinned_image(before['camera-db']['image']),
            'env_sha256':env_digest, 'secret_sha256':secret_hashes}


class IsolatedDocker(Docker):
    def __init__(self, root, project, production_root):
        require(re.fullmatch(PREFIX+r'[0-9a-f]{12}', project), 'ISOLATED_PROJECT_REQUIRED')
        require(root.resolve() != production_root.resolve()
                and production_root.resolve() not in root.resolve().parents,
                'SEPARATE_TEMPORARY_WORKSPACE_REQUIRED')
        require((root/'source-list-test-project').read_text() == project, 'WORKSPACE_MARKER_MISMATCH')
        super().__init__(root, project)


def configure_workspace(production_root, root, state, project):
    require(checked_manifest(production_root) == state['checked_revision'], 'PROJECT_REVISION_CHANGED')
    root.mkdir()
    manifest = json.loads((production_root/'project-manifest.json').read_text())
    for name in [*manifest['files'], 'project-manifest.json']:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(production_root/name, target)
    # Detect a source edit during the copy before changing test-only configuration.
    require(checked_manifest(root) == state['checked_revision'], 'COPIED_PROJECT_REVISION_CHANGED')
    (root/'source-list-test-project').write_text(project)
    token, port = secrets.token_urlsafe(36), unused_port()
    atomic_write(root/'.env', ('VMS_API_TOKEN='+token+'\nVMS_BIND_ADDR=127.0.0.1\n'
                              'VMS_CAMERA_PORT='+str(port)+'\n').encode())
    private_directory(root/'var/camera')
    values = prepare_secrets(root, False)
    # Only camera services exist in this fresh project. No production mounts,
    # secrets, database volume, network or bearer token are copied.
    (root/'compose.yaml').write_text(json.dumps({'include':[{'path':ACTIVE}]}))
    path = root/'src/infra/postgresql/compose.camera.yaml'
    definition = path.read_text()
    require(definition.count('image: postgres:17.11-bookworm') == 1, 'DATABASE_DEFINITION_CHANGED')
    path.write_text(definition.replace('image: postgres:17.11-bookworm',
                                       'image: '+pinned_image(state['database_image'])))
    return token, 'http://127.0.0.1:'+str(port), values


@contextlib.contextmanager
def isolated_environment(production_root, state, project):
    directory = Path(tempfile.mkdtemp(prefix=project+'-'))
    root, docker = directory/'project', None
    try:
        token, base, values = configure_workspace(production_root, root, state, project)
        candidate = IsolatedDocker(root, project, production_root)
        require(candidate.preflight() == state['docker_daemon'], 'DOCKER_DAEMON_CHANGED')
        require(not candidate.snapshot() and not candidate.volume_exists(), 'ISOLATED_PROJECT_ALREADY_EXISTS')
        docker = candidate
        docker.redact.extend([token, *values.values()])
        yield root, docker, token, base
    finally:
        if docker is not None:
            try:
                docker.compose(['--profile', '*', 'down', '--volumes', '--remove-orphans', '--timeout', '10'])
                require(not docker.snapshot() and not docker.volume_exists(), 'ISOLATED_RESOURCES_REMAIN')
                networks = docker.run(['network', 'ls', '-q', '--filter',
                                      'label=com.docker.compose.project='+project]).decode().strip()
                require(not networks, 'ISOLATED_NETWORKS_REMAIN')
            except BaseException:
                print(json.dumps({'status':'cleanup_failed', 'project':project,
                                  'retained_workspace':str(root)}), flush=True)
                raise
        shutil.rmtree(directory)


def verify_candidate(base, token):
    verify_version(base, token, NEW_VERSION)
    code, value, _ = request(base, '/api/v1/platform', token)
    require(code == 200 and value.get('capabilities', {}).get('source_list') == 'implemented',
            'SOURCE_LIST_CAPABILITY_REQUIRED')


def get_list(base, token, **query):
    code, value, _ = request(base, '/api/v1/sources?'+urlencode(query), token)
    require(code == 200 and isinstance(value.get('items'), list)
            and value.get('request_id') and 'next_cursor' in value
            and (value['next_cursor'] is None or isinstance(value['next_cursor'], str)),
            'SOURCE_LIST_RESPONSE_INVALID')
    return value


def seed(base, token, collection, body, key):
    code, value, _ = request(base, '/api/v1/'+collection, token, body, key)
    field = 'device' if collection == 'devices' else 'source'
    require(code == 201 and isinstance(value.get(field), dict), 'ISOLATED_SEED_FAILED')
    return value[field]


def rehearse(production_root, state, project):
    with isolated_environment(production_root, state, project) as (root, docker, token, base):
        tag = project+'-camera:source-list'
        print('source list image check: build candidate in isolated workspace', flush=True)
        docker.compose(['build', 'camera-api'], image=tag, timeout=900)
        image = pinned_image(docker.run(['image', 'inspect', '--format', '{{.Id}}', tag]).decode().strip())
        old = pinned_image(state['camera_image'])
        require(image != old, 'NEW_CAMERA_IMAGE_REQUIRED')
        config = json.loads(docker.compose(['config', '--format', 'json'], image=image))
        require(config_endpoint(config) == (base, token)
                and not config['services']['camera-db'].get('ports')
                and config['networks']['camera-storage'].get('internal') is True,
                'ISOLATED_NETWORK_CONFIGURATION_REQUIRED')
        print('source list image check: seed disposable schema 3 with the running old image', flush=True)
        docker.compose(['up', '-d', '--no-deps', '--wait', '--wait-timeout', '90', 'camera-db'],
                       image=old, timeout=180)
        # The only migration/grant is initial bootstrap of the disposable DB.
        migrate(docker, old, 3, 3)
        verify_privileges(docker)
        database = docker.snapshot()['camera-db']
        start_api(docker, old)
        verify_version(base, token, OLD_VERSION)
        dev = {**DEVICE, 'device_id':'list-device'}
        dev2 = {**DEVICE, 'device_id':'list-other'}
        device = seed(base, token, 'devices', dev, 'list-device-key')
        seed(base, token, 'devices', dev2, 'list-other-key')
        sources = {}
        for identity, device_id in [('list-c', 'list-device'), ('list-a', 'list-device'), ('list-b', 'list-other')]:
            body = {**SOURCE, 'source_id':identity, 'device_id':device_id, 'channel_key':identity}
            sources[identity] = seed(base, token, 'sources', body, identity+'-key')
        print('source list image check: verify packaged list API, profiles, filters and cursor', flush=True)
        start_api(docker, image)
        verify_candidate(base, token)
        code, _, _ = request(base, '/api/v1/sources?limit=1')
        require(code == 401, 'SOURCE_LIST_AUTHENTICATION_REQUIRED')
        first = get_list(base, token, limit=1)
        require(first['items'] == [sources['list-a']] and first['next_cursor'], 'FIRST_PAGE_INVALID')
        cursor = first['next_cursor']
        second = get_list(base, token, limit=2, cursor=cursor)
        require(second['items'] == [sources['list-b'], sources['list-c']]
                and second['next_cursor'] is None, 'SECOND_PAGE_INVALID')
        filtered = get_list(base, token, device_id='list-device')
        require(filtered['items'] == [sources['list-a'], sources['list-c']]
                and filtered['next_cursor'] is None, 'DEVICE_FILTER_INVALID')
        empty = get_list(base, token, device_id='missing-device')
        require(empty['items'] == [] and empty['next_cursor'] is None, 'EMPTY_LIST_INVALID')
        code, value, _ = request(base, '/api/v1/sources?'+urlencode({
            'cursor':cursor, 'device_id':'list-device'}), token)
        require(code == 400 and value.get('error', {}).get('code') == 'QUERY_INVALID',
                'CURSOR_FILTER_BINDING_INVALID')
        new_body = {**SOURCE, 'source_id':'list-d', 'device_id':'list-device', 'channel_key':'list-d'}
        sources['list-d'] = seed(base, token, 'sources', new_body, 'list-d-key')
        start_api(docker, image)
        verify_candidate(base, token)
        resumed = get_list(base, token, cursor=cursor)
        require(resumed['items'] == [sources[k] for k in ('list-b', 'list-c', 'list-d')]
                and resumed['next_cursor'] is None, 'CURSOR_AFTER_RECREATE_INVALID')
        print('source list image check: verify image-only rollback preserves acknowledged data', flush=True)
        start_api(docker, old)
        verify_version(base, token, OLD_VERSION)
        verify_resource(base, token, 'devices', dev, 'list-device-key', device)
        verify_resource(base, token, 'sources', new_body, 'list-d-key', sources['list-d'])
        start_api(docker, image)
        verify_candidate(base, token)
        final = get_list(base, token)
        require(final['items'] == [sources[k] for k in sorted(sources)]
                and final['next_cursor'] is None, 'DATA_CHANGED_ACROSS_IMAGE_SWITCHES')
        require(docker.snapshot()['camera-db'] == database, 'ISOLATED_DATABASE_CONTAINER_CHANGED')
        check_schema(root, read_database(docker, database['id']), 3)
        return {'candidate_image':image, 'candidate_image_tag':tag, 'schema_version':3,
                'source_list_verified':True, 'api_recreation_verified':True,
                'image_only_rollback_verified':True, 'post_switch_data_preserved':True,
                'isolated_database_unchanged':True}


def run_check(root, live, project):
    print('source list image check: read production state without changing services', flush=True)
    state = inspect_live(root, live)
    recipe = recipe_fingerprint(root)
    result = rehearse(root, state, project)
    require(live.snapshot() == state['containers']
            and sha(root/'.env') == state['env_sha256']
            and all(sha(root/'var/camera/secrets'/name) == value for name, value in state['secret_sha256'].items())
            and checked_manifest(root) == state['checked_revision']
            and recipe_fingerprint(root) == recipe, 'PRODUCTION_OR_RECIPE_CHANGED_DURING_CHECK')
    check_schema(root, read_database(live, state['containers']['camera-db']['id']), 3)
    return {**result, 'status':'passed', 'scope':SCOPE, 'project':project,
            'checked_revision':state['checked_revision'], 'docker_daemon':state['docker_daemon'],
            'recipe_sha256':recipe, 'previous_camera_image':state['camera_image'],
            'database_image':state['database_image'], 'production_services_modified':False,
            'source_list_activated':False, 'isolated_resources_removed':True,
            'automatic_production_database_restore':False}


def main():
    root = Path(__file__).resolve().parents[3]
    path = root/REPORT
    project = PREFIX+secrets.token_hex(6)
    try:
        with activation_lock(root):
            atomic_write(path, json.dumps({'status':'running', 'project':project}).encode())
            try:
                result = run_check(root, InspectionDocker(root), project)
                atomic_write(path, (json.dumps(result, indent=2)+'\n').encode())
            except BaseException:
                atomic_write(path, json.dumps({'status':'failed', 'project':project}).encode())
                raise
        public = {k:v for k,v in result.items() if k not in {'checked_revision', 'docker_daemon', 'recipe_sha256'}}
        print(json.dumps({**public, 'report':str(path)}, ensure_ascii=False))
        return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, URLError) as exc:
        code = str(exc).split(':', 1)[0] if isinstance(exc, ActivationError) else 'SOURCE_LIST_IMAGE_CHECK_UNAVAILABLE'
        print(json.dumps({'status':'failed', 'scope':SCOPE, 'project':project, 'code':code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
