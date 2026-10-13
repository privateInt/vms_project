"""Read-only storage location observations, command boundaries and drift."""
import builtins
import copy
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import inspect_camera_database_storage_layout as layout
import test_inspect_camera_credential_storage_topology as legacy

SOURCE = Path(__file__).resolve().parents[3]
DATA = '/var/lib/postgresql/data'
DB_ID = legacy.legacy.DB_ID


def sample():
    return {'database': 'vms_camera', 'session_user': 'camera_admin', 'current_user': 'camera_admin',
        'transaction_read_only': True, 'server_version_num': 170011,
        'postmaster_started': '2026-10-08 01:02:03.456789+00', 'data_directory': DATA,
        'config_file': DATA+'/postgresql.conf', 'hba_file': DATA+'/pg_hba.conf',
        'ident_file': DATA+'/pg_ident.conf', 'archive_mode': 'off', 'tablespace_count': 2,
        'tablespaces': [{'oid': 1663, 'location': ''}, {'oid': 1664, 'location': ''}]}


def record(path, *, resolved=None, symlink=False, inode=9000):
    first = f'1 {inode} {0o120777 if symlink else 0o40700:x} 999 999'.encode()
    target = f'1 {inode+1 if symlink else inode} {0o40700:x} 999 999'.encode()
    canonical = (resolved or path).encode()
    return [first, canonical, target, first, canonical]


def wire(paths, changes=None):
    changes = changes or {}
    fields = [b'camera_db_directory_metadata_v1', b'999', b'999']
    for path in paths: fields.extend(record(path, **changes.get(path, {})))
    return b'\0'.join([*fields, b''])


def fixture(root):
    legacy.fixture(root)
    path = root/'project-manifest.json'; manifest = json.loads(path.read_text())
    target = root/layout.SOURCE; target.write_bytes((SOURCE/layout.SOURCE).read_bytes())
    manifest['files'][layout.SOURCE] = layout.sha(target)
    manifest.update(credential_production_database_mount_topology_server_verified=True,
        validated_credential_production_directory_observer_project_sha256=layout.ACCEPTED_VOLUME,
        camera_database_storage_layout_implemented=True)
    path.write_text(json.dumps(manifest))


class FakeDocker(legacy.legacy.FakeDocker):
    def __init__(self, root):
        super().__init__(root)
        # Real camera-db has a data volume, three secrets and the init bind.
        self.db['Mounts'] += [{'Type': 'bind', 'Source': '/synthetic/'+name,
            'Destination': destination, 'Mode': 'ro', 'RW': False, 'Propagation': 'rprivate'}
            for name, destination in [('admin', '/run/secrets/camera_admin_password'),
                ('migration', '/run/secrets/camera_migration_password'),
                ('runtime', '/run/secrets/camera_runtime_password'),
                ('init', '/docker-entrypoint-initdb.d/10-camera.sh')]]
        self.db_inspects = 0; self.inspect_transform = lambda value: value
        self.catalog_value = sample(); self.metadata_changes = {}
        self.catalog_calls = 0; self.metadata_calls = 0
        self.after_catalog = lambda: None; self.after_metadata = lambda: None
        self.catalog_error = None; self.metadata_error = None
        self.metadata_transform = lambda v: v
    def run(self, args, **kwargs):
        if args == ['exec', '--user', '999:999', DB_ID, *layout.inventory.SQL_ARGS, layout.CATALOG_SQL]:
            self.calls.append(args); self.catalog_calls += 1
            if self.catalog_error: raise self.catalog_error
            value = json.dumps(self.catalog_value).encode(); self.after_catalog(); return value
        if args == layout.metadata_args(DB_ID, getattr(self, 'layout_paths', ())):
            self.calls.append(args); self.metadata_calls += 1
            if self.metadata_error: raise self.metadata_error
            value = self.metadata_transform(wire(self.layout_paths, self.metadata_changes))
            self.after_metadata(); return value
        raw = super().run(args, **kwargs)
        if args == ['inspect', DB_ID]:
            self.db_inspects += 1
            return json.dumps(self.inspect_transform(json.loads(raw))).encode()
        return raw


