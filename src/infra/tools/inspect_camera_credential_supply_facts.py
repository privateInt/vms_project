#!/usr/bin/env python3
"""Read planning facts from the accepted registry; never create an approved plan.

docker top reports daemon-host identities. Container UID mapping, future pinned
addresses, physical backup topology and protected supply bindings stay unverified.
Only the private report and the existing camera coordination lock are written.
"""
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.error import URLError

import inspect_camera_credential_supply as inventory
from camera_activation import ActivationError, Docker, activation_lock, atomic_write, safe, sha

SCOPE = 'camera_credential_production_supply_planning_facts'
REPORT = 'var/camera/credential-supply-facts.json'
ACCEPTED_CONTRACT = '8ab00aec97ebbc80d90f4536a9c2ad94304ac5d535c312ed0bffb6819e34b85f'
SECURITY_ARGS = ['info', '--format', '{{json .SecurityOptions}}']
require = inventory.require
NO_CHANGES = {**inventory.NO_CHANGES, 'supply_plan_created': False,
              'approved_binding_created': False, 'network_modified': False}
UNRESOLVED = [
    'CONTAINER_UID_MAPPING_AND_EXECUTION_IDENTITIES',
    'MAINTENANCE_UID_AND_AUTHORITY_RUNTIME_GROUP',
    'PINNED_ENDPOINT_AND_DISTINCT_RUNTIME_MAINTENANCE_SOURCES',
    'TLS_CA_SERVER_AND_MAINTENANCE_CERTIFICATE_SUPPLY',
    'PROTECTED_ROLE_DSN_FILE_SUPPLY',
    'SOURCE_KEY_INTEGRITY_AND_SEPARATE_RUNTIME_COPY',
    'AUTHORITY_AND_STABLE_LOCK_RECEIPT_LOCATIONS',
    'EXTERNAL_HBA_AND_DATABASE_CONTROL_FILE_LOCATIONS',
    'DECLARED_SNAPSHOT_ROOTS_AND_PHYSICAL_BACKUP_TOPOLOGY',
]
STAGES = ('accepted_source', 'host_key_metadata', 'accepted_registry_inventory',
    'container_metadata', 'process_identity_observation', 'daemon_security_metadata',
    'database_volume_and_network_attachments', 'owned_storage_network',
    'observation_recheck', 'input_and_container_recheck')


