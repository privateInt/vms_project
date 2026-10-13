"""Current init identity evidence, drift and read boundaries; synthetic Docker."""
import builtins
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

import inspect_camera_credential_identity as identity
import test_inspect_camera_credential_supply_facts as legacy

SOURCE = Path(__file__).resolve().parents[3]
API_ID, DB_ID = legacy.legacy.API_ID, legacy.legacy.DB_ID
TOKEN = legacy.legacy.TOKEN


def fixture(root):
    legacy.fixture(root)
    path = root/'project-manifest.json'; manifest = json.loads(path.read_text())
    for name in ('prepare_camera_credential_supply_review.py', 'inspect_camera_credential_identity.py'):
        rel = 'src/infra/tools/'+name; target = root/rel; target.write_bytes((SOURCE/rel).read_bytes())
        manifest['files'][rel] = identity.sha(target)
    manifest.update(credential_production_supply_facts_server_verified=True,
        validated_credential_production_supply_facts_project_sha256=identity.review.ACCEPTED_FACTS,
        credential_production_supply_review_implemented=True,
        credential_production_supply_review_server_verified=True,
        validated_credential_production_supply_review_project_sha256=identity.ACCEPTED_REVIEW,
        credential_production_process_identity_implemented=True)
    path.write_text(json.dumps(manifest))


class FakeDocker(legacy.FakeDocker):
    def __init__(self, root):
        super().__init__(root)
        for service, pid in ((self.camera, 101), (self.db, 102)):
            service.setdefault('State', {}).update(Running=True, StartedAt='synthetic-start', Pid=pid)
            service['HostConfig']['PidMode'] = ''


def record(pid, uid, gid, cid):
    return {'ids': {'Uid': (uid,)*4, 'Gid': (gid,)*4, 'NSpid': (pid, 1)}, 'uid_map': identity.FULL_MAP,
        'gid_map': identity.FULL_MAP, 'cgroup': ('0::/system.slice/docker-'+cid+'.scope\n').encode(),
        'signature': (1, pid+5000, 1000+pid)}


class FakeReader:
    def __init__(self):
        self.records = {101: record(101, 65532, 65532, API_ID), 102: record(102, 999, 999, DB_ID)}
        self.observer_record = record(100, 1006, 1007, 'c'*64)
        self.observer_error = None; self.enter_error = None; self.calls = []; self.after_read = lambda pid: None
    def __enter__(self):
        if self.enter_error: raise self.enter_error
        return self
    def __exit__(self, *exc): pass
    def observer(self):
        self.calls.append('observer')
        if self.observer_error: raise self.observer_error
        return copy.deepcopy(self.observer_record)
    def process(self, pid):
        self.calls.append(pid)
        value = self.records[pid]
        if isinstance(value, BaseException): raise value
        result = copy.deepcopy(value); self.after_read(pid); return result


