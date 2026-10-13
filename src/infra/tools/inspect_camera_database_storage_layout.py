#!/usr/bin/env python3
"""Observe active PostgreSQL storage locations; never create a backup or a plan.

Only fixed read-only catalog SQL and stat/readlink metadata commands are added.
Container observations and lexical host candidates are not physical backup proof.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from urllib.error import URLError

import inspect_camera_credential_storage_topology as topology
from camera_activation import ActivationError, Docker, activation_lock, atomic_write, safe, sha

identity, facts, inventory = topology.identity, topology.facts, topology.inventory
require = inventory.require
SCOPE = 'camera_database_storage_layout_observation'
REPORT = 'var/camera/database-storage-layout.json'
ACCEPTED_VOLUME = '61db0fcc701df8fc5d4e1087107513a60b6b01ac4db96779482d7df8e8ef9009'
SOURCE = 'src/infra/tools/inspect_camera_database_storage_layout.py'
MAX_OUTPUT = 1048576
NO_CHANGES = topology.NO_CHANGES
STAGES = (*topology.STAGES, 'database_layout_identity', 'database_layout_catalog',
    'database_layout_directories', 'database_layout_recheck',
    'database_layout_container_recheck', 'layout_input_recheck')
UNRESOLVED = [*topology.UNRESOLVED, 'ARCHIVED_WAL_DESTINATIONS_AND_RETENTION_POLICY']

CATALOG_SQL = """BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '3s';
SET LOCAL search_path = pg_catalog;
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL TimeZone = 'UTC';
SELECT json_build_object(
  'database', current_database(), 'session_user', session_user, 'current_user', current_user,
  'transaction_read_only', current_setting('transaction_read_only') = 'on',
  'server_version_num', current_setting('server_version_num')::integer,
  'postmaster_started', pg_postmaster_start_time()::text,
  'data_directory', left(current_setting('data_directory'), 4097),
  'config_file', left(current_setting('config_file'), 4097),
  'hba_file', left(current_setting('hba_file'), 4097),
  'ident_file', left(current_setting('ident_file'), 4097),
  'archive_mode', current_setting('archive_mode'),
  'tablespace_count', (SELECT count(*) FROM pg_tablespace),
  'tablespaces', (SELECT coalesce(json_agg(json_build_object('oid', oid::bigint,
    'location', left(pg_tablespace_location(oid), 4097)) ORDER BY oid), '[]'::json)
    FROM (SELECT oid FROM pg_tablespace ORDER BY oid LIMIT 129) AS locations));
