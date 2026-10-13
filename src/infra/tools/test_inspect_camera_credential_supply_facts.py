"""Read-only planning-fact boundaries using synthetic registry/Docker metadata."""
import builtins
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import inspect_camera_credential_supply_facts as facts
import test_inspect_camera_credential_supply as legacy

NETWORK_ID = 'e'*64
KEY_MARKER = 'SYNTHETIC_KEY_BYTES_NEVER_PARSED_OR_HASHED'


def fixture(root):
    legacy.fixture(root)
    p = root/'project-manifest.json'; manifest = json.loads(p.read_text())
    names = ('src/infra/tools/inspect_camera_credential_supply_facts.py',
        'src/platform/camera/api/planned/credential-supply.schema.json',
        'src/platform/camera/api/planned/credential_supply_contract.py')
    for name in names:
        target = root/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((legacy.SOURCE/name).read_bytes())
        manifest['files'][name] = facts.sha(target)
    manifest.update(credential_production_supply_plan_contract_implemented=True,
        credential_production_supply_plan_contract_server_verified=True,
        validated_credential_production_supply_plan_contract_project_sha256=facts.ACCEPTED_CONTRACT,
        credential_production_supply_facts_implemented=True)
    p.write_text(json.dumps(manifest))


class FakeDocker(legacy.FakeDocker):
    def __init__(self, root):
        super().__init__(root)
        self.camera['Image'] = legacy.API_IMAGE
        self.db['Image'] = legacy.DB_IMAGE
        self.db['HostConfig'] = {}
        for service, ip in ((self.camera, '172.22.0.2'), (self.db, '172.22.0.3')):
            service['HostConfig']['UsernsMode'] = ''
            service['NetworkSettings'] = {'Networks': {'vms-project_camera-storage': {
                'NetworkID': NETWORK_ID, 'IPAddress': ip, 'IPPrefixLen': 16,
                'GlobalIPv6Address': '', 'GlobalIPv6PrefixLen': 0}}}
        self.db['Mounts'][0].update(Source='/var/lib/docker/volumes/vms-project_camera-data/_data', RW=True)
        self.network = {'Id': NETWORK_ID, 'Name': 'vms-project_camera-storage', 'Scope': 'local',
            'Driver': 'bridge', 'Internal': True, 'Labels': {'com.docker.compose.project': 'vms-project',
            'com.docker.compose.network': 'camera-storage'}, 'IPAM': {'Config': [
            {'Subnet': '172.22.0.0/16', 'Gateway': '172.22.0.1'}]}, 'Containers': {
            legacy.API_ID: {'Name': legacy.TOKEN, 'IPv4Address': '172.22.0.2/16', 'IPv6Address': ''},
            legacy.DB_ID: {'Name': 'synthetic-db', 'IPv4Address': '172.22.0.3/16', 'IPv6Address': ''}}}
        self.top = {legacy.API_ID: b' PID EUID EGID\n 101 65532 65532\n',
                    legacy.DB_ID: b'PID EUID EGID\n102 999 999\n103 999 999\n'}
        self.security = ['name=seccomp,profile=builtin', 'name=cgroupns']
        self.network_calls = 0; self.top_calls = {}
        self.after_first_network = lambda: None
        self.before_second_top = lambda cid: None

    def run(self, args, **kwargs):
        if args == ['network', 'inspect', NETWORK_ID]:
            self.calls.append(args); self.network_calls += 1
            value = json.dumps([self.network]).encode()
            if self.network_calls == 1: self.after_first_network()
            return value
        if args == facts.SECURITY_ARGS:
            self.calls.append(args); return json.dumps(self.security).encode()
        if len(args) == 4 and args[0] == 'top':
            self.calls.append(args); cid = args[1]
            assert args[2:] == ['-eo', 'pid,euid,egid']
            self.top_calls[cid] = self.top_calls.get(cid, 0)+1
            if self.top_calls[cid] == 2: self.before_second_top(cid)
            return self.top[cid]
        return super().run(args, **kwargs)


