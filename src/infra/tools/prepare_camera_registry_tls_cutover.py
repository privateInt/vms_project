#!/usr/bin/env python3
"""Prepare schema7 TLS control/DSN files and a Compose recipe; never start production services."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlencode

import camera_activation as activation
import prepare_camera_database_tls_candidate as pki
import prepare_camera_database_tls_supply as supply
import test_camera_registry_tls_cutover as rehearsal

SCOPE = 'camera_registry_schema7_tls_cutover_preparation'
ACCEPTED = '1e3cc7206a7f2cf0c3298e25635961d5ad6c26bed02c830c80ade1139d2a4159'
DIRECTORY = ('var', 'camera', 'registry-tls-preparations')
PREPARED = 'prepared-v1'
LABEL = 'io.vms.camera.registry-tls-control'
CONTROL = ('hba.conf', 'pg_ident.conf')
FILES = {'receipt.json': 0o600, 'compose.camera.json': 0o600, 'compose.root.json': 0o600,
         'runtime-dsn': 0o444, 'migrator-dsn': 0o444}
STAGES = ('accepted_source', 'coordination_lock', 'docker_preflight', 'environment_binding',
          'current_production', 'accepted_supply', 'registry_secrets',
          'preparation_files', 'compose_validation', 'control_volume', 'final_recheck')
NO_CHANGES = {**rehearsal.NO_CHANGES, 'current_compose_modified': False,
              'credential_key_material_read': False, 'host_permissions_modified': False,
              'production_restore_fence_implemented': False,
              'production_endpoint_and_sources_reserved': False}
for _field in ('production_candidate_files_read', 'production_prepared_supply_files_read'):
    NO_CHANGES.pop(_field)


class PreparationError(Exception):
    pass


def require(value, code):
    if not value: raise PreparationError(code)


def checked_source(root):
    revision = rehearsal.checked_source(root)
    manifest = json.loads((root / 'project-manifest.json').read_text())
    require(manifest.get('credential_registry_tls_cutover_server_verified') is True
            and manifest.get('validated_credential_registry_tls_cutover_project_sha256') == ACCEPTED
            and manifest.get('credential_registry_tls_cutover_latest_server_status') == 'passed'
            and manifest.get('credential_registry_tls_cutover_latest_server_checked_revision') == ACCEPTED
            and manifest.get('credential_registry_tls_cutover_preparation_implemented') is True,
            'ACCEPTED_REGISTRY_TLS_REHEARSAL_REQUIRED')
    require({'src/infra/tools/prepare_camera_registry_tls_cutover.py',
             'src/infra/tools/test_prepare_camera_registry_tls_cutover.py'} <= manifest['files'].keys(),
            'REGISTRY_TLS_PREPARATION_SOURCE_INCOMPLETE')
    return revision, manifest


def directory(root, parts, create=False):
    root = Path(root).absolute()
    require('..' not in root.parts and not any(v in str(root) for v in (',', '$', '\n', '\r')),
            'REGISTRY_TLS_PROJECT_PATH_INVALID')
    fd = os.open('/', pki.DIR_FLAGS)
    try:
        for name in root.parts[1:]:
            child = os.open(name, pki.DIR_FLAGS, dir_fd=fd); os.close(fd); fd = child
        pki.owned(os.fstat(fd))
        for index, name in enumerate(parts):
            if create:
                try: os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(name, pki.DIR_FLAGS, dir_fd=fd); os.close(fd); fd = child
            pki.owned(os.fstat(fd), 0o700 if index >= 2 else None)
        return fd
    except BaseException:
        os.close(fd); raise


def read_mode(fd, name, mode):
    file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(file); pki.owned(before, regular=True)
        require(stat.S_IMODE(before.st_mode) == mode and 0 < before.st_size <= pki.MAX_BYTES,
                'REGISTRY_TLS_PREPARATION_FILE_INVALID')
        body = b''
        while len(body) <= pki.MAX_BYTES:
            chunk = os.read(file, pki.MAX_BYTES + 1 - len(body))
            if not chunk: break
            body += chunk
        after = os.fstat(file)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        require(tuple(getattr(before, k) for k in fields) == tuple(getattr(after, k) for k in fields)
                and len(body) == before.st_size, 'REGISTRY_TLS_PREPARATION_FILE_CHANGED')
        return body
    finally: os.close(file)


def environment(root):
    fd = directory(root, ())
    try: return read_mode(fd, '.env', 0o600)
    finally: os.close(fd)


def validate_current_environment(body, manifest):
    """Accept the already-rehearsed image pin; do not reuse the initial activation writer."""
    text = body.decode('utf-8')
    for name in ('COMPOSE_FILE', 'COMPOSE_PROJECT_NAME'):
        require(not re.search(r'^\s*(?:export\s+)?' + name + r'\s*=', text, re.M),
                'REGISTRY_TLS_CUSTOM_COMPOSE_ENVIRONMENT_REJECTED')
    for name, expected, required in (
            ('VMS_CAMERA_COMPOSE_FILE', activation.ACTIVE, True),
            ('VMS_CAMERA_IMAGE', manifest['credential_registry_tls_cutover_latest_server_test_api_image'], False)):
        entries = re.findall(r'^\s*(?:export\s+)?' + name + r'\s*=\s*(.*?)\s*$', text, re.M)
        require(len(entries) == 1 if required else len(entries) <= 1,
                'REGISTRY_TLS_COMPOSE_ENVIRONMENT_AMBIGUOUS')
        if entries:
            value = entries[0]
            if value[:1] in ('\"', "'"):
                require(len(value) >= 2 and value[-1] == value[0], 'REGISTRY_TLS_COMPOSE_ENVIRONMENT_INVALID')
                value = value[1:-1]
            require(value == expected, 'REGISTRY_TLS_COMPOSE_OR_IMAGE_PIN_CHANGED')


def accepted_supply(root, manifest, docker, network, db_image):
    """Read the accepted candidate receipt and selected D1c supply; never read ca.key."""
    fd = directory(root, (*pki.DIRECTORY, pki.CANDIDATE))
    try: candidate_bytes = pki.read_file(fd, 'candidate.json')
    finally: os.close(fd)
    require(pki.sha(candidate_bytes) == manifest['credential_database_tls_supply_latest_server_candidate_sha256'],
            'REGISTRY_TLS_ACCEPTED_CANDIDATE_CHANGED')
    candidate_receipt = json.loads(candidate_bytes)
    fd = directory(root, (*supply.DIRECTORY, supply.SUPPLY))
    try:
        receipt_bytes = pki.read_file(fd, 'receipt.json')
        receipt = json.loads(receipt_bytes)
        canonical = {k: v for k, v in receipt.items() if k not in ('supply_sha256', 'volume_names')}
        digest = pki.sha(pki.encoded(canonical))
        require(receipt_bytes == pki.encoded(receipt)
                and digest == receipt['supply_sha256']
                == manifest['credential_database_tls_supply_latest_server_supply_sha256']
                and receipt['candidate_sha256'] == pki.sha(candidate_bytes)
                and receipt['network_recipe'] == network and receipt['probe_image'] == db_image
                and receipt['supply_directory'] == str(root.joinpath(*supply.DIRECTORY, supply.SUPPLY))
                and receipt['source_directory'] == str(root.joinpath(*pki.DIRECTORY, pki.CANDIDATE))
                and receipt['volume_names'] == manifest['credential_database_tls_supply_latest_server_tls_supply_volume_names'],
                'REGISTRY_TLS_ACCEPTED_SUPPLY_BINDING_CHANGED')
        snapshot = {'candidate.json': candidate_bytes}
        wanted = {'receipt.json': receipt_bytes, 'compose.recipe.json': pki.read_file(fd, 'compose.recipe.json')}
        for role, (_, names) in supply.ROLES.items():
            child = os.open(role, pki.DIR_FLAGS, dir_fd=fd)
            try:
                for name in names:
                    body = pki.read_file(child, name)
                    require(pki.sha(body) == candidate_receipt['files_sha256'][name],
                            'REGISTRY_TLS_ACCEPTED_SUPPLY_BYTES_CHANGED')
                    if name in snapshot: require(snapshot[name] == body, 'REGISTRY_TLS_SUPPLY_CA_COPIES_DIFFER')
                    snapshot[name] = body; wanted[role + '/' + name] = body
                if role != 'runtime':
                    prefix = 'server' if role == 'database' else 'maintenance'
                    require(pki.openssl(child, ['pkey', '-in', prefix + '.key', '-pubout']) ==
                            pki.openssl(child, ['x509', '-in', prefix + '.pem', '-pubkey', '-noout']),
                            'REGISTRY_TLS_SUPPLY_KEY_CERTIFICATE_MISMATCH')
                    der = pki.openssl(child, ['x509', '-in', prefix + '.pem', '-outform', 'DER'])
                    field = 'server_certificate_sha256' if role == 'database' else 'maintenance_certificate_sha256'
                    require(pki.sha(der) == receipt['public_certificates'][field],
                            'REGISTRY_TLS_SUPPLY_LEAF_CERTIFICATE_CHANGED')
                    args = ['verify', '-x509_strict', '-CAfile', 'ca.pem', '-purpose',
                            'sslserver' if role == 'database' else 'sslclient']
                    if role == 'database': args += ['-verify_hostname', pki.SERVER_NAME]
                    pki.openssl(child, [*args, prefix + '.pem'])
                    for name in ('ca.pem', prefix + '.pem'):
                        pki.openssl(child, ['x509', '-in', name, '-checkend', '86400', '-noout'])
            finally: os.close(child)
        expected_receipt, expected_files = supply.bundle(root, docker.project, db_image, network, snapshot,
                                                        receipt['public_certificates'])
        require(expected_receipt == receipt and expected_files == wanted,
                'REGISTRY_TLS_SUPPLY_RECIPE_CHANGED')
        supply.inspect_bundle(fd, wanted)
    finally: os.close(fd)
    ready, created = supply.prepare_volumes(docker, receipt, snapshot, False)
    require(ready and created == 0, 'REGISTRY_TLS_PREPARED_SUPPLY_VOLUMES_REQUIRED')
    return receipt, wanted


def current_binding(root, docker, manifest):
    before, containers, image, raw_network = supply.observe(root, docker)
    for service, field in (('camera-api', 'test_api_image'), ('camera-db', 'test_database_image')):
        require(before[service]['image'] == manifest['credential_registry_tls_cutover_latest_server_' + field],
                'REGISTRY_TLS_REHEARSED_IMAGE_REQUIRED')
    proposal = manifest['credential_database_tls_supply_latest_server_fixed_address_recipe']
    network = supply.network_recipe(raw_network, docker.project, containers, proposal)
    configured = json.loads(docker.compose(['config', '--format', 'json'], active=False))
    names = set(configured['services'])
    require({'camera-api', 'camera-db', 'model-api', 'analysis-api', 'operation-api'} <= names
            <= {'camera-api', 'camera-db', 'camera-migrate', 'model-api', 'analysis-api', 'operation-api'},
            'REGISTRY_TLS_CURRENT_COMPOSE_SERVICES_CHANGED')
    ports = configured['services']['camera-api'].get('ports', [])
    require(len(ports) == 1 and ports[0].get('host_ip') == '127.0.0.1'
            and ports[0].get('target') == 8080 and ports[0].get('protocol') == 'tcp'
            and re.fullmatch('[1-9][0-9]{0,4}', str(ports[0].get('published', '')))
            and 1 <= int(ports[0]['published']) <= 65535, 'REGISTRY_TLS_LOOPBACK_HTTP_REQUIRED')
    published = int(ports[0]['published']); port_map = {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(published)}]}
    api, db = containers['camera-api'], containers['camera-db']
    require(api['NetworkSettings'].get('Ports') == port_map
            and api['HostConfig'].get('PortBindings') == port_map,
            'REGISTRY_TLS_CURRENT_HTTP_NOT_PUBLISHED')
    storage, http = docker.project + '_camera-storage', docker.project + '_default'
    require(set(api['NetworkSettings']['Networks']) == {storage, http}
            and set(db['NetworkSettings']['Networks']) == {storage}
            and not db['HostConfig'].get('PortBindings')
            and all(not v for v in (db['NetworkSettings'].get('Ports') or {}).values()),
            'REGISTRY_TLS_CURRENT_NETWORK_BOUNDARY_CHANGED')
    http_network = json.loads(docker.run(['network', 'inspect', http]))
    require(len(http_network) == 1, 'REGISTRY_TLS_HTTP_NETWORK_INVALID')
    http_network = http_network[0]
    require(http_network.get('Name') == http and http_network.get('Internal') is False
            and http_network.get('Driver') == 'bridge' and http_network.get('Scope') == 'local'
            and re.fullmatch('[0-9a-f]{64}', http_network.get('Id', '')) is not None
            and http_network.get('Labels', {}).get('com.docker.compose.project') == docker.project
            and http_network.get('Labels', {}).get('com.docker.compose.network') == 'default'
            and api['NetworkSettings']['Networks'][http].get('NetworkID') == http_network.get('Id')
            and api['Id'] in http_network.get('Containers', {}), 'REGISTRY_TLS_HTTP_NETWORK_INVALID')
    require(docker.volume_exists(), 'REGISTRY_TLS_EXISTING_DATA_VOLUME_REQUIRED')
    data = [v for v in db.get('Mounts', []) if v.get('Destination') == '/var/lib/postgresql/data']
    require(len(data) == 1 and data[0].get('Type') == 'volume' and data[0].get('RW') is True
            and data[0].get('Name') == docker.project + '_camera-data', 'REGISTRY_TLS_CURRENT_DATA_VOLUME_CHANGED')
    return {'snapshot': before, 'network': network, 'http_network': http_network,
            'raw_network': json.loads(raw_network), 'port': published,
            'config_sha256': pki.sha(pki.encoded(configured)), 'database_image': image}


def recipes(root, project, current, tls_receipt, control_volume):
    path = root.joinpath(*DIRECTORY, PREPARED)
    network = current['network']
    ro = lambda source, target: {'type': 'volume', 'source': source, 'target': target,
                                'read_only': True, 'volume': {'nocopy': True}}
    secured = {'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true']}
    image = current['snapshot']['camera-api']['image']
    db = {'image': current['database_image'], 'user': '999:999',
        'environment': {'POSTGRES_DB': 'vms_camera', 'POSTGRES_USER': 'camera_admin',
                        'POSTGRES_PASSWORD_FILE': '/run/secrets/camera_admin_password'},
        'secrets': ['camera_admin_password'], 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
        'command': ['postgres', '-c', 'ssl=on', '-c', 'ssl_min_protocol_version=TLSv1.2',
            '-c', 'ssl_cert_file=/run/camera-db-tls/server.pem', '-c', 'ssl_key_file=/run/camera-db-tls/server.key',
            '-c', 'ssl_ca_file=/run/camera-db-tls/ca.pem', '-c', 'hba_file=/run/camera-db-control/hba.conf',
            '-c', 'ident_file=/run/camera-db-control/pg_ident.conf'],
        'volumes': [{'type': 'volume', 'source': 'camera-data', 'target': '/var/lib/postgresql/data',
                     'volume': {'nocopy': True}}, ro('tls-database', '/run/camera-db-tls'),
                    ro('tls-control', '/run/camera-db-control')],
        'networks': {'camera-storage': {'ipv4_address': network['database_ip'], 'aliases': [pki.SERVER_NAME]}},
        'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -h 127.0.0.1 -U camera_admin -d vms_camera'],
                        'interval': '2s', 'timeout': '3s', 'retries': 30, 'start_period': '10s'},
        'restart': 'unless-stopped', 'stop_grace_period': '30s'}
    api = {**secured, 'image': image, 'user': '65532:65532',
        'environment': {'HTTP_ADDR': ':8080', 'VMS_API_TOKEN': '${VMS_API_TOKEN:?VMS_API_TOKEN required}',
                        'CAMERA_DATABASE_URL_FILE': '/run/secrets/camera_runtime_tls_dsn'},
        'secrets': ['camera_runtime_tls_dsn'], 'volumes': [ro('tls-runtime', '/run/camera-tls')],
        'networks': {'default': {}, 'camera-storage': {'ipv4_address': network['runtime_source_ip']}},
        'ports': [{'target': 8080, 'published': str(current['port']), 'host_ip': '127.0.0.1', 'protocol': 'tcp'}],
        'depends_on': {'camera-db': {'condition': 'service_healthy'}},
        'healthcheck': {'test': ['CMD', '/vms-api', '--healthcheck'], 'interval': '10s', 'timeout': '3s',
                        'retries': 3, 'start_period': '20s'},
        'restart': 'unless-stopped', 'stop_grace_period': '10s'}
    migrator = {**secured, 'image': image, 'user': '10002:10002', 'entrypoint': ['/camera-migrate'],
        'command': ['--apply', '--grant-runtime'], 'profiles': ['camera-tools'],
        'environment': {'CAMERA_DATABASE_URL_FILE': '/run/secrets/camera_migrator_tls_dsn'},
        'secrets': ['camera_migrator_tls_dsn'], 'volumes': [ro('tls-maintenance', '/run/camera-maintenance-tls')],
        'networks': {'camera-storage': {'ipv4_address': network['maintenance_source_ip']}}, 'restart': 'no'}
    camera = {'services': {'camera-api': api, 'camera-db': db, 'camera-migrate': migrator},
        # Match the other included platforms' implicit Compose-owned default network.
        # The existing network ID is verified before/after preparation; storage stays external.
        'networks': {'default': {'name': project + '_default'},
                     'camera-storage': {'external': True, 'name': project + '_camera-storage'}},
        'volumes': {'camera-data': {'external': True, 'name': project + '_camera-data'},
                    'tls-control': {'external': True, 'name': control_volume},
                    **{'tls-' + role: {'external': True, 'name': name}
                       for role, name in tls_receipt['volume_names'].items()}},
        'secrets': {'camera_admin_password': {'file': str(root / 'var/camera/secrets/admin-password')},
                    'camera_runtime_tls_dsn': {'file': str(path / 'runtime-dsn')},
                    'camera_migrator_tls_dsn': {'file': str(path / 'migrator-dsn')}}}
    full = {'name': project, 'include': [{'path': str(path / 'compose.camera.json')},
        *[{'path': str(root / 'src/platform' / platform / 'compose.yaml')}
          for platform in ('model', 'analysis', 'operation')]]}
    return camera, full


def bundle(root, project, revision, current, tls_receipt, secret_values, env_hash):
    network = current['network']
    runtime = ('postgres://camera_runtime:' + secret_values['runtime-password'] + '@' + pki.SERVER_NAME +
               ':5432/vms_camera?' + urlencode({'sslmode': 'verify-full', 'sslrootcert': '/run/camera-tls/ca.pem'}) + '\n').encode()
    # Certificate CN is mapped to the existing camera_migrator. No password is forwarded.
    migrator = ('postgres://camera_migrator@' + pki.SERVER_NAME + ':5432/vms_camera?' + urlencode({
        'sslmode': 'verify-full', 'sslrootcert': '/run/camera-maintenance-tls/ca.pem',
        'sslcert': '/run/camera-maintenance-tls/maintenance.pem',
        'sslkey': '/run/camera-maintenance-tls/maintenance.key'}) + '\n').encode()
    control = {'database/hba.conf': rehearsal.hba(network['runtime_source_ip'], network['maintenance_source_ip'], True),
               'database/pg_ident.conf': b'registry_migrator camera_maintenance camera_migrator\n'}
    receipt = {'format_version': 1, 'kind': 'camera-registry-schema7-tls-preparation',
        'intent': 'prepare-only', 'prepared_source_revision': revision, 'accepted_rehearsal_revision': ACCEPTED,
        'accepted_supply_sha256': tls_receipt['supply_sha256'], 'project': project,
        'current_snapshot': current['snapshot'], 'current_compose_sha256': current['config_sha256'],
        'current_env_sha256': env_hash, 'network_recipe': network,
        'http_network_id': current['http_network']['Id'], 'http_port': current['port'],
        'registry_schema_version': 7, 'runtime_tls_authentication': 'scram-sha-256',
        'migrator_tls_authentication': 'certificate-cn-map',
        'files_sha256': {name: pki.sha(body) for name, body in {**control, 'runtime-dsn': runtime, 'migrator-dsn': migrator}.items()},
        'recipe_is_deployable': False, 'activation_allowed': False, 'database_tls_activated': False}
    digest = pki.sha(pki.encoded(receipt))
    volume = project + '-camera-registry-tls-control-' + digest[:16]
    receipt.update(preparation_sha256=digest, control_volume_name=volume)
    camera, full = recipes(root, project, current, tls_receipt, volume)
    return receipt, {**control, 'runtime-dsn': runtime, 'migrator-dsn': migrator,
        'receipt.json': pki.encoded(receipt), 'compose.camera.json': pki.encoded(camera),
        'compose.root.json': pki.encoded(full)}


def inspect_files(fd, wanted):
    pki.owned(os.fstat(fd), 0o700)
    require(set(os.listdir(fd)) == {*FILES, 'database'}, 'REGISTRY_TLS_PREPARATION_INCOMPLETE_OR_UNKNOWN')
    actual = {name: read_mode(fd, name, mode) for name, mode in FILES.items()}
    child = os.open('database', pki.DIR_FLAGS, dir_fd=fd)
    try:
        pki.owned(os.fstat(child), 0o700)
        require(set(os.listdir(child)) == set(CONTROL), 'REGISTRY_TLS_CONTROL_FILES_INVALID')
        actual.update({'database/' + n: pki.read_file(child, n) for n in CONTROL})
    finally: os.close(child)
    require(actual == wanted, 'REGISTRY_TLS_PREPARATION_CHANGED_OR_STALE')


def prepare_files(root, wanted, apply):
    try: fd = directory(root, DIRECTORY, apply)
    except FileNotFoundError:
        require(not apply, 'REGISTRY_TLS_PREPARATION_DIRECTORY_MISSING'); return False, False
    try:
        created = False
        try: leaf = os.open(PREPARED, pki.DIR_FLAGS, dir_fd=fd)
        except FileNotFoundError:
            if not apply: return False, False
            os.mkdir(PREPARED, 0o700, dir_fd=fd); os.fsync(fd)
            leaf = os.open(PREPARED, pki.DIR_FLAGS, dir_fd=fd); created = True
        try:
            if created:
                os.mkdir('database', 0o700, dir_fd=leaf)
                child = os.open('database', pki.DIR_FLAGS, dir_fd=leaf)
                try:
                    for name in CONTROL: pki.write_new(child, name, wanted['database/' + name])
                finally: os.close(child)
                for name, mode in FILES.items():
                    pki.write_new(leaf, name, wanted[name])
                    file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=leaf)
                    try: os.fchmod(file, mode); os.fsync(file)
                    finally: os.close(file)
            inspect_files(leaf, wanted)
            current = directory(root, (*DIRECTORY, PREPARED))
            try:
                a, b = os.fstat(leaf), os.fstat(current)
                require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), 'REGISTRY_TLS_PREPARATION_DIRECTORY_CHANGED')
                inspect_files(current, wanted)
            finally: os.close(current)
        finally: os.close(leaf)
        return True, created
    finally: os.close(fd)


def control_script(initialize=False):
    if initialize:
        return ('set -C\numask 077\ntest -z "$(find /output -mindepth 1 -maxdepth 1 -print -quit)"\n'
                'chmod 0700 /output\n' + ''.join('cat /input/' + n + ' > /output/' + n + '\n' for n in CONTROL)
                + 'chmod 0400 /output/*\nchown 999:999 /output /output/*\nsync /output\n')
    script = 'test "$(id -u):$(id -g)" = 999:999\n'
    script += 'for map in /proc/self/uid_map /proc/self/gid_map; do test "$(awk \'{print $1, $2, $3}\' "$map")" = "0 0 4294967295"; done\n'
    script += 'cd /supply/database\ntest "$(stat -c \'%u:%g:%a\' .)" = 999:999:700\n'
    script += 'test "$(find . -mindepth 1 -maxdepth 1 -printf \'%f\\n\' | sort)" = "' + '\n'.join(CONTROL) + '"\n'
    for name in CONTROL:
        script += f'test -f {name} && test ! -L {name}\ntest "$(stat -c \'%u:%g:%a:%h\' {name})" = 999:999:400:1\n'
    script += 'if error=$(touch .write-probe 2>&1); then exit 41; fi\ncase "$error" in *"Read-only file system"*) ;; *) exit 42 ;; esac\n'
    return script + 'printf \'REGISTRY_TLS_CONTROL_OK\\n\'\nsha256sum ' + ' '.join(CONTROL) + '\n'


def prepare_control(docker, root, receipt, wanted, apply):
    name = receipt['control_volume_name']
    labels = {LABEL: receipt['preparation_sha256'], LABEL + '.project': docker.project}
    before = docker.volume(name, labels)
    helper = {'supply_sha256': receipt['preparation_sha256'], 'probe_image': receipt['current_snapshot']['camera-db']['image'],
              'supply_directory': str(root.joinpath(*DIRECTORY, PREPARED)), 'volume_names': {'database': name}}
    created = 0
    if before is None:
        if not apply: return False, 0
        args = ['volume', 'create', '--driver', 'local']
        for k, v in labels.items(): args += ['--label', k + '=' + v]
        docker.run([*args, name]); before = docker.volume(name, labels)
        require(before is not None, 'REGISTRY_TLS_CONTROL_VOLUME_NOT_CREATED')
        docker.helper(helper, 'database', control_script(True), initialize=True); created = 1
    expected = ['REGISTRY_TLS_CONTROL_OK', *[pki.sha(wanted['database/' + n]) + '  ' + n for n in CONTROL]]
    raw = docker.helper(helper, 'database', control_script(), own_only=True)
    require(raw == ('\n'.join(expected) + '\n').encode(), 'REGISTRY_TLS_CONTROL_UID_RO_BYTES_NOT_VERIFIED')
    for role in ('runtime', 'maintenance'):
        uid = supply.ROLES[role][0]
        script = (f'test "$(id -u):$(id -g)" = {uid}:{uid}\n'
                  'if ls /supply/database >/dev/null 2>&1; then exit 43; fi\n'
                  f'printf \'REGISTRY_TLS_CONTROL_DENIED:{uid}\\n\'\n')
        require(docker.helper(helper, role, script) == f'REGISTRY_TLS_CONTROL_DENIED:{uid}\n'.encode(),
                'REGISTRY_TLS_CONTROL_CROSS_UID_ACCESS_NOT_DENIED')
    require(docker.volume(name, labels) == before, 'REGISTRY_TLS_CONTROL_VOLUME_CHANGED')
    return True, created


def validate_compose(docker, root, wanted):
    path = root.joinpath(*DIRECTORY, PREPARED)
    resolved = json.loads(docker.run(['compose', '--project-name', docker.project,
        '--project-directory', str(root), '--env-file', str(root / '.env'), '-f', str(path / 'compose.root.json'),
        '--profile', 'camera-tools', 'config', '--format', 'json']))
    expected = json.loads(wanted['compose.camera.json'])
    require(set(resolved['services']) == {'camera-api', 'camera-db', 'camera-migrate',
        'model-api', 'analysis-api', 'operation-api'}, 'REGISTRY_TLS_COMPOSE_RECIPE_INVALID')
    for name, desired in expected['services'].items():
        actual = resolved['services'][name]
        for key in ('image', 'user', 'command', 'entrypoint', 'read_only', 'cap_drop', 'security_opt'):
            if key in desired:
                require(actual.get(key) == desired[key],
                        'REGISTRY_TLS_COMPOSE_SERVICE_CHANGED')
        require(actual['image'] == desired['image'] and not actual.get('build')
                and actual.get('environment', {}).get('CAMERA_DATABASE_URL_FILE') ==
                    desired.get('environment', {}).get('CAMERA_DATABASE_URL_FILE'),
                'REGISTRY_TLS_COMPOSE_IMAGE_OR_DSN_CHANGED')
        # Compose normalizes volume/secret/network defaults. Check selected semantic fields.
        mounts = {m['target']: m for m in actual.get('volumes', [])}
        require(len(mounts) == len(actual.get('volumes', []))
                and set(mounts) == {m['target'] for m in desired.get('volumes', [])}, 'REGISTRY_TLS_COMPOSE_MOUNTS_CHANGED')
        for mount in desired.get('volumes', []):
            row = mounts[mount['target']]
            require(row['type'] == 'volume' and row['source'] == mount['source']
                    and row.get('read_only', False) is mount.get('read_only', False)
                    and row.get('volume', {}).get('nocopy') is True, 'REGISTRY_TLS_COMPOSE_MOUNTS_CHANGED')
        require(set(actual['networks']) == set(desired['networks']), 'REGISTRY_TLS_COMPOSE_NETWORKS_CHANGED')
        for key, attachment in desired['networks'].items():
            for field, value in attachment.items():
                require(actual['networks'][key].get(field) == value, 'REGISTRY_TLS_COMPOSE_NETWORKS_CHANGED')
        secret_mounts = actual.get('secrets', [])
        require(len(secret_mounts) == len(desired.get('secrets', []))
                and {s['source'] for s in secret_mounts} == set(desired.get('secrets', []))
                and all(s.get('target', s['source']) == s['source'] for s in secret_mounts),
                'REGISTRY_TLS_COMPOSE_SECRETS_CHANGED')
    api = resolved['services']['camera-api']
    port = api.get('ports', [])
    require(len(port) == 1 and all(port[0].get(k) == v for k, v in expected['services']['camera-api']['ports'][0].items()),
            'REGISTRY_TLS_COMPOSE_HTTP_CHANGED')
    require(not resolved['services']['camera-db'].get('ports') and not resolved['services']['camera-migrate'].get('ports'),
            'REGISTRY_TLS_COMPOSE_DATABASE_PUBLISHED')
    for section in ('networks', 'volumes'):
        for name, value in expected[section].items():
            require(resolved[section][name].get('external', False) is value.get('external', False)
                    and resolved[section][name].get('name') == value['name'], 'REGISTRY_TLS_COMPOSE_EXTERNAL_RESOURCE_CHANGED')
    for name, value in expected['secrets'].items():
        require(resolved['secrets'][name].get('file') == value['file'], 'REGISTRY_TLS_COMPOSE_SECRET_PATH_CHANGED')
    current = json.loads(docker.compose(['config', '--format', 'json'], active=False))
    for name in ('model-api', 'analysis-api', 'operation-api'):
        require(resolved['services'][name] == current['services'][name], 'REGISTRY_TLS_OTHER_PLATFORM_CONFIG_CHANGED')


def prepare(root, apply=False, docker_factory=supply.SupplyDocker):
    root = Path(root).absolute(); stage = 'accepted_source'
    try:
        revision, manifest = checked_source(root)
        stage = 'coordination_lock'
        with activation.activation_lock(root):
            stage = 'docker_preflight'
            docker = docker_factory(root); daemon = docker.preflight()
            stage = 'environment_binding'
            env = environment(root)
            validate_current_environment(env, manifest)
            stage = 'current_production'; current = current_binding(root, docker, manifest)
            stage = 'accepted_supply'
            tls_receipt, tls_files = accepted_supply(root, manifest, docker, current['network'], current['database_image'])
            stage = 'registry_secrets'; values = activation.prepare_secrets(root, True)
            receipt, wanted = bundle(root, docker.project, revision, current, tls_receipt, values, pki.sha(env))
            stage = 'preparation_files'; files_ready, files_created = prepare_files(root, wanted, apply)
            ready, count = False, 0
            if files_ready:
                stage = 'compose_validation'; validate_compose(docker, root, wanted)
                stage = 'control_volume'; ready, count = prepare_control(docker, root, receipt, wanted, apply)
            stage = 'final_recheck'
            require(checked_source(root)[0] == revision and environment(root) == env
                    and docker.preflight() == daemon and current_binding(root, docker, manifest) == current,
                    'REGISTRY_TLS_SOURCE_OR_PRODUCTION_CHANGED')
            require(activation.prepare_secrets(root, True) == values, 'REGISTRY_TLS_REGISTRY_SECRETS_CHANGED')
            require(accepted_supply(root, manifest, docker, current['network'], current['database_image']) ==
                    (tls_receipt, tls_files), 'REGISTRY_TLS_ACCEPTED_SUPPLY_CHANGED')
            if files_ready: prepare_files(root, wanted, False)
            return {'status': ('prepared' if files_created or count else 'already_prepared') if ready else 'planned',
                'scope': SCOPE, 'checked_revision': revision, 'accepted_rehearsal_revision': ACCEPTED,
                'registry_schema_version': 7, 'preparation_directory': str(root.joinpath(*DIRECTORY, PREPARED)),
                'preparation_sha256': receipt['preparation_sha256'], 'preparation_files_ready': files_ready,
                'control_volume_ready': ready, 'control_volumes_created': count,
                'control_volume_name': receipt['control_volume_name'], 'cutover_preparation_ready': ready,
                'accepted_tls_supply_rechecked': True, 'accepted_tls_supply_modified': False,
                'offline_tls_supply_full_probes_passed': 6, 'offline_tls_supply_precheck_probes_passed': 6,
                'offline_tls_cross_uid_denials_passed': 12,
                'offline_control_probes_passed': 1 if ready else 0, 'offline_control_cross_uid_denials_passed': 2 if ready else 0,
                'offline_probe_helpers_removed': True, 'current_registry_identity_and_http_verified': True,
                'registry_connection_files_read': True, 'tls_supply_private_keys_read_for_validation': True,
                'production_candidate_files_read': True, 'production_prepared_supply_files_read': True,
                'ca_signing_key_read': False, 'prepared_tls_connection_files_ready': files_ready,
                'prepared_connection_files_activated': False, 'compose_recipe_validated': files_ready,
                'recipe_is_deployable': False, 'registry_tls_activation_tool_implemented': False,
                'next_step': 'prepare_schema7_registry_tls_activation_tool', **NO_CHANGES}
    except BaseException as exc:
        exc.inspection_stage = stage; raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--apply', action='store_true'); args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.project_root, args.apply), ensure_ascii=False)); return 0
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc) if isinstance(exc, (PreparationError, supply.SupplyError, pki.CandidateError,
                                           activation.ActivationError)) else 'REGISTRY_TLS_PREPARATION_FAILED'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code): code = 'REGISTRY_TLS_PREPARATION_FAILED'
        stage = getattr(exc, 'inspection_stage', 'accepted_source')
        if stage not in STAGES: stage = 'accepted_source'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': code, 'failed_stage': stage,
            'cutover_preparation_ready': False, 'control_volume_ready': False, **NO_CHANGES}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
