"""Physical directory identity, drift, fixed-path privilege and safe reports."""
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

import inspect_camera_database_storage_mapping as mapping
import test_inspect_camera_database_storage_layout as legacy

SOURCE = Path(__file__).resolve().parents[3]
TOKEN = legacy.legacy.TOKEN
DEVICE = (os.major(1), os.minor(1))


def fixture(root):
    legacy.fixture(root)
    path = root/'project-manifest.json'; manifest = json.loads(path.read_text())
    target = root/mapping.SOURCE; target.write_bytes((SOURCE/mapping.SOURCE).read_bytes())
    manifest['files'][mapping.SOURCE] = mapping.sha(target)
    manifest.update(camera_database_storage_layout_server_verified=True,
        validated_camera_database_storage_layout_project_sha256=mapping.ACCEPTED_LAYOUT,
        camera_database_storage_mapping_implemented=True)
    path.write_text(json.dumps(manifest))


class FakeDocker(legacy.FakeDocker):
    def __init__(self, root):
        super().__init__(root)
        self.db['Mounts'][0]['Source'] = mapping.HOST
        self.metadata_changes[mapping.PATHS[1]] = {'inode': 9001}


class FakeReader(legacy.legacy.FakeReader):
    def __init__(self, docker):
        super().__init__(); self.docker = docker
        self.directory_value['device'] = DEVICE
        self.host_mounts[1]['device'] = DEVICE
        self.db_mounts[12].update(root=mapping.HOST, device=DEVICE)
        self.values = {mapping.HOST: copy.deepcopy(self.directory_value),
            mapping.HOSTS[1]: {**copy.deepcopy(self.directory_value),
                'signature': self.directory_value['signature']+((1, 9001, 999, 999, 0o40700),)}}
        self.errors = {}; self.after_mapping_directory = lambda: None; self.mapping_calls = 0
    def directory(self, path):
        assert path in mapping.HOSTS
        self.calls.append(path)
        if path in self.errors: raise self.errors[path]
        result = copy.deepcopy(self.values[path])
        if self.docker.inspection_stage in ('host_storage_directories', 'physical_mapping_recheck'):
            self.mapping_calls += 1; self.after_mapping_directory()
        return result