class SupplyFactsTest(unittest.TestCase):
    read_api = legacy.SupplyInspectionTest.read_api

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'; self.root.mkdir()
        fixture(self.root); self.docker = FakeDocker(self.root)
        api = patch.object(facts.inventory, 'read_api', side_effect=self.read_api)
        api.start(); self.addCleanup(api.stop)

    def inspect(self): return facts.inspect_facts(self.root, self.docker)

    def rejected(self, code):
        with self.assertRaisesRegex(facts.ActivationError, '^'+code+'$'): self.inspect()

    def test_facts_remain_unapproved_and_do_not_expose_secrets(self):
        value = self.inspect(); text = json.dumps(value)
        self.assertEqual(value['status'], 'inspected'); self.assertEqual(value['plan_state'], 'incomplete')
        self.assertEqual(value['readiness'], 'blocked'); self.assertFalse(value['activation_allowed'])
        self.assertEqual(value['host_key_bundle']['owner_uid'], os.getuid())
        self.assertEqual(value['host_key_bundle']['owner_gid'], os.getgid())
        self.assertFalse(value['host_key_bundle']['key_material_integrity_verified'])
        self.assertEqual(value['processes']['camera-db']['effective_identities'], [{'uid': 999, 'gid': 999}])
        self.assertEqual(value['processes']['camera-api']['identity_namespace'], 'docker-daemon-host')
        self.assertFalse(value['processes']['camera-api']['actual_execution_uid_verified'])
        self.assertFalse(value['database_volume']['local_host_path_verified'])
        self.assertFalse(value['storage_network']['source_binding_approved'])
        self.assertEqual(len(value['unresolved_inputs']), 9)
        self.assertTrue(all(value[k] is False for k in facts.NO_CHANGES))
        self.assertNotIn(legacy.TOKEN, text); self.assertNotIn(KEY_MARKER, text)
        self.assertFalse((self.root/facts.REPORT).exists())

    def test_source_gate_requires_server_contract_acceptance(self):
        p = self.root/'project-manifest.json'; value = json.loads(p.read_text())
        value['credential_production_supply_plan_contract_server_verified'] = False
        p.write_text(json.dumps(value)); self.rejected('ACCEPTED_SUPPLY_CONTRACT_REQUIRED')
        self.assertEqual(self.docker.calls, [])

    def test_changed_facts_source_rejected_before_docker(self):
        (self.root/'src/infra/tools/inspect_camera_credential_supply_facts.py').write_text('synthetic edit')
        self.rejected('SOURCE_FILE_CHANGED'); self.assertEqual(self.docker.calls, [])

    def test_key_file_contents_are_never_opened(self):
        def guarded(original):
            def call(path, *args, **kwargs):
                self.assertNotIn(str(path), ('key-bundle.json', str(self.root/facts.inventory.KEY)))
                return original(path, *args, **kwargs)
            return call
        with patch.object(os, 'open', side_effect=guarded(os.open)), \
                patch.object(io, 'open', side_effect=guarded(io.open)), \
                patch.object(builtins, 'open', side_effect=guarded(builtins.open)):
            self.assertEqual(self.inspect()['host_key_bundle']['status'], 'metadata_valid')

    def test_declared_volume_path_is_never_traversed(self):
        original = Path.stat
        def guarded(path, *args, **kwargs):
            self.assertFalse(str(path).startswith('/var/lib/docker'))
            return original(path, *args, **kwargs)
        with patch.object(Path, 'stat', guarded): self.inspect()

    def test_missing_key_owner_stays_unknown_without_creation(self):
        key = self.root/facts.inventory.KEY; key.unlink()
        value = self.inspect(); self.assertIsNone(value['host_key_bundle']['owner_uid'])
        self.assertIn('HOST_KEY_BUNDLE_MISSING', value['inventory']['blockers'])
        self.assertFalse(key.exists())

    def test_process_count_may_change_without_identity_change(self):
        self.docker.before_second_top = lambda cid: self.docker.top.update({cid: self.docker.top[cid]+b'104 999 999\n'}) if cid == legacy.DB_ID else None
        self.assertEqual(self.inspect()['processes']['camera-db']['process_count'], 2)

    def test_transient_process_identity_is_observed_without_uid_verification(self):
        self.docker.before_second_top = lambda cid: self.docker.top.update({cid: b'PID EUID EGID\n101 0 0\n'})
        value = self.inspect()['processes']['camera-db']
        self.assertFalse(value['identities_stable_across_observations'])
        self.assertEqual(value['end_effective_identities'], [{'uid': 0, 'gid': 0}])
        self.assertFalse(value['actual_execution_uid_verified'])

    def test_rootless_and_userns_are_observations_without_uid_mapping_proof(self):
        self.docker.security = ['name=rootless', 'name=userns']
        value = self.inspect()
        self.assertTrue(value['daemon_security']['rootless_declared'])
        self.assertTrue(value['daemon_security']['userns_remap_declared'])
        self.assertFalse(value['daemon_security']['container_uid_mapping_verified'])
        self.assertFalse(value['processes']['camera-db']['actual_execution_uid_verified'])

    def test_unsafe_volume_paths_rejected(self):
        for path in ('relative', '/', '//host/share', '/a/../b', '/a//b', '/a\nsecret', '/a\\b'):
            with self.subTest(path=path):
                self.docker.db['Mounts'][0]['Source'] = path
                self.rejected('DATABASE_VOLUME_HOST_PATH_INVALID')

    def test_readonly_or_ambiguous_database_mount_rejected(self):
        self.docker.db['Mounts'][0]['RW'] = False; self.rejected('DATABASE_VOLUME_FACTS_MISMATCH')
        self.docker.db['Mounts'][0]['RW'] = True
        self.docker.db['Mounts'].append(copy.deepcopy(self.docker.db['Mounts'][0]))
        self.rejected('DATABASE_VOLUME_FACTS_MISMATCH')

    def test_external_network_rejected_before_network_inspection(self):
        self.docker.network['Internal'] = False; self.rejected('OWNED_INTERNAL_STORAGE_NETWORK_REQUIRED')

    def test_network_project_or_name_mismatch_rejected(self):
        for field, replacement in (('Name', 'synthetic-other'), ('Id', 'f'*64)):
            with self.subTest(field=field):
                old = self.docker.network[field]; self.docker.network[field] = replacement
                self.rejected('OWNED_INTERNAL_STORAGE_NETWORK_REQUIRED'); self.docker.network[field] = old
        self.docker.network['Labels']['com.docker.compose.project'] = 'other'
        self.rejected('OWNED_INTERNAL_STORAGE_NETWORK_REQUIRED')

    def test_peer_attachment_and_inspected_endpoint_must_agree(self):
        self.docker.network['Containers'][legacy.API_ID]['IPv4Address'] = '172.22.0.4/16'
        self.rejected('NETWORK_ENDPOINT_MISMATCH')

    def test_network_address_and_subnet_malformed_rejected(self):
        entry = self.docker.camera['NetworkSettings']['Networks']['vms-project_camera-storage']
        for ip in ('127.0.0.1', '172.022.0.2', 'host.example', '::1', '0.0.0.0', '224.0.0.1'):
            with self.subTest(ip=ip):
                entry['IPAddress'] = ip; self.rejected('NETWORK_ADDRESS_INVALID')
        entry['IPAddress'] = '172.22.0.2'
        self.docker.network['IPAM']['Config'][0]['Subnet'] = '172.22.0.3/16'
        self.rejected('NETWORK_SUBNET_INVALID')

    def test_ipv6_observation_is_supported_without_approval(self):
        for service, cid, ip in ((self.docker.camera, legacy.API_ID, '2001:db8::2'),
                                (self.docker.db, legacy.DB_ID, '2001:db8::3')):
            entry = service['NetworkSettings']['Networks']['vms-project_camera-storage']
            entry.update(IPAddress='', IPPrefixLen=0, GlobalIPv6Address=ip, GlobalIPv6PrefixLen=64)
            self.docker.network['Containers'][cid].update(IPv4Address='', IPv6Address=ip+'/64')
        self.docker.network['IPAM']['Config'] = [{'Subnet': '2001:db8::/64', 'Gateway': '2001:db8::1'}]
        value = self.inspect(); self.assertFalse(value['storage_network']['source_binding_approved'])
        self.assertEqual(value['storage_network']['observed_container_addresses']['camera-db']['ipv6'], '2001:db8::3/64')

    def test_other_peer_names_are_not_returned(self):
        self.docker.network['Containers']['f'*64] = {'Name': legacy.TOKEN, 'IPv4Address': '172.22.0.4/16', 'IPv6Address': ''}
        value = self.inspect(); self.assertEqual(value['storage_network']['other_attached_container_count'], 1)
        self.assertNotIn(legacy.TOKEN, json.dumps(value))

    def test_network_membership_drift_rejected(self):
        self.docker.after_first_network = lambda: self.docker.network['Containers'].update({'f'*64: {'Name': 'synthetic'}})
        self.rejected('SUPPLY_FACTS_TOPOLOGY_CHANGED')

    def test_volume_source_drift_rejected(self):
        self.docker.after_first_network = lambda: self.docker.db['Mounts'][0].update(Source='/synthetic/other')
        self.rejected('SUPPLY_FACTS_TOPOLOGY_CHANGED')

    def test_failed_network_read_reports_fixed_stage_without_detail(self):
        original = self.docker.run
        def fail(args, **kwargs):
            if args == ['network', 'inspect', NETWORK_ID]:
                raise facts.ActivationError('READ_ONLY_DOCKER_COMMAND_UNAVAILABLE: '+legacy.TOKEN)
            return original(args, **kwargs)
        self.docker.run = fail
        with patch.object(facts, 'FactsDocker', return_value=self.docker):
            with self.assertRaises(facts.ActivationError): facts.run_inspection(self.root)
        text = (self.root/facts.REPORT).read_text(); value = json.loads(text)
        self.assertEqual(value['failed_stage'], 'owned_storage_network')
        self.assertEqual(value['code'], 'READ_ONLY_DOCKER_COMMAND_UNAVAILABLE')
        self.assertNotIn(legacy.TOKEN, text)

    def test_environment_or_receipt_change_after_inventory_rejected(self):
        for name in ('.env', facts.inventory.RECEIPT):
            with self.subTest(name=name):
                self.docker = FakeDocker(self.root)
                p = self.root/name; original = p.read_bytes()
                self.docker.after_first_network = lambda: p.write_bytes(b'SYNTHETIC_CHANGED')
                self.rejected('INSPECTION_INPUT_CHANGED'); p.write_bytes(original)

    def test_key_metadata_change_after_inventory_rejected(self):
        self.docker.after_first_network = lambda: (self.root/facts.inventory.KEY).write_bytes(b'SYNTHETIC_CHANGED')
        self.rejected('KEY_METADATA_CHANGED_DURING_INSPECTION')

    def test_container_recreation_after_inventory_rejected(self):
        self.docker.after_first_network = lambda: self.docker.before['camera-api'].update(id='f'*64)
        self.rejected('PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')

    def test_private_report_does_not_overwrite_old_preflight_or_protected_inputs(self):
        old_report = self.root/facts.inventory.REPORT; old_report.write_bytes(b'SYNTHETIC_OLD_REPORT'); old_report.chmod(0o600)
        protected = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in
            (old_report, self.root/facts.inventory.KEY, self.root/'.env', self.root/facts.inventory.RECEIPT)}
        with patch.object(facts, 'FactsDocker', side_effect=lambda root: FakeDocker(root)):
            for _ in range(2): self.assertEqual(facts.run_inspection(self.root)['status'], 'inspected')
        self.assertEqual((self.root/facts.REPORT).stat().st_mode & 0o777, 0o600)
        for p, state in protected.items(): self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), state)

    def test_failed_report_cannot_keep_old_success_or_disclose_exception_text(self):
        with patch.object(facts, 'FactsDocker', return_value=self.docker), \
                patch.object(facts, 'inspect_facts', side_effect=facts.ActivationError('BAD_RESULT: '+legacy.TOKEN)):
            with self.assertRaises(facts.ActivationError): facts.run_inspection(self.root)
        p = self.root/facts.REPORT; value = json.loads(p.read_text())
        self.assertEqual(value['status'], 'failed'); self.assertEqual(value['code'], 'BAD_RESULT')
        self.assertFalse(value['activation_allowed']); self.assertNotIn(legacy.TOKEN, p.read_text())
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)


