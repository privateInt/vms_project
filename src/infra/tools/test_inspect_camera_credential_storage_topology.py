"""Read-only volume mount proof and races; synthetic Docker/kernel records."""
import copy
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import inspect_camera_credential_storage_topology as topology
import test_inspect_camera_credential_identity as legacy

SOURCE = Path(__file__).resolve().parents[3]
TOKEN = legacy.TOKEN
HOST_PATH = '/var/lib/docker/volumes/vms-project_camera-data/_data'
TARGET = '/var/lib/postgresql/data'
NONCANONICAL_ROOTS = ('synthetic:root', '/bad//deleted/child', '/bad//other', '/../bad',
    '//bad/root', '/bad/./file', '/bad/', '/bad//deleted')


def mount(mid, parent, point, root='/', filesystem='ext4', device=(1, 1), read_only=False):
    return {'id': mid, 'parent': parent, 'point': point, 'root': root,
        'filesystem': filesystem, 'device': device, 'read_only': read_only}


def fixture(root):
    legacy.fixture(root)
    path = root/'project-manifest.json'; manifest = json.loads(path.read_text())
    name = 'src/infra/tools/inspect_camera_credential_storage_topology.py'
    target = root/name; target.write_bytes((SOURCE/name).read_bytes()); manifest['files'][name] = topology.sha(target)
    helper = root/topology.OBSERVER_SOURCE
    helper.write_bytes((SOURCE/topology.OBSERVER_SOURCE).read_bytes())
    manifest['files'][topology.OBSERVER_SOURCE] = topology.sha(helper)
    manifest.update(credential_production_process_identity_server_verified=True,
        validated_credential_production_process_identity_project_sha256=topology.ACCEPTED_IDENTITY,
        credential_production_database_mount_topology_implemented=True)
    path.write_text(json.dumps(manifest))


class FakeReader(legacy.FakeReader):
    def __init__(self):
        super().__init__()
        self.host_mounts = {1: mount(1, 0, '/')}
        self.db_mounts = {11: mount(11, 0, '/', filesystem='overlay', device=(0, 11)),
            12: mount(12, 11, TARGET, root=HOST_PATH)}
        self.directory_value = {'signature': ((1, 9000, 999, 999, 0o40700),),
            'device': (1, 1), 'mount_id': 1, 'owner_uid': 999, 'owner_gid': 999, 'mode': '0700'}
        self.directory_error = None; self.mount_error = None
        self.after_directory = lambda: None; self.after_db_mount = lambda: None
        self.directory_calls = 0; self.mount_calls = 0
    def mounts(self, pid):
        self.calls.append('mounts')
        if self.mount_error: raise self.mount_error
        if pid == 102:
            self.mount_calls += 1; result = copy.deepcopy(self.db_mounts); self.after_db_mount(); return result
        return copy.deepcopy(self.host_mounts)
    def directory(self, path):
        assert path == HOST_PATH
        self.directory_calls += 1; self.calls.append('directory')
        if self.directory_error: raise self.directory_error
        result = copy.deepcopy(self.directory_value); self.after_directory(); return result