def checked_source(root):
    revision = inventory.checked_manifest(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    require(manifest.get('credential_production_supply_plan_contract_implemented') is True
        and manifest.get('credential_production_supply_plan_contract_server_verified') is True
        and manifest.get('validated_credential_production_supply_plan_contract_project_sha256') == ACCEPTED_CONTRACT
        and manifest.get('credential_production_supply_facts_implemented') is True,
        'ACCEPTED_SUPPLY_CONTRACT_REQUIRED')
    require({'src/infra/tools/inspect_camera_credential_supply_facts.py',
        'src/platform/camera/api/planned/credential-supply.schema.json',
        'src/platform/camera/api/planned/credential_supply_contract.py'} <= manifest['files'].keys(),
        'SUPPLY_FACTS_SOURCE_MANIFEST_INCOMPLETE')
    return revision


class FactsDocker(inventory.InventoryDocker):
    """Extend the inventory allowlist with exact numeric top and owned-network reads."""
    def __init__(self, root):
        super().__init__(root)
        self.reviewed_container_ids = set()
        self.reviewed_network_id = None

    def run(self, args, **kwargs):
        extra_read = args == SECURITY_ARGS
        extra_read = extra_read or (len(args) == 4 and args[0] == 'top'
            and re.fullmatch('[0-9a-f]{64}', args[1])
            and args[1] in self.reviewed_container_ids and args[2:] == ['-eo', 'pid,euid,egid'])
        extra_read = extra_read or (self.reviewed_network_id is not None
            and re.fullmatch('[0-9a-f]{64}', self.reviewed_network_id)
            and args == ['network', 'inspect', self.reviewed_network_id])
        if not extra_read:
            return super().run(args, **kwargs)
        require(not (kwargs.keys()-{'input', 'stdout', 'timeout', 'extra'})
            and kwargs.get('input') is None and kwargs.get('stdout') is None
            and not kwargs.get('extra'), 'PRODUCTION_DOCKER_WRITE_REJECTED')
        try:
            return Docker.run(self, args, **kwargs)
        except ActivationError:
            raise ActivationError('READ_ONLY_DOCKER_COMMAND_UNAVAILABLE') from None


def process_identities(raw):
    require(isinstance(raw, bytes) and len(raw) <= 1048576, 'PROCESS_IDENTITY_OUTPUT_INVALID')
    rows = raw.decode('ascii').splitlines()
    require(2 <= len(rows) <= 4097 and rows[0].split() == ['PID', 'EUID', 'EGID'],
            'PROCESS_IDENTITY_OUTPUT_INVALID')
    identities, seen_pids = set(), set()
    for row in rows[1:]:
        fields = row.split()
        require(len(fields) == 3 and all(re.fullmatch('0|[1-9][0-9]{0,9}', x) for x in fields),
                'PROCESS_IDENTITY_OUTPUT_INVALID')
        numbers = tuple(map(int, fields))
        require(all(x < 4294967295 for x in numbers) and numbers[0] > 0
            and numbers[0] not in seen_pids, 'PROCESS_IDENTITY_OUTPUT_INVALID')
        seen_pids.add(numbers[0]); identities.add(numbers[1:])
    return {'identity_namespace': 'docker-daemon-host', 'process_count': len(rows)-1,
        'effective_identities': [{'uid': u, 'gid': g} for u, g in sorted(identities)],
        'pids_retained': False, 'container_uid_mapping_verified': False, 'actual_execution_uid_verified': False}


def daemon_security(raw):
    value = json.loads(raw)
    require(isinstance(value, list) and len(value) <= 32
        and all(isinstance(x, str) and len(x) <= 256 for x in value), 'DAEMON_SECURITY_OUTPUT_INVALID')
    names = {x.split(',', 1)[0] for x in value}
    return {'rootless_declared': 'name=rootless' in names,
        'userns_remap_declared': 'name=userns' in names,
        'local_host_path_verified': False, 'container_uid_mapping_verified': False}


def canonical_host_path(value):
    require(isinstance(value, str) and 1 < len(value) <= 4096
        and all(ord(c) >= 32 and ord(c) != 127 for c in value) and '\\' not in value,
        'DATABASE_VOLUME_HOST_PATH_INVALID')
    p = PurePosixPath(value)
    require(p.is_absolute() and not value.startswith('//') and p.as_posix() == value
        and '..' not in p.parts, 'DATABASE_VOLUME_HOST_PATH_INVALID')
    return value


def database_volume(db, project):
    matches = [m for m in db.get('Mounts', []) if m.get('Destination') == '/var/lib/postgresql/data']
    require(len(matches) == 1 and matches[0].get('Type') == 'volume'
        and matches[0].get('Name') == project+'_camera-data' and matches[0].get('RW') is True,
        'DATABASE_VOLUME_FACTS_MISMATCH')
    return {'volume_name': project+'_camera-data', 'container_data_directory': '/var/lib/postgresql/data',
        'daemon_declared_host_data_directory': canonical_host_path(matches[0].get('Source')),
        'host_path_contents_read': False, 'local_host_path_verified': False,
        'backup_topology_verified': False}


def address(value, version):
    require(isinstance(value, str), 'NETWORK_ADDRESS_INVALID')
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        raise ActivationError('NETWORK_ADDRESS_INVALID') from None
    require(ip.version == version and str(ip) == value and not ip.is_unspecified
        and not ip.is_multicast and not ip.is_loopback and '%' not in value, 'NETWORK_ADDRESS_INVALID')
    return ip


def attachment(value, project):
    name = project+'_camera-storage'
    networks = value.get('NetworkSettings', {}).get('Networks', {})
    require(isinstance(networks, dict) and isinstance(networks.get(name), dict),
            'OWNED_STORAGE_NETWORK_ATTACHMENT_REQUIRED')
    entry = networks[name]
    nid = entry.get('NetworkID')
    require(isinstance(nid, str) and re.fullmatch('[0-9a-f]{64}', nid), 'NETWORK_IDENTITY_INVALID')
    ips = {}
    for version, key, prefix in ((4, 'IPAddress', 'IPPrefixLen'), (6, 'GlobalIPv6Address', 'GlobalIPv6PrefixLen')):
        raw, bits = entry.get(key), entry.get(prefix)
        require(type(bits) is int and 0 <= bits <= (32 if version == 4 else 128), 'NETWORK_ADDRESS_INVALID')
        if raw == '':
            require(bits == 0, 'NETWORK_ADDRESS_INVALID')
            ips[str(version)] = None
        else:
            ips[str(version)] = str(address(raw, version))+'/'+str(bits)
    require(any(ips.values()), 'NETWORK_ADDRESS_REQUIRED')
    return {'network_id': nid, 'addresses': ips}


def network_facts(raw, project, container_ids, attachments):
    values = json.loads(raw)
    require(isinstance(values, list) and len(values) == 1 and isinstance(values[0], dict),
            'NETWORK_INSPECTION_INVALID')
    value = values[0]
    require(value.get('Id') == attachments['camera-api']['network_id'] == attachments['camera-db']['network_id']
        and value.get('Name') == project+'_camera-storage' and value.get('Scope') == 'local'
        and value.get('Driver') == 'bridge' and value.get('Internal') is True
        and value.get('Labels', {}).get('com.docker.compose.project') == project
        and value.get('Labels', {}).get('com.docker.compose.network') == 'camera-storage',
        'OWNED_INTERNAL_STORAGE_NETWORK_REQUIRED')
    configs = value.get('IPAM', {}).get('Config')
    require(isinstance(configs, list) and 1 <= len(configs) <= 16, 'NETWORK_SUBNET_INVALID')
    subnets, parsed = [], []
    for config in configs:
        require(isinstance(config, dict) and isinstance(config.get('Subnet'), str), 'NETWORK_SUBNET_INVALID')
        try:
            subnet = ipaddress.ip_network(config['Subnet'], strict=True)
        except ValueError:
            raise ActivationError('NETWORK_SUBNET_INVALID') from None
        require(str(subnet) == config['Subnet'], 'NETWORK_SUBNET_INVALID')
        gateway = config.get('Gateway', '')
        require(gateway == '' or address(gateway, subnet.version) in subnet, 'NETWORK_SUBNET_INVALID')
        parsed.append(subnet); subnets.append({'subnet': str(subnet), 'gateway': gateway or None})
    peers = value.get('Containers')
    require(isinstance(peers, dict), 'NETWORK_ENDPOINTS_INVALID')
    observed = {}
    for service, cid in container_ids.items():
        peer = peers.get(cid)
        require(isinstance(peer, dict), 'NETWORK_ENDPOINT_MISMATCH')
        observed[service] = {}
        for version, field in ((4, 'IPv4Address'), (6, 'IPv6Address')):
            wanted = attachments[service]['addresses'][str(version)]
            require(peer.get(field) == (wanted or ''), 'NETWORK_ENDPOINT_MISMATCH')
            if wanted:
                interface = ipaddress.ip_interface(wanted)
                require(any(interface.network == subnet and interface.ip in subnet for subnet in parsed),
                        'NETWORK_ENDPOINT_SUBNET_MISMATCH')
            observed[service]['ipv'+str(version)] = wanted
    return {'network_name': value['Name'], 'network_id': value['Id'], 'internal': True,
        'subnets': subnets, 'observed_container_addresses': observed,
        'other_attached_container_count': len(peers)-len(container_ids),
        'address_status': 'current-unpinned-observation', 'source_binding_approved': False,
        'address_reservation_reviewed': False}, json.dumps(value, sort_keys=True)


def inspected_containers(docker, before):
    result = {}
    for service in ('camera-api', 'camera-db'):
        value = json.loads(docker.run(['inspect', before[service]['id']]))
        require(isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict)
            and value[0].get('Id') == before[service]['id']
            and value[0].get('Image') == before[service]['image'], 'CONTAINER_IDENTITY_MISMATCH')
        mode = value[0].get('HostConfig', {}).get('UsernsMode')
        require(mode in ('', 'host'), 'CONTAINER_USER_NAMESPACE_MODE_UNREVIEWED')
        result[service] = value[0]
    return result