class FactsParsingAndAllowlistTest(unittest.TestCase):
    def test_non_numeric_wrong_header_and_oversized_process_output_rejected(self):
        bodies = (b'UID GID CMD\n999 999 secret\n', b'PID EUID EGID\n101 postgres postgres\n',
            b'PID EUID EGID\n', b'PID EUID EGID\n101 -1 1\n', b'PID EUID EGID\n101 4294967295 1\n',
            b'PID EUID EGID\n101 999 999 secret\n', b'PID EUID EGID\n0 999 999\n',
            b'PID EUID EGID\n101 999 999\n101 999 999\n', b'EUID EGID\n999 999\n', b'x'*1048577)
        for body in bodies:
            with self.subTest(body=body[:64]), self.assertRaises(facts.ActivationError): facts.process_identities(body)

    def test_top_and_network_reads_require_reviewed_exact_ids(self):
        docker = facts.FactsDocker(Path('/synthetic-project'))
        top = ['top', legacy.API_ID, '-eo', 'pid,euid,egid']
        net = ['network', 'inspect', NETWORK_ID]
        with patch.object(facts.Docker, 'run', return_value=b'synthetic') as run:
            for args in (top, net):
                with self.assertRaises(facts.ActivationError): docker.run(args)
            run.assert_not_called()
            docker.reviewed_container_ids = {legacy.API_ID}; docker.reviewed_network_id = NETWORK_ID
            self.assertEqual(docker.run(top), b'synthetic'); self.assertEqual(docker.run(net), b'synthetic')
            self.assertEqual(run.call_count, 2)

    def test_commands_that_expose_args_or_mutate_network_rejected(self):
        docker = facts.FactsDocker(Path('/synthetic-project'))
        docker.reviewed_container_ids = {legacy.API_ID}; docker.reviewed_network_id = NETWORK_ID
        commands = (['top', legacy.API_ID], ['top', legacy.API_ID, '-eo', 'pid,euid,egid,args'],
            ['exec', legacy.API_ID, 'id'], ['network', 'inspect', 'vms-project_camera-storage'],
            ['network', 'connect', NETWORK_ID, legacy.API_ID], ['network', 'create', 'synthetic'],
            ['info'], ['restart', legacy.API_ID])
        with patch.object(facts.Docker, 'run') as run:
            for args in commands:
                with self.subTest(args=args), self.assertRaises(facts.ActivationError): docker.run(args)
            run.assert_not_called()

    def test_new_read_commands_reject_input_environment_and_redirect(self):
        docker = facts.FactsDocker(Path('/synthetic-project')); docker.reviewed_container_ids = {legacy.API_ID}
        with patch.object(facts.Docker, 'run') as run:
            for kwargs in ({'input': b''}, {'extra': {'SYNTHETIC': 'secret'}}, {'stdout': 1}, {'unknown': 1}):
                with self.subTest(kwargs=kwargs), self.assertRaises(facts.ActivationError):
                    docker.run(['top', legacy.API_ID, '-eo', 'pid,euid,egid'], **kwargs)
            run.assert_not_called()

    def test_read_errors_drop_docker_stderr(self):
        docker = facts.FactsDocker(Path('/synthetic-project'))
        with patch.object(facts.Docker, 'run', side_effect=facts.ActivationError('FAILED: '+legacy.TOKEN)):
            with self.assertRaisesRegex(facts.ActivationError, '^READ_ONLY_DOCKER_COMMAND_UNAVAILABLE$'):
                docker.run(facts.SECURITY_ARGS)

    def test_security_options_are_bounded_and_not_echoed(self):
        self.assertFalse(facts.daemon_security(json.dumps(['name=other,detail='+legacy.TOKEN]))['rootless_declared'])
        with self.assertRaises(facts.ActivationError): facts.daemon_security(b'{}')
        with self.assertRaises(facts.ActivationError): facts.daemon_security(json.dumps(['x'*257]))

    @unittest.skipUnless(os.name == 'posix' and Path('/proc/self').exists(), 'native Linux ps required')
    def test_native_numeric_ps_format_without_retaining_pid(self):
        raw = subprocess.check_output(['ps', '-eo', 'pid,euid,egid'], timeout=5)
        value = facts.process_identities(raw)
        self.assertIn({'uid': os.geteuid(), 'gid': os.getegid()}, value['effective_identities'])
        self.assertGreater(value['process_count'], 0); self.assertFalse(value['pids_retained'])
        self.assertNotIn('pid', value); self.assertNotIn('command', value)


if __name__ == '__main__': unittest.main()
