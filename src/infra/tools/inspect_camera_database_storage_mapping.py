#!/usr/bin/env python3
"""Match two reviewed PostgreSQL directories using live host/container metadata.

Directory O_PATH descriptors, fixed existing SQL/stat and procfs metadata only.
Never declare full backup topology, read DB files or activate credential supply.
"""
import json
import os
from pathlib import Path, PurePosixPath
import sys
from urllib.error import URLError

import inspect_camera_database_storage_layout as layout
from camera_activation import ActivationError, activation_lock, atomic_write, safe, sha

topology, identity, facts, inventory = layout.topology, layout.identity, layout.facts, layout.inventory
require = inventory.require
SCOPE = 'camera_database_storage_physical_mapping'
REPORT = 'var/camera/database-storage-mapping.json'
SOURCE = 'src/infra/tools/inspect_camera_database_storage_mapping.py'
DATA = '/var/lib/postgresql/data'
HOST = topology.directory_observer.HOST_PATH
PATHS = (DATA, DATA+'/pg_wal')
HOSTS = (HOST, HOST+'/pg_wal')
ACCEPTED_LAYOUT = topology.ACCEPTED_STORAGE_LAYOUT
NO_CHANGES = layout.NO_CHANGES
STAGES = (*layout.STAGES, 'mapping_container_metadata', 'mapping_catalog_metadata',
    'host_storage_directories', 'physical_mapping_comparison', 'physical_mapping_recheck',
    'mapping_container_recheck', 'mapping_input_recheck')
UNRESOLVED = ['ALL_BACKUP_AND_RESTORE_SNAPSHOT_ROOTS_AND_DESTINATIONS',
    'EXTERNAL_AUTHORITY_LOCK_HBA_AND_PKI_PHYSICAL_EXCLUSION',
    'COORDINATED_DATABASE_AND_KEY_BACKUP_RESTORE_PROCEDURE',
    'ARCHIVED_WAL_DESTINATIONS_AND_RETENTION_POLICY']