def inspect_facts(root, docker):
    docker.inspection_stage = 'accepted_source'
    revision = checked_source(root)
    paths = [root/'.env', root/inventory.RECEIPT]
    for path in paths: safe(path)
    inputs = [sha(path) for path in paths]
    docker.inspection_stage = 'host_key_metadata'
    key, key_before = inventory.key_metadata(root)
    docker.inspection_stage = 'accepted_registry_inventory'
    daemon = docker.preflight()
    before = docker.snapshot()
    result = inventory.inspect_supply(root, docker)
    require(all(before.get(s, {}).get('running') for s in ('camera-api', 'camera-db')),
            'RUNNING_CAMERA_DATABASE_REQUIRED')
    docker.inspection_stage = 'container_metadata'
    containers = inspected_containers(docker, before)
    ids = {s: before[s]['id'] for s in containers}
    docker.reviewed_container_ids = set(ids.values())
    docker.inspection_stage = 'process_identity_observation'
    processes = {s: process_identities(docker.run(['top', cid, '-eo', 'pid,euid,egid'])) for s, cid in ids.items()}
    docker.inspection_stage = 'daemon_security_metadata'
    security = daemon_security(docker.run(SECURITY_ARGS))
    docker.inspection_stage = 'database_volume_and_network_attachments'
    volume = database_volume(containers['camera-db'], docker.project)
    attachments = {s: attachment(value, docker.project) for s, value in containers.items()}
    require(attachments['camera-api']['network_id'] == attachments['camera-db']['network_id'],
            'NETWORK_ATTACHMENT_IDENTITY_MISMATCH')
    docker.reviewed_network_id = attachments['camera-db']['network_id']
    docker.inspection_stage = 'owned_storage_network'
    network, network_before = network_facts(docker.run(['network', 'inspect', docker.reviewed_network_id]),
        docker.project, ids, attachments)
    # Healthchecks can add a different UID temporarily. Record both windows;
    # neither window proves the identity of the future credential runtime.
    docker.inspection_stage = 'observation_recheck'
    after = inspected_containers(docker, before)
    require(database_volume(after['camera-db'], docker.project) == volume
        and {s: attachment(v, docker.project) for s, v in after.items()} == attachments
        and {s: v['HostConfig']['UsernsMode'] for s, v in after.items()} ==
            {s: v['HostConfig']['UsernsMode'] for s, v in containers.items()}, 'SUPPLY_FACTS_TOPOLOGY_CHANGED')
    for service, cid in ids.items():
        last = process_identities(docker.run(['top', cid, '-eo', 'pid,euid,egid']))
        processes[service].update(end_process_count=last['process_count'],
            end_effective_identities=last['effective_identities'],
            identities_stable_across_observations=
                processes[service]['effective_identities'] == last['effective_identities'])
    require(network_facts(docker.run(['network', 'inspect', docker.reviewed_network_id]),
        docker.project, ids, attachments)[1] == network_before
        and daemon_security(docker.run(SECURITY_ARGS)) == security, 'SUPPLY_FACTS_TOPOLOGY_CHANGED')
    docker.inspection_stage = 'input_and_container_recheck'
    require(checked_source(root) == revision and [sha(path) for path in paths] == inputs,
            'INSPECTION_INPUT_CHANGED')
    require(inventory.key_metadata(root)[1] == key_before, 'KEY_METADATA_CHANGED_DURING_INSPECTION')
    require(docker.preflight() == daemon and docker.snapshot() == before,
            'PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')
    key_fact = {**key, 'source_file': str(root/inventory.KEY), 'owner_uid': None, 'owner_gid': None}
    for name, fingerprint in key_before:
        if name == 'key-bundle.json' and isinstance(fingerprint, tuple):
            key_fact.update(owner_uid=fingerprint[2], owner_gid=fingerprint[3])
    return {'status': 'inspected', 'scope': SCOPE, 'inspection_completed': True,
        'project': docker.project, 'checked_revision': revision, 'plan_state': 'incomplete',
        'readiness': 'blocked', 'production_supply_ready': False, 'activation_allowed': False,
        'inventory': result, 'host_key_bundle': key_fact, 'daemon_security': security,
        'processes': processes, 'database_volume': volume, 'storage_network': network,
        'container_userns_modes': {s: v['HostConfig']['UsernsMode'] for s, v in containers.items()},
        'unresolved_inputs': UNRESOLVED, 'next_step': 'review_observed_facts_and_supply_locations', **NO_CHANGES}


