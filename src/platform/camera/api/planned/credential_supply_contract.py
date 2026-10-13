"""Static review-only supply-plan validator. No deployment, key or authority IO.

Successful parsing returns declarations, never runtime authorization or readiness.
The file/hash/mount/role/TLS/backup observations needed for supply remain external.
"""
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re

from jsonschema import Draft202012Validator

MAX_BYTES = 32768
SCHEMA = json.loads((Path(__file__).parent/'credential-supply.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


class SupplyContractError(ValueError):
    """Only fixed codes; schema/parser exceptions can contain supplied secrets."""


def require(condition, code):
    if not condition:
        raise SupplyContractError(code)


def canonical_path(value):
    p = PurePosixPath(value)
    require(p.is_absolute() and value != '/' and p.as_posix() == value
        and '..' not in p.parts, 'SUPPLY_PATH_NOT_CANONICAL')
    return p


def overlaps(a, b):
    a, b = PurePosixPath(a), PurePosixPath(b)
    return a == b or a in b.parents or b in a.parents


def canonical_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise SupplyContractError('SUPPLY_IP_NOT_CANONICAL') from None
    require(str(address) == value and not address.is_unspecified and not address.is_multicast
        and '%' not in value and not getattr(address, 'ipv4_mapped', None),
        'SUPPLY_IP_NOT_CANONICAL')
    return address


def tls_identity(value):
    try:
        canonical_ip(value)
        return
    except SupplyContractError:
        pass
    # Mirror the existing endpoint constructor's lowercase DNS identity rules.
    require(value == value.lower() and all(0 < len(label) <= 63
        and re.fullmatch('[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label)
        for label in value.split('.')), 'SUPPLY_TLS_IDENTITY_INVALID')


def mount_references(profile):
    """Context matters: shared CA/authority are used in independent containers."""
    d, m, r = profile['database'], profile['maintenance'], profile['runtime']
    ca = profile['tls']['ca_file']
    key = profile['key_supply']['runtime_directory']
    authority = {'host_path': profile['authority']['host_directory'],
        'container_path': profile['authority']['container_directory']}
    return {
        'database': [d['hba_file'], d['server_certificate_file'], d['server_private_key_file'], ca],
        'maintenance': [m['control_dsn_file'], m['target_dsn_file'], m['client_certificate_file'],
            m['client_private_key_file'], ca, authority],
        'runtime': [r['writer_dsn_file'], r['budget_dsn_file'], ca, key, authority],
    }


def validate_supply_profile(profile):
    """Validate declaration shape/relationships; do not inspect referenced paths."""
    require(VALIDATOR.is_valid(profile), 'SUPPLY_SCHEMA_INVALID')
    d, m, r, a, k = (profile[n] for n in ('database', 'maintenance', 'runtime', 'authority', 'key_supply'))
    require(all(type(v) is int for v in (profile['format_version'],
        profile['inventory_basis']['schema_version'], d['target_schema_version'], d['port'], d['server_uid'],
        m['uid'], r['uid'], r['gid'], a['owner_uid'], a['runtime_gid'], k['source_owner_uid'])),
        'SUPPLY_INTEGER_TYPE_INVALID')
    paths = [profile['project_root'], d['host_data_directory'], d['container_data_directory'],
        k['source_file'], a['host_directory'], a['container_directory'], a['lock_receipt_host_file'],
        *profile['declared_snapshot_roots']]
    contexts = mount_references(profile)
    for mounts in contexts.values():
        paths.extend(p[name] for p in mounts for name in ('host_path', 'container_path'))
    for value in paths:
        canonical_path(value)
    require(r['uid'] != m['uid'] and a['owner_uid'] == m['uid']
        and a['runtime_gid'] == r['gid'], 'SUPPLY_UID_OR_GROUP_CONFLICT')
    # Both sources must be distinct addresses of the endpoint's address family.
    addresses = [canonical_ip(v) for v in (d['host_ip'], m['source_ip'], r['source_ip'])]
    require(len({ip.version for ip in addresses}) == 1 and addresses[1] != addresses[2],
            'SUPPLY_SOURCE_BOUNDARY_CONFLICT')
    tls_identity(profile['tls']['server_name'])
    # A runtime-owned copy must never retag or shadow the prepared source file.
    require(not overlaps(k['source_file'], k['runtime_directory']['host_path']),
            'SUPPLY_KEY_SOURCE_COPY_OVERLAP')
    fences = [profile['project_root'], d['host_data_directory'],
        str(PurePosixPath(k['source_file']).parent), k['runtime_directory']['host_path'],
        *profile['declared_snapshot_roots']]
    for protected in (a['host_directory'], a['lock_receipt_host_file']):
        require(not any(overlaps(protected, fence) for fence in fences),
                'SUPPLY_AUTHORITY_SNAPSHOT_OVERLAP')
    require(not overlaps(a['host_directory'], a['lock_receipt_host_file']),
            'SUPPLY_LOCK_RECEIPT_INSIDE_AUTHORITY')
    # HBA and TLS artifacts must survive target data-directory replacement.
    for mount in contexts['database']:
        require(not overlaps(mount['host_path'], d['host_data_directory'])
            and not overlaps(mount['container_path'], d['container_data_directory']),
            'SUPPLY_DATABASE_CONTROL_INSIDE_DATA')
        require(not any(overlaps(mount['host_path'], fence) for fence in fences),
                'SUPPLY_DATABASE_CONTROL_SNAPSHOT_OVERLAP')
    # A mount at a parent/child destination can hide another reviewed mount.
    for mounts in contexts.values():
        for i, left in enumerate(mounts):
            for right in mounts[i+1:]:
                require(not overlaps(left['container_path'], right['container_path']),
                        'SUPPLY_CONTAINER_MOUNT_OVERLAP')
    # Secret roles, certs, key directory and authority must have separate host entries.
    unique = {p['host_path'] for mounts in contexts.values() for p in mounts}
    host_entries = [k['source_file'], a['lock_receipt_host_file'], *sorted(unique)]
    # Repeated shared CA/authority above are intentional; distinct declarations
    # may not point at the same host file (e.g. writer DSN = maintenance key).
    originals = [d['hba_file'], d['server_certificate_file'], d['server_private_key_file'],
        profile['tls']['ca_file'], m['control_dsn_file'], m['target_dsn_file'],
        m['client_certificate_file'], m['client_private_key_file'],
        r['writer_dsn_file'], r['budget_dsn_file'], k['runtime_directory']]
    require(len({p['host_path'] for p in originals}) == len(originals),
            'SUPPLY_HOST_MOUNT_ALIAS')
    for i, left in enumerate(host_entries):
        for right in host_entries[i+1:]:
            require(not overlaps(left, right), 'SUPPLY_HOST_PATH_OVERLAP')
    return profile


def parse_supply_profile(raw):
    """Bounded UTF8 JSON: reject aliases/duplicate fields, float and NaN tokens."""
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, 'SUPPLY_INPUT_SIZE_OR_TYPE_INVALID')
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'SUPPLY_DUPLICATE_FIELD')
            result[key] = value
        return result
    def reject_number(_):
        raise SupplyContractError('SUPPLY_NONINTEGER_NUMBER')
    try:
        profile = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
            parse_float=reject_number, parse_constant=reject_number)
    except SupplyContractError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise SupplyContractError('SUPPLY_JSON_INVALID') from None
    return validate_supply_profile(profile)