def checked_source(root):
    revision = layout.checked_source(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    require(manifest.get('camera_database_storage_layout_server_verified') is True
        and manifest.get('validated_camera_database_storage_layout_project_sha256') == ACCEPTED_LAYOUT
        and manifest.get('camera_database_storage_mapping_implemented') is True,
        'ACCEPTED_STORAGE_LAYOUT_REQUIRED')
    require({SOURCE, topology.OBSERVER_SOURCE} <= manifest['files'].keys(),
        'DATABASE_MAPPING_SOURCE_MANIFEST_INCOMPLETE')
    return revision


def reviewed_profile(proof):
    """Authorize exactly the observed non-symlink PGDATA and in-place WAL."""
    require(proof['layout_readiness'] == 'observed' and proof['current_volume_mount_verified'] is True
        and proof['active_database_storage_locations_observed'] is True, 'CURRENT_STORAGE_LAYOUT_REQUIRED')
    value = proof['layout']
    require(value['custom_tablespaces'] == [] and value['catalog_tablespace_count'] == 2
        and value['archive_mode'] == 'off', 'CURRENT_STORAGE_LAYOUT_REVIEW_REQUIRED')
    for name, path, host in zip(('pgdata', 'wal'), PATHS, HOSTS):
        row = value[name]
        require(row['container_path'] == row['resolved_path'] == path
            and row['host_path_candidate'] == host and row['leaf_is_symlink'] is False
            and row['within_verified_container_volume'] is True
            and row['outside_resolved_pgdata'] is False
            and (row['owner_uid'], row['owner_gid'], row['permissions']) == (999, 999, '0700'),
            'CURRENT_STORAGE_LAYOUT_REVIEW_REQUIRED')
    return value


def compare_directory(host_path, container_path, host_mounts, db_mounts, host, observed):
    """Bind the path descriptor and container stat to the same mount and inode."""
    leaf, target = observed['signature']
    require(leaf == target and observed['leaf_is_symlink'] is False
        and observed['resolved_path'] == container_path, 'DATABASE_MAPPING_SYMLINK_OR_PATH_REJECTED')
    expected = (target[0], target[1], target[3], target[4], target[2])
    require(host['signature'][-1] == expected, 'DATABASE_HOST_DIRECTORY_IDENTITY_MISMATCH')
    require(host['device'] == (os.major(target[0]), os.minor(target[0])),
        'DATABASE_HOST_DIRECTORY_DEVICE_MISMATCH')
    selected_host = topology.visible_mount(host_path, host_mounts)
    selected_db = topology.visible_mount(container_path, db_mounts)
    require(host['mount_id'] == selected_host['id'] and host['device'] == selected_host['device'],
        'HOST_DIRECTORY_MOUNT_MISMATCH')
    require(topology.canonical_mount_path(selected_host['root'])
        and topology.canonical_mount_path(selected_db['root']), 'DATABASE_MOUNT_ROOT_NOT_CANONICAL')
    expected_root = (PurePosixPath(selected_host['root']) /
        PurePosixPath(host_path).relative_to(selected_host['point'])).as_posix()
    actual_root = (PurePosixPath(selected_db['root']) /
        PurePosixPath(container_path).relative_to(selected_db['point'])).as_posix()
    require(expected_root == actual_root and selected_host['device'] == selected_db['device']
        and selected_host['filesystem'] == selected_db['filesystem'], 'DATABASE_MAPPING_MOUNT_SOURCE_MISMATCH')
    require(selected_db['filesystem'] in topology.SUPPORTED_FILESYSTEMS
        and selected_host['read_only'] is False and selected_db['read_only'] is False,
        'DATABASE_MAPPING_FILESYSTEM_OR_MODE_REJECTED')
    result = {'container_path': container_path, 'host_path': host_path, 'host_path_verified': True,
        'host_path_without_symlinks_verified': True, 'same_directory_identity_verified': True,
        'filesystem_type': selected_db['filesystem'], 'owner_uid': host['owner_uid'],
        'owner_gid': host['owner_gid'], 'permissions': host['mode'],
        'privileged_directory_observer_used': host.get('privileged_directory_observer_used', False),
        'privileged_sender_uid_verified': host.get('privileged_sender_uid_verified', False)}
    return result, (selected_host, selected_db)


def inspect_mapping(root, docker, reader_factory=topology.MountReader):
    docker.inspection_stage = 'accepted_source'; revision = checked_source(root)
    inputs = [root/'.env', root/inventory.RECEIPT]
    for path in inputs: safe(path)
    digests = [sha(path) for path in inputs]; key = inventory.key_metadata(root)[1]
    daemon, before = docker.preflight(), docker.snapshot()
    proof = layout.inspect_layout(root, docker, reader_factory)
    require(proof['checked_revision'] == revision, 'INSPECTION_INPUT_CHANGED')
    result, blockers = None, list(proof['blockers'])
    if proof['layout_readiness'] == 'observed':
        reviewed_profile(proof)
        docker.inspection_stage = 'mapping_container_metadata'
        db = facts.inspected_containers(docker, before)['camera-db']
        pid = identity.init_pid(db, before['camera-db']); mounts = layout.mount_bindings(db['Mounts'])
        try:
            docker.inspection_stage = 'mapping_catalog_metadata'
            query = ['exec', '--user', '999:999', before['camera-db']['id'], *inventory.SQL_ARGS, layout.CATALOG_SQL]
            first = layout.catalog(docker.run(query, timeout=30))
            require(layout.metadata_paths(first) == PATHS, 'CURRENT_STORAGE_LAYOUT_REVIEW_REQUIRED')
            docker.layout_paths = PATHS
            command = layout.metadata_args(before['camera-db']['id'], PATHS)
            observed = layout.directories(docker.run(command, timeout=30), PATHS)
            volume = {'container_data_directory': DATA, 'daemon_declared_host_data_directory': HOST}
            require(layout.layout_report(first, observed, volume) == proof['layout'], 'DATABASE_LAYOUT_CHANGED')
            with reader_factory() as reader:
                observer, process = reader.observer(), reader.process(pid)
                identity.process_result(process, before['camera-db']['id'], (999, 999))
                host_mounts, db_mounts = reader.mounts(os.getpid()), reader.mounts(pid)
                docker.inspection_stage = 'host_storage_directories'
                directories = [reader.directory(path) for path in HOSTS]
                require(directories[1]['signature'][:-1] == directories[0]['signature'],
                    'DATABASE_HOST_DIRECTORY_CHAIN_MISMATCH')
                docker.inspection_stage = 'physical_mapping_comparison'
                _, volume_mounts = topology.compare_volume(HOST, DATA, host_mounts, db_mounts, directories[0])
                pairs = [compare_directory(host, path, host_mounts, db_mounts, metadata, observed[path])
                    for host, path, metadata in zip(HOSTS, PATHS, directories)]
                # Re-run the complete parent observation before the final
                # identity checks. Its public report omits inode values, so
                # equality alone cannot detect a replaced WAL directory.
                require(layout.inspect_layout(root, docker, reader_factory) == proof, 'DATABASE_LAYOUT_CHANGED')
                docker.inspection_stage = 'physical_mapping_recheck'
                try:
                    require(layout.catalog(docker.run(query, timeout=30)) == first, 'DATABASE_LAYOUT_CATALOG_CHANGED')
                    require(layout.directories(docker.run(command, timeout=30), PATHS) == observed,
                        'DATABASE_LAYOUT_DIRECTORY_CHANGED')
                    require([reader.directory(path) for path in HOSTS] == directories,
                        'DATABASE_HOST_DIRECTORY_CHANGED')
                    require(reader.observer() == observer and reader.process(pid) == process,
                        'PROCESS_CHANGED_DURING_INSPECTION')
                    host_after, db_after = reader.mounts(os.getpid()), reader.mounts(pid)
                    _, volume_after = topology.compare_volume(HOST, DATA, host_after, db_after, directories[0])
                    require(volume_after == volume_mounts, 'DATABASE_MAPPING_MOUNT_CHANGED')
                    repeated = [compare_directory(host, path, host_after, db_after, metadata, observed[path])
                        for host, path, metadata in zip(HOSTS, PATHS, directories)]
                    require(repeated == pairs, 'DATABASE_MAPPING_MOUNT_CHANGED')
                except (identity.IdentityBlocked, OSError):
                    raise ActivationError('DATABASE_MAPPING_UNAVAILABLE_DURING_RECHECK') from None
            docker.inspection_stage = 'mapping_container_recheck'
            last = facts.inspected_containers(docker, before)['camera-db']
            require(identity.init_pid(last, before['camera-db']) == pid and last['HostConfig'] == db['HostConfig']
                and layout.mount_bindings(last['Mounts']) == mounts, 'DATABASE_MAPPING_CONTAINER_CHANGED')
            result = {name: pair[0] for name, pair in zip(('pgdata', 'wal'), pairs)}
        except (identity.IdentityBlocked, OSError) as exc:
            blockers = [topology.unavailable(exc)]
    docker.inspection_stage = 'mapping_input_recheck'
    for path in inputs: safe(path)
    require(checked_source(root) == revision and [sha(path) for path in inputs] == digests, 'INSPECTION_INPUT_CHANGED')
    require(inventory.key_metadata(root)[1] == key, 'KEY_METADATA_CHANGED_DURING_INSPECTION')
    require(docker.preflight() == daemon and docker.snapshot() == before, 'PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')
    return {'status': 'inspected', 'scope': SCOPE, 'inspection_completed': True, 'project': docker.project,
        'checked_revision': revision, 'mapping_readiness': 'verified' if result else 'blocked',
        'current_volume_mount_verified': proof['current_volume_mount_verified'],
        'current_storage_layout_observed': proof['active_database_storage_locations_observed'],
        'individual_host_paths_verified': result is not None, 'mapping': result, 'blockers': blockers,
        'unresolved_backup_topology': UNRESOLVED, 'readiness': 'blocked', 'production_supply_ready': False,
        'activation_allowed': False, 'next_step': 'review_complete_backup_roots_and_external_control_exclusion',
        **NO_CHANGES}


def run_inspection(root, *, privileged=False):
    if privileged: require(os.geteuid() != 0, 'RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER')
    with activation_lock(root):
        atomic_write(root/REPORT, json.dumps({'status': 'running', 'scope': SCOPE,
            'individual_host_paths_verified': False, 'activation_allowed': False, **NO_CHANGES}).encode()+b'\n')
        docker = layout.LayoutDocker(root)
        factory = (lambda: topology.AssistedMountReader(root)) if privileged else topology.MountReader
        try:
            result = inspect_mapping(root, docker, factory)
            result['privileged_directory_observer_requested'] = privileged
        except BaseException as exc:
            stage = getattr(docker, 'inspection_stage', 'accepted_source')
            if stage not in STAGES: stage = 'accepted_source'
            exc.inspection_stage = stage
            atomic_write(root/REPORT, json.dumps({'status': 'failed', 'scope': SCOPE,
                'inspection_completed': False, 'individual_host_paths_verified': False,
                'activation_allowed': False, 'production_supply_ready': False,
                'code': layout.failure_code(exc), 'failed_stage': stage, **NO_CHANGES}).encode()+b'\n')
            raise
        atomic_write(root/REPORT, (json.dumps(result, indent=2)+'\n').encode())
    return result


def main():
    root = Path(__file__).resolve().parents[3]
    privileged = sys.argv[1:] == ['--privileged-directory-metadata']
    try:
        require(len(sys.argv) == 1 or privileged, 'NO_ARGUMENTS_EXPECTED')
        result = run_inspection(root, privileged=privileged)
        print(json.dumps({**result, 'report': str(root/REPORT)}, ensure_ascii=False)); return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError,
        URLError, KeyboardInterrupt) as exc:
        stage = getattr(exc, 'inspection_stage', 'accepted_source')
        if stage not in STAGES: stage = 'accepted_source'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': layout.failure_code(exc),
            'failed_stage': stage, 'inspection_completed': False, 'individual_host_paths_verified': False,
            'activation_allowed': False, 'production_supply_ready': False, **NO_CHANGES}), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