def failure_code(exc):
    return inventory.failure_code(exc) if isinstance(exc, ActivationError) else 'SUPPLY_FACTS_INSPECTION_UNAVAILABLE'


def run_inspection(root):
    with activation_lock(root):
        atomic_write(root/REPORT, json.dumps({'status': 'running', 'scope': SCOPE, **NO_CHANGES}).encode()+b'\n')
        docker = FactsDocker(root)
        try:
            value = inspect_facts(root, docker)
        except BaseException as exc:
            stage = getattr(docker, 'inspection_stage', 'accepted_source')
            if stage not in STAGES: stage = 'accepted_source'
            exc.inspection_stage = stage
            atomic_write(root/REPORT, json.dumps({'status': 'failed', 'scope': SCOPE,
                'inspection_completed': False, 'production_supply_ready': False,
                'activation_allowed': False, 'code': failure_code(exc), 'failed_stage': stage,
                **NO_CHANGES}).encode()+b'\n')
            raise
        atomic_write(root/REPORT, (json.dumps(value, indent=2)+'\n').encode())
    return value


def main():
    root = Path(__file__).resolve().parents[3]
    try:
        require(len(sys.argv) == 1, 'NO_ARGUMENTS_EXPECTED')
        result = run_inspection(root)
        print(json.dumps({**result, 'report': str(root/REPORT)}, ensure_ascii=False))
        return 0  # Facts collected; unresolved review inputs are expected.
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError,
            AttributeError, URLError, KeyboardInterrupt) as exc:
        stage = getattr(exc, 'inspection_stage', 'accepted_source')
        if stage not in STAGES: stage = 'accepted_source'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': failure_code(exc),
            'inspection_completed': False, 'production_supply_ready': False,
            'activation_allowed': False, 'failed_stage': stage, **NO_CHANGES}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