class DatabaseMountTopologyTest(unittest.TestCase):
    read_api = legacy.ProcessIdentityTest.read_api
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'; self.root.mkdir(); fixture(self.root)
        self.docker, self.reader = legacy.FakeDocker(self.root), FakeReader()
        api = patch.object(topology.inventory, 'read_api', side_effect=self.read_api)
        api.start(); self.addCleanup(api.stop)
    def inspect(self): return topology.inspect_topology(self.root, self.docker, lambda: self.reader)
    def rejected(self, code):
        with self.assertRaisesRegex(topology.ActivationError, '^'+code+'$'): self.inspect()

    def test_verified_mount_does_not_claim_complete_backup_or_supply_readiness(self):
        value = self.inspect(); text = json.dumps(value)
        self.assertEqual(value['topology_readiness'], 'verified')
        self.assertTrue(value['volume']['database_volume_mount_verified'])
        self.assertTrue(value['volume']['host_path_without_symlinks_verified'])
        self.assertEqual(value['volume']['directory_owner_uid'], 999)
        self.assertEqual(value['volume']['filesystem_type'], 'ext4')
        self.assertEqual(value['volume']['directory_permissions'], '0700')
        self.assertEqual(value['volume']['nested_database_mount_count'], 0)
        self.assertEqual(len(value['unresolved_backup_topology']), 4)
        self.assertTrue(all(value[k] is False for k in topology.NO_CHANGES))
        self.assertFalse(value['activation_allowed']); self.assertFalse(value['production_supply_ready'])
        for secret in (TOKEN, legacy.API_ID, legacy.DB_ID, '"signature":', '"mount_id":', '"pid":'):
            self.assertNotIn(secret, text)

    def test_server_identity_acceptance_and_source_hash_required_before_docker(self):
        path = self.root/'project-manifest.json'; value = json.loads(path.read_text())
        value['credential_production_process_identity_server_verified'] = False; path.write_text(json.dumps(value))
        self.rejected('ACCEPTED_PROCESS_IDENTITY_REQUIRED'); self.assertEqual(self.docker.calls, [])
        value['credential_production_process_identity_server_verified'] = True; path.write_text(json.dumps(value))
        (self.root/'src/infra/tools/inspect_camera_credential_storage_topology.py').write_text('synthetic change')
        self.rejected('SOURCE_FILE_CHANGED'); self.assertEqual(self.docker.calls, [])

    def test_fresh_identity_blocked_prevents_host_path_access(self):
        self.reader.observer_error = topology.identity.IdentityBlocked('OBSERVER_IDENTITY_MAP_UNSUPPORTED')
        value = self.inspect(); self.assertEqual(value['blockers'], ['CURRENT_PROCESS_IDENTITY_NOT_VERIFIED'])
        self.assertEqual(self.reader.directory_calls, 0)

    def test_host_path_permission_or_absence_stays_blocked_without_repair(self):
        for error, code in ((errno.EACCES, 'HOST_STORAGE_METADATA_PERMISSION_REQUIRED'),
            (errno.ENOENT, 'HOST_STORAGE_METADATA_UNAVAILABLE')):
            self.reader = FakeReader(); self.reader.directory_error = OSError(error, TOKEN)
            value = self.inspect(); self.assertEqual(value['blockers'], [code])
            self.assertEqual(value['volume']['blocked_stage'], 'host_database_directory')
            self.assertFalse(value['volume']['database_volume_mount_verified']); self.assertNotIn(TOKEN, json.dumps(value))

    def test_mountinfo_permission_is_blocked(self):
        self.reader.mount_error = OSError(errno.EPERM, TOKEN)
        value = self.inspect()
        self.assertEqual(value['blockers'], ['HOST_STORAGE_METADATA_PERMISSION_REQUIRED'])
        self.assertNotIn('access_diagnostics', value['volume'])
        self.reader.mount_error = topology.StorageAccessDenied(errno.EPERM, 'open_filesystem_root', '/')
        value = self.inspect()
        self.assertEqual(value['volume']['blocked_stage'], 'database_mount_metadata')
        self.assertNotIn('access_diagnostics', value['volume'])

    def test_assisted_observation_repeats_full_directory_and_mount_proof(self):
        self.reader.directory_value.update(privileged_directory_observer_used=True, privileged_sender_uid_verified=True)
        value = self.inspect()
        self.assertTrue(value['volume']['database_volume_mount_verified'])
        self.assertTrue(value['volume']['privileged_sender_uid_verified'])
        self.assertEqual(self.reader.directory_calls, 2)
        self.assertFalse(value['backup_topology_verified']); self.assertFalse(value['activation_allowed'])
        self.reader.after_directory = lambda: self.reader.directory_value.update(signature=((1, 9001, 999, 999, 0o40700),))
        self.rejected('DATABASE_DIRECTORY_CHANGED_DURING_INSPECTION')

    def test_assisted_permission_unavailable_stays_blocked_and_recheck_loss_fails(self):
        self.reader.directory_error = topology.identity.IdentityBlocked('PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE')
        value = self.inspect()
        self.assertEqual(value['blockers'], ['PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE'])
        self.assertFalse(value['volume']['database_volume_mount_verified'])
        self.reader = FakeReader()
        self.reader.after_directory = lambda: setattr(self.reader, 'directory_error', topology.identity.IdentityBlocked('PRIVILEGED_DIRECTORY_PERMISSION_DENIED'))
        self.rejected('STORAGE_METADATA_UNAVAILABLE_DURING_RECHECK')

    def test_assisted_cli_is_explicit_and_root_parent_rejected_before_report(self):
        with patch.object(sys, 'argv', ['inspect', '--privileged-directory-metadata']), \
            patch.object(sys, 'stdout', io.StringIO()), \
            patch.object(topology, 'run_inspection', return_value={'scope': topology.SCOPE}) as run:
            self.assertEqual(topology.main(), 0)
            self.assertEqual(run.call_args.kwargs, {'privileged': True})
        with patch.object(os, 'geteuid', return_value=0), patch.object(topology, 'atomic_write') as write:
            with self.assertRaisesRegex(topology.ActivationError, '^RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER$'):
                topology.run_inspection(self.root, privileged=True)
            write.assert_not_called()
    def test_directory_access_context_is_bound_to_declared_path_and_never_proves_volume(self):
        parent = str(Path(HOST_PATH).parent)
        observed = {'path': parent, 'owner_uid': 0, 'owner_gid': 0, 'permissions': '0710'}
        self.reader.directory_error = topology.StorageAccessDenied(errno.EACCES,
            'open_directory_component', HOST_PATH, observed)
        value = self.inspect(); diagnostic = value['volume']['access_diagnostics']
        self.assertEqual(diagnostic['operation'], 'open_directory_component')
        self.assertEqual(diagnostic['attempted_path'], HOST_PATH)
        self.assertEqual(diagnostic['observed_directory'], observed)
        self.assertEqual(diagnostic['error'], 'EACCES')
        self.assertFalse(diagnostic['path_binding_rechecked'])
        self.assertFalse(diagnostic['permission_policy_cause_proven'])
        self.assertEqual(value['volume']['blocked_stage'], 'host_database_directory')
        self.assertEqual(value['blockers'], ['HOST_STORAGE_METADATA_PERMISSION_REQUIRED'])
        self.assertFalse(value['volume']['database_volume_mount_verified'])
        self.assertTrue(all(value[k] is False for k in topology.NO_CHANGES))
        self.assertNotIn(TOKEN, json.dumps(value))

    def test_arbitrary_os_error_attributes_are_not_reflected_into_access_context(self):
        error = OSError(errno.EACCES, TOKEN, '/'+TOKEN)
        error.operation, error.attempted_path = TOKEN, '/'+TOKEN
        error.observed = {'path': '/'+TOKEN}
        self.reader.directory_error = error
        value = self.inspect()
        self.assertNotIn('access_diagnostics', value['volume'])
        self.assertNotIn(TOKEN, json.dumps(value))

    def test_malformed_or_unrelated_denial_context_is_rejected_and_report_sanitized(self):
        parent = str(Path(HOST_PATH).parent)
        observed = {'path': parent, 'owner_uid': 0, 'owner_gid': 0, 'permissions': '0700'}
        for operation, attempted, metadata in (
            ('open_directory_component', '/unrelated/'+TOKEN, observed),
            ('open_directory_component', HOST_PATH, {**observed, 'path': '/'+TOKEN}),
            ('open_directory_component', HOST_PATH, {**observed, 'extra': TOKEN}),
            ('open_directory_component', HOST_PATH, {**observed, 'owner_uid': True}),
            ('open_directory_component', HOST_PATH, {**observed, 'permissions': TOKEN}),
            ('read_own_directory_fdinfo', parent, {**observed, 'path': HOST_PATH}),
            ('open_filesystem_root', '/', observed),
            (TOKEN, HOST_PATH, observed)):
            with self.subTest(operation=operation):
                self.reader = FakeReader()
                self.reader.directory_error = topology.StorageAccessDenied(errno.EPERM, operation, attempted, metadata)
                probe = topology.inspect_topology
                with patch.object(topology.facts, 'FactsDocker', return_value=self.docker), \
                    patch.object(topology, 'inspect_topology', side_effect=lambda root, docker: probe(root, docker, lambda: self.reader)):
                    with self.assertRaisesRegex(topology.ActivationError, '^STORAGE_ACCESS_DIAGNOSTICS_INVALID$'):
                        topology.run_inspection(self.root)
                report = self.root/topology.REPORT; text = report.read_text(); result = json.loads(text)
                self.assertEqual(report.stat().st_mode & 0o777, 0o600)
                self.assertEqual(result['failed_stage'], 'host_database_directory')
                self.assertFalse(result['inspection_completed']); self.assertNotIn(TOKEN, text)

    def test_same_device_with_wrong_root_is_rejected(self):
        self.reader.db_mounts[12]['root'] = '/synthetic/other-volume'
        self.rejected('DATABASE_MOUNT_SOURCE_MISMATCH')

    def test_wrong_device_filesystem_and_readonly_volume_are_rejected(self):
        for changes, code in (({'device': (8, 20)}, 'DATABASE_MOUNT_SOURCE_MISMATCH'),
            ({'filesystem': 'xfs'}, 'DATABASE_MOUNT_SOURCE_MISMATCH'),
            ({'read_only': True}, 'DATABASE_VOLUME_UNEXPECTED_READ_ONLY')):
            self.reader = FakeReader(); self.reader.db_mounts[12].update(changes); self.rejected(code)

    def test_fd_mount_and_stat_device_must_match_visible_host_mount(self):
        self.reader.directory_value['mount_id'] = 99; self.rejected('HOST_DIRECTORY_MOUNT_NOT_FOUND')
        self.reader.directory_value['mount_id'] = 1; self.reader.directory_value['device'] = (8, 20)
        self.rejected('HOST_DIRECTORY_MOUNT_MISMATCH')

    def test_bind_host_mount_root_is_used_instead_of_string_prefix(self):
        self.reader.host_mounts[2] = mount(2, 1, '/var/lib/docker', '/actual-base')
        self.reader.directory_value['mount_id'] = 2
        self.reader.db_mounts[12]['root'] = '/actual-base/volumes/vms-project_camera-data/_data'
        self.assertEqual(self.inspect()['topology_readiness'], 'verified')

    def test_unrelated_deleted_roots_preserve_current_database_proof_and_redaction(self):
        raw = ('1 0 1:1 / / rw - ext4 none rw\n'
            '2 1 1:1 /'+TOKEN+'//deleted /unrelated rw - ext4 none rw\n').encode()
        self.reader.host_mounts = topology.mountinfo(raw)
        self.reader.db_mounts[13] = mount(13, 11, '/etc/unrelated', '/'+TOKEN+'//deleted')
        value = self.inspect()
        self.assertEqual(value['topology_readiness'], 'verified')
        self.assertNotIn(TOKEN, json.dumps(value))
        self.assertEqual(len(self.reader.host_mounts), 2)

    def test_unrelated_root_renderings_preserve_all_records_and_database_proof(self):
        for index, name in enumerate(NONCANONICAL_ROOTS, 2):
            raw = ('1 0 1:1 / / rw - ext4 none rw\n'
                +str(index)+' 1 1:1 '+name+' /unrelated rw - ext4 none rw\n').encode()
            with self.subTest(index=index):
                self.reader = FakeReader(); self.reader.host_mounts = topology.mountinfo(raw)
                self.reader.db_mounts[13] = mount(13, 11, '/unrelated', name)
                self.assertEqual(self.inspect()['topology_readiness'], 'verified')
                self.assertEqual(len(self.reader.host_mounts), 2)

    def test_each_noncanonical_selected_root_is_rejected_before_path_arithmetic(self):
        for name in NONCANONICAL_ROOTS:
            with self.subTest(name=name, side='host'):
                self.reader = FakeReader(); self.reader.host_mounts[1]['root'] = name
                self.reader.db_mounts[12]['root'] = (Path(name)/HOST_PATH.lstrip('/')).as_posix()
                self.rejected('DATABASE_MOUNT_ROOT_NOT_CANONICAL')
            with self.subTest(name=name, side='database'):
                self.reader = FakeReader(); self.reader.db_mounts[12]['root'] = name
                self.rejected('DATABASE_MOUNT_ROOT_NOT_CANONICAL')

    def test_noncanonical_roots_cannot_hide_parent_or_nested_mounts(self):
        for name in NONCANONICAL_ROOTS:
            with self.subTest(name=name):
                self.reader = FakeReader()
                self.reader.db_mounts[13] = mount(13, 11, '/var/lib/postgresql', name)
                self.rejected('DATABASE_VOLUME_MOUNT_NOT_VISIBLE')
                self.reader = FakeReader()
                self.reader.db_mounts[13] = mount(13, 12, TARGET+'/pg_wal', name)
                self.assertEqual(self.inspect()['blockers'], ['DATABASE_NESTED_MOUNTS_REQUIRE_REVIEW'])

    def test_selected_deleted_host_or_database_root_is_never_normalized_into_proof(self):
        self.reader.host_mounts[1]['root'] = '/host//deleted'
        self.reader.db_mounts[12]['root'] = '/host/deleted'+HOST_PATH
        self.rejected('DATABASE_MOUNT_ROOT_NOT_CANONICAL')
        self.reader = FakeReader(); self.reader.db_mounts[12]['root'] = HOST_PATH+'//deleted'
        self.rejected('DATABASE_MOUNT_ROOT_NOT_CANONICAL')

    def test_deleted_root_overmount_still_hides_old_database_child(self):
        self.reader.db_mounts[13] = mount(13, 11, '/var/lib/postgresql', '/hidden//deleted')
        self.rejected('DATABASE_VOLUME_MOUNT_NOT_VISIBLE')

    def test_deleted_root_nested_mount_still_requires_backup_review(self):
        self.reader.db_mounts[13] = mount(13, 12, TARGET+'/pg_wal', '/wal//deleted')
        self.assertEqual(self.inspect()['blockers'], ['DATABASE_NESTED_MOUNTS_REQUIRE_REVIEW'])

    def test_unsupported_filesystem_and_nested_mount_require_backup_review(self):
        self.reader.host_mounts[1]['filesystem'] = 'nfs'; self.reader.db_mounts[12]['filesystem'] = 'nfs'
        self.assertEqual(self.inspect()['blockers'], ['DATABASE_FILESYSTEM_REVIEW_REQUIRED'])
        self.reader = FakeReader(); self.reader.db_mounts[13] = mount(13, 12, TARGET+'/pg_wal')
        self.assertEqual(self.inspect()['blockers'], ['DATABASE_NESTED_MOUNTS_REQUIRE_REVIEW'])

    def test_overmounted_parent_hides_old_database_child(self):
        self.reader.db_mounts[13] = mount(13, 11, '/var/lib/postgresql', filesystem='tmpfs', device=(0, 20))
        self.rejected('DATABASE_VOLUME_MOUNT_NOT_VISIBLE')

    def test_directory_rename_or_inode_change_is_rejected(self):
        self.reader.after_directory = lambda: self.reader.directory_value.update(signature=((1, 9999, 999, 999, 0o40700),))
        self.rejected('DATABASE_DIRECTORY_CHANGED_DURING_INSPECTION')

    def test_selected_mount_id_replacement_is_rejected_even_when_source_matches(self):
        def change():
            value = self.reader.db_mounts.pop(12, self.reader.db_mounts.get(13))
            self.reader.db_mounts[13] = {**value, 'id': 13}
        self.reader.after_db_mount = change; self.rejected('DATABASE_MOUNT_CHANGED_DURING_INSPECTION')

    def test_permission_loss_during_recheck_cannot_leave_success(self):
        self.reader.after_directory = lambda: setattr(self.reader, 'directory_error', OSError(errno.EACCES, TOKEN))
        self.rejected('STORAGE_METADATA_UNAVAILABLE_DURING_RECHECK')

    def test_process_identity_drift_during_mount_read_is_rejected(self):
        self.reader.after_directory = lambda: self.reader.records[102].update(signature=(1, 5102, 99999))
        self.rejected('PROCESS_CHANGED_DURING_INSPECTION')

    def test_container_pid_recreation_during_mount_read_is_rejected(self):
        self.reader.after_directory = lambda: self.docker.db['State'].update(Pid=9999)
        self.rejected('DATABASE_CONTAINER_CHANGED_DURING_INSPECTION')

    def test_source_env_key_and_volume_drift_rejected(self):
        for name, code in (('.env', 'INSPECTION_INPUT_CHANGED'),
            (topology.inventory.KEY, 'KEY_METADATA_CHANGED_DURING_INSPECTION'),
            ('src/infra/tools/inspect_camera_credential_storage_topology.py', 'SOURCE_FILE_CHANGED')):
            path = self.root/name; original = path.read_bytes(); self.reader = FakeReader()
            self.reader.after_directory = lambda: path.write_bytes(b'SYNTHETIC_CHANGED')
            self.rejected(code); path.write_bytes(original)
        self.reader = FakeReader()
        self.reader.after_directory = lambda: self.docker.db['Mounts'][0].update(Source='/synthetic/other')
        self.rejected('DATABASE_CONTAINER_CHANGED_DURING_INSPECTION')

    def test_only_previously_accepted_readonly_sql_exec_is_used(self):
        self.inspect()
        commands = [c for c in self.docker.calls if isinstance(c, list) and c[0] == 'exec']
        self.assertEqual(commands, [['exec', legacy.DB_ID, *topology.inventory.SQL_ARGS, topology.inventory.READ_ONLY_SQL]])

    def test_private_report_preserves_previous_reports_and_replaces_stale_success(self):
        protected = {}
        for name in (topology.identity.REPORT, topology.facts.REPORT, topology.inventory.REPORT):
            path = self.root/name; path.write_bytes(b'SYNTHETIC_OLD_REPORT')
            protected[path] = (path.read_bytes(), path.stat().st_mtime_ns)
        probe = topology.inspect_topology
        with patch.object(topology.facts, 'FactsDocker', return_value=self.docker), \
            patch.object(topology, 'inspect_topology', side_effect=lambda root, docker: probe(root, docker, lambda: self.reader)):
            self.assertEqual(topology.run_inspection(self.root)['topology_readiness'], 'verified')
        with patch.object(topology.facts, 'FactsDocker', return_value=self.docker), \
            patch.object(topology, 'inspect_topology', side_effect=topology.ActivationError('BAD_RESULT: '+TOKEN)):
            with self.assertRaises(topology.ActivationError): topology.run_inspection(self.root)
        p = self.root/topology.REPORT; text = p.read_text(); self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(text)['status'], 'failed'); self.assertNotIn(TOKEN, text)
        for path, before in protected.items(): self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_empty_root_failure_reports_field_and_stage_without_raw_path(self):
        raw = ('1 0 1:1  / rw - ext4 '+TOKEN+' rw\n').encode()
        try: topology.mountinfo(raw)
        except topology.ActivationError as exc: self.reader.mount_error = exc
        else: self.fail('invalid root was accepted')
        probe = topology.inspect_topology
        with patch.object(topology.facts, 'FactsDocker', return_value=self.docker), \
            patch.object(topology, 'inspect_topology', side_effect=lambda root, docker: probe(root, docker, lambda: self.reader)):
            with self.assertRaisesRegex(topology.ActivationError, '^MOUNTINFO_ROOT_PATH_INVALID$'):
                topology.run_inspection(self.root)
        text = (self.root/topology.REPORT).read_text(); value = json.loads(text)
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['code'], 'MOUNTINFO_ROOT_PATH_INVALID')
        self.assertEqual(value['failed_stage'], 'database_mount_metadata')
        self.assertFalse(value['inspection_completed']); self.assertFalse(value['activation_allowed'])
        self.assertNotIn(TOKEN, text)

    def test_diagnostics_read_only_self_mount_metadata_and_preserve_all_files(self):
        self.reader.fd = -1
        self.reader.host_mounts = topology.mountinfo(('1 0 1:1 / / rw - ext4 none rw\n'
            '2 1 1:1 synthetic:'+TOKEN+' /other rw - ext4 none rw\n'
            '3 1 1:1 /'+TOKEN+'/../parent /third rw - ext4 none rw\n').encode())
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        def forbidden(*args, **kwargs): raise AssertionError('diagnostic must only read source and self mountinfo')
        with patch.object(topology, 'MountReader', return_value=self.reader), \
            patch.object(os, 'readlink', return_value='777') as link, \
            patch.object(topology.facts, 'FactsDocker', side_effect=forbidden), \
            patch.object(topology.inventory, 'key_metadata', side_effect=forbidden), \
            patch.object(topology.inventory, 'read_api', side_effect=forbidden), \
            patch.object(topology, 'activation_lock', side_effect=forbidden), \
            patch.object(topology, 'atomic_write', side_effect=forbidden):
            value = topology.run_mountinfo_diagnostics(self.root)
        link.assert_called_once_with('self', dir_fd=-1)
        self.assertEqual(self.reader.calls, ['mounts'])
        self.assertEqual(value['mount_count'], 3)
        self.assertEqual(value['root_shapes']['relative_or_synthetic'], 1)
        self.assertEqual(value['root_shapes']['parent_component'], 1)
        self.assertTrue(value['diagnostic_only']); self.assertFalse(value['database_volume_mount_verified'])
        self.assertFalse(value['report_modified']); self.assertFalse(value['raw_paths_emitted'])
        self.assertNotIn(TOKEN, json.dumps(value)); self.assertTrue(all(value[k] is False for k in topology.NO_CHANGES))
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_diagnostic_cli_dispatch_and_unknown_arguments_do_not_run_volume_inspection(self):
        value = {'scope': topology.DIAGNOSTIC_SCOPE, 'diagnostic_only': True, 'root_shapes': {}}
        with patch.object(sys, 'argv', ['inspect', '--mountinfo-diagnostics']), \
            patch.object(sys, 'stdout', io.StringIO()) as output, \
            patch.object(topology, 'run_mountinfo_diagnostics', return_value=value) as diagnostic, \
            patch.object(topology, 'run_inspection') as normal:
            self.assertEqual(topology.main(), 0); diagnostic.assert_called_once(); normal.assert_not_called()
            self.assertNotIn('report', json.loads(output.getvalue()))
        with patch.object(sys, 'argv', ['inspect', '--mountinfo-diagnostics', '--apply']), \
            patch.object(sys, 'stderr', io.StringIO()), \
            patch.object(topology, 'run_mountinfo_diagnostics') as diagnostic, \
            patch.object(topology, 'run_inspection') as normal:
            self.assertEqual(topology.main(), 1); diagnostic.assert_not_called(); normal.assert_not_called()

    def test_diagnostic_cli_failure_is_sanitized_and_does_not_write_report(self):
        self.reader.enter_error = OSError(errno.EACCES, TOKEN)
        with patch.object(sys, 'argv', ['inspect', '--mountinfo-diagnostics']), \
            patch.object(sys, 'stderr', io.StringIO()) as output, \
            patch.object(topology, 'checked_source', return_value='a'*64), \
            patch.object(topology, 'MountReader', return_value=self.reader), \
            patch.object(topology, 'atomic_write') as written:
            self.assertEqual(topology.main(), 1); written.assert_not_called()
        value = json.loads(output.getvalue())
        self.assertEqual(value['scope'], topology.DIAGNOSTIC_SCOPE)
        self.assertEqual(value['failed_stage'], 'database_mount_metadata')
        self.assertFalse(value['report_modified']); self.assertFalse(value['inspection_completed'])
        self.assertNotIn(TOKEN, output.getvalue())


class MountMetadataTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux') and hasattr(os, 'O_PATH'), 'Linux O_PATH required')
    def test_native_denied_child_reports_open_parent_metadata_and_closes_all_descriptors(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)/'parent'; parent.mkdir(); parent.chmod(0o710)
            child = parent/'denied'; child.mkdir(); (child/'SYNTHETIC_SECRET').write_text(TOKEN)
            original, descriptors, calls = os.open, [], []
            def denied(path, flags, *args, **kwargs):
                calls.append((str(path), flags))
                if str(path) == 'denied': raise OSError(errno.EACCES, TOKEN, TOKEN)
                fd = original(path, flags, *args, **kwargs); descriptors.append(fd); return fd
            with patch.object(os, 'open', side_effect=denied), \
                patch.object(os, 'listdir', side_effect=AssertionError('listing forbidden')), \
                patch.object(os, 'scandir', side_effect=AssertionError('listing forbidden')), \
                patch.object(os, 'chmod', side_effect=AssertionError('permission change forbidden')), \
                patch.object(os, 'chown', side_effect=AssertionError('owner change forbidden')), \
                patch.object(os, 'read', side_effect=AssertionError('content read forbidden')):
                with self.assertRaises(topology.StorageAccessDenied) as caught:
                    topology.MountReader().directory(str(child))
            value = topology.access_diagnostics(caught.exception, str(child))
            self.assertEqual(value['observed_directory'], {'path': str(parent),
                'owner_uid': parent.stat().st_uid, 'owner_gid': parent.stat().st_gid, 'permissions': '0710'})
            self.assertEqual(value['attempted_path'], str(child)); self.assertEqual(value['error'], 'EACCES')
            self.assertNotIn(TOKEN, str(caught.exception)+json.dumps(value))
            self.assertTrue(all(flags & os.O_PATH and flags & os.O_NOFOLLOW for _, flags in calls))
            self.assertNotIn('SYNTHETIC_SECRET', [name for name, _ in calls])
            for fd in descriptors:
                with self.assertRaises(OSError) as closed: os.fstat(fd)
                self.assertEqual(closed.exception.errno, errno.EBADF)

    @unittest.skipUnless(sys.platform.startswith('linux') and hasattr(os, 'O_PATH'), 'Linux O_PATH required')
    def test_native_root_denial_has_no_invented_parent_metadata(self):
        with patch.object(os, 'open', side_effect=OSError(errno.EPERM, TOKEN)) as opened, \
            patch.object(os, 'fstat') as metadata:
            with self.assertRaises(topology.StorageAccessDenied) as caught:
                topology.MountReader().directory(HOST_PATH)
        opened.assert_called_once(); metadata.assert_not_called()
        value = topology.access_diagnostics(caught.exception, HOST_PATH)
        self.assertEqual(value['operation'], 'open_filesystem_root')
        self.assertEqual(value['attempted_path'], '/'); self.assertEqual(value['error'], 'EPERM')
        self.assertIsNone(value['observed_directory']); self.assertNotIn(TOKEN, json.dumps(value))

    @unittest.skipUnless(sys.platform.startswith('linux') and hasattr(os, 'O_PATH'), 'Linux O_PATH required')
    def test_native_intermediate_denial_never_opens_remaining_path_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary); target = parent/'denied'/'remaining'/'database'
            original, calls = os.open, []
            def denied(path, flags, *args, **kwargs):
                calls.append(str(path))
                if str(path) == 'denied': raise OSError(errno.EPERM, TOKEN)
                return original(path, flags, *args, **kwargs)
            with patch.object(os, 'open', side_effect=denied):
                with self.assertRaises(topology.StorageAccessDenied) as caught:
                    topology.MountReader().directory(str(target))
            value = topology.access_diagnostics(caught.exception, str(target))
            self.assertEqual(value['attempted_path'], str(parent/'denied'))
            self.assertEqual(value['observed_directory']['path'], str(parent))
            self.assertEqual(value['error'], 'EPERM')
            self.assertNotIn('remaining', calls); self.assertNotIn('database', calls)

    @unittest.skipUnless(sys.platform.startswith('linux') and hasattr(os, 'O_PATH'), 'Linux O_PATH required')
    def test_native_fdinfo_denial_is_distinct_from_directory_component_denial(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'database'; path.mkdir()
            original, descriptors = os.open, []
            def track(*args, **kwargs):
                fd = original(*args, **kwargs); descriptors.append(fd); return fd
            with patch.object(os, 'open', side_effect=track), \
                patch.object(topology.MountReader, 'descriptor_mount', side_effect=OSError(errno.EPERM, TOKEN)):
                with self.assertRaises(topology.StorageAccessDenied) as caught:
                    topology.MountReader().directory(str(path))
            value = topology.access_diagnostics(caught.exception, str(path))
            self.assertEqual(value['operation'], 'read_own_directory_fdinfo')
            self.assertEqual(value['observed_directory']['path'], str(path))
            self.assertEqual(value['observed_directory']['owner_uid'], path.stat().st_uid)
            self.assertFalse(value['permission_policy_cause_proven']); self.assertNotIn(TOKEN, json.dumps(value))
            for fd in descriptors:
                with self.assertRaises(OSError) as closed: os.fstat(fd)
                self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_mountinfo_discards_sources_options_and_unrelated_names(self):
        raw = ('1 0 8:1 / / rw,relatime shared:2 - ext4 '+TOKEN+' rw\n'
            '2 1 8:1 /space\\040name /mount\\040name ro future:unknown - ext4 none ro\n').encode()
        value = topology.mountinfo(raw)
        self.assertEqual(value[2]['root'], '/space name'); self.assertNotIn(TOKEN, json.dumps(value))
        self.assertTrue(value[2]['read_only'])

    def test_kernel_deleted_root_rendering_is_retained_without_path_normalization(self):
        raw = (b'1 0 8:1 / / rw - ext4 none rw\n'
            b'2 1 8:1 /old\\040root//deleted /old-mount rw - ext4 none rw\n'
            b'3 1 8:1 /literal\\134040//deleted /literal-mount rw - ext4 none rw\n')
        value = topology.mountinfo(raw)
        self.assertEqual(set(value), {1, 2, 3})
        self.assertEqual(value[2]['root'], '/old root//deleted')
        self.assertEqual(value[3]['root'], '/literal\\040//deleted')
        self.assertEqual(topology.visible_mount('/old-mount/file', value)['id'], 2)

    def test_only_ascii_space_and_lf_delimit_kernel_paths(self):
        for character in ('\r', '\v', '\f', '\x85', '\u00a0', '\u2028', '\u2029', '\udcff'):
            with self.subTest(character=ascii(character)):
                name = '/literal'+character+'name'
                raw = ('1 0 8:1 / / rw - ext4 none rw\n'
                    '2 1 8:1 '+name+' '+name+' rw - ext4 none rw\n').encode('utf-8', 'surrogateescape')
                value = topology.mountinfo(raw)
                self.assertEqual(len(value), 2)
                self.assertEqual(value[2]['root'], name); self.assertEqual(value[2]['point'], name)

    def test_invalid_empty_root_mountpoint_and_escape_have_fixed_distinct_codes(self):
        for root, point, code in (('', '/', 'MOUNTINFO_ROOT_PATH_INVALID'),
            ('/', '/'+TOKEN+'//deleted', 'MOUNTINFO_MOUNTPOINT_PATH_INVALID'),
            ('/unknown\\001', '/', 'MOUNTINFO_PATH_ESCAPE_INVALID')):
            with self.subTest(code=code):
                raw = ('1 0 8:1 '+root+' '+point+' rw - ext4 none rw\n').encode()
                with self.assertRaisesRegex(topology.ActivationError, '^'+code+'$') as caught:
                    topology.mountinfo(raw)
                self.assertNotIn(TOKEN, str(caught.exception))

    def test_root_metadata_is_retained_without_a_lookup_path_requirement(self):
        for name in NONCANONICAL_ROOTS:
            with self.subTest(name=name):
                records = topology.mountinfo(('1 0 8:1 '+name+' / rw - ext4 none rw\n').encode())
                self.assertEqual(records[1]['root'], name)
                self.assertFalse(topology.canonical_mount_path(records[1]['root']))

    def test_root_shape_summary_uses_fixed_keys_and_counts_without_raw_names(self):
        names = ('/', '/name//deleted', TOKEN, '//prefix', '/a/../b', '/a/./b', '/a//b', '/a/')
        records = {i: mount(i, 0, '/', name) for i, name in enumerate(names, 1)}
        value = topology.root_shape_counts(records)
        self.assertEqual(set(value), set(topology.ROOT_SHAPES))
        self.assertEqual(sum(value.values()), len(records))
        self.assertTrue(all(value[k] == 1 for k in topology.ROOT_SHAPES if k != 'other_noncanonical'))
        self.assertEqual(value['other_noncanonical'], 0); self.assertNotIn(TOKEN, json.dumps(value))

    def test_malformed_duplicate_and_oversized_mountinfo_rejected(self):
        body = b'1 0 8:1 / / rw - ext4 none rw\n'
        for raw in (b'', b'bad', body+body, body.replace(b'8:1', b'bad'), body.replace(b' rw -', b' rw,ro -'),
            body.replace(b' / / ', b'  / '), body.replace(b' / / ', b' /null\x00 / '),
            body+b'2 1 8:1 /unknown\\001 /a rw - ext4 none rw\n', b'x'*1048577):
            with self.assertRaises(topology.ActivationError): topology.mountinfo(raw)

    def test_stacked_root_and_parent_mounts_choose_visible_children(self):
        values = {1: mount(1, 0, '/'), 2: mount(2, 1, '/', filesystem='overlay'),
            3: mount(3, 2, '/data'), 4: mount(4, 2, '/data/deep'),
            5: mount(5, 3, '/data', root='/new'), 6: mount(6, 5, '/data/deep', root='/nested')}
        self.assertEqual(topology.visible_mount('/data/deep/file', values)['id'], 6)
        del values[6]; self.assertEqual(topology.visible_mount('/data/deep/file', values)['id'], 5)

    def test_ambiguous_root_and_same_parent_siblings_are_rejected(self):
        with self.assertRaises(topology.ActivationError): topology.visible_mount('/data', {1: mount(1, 0, '/'), 2: mount(2, 0, '/')})
        with self.assertRaises(topology.ActivationError): topology.visible_mount('/data', {1: mount(1, 0, '/'), 2: mount(2, 1, '/data'), 3: mount(3, 1, '/data')})

    def test_fdinfo_requires_unique_mount_id_and_matching_inode(self):
        raw = b'pos:\t0\nflags:\t010000000\nmnt_id:\t123\nino:\t456\n'
        self.assertEqual(topology.fd_mount(raw, 456), 123)
        for body in (raw+b'mnt_id: 123\n', raw.replace(b'456', b'457'), raw.replace(b'123', b'0'), b'flags: 1\n'):
            with self.assertRaises(topology.ActivationError): topology.fd_mount(body, 456)

    def test_proc_metadata_rejects_environment_and_process_args_before_open(self):
        with patch.object(os, 'open') as opened:
            for name in ('environ', 'cmdline', 'mem', 'root', 'fd/1', '../mountinfo'):
                with self.assertRaises(topology.ActivationError): topology.MountReader().proc_metadata(-1, name, 4096)
            opened.assert_not_called()

    def test_proc_metadata_requires_procfs_and_bounded_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'mountinfo').write_bytes(b'x'*1048577)
            fd = os.open(root, os.O_RDONLY|os.O_DIRECTORY)
            try:
                with self.assertRaisesRegex(topology.ActivationError, '^MOUNT_METADATA_FILE_INVALID$'):
                    topology.MountReader().proc_metadata(fd, 'mountinfo', topology.MAX_MOUNTINFO)
                with patch.object(topology.identity, 'procfs_fd', return_value=True), \
                    self.assertRaisesRegex(topology.ActivationError, '^MOUNT_METADATA_FILE_INVALID$'):
                    topology.MountReader().proc_metadata(fd, 'mountinfo', topology.MAX_MOUNTINFO)
            finally: os.close(fd)

    @unittest.skipUnless(sys.platform.startswith('linux') and hasattr(os, 'O_PATH'), 'Linux O_PATH required')
    def test_native_directory_and_fdinfo_without_contents_or_following_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); actual = root/'database'; actual.mkdir(); (actual/'SYNTHETIC_SECRET').write_bytes(TOKEN.encode())
            alias = root/'alias'; alias.symlink_to(actual, target_is_directory=True)
            opened = []; original = os.open
            def track(path, flags, *args, **kwargs):
                opened.append((str(path), flags)); return original(path, flags, *args, **kwargs)
            with topology.MountReader() as reader, patch.object(os, 'open', side_effect=track), \
                patch.object(os, 'listdir', side_effect=AssertionError('directory listing forbidden')):
                value = reader.directory(str(actual)); self.assertEqual(value['owner_uid'], os.getuid())
                host = reader.mounts(int(os.readlink('self', dir_fd=reader.fd)))
                self.assertIn(value['mount_id'], host)
                self.assertEqual(topology.visible_mount(str(actual), host)['id'], value['mount_id'])
                with self.assertRaisesRegex(topology.ActivationError, '^DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED$'):
                    reader.directory(str(alias))
                with self.assertRaisesRegex(topology.ActivationError, '^DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED$'):
                    reader.directory(str(alias/'subdirectory'))
            self.assertNotIn('SYNTHETIC_SECRET', [name for name, _ in opened])
            self.assertTrue(all(not flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC) for _, flags in opened))
            self.assertTrue(all(flags & os.O_PATH for name, flags in opened if name in ('/', 'database')))


if __name__ == '__main__': unittest.main()