class CatalogTest(unittest.TestCase):
    def parse(self, value): return layout.catalog(json.dumps(value).encode())
    def reject(self, value, code):
        with self.assertRaisesRegex(layout.ActivationError, '^'+code+'$'): self.parse(value)
    def test_fixed_catalog_is_read_only_and_does_not_read_files_or_secrets(self):
        self.assertEqual(self.parse(sample()), sample())
        sql = layout.CATALOG_SQL.lower()
        self.assertTrue(sql.startswith('begin isolation level repeatable read read only;'))
        self.assertTrue(sql.endswith('commit;'))
        for forbidden in ('pg_read_file', 'pg_ls_', 'pg_stat_file', 'pg_authid', 'archive_command',
            'pg_backup_start', 'pg_backup_stop', 'pg_switch_wal', 'pg_reload_conf', 'alter ', 'update ', 'insert ', 'delete '):
            self.assertNotIn(forbidden, sql)
        self.assertIn('limit 129', sql); self.assertIn('pg_tablespace_location(oid)', sql)
    def test_session_role_database_and_read_only_guard(self):
        for field, value in (('database', 'postgres'), ('session_user', 'postgres'),
            ('current_user', 'camera_runtime'), ('transaction_read_only', False), ('transaction_read_only', 1)):
            self.reject({**sample(), field: value}, 'DATABASE_LAYOUT_READ_ONLY_SESSION_REQUIRED')
    def test_version_major_and_type_guard(self):
        for version in (True, '170011', 160011, 180000):
            self.reject({**sample(), 'server_version_num': version}, 'DATABASE_LAYOUT_SERVER_VERSION_UNSUPPORTED')
    def test_json_shape_duplicate_fields_and_output_limit(self):
        for raw in (b'[]', b'{', b'{}', b'{}\n{}', b'\xff', b' '*1048577,
            b'{"database":1,"database":2}'):
            with self.assertRaisesRegex(layout.ActivationError, '^DATABASE_LAYOUT_CATALOG_INVALID$'): layout.catalog(raw)
        self.reject({**sample(), 'secret': legacy.TOKEN}, 'DATABASE_LAYOUT_CATALOG_INVALID')
    def test_path_controls_normalization_relative_and_limit_rejected(self):
        for path in ('../data', '/data/../secret', '//data', '/data//more', '/data/./more', '/data/',
            '/data\n', '/data\x00', '/data\\more', '/'+'x'*4096):
            self.reject({**sample(), 'data_directory': path}, 'DATABASE_LAYOUT_PATH_INVALID')
    def test_custom_tablespaces_are_enumerated_without_user_names(self):
        value = sample(); value['tablespace_count'] = 3
        value['tablespaces'].append({'oid': 18000, 'location': '/external/tablespace'})
        self.assertEqual(layout.metadata_paths(self.parse(value)), (DATA, DATA+'/pg_wal', '/external/tablespace'))
    def test_tablespace_count_limit_default_oids_and_uniqueness(self):
        for count in (True, 1, 3, 129):
            self.reject({**sample(), 'tablespace_count': count}, 'DATABASE_LAYOUT_TABLESPACE_LIMIT_OR_COUNT_INVALID')
        for rows in ([{'oid': 1663, 'location': ''}]*2, list(reversed(sample()['tablespaces'])),
            [{'oid': 1663, 'location': ''}, {'oid': 18000, 'location': '/extra'}]):
            self.reject({**sample(), 'tablespaces': rows}, 'DATABASE_LAYOUT_TABLESPACE_INVALID')
    def test_builtin_location_and_relative_in_place_tablespace_rejected(self):
        value = sample(); value['tablespaces'][0]['location'] = '/fake'
        self.reject(value, 'DATABASE_LAYOUT_BUILTIN_TABLESPACE_INVALID')
        value = sample(); value['tablespace_count'] = 3
        value['tablespaces'].append({'oid': 18000, 'location': 'pg_tblspc/18000'})
        self.reject(value, 'DATABASE_LAYOUT_PATH_INVALID')
    def test_oid_type_and_unreviewed_fields_rejected(self):
        for row in ({'oid': True, 'location': ''}, {'oid': -1, 'location': ''},
            {'oid': 1663, 'location': '', 'name': legacy.TOKEN}):
            value = sample(); value['tablespaces'][0] = row
            self.reject(value, 'DATABASE_LAYOUT_TABLESPACE_INVALID')
    def test_uncast_postgresql_oid_json_strings_reproduce_catalog_rejection(self):
        value = sample()
        # PostgreSQL17 json_build_object with an uncast oid produces strings.
        # The former SQL hit this guard before any directory metadata command.
        value['tablespaces'] = [{'oid': '1663', 'location': ''}, {'oid': '1664', 'location': ''}]
        self.reject(value, 'DATABASE_LAYOUT_TABLESPACE_INVALID')
    def test_unsigned_oid_above_signed_int4_limit_is_preserved(self):
        value = sample(); value['tablespace_count'] = 3
        value['tablespaces'].append({'oid': 4294967294, 'location': '/external/tablespace'})
        parsed = self.parse(value)
        self.assertEqual(parsed['tablespaces'][-1]['oid'], 4294967294)
        self.assertEqual(layout.metadata_paths(parsed)[-1], '/external/tablespace')
    def test_oid_strings_booleans_fractional_and_out_of_range_rejected(self):
        for oid in ('18000', True, 18000.0, 0, -1, 4294967295, 4294967296):
            value = sample(); value['tablespace_count'] = 3
            value['tablespaces'].append({'oid': oid, 'location': '/external/tablespace'})
            self.reject(value, 'DATABASE_LAYOUT_TABLESPACE_INVALID')
    def test_metadata_paths_deduplicate_shared_locations(self):
        value = sample(); value['tablespace_count'] = 4
        value['tablespaces'] += [{'oid': x, 'location': '/shared'} for x in (18000, 18001)]
        self.assertEqual(layout.metadata_paths(self.parse(value)), (DATA, DATA+'/pg_wal', '/shared'))