class ProcessIdentityTest(unittest.TestCase):
    read_api = legacy.SupplyFactsTest.read_api
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'; self.root.mkdir(); fixture(self.root)
        self.docker, self.reader = FakeDocker(self.root), FakeReader()
        api = patch.object(identity.inventory, 'read_api', side_effect=self.read_api)
        api.start(); self.addCleanup(api.stop)
    def inspect(self): return identity.inspect_identity(self.root, self.docker, lambda: self.reader)
    def rejected(self, code):
        with self.assertRaisesRegex(identity.ActivationError, '^'+code+'$'): self.inspect()

    def test_verified_current_init_is_not_future_credential_binding(self):
        value = self.inspect(); text = json.dumps(value)
        self.assertEqual(value['identity_readiness'], 'verified'); self.assertEqual(value['verified_process_count'], 2)
        self.assertTrue(value['observer_identity_mapping_verified'])
        api, db = value['processes']['camera-api'], value['processes']['camera-db']
        self.assertEqual((api['effective_uid'], db['effective_uid']), (65532, 999))
        self.assertTrue(api['actual_execution_uid_verified']); self.assertTrue(db['container_uid_mapping_verified'])
        self.assertEqual(api['identity_scope'], 'current-container-init-process')
        self.assertFalse(value['activation_allowed']); self.assertFalse(value['production_supply_ready'])
        self.assertEqual(value['schema_version'], 7)
        self.assertTrue(all(value[k] is False for k in identity.NO_CHANGES))
        for secret in (TOKEN, API_ID, DB_ID, 'SYNTHETIC_KEY_BYTES', 'synthetic-start', '"signature":', '"uid_map":', '"pid":'):
            self.assertNotIn(secret, text)
        self.assertFalse((self.root/identity.REPORT).exists())

    def test_server_review_acceptance_required_before_docker(self):
        path = self.root/'project-manifest.json'; value = json.loads(path.read_text())
        value['credential_production_supply_review_server_verified'] = False; path.write_text(json.dumps(value))
        self.rejected('ACCEPTED_SUPPLY_REVIEW_REQUIRED'); self.assertEqual(self.docker.calls, [])

    def test_changed_inspector_source_rejected_before_docker(self):
        (self.root/'src/infra/tools/inspect_camera_credential_identity.py').write_text('synthetic edit')
        self.rejected('SOURCE_FILE_CHANGED'); self.assertEqual(self.docker.calls, [])

    def test_observer_namespace_or_permissions_block_both_without_target_reads(self):
        for error in (identity.IdentityBlocked('OBSERVER_IDENTITY_MAP_UNSUPPORTED'),
            identity.IdentityBlocked('HOST_PROCFS_PID_VIEW_UNSUPPORTED'), OSError(errno.EACCES, TOKEN)):
            with self.subTest(error=type(error)):
                self.reader = FakeReader(); self.reader.observer_error = error
                value = self.inspect(); self.assertEqual(value['verified_process_count'], 0)
                self.assertEqual(self.reader.calls, ['observer']); self.assertNotIn(TOKEN, json.dumps(value))
                self.assertFalse(value['observer_identity_mapping_verified'])

    def test_procfs_open_permission_and_missing_host_view_stay_blocked(self):
        for code in (errno.ENOENT, errno.EPERM):
            self.reader = FakeReader(); self.reader.enter_error = OSError(code, TOKEN)
            value = self.inspect(); self.assertEqual(value['identity_readiness'], 'blocked')
            self.assertEqual(value['verified_process_count'], 0); self.assertNotIn(TOKEN, json.dumps(value))

    def test_one_unreadable_process_preserves_only_other_verified_result(self):
        self.reader.records[102] = OSError(errno.EACCES, TOKEN)
        value = self.inspect(); self.assertEqual(value['verified_process_count'], 1)
        self.assertEqual(value['processes']['camera-db']['code'], 'HOST_PROCESS_METADATA_PERMISSION_REQUIRED')
        self.assertIsNone(value['processes']['camera-db']['effective_uid'])
        self.assertTrue(value['processes']['camera-api']['actual_execution_uid_verified'])

    def test_target_partial_uid_or_gid_map_stays_unverified(self):
        for name in ('uid_map', 'gid_map'):
            self.reader = FakeReader(); self.reader.records[101][name] = ((0, 100000, 65536),)
            value = self.inspect(); self.assertEqual(value['verified_process_count'], 1)
            self.assertEqual(value['processes']['camera-api']['code'], 'CONTAINER_IDENTITY_MAP_UNSUPPORTED')

    def test_unrecognized_cgroup_or_other_container_cannot_verify_local_pid(self):
        for raw in (b'0::/\n', ('0::/docker/'+'f'*64+'\n').encode(), ('0::/docker/'+API_ID[:12]+'\n').encode()):
            self.reader.records[101]['cgroup'] = raw
            value = self.inspect(); self.assertEqual(value['verified_process_count'], 1)
            self.assertEqual(value['processes']['camera-api']['code'], 'HOST_CONTAINER_CGROUP_CORRELATION_UNAVAILABLE')

    def test_worker_in_same_container_is_not_accepted_as_init(self):
        for ns in (None, (101,), (101, 2)):
            self.reader.records[101]['ids']['NSpid'] = ns
            value = self.inspect(); self.assertEqual(value['verified_process_count'], 1)
            self.assertEqual(value['processes']['camera-api']['code'], 'CONTAINER_INIT_PID_NAMESPACE_UNVERIFIED')

    def test_host_or_shared_container_pid_namespace_stays_blocked(self):
        for mode in ('host', 'container:'+DB_ID, None):
            self.docker.camera['HostConfig']['PidMode'] = mode
            value = self.inspect(); self.assertEqual(value['verified_process_count'], 1)
            self.assertEqual(value['processes']['camera-api']['code'], 'CONTAINER_PID_MODE_UNSUPPORTED')

    def test_host_proc_and_daemon_uid_disagreement_rejected(self):
        self.reader.records[101]['ids']['Uid'] = (0,)*4
        self.rejected('PROCESS_EFFECTIVE_IDENTITY_MISMATCH')

    def test_init_pid_invalid_missing_in_top_or_started_at_changed_rejected(self):
        for pid in (0, -1, True, '101', 4294967295):
            self.docker.camera['State']['Pid'] = pid; self.rejected('CONTAINER_PROCESS_PID_INVALID')
        self.docker.camera['State']['Pid'] = 9999; self.rejected('CONTAINER_INIT_PROCESS_NOT_IN_TOP')
        self.docker.camera['State']['Pid'] = 101
        self.docker.camera['State']['StartedAt'] = 'changed'; self.rejected('CONTAINER_PROCESS_STATE_MISMATCH')

    def test_init_start_time_inode_and_ids_changes_rejected(self):
        for mutate in (lambda v: v.update(signature=(1, 5101, 9999)),
            lambda v: v.update(signature=(1, 99999, 1101)),
            lambda v: v['ids'].update(Gid=(0,)*4)):
            self.reader = FakeReader()
            self.reader.after_read = lambda pid: mutate(self.reader.records[101]) if pid == 101 else None
            self.rejected('PROCESS_CHANGED_DURING_INSPECTION')

    def test_recheck_permission_loss_is_failure_and_cannot_leave_verified_result(self):
        self.reader.after_read = lambda pid: self.reader.records.update({pid: OSError(errno.EACCES, TOKEN)})
        self.rejected('PROCESS_METADATA_UNAVAILABLE_DURING_RECHECK')

    def test_observer_identity_drift_rejected(self):
        self.reader.after_read = lambda pid: self.reader.observer_record.update(signature=(1, 5100, 9999))
        self.rejected('OBSERVER_PROCESS_CHANGED_DURING_INSPECTION')

    def test_docker_init_pid_drift_rejected(self):
        self.reader.after_read = lambda pid: self.docker.camera['State'].update(Pid=9999)
        self.rejected('PROCESS_CHANGED_DURING_INSPECTION')

    def test_final_top_uid_drift_rejected_but_transient_worker_count_allowed(self):
        self.reader.after_read = lambda pid: self.docker.top.update({API_ID: b'PID EUID EGID\n101 0 0\n'})
        self.rejected('PROCESS_CHANGED_DURING_INSPECTION')
        self.docker = FakeDocker(self.root); self.reader = FakeReader()
        self.reader.after_read = lambda pid: self.docker.top.update({DB_ID: b'PID EUID EGID\n102 999 999\n'})
        self.assertEqual(self.inspect()['identity_readiness'], 'verified')

    def test_environment_receipt_and_key_metadata_drift_rejected(self):
        for name, code in (('.env', 'INSPECTION_INPUT_CHANGED'), (identity.inventory.RECEIPT, 'INSPECTION_INPUT_CHANGED'),
            (identity.inventory.KEY, 'KEY_METADATA_CHANGED_DURING_INSPECTION')):
            with self.subTest(name=name):
                path = self.root/name; original = path.read_bytes()
                self.reader = FakeReader(); self.reader.after_read = lambda pid: path.write_bytes(b'SYNTHETIC_CHANGED')
                self.rejected(code); path.write_bytes(original)

    def test_source_and_container_recreation_during_proc_read_rejected(self):
        path = self.root/'src/infra/tools/inspect_camera_credential_identity.py'
        original = path.read_bytes()
        self.reader.after_read = lambda pid: path.write_bytes(b'SYNTHETIC_CHANGED')
        self.rejected('SOURCE_FILE_CHANGED'); path.write_bytes(original)
        self.reader = FakeReader()
        self.reader.after_read = lambda pid: self.docker.before['camera-api'].update(id='f'*64)
        self.rejected('PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')

    def test_key_material_never_opened_and_only_existing_read_only_sql_exec_reused(self):
        def guard(original):
            def call(path, *args, **kwargs):
                self.assertNotIn(str(path), ('key-bundle.json', str(self.root/identity.inventory.KEY)))
                return original(path, *args, **kwargs)
            return call
        with patch.object(os, 'open', side_effect=guard(os.open)), patch.object(io, 'open', side_effect=guard(io.open)), \
            patch.object(builtins, 'open', side_effect=guard(builtins.open)):
            self.inspect()
        calls = [x for x in self.docker.calls if isinstance(x, list) and x[0] == 'exec']
        self.assertEqual(calls, [['exec', DB_ID, *identity.inventory.SQL_ARGS, identity.inventory.READ_ONLY_SQL]])

    def test_private_report_replaces_stale_success_and_preserves_existing_reports_and_review(self):
        protected = {}
        for name in (identity.inventory.REPORT, identity.facts.REPORT, identity.review.DIRECTORY+'/review-synthetic.json'):
            p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'SYNTHETIC_OLD_REPORT')
            protected[p] = (p.read_bytes(), p.stat().st_mtime_ns)
        probe = identity.inspect_identity
        with patch.object(identity.facts, 'FactsDocker', return_value=self.docker), \
            patch.object(identity, 'inspect_identity', side_effect=lambda root, docker: probe(root, docker, lambda: self.reader)):
            self.assertEqual(identity.run_inspection(self.root)['identity_readiness'], 'verified')
        with patch.object(identity.facts, 'FactsDocker', return_value=self.docker), \
            patch.object(identity, 'inspect_identity', side_effect=identity.ActivationError('BAD_RESULT: '+TOKEN)):
            with self.assertRaises(identity.ActivationError): identity.run_inspection(self.root)
        report = self.root/identity.REPORT; value = json.loads(report.read_text())
        self.assertEqual(value['status'], 'failed'); self.assertEqual(value['code'], 'BAD_RESULT')
        self.assertFalse(value['activation_allowed']); self.assertNotIn(TOKEN, report.read_text())
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        for p, before in protected.items(): self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)