class MappingInspectionTest(unittest.TestCase):
    read_api = legacy.LayoutInspectionTest.read_api
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'; self.root.mkdir(); fixture(self.root)
        self.docker = FakeDocker(self.root); self.reader = FakeReader(self.docker)
        api = patch.object(mapping.inventory, 'read_api', side_effect=self.read_api)
        api.start(); self.addCleanup(api.stop)
    def inspect(self): return mapping.inspect_mapping(self.root, self.docker, lambda: self.reader)
    def rejected(self, code):
        with self.assertRaisesRegex(mapping.ActivationError, '^'+code+'$'): self.inspect()
    def after_initial_host(self, action):
        self.reader.after_mapping_directory = lambda: action() if self.reader.mapping_calls == 2 else None
    def test_two_directories_verified_with_full_read_only_rechecks(self):
        value = self.inspect(); text = json.dumps(value)
        self.assertEqual(value['mapping_readiness'], 'verified'); self.assertEqual(value['blockers'], [])
        self.assertTrue(value['individual_host_paths_verified'])
        self.assertEqual(self.docker.catalog_calls, 6); self.assertEqual(self.docker.metadata_calls, 6)
        for name, host, path in zip(('pgdata', 'wal'), mapping.HOSTS, mapping.PATHS):
            row = value['mapping'][name]
            self.assertEqual((row['host_path'], row['container_path']), (host, path))
            self.assertTrue(row['same_directory_identity_verified']); self.assertTrue(row['host_path_verified'])
        self.assertTrue(all(value[k] is False for k in mapping.NO_CHANGES))
        self.assertFalse(value['activation_allowed']); self.assertFalse(value['production_supply_ready'])
        for private in (TOKEN, legacy.DB_ID, '"signature":', '"pid":', '"inode":', '"device":'):
            self.assertNotIn(private, text)
        self.assertFalse((self.root/mapping.REPORT).exists())
    def test_accepted_layout_receipt_and_mapping_flag_before_docker(self):
        path = self.root/'project-manifest.json'; original = json.loads(path.read_text())
        for field, value in (('camera_database_storage_layout_server_verified', False),
            ('validated_camera_database_storage_layout_project_sha256', 'wrong'),
            ('camera_database_storage_mapping_implemented', False)):
            path.write_text(json.dumps({**original, field: value}))
            self.rejected('ACCEPTED_STORAGE_LAYOUT_REQUIRED'); self.assertEqual(self.docker.calls, [])
    def test_changed_source_is_rejected_before_docker(self):
        (self.root/mapping.SOURCE).write_text(TOKEN)
        self.rejected('SOURCE_FILE_CHANGED'); self.assertEqual(self.docker.calls, [])
    def test_stale_verified_reports_cannot_replace_live_observation(self):
        (self.root/mapping.layout.REPORT).write_text('{"layout_readiness":"observed"}')
        self.reader.records[102]['gid_map'] = ((0, 999, 1),)
        value = self.inspect()
        self.assertEqual(value['mapping_readiness'], 'blocked'); self.assertIsNone(value['mapping'])
        self.assertFalse(value['individual_host_paths_verified']); self.assertEqual(self.docker.catalog_calls, 0)
    def test_different_pgdata_or_external_wal_requires_review(self):
        cases = [('pgdata', {'data_directory': '/different/data'}, {}),
            ('wal', {}, {mapping.PATHS[1]: {'symlink': True, 'resolved': '/outside/wal'}})]
        for name, settings, changes in cases:
            with self.subTest(name=name):
                self.docker = FakeDocker(self.root); self.reader = FakeReader(self.docker)
                self.docker.catalog_value.update(settings); self.docker.metadata_changes.update(changes)
                self.rejected('CURRENT_STORAGE_LAYOUT_REVIEW_REQUIRED')
                self.assertEqual(self.reader.mapping_calls, 0)
    def test_new_tablespace_or_archive_mode_requires_review(self):
        for field in ('tablespace', 'archive'):
            with self.subTest(field=field):
                self.docker = FakeDocker(self.root); self.reader = FakeReader(self.docker)
                if field == 'tablespace':
                    self.docker.catalog_value['tablespace_count'] = 3
                    self.docker.catalog_value['tablespaces'].append({'oid': 18000, 'location': '/external'})
                else: self.docker.catalog_value['archive_mode'] = 'on'
                self.rejected('CURRENT_STORAGE_LAYOUT_REVIEW_REQUIRED'); self.assertEqual(self.reader.mapping_calls, 0)
    def test_host_inode_device_owner_gid_and_mode_mismatch_rejected(self):
        for index, value in ((0, 2), (1, 9999), (2, 1006), (3, 1007), (4, 0o40755)):
            with self.subTest(index=index):
                row = list(self.reader.values[mapping.HOSTS[1]]['signature'][-1]); row[index] = value
                self.reader.values[mapping.HOSTS[1]]['signature'] = self.reader.values[mapping.HOST]['signature']+(tuple(row),)
                self.rejected('DATABASE_HOST_DIRECTORY_IDENTITY_MISMATCH')
    def test_wal_parent_chain_must_match_pgdata(self):
        row = list(self.reader.values[mapping.HOSTS[1]]['signature'][0]); row[1] += 1
        self.reader.values[mapping.HOSTS[1]]['signature'] = (tuple(row), self.reader.values[mapping.HOSTS[1]]['signature'][-1])
        self.rejected('DATABASE_HOST_DIRECTORY_CHAIN_MISMATCH')
    def test_wal_descriptor_mount_and_device_must_match_live_metadata(self):
        original = copy.deepcopy(self.reader.values[mapping.HOSTS[1]])
        for field, value, code in (('mount_id', 999, 'HOST_DIRECTORY_MOUNT_MISMATCH'),
            ('device', (0, 2), 'DATABASE_HOST_DIRECTORY_DEVICE_MISMATCH')):
            with self.subTest(field=field):
                self.reader.values[mapping.HOSTS[1]] = {**original, field: value}
                self.rejected(code)
    def test_wal_host_overmount_with_wrong_root_is_rejected(self):
        self.reader.host_mounts[50] = legacy.legacy.mount(50, 1, mapping.HOSTS[1], root='/wrong', device=DEVICE)
        self.reader.values[mapping.HOSTS[1]]['mount_id'] = 50
        self.rejected('DATABASE_MAPPING_MOUNT_SOURCE_MISMATCH')
    def test_initial_wal_permission_absence_or_privilege_unavailable_stays_blocked(self):
        for error in (OSError(errno.EACCES, TOKEN), OSError(errno.ENOENT, TOKEN),
            mapping.identity.IdentityBlocked('PRIVILEGED_DIRECTORY_OBSERVER_UNAVAILABLE')):
            with self.subTest(error=type(error)):
                self.reader.errors[mapping.HOSTS[1]] = error
                value = self.inspect(); self.assertEqual(value['mapping_readiness'], 'blocked')
                self.assertFalse(value['individual_host_paths_verified']); self.assertIsNone(value['mapping'])
                self.assertNotIn(TOKEN, json.dumps(value))
    def test_host_symlink_or_non_directory_is_failed_without_fallback(self):
        self.reader.errors[mapping.HOSTS[1]] = mapping.ActivationError('DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED')
        self.rejected('DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED')
    def test_host_directory_identity_drift_is_failed(self):
        self.after_initial_host(lambda: self.reader.values[mapping.HOSTS[1]].update(
            signature=self.reader.values[mapping.HOST]['signature']+((1, 9999, 999, 999, 0o40700),)))
        self.rejected('DATABASE_HOST_DIRECTORY_CHANGED')
    def test_host_disappearance_during_recheck_is_failed(self):
        self.after_initial_host(lambda: self.reader.errors.update({mapping.HOSTS[1]: OSError(errno.ENOENT, TOKEN)}))
        self.rejected('DATABASE_MAPPING_UNAVAILABLE_DURING_RECHECK')
    def test_container_directory_drift_is_failed(self):
        self.after_initial_host(lambda: self.docker.metadata_changes.update({mapping.PATHS[1]: {'inode': 9999}}))
        self.rejected('DATABASE_LAYOUT_DIRECTORY_CHANGED')
    def test_catalog_drift_is_failed(self):
        self.after_initial_host(lambda: self.docker.catalog_value.update(archive_mode='on'))
        self.rejected('DATABASE_LAYOUT_CHANGED')
    def test_new_nested_container_mount_is_rejected(self):
        extra = legacy.legacy.mount(13, 12, mapping.PATHS[1], root='/unreviewed', device=DEVICE)
        self.after_initial_host(lambda: self.reader.db_mounts.update({13: extra}))
        self.rejected('DATABASE_LAYOUT_CHANGED')
    def test_replaced_wal_on_both_sides_is_detected_after_full_parent_recheck(self):
        def replace():
            self.reader.values[mapping.HOSTS[1]]['signature'] = self.reader.values[mapping.HOST]['signature']+((1, 9999, 999, 999, 0o40700),)
            self.docker.metadata_changes[mapping.PATHS[1]] = {'inode': 9999}
        self.after_initial_host(replace)
        self.rejected('DATABASE_LAYOUT_DIRECTORY_CHANGED')
    def test_process_environment_and_key_metadata_drift_are_rejected(self):
        key = self.root/mapping.inventory.KEY; before = key.stat()
        actions = [(lambda: self.reader.records[102].update(signature=(1, 2, 3)), 'PROCESS_CHANGED_DURING_INSPECTION'),
            (lambda: (self.root/'.env').write_text('synthetic change'), 'INSPECTION_INPUT_CHANGED'),
            (lambda: os.utime(key, ns=(before.st_atime_ns, before.st_mtime_ns+1)), 'KEY_METADATA_CHANGED_DURING_INSPECTION')]
        for action, code in actions:
            with self.subTest(code=code):
                self.reader.records[102] = legacy.legacy.legacy.record(102, 999, 999, legacy.DB_ID)
                (self.root/'.env').write_text('CAMERA_API_ENDPOINT=http://127.0.0.1:18081\n')
                self.reader.mapping_calls = 0; self.after_initial_host(action)
                self.rejected(code)
    def test_final_container_binding_change_is_rejected(self):
        def mutate(value):
            if self.docker.inspection_stage == 'mapping_container_recheck': value[0]['Mounts'][-1]['Source'] = '/private/'+TOKEN
            return value
        self.docker.inspect_transform = mutate
        self.rejected('DATABASE_MAPPING_CONTAINER_CHANGED')
    def test_mount_order_variation_during_all_rechecks_is_allowed(self):
        def rotate(value):
            rows = value[0]['Mounts']; offset = self.docker.db_inspects % len(rows)
            value[0]['Mounts'] = rows[offset:]+rows[:offset]; return value
        self.docker.inspect_transform = rotate
        self.assertTrue(self.inspect()['individual_host_paths_verified'])
    def test_report_failure_replaces_stale_success_privately_without_raw_values(self):
        report = self.root/mapping.REPORT; report.write_text('{"individual_host_paths_verified":true}')
        self.reader.errors[mapping.HOSTS[1]] = mapping.ActivationError('DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED')
        probe = mapping.inspect_mapping
        with patch.object(mapping.layout, 'LayoutDocker', return_value=self.docker), \
            patch.object(mapping, 'inspect_mapping', side_effect=lambda root, docker, factory: probe(root, docker, lambda: self.reader)):
            with self.assertRaisesRegex(mapping.ActivationError, '^DATABASE_PATH_SYMLINK_OR_TYPE_REJECTED$'):
                mapping.run_inspection(self.root)
        value = json.loads(report.read_text()); self.assertEqual(value['failed_stage'], 'host_storage_directories')
        self.assertFalse(value['individual_host_paths_verified']); self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(TOKEN, report.read_text()); self.assertNotIn(legacy.DB_ID, report.read_text())
        self.assertTrue(all(value[k] is False for k in mapping.NO_CHANGES))
    def test_success_report_does_not_overwrite_parent_reports(self):
        for name in (mapping.layout.REPORT, mapping.topology.REPORT): (self.root/name).write_text(TOKEN)
        probe = mapping.inspect_mapping
        with patch.object(mapping.layout, 'LayoutDocker', return_value=self.docker), \
            patch.object(mapping, 'inspect_mapping', side_effect=lambda root, docker, factory: probe(root, docker, lambda: self.reader)):
            value = mapping.run_inspection(self.root)
        self.assertTrue(value['individual_host_paths_verified'])
        self.assertEqual((self.root/mapping.REPORT).stat().st_mode & 0o777, 0o600)
        for name in (mapping.layout.REPORT, mapping.topology.REPORT): self.assertEqual((self.root/name).read_text(), TOKEN)
    def test_original_key_material_is_not_opened(self):
        key = self.root/mapping.inventory.KEY; original = Path.read_bytes
        def guarded(path):
            self.assertNotEqual(path, key); return original(path)
        with patch.object(Path, 'read_bytes', guarded): self.assertTrue(self.inspect()['individual_host_paths_verified'])
    def test_cli_explicit_option_and_root_parent_guard(self):
        with patch.object(sys, 'argv', ['inspect', '--privileged-directory-metadata']), \
            patch.object(sys, 'stdout', io.StringIO()), patch.object(mapping, 'run_inspection', return_value={}) as run:
            self.assertEqual(mapping.main(), 0); self.assertEqual(run.call_args.kwargs, {'privileged': True})
        with patch.object(os, 'geteuid', return_value=0), patch.object(mapping, 'atomic_write') as write:
            with self.assertRaisesRegex(mapping.ActivationError, '^RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER$'):
                mapping.run_inspection(self.root, privileged=True)
            write.assert_not_called()


class NativeMetadataTest(unittest.TestCase):
    def test_actual_stat_and_path_descriptor_have_same_identity_without_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); wal = root/'pg_wal'; wal.mkdir(mode=0o700)
            sentinel = root/'DATABASE_CONTENT'; sentinel.write_text(TOKEN); before = sentinel.stat()
            paths = (str(root), str(wal))
            result = subprocess.run(['/bin/sh', '-c', mapping.layout.METADATA_SCRIPT, 'camera-layout', *paths],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
            values = mapping.layout.directories(result.stdout, paths, execution=(os.geteuid(), os.getegid()))
            with mapping.topology.MountReader() as reader, \
                patch.object(os, 'listdir', side_effect=AssertionError('contents')), \
                patch.object(os, 'scandir', side_effect=AssertionError('contents')):
                for path in paths:
                    host = reader.directory(path); leaf = values[path]['signature'][-1]
                    self.assertEqual(host['signature'][-1], (leaf[0], leaf[1], leaf[3], leaf[4], leaf[2]))
            after = sentinel.stat(); self.assertEqual((before.st_atime_ns,before.st_mtime_ns),(after.st_atime_ns,after.st_mtime_ns))


if __name__ == '__main__': unittest.main()
