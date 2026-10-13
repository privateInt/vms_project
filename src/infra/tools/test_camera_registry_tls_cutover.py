#!/usr/bin/env python3
"""Rehearse schema7 registry TLS with the running images and synthetic resources only."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from camera_activation import Docker, ActivationError, activation_lock, atomic_write, private_directory
import prepare_camera_database_tls_candidate as pki
import prepare_camera_database_tls_supply as supply
import test_camera_database_tls_boundary as transport
import test_camera_device_delete_upgrade as registry
from test_camera_source_upgrade import unused_port, sql

SCOPE = 'camera_registry_schema7_tls_cutover_native_docker'
PREFIX = 'vms-registry-tls-test-'
ACCEPTED_SUPPLY = '5d2f6e3ce0016e173157051c44540cc9cbc8274d8cf567711985701c9815c9d7'
PACKAGE = 'vms.local/platform/camera/internal/storage'
GO_PHASES = ('runtime-schema7-tls', 'runtime-auth-denials', 'migrator-mtls',
             'migrator-auth-denials', 'offsource-auth-denials')
GO_PARENTS = ('TestNativeRegistryTLSRuntime',) * 2 + ('TestNativeRegistryTLSMigrator',) * 2 + ('TestNativeRegistryTLSOffSource',)
GO_PREFIX = 'REGISTRY_TLS_PHASE_OK:'
STAGES = ('accepted_source', 'production_observation', 'isolated_network', 'synthetic_fixture',
          'probe_build', 'input_ownership', 'plaintext_database', 'schema7_migration',
          'plaintext_http_binding', 'tls_http_binding', 'recreated_api_http_binding', 'recreated_db_api_http_binding',
          'plaintext_registry_seed', 'plaintext_api_drain', 'tls_database', 'mtls_migration_replay',
          'tls_api_and_native_probes', 'legacy_history_replay', 'new_tls_registry_writes',
          'api_recreation', 'database_and_api_recreation', 'source_and_production_recheck', 'cleanup')
ROLE_UIDS = {'db': 999, 'control': 999, 'runtime': 65532, 'maintenance': 10002, 'offsource': 10003, 'bootstrap': 10002}
HTTP_BINDING_FORMAT = ('{"Id":{{json .Id}},"Image":{{json .Image}},"Labels":{{json .Config.Labels}},'
    '"Running":{{json .State.Running}},"Ports":{{json .NetworkSettings.Ports}},'
    '"Networks":{{json .NetworkSettings.Networks}},"PortBindings":{{json .HostConfig.PortBindings}}}')
NO_CHANGES = {**transport.NO_CHANGES, 'production_candidate_files_read': False,
              'production_prepared_supply_files_read': False, 'production_prepared_volumes_modified': False,
              'backup_created': False, 'database_backup_restore_performed': False}
BUILD = ('set -eu\numask 077\nchmod 0755 /exchange\ncp -a /source/. /work/\n'
         'go vet ./...\ngo test -race -count=1 -json ./camera/internal/storage -run \'^TestRegistryTLSInputPolicy$\'\n'
         'CGO_ENABLED=0 go test -c -o /exchange/registry.test ./camera/internal/storage\n'
         'CGO_ENABLED=0 go build -o /exchange/test2json cmd/test2json\n'
         'chmod 0755 /exchange/registry.test /exchange/test2json\n')
OWN_FILES = ('set -eu\numask 077\n' + ''.join(
    f'chmod 0700 /{role}\ncp /input/{role}/* /{role}/\nchmod 0400 /{role}/*\nchown -R {uid}:{uid} /{role}\n'
    for role, uid in ROLE_UIDS.items()))


class CheckError(Exception):
    pass


class RegistryHTTPError(CheckError):
    """Public request context excludes token, headers, body and raw exception text."""
    def __init__(self, code, collection, method, identifier, status=None, api_code=None):
        super().__init__(code)
        self.step = {'collection': collection, 'method': method, 'resource_id': identifier}
        if isinstance(status, int) and 100 <= status <= 599: self.step['status'] = status
        if isinstance(api_code, str) and re.fullmatch('[A-Z][A-Z0-9_]{1,80}', api_code):
            self.step['api_error_code'] = api_code


def require(condition, code):
    if not condition: raise CheckError(code)


def checked_source(root):
    revision, value = supply.checked_source(root)
    require(value.get('credential_database_tls_supply_server_verified') is True
            and value.get('validated_credential_database_tls_supply_project_sha256') == ACCEPTED_SUPPLY
            and value.get('credential_registry_tls_cutover_rehearsal_implemented') is True,
            'ACCEPTED_TLS_SUPPLY_REQUIRED')
    return revision


def hba(runtime, maintenance, tls):
    require(runtime != maintenance, 'ISOLATED_DISTINCT_SOURCES_REQUIRED')
    method = 'hostssl' if tls else 'hostnossl'
    migrator_auth = 'cert map=registry_migrator' if tls else 'scram-sha-256'
    return (f'local all camera_admin trust\nlocal all all reject\n'
            f'{method} vms_camera camera_runtime {runtime}/32 scram-sha-256\n'
            f'{method} vms_camera camera_migrator {maintenance}/32 {migrator_auth}\n'
            'host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n').encode()


def dsn(role, password, host, port, base, mode='verify-full', ca='ca.pem', client=True):
    q = {'sslmode': mode}
    if mode != 'disable':
        q['sslrootcert'] = str(base / ca)
        if role == 'camera_migrator' and client:
            q.update(sslcert=str(base / 'maintenance.pem'), sslkey=str(base / 'maintenance.key'))
    return f'postgres://{role}:{password}@{host}:{port}/vms_camera?' + urlencode(q)


def prepare_fixture(root, source, addresses):
    require(root.is_dir() and not list(root.iterdir()), 'FRESH_SYNTHETIC_WORKSPACE_REQUIRED')
    first, wrong = root / 'pki', root / 'wrong-pki'
    first.mkdir(mode=0o700); wrong.mkdir(mode=0o700)
    proof = pki.prepare(first, True); pki.prepare(wrong, True)
    original = first.joinpath(*pki.DIRECTORY, pki.CANDIDATE)
    bad_ca = wrong.joinpath(*pki.DIRECTORY, pki.CANDIDATE, 'ca.pem').read_bytes()
    signer = root / 'signer'; signer.mkdir(mode=0o700)
    for name in ('ca.pem', 'ca.key', 'maintenance.key'): atomic_write(signer / name, (original / name).read_bytes())
    fd = os.open(signer, pki.DIR_FLAGS)
    try:
        pki.write_new(fd, 'wrong.csr', pki.openssl(fd, ['req', '-new', '-key', 'maintenance.key', '-subj', '/CN=wrong_maintenance']))
        pki.write_new(fd, 'wrong.cnf', b'[leaf]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
        bad_client = pki.openssl(fd, ['x509', '-req', '-in', 'wrong.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
            '-set_serial', '0x1' + secrets.token_hex(16), '-days', '365', '-sha256', '-extfile', 'wrong.cnf', '-extensions', 'leaf'])
    finally: os.close(fd)
    inputs = root / 'input'; inputs.mkdir(mode=0o700)
    for role in ROLE_UIDS: (inputs / role).mkdir(mode=0o700)
    passwords = {r: secrets.token_hex(24) for r in ('camera_admin', 'camera_migrator', 'camera_runtime')}
    state = {'Kind': 'isolated-registry-tls-schema7', 'Host': addresses[0], 'Port': 5432,
             'Database': 'vms_camera', 'ServerName': pki.SERVER_NAME, 'RuntimeIP': addresses[1],
             'MaintenanceIP': addresses[2], 'OffSourceIP': addresses[3],
             'ServerCertificateSHA256': proof['server_certificate_sha256']}
    for name in ('ca.pem', 'server.pem', 'server.key'): atomic_write(inputs / 'db' / name, (original / name).read_bytes())
    for role in ('runtime', 'maintenance', 'offsource'):
        dest = inputs / role; base = Path('/registry-' + role)
        atomic_write(dest / 'endpoint.json', pki.encoded(state))
        atomic_write(dest / 'ca.pem', (original / 'ca.pem').read_bytes())
        atomic_write(dest / 'runtime-dsn', (dsn('camera_runtime', passwords['camera_runtime'], pki.SERVER_NAME, 5432, base) + '\n').encode())
        if role == 'runtime':
            atomic_write(dest / 'wrong-ca.pem', bad_ca)
            for file, host, ca, mode in (('plaintext-dsn', pki.SERVER_NAME, 'ca.pem', 'disable'),
                ('wrong-ca-dsn', pki.SERVER_NAME, 'wrong-ca.pem', 'verify-full'),
                ('wrong-host-dsn', 'wrong-db.vms.internal', 'ca.pem', 'verify-full')):
                atomic_write(dest / file, (dsn('camera_runtime', passwords['camera_runtime'], host, 5432, base, mode, ca) + '\n').encode())
        else:
            for name in ('maintenance.pem', 'maintenance.key'): atomic_write(dest / name, (original / name).read_bytes())
            atomic_write(dest / 'migrator-dsn', (dsn('camera_migrator', passwords['camera_migrator'], pki.SERVER_NAME, 5432, base) + '\n').encode())
            if role == 'maintenance':
                atomic_write(dest / 'wrong-client.pem', bad_client)
                atomic_write(dest / 'wrong-client.key', (original / 'maintenance.key').read_bytes())
    atomic_write(inputs / 'bootstrap' / 'migrator-dsn', (dsn('camera_migrator', passwords['camera_migrator'], pki.SERVER_NAME, 5432, Path('/registry-bootstrap'), 'disable') + '\n').encode())
    control = inputs / 'control'
    for role, name in (('camera_admin', 'camera_admin_password'), ('camera_migrator', 'camera_migration_password'), ('camera_runtime', 'camera_runtime_password')):
        atomic_write(control / name, (passwords[role] + '\n').encode())
    atomic_write(control / '10-camera.sh', (source / 'src/infra/postgresql/camera-init.sh').read_bytes())
    atomic_write(control / 'hba-bootstrap.conf', hba(addresses[1], addresses[2], False))
    atomic_write(control / 'hba-tls.conf', hba(addresses[1], addresses[2], True))
    atomic_write(control / 'pg_ident.conf', b'registry_migrator camera_maintenance camera_migrator\n')
    require(not list(inputs.rglob('ca.key')), 'CA_SIGNING_KEY_EXPORTED')
    return inputs


def compose_recipe(source, root, project, network, addresses, api_image, db_image, token, port, tls=False):
    require(all(re.fullmatch('sha256:[0-9a-f]{64}', v) for v in (api_image, db_image)), 'IMMUTABLE_IMAGES_REQUIRED')
    shared = {'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'], 'restart': 'no'}
    services = {
        'files-owner': {'image': db_image, 'entrypoint': ['/bin/sh', '-ec', OWN_FILES], 'network_mode': 'none',
            'volumes': [{'type': 'bind', 'source': str(root / 'input'), 'target': '/input', 'read_only': True,
                         'bind': {'create_host_path': False}}, *[r + ':/' + r for r in ROLE_UIDS]],
            'tmpfs': ['/var/lib/postgresql/data']},
        'probe-build': {'image': 'golang:1.27.1-bookworm', 'working_dir': '/work',
            'entrypoint': ['/bin/sh', '-ec', BUILD], 'environment': {'GOTOOLCHAIN': 'local'},
            'volumes': [{'type': 'bind', 'source': str(source / 'src/platform'), 'target': '/source',
                         'read_only': True, 'bind': {'create_host_path': False}}, 'exchange:/exchange']},
        'camera-db': {'image': db_image, 'environment': {'POSTGRES_DB': 'vms_camera', 'POSTGRES_USER': 'camera_admin',
                'POSTGRES_PASSWORD_FILE': '/run/secrets/camera_admin_password', 'POSTGRES_INITDB_ARGS': '--auth-host=scram-sha-256'},
            'command': ['postgres', '-c', 'ssl=' + ('on' if tls else 'off'), '-c', 'ssl_min_protocol_version=TLSv1.2',
                '-c', 'ssl_cert_file=/db-tls/server.pem', '-c', 'ssl_key_file=/db-tls/server.key', '-c', 'ssl_ca_file=/db-tls/ca.pem',
                '-c', 'hba_file=/tls-control/hba-' + ('tls' if tls else 'bootstrap') + '.conf', '-c', 'ident_file=/tls-control/pg_ident.conf'],
            'volumes': ['camera-data:/var/lib/postgresql/data', 'db:/db-tls:ro', 'control:/tls-control:ro',
                        'control:/run/secrets:ro', 'control:/docker-entrypoint-initdb.d:ro'],
            'networks': {'storage': {'ipv4_address': addresses[0], 'aliases': [pki.SERVER_NAME, 'wrong-db.vms.internal']}},
            'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -h 127.0.0.1 -U camera_admin -d vms_camera'],
                            'interval': '2s', 'timeout': '3s', 'retries': 30}, 'restart': 'no'},
        'camera-api': {**shared, 'image': api_image, 'user': '65532:65532',
            'environment': {'HTTP_ADDR': ':8080', 'VMS_API_TOKEN': token,
                            'CAMERA_DATABASE_URL_FILE': '/registry-runtime/' + ('runtime-dsn' if tls else 'plaintext-dsn')},
            'volumes': ['runtime:/registry-runtime:ro', 'exchange:/exchange:ro'],
            'networks': {'http': {}, 'storage': {'ipv4_address': addresses[1]}},
            'ports': ['127.0.0.1:' + str(port) + ':8080'],
            'healthcheck': {'test': ['CMD', '/vms-api', '--healthcheck'], 'interval': '2s', 'timeout': '3s', 'retries': 30}},
        'camera-migrate': {**shared, 'image': api_image, 'user': '10002:10002', 'entrypoint': ['/camera-migrate'],
            'command': ['--apply', '--grant-runtime'], 'environment': {'CAMERA_DATABASE_URL_FILE':
                '/registry-maintenance/migrator-dsn' if tls else '/registry-bootstrap/migrator-dsn'},
            'volumes': ['bootstrap:/registry-bootstrap:ro', 'maintenance:/registry-maintenance:ro'],
            'networks': {'storage': {'ipv4_address': addresses[2]}}, 'profiles': ['migration']},
    }
    for role, uid, ip in (('maintenance', 10002, addresses[2]), ('offsource', 10003, addresses[3])):
        services['probe-' + role] = {**shared, 'image': 'golang:1.27.1-bookworm', 'user': f'{uid}:{uid}',
            'entrypoint': ['sleep', 'infinity'], 'volumes': [role + ':/registry-' + role + ':ro', 'exchange:/exchange:ro'],
            'networks': {'storage': {'ipv4_address': ip}}}
    return {'name': project, 'services': services, 'networks': {
                'http': {'name': project + '-http', 'driver': 'bridge', 'internal': False},
                'storage': {'external': True, 'name': network}},
            'volumes': {r: {} for r in (*ROLE_UIDS, 'exchange', 'camera-data')}}


class RehearsalDocker(Docker):
    def __init__(self, root, project, production_root, log, run=subprocess.run):
        require(re.fullmatch(PREFIX + '[0-9a-f]{12}', project) is not None
                and root != production_root and production_root not in root.parents,
                'SEPARATE_SYNTHETIC_PROJECT_REQUIRED')
        super().__init__(root, project)
        self.log, self.invoke, self.last_exit = log, run, None

    def run(self, args, *, input=None, timeout=120, **kwargs):
        require(not kwargs, 'ISOLATED_COMMAND_OPTIONS_INVALID')
        try:
            result = self.invoke(['docker', *args], cwd=self.root, env=self.env.copy(), input=input,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired): raise CheckError('ISOLATED_COMMAND_TIMEOUT_OR_UNAVAILABLE') from None
        self.last_exit = result.returncode
        with self.log.open('ab') as output: output.write(result.stdout); output.write(result.stderr)
        require(result.returncode == 0, 'ISOLATED_REGISTRY_TLS_COMMAND_FAILED')
        return result.stdout

    def compose(self, args, **kwargs):
        return self.run(['compose', '--project-name', self.project, '--project-directory', str(self.root),
                         '--env-file', '/dev/null', '-f', str(self.root / 'compose.json'), *args], **kwargs)


def summarize_go(path):
    terminal, active, phases = {}, {}, []
    for line in path.read_text(errors='replace').splitlines():
        try: row = json.loads(line)
        except ValueError: continue
        if not isinstance(row, dict): continue
        require(row.get('Action') != 'fail', 'REGISTRY_TLS_GO_TEST_FAILED')
        if row.get('Package') != PACKAGE: continue
        name, action = row.get('Test'), row.get('Action')
        if action in ('pass', 'skip'): terminal[name] = action
        if name not in set(GO_PARENTS): continue
        if action == 'run':
            require(name not in active, 'REGISTRY_TLS_TRANSCRIPT_INVALID'); active[name] = []
        elif action == 'output':
            match = re.search(r'(?:^|\s)' + GO_PREFIX + r'([a-z0-9-]+)\s*$', str(row.get('Output', '')))
            if match:
                require(name in active, 'REGISTRY_TLS_TRANSCRIPT_INVALID'); active[name].append(match.group(1))
        elif action in ('pass', 'skip'):
            require(name in active and action == 'pass' and active[name], 'REGISTRY_TLS_NATIVE_PROOF_REQUIRED')
            for phase in active.pop(name):
                i = len(phases)
                require(i < len(GO_PHASES) and phase == GO_PHASES[i] and name == GO_PARENTS[i], 'REGISTRY_TLS_COMPLETE_PHASES_REQUIRED')
                phases.append(phase)
    require(not active and tuple(phases) == GO_PHASES and terminal.get(None) == 'pass'
            and all(terminal.get(n) == 'pass' for n in (*set(GO_PARENTS), 'TestRegistryTLSInputPolicy')),
            'REGISTRY_TLS_COMPLETE_TESTS_REQUIRED')
    return {'required_go_policy_tests_passed': 1, 'required_native_peer_tests_passed': 3,
            'native_transport_phases_passed': 5}


def api_call(base, token, collection, method, identifier, body, key):
    require(collection in ('devices', 'sources') and method in ('POST', 'PATCH', 'DELETE'), 'INVALID_REGISTRY_HTTP_OPERATION')
    identity = identifier if method != 'POST' else body.get('device_id' if collection == 'devices' else 'source_id')
    suffix = '-device' if collection == 'devices' else '-source'
    require(identity in {prefix + suffix for prefix in ('before-tls', 'retained', 'after-tls')}, 'INVALID_REGISTRY_HTTP_RESOURCE')
    endpoint = urlsplit(base)
    require(endpoint.scheme == 'http' and endpoint.hostname == '127.0.0.1' and endpoint.port
            and endpoint.username is None and endpoint.password is None and not endpoint.path
            and not endpoint.query and not endpoint.fragment, 'ISOLATED_LOOPBACK_HTTP_REQUIRED')
    # The Step10 mutation helper only permits its own fixed fixture IDs.
    # This client is restricted to this rehearsal's three synthetic campaigns.
    path = '/api/v1/' + collection + (('/' + identity) if method != 'POST' else '')
    request = Request(base + path, data=json.dumps(body, ensure_ascii=False).encode(), method=method,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Idempotency-Key': key})
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    try:
        try: response = build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=3)
        except HTTPError as exc: response = exc
        with response:
            value = json.load(response)
            if not isinstance(value, dict):
                raise RegistryHTTPError('REGISTRY_HTTP_RESPONSE_INVALID', collection, method, identity, response.status)
            return response.status, value, response.headers
    except RegistryHTTPError: raise
    except (ValueError, UnicodeError):
        raise RegistryHTTPError('REGISTRY_HTTP_RESPONSE_INVALID', collection, method, identity) from None
    except (OSError, TimeoutError):
        raise RegistryHTTPError('REGISTRY_HTTP_TRANSPORT_FAILED', collection, method, identity) from None


def http_result(condition, code, collection, method, identifier, status, value):
    if condition: return
    error = value.get('error')
    api_code = error.get('code') if isinstance(error, dict) else None
    raise RegistryHTTPError(code, collection, method, identifier, status, api_code)


def campaign(base, token, prefix, delete=True):
    device = {**registry.DEVICE, 'device_id': prefix + '-device'}
    source = {**registry.SOURCE, 'source_id': prefix + '-source', 'device_id': device['device_id']}
    calls = []
    def remember(collection, method, identifier, body, key, status, field):
        response = api_call(base, token, collection, method, identifier, body, key)
        code, value, headers = response
        http_result(code == status and isinstance(value.get(field), dict)
                and headers.get('Idempotency-Replayed') == 'false', 'REGISTRY_SEED_OR_MUTATION_FAILED',
                collection, method, identifier or body.get('device_id' if collection == 'devices' else 'source_id'), code, value)
        calls.append((collection, method, identifier, body, key, status, field, value[field]))
        return value[field]
    d = remember('devices', 'POST', None, device, prefix + '-create-device', 201, 'device')
    s = remember('sources', 'POST', None, source, prefix + '-create-source', 201, 'source')
    if delete:
        d = remember('devices', 'PATCH', device['device_id'], {'schema_version': 'v1', 'expected_version': d['version'],
            'display_name': 'TLS 이력 장치'}, prefix + '-update-device', 200, 'device')
        s = remember('sources', 'PATCH', source['source_id'], {'schema_version': 'v1', 'expected_version': s['version'],
            'display_name': 'TLS 이력 소스'}, prefix + '-update-source', 200, 'source')
        body = {'schema_version': 'v1', 'expected_version': d['version']}
        registry.expect_error(api_call(base, token, 'devices', 'DELETE', device['device_id'], body,
                                       prefix + '-delete-device'), 409, 'DEVICE_HAS_ACTIVE_SOURCES')
        remember('sources', 'DELETE', source['source_id'], {'schema_version': 'v1', 'expected_version': s['version']},
                 prefix + '-delete-source', 200, 'deletion')
        remember('devices', 'DELETE', device['device_id'], body, prefix + '-delete-device', 200, 'deletion')
    return {'calls': calls, 'device_id': device['device_id'], 'source_id': source['source_id'],
            'deleted': delete, 'device': d, 'source': s}


def replay(base, token, campaigns):
    active_devices, active_sources = [], []
    for history in campaigns:
        for collection, method, identifier, body, key, status, field, expected in history['calls']:
            code, value, headers = api_call(base, token, collection, method, identifier, body, key)
            http_result(code == status and value.get(field) == expected
                    and headers.get('Idempotency-Replayed') == 'true', 'REGISTRY_HISTORY_REPLAY_CHANGED',
                    collection, method, identifier or body.get('device_id' if collection == 'devices' else 'source_id'), code, value)
        for collection, name, field in (('devices', 'device_id', 'device'), ('sources', 'source_id', 'source')):
            code, value, _ = registry.request(base, '/api/v1/' + collection + '/' + history[name], token)
            require(code == (404 if history['deleted'] else 200), 'REGISTRY_TOMBSTONE_OR_LOOKUP_CHANGED')
            if not history['deleted']: require(value.get(field) == history[field], 'REGISTRY_CURRENT_ROW_CHANGED')
        if not history['deleted']:
            active_devices.append(history['device']); active_sources.append(history['source'])
    for collection, expected, identity in (('devices', active_devices, 'device_id'), ('sources', active_sources, 'source_id')):
        code, page, _ = registry.request(base, '/api/v1/' + collection, token)
        require(code == 200 and page.get('items') == sorted(expected, key=lambda x: x[identity])
                and page.get('next_cursor') is None, 'REGISTRY_LIST_CHANGED')


def runtime_tls_sessions(docker, runtime_ip):
    value = json.loads(sql(docker, "SELECT json_build_object('count',count(*),'safe',coalesce(bool_and(s.ssl AND "
        "s.version IN ('TLSv1.2','TLSv1.3') AND host(a.client_addr)='" + runtime_ip + "'),false)) "
        "FROM pg_stat_activity a JOIN pg_stat_ssl s ON a.pid=s.pid WHERE a.usename='camera_runtime' AND a.datname='vms_camera';"))
    require(value['count'] >= 1 and value['safe'] is True, 'ACTUAL_API_TLS_SESSIONS_REQUIRED')


def verify_http_binding(docker, storage_network, addresses, port, api_image, db_image):
    """Read selected metadata only; declared PortBindings alone are not proof."""
    ids = []
    for service in ('camera-api', 'camera-db'):
        identifier = docker.compose(['ps', '-q', service]).decode().strip()
        require(re.fullmatch('[0-9a-f]{64}', identifier) is not None, 'ISOLATED_HTTP_CONTAINER_ID_INVALID')
        ids.append(identifier)
    require(ids[0] != ids[1], 'ISOLATED_HTTP_CONTAINER_ID_INVALID')
    try:
        rows = [json.loads(line) for line in docker.run(['inspect', '--format', HTTP_BINDING_FORMAT, *ids]).decode().splitlines()]
        require(len(rows) == 2 and all(isinstance(row, dict) for row in rows), 'ISOLATED_HTTP_CONTAINER_METADATA_INVALID')
        containers = {row.get('Id'): row for row in rows}
        require(set(containers) == set(ids), 'ISOLATED_HTTP_CONTAINER_METADATA_INVALID')
        http_network = docker.project + '-http'
        networks = json.loads(docker.run(['network', 'inspect', http_network, storage_network]))
        require(isinstance(networks, list) and len(networks) == 2 and all(isinstance(n, dict) for n in networks),
                'ISOLATED_HTTP_NETWORK_METADATA_INVALID')
        networks = {n.get('Name'): n for n in networks}
        require(set(networks) == {http_network, storage_network}, 'ISOLATED_HTTP_NETWORK_METADATA_INVALID')
        for name, internal in ((http_network, False), (storage_network, True)):
            n = networks[name]
            require(n.get('Driver') == 'bridge' and n.get('Internal') is internal
                and re.fullmatch('[0-9a-f]{64}', n.get('Id', '')) is not None
                and n.get('Labels', {}).get('com.docker.compose.project') == docker.project,
                'ISOLATED_HTTP_NETWORK_BOUNDARY_INVALID')
        require(set(networks[http_network].get('Containers', {})) == {ids[0]}, 'ISOLATED_HTTP_NETWORK_PEERS_INVALID')
        for i, service, image in ((0, 'camera-api', api_image), (1, 'camera-db', db_image)):
            row = containers[ids[i]]; labels = row.get('Labels') or {}; attached = row.get('Networks') or {}
            require(row.get('Running') is True and row.get('Image') == image
                    and labels.get('com.docker.compose.project') == docker.project
                    and labels.get('com.docker.compose.service') == service
                    and labels.get('com.docker.compose.project.working_dir') == str(docker.root),
                    'ISOLATED_HTTP_CONTAINER_BINDING_INVALID')
            expected = {http_network, storage_network} if i == 0 else {storage_network}
            require(set(attached) == expected and attached[storage_network].get('IPAddress') == addresses[1 if i == 0 else 0]
                    and all(attached[name].get('NetworkID') == networks[name]['Id'] for name in expected),
                    'ISOLATED_HTTP_SOURCE_OR_NETWORK_CHANGED')
        api, database = containers[ids[0]], containers[ids[1]]
        expected_port = {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}
        require(api.get('Ports') == expected_port and api.get('PortBindings') == expected_port,
                'ISOLATED_HTTP_PORT_NOT_PUBLISHED')
        require(not database.get('PortBindings') and all(not bindings for bindings in (database.get('Ports') or {}).values()),
                'ISOLATED_DATABASE_PORT_PUBLISHED')
    except (ValueError, TypeError, KeyError, AttributeError):
        raise CheckError('ISOLATED_HTTP_BINDING_METADATA_INVALID') from None


def readiness_diagnostic(base):
    """Allowlisted response fields distinguish HTTP reachability and DB readiness."""
    try:
        status, value, _ = registry.request(base, '/health/ready')
        if not isinstance(value, dict): return {'response_is_object': False}
        result = {'response_is_object': True,
            'scope': value.get('scope') if value.get('scope') in ('camera_registry', 'http_api_foundation', 'process') else 'other',
            'platform': value.get('platform') if value.get('platform') in ('camera', 'model', 'analysis', 'operation') else 'other',
            'ready': value.get('ready') if type(value.get('ready')) is bool else None,
            'business_runtime_ready_present': 'business_runtime_ready' in value,
            'business_runtime_ready': value.get('business_runtime_ready') if type(value.get('business_runtime_ready')) is bool else None}
        if type(status) is int and 100 <= status <= 599: result['status'] = status
        return result
    except Exception as exc:
        kind = type(exc).__name__
        return {'exception_type': kind if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind) else 'UnknownError'}


def run_probe(docker, service, parent, mode, base):
    docker.compose(['exec', '-T', '-e', 'CAMERA_REGISTRY_TLS_MODE=' + mode, '-e', 'CAMERA_TLS_TEST_BASE=' + base,
        service, '/exchange/test2json', '-t', '-p', PACKAGE, '/exchange/registry.test', '-test.v=test2json',
        '-test.count=1', '-test.run=^' + parent + '$', '-test.timeout=80s'], timeout=100)


def cleanup(docker, network, network_attempted):
    if (docker.root / 'compose.json').exists():
        docker.compose(['--profile', '*', 'down', '--volumes', '--remove-orphans', '--timeout', '10'], timeout=90)
    if network_attempted:
        rows = docker.run(['network', 'ls', '--filter', 'label=com.docker.compose.project=' + docker.project,
                           '--format', '{{.ID}} {{.Name}}']).decode().splitlines()
        for line in rows:
            values = line.split(); require(len(values) == 2, 'ISOLATED_CLEANUP_IDENTITY_INVALID')
            if values[1] == network: docker.run(['network', 'rm', values[0]])
    require(not docker.run(['ps', '-aq', '--filter', 'label=com.docker.compose.project=' + docker.project]).strip()
            and not docker.run(['volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + docker.project]).strip()
            and not docker.run(['network', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + docker.project]).strip(),
            'ISOLATED_RESOURCES_REMAIN')


def empty_namespace(docker):
    for args in (['ps', '-aq'], ['volume', 'ls', '-q'], ['network', 'ls', '-q']):
        require(not docker.run([*args, '--filter', 'label=com.docker.compose.project=' + docker.project]).strip(),
                'ISOLATED_NAMESPACE_ALREADY_EXISTS')


def verify(root, docker_factory=RehearsalDocker, fixture=prepare_fixture):
    root = Path(root).absolute(); revision = checked_source(root)
    directory = root / 'var/camera/registry-tls-checks'; private_directory(directory)
    project = PREFIX + secrets.token_hex(6); network = project + '-storage'
    log = directory / (project + '.log'); atomic_write(log, b'')
    work = Path(tempfile.mkdtemp(prefix=project + '-')); docker = docker_factory(work, project, root, log)
    stage, failure, summary, completed = 'accepted_source', None, {}, []
    network_attempted = False; namespace_checked = False; cleaned = False; vetted = False; unit_race = False
    api_image = db_image = None; diagnostics = False; exception_type = None; http_failure = None
    binding_checks = 0; ready_probe = None; base = None
    try:
        with activation_lock(root):
            stage = 'production_observation'
            prod = supply.SupplyDocker(root); daemon = prod.preflight()
            before, containers, db_image, production_network = supply.observe(root, prod)
            api_image = containers['camera-api']['Image']; require(docker.preflight() == daemon, 'DOCKER_DAEMON_CHANGED')
            env_digest = pki.sha((root / '.env').read_bytes())
            empty_namespace(docker); namespace_checked = True
            stage = 'isolated_network'; network_attempted = True
            docker.run(['network', 'create', '--internal', '--label', 'com.docker.compose.project=' + project, network])
            addresses = transport.network_addresses(docker.run(['network', 'inspect', '--format', '{{json .IPAM.Config}}', network]))
            stage = 'synthetic_fixture'; fixture(work, root, addresses)
            token = secrets.token_urlsafe(36); port = unused_port(); base = 'http://127.0.0.1:' + str(port)
            recipe_args = (root, work, project, network, addresses, api_image, db_image, token, port)
            atomic_write(work / 'compose.json', pki.encoded(compose_recipe(*recipe_args)))
            stage = 'probe_build'; docker.compose(['run', '--rm', '--no-deps', 'probe-build'], timeout=240)
            vetted = True; unit_race = True
            stage = 'input_ownership'; docker.compose(['run', '--rm', '--no-deps', 'files-owner'], timeout=90)
            stage = 'plaintext_database'; docker.compose(['up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '60', 'camera-db'], timeout=100)
            stage = 'schema7_migration'
            migrated = json.loads(docker.compose(['run', '--rm', '--no-deps', 'camera-migrate'], timeout=90))
            require(migrated.get('version') == 7 and migrated.get('applied') == 7, 'ISOLATED_SCHEMA7_BOOTSTRAP_REQUIRED')
            registry.check_schema(root, docker, 7); registry.verify_runtime_grants(docker)
            stage = 'plaintext_registry_seed'
            docker.compose(['up', '-d', '--no-build', '--pull', 'never', '--no-deps', '--wait', '--wait-timeout', '60', 'camera-api'], timeout=100)
            stage = 'plaintext_http_binding'
            verify_http_binding(docker, network, addresses, port, api_image, db_image); binding_checks += 1
            stage = 'plaintext_registry_seed'
            registry.verify_version(base, token, '0.7.0-device-delete')
            histories = [campaign(base, token, 'before-tls'), campaign(base, token, 'retained', False)]
            replay(base, token, histories); baseline = registry.registry_fingerprint(docker, include_device_delete=True)
            completed.append('schema7-plaintext-history')
            stage = 'plaintext_api_drain'; docker.compose(['stop', '--timeout', '15', 'camera-api'])
            require(sql(docker, "SELECT count(*) FROM pg_stat_activity WHERE usename IN ('camera_runtime','camera_migrator');") == '0', 'ISOLATED_DATABASE_WRITERS_REMAIN')
            require(registry.registry_fingerprint(docker, include_device_delete=True) == baseline, 'PRE_CUTOVER_ROWS_CHANGED')
            old_data = json.loads(docker.run(['volume', 'inspect', project + '_camera-data']))
            completed.append('plaintext-api-drained')
            stage = 'tls_database'; atomic_write(work / 'compose.json', pki.encoded(compose_recipe(*recipe_args, tls=True)))
            docker.compose(['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '60', 'camera-db'], timeout=100)
            docker.compose(['exec', '-T', '--user', '999:999', 'camera-db', '/bin/sh', '-ec', transport.VERIFY_DATABASE], timeout=30)
            require(json.loads(docker.run(['volume', 'inspect', project + '_camera-data'])) == old_data, 'ISOLATED_DATA_VOLUME_REPLACED')
            require(sql(docker, "SELECT current_setting('ssl');") == 'on', 'TLS_DATABASE_NOT_ENABLED')
            registry.check_schema(root, docker, 7); registry.verify_runtime_grants(docker)
            require(registry.registry_fingerprint(docker, include_device_delete=True) == baseline, 'TLS_CUTOVER_ROWS_CHANGED')
            completed.append('tls-database-same-schema-and-data')
            stage = 'mtls_migration_replay'; migrated = json.loads(docker.compose(['run', '--rm', '--no-deps', 'camera-migrate'], timeout=90))
            require(migrated.get('version') == 7 and migrated.get('applied') == 0, 'TLS_MIGRATION_REPLAY_CHANGED')
            require(registry.registry_fingerprint(docker, include_device_delete=True) == baseline, 'MIGRATION_REPLAY_ROWS_CHANGED')
            completed.append('mtls-migration-no-schema-upgrade')
            stage = 'tls_api_and_native_probes'
            docker.compose(['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '60', 'camera-api'], timeout=100)
            stage = 'tls_http_binding'
            verify_http_binding(docker, network, addresses, port, api_image, db_image); binding_checks += 1
            stage = 'tls_api_and_native_probes'
            registry.verify_version(base, token, '0.7.0-device-delete'); runtime_tls_sessions(docker, addresses[1])
            run_probe(docker, 'camera-api', GO_PARENTS[0], 'runtime', '/registry-runtime')
            docker.compose(['up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'probe-maintenance', 'probe-offsource'], timeout=90)
            run_probe(docker, 'probe-maintenance', GO_PARENTS[2], 'migrator', '/registry-maintenance')
            run_probe(docker, 'probe-offsource', GO_PARENTS[4], 'offsource', '/registry-offsource')
            summary = summarize_go(log); completed.append('native-tls-role-source-authentication')
            stage = 'legacy_history_replay'; replay(base, token, histories)
            require(registry.registry_fingerprint(docker, include_device_delete=True) == baseline, 'LEGACY_REPLAY_ROWS_CHANGED')
            completed.append('legacy-history-and-lists-preserved')
            stage = 'new_tls_registry_writes'; histories.append(campaign(base, token, 'after-tls')); replay(base, token, histories)
            latest = registry.registry_fingerprint(docker, include_device_delete=True); completed.append('new-tls-registry-writes')
            stage = 'api_recreation'
            docker.compose(['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '60', 'camera-api'], timeout=100)
            stage = 'recreated_api_http_binding'
            verify_http_binding(docker, network, addresses, port, api_image, db_image); binding_checks += 1
            stage = 'api_recreation'
            registry.verify_version(base, token, '0.7.0-device-delete'); replay(base, token, histories); runtime_tls_sessions(docker, addresses[1])
            require(registry.registry_fingerprint(docker, include_device_delete=True) == latest, 'RECREATED_API_ROWS_CHANGED')
            completed.append('recreated-api-replay')
            stage = 'database_and_api_recreation'; docker.compose(['stop', '--timeout', '15', 'camera-api'])
            require(sql(docker, "SELECT count(*) FROM pg_stat_activity WHERE usename IN ('camera_runtime','camera_migrator');") == '0', 'ISOLATED_DATABASE_WRITERS_REMAIN')
            docker.compose(['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '60', 'camera-db'], timeout=100)
            docker.compose(['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '60', 'camera-api'], timeout=100)
            stage = 'recreated_db_api_http_binding'
            verify_http_binding(docker, network, addresses, port, api_image, db_image); binding_checks += 1
            stage = 'database_and_api_recreation'
            registry.check_schema(root, docker, 7); registry.verify_runtime_grants(docker)
            registry.verify_version(base, token, '0.7.0-device-delete'); replay(base, token, histories); runtime_tls_sessions(docker, addresses[1])
            require(registry.registry_fingerprint(docker, include_device_delete=True) == latest
                    and json.loads(docker.run(['volume', 'inspect', project + '_camera-data'])) == old_data, 'RECREATED_DATABASE_ROWS_CHANGED')
            completed.append('recreated-database-and-api-replay')
            stage = 'source_and_production_recheck'
            require(checked_source(root) == revision and prod.preflight() == daemon and prod.snapshot() == before
                    and pki.sha((root / '.env').read_bytes()) == env_digest, 'PRODUCTION_OR_SOURCE_CHANGED')
            require(supply.observe(root, prod)[0] == before
                    and prod.run(['network', 'inspect', 'vms-project_camera-storage']) == production_network,
                    'PRODUCTION_IDENTITY_OR_NETWORK_CHANGED')
            completed.append('production-read-only-recheck')
    except (Exception, KeyboardInterrupt) as exc:
        failure = str(exc) if isinstance(exc, (CheckError, pki.CandidateError, ActivationError)) else 'REGISTRY_TLS_REHEARSAL_FAILED'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', failure): failure = 'REGISTRY_TLS_REHEARSAL_FAILED'
        exception_type = type(exc).__name__
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', exception_type): exception_type = 'UnknownError'
        if isinstance(exc, RegistryHTTPError): http_failure = exc.step
        if failure == 'CAMERA_REGISTRY_READINESS_FAILED' and base is not None: ready_probe = readiness_diagnostic(base)
    finally:
        failed_stage = stage if failure else None
        failed_exit = docker.last_exit
        if failure and namespace_checked and (work / 'compose.json').exists():
            try:
                docker.compose(['logs', '--no-color', '--tail', '120', 'camera-db', 'camera-api'], timeout=30)
                diagnostics = True
            except (Exception, KeyboardInterrupt): pass
        try:
            if namespace_checked: cleanup(docker, network, network_attempted)
            cleaned = True
        except (Exception, KeyboardInterrupt): failure = 'ISOLATED_REGISTRY_TLS_CLEANUP_FAILED'; failed_stage = failed_stage or 'cleanup'
        if cleaned: shutil.rmtree(work)
    success = failure is None and cleaned
    report = {'status': 'passed' if success else 'failed', 'scope': SCOPE, 'project': project, 'checked_revision': revision,
              'registry_schema_version': 7, 'running_image_reused_for_test': success,
              'test_api_image': api_image, 'test_database_image': db_image,
              'go_unit_race_passed': vetted and unit_race, 'go_vet_passed': vetted,
              'native_probe_race_enabled': False, **(summary if success else {}), **NO_CHANGES,
              'synthetic_pki_only': True, 'isolated_resources_removed': cleaned, 'synthetic_input_removed': not work.exists(),
              'isolated_diagnostics_collected': diagnostics,
              'isolated_http_binding_checks_passed': binding_checks,
              'log': str(log)}
    if success:
        report.update(cutover_phases_passed=len(completed), schema7_preserved=True, existing_rows_and_all_journals_preserved=True,
            registry_create_update_delete_replay_verified=True, active_children_rejection_verified=True,
            actual_api_tls_sessions_verified=True, runtime_uid_and_ro_supply_verified=True,
            database_uid_and_ro_tls_control_verified=True, migrator_certificate_role_map_verified=True,
            migrator_tls_authentication='certificate-cn-map', runtime_tls_authentication='scram-sha-256',
            wrong_ca_hostname_password_plaintext_control_db_and_source_rejected=True,
            api_and_database_recreation_verified=True, isolated_data_volume_preserved=True,
            isolated_loopback_http_port_and_storage_boundary_verified=True,
            production_services_and_network_unchanged=True)
    else:
        report.update(code=failure, failed_stage=failed_stage, last_completed_phase=completed[-1] if completed else None)
        if exception_type: report['exception_type'] = exception_type
        if http_failure: report['failed_http_step'] = http_failure
        if ready_probe: report['http_readiness_probe'] = ready_probe
        if failed_exit is not None: report['last_command_exit_code'] = failed_exit
        if not cleaned: report['retained_workspace'] = str(work)
    report['report'] = str(directory / (project + '.json')); atomic_write(Path(report['report']), pki.encoded(report))
    return report


def main():
    try:
        result = verify(Path(__file__).resolve().parents[3]); print(json.dumps(result)); return 0 if result['status'] == 'passed' else 1
    except (Exception, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': 'REGISTRY_TLS_PREFLIGHT_FAILED', **NO_CHANGES}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