class MetadataParserAndReaderTest(unittest.TestCase):
    def test_full_and_partial_maps_parse_without_guessing_translation(self):
        self.assertEqual(identity.id_map(b'         0          0 4294967295\n'), identity.FULL_MAP)
        self.assertEqual(identity.id_map(b'0 100000 65536\n'), ((0, 100000, 65536),))
        for raw in (b'', b'0 0 0\n', b'0 0 4294967296\n', b'1 0 4294967295\n', b'0 0 10\n9 20 1\n',
            b'0 0 10\n20 9 1\n', b'root root 1\n', b'0 0 1 extra\n', b'\xff', b'x'*16385):
            with self.subTest(raw=raw[:50]), self.assertRaises(identity.ActivationError): identity.id_map(raw)

    def test_status_requires_unique_numeric_real_effective_saved_filesystem_ids(self):
        self.assertEqual(identity.status_ids(b'Name:\tignored\nUid:\t1 2 3 4\nGid:\t5 6 7 8\n')['Uid'], (1,2,3,4))
        for raw in (b'Uid: 1 2 3\nGid: 4 5 6 7\n', b'Uid: 1 2 3 4\nUid: 1 2 3 4\nGid: 1 2 3 4\n',
            b'Uid: 1 2 3 4294967295\nGid: 1 2 3 4\n', b'Uid: 1 -2 3 4\nGid: 1 2 3 4\n'):
            with self.assertRaises(identity.ActivationError): identity.status_ids(raw)

    def test_proc_status_pid_and_namespace_chain_are_bound_to_requested_pid(self):
        body = b'Uid: 999 999 999 999\nGid: 999 999 999 999\nPid: 102\nNSpid: 102 1\n'
        self.assertEqual(identity.process_status(body, 102)['NSpid'], (102, 1))
        for raw in (body.replace(b'Pid: 102\n', b'Pid: 103\n'), body.replace(b'NSpid: 102', b'NSpid: 103'),
            body.replace(b'NSpid: 102 1', b'NSpid: 102 0'), body+b'NSpid: 102 1\n'):
            with self.assertRaises(identity.ActivationError): identity.process_status(raw, 102)

    def test_stat_discards_complex_comm_and_detects_zombie_wrong_pid_or_bad_start_time(self):
        raw = b'101 (synthetic ) nested(name)) S '+b'0 '*18+b'12345 0 0\n'
        self.assertEqual(identity.start_time(raw, 101), 12345)
        for body in (raw.replace(b' S ', b' Z '), raw.replace(b'12345', b'0'), raw.replace(b'101 (', b'102 ('), b'101 (short) S 1'):
            with self.assertRaises(identity.ActivationError): identity.start_time(body, 101)

    def test_cgroup_v1_v2_require_full_exact_container_component(self):
        for path in ('/docker/'+API_ID, '/system.slice/docker-'+API_ID+'.scope', '/custom/docker/'+API_ID+'/child'):
            self.assertTrue(identity.container_cgroup(('0::'+path+'\n').encode(), API_ID))
        self.assertTrue(identity.container_cgroup(('2:cpu,cpuacct:/docker/'+API_ID+'\n').encode(), API_ID))
        self.assertFalse(identity.container_cgroup(('0::/docker/prefix'+API_ID+'\n').encode(), API_ID))
        for raw in (b'0::/a/../b\n', b'0:://docker/id\n', b'0::/docker/id/\n', b'bad::/\n', b'0::/\x00\n'):
            with self.assertRaises(identity.ActivationError): identity.container_cgroup(raw, API_ID)

    def test_reader_rejects_secret_and_arbitrary_process_metadata_names_before_open(self):
        reader = identity.ProcReader()
        with patch.object(os, 'open') as opened:
            for name in ('environ', 'cmdline', 'mem', 'root', 'exe', 'fd', '../status', '/etc/passwd'):
                with self.assertRaises(identity.ActivationError): reader.read(-1, name)
            opened.assert_not_called()

    def test_non_procfs_root_rejected_and_fd_closed(self):
        with patch.object(identity, 'procfs_fd', return_value=False), patch.object(os, 'open', return_value=123), \
            patch.object(os, 'close') as closed:
            with self.assertRaisesRegex(identity.IdentityBlocked, '^HOST_PROCFS_UNAVAILABLE$'):
                with identity.ProcReader(): pass
            closed.assert_called_once_with(123)

    def test_proc_file_symlink_rejected_without_following(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary); (p/'secret').write_bytes(b'SYNTHETIC_SECRET'); (p/'status').symlink_to('secret')
            fd = os.open(p, os.O_RDONLY|os.O_DIRECTORY)
            try:
                with self.assertRaises(OSError): identity.ProcReader().read(fd, 'status')
            finally: os.close(fd)

    def test_real_observer_rejects_partial_maps_and_pid_view_mismatch(self):
        reader = identity.ProcReader(); reader.fd = -1
        value = record(os.getpid(), os.geteuid(), os.getegid(), API_ID)
        with patch.object(os, 'readlink', return_value=str(os.getpid())), patch.object(reader, 'process', return_value=value):
            self.assertEqual(reader.observer(), value)
            value['gid_map'] = ((0, 0, 1),)
            with self.assertRaisesRegex(identity.IdentityBlocked, '^OBSERVER_IDENTITY_MAP_UNSUPPORTED$'): reader.observer()
        with patch.object(os, 'readlink', return_value=str(os.getpid()+1)), patch.object(reader, 'process') as process:
            with self.assertRaisesRegex(identity.IdentityBlocked, '^HOST_PROCFS_PID_VIEW_UNSUPPORTED$'): reader.observer()
            process.assert_not_called()

    def test_bounded_reader_rejects_non_procfs_file_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary); (path/'status').write_bytes(b'x'*65537)
            fd = os.open(path, os.O_RDONLY|os.O_DIRECTORY)
            try:
                with self.assertRaisesRegex(identity.ActivationError, '^PROCESS_METADATA_FILE_INVALID$'):
                    identity.ProcReader().read(fd, 'status')
                with patch.object(identity, 'procfs_fd', return_value=True), \
                    self.assertRaisesRegex(identity.ActivationError, '^PROCESS_METADATA_FILE_INVALID$'):
                    identity.ProcReader().read(fd, 'status')
            finally: os.close(fd)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux procfs required')
    def test_native_procfs_bounded_metadata_and_observer_scope(self):
        opened = []; original = os.open
        def tracking(path, flags, *args, **kwargs):
            opened.append((str(path), flags)); return original(path, flags, *args, **kwargs)
        with patch.object(os, 'open', side_effect=tracking), identity.ProcReader() as reader:
            alias = os.readlink('self', dir_fd=reader.fd)
            value = reader.process(int(alias))
            self.assertEqual(value['ids']['Uid'][1], os.geteuid())
            self.assertEqual(value['ids']['Gid'][1], os.getegid())
            expected = alias == str(os.getpid()) and value['uid_map'] == identity.FULL_MAP and value['gid_map'] == identity.FULL_MAP
            if expected: self.assertEqual(reader.observer(), value)
            else:
                with self.assertRaises(identity.IdentityBlocked): reader.observer()
        self.assertTrue(all(not flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC) for _, flags in opened))
        self.assertTrue(all(name == '/proc' or name.isdecimal() or name in identity.LIMITS for name, _ in opened))


if __name__ == '__main__': unittest.main()