class MetadataTest(unittest.TestCase):
    def setUp(self): self.paths = (DATA, DATA+'/pg_wal')
    def reject(self, raw, code):
        with self.assertRaisesRegex(layout.ActivationError, '^'+code+'$'): layout.directories(raw, self.paths)
    def test_external_wal_symlink_resolves_to_directory(self):
        result = layout.directories(wire(self.paths, {self.paths[1]: {'symlink': True, 'resolved': '/external/wal'}}), self.paths)
        self.assertTrue(result[self.paths[1]]['leaf_is_symlink'])
        self.assertEqual(result[self.paths[1]]['resolved_path'], '/external/wal')
    def test_wrong_execution_uid_or_gid_rejected(self):
        for index in (1, 2):
            fields = wire(self.paths).split(b'\0'); fields[index] = b'0'
            self.reject(b'\0'.join(fields), 'DATABASE_LAYOUT_EXECUTION_IDENTITY_MISMATCH')
    def test_wire_boundaries_extra_partial_and_oversize_rejected(self):
        value = wire(self.paths)
        for raw in (value[:-1], value+b'\0', value[:-10], value.replace(b'metadata_v1', b'metadata_v2'), b'x'*1048577):
            self.reject(raw, 'DATABASE_LAYOUT_METADATA_INVALID')
    def test_symlink_target_controls_preserved_then_rejected(self):
        for path in ('/external\n', '/external/../hidden', 'relative', '/external//wal', '/external\x00'):
            self.reject(wire(self.paths, {self.paths[1]: {'resolved': path}}),
                'DATABASE_LAYOUT_METADATA_INVALID' if '\x00' in path else 'DATABASE_LAYOUT_PATH_INVALID')
    def test_leaf_and_resolution_changes_rejected(self):
        for index, value in ((6, b'1 9999 41c0 999 999'), (7, b'/other')):
            fields = wire(self.paths).split(b'\0'); fields[index] = value
            self.reject(b'\0'.join(fields), 'DATABASE_LAYOUT_DIRECTORY_CHANGED')
    def test_regular_file_and_non_directory_target_rejected(self):
        for index in (3, 5):
            fields = wire(self.paths).split(b'\0'); fields[index] = b'1 9000 81c0 999 999'
            if index == 3: fields[6] = fields[3]
            self.reject(b'\0'.join(fields), 'DATABASE_LAYOUT_DIRECTORY_REQUIRED')
    def test_malformed_stat_values_rejected(self):
        for value in (b'1 0 41c0 999 999', b'1 9000 fffff 999 999', b'1 9000 41c0 -1 999',
            b'1 9000 41c0 4294967295 999', b'1  9000 41c0 999 999', b'\xff'):
            fields = wire(self.paths).split(b'\0'); fields[3] = fields[6] = value
            self.reject(b'\0'.join(fields), 'DATABASE_LAYOUT_METADATA_INVALID')
    def test_non_symlink_leaf_and_followed_directory_identity_must_match(self):
        fields = wire(self.paths).split(b'\0'); fields[5] = b'1 9991 41c0 999 999'
        self.reject(b'\0'.join(fields), 'DATABASE_LAYOUT_DIRECTORY_CHANGED')
    def test_native_directories_symlink_and_quoted_shell_characters_no_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root/"data ' $(touch injected);"; data.mkdir(mode=0o700)
            wal = root/'wal'; wal.mkdir(mode=0o700); (data/'pg_wal').symlink_to(wal, target_is_directory=True)
            sentinel = wal/'secret'; sentinel.write_bytes(b'SYNTHETIC_DATABASE_CONTENT_NEVER_READ')
            before = sentinel.stat(); paths = (str(data), str(data/'pg_wal'))
            result = subprocess.run(['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'LC_ALL=C',
                '/bin/sh', '-c', layout.METADATA_SCRIPT, 'camera-layout', *paths],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
            observed = layout.directories(result.stdout, paths, execution=(os.geteuid(), os.getegid()))
            self.assertTrue(observed[paths[1]]['leaf_is_symlink'])
            self.assertEqual(observed[paths[1]]['resolved_path'], str(wal))
            self.assertFalse((root/'injected').exists()); self.assertNotIn(b'SYNTHETIC_DATABASE_CONTENT', result.stdout)
            after = sentinel.stat(); self.assertEqual((before.st_mtime_ns, before.st_atime_ns, before.st_mode),
                (after.st_mtime_ns, after.st_atime_ns, after.st_mode))
    def test_native_dangling_link_and_nonexistent_path_fail_without_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); link = root/'dangling'; link.symlink_to(root/'missing')
            for path in (link, root/'absent'):
                result = subprocess.run(['/bin/sh', '-c', layout.METADATA_SCRIPT, 'camera-layout', str(path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                self.assertNotEqual(result.returncode, 0); self.assertFalse((root/'missing').exists())
    def test_native_newline_in_resolved_path_is_not_stripped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); target = root/'wal\n'; target.mkdir(); link = root/'pg_wal'; link.symlink_to(target)
            result = subprocess.run(['/bin/sh', '-c', layout.METADATA_SCRIPT, 'camera-layout', str(link)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
            self.assertIn(str(target).encode()+b'\0', result.stdout)
            with self.assertRaisesRegex(layout.ActivationError, '^DATABASE_LAYOUT_PATH_INVALID$'):
                layout.directories(result.stdout, (str(link),), execution=(os.geteuid(), os.getegid()))


class LayoutInspectionTest(unittest.TestCase):
    read_api = legacy.DatabaseMountTopologyTest.read_api
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'; self.root.mkdir(); fixture(self.root)
        self.docker, self.reader = FakeDocker(self.root), legacy.FakeReader()
        api = patch.object(layout.inventory, 'read_api', side_effect=self.read_api)
        api.start(); self.addCleanup(api.stop)
    def inspect(self): return layout.inspect_layout(self.root, self.docker, lambda: self.reader)
    def rejected(self, code):
        with self.assertRaisesRegex(layout.ActivationError, '^'+code+'$'): self.inspect()
    def final_inspect(self, change):
        def transform(value):
            if self.docker.inspection_stage == 'database_layout_container_recheck': change(value[0])
            return value
        self.docker.inspect_transform = transform
    def test_five_mounts_with_different_order_on_every_inspect_remain_observed(self):
        def rotate(value):
            rows = value[0]['Mounts']; offset = self.docker.db_inspects % len(rows)
            value[0]['Mounts'] = rows[offset:]+rows[:offset]
            return value
        self.docker.inspect_transform = rotate
        value = self.inspect()
        self.assertEqual(value['layout_readiness'], 'observed')
        self.assertTrue(value['active_database_storage_locations_observed'])
        self.assertGreater(self.docker.db_inspects, 5)
        self.assertEqual((self.docker.catalog_calls, self.docker.metadata_calls), (2, 2))
        self.assertTrue(all(value[k] is False for k in layout.NO_CHANGES))
    def test_mount_object_key_order_does_not_change_binding(self):
        self.final_inspect(lambda row: row.update(Mounts=[dict(reversed(list(m.items())))
            for m in reversed(row['Mounts'])]))
        self.assertEqual(self.inspect()['layout_readiness'], 'observed')
    def test_every_mount_attribute_including_unknown_nested_values_and_types_is_preserved(self):
        self.docker.db['Mounts'][-1]['Extra'] = {'nested': [1, 2]}
        changes = [('Source', '/synthetic/'+legacy.TOKEN), ('Type', 'volume'), ('RW', True),
            ('RW', 0), ('Mode', 'rw'), ('Propagation', 'shared'), ('Name', 'different'),
            ('Driver', 'different'), ('Extra', {'nested': [2, 1]})]
        for index in range(5):
            for field, value in changes:
                with self.subTest(mount=index, field=field, value=value):
                    if field == 'Type' and self.docker.db['Mounts'][index]['Type'] == value: value = 'bind'
                    if field == 'RW' and value is True and self.docker.db['Mounts'][index]['RW'] is True: value = False
                    self.final_inspect(lambda row, i=index, k=field, v=value: row['Mounts'][i].update({k: v}))
                    self.rejected('DATABASE_LAYOUT_MOUNTS_CHANGED')
                    self.assertEqual(self.docker.inspection_stage, 'database_layout_container_recheck')
    def test_added_removed_or_retargeted_mount_is_rejected(self):
        mutations = [lambda row: row['Mounts'].pop(),
            lambda row: row['Mounts'].append({'Type': 'bind', 'Source': '/synthetic/new',
                'Destination': '/new', 'RW': False}),
            lambda row: row['Mounts'][-1].update(Destination='/retargeted')]
        for change in mutations:
            with self.subTest(change=mutations.index(change)):
                self.final_inspect(change); self.rejected('DATABASE_LAYOUT_MOUNTS_CHANGED')
    def test_initial_duplicate_or_invalid_destination_is_rejected_before_catalog(self):
        for destination in ('/run/secrets/camera_admin_password', '', None,
            '//duplicate', '/path/../other', '/path/', ['bad']):
            with self.subTest(destination=destination):
                self.docker = FakeDocker(self.root)
                self.docker.db['Mounts'][-1]['Destination'] = destination
                # A duplicate of a non-volume binding passes the parent's data-volume check.
                self.rejected('DATABASE_LAYOUT_MOUNTS_INVALID')
                self.assertEqual(self.docker.catalog_calls, 0)
                self.assertEqual(self.docker.inspection_stage, 'database_layout_identity')
    def test_final_malformed_or_duplicate_mounts_are_rejected(self):
        invalid = [None, {}, [], [None], [{'Source': legacy.TOKEN}],
            [{'Destination': '//noncanonical'}], [self.docker.db['Mounts'][0]]*2]
        for rows in invalid:
            with self.subTest(rows=rows):
                self.final_inspect(lambda row, mounts=rows: row.update(Mounts=mounts))
                self.rejected('DATABASE_LAYOUT_MOUNTS_INVALID')
    def test_final_pid_and_host_config_changes_have_distinct_codes(self):
        cases = [(lambda row: row['State'].update(Pid=103), 'DATABASE_LAYOUT_CONTAINER_PID_CHANGED'),
            (lambda row: row['HostConfig'].update(ReadonlyRootfs=True), 'DATABASE_LAYOUT_HOST_CONFIG_CHANGED')]
        for change, code in cases:
            with self.subTest(code=code):
                self.final_inspect(change); self.rejected(code)
                self.assertEqual(self.docker.inspection_stage, 'database_layout_container_recheck')
    def test_mount_drift_failure_report_has_accurate_stage_without_mount_values(self):
        self.final_inspect(lambda row: row['Mounts'][-1].update(Source='/private/'+legacy.TOKEN))
        report = self.root/layout.REPORT; report.write_text('{"status":"inspected"}')
        probe = layout.inspect_layout
        with patch.object(layout, 'LayoutDocker', return_value=self.docker), \
            patch.object(layout, 'inspect_layout', side_effect=lambda root, docker: probe(root, docker, lambda: self.reader)):
            with self.assertRaisesRegex(layout.ActivationError, '^DATABASE_LAYOUT_MOUNTS_CHANGED$'):
                layout.run_inspection(self.root)
        value = json.loads(report.read_text())
        self.assertEqual(value['code'], 'DATABASE_LAYOUT_MOUNTS_CHANGED')
        self.assertEqual(value['failed_stage'], 'database_layout_container_recheck')
        self.assertFalse(value['inspection_completed'])
        self.assertFalse(value['active_database_storage_locations_observed'])
        self.assertTrue(all(value[k] is False for k in layout.NO_CHANGES))
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        for private in (legacy.TOKEN, '/private/', DB_ID, 'Mounts', 'HostConfig'):
            self.assertNotIn(private, report.read_text())
    def test_observed_locations_are_not_full_backup_or_activation_proof(self):
        value = self.inspect(); text = json.dumps(value)
        self.assertEqual(value['layout_readiness'], 'observed'); self.assertEqual(value['blockers'], [])
        self.assertTrue(value['active_database_storage_locations_observed'])
        self.assertTrue(value['current_volume_mount_verified']); self.assertTrue(value['layout']['read_only_transaction_verified'])
        self.assertFalse(value['layout']['wal']['outside_resolved_pgdata'])
        self.assertEqual(value['layout']['wal']['host_path_candidate'], legacy.HOST_PATH+'/pg_wal')
        self.assertFalse(value['layout']['wal']['host_path_verified'])
        self.assertTrue(all(value[k] is False for k in layout.NO_CHANGES))
        self.assertFalse(value['activation_allowed']); self.assertFalse(value['production_supply_ready'])
        for private in (legacy.TOKEN, DB_ID, '"signature":', '"pid":', 'postmaster_started'):
            self.assertNotIn(private, text)
        self.assertFalse((self.root/layout.REPORT).exists())
    def test_external_wal_and_tablespace_host_mapping_remains_unresolved(self):
        self.docker.catalog_value['tablespace_count'] = 3
        self.docker.catalog_value['tablespaces'].append({'oid': 18000, 'location': '/external/tablespace'})
        self.docker.metadata_changes[DATA+'/pg_wal'] = {'symlink': True, 'resolved': '/external/wal'}
        value = self.inspect()['layout']
        self.assertTrue(value['wal']['outside_resolved_pgdata']); self.assertIsNone(value['wal']['host_path_candidate'])
        self.assertEqual(value['custom_tablespaces'][0]['container_path'], '/external/tablespace')
        self.assertFalse(value['custom_tablespaces'][0]['host_path_verified'])
    def test_actual_setting_outside_declared_volume_not_misreported_as_backup_verified(self):
        self.docker.catalog_value['data_directory'] = '/different/data'
        value = self.inspect()['layout']['pgdata']
        self.assertEqual(value['container_path'], '/different/data')
        self.assertFalse(value['within_verified_container_volume']); self.assertIsNone(value['host_path_candidate'])
    def test_source_and_accepted_volume_gate_before_docker(self):
        path = self.root/'project-manifest.json'; value = json.loads(path.read_text())
        value['credential_production_database_mount_topology_server_verified'] = False; path.write_text(json.dumps(value))
        self.rejected('ACCEPTED_VOLUME_OBSERVATION_REQUIRED'); self.assertEqual(self.docker.calls, [])
        value['credential_production_database_mount_topology_server_verified'] = True; path.write_text(json.dumps(value))
        (self.root/layout.SOURCE).write_text('synthetic user edit')
        self.rejected('SOURCE_FILE_CHANGED'); self.assertEqual(self.docker.calls, [])
    def test_stale_parent_report_is_ignored_and_blocked_mount_prevents_exec(self):
        (self.root/layout.topology.REPORT).write_text('{"topology_readiness":"verified"}')
        self.reader.directory_error = OSError(errno.EACCES, legacy.TOKEN)
        value = self.inspect()
        self.assertEqual(value['layout_readiness'], 'blocked'); self.assertIsNone(value['layout'])
        self.assertFalse(value['active_database_storage_locations_observed']); self.assertEqual(self.docker.catalog_calls, 0)
    def test_metadata_command_unavailable_stays_blocked_without_repair(self):
        self.docker.metadata_error = layout.identity.IdentityBlocked('READ_ONLY_LAYOUT_COMMAND_UNAVAILABLE')
        value = self.inspect(); self.assertEqual(value['blockers'], ['READ_ONLY_LAYOUT_COMMAND_UNAVAILABLE'])
        self.assertFalse(value['active_database_storage_locations_observed']); self.assertNotIn(legacy.TOKEN, json.dumps(value))
    def test_catalog_change_after_first_command_rejected(self):
        self.docker.after_catalog = lambda: self.docker.catalog_value.update(archive_mode='on')
        self.rejected('DATABASE_LAYOUT_CATALOG_CHANGED')
    def test_inode_change_between_metadata_commands_rejected(self):
        self.docker.after_metadata = lambda: self.docker.metadata_changes.update({DATA: {'inode': 9500}})
        self.rejected('DATABASE_LAYOUT_DIRECTORY_CHANGED')
    def test_command_disappearing_at_recheck_is_failed(self):
        self.docker.after_metadata = lambda: setattr(self.docker, 'metadata_error',
            layout.identity.IdentityBlocked('READ_ONLY_LAYOUT_COMMAND_UNAVAILABLE'))
        self.rejected('DATABASE_LAYOUT_UNAVAILABLE_DURING_RECHECK')
    def test_process_identity_changes_after_metadata_rejected(self):
        self.docker.after_metadata = lambda: self.reader.records[102].update(signature=(1, 2, 3))
        self.rejected('PROCESS_CHANGED_DURING_INSPECTION')
    def test_environment_change_rejected(self):
        self.docker.after_metadata = lambda: (self.root/'.env').write_text('synthetic change')
        self.rejected('INSPECTION_INPUT_CHANGED')
    def test_key_metadata_change_rejected_without_loading_material(self):
        key = self.root/layout.inventory.KEY; before = key.stat()
        self.docker.after_metadata = lambda: os.utime(key, ns=(before.st_atime_ns, before.st_mtime_ns+1))
        self.rejected('KEY_METADATA_CHANGED_DURING_INSPECTION')
    def test_full_parent_volume_proof_repeated_after_location_observation(self):
        self.docker.after_metadata = lambda: self.reader.directory_value.update(signature=((1, 9011, 999, 999, 0o40700),))
        self.rejected('DATABASE_LAYOUT_VOLUME_CHANGED')
    def test_report_failure_replaces_stale_success_is_private_and_sanitized(self):
        report = self.root/layout.REPORT; report.write_text('{"status":"inspected","layout_readiness":"observed"}')
        self.docker.metadata_transform = lambda v: b'invalid '+legacy.TOKEN.encode()
        probe = layout.inspect_layout
        with patch.object(layout, 'LayoutDocker', return_value=self.docker), \
            patch.object(layout, 'inspect_layout', side_effect=lambda root, docker: probe(root, docker, lambda: self.reader)):
            with self.assertRaisesRegex(layout.ActivationError, '^DATABASE_LAYOUT_METADATA_INVALID$'):
                layout.run_inspection(self.root)
        value = json.loads(report.read_text()); self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['failed_stage'], 'database_layout_directories')
        self.assertEqual(report.stat().st_mode & 0o777, 0o600); self.assertNotIn(legacy.TOKEN, report.read_text())
        self.assertFalse(value['active_database_storage_locations_observed'])
    def test_protected_key_material_is_not_opened_or_hashed(self):
        real_open = builtins.open; real_read_bytes = Path.read_bytes
        key = self.root/layout.inventory.KEY
        def guarded_open(path, *args, **kwargs):
            if isinstance(path, (str, Path)): self.assertNotEqual(Path(path), key)
            return real_open(path, *args, **kwargs)
        def guarded_bytes(path):
            self.assertNotEqual(path, key); return real_read_bytes(path)
        with patch.object(builtins, 'open', side_effect=guarded_open), patch.object(Path, 'read_bytes', guarded_bytes):
            self.assertEqual(self.inspect()['layout_readiness'], 'observed')
    def test_cli_explicit_privileged_option_and_root_parent_guard(self):
        with patch.object(sys, 'argv', ['inspect', '--privileged-directory-metadata']), \
            patch.object(sys, 'stdout', io.StringIO()), patch.object(layout, 'run_inspection', return_value={}) as run:
            self.assertEqual(layout.main(), 0); self.assertEqual(run.call_args.kwargs, {'privileged': True})
        with patch.object(os, 'geteuid', return_value=0), patch.object(layout, 'atomic_write') as write:
            with self.assertRaisesRegex(layout.ActivationError, '^RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER$'):
                layout.run_inspection(self.root, privileged=True)
            write.assert_not_called()


class CommandBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.docker = layout.LayoutDocker(Path('/synthetic'))
        self.docker.database_id = DB_ID; self.docker.reviewed_container_ids = {DB_ID}
        self.docker.layout_paths = (DATA, DATA+'/pg_wal')
    def test_exact_catalog_and_metadata_exec_only_for_owned_identified_db(self):
        with patch.object(layout.Docker, 'run', return_value=b'fixed') as run:
            for args in (['exec', '--user', '999:999', DB_ID, *layout.inventory.SQL_ARGS, layout.CATALOG_SQL],
                layout.metadata_args(DB_ID, self.docker.layout_paths)):
                self.assertEqual(self.docker.run(args), b'fixed')
            self.assertEqual(run.call_count, 2)
    def test_sql_shell_user_path_and_stdin_variations_rejected(self):
        sql = ['exec', '--user', '999:999', DB_ID, *layout.inventory.SQL_ARGS, layout.CATALOG_SQL]
        metadata = layout.metadata_args(DB_ID, self.docker.layout_paths)
        variants = [sql[:-1]+['SELECT 1'], sql[:2]+['0:0']+sql[3:], sql[:3]+['c'*64]+sql[4:],
            metadata[:-1]+['/arbitrary'], metadata+['/extra'], ['exec', DB_ID, 'cat', '/secret']]
        with patch.object(layout.Docker, 'run') as run:
            for args in variants:
                with self.assertRaisesRegex(layout.ActivationError, '^PRODUCTION_DOCKER_WRITE_REJECTED$'):
                    self.docker.run(args)
            for kwargs in ({'input': b'bad'}, {'stdout': io.BytesIO()}, {'extra': ['--privileged']}, {'shell': True}):
                with self.assertRaisesRegex(layout.ActivationError, '^PRODUCTION_DOCKER_WRITE_REJECTED$'):
                    self.docker.run(sql, **kwargs)
            run.assert_not_called()
    def test_missing_owned_db_and_unregistered_metadata_paths_rejected(self):
        args = layout.metadata_args(DB_ID, self.docker.layout_paths); self.docker.layout_paths = None
        with patch.object(layout.Docker, 'run') as run:
            with self.assertRaisesRegex(layout.ActivationError, '^PRODUCTION_DOCKER_WRITE_REJECTED$'): self.docker.run(args)
            self.docker.reviewed_container_ids = set()
            sql = ['exec', '--user', '999:999', DB_ID, *layout.inventory.SQL_ARGS, layout.CATALOG_SQL]
            with self.assertRaisesRegex(layout.ActivationError, '^PRODUCTION_DOCKER_WRITE_REJECTED$'): self.docker.run(sql)
            run.assert_not_called()
    def test_command_failure_stderr_is_not_emitted(self):
        with patch.object(layout.Docker, 'run', side_effect=layout.ActivationError(legacy.TOKEN)):
            with self.assertRaisesRegex(layout.identity.IdentityBlocked, '^READ_ONLY_LAYOUT_COMMAND_UNAVAILABLE$'):
                self.docker.run(layout.metadata_args(DB_ID, self.docker.layout_paths))


if __name__ == '__main__': unittest.main()