COMMIT;"""

# NUL-delimited readlink output must not pass through command substitution:
# trailing newlines in a real pathname would otherwise be silently discarded.
METADATA_SCRIPT = r'''set -eu
printf 'camera_db_directory_metadata_v1\0%s\0%s\0' "$(/usr/bin/id -u)" "$(/usr/bin/id -g)"
for path do
  /usr/bin/stat --printf '%d %i %f %u %g\0' -- "$path"
  /usr/bin/readlink -e -z -- "$path"
  /usr/bin/stat -L --printf '%d %i %f %u %g\0' -- "$path"
  /usr/bin/stat --printf '%d %i %f %u %g\0' -- "$path"
  /usr/bin/readlink -e -z -- "$path"
done'''


def checked_source(root):
    revision = topology.checked_source(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    require(manifest.get('credential_production_database_mount_topology_server_verified') is True
        and manifest.get('validated_credential_production_directory_observer_project_sha256') == ACCEPTED_VOLUME
        and manifest.get('camera_database_storage_layout_implemented') is True,
        'ACCEPTED_VOLUME_OBSERVATION_REQUIRED')
    require(SOURCE in manifest['files'], 'DATABASE_LAYOUT_SOURCE_MANIFEST_INCOMPLETE')
    return revision


def path_value(value):
    try: return facts.canonical_host_path(value)
    except ActivationError: raise ActivationError('DATABASE_LAYOUT_PATH_INVALID') from None


def unique_object(items):
    value = {}
    for key, item in items:
        require(key not in value, 'DATABASE_LAYOUT_CATALOG_INVALID')
        value[key] = item
    return value


def mount_bindings(rows):
    """Compare whole mount records by destination, independent of array order.

    Keep every attribute and JSON type; duplicate destinations cannot identify
    a unique binding. Do not include mount values in errors or public reports.
    """
    require(isinstance(rows, list) and rows, 'DATABASE_LAYOUT_MOUNTS_INVALID')
    bindings = {}
    for row in rows:
        require(isinstance(row, dict), 'DATABASE_LAYOUT_MOUNTS_INVALID')
        try: destination = path_value(row.get('Destination'))
        except ActivationError: raise ActivationError('DATABASE_LAYOUT_MOUNTS_INVALID') from None
        require(destination not in bindings, 'DATABASE_LAYOUT_MOUNTS_INVALID')
        try: bindings[destination] = json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError): raise ActivationError('DATABASE_LAYOUT_MOUNTS_INVALID') from None
    return bindings


def catalog(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_OUTPUT, 'DATABASE_LAYOUT_CATALOG_INVALID')
    try: value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError): raise ActivationError('DATABASE_LAYOUT_CATALOG_INVALID') from None
    fields = {'database', 'session_user', 'current_user', 'transaction_read_only', 'server_version_num',
        'postmaster_started', 'data_directory', 'config_file', 'hba_file', 'ident_file',
        'archive_mode', 'tablespace_count', 'tablespaces'}
    require(isinstance(value, dict) and set(value) == fields, 'DATABASE_LAYOUT_CATALOG_INVALID')
    require(value['database'] == 'vms_camera' and value['session_user'] == 'camera_admin'
        and value['current_user'] == 'camera_admin' and value['transaction_read_only'] is True,
        'DATABASE_LAYOUT_READ_ONLY_SESSION_REQUIRED')
    require(type(value['server_version_num']) is int and 170000 <= value['server_version_num'] < 180000,
        'DATABASE_LAYOUT_SERVER_VERSION_UNSUPPORTED')
    require(isinstance(value['postmaster_started'], str) and
        re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:.]{8,18}[+-][0-9:]{2,5}', value['postmaster_started']),
        'DATABASE_LAYOUT_CATALOG_INVALID')
    for field in ('data_directory', 'config_file', 'hba_file', 'ident_file'): path_value(value[field])
    require(value['archive_mode'] in ('off', 'on', 'always'), 'DATABASE_LAYOUT_CATALOG_INVALID')
    rows = value['tablespaces']
    require(type(value['tablespace_count']) is int and 2 <= value['tablespace_count'] <= 128
        and isinstance(rows, list) and len(rows) == value['tablespace_count'],
        'DATABASE_LAYOUT_TABLESPACE_LIMIT_OR_COUNT_INVALID')
    oids = []
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'oid', 'location'} and type(row['oid']) is int
            and 0 < row['oid'] < 4294967295, 'DATABASE_LAYOUT_TABLESPACE_INVALID')
        oids.append(row['oid'])
        if row['oid'] in (1663, 1664):
            require(row['location'] == '', 'DATABASE_LAYOUT_BUILTIN_TABLESPACE_INVALID')
        else: path_value(row['location'])
    require(oids == sorted(set(oids)) and {1663, 1664} <= set(oids), 'DATABASE_LAYOUT_TABLESPACE_INVALID')
    return value


def metadata_paths(value):
    return tuple(dict.fromkeys([value['data_directory'], value['data_directory']+'/pg_wal',
        *[row['location'] for row in value['tablespaces'] if row['oid'] not in (1663, 1664)]]))


def metadata_args(database_id, paths):
    return ['exec', '--user', '999:999', database_id, '/usr/bin/env', '-i',
        'PATH=/usr/bin:/bin', 'LC_ALL=C', '/bin/sh', '-c', METADATA_SCRIPT, 'camera-layout', *paths]


class LayoutDocker(facts.FactsDocker):
    """Permit two exact read commands only for the already identified owned DB."""
    def __init__(self, root):
        super().__init__(root)
        self.layout_paths = None

    def run(self, args, **kwargs):
        valid_db = isinstance(self.database_id, str) and re.fullmatch('[0-9a-f]{64}', self.database_id)
        valid_db = valid_db and self.database_id in self.reviewed_container_ids
        sql = ['exec', '--user', '999:999', self.database_id, *inventory.SQL_ARGS, CATALOG_SQL]
        metadata = None
        if self.layout_paths is not None:
            require(isinstance(self.layout_paths, tuple) and 2 <= len(self.layout_paths) <= 128,
                'DATABASE_LAYOUT_COMMAND_PATHS_INVALID')
            for path in self.layout_paths: path_value(path)
            metadata = metadata_args(self.database_id, self.layout_paths)
        if not valid_db or (args != sql and args != metadata): return super().run(args, **kwargs)
        require(not (kwargs.keys()-{'input', 'stdout', 'timeout', 'extra'})
            and kwargs.get('input') is None and kwargs.get('stdout') is None and not kwargs.get('extra'),
            'PRODUCTION_DOCKER_WRITE_REJECTED')
        try: return Docker.run(self, args, **kwargs)
        except ActivationError: raise identity.IdentityBlocked('READ_ONLY_LAYOUT_COMMAND_UNAVAILABLE') from None


def stat_value(raw):
    try: fields = raw.decode('ascii').split(' ')
    except UnicodeError: raise ActivationError('DATABASE_LAYOUT_METADATA_INVALID') from None
    require(len(fields) == 5 and all(re.fullmatch('0|[1-9][0-9]{0,19}', fields[i]) for i in (0, 1, 3, 4))
        and re.fullmatch('[0-9a-f]{1,4}', fields[2]), 'DATABASE_LAYOUT_METADATA_INVALID')
    result = (int(fields[0]), int(fields[1]), int(fields[2], 16), int(fields[3]), int(fields[4]))
    require(result[1] > 0 and result[3] < 4294967295 and result[4] < 4294967295,
        'DATABASE_LAYOUT_METADATA_INVALID')
    return result


def directories(raw, paths, *, execution=(999, 999)):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_OUTPUT, 'DATABASE_LAYOUT_METADATA_INVALID')
    fields = raw.split(b'\0')
    require(len(fields) == 4+5*len(paths) and fields[-1] == b''
        and fields[0] == b'camera_db_directory_metadata_v1', 'DATABASE_LAYOUT_METADATA_INVALID')
    require(fields[1:3] == [str(v).encode('ascii') for v in execution], 'DATABASE_LAYOUT_EXECUTION_IDENTITY_MISMATCH')
    result = {}
    for index, path in enumerate(paths):
        path_value(path)
        first, resolved, target, last, resolved_after = fields[3+5*index:8+5*index]
        leaf, resolved_stat = stat_value(first), stat_value(target)
        require(first == last and resolved == resolved_after, 'DATABASE_LAYOUT_DIRECTORY_CHANGED')
        require(stat.S_ISDIR(resolved_stat[2]) and (stat.S_ISDIR(leaf[2]) or stat.S_ISLNK(leaf[2])),
            'DATABASE_LAYOUT_DIRECTORY_REQUIRED')
        require(stat.S_ISLNK(leaf[2]) or leaf == resolved_stat, 'DATABASE_LAYOUT_DIRECTORY_CHANGED')
        try: resolved_path = path_value(resolved.decode('utf-8', 'strict'))
        except UnicodeError: raise ActivationError('DATABASE_LAYOUT_PATH_INVALID') from None
        result[path] = {'resolved_path': resolved_path, 'leaf_is_symlink': stat.S_ISLNK(leaf[2]),
            'owner_uid': resolved_stat[3], 'owner_gid': resolved_stat[4],
            'permissions': format(stat.S_IMODE(resolved_stat[2]), '04o'),
            'signature': (leaf, resolved_stat)}
    return result


def location(path, observed, volume, pgdata):
    resolved = observed['resolved_path']; target = volume['container_data_directory']
    candidate = None
    if topology.below(resolved, target):
        candidate = (PurePosixPath(volume['daemon_declared_host_data_directory']) /
            PurePosixPath(resolved).relative_to(target)).as_posix()
    return {'container_path': path, **{k: v for k, v in observed.items() if k != 'signature'},
        'outside_resolved_pgdata': not topology.below(resolved, pgdata),
        'within_verified_container_volume': topology.below(resolved, target),
        'host_path_candidate': candidate, 'host_path_candidate_basis':
            'lexical-relative-to-current-verified-volume' if candidate else 'unresolved',
        'host_path_verified': False}


def layout_report(value, observed, volume):
    data = value['data_directory']; resolved = observed[data]['resolved_path']
    return {'database': 'vms_camera', 'server_version_num': value['server_version_num'],
        'read_only_transaction_verified': True, 'metadata_execution_uid': 999, 'metadata_execution_gid': 999,
        'pgdata': location(data, observed[data], volume, resolved),
        'wal': location(data+'/pg_wal', observed[data+'/pg_wal'], volume, resolved),
        'custom_tablespaces': [{'oid': row['oid'], **location(row['location'], observed[row['location']], volume, resolved)}
            for row in value['tablespaces'] if row['oid'] not in (1663, 1664)],
        'catalog_tablespace_count': value['tablespace_count'], 'archive_mode': value['archive_mode'],
        'archive_destinations_observed': False,
        'configuration_paths': {field: {'container_path': value[field],
            'lexically_outside_configured_pgdata': not topology.below(value[field], data),
            'file_contents_read': False, 'physical_path_verified': False}
            for field in ('config_file', 'hba_file', 'ident_file')}}


def inspect_layout(root, docker, reader_factory=topology.MountReader):
    docker.inspection_stage = 'accepted_source'; revision = checked_source(root)
    inputs = [root/'.env', root/inventory.RECEIPT]
    for path in inputs: safe(path)
    digests = [sha(path) for path in inputs]; key = inventory.key_metadata(root)[1]
    daemon, before = docker.preflight(), docker.snapshot()
    proof = topology.inspect_topology(root, docker, reader_factory)
    require(proof['checked_revision'] == revision, 'INSPECTION_INPUT_CHANGED')
    result, blockers = None, list(proof['blockers'])
    if proof['topology_readiness'] == 'verified':
        docker.inspection_stage = 'database_layout_identity'
        db = facts.inspected_containers(docker, before)['camera-db']
        mounts = mount_bindings(db['Mounts'])
        pid = identity.init_pid(db, before['camera-db'])
        try:
            docker.inspection_stage = 'database_layout_identity'
            with reader_factory() as reader:
                observer, process = reader.observer(), reader.process(pid)
                identity.process_result(process, before['camera-db']['id'], (999, 999))
                host_path = proof['volume']['daemon_declared_host_data_directory']
                target = proof['volume']['container_data_directory']
                volume_directory = reader.directory(host_path)
                _, selected = topology.compare_volume(host_path, target,
                    reader.mounts(os.getpid()), reader.mounts(pid), volume_directory)
                docker.inspection_stage = 'database_layout_catalog'
                query = ['exec', '--user', '999:999', before['camera-db']['id'], *inventory.SQL_ARGS, CATALOG_SQL]
                first = catalog(docker.run(query, timeout=30))
                docker.layout_paths = metadata_paths(first)
                docker.inspection_stage = 'database_layout_directories'
                command = metadata_args(before['camera-db']['id'], docker.layout_paths)
                observed = directories(docker.run(command, timeout=30), docker.layout_paths)
                docker.inspection_stage = 'database_layout_recheck'
                try:
                    require(catalog(docker.run(query, timeout=30)) == first, 'DATABASE_LAYOUT_CATALOG_CHANGED')
                    require(directories(docker.run(command, timeout=30), docker.layout_paths) == observed,
                        'DATABASE_LAYOUT_DIRECTORY_CHANGED')
                    require(reader.observer() == observer and reader.process(pid) == process,
                        'PROCESS_CHANGED_DURING_INSPECTION')
                    require(reader.directory(host_path) == volume_directory, 'DATABASE_LAYOUT_VOLUME_CHANGED')
                    _, selected_after = topology.compare_volume(host_path, target,
                        reader.mounts(os.getpid()), reader.mounts(pid), volume_directory)
                    require(selected_after == selected, 'DATABASE_LAYOUT_VOLUME_CHANGED')
                except (identity.IdentityBlocked, OSError):
                    raise ActivationError('DATABASE_LAYOUT_UNAVAILABLE_DURING_RECHECK') from None
            final = topology.inspect_topology(root, docker, reader_factory)
            require(final == proof, 'DATABASE_LAYOUT_VOLUME_CHANGED')
            docker.inspection_stage = 'database_layout_container_recheck'
            last = facts.inspected_containers(docker, before)['camera-db']
            require(identity.init_pid(last, before['camera-db']) == pid, 'DATABASE_LAYOUT_CONTAINER_PID_CHANGED')
            require(last['HostConfig'] == db['HostConfig'], 'DATABASE_LAYOUT_HOST_CONFIG_CHANGED')
            require(mount_bindings(last['Mounts']) == mounts, 'DATABASE_LAYOUT_MOUNTS_CHANGED')
            result = layout_report(first, observed, proof['volume'])
        except (identity.IdentityBlocked, OSError) as exc:
            blockers = [inventory.failure_code(exc) if isinstance(exc, identity.IdentityBlocked)
                else 'DATABASE_LAYOUT_METADATA_UNAVAILABLE']
    docker.inspection_stage = 'layout_input_recheck'
    for path in inputs: safe(path)
    require(checked_source(root) == revision and [sha(path) for path in inputs] == digests, 'INSPECTION_INPUT_CHANGED')
    require(inventory.key_metadata(root)[1] == key, 'KEY_METADATA_CHANGED_DURING_INSPECTION')
    require(docker.preflight() == daemon and docker.snapshot() == before, 'PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')
    return {'status': 'inspected', 'scope': SCOPE, 'inspection_completed': True,
        'project': docker.project, 'checked_revision': revision, 'layout_readiness': 'observed' if result else 'blocked',
        'current_volume_mount_verified': proof['topology_readiness'] == 'verified',
        'active_database_storage_locations_observed': result is not None,
        'layout': result, 'blockers': blockers, 'unresolved_backup_topology': UNRESOLVED,
        'readiness': 'blocked', 'production_supply_ready': False, 'activation_allowed': False,
        'next_step': 'review_physical_storage_mappings_and_complete_backup_roots', **NO_CHANGES}


def failure_code(exc):
    return inventory.failure_code(exc) if isinstance(exc, ActivationError) else 'DATABASE_LAYOUT_INSPECTION_UNAVAILABLE'


def run_inspection(root, *, privileged=False):
    if privileged: require(os.geteuid() != 0, 'RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER')
    with activation_lock(root):
        atomic_write(root/REPORT, json.dumps({'status': 'running', 'scope': SCOPE,
            'activation_allowed': False, **NO_CHANGES}).encode()+b'\n')
        docker = LayoutDocker(root)
        try:
            result = inspect_layout(root, docker, lambda: topology.AssistedMountReader(root)) if privileged else inspect_layout(root, docker)
            result['privileged_directory_observer_requested'] = privileged
        except BaseException as exc:
            stage = getattr(docker, 'inspection_stage', 'accepted_source')
            if stage not in STAGES: stage = 'accepted_source'
            exc.inspection_stage = stage
            atomic_write(root/REPORT, json.dumps({'status': 'failed', 'scope': SCOPE,
                'inspection_completed': False, 'active_database_storage_locations_observed': False,
                'layout_readiness': 'blocked', 'activation_allowed': False, 'production_supply_ready': False,
                'code': failure_code(exc), 'failed_stage': stage, **NO_CHANGES}).encode()+b'\n')
            raise
        atomic_write(root/REPORT, (json.dumps(result, indent=2)+'\n').encode())
    return result


def main():
    root = Path(__file__).resolve().parents[3]
    privileged = sys.argv[1:] == ['--privileged-directory-metadata']
    try:
        require(len(sys.argv) == 1 or privileged, 'NO_ARGUMENTS_EXPECTED')
        result = run_inspection(root, privileged=True) if privileged else run_inspection(root)
        print(json.dumps({**result, 'report': str(root/REPORT)}, ensure_ascii=False)); return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError,
        URLError, KeyboardInterrupt) as exc:
        stage = getattr(exc, 'inspection_stage', 'accepted_source')
        if stage not in STAGES: stage = 'accepted_source'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': failure_code(exc), 'failed_stage': stage,
            'inspection_completed': False, 'active_database_storage_locations_observed': False,
            'activation_allowed': False, 'production_supply_ready': False, **NO_CHANGES}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
