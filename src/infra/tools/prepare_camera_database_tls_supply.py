#!/usr/bin/env python3
"""Prepare separated TLS supply volumes and a fixed-address recipe; never activate DB/API."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sys

import prepare_camera_database_tls_candidate as candidate
import test_camera_database_tls_boundary as boundary
import inspect_camera_credential_identity as identity
import inspect_camera_credential_supply_facts as facts
from camera_activation import ActivationError, Docker, activation_lock

SCOPE = 'camera_database_tls_supply_preparation'
DIRECTORY = ('var', 'camera', 'database-tls-supply')
SUPPLY = 'supply-v1'
ACCEPTED = 'f18af0cf9a0580c05609ff7a0585fb023e781220318bb18b4957ed368a4dd103'
LABEL = 'io.vms.camera.tls-supply'
ROLES = {
    'database': (999, ('ca.pem', 'server.pem', 'server.key')),
    'runtime': (65532, ('ca.pem',)),
    'maintenance': (10002, ('ca.pem', 'maintenance.pem', 'maintenance.key')),
}
NO_CHANGES = {**boundary.NO_CHANGES, 'credential_key_material_read': False,
              'host_permissions_modified': False, 'current_compose_modified': False,
              'approved_binding_created': False}
STAGES = ('accepted_source', 'current_identity', 'current_network', 'accepted_candidate',
          'supply_files', 'compose_validation', 'supply_volumes', 'native_mount_probes',
          'source_and_production_recheck', 'helper_cleanup')


class SupplyError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise SupplyError(code)


def checked_source(root):
    revision = boundary.checked_revision(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_database_tls_boundary_server_verified') is True
            and value.get('validated_credential_database_tls_boundary_project_sha256') == ACCEPTED
            and value.get('credential_database_tls_supply_preparation_implemented') is True,
            'ACCEPTED_DATABASE_TLS_BOUNDARY_REQUIRED')
    return revision, value


def opened_directory(root, create=False):
    root = Path(root).absolute()
    require(root.is_absolute() and '..' not in root.parts and ',' not in str(root),
            'TLS_SUPPLY_PROJECT_PATH_INVALID')
    fd = os.open('/', candidate.DIR_FLAGS)
    try:
        for name in root.parts[1:]:
            child = os.open(name, candidate.DIR_FLAGS, dir_fd=fd)
            os.close(fd); fd = child
        candidate.owned(os.fstat(fd))
        for index, name in enumerate(DIRECTORY):
            if create:
                try: os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(name, candidate.DIR_FLAGS, dir_fd=fd)
            os.close(fd); fd = child
            candidate.owned(os.fstat(fd), 0o700 if index == 2 else None)
        return fd, root.joinpath(*DIRECTORY)
    except BaseException:
        os.close(fd)
        raise


def read_candidate(root, manifest):
    fd, _ = candidate.directory(root, False)
    try:
        leaf = os.open(candidate.CANDIDATE, candidate.DIR_FLAGS, dir_fd=fd)
        try:
            snapshot = candidate.inspect(leaf)
            expected = manifest['credential_tls_candidate_latest_server_candidate_sha256']
            require(candidate.sha(snapshot['candidate.json']) == expected,
                    'ACCEPTED_TLS_CANDIDATE_MISMATCH')
            proof = candidate.probe(leaf, snapshot)
            for field in ('server_certificate_sha256', 'maintenance_certificate_sha256', 'ca_pem_sha256'):
                require(proof[field] == manifest['credential_tls_candidate_latest_server_' + field],
                        'ACCEPTED_TLS_CERTIFICATE_MISMATCH')
            return snapshot, proof
        finally: os.close(leaf)
    finally: os.close(fd)


def network_recipe(raw, project, containers, proposal):
    entries = json.loads(raw)
    require(isinstance(entries, list) and len(entries) == 1, 'TLS_SUPPLY_NETWORK_INVALID')
    value = entries[0]
    require(value.get('Name') == project + '_camera-storage'
            and re.fullmatch('[0-9a-f]{64}', value.get('Id', ''))
            and value.get('Internal') is True and value.get('Driver') == 'bridge'
            and value.get('Scope') == 'local' and value.get('EnableIPv6') is False
            and value.get('Labels', {}).get('com.docker.compose.project') == project
            and value.get('Labels', {}).get('com.docker.compose.network') == 'camera-storage',
            'TLS_SUPPLY_OWNED_IPV4_NETWORK_REQUIRED')
    configs = value.get('IPAM', {}).get('Config')
    require(isinstance(configs, list) and len(configs) == 1, 'TLS_SUPPLY_SINGLE_SUBNET_REQUIRED')
    config = configs[0]
    net = ipaddress.IPv4Network(config['Subnet'], strict=True)
    gateway = ipaddress.IPv4Address(config['Gateway'])
    require(net.is_private and gateway in net, 'TLS_SUPPLY_SUBNET_INVALID')
    addresses = {role: ipaddress.IPv4Address(proposal[field]) for role, field in (
        ('database', 'database_ip'), ('runtime', 'runtime_source_ip'),
        ('maintenance', 'maintenance_source_ip'))}
    require(len(set(addresses.values())) == 3
            and all(ip in net and ip not in (net.network_address, net.broadcast_address, gateway)
                    for ip in addresses.values()), 'TLS_SUPPLY_PROPOSAL_OUTSIDE_CURRENT_SUBNET')
    peers = value.get('Containers')
    require(isinstance(peers, dict)
            and set(peers) == {containers['camera-db']['Id'], containers['camera-api']['Id']},
            'TLS_SUPPLY_OTHER_NETWORK_PEERS_REJECTED')
    for role, service in (('database', 'camera-db'), ('runtime', 'camera-api')):
        obj = containers[service]
        attachment = obj['NetworkSettings']['Networks'][value['Name']]
        require(attachment['NetworkID'] == value['Id']
                and attachment['IPAddress'] == str(addresses[role])
                and attachment['IPPrefixLen'] == net.prefixlen
                and not attachment.get('GlobalIPv6Address')
                and peers[obj['Id']]['IPv4Address'] == str(addresses[role]) + '/' + str(net.prefixlen)
                and not peers[obj['Id']].get('IPv6Address'), 'TLS_SUPPLY_CURRENT_ADDRESS_MISMATCH')
    reserved = config.get('AuxiliaryAddresses', {})
    require(isinstance(reserved, dict) and str(addresses['maintenance']) not in reserved.values(),
            'TLS_SUPPLY_MAINTENANCE_ADDRESS_RESERVED')
    return {'network_name': value['Name'], 'network_id': value['Id'], 'subnet': str(net),
            'gateway': str(gateway), 'internal': True, 'database_ip': str(addresses['database']),
            'runtime_source_ip': str(addresses['runtime']),
            'maintenance_source_ip': str(addresses['maintenance']),
            'current_database_and_runtime_addresses_verified': True,
            'maintenance_address_currently_unattached': True,
            'address_state': 'observed-recipe-unreserved', 'address_reservation_verified': False}


def compose_recipe(project, image, network, volumes):
    # Config-only recipe. No application image, PGDATA, DSN, HBA or API token.
    # All services exit immediately and are opt-in; this is not a deployment file.
    services = {}
    for role, (uid, _) in ROLES.items():
        address = network[{'database': 'database_ip', 'runtime': 'runtime_source_ip',
                           'maintenance': 'maintenance_source_ip'}[role]]
        services['tls-' + role + '-recipe'] = {
            'image': image, 'user': f'{uid}:{uid}', 'entrypoint': ['/bin/true'],
            'profiles': ['tls-supply-recipe-only'], 'read_only': True,
            'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'], 'restart': 'no',
            'labels': {'io.vms.intent': 'configuration-only-not-a-deployment'},
            'volumes': [{'type': 'volume', 'source': role, 'target': '/run/camera-tls',
                         'read_only': True, 'volume': {'nocopy': True}}],
            'networks': {'camera-storage': {'ipv4_address': address,
                **({'aliases': [candidate.SERVER_NAME]} if role == 'database' else {})}},
        }
    return {'name': project + '-tls-recipe', 'services': services,
            'volumes': {r: {'external': True, 'name': v} for r, v in volumes.items()},
            'networks': {'camera-storage': {'external': True, 'name': network['network_name']}}}


def bundle(root, project, image, network, snapshot, proof):
    receipt = {'format_version': 1, 'kind': 'camera-database-tls-supply', 'intent': 'supply-only',
        'accepted_boundary_revision': ACCEPTED, 'candidate_sha256': candidate.sha(snapshot['candidate.json']),
        'server_name': candidate.SERVER_NAME, 'maintenance_common_name': candidate.CLIENT_NAME,
        'minimum_tls_version': 'TLS1.2', 'database': 'vms_camera', 'port': 5432,
        'probe_image': image, 'network_recipe': network,
        'source_directory': str(root.joinpath(*candidate.DIRECTORY, candidate.CANDIDATE)),
        'supply_directory': str(root.joinpath(*DIRECTORY, SUPPLY)),
        'public_certificates': {k: proof[k] for k in ('server_certificate_sha256',
                                   'maintenance_certificate_sha256', 'ca_pem_sha256')},
        'owners': {r: {'uid': u, 'gid': u, 'directory_mode': '0700', 'file_mode': '0400',
                       'files': list(names)} for r, (u, names) in ROLES.items()},
        'activation_allowed': False, 'production_supply_ready': False,
        'production_runtime_mount_verified': False, 'database_tls_activated': False}
    digest = candidate.sha(candidate.encoded(receipt))
    volumes = {role: project + '-camera-tls-' + role + '-' + digest[:16] for role in ROLES}
    receipt['supply_sha256'] = digest
    receipt['volume_names'] = volumes
    body = {'receipt.json': candidate.encoded(receipt),
            'compose.recipe.json': candidate.encoded(compose_recipe(project, image, network, volumes))}
    for role, (_, names) in ROLES.items():
        for name in names: body[role + '/' + name] = snapshot[name]
    require(not any(name.endswith('/ca.key') for name in body), 'TLS_CA_SIGNING_KEY_EXPORT_REJECTED')
    return receipt, body


def inspect_bundle(fd, wanted):
    candidate.owned(os.fstat(fd), 0o700)
    require(set(os.listdir(fd)) == {'receipt.json', 'compose.recipe.json', *ROLES},
            'TLS_SUPPLY_BUNDLE_INCOMPLETE_OR_UNKNOWN')
    actual = {name: candidate.read_file(fd, name) for name in ('receipt.json', 'compose.recipe.json')}
    for role, (_, names) in ROLES.items():
        child = os.open(role, candidate.DIR_FLAGS, dir_fd=fd)
        try:
            candidate.owned(os.fstat(child), 0o700)
            require(set(os.listdir(child)) == set(names), 'TLS_SUPPLY_SELECTED_FILES_INVALID')
            actual.update({role + '/' + name: candidate.read_file(child, name) for name in names})
        finally: os.close(child)
    require(actual == wanted, 'TLS_SUPPLY_BUNDLE_CHANGED_OR_WRONG_BINDING')


def prepare_bundle(root, wanted, apply=False):
    try: fd, path = opened_directory(root, apply)
    except FileNotFoundError:
        require(not apply, 'TLS_SUPPLY_DIRECTORY_MISSING')
        return False
    try:
        created = False
        try: leaf = os.open(SUPPLY, candidate.DIR_FLAGS, dir_fd=fd)
        except FileNotFoundError:
            if not apply: return False
            os.mkdir(SUPPLY, 0o700, dir_fd=fd); os.fsync(fd)
            leaf = os.open(SUPPLY, candidate.DIR_FLAGS, dir_fd=fd); created = True
        try:
            if created:
                for role, (_, names) in ROLES.items():
                    os.mkdir(role, 0o700, dir_fd=leaf)
                    child = os.open(role, candidate.DIR_FLAGS, dir_fd=leaf)
                    try:
                        for name in names: candidate.write_new(child, name, wanted[role + '/' + name])
                    finally: os.close(child)
                for name in ('compose.recipe.json', 'receipt.json'): candidate.write_new(leaf, name, wanted[name])
            inspect_bundle(leaf, wanted)
            current, _ = opened_directory(root, False)
            try:
                check = os.open(SUPPLY, candidate.DIR_FLAGS, dir_fd=current)
                try:
                    a, b = os.fstat(leaf), os.fstat(check)
                    require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), 'TLS_SUPPLY_DIRECTORY_CHANGED')
                    inspect_bundle(check, wanted)
                finally: os.close(check)
            finally: os.close(current)
        finally: os.close(leaf)
        return created
    finally: os.close(fd)


class SupplyDocker(Docker):
    def run(self, args, **kwargs):
        try: return super().run(args, **kwargs)
        except ActivationError: raise SupplyError('TLS_SUPPLY_DOCKER_COMMAND_FAILED') from None

    def volume(self, name, labels):
        names = [v for v in self.run(['volume', 'ls', '--format', '{{.Name}}',
                                     '--filter', 'name=' + name]).decode().split() if v == name]
        require(names in ([], [name]), 'TLS_SUPPLY_VOLUME_NAME_AMBIGUOUS')
        if not names: return None
        entries = json.loads(self.run(['volume', 'inspect', name]))
        require(len(entries) == 1, 'TLS_SUPPLY_VOLUME_INVALID')
        value = entries[0]
        require(value['Name'] == name and value.get('Driver') == 'local'
                and not value.get('Options') and value.get('Labels') == labels
                and value.get('Scope') == 'local', 'TLS_SUPPLY_VOLUME_OWNERSHIP_MISMATCH')
        return value

    def helper(self, receipt, role, script, *, initialize=False, own_only=False):
        name = self.project + '-tls-supply-' + secrets.token_hex(6)
        labels = {LABEL: receipt['supply_sha256'], LABEL + '.project': self.project,
                  LABEL + '.helper': 'offline-supply-only'}
        args = ['run', '--rm', '--name', name, '--pull', 'never', '--network', 'none',
                '--read-only', '--user', '0:0' if initialize else str(ROLES[role][0]) + ':' + str(ROLES[role][0]),
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--env', 'LANG=C',
                '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev,size=16m,mode=0700']
        for key, value in labels.items(): args += ['--label', key + '=' + value]
        if initialize:
            args += ['--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE',
                '--mount', 'type=bind,source=' + receipt['supply_directory'] + '/' + role + ',target=/input,readonly',
                '--mount', 'type=volume,source=' + receipt['volume_names'][role] + ',target=/output,volume-nocopy']
        else:
            for owner, volume in receipt['volume_names'].items():
                if own_only and owner != role: continue
                args += ['--mount', 'type=volume,source=' + volume + ',target=/supply/' + owner + ',readonly,volume-nocopy']
        args += ['--entrypoint', '/bin/sh', receipt['probe_image'], '-ec', script]
        try: return self.run(args, timeout=60)
        finally:
            ids = self.run(['ps', '-aq', '--filter', 'name=^/' + name + '$']).decode().split()
            require(len(ids) <= 1, 'TLS_SUPPLY_HELPER_IDENTITY_INVALID')
            if ids:
                objects = json.loads(self.run(['inspect', ids[0]]))
                require(len(objects) == 1 and objects[0]['Name'] == '/' + name
                        and all(objects[0]['Config'].get('Labels', {}).get(k) == v for k, v in labels.items()),
                        'TLS_SUPPLY_HELPER_OWNERSHIP_MISMATCH')
                self.run(['rm', '-f', '-v', ids[0]])


def initializer(role):
    uid, names = ROLES[role]
    # Empty-only, noclobber, no repair. A partial existing volume is never initialized again.
    return ('set -C\numask 077\ntest -z "$(find /output -mindepth 1 -maxdepth 1 -print -quit)"\n'
            + 'chmod 0700 /output\n'
            + ''.join('cat /input/' + name + ' > /output/' + name + '\n' for name in names)
            + 'chmod 0400 ' + ' '.join('/output/' + n for n in names) + '\n'
            + f'chown {uid}:{uid} /output ' + ' '.join('/output/' + n for n in names)
            + '\nsync /output\n')


def probe_script(role, cross_uid=True):
    uid, names = ROLES[role]
    script = f'test "$(id -u)" = {uid}\ntest "$(id -g)" = {uid}\n'
    script += 'for map in /proc/self/uid_map /proc/self/gid_map; do\n'
    script += '  test "$(awk \'{print $1, $2, $3}\' "$map")" = "0 0 4294967295"\ndone\n'
    script += 'cd /supply/' + role + '\n'
    script += f'test "$(stat -c \'%u:%g:%a\' .)" = "{uid}:{uid}:700"\n'
    script += 'test "$(find . -mindepth 1 -maxdepth 1 -printf \'%f\\n\' | sort)" = "' + '\n'.join(sorted(names)) + '"\n'
    for name in names:
        script += f'test -f {name} && test ! -L {name}\n'
        script += f'test "$(stat -c \'%u:%g:%a:%h\' {name})" = "{uid}:{uid}:400:1"\n'
    script += 'if error=$(touch .write-probe 2>&1); then exit 41; fi\n'
    script += 'case "$error" in *"Read-only file system"*) ;; *) exit 42 ;; esac\n'
    for other in ROLES:
        if other == role or not cross_uid: continue
        script += 'if ls /supply/' + other + ' >/dev/null 2>&1; then exit 43; fi\n'
    script += 'printf \'TLS_SUPPLY_OK:' + role + '\\n\'\n'
    script += 'sha256sum ' + ' '.join(sorted(names)) + '\n'
    return script


def verify_probe(raw, role, snapshot):
    require(isinstance(raw, bytes) and len(raw) < 4096, 'TLS_SUPPLY_PROBE_OUTPUT_INVALID')
    uid, names = ROLES[role]
    lines = raw.decode('ascii').splitlines()
    expected = ['TLS_SUPPLY_OK:' + role]
    expected += [candidate.sha(snapshot[name]) + '  ' + name for name in sorted(names)]
    require(lines == expected, 'TLS_SUPPLY_UID_RO_OR_EXACT_BYTES_NOT_VERIFIED')


def prepare_volumes(docker, receipt, snapshot, apply):
    created = 0
    existing = {}
    for role, name in receipt['volume_names'].items():
        labels = {LABEL: receipt['supply_sha256'], LABEL + '.project': docker.project, LABEL + '.role': role}
        existing[role] = docker.volume(name, labels)
        if existing[role] is not None:
            verify_probe(docker.helper(receipt, role, probe_script(role, False), own_only=True), role, snapshot)
            require(docker.volume(name, labels) == existing[role], 'TLS_SUPPLY_VOLUME_CHANGED')
    for role, name in receipt['volume_names'].items():
        labels = {LABEL: receipt['supply_sha256'], LABEL + '.project': docker.project, LABEL + '.role': role}
        before = existing[role]
        if before is None:
            if not apply: return False, 0
            args = ['volume', 'create', '--driver', 'local']
            for key, value in labels.items(): args += ['--label', key + '=' + value]
            docker.run([*args, name])
            require(docker.volume(name, labels) is not None, 'TLS_SUPPLY_CREATED_VOLUME_NOT_VERIFIED')
            docker.helper(receipt, role, initializer(role), initialize=True)
            created += 1
    # All three volumes must exist before probes; no implicit Docker auto-created volume is accepted.
    before_all = {}
    for role, name in receipt['volume_names'].items():
        labels = {LABEL: receipt['supply_sha256'], LABEL + '.project': docker.project, LABEL + '.role': role}
        before_all[role] = docker.volume(name, labels)
        require(before_all[role] is not None, 'TLS_SUPPLY_VOLUME_DISAPPEARED')
    for role in ROLES: verify_probe(docker.helper(receipt, role, probe_script(role)), role, snapshot)
    for role, name in receipt['volume_names'].items():
        labels = {LABEL: receipt['supply_sha256'], LABEL + '.project': docker.project, LABEL + '.role': role}
        require(docker.volume(name, labels) == before_all[role], 'TLS_SUPPLY_VOLUME_CHANGED')
    return True, created


def observe(root, docker):
    value = identity.inspect_identity(root, facts.FactsDocker(root))
    require(value['identity_readiness'] == 'verified' and value['verified_process_count'] == 2
            and value['running_api_version'] == '0.7.0-device-delete' and value['schema_version'] == 7,
            'TLS_SUPPLY_CURRENT_SCHEMA_7_IDENTITY_REQUIRED')
    inventory = facts.inspect_facts(root, facts.FactsDocker(root))['inventory']
    require(inventory['database']['tls_enabled'] is False
            and inventory['database']['schema_version'] == 7
            and inventory['running_api_version'] == '0.7.0-device-delete',
            'TLS_SUPPLY_CURRENT_TLS_OFF_REQUIRED')
    for service, uid in (('camera-api', 65532), ('camera-db', 999)):
        row = value['processes'][service]
        require(row['effective_uid'] == row['filesystem_uid'] == uid
                and row['effective_gid'] == row['filesystem_gid'] == uid,
                'TLS_SUPPLY_CURRENT_UID_MISMATCH')
    before = docker.snapshot()
    require({'camera-db', 'camera-api'} <= before.keys(), 'TLS_SUPPLY_RUNNING_CAMERA_REQUIRED')
    objects = json.loads(docker.run(['inspect', before['camera-db']['id'], before['camera-api']['id']]))
    containers = {x['Config']['Labels']['com.docker.compose.service']: x for x in objects}
    require(set(containers) == {'camera-db', 'camera-api'}, 'TLS_SUPPLY_CONTAINER_IDENTITY_INVALID')
    for service, obj in containers.items():
        require(obj['Id'] == before[service]['id'] and obj['Image'] == before[service]['image']
                and obj['State']['Running'] is True, 'TLS_SUPPLY_CONTAINER_CHANGED')
    image = containers['camera-db']['Image']
    require(re.fullmatch('sha256:[0-9a-f]{64}', image) is not None, 'TLS_SUPPLY_IMAGE_ID_INVALID')
    network = docker.run(['network', 'inspect', docker.project + '_camera-storage'])
    return before, containers, image, network


def prepare(root, apply=False, docker_factory=SupplyDocker):
    root = Path(root).absolute()
    stage = 'accepted_source'
    try:
        revision, manifest = checked_source(root)
        with activation_lock(root):
            docker = docker_factory(root); daemon = docker.preflight()
            stage = 'current_identity'
            before, containers, image, raw_network = observe(root, docker)
            stage = 'accepted_candidate'
            snapshot, proof = read_candidate(root, manifest)
            proposal = json.loads(snapshot['candidate.json'])['endpoint_proposal']
            stage = 'current_network'
            network = network_recipe(raw_network, docker.project, containers, proposal)
            receipt, wanted = bundle(root, docker.project, image, network, snapshot, proof)
            stage = 'supply_files'
            created_files = prepare_bundle(root, wanted, apply)
            supply_path = root.joinpath(*DIRECTORY, SUPPLY)
            prepared = supply_path.exists()
            volumes_ready, volume_count = False, 0
            if prepared:
                stage = 'compose_validation'
                resolved = json.loads(docker.run(['compose', '--project-directory', str(supply_path),
                    '--env-file', '/dev/null', '-f', str(supply_path / 'compose.recipe.json'),
                    '--profile', 'tls-supply-recipe-only', 'config', '--format', 'json']))
                require(set(resolved['services']) == {'tls-' + r + '-recipe' for r in ROLES}
                        and not resolved.get('secrets'), 'TLS_SUPPLY_COMPOSE_RECIPE_INVALID')
                for role in ROLES:
                    service = resolved['services']['tls-' + role + '-recipe']
                    require(service['entrypoint'] == ['/bin/true']
                            and service['volumes'][0]['read_only'] is True
                            and service['volumes'][0].get('volume', {}).get('nocopy') is True,
                            'TLS_SUPPLY_COMPOSE_MOUNT_INVALID')
                stage = 'supply_volumes'
                volumes_ready, volume_count = prepare_volumes(docker, receipt, snapshot, apply)
            stage = 'source_and_production_recheck'
            require(checked_source(root)[0] == revision and docker.preflight() == daemon
                    and docker.snapshot() == before, 'TLS_SUPPLY_PRODUCTION_OR_SOURCE_CHANGED')
            require(observe(root, docker)[0] == before, 'TLS_SUPPLY_CURRENT_IDENTITY_OR_SCHEMA_CHANGED')
            require(json.loads(docker.run(['network', 'inspect', docker.project + '_camera-storage'])) ==
                    json.loads(raw_network), 'TLS_SUPPLY_NETWORK_CHANGED')
            require(read_candidate(root, manifest)[0] == snapshot, 'TLS_SUPPLY_CANDIDATE_CHANGED')
            if prepared: prepare_bundle(root, wanted, False)
            return {'status': ('prepared' if created_files or volume_count else 'already_prepared')
                    if prepared and volumes_ready else 'planned', 'scope': SCOPE,
                'checked_revision': revision, 'candidate_sha256': receipt['candidate_sha256'],
                'supply_sha256': receipt['supply_sha256'], 'supply_directory': str(supply_path),
                'tls_supply_files_prepared': prepared, 'tls_supply_volumes_ready': volumes_ready,
                'tls_supply_volumes_created': volume_count, 'tls_supply_volume_names': receipt['volume_names'],
                'prepared_separate_uid_and_ro_mounts_verified': volumes_ready,
                'prepared_exact_candidate_bytes_verified': volumes_ready,
                'cross_uid_access_rejected': volumes_ready,
                'native_supply_probes_passed': 3 if volumes_ready else 0,
                'native_cross_uid_denials_passed': 6 if volumes_ready else 0,
                'offline_probe_helpers_removed': prepared and volumes_ready,
                'current_process_identity_verified': True, 'fixed_address_recipe': network,
                'ca_signing_key_exported': False, 'tls_candidate_private_keys_read': True,
                'source_candidate_unchanged': True, 'current_services_unchanged': True,
                'compose_recipe_validated': prepared, 'recipe_is_deployable': False,
                'actual_socketpair_mtls_verified': proof['actual_socketpair_mtls_verified'],
                'next_step': 'isolated_schema_7_tls_cutover_check', **NO_CHANGES}
    except BaseException as exc:
        exc.inspection_stage = stage
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = prepare(args.project_root, args.apply)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc) if isinstance(exc, (SupplyError, candidate.CandidateError)) else 'TLS_SUPPLY_PREPARATION_FAILED'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code): code = 'TLS_SUPPLY_PREPARATION_FAILED'
        stage = getattr(exc, 'inspection_stage', 'accepted_source')
        if stage not in STAGES: stage = 'accepted_source'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': code, 'failed_stage': stage,
            'activation_allowed': False, 'production_supply_ready': False,
            'tls_supply_volumes_ready': False, **NO_CHANGES}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
