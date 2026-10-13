"""Real synthetic PKI and file failure checks; Docker interactions here are mocked."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import prepare_camera_database_tls_supply as tool


def fixture_network(project='vms-project'):
    ids = {'camera-db': 'd' * 64, 'camera-api': 'a' * 64}
    nid = 'b' * 64
    addresses = {'camera-db': '192.168.96.2', 'camera-api': '192.168.96.3'}
    objects = {service: {'Id': cid, 'NetworkSettings': {'Networks': {
        project + '_camera-storage': {'NetworkID': nid, 'IPAddress': addresses[service],
                                     'IPPrefixLen': 20, 'GlobalIPv6Address': ''}}}}
        for service, cid in ids.items()}
    value = {'Name': project + '_camera-storage', 'Id': nid, 'Driver': 'bridge', 'Scope': 'local',
        'Internal': True, 'EnableIPv6': False,
        'Labels': {'com.docker.compose.project': project, 'com.docker.compose.network': 'camera-storage'},
        'IPAM': {'Config': [{'Subnet': '192.168.96.0/20', 'Gateway': '192.168.96.1'}]},
        'Containers': {cid: {'IPv4Address': addresses[s] + '/20', 'IPv6Address': ''} for s, cid in ids.items()}}
    return value, objects


class FakeDocker:
    """Orchestration fixture; outputs never establish local native Docker acceptance."""
    project = 'vms-project'

    def __init__(self, root, snapshot):
        self.root, self.snapshot_bytes = root, snapshot
        self.values, self.commands, self.helpers = {}, [], []
        self.fail_initialize, self.fail_probe, self.changed_volume = None, None, False

    def volume(self, name, labels):
        value = self.values.get(name)
        if value is not None:
            tool.require(value['Labels'] == labels, 'TLS_SUPPLY_VOLUME_OWNERSHIP_MISMATCH')
        return value

    def run(self, args, **kwargs):
        self.commands.append(args)
        if args[:2] == ['volume', 'create']:
            labels = {}
            for index, item in enumerate(args):
                if item == '--label':
                    name, value = args[index + 1].split('=', 1); labels[name] = value
            self.values[args[-1]] = {'Name': args[-1], 'Labels': labels, 'CreatedAt': 'synthetic'}
            return args[-1].encode()
        if args[0] == 'compose':
            return (Path(args[args.index('-f') + 1])).read_bytes()
        if args[:2] == ['network', 'inspect']:
            return json.dumps([fixture_network()[0]]).encode()
        raise AssertionError(args)

    def helper(self, receipt, role, script, initialize=False, own_only=False):
        self.helpers.append((role, initialize, own_only))
        if initialize:
            if self.fail_initialize == role: raise tool.SupplyError('SYNTHETIC_INITIALIZER_INTERRUPTED')
            return b''
        if self.fail_probe == role: return b'TLS_SUPPLY_INCOMPLETE\n'
        result = ['TLS_SUPPLY_OK:' + role]
        result += [tool.candidate.sha(self.snapshot_bytes[name]) + '  ' + name for name in sorted(tool.ROLES[role][1])]
        if self.changed_volume:
            self.values[receipt['volume_names'][role]] = {
                **self.values[receipt['volume_names'][role]], 'CreatedAt': 'changed'}
        return ('\n'.join(result) + '\n').encode()

    def preflight(self): return 'synthetic-daemon'
    def snapshot(self): return {'camera-api': {'id': 'a' * 64}, 'camera-db': {'id': 'd' * 64}}


class TLSSupplyFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='tls-supply-template-')
        cls.template = Path(cls.temporary.name) / 'project'; cls.template.mkdir(mode=0o700)
        cls.first = tool.candidate.prepare(cls.template, True)
        cls.manifest = {'credential_tls_candidate_latest_server_' + k: cls.first[k]
            for k in ('candidate_sha256', 'server_certificate_sha256',
                      'maintenance_certificate_sha256', 'ca_pem_sha256')}

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tls-supply-case-'); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'; shutil.copytree(self.template, self.root)
        self.snapshot, self.proof = tool.read_candidate(self.root, self.manifest)
        self.raw, self.containers = fixture_network()
        self.proposal = json.loads(self.snapshot['candidate.json'])['endpoint_proposal']
        self.network = tool.network_recipe(json.dumps([self.raw]), 'vms-project', self.containers, self.proposal)
        self.receipt, self.wanted = tool.bundle(self.root, 'vms-project', 'sha256:' + 'f' * 64,
                                             self.network, self.snapshot, self.proof)
        self.path = self.root.joinpath(*tool.DIRECTORY, tool.SUPPLY)

    def test_real_accepted_key_pair_and_public_certificate_binding(self):
        self.assertTrue(self.proof['actual_socketpair_mtls_verified'])
        self.assertEqual(self.receipt['candidate_sha256'], self.first['candidate_sha256'])
        wrong = dict(self.manifest)
        wrong['credential_tls_candidate_latest_server_candidate_sha256'] = '0' * 64
        with self.assertRaisesRegex(tool.SupplyError, '^ACCEPTED_TLS_CANDIDATE_MISMATCH$'):
            tool.read_candidate(self.root, wrong)
        wrong = dict(self.manifest)
        wrong['credential_tls_candidate_latest_server_server_certificate_sha256'] = '0' * 64
        with self.assertRaisesRegex(tool.SupplyError, '^ACCEPTED_TLS_CERTIFICATE_MISMATCH$'):
            tool.read_candidate(self.root, wrong)

    def test_selected_exact_files_and_no_ca_signing_key_or_dsn(self):
        self.assertEqual(set(self.wanted), {'receipt.json', 'compose.recipe.json',
            'database/ca.pem', 'database/server.pem', 'database/server.key', 'runtime/ca.pem',
            'maintenance/ca.pem', 'maintenance/maintenance.pem', 'maintenance/maintenance.key'})
        for role, (_, names) in tool.ROLES.items():
            for name in names: self.assertEqual(self.wanted[role + '/' + name], self.snapshot[name])
        text = self.wanted['receipt.json'] + self.wanted['compose.recipe.json']
        self.assertNotIn(b'PRIVATE KEY', text)
        self.assertNotIn(self.snapshot['ca.key'], b''.join(self.wanted.values()))
        self.assertNotIn(b'postgres://', text)

    def test_create_replay_and_validate_preserve_bytes_modes_and_mtimes(self):
        before = {n: (self.root.joinpath(*tool.candidate.DIRECTORY, tool.candidate.CANDIDATE, n)).read_bytes()
                  for n in tool.candidate.FILES}
        self.assertTrue(tool.prepare_bundle(self.root, self.wanted, True))
        saved = {p.relative_to(self.path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns, stat.S_IMODE(p.stat().st_mode))
                 for p in self.path.rglob('*') if p.is_file()}
        self.assertFalse(tool.prepare_bundle(self.root, self.wanted, True))
        self.assertFalse(tool.prepare_bundle(self.root, self.wanted, False))
        self.assertEqual(saved, {p.relative_to(self.path).as_posix():
            (p.read_bytes(), p.stat().st_mtime_ns, stat.S_IMODE(p.stat().st_mode))
            for p in self.path.rglob('*') if p.is_file()})
        self.assertTrue(all(v[2] == 0o600 for v in saved.values()))
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in self.path.rglob('*') if p.is_dir()))
        self.assertEqual(before, {n: self.root.joinpath(*tool.candidate.DIRECTORY, tool.candidate.CANDIDATE, n).read_bytes()
                                  for n in tool.candidate.FILES})

    def test_without_apply_creates_no_supply_files(self):
        self.assertFalse(tool.prepare_bundle(self.root, self.wanted))
        self.assertFalse(self.root.joinpath(*tool.DIRECTORY).exists())

    def test_wrong_umask_still_creates_private_exact_modes(self):
        previous = os.umask(0o002)
        try: tool.prepare_bundle(self.root, self.wanted, True)
        finally: os.umask(previous)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.path / 'database/server.key').stat().st_mode), 0o600)

    def test_partial_bundle_is_rejected_without_repair(self):
        self.path.mkdir(parents=True, mode=0o700)
        self.path.parent.chmod(0o700)
        (self.path / 'user-file').write_bytes(b'UNMANAGED_SENTINEL')
        with self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_BUNDLE_INCOMPLETE_OR_UNKNOWN$'):
            tool.prepare_bundle(self.root, self.wanted, True)
        self.assertEqual(list(self.path.iterdir()), [self.path / 'user-file'])

    def test_corrupt_unknown_and_wrong_binding_cannot_be_overwritten(self):
        tool.prepare_bundle(self.root, self.wanted, True)
        key = self.path / 'database/server.key'; key.write_bytes(b'PRIVATE_USER_SENTINEL')
        with self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_BUNDLE_CHANGED_OR_WRONG_BINDING$'):
            tool.prepare_bundle(self.root, self.wanted, True)
        self.assertEqual(key.read_bytes(), b'PRIVATE_USER_SENTINEL')
        key.write_bytes(self.snapshot['server.key'])
        (self.path / 'runtime/extra').write_bytes(b'UNMANAGED')
        with self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_SELECTED_FILES_INVALID$'):
            tool.prepare_bundle(self.root, self.wanted, True)

    def test_symlink_file_hardlink_and_permissions_rejected(self):
        tool.prepare_bundle(self.root, self.wanted, True)
        key = self.path / 'database/server.key'; key.unlink()
        key.symlink_to(self.root.joinpath(*tool.candidate.DIRECTORY, tool.candidate.CANDIDATE, 'server.key'))
        with self.assertRaises(OSError): tool.prepare_bundle(self.root, self.wanted, True)
        key.unlink(); key.write_bytes(self.snapshot['server.key']); key.chmod(0o600)
        other = self.root / 'hardlink'; os.link(key, other)
        with self.assertRaisesRegex(tool.candidate.CandidateError, '^TLS_PATH_TYPE_INVALID$'):
            tool.prepare_bundle(self.root, self.wanted, True)
        other.unlink(); key.chmod(0o640)
        with self.assertRaisesRegex(tool.candidate.CandidateError, '^TLS_PATH_PERMISSIONS_INVALID$'):
            tool.prepare_bundle(self.root, self.wanted, True)

    def test_symlink_parent_directory_is_rejected(self):
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir(mode=0o700)
        self.path.parent.symlink_to(elsewhere)
        with self.assertRaises(OSError): tool.prepare_bundle(self.root, self.wanted, True)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_candidate_changed_and_comma_bind_path_rejected(self):
        key = self.root.joinpath(*tool.candidate.DIRECTORY, tool.candidate.CANDIDATE, 'server.key')
        original = key.read_bytes(); key.write_bytes(b'PRIVATE_INVALID_KEY')
        with self.assertRaises(tool.candidate.CandidateError): tool.read_candidate(self.root, self.manifest)
        self.assertEqual(key.read_bytes(), b'PRIVATE_INVALID_KEY'); key.write_bytes(original)
        with self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_PROJECT_PATH_INVALID$'):
            tool.opened_directory(self.root / 'comma,path', True)

    def test_wrong_source_address_extra_peers_ipv6_and_aux_reservation_rejected(self):
        for change in ('source', 'peer', 'ipv6', 'aux', 'gateway', 'outside', 'labels'):
            raw = json.loads(json.dumps(self.raw)); proposal = dict(self.proposal)
            if change == 'source': raw['Containers']['a' * 64]['IPv4Address'] = '192.168.96.5/20'
            if change == 'peer': raw['Containers']['c' * 64] = {'IPv4Address': '192.168.96.4/20'}
            if change == 'ipv6': raw['EnableIPv6'] = True
            if change == 'aux': raw['IPAM']['Config'][0]['AuxiliaryAddresses'] = {'other': '192.168.96.4'}
            if change == 'gateway': raw['IPAM']['Config'][0]['Gateway'] = '192.168.96.4'
            if change == 'outside': proposal['maintenance_source_ip'] = '192.168.112.4'
            if change == 'labels': raw['Labels']['com.docker.compose.project'] = 'other'
            with self.subTest(change=change), self.assertRaises(tool.SupplyError):
                tool.network_recipe(json.dumps([raw]), 'vms-project', self.containers, proposal)

    def test_recipe_is_config_only_external_ro_and_has_three_fixed_addresses(self):
        recipe = json.loads(self.wanted['compose.recipe.json'])
        self.assertEqual(recipe['networks']['camera-storage'], {'external': True, 'name': 'vms-project_camera-storage'})
        for role, service in zip(tool.ROLES, recipe['services'].values()):
            # JSON keys are sorted; inspect by role rather than serialization order.
            service = recipe['services']['tls-' + role + '-recipe']
            self.assertEqual(service['entrypoint'], ['/bin/true'])
            self.assertEqual(service['profiles'], ['tls-supply-recipe-only'])
            self.assertTrue(service['read_only']); self.assertTrue(service['volumes'][0]['read_only'])
            self.assertTrue(service['volumes'][0]['volume']['nocopy'])
            self.assertEqual(service['user'], str(tool.ROLES[role][0]) + ':' + str(tool.ROLES[role][0]))
            self.assertNotIn('environment', service); self.assertNotIn('ports', service)
        self.assertFalse(self.receipt['activation_allowed'])
        self.assertFalse(self.receipt['network_recipe']['address_reservation_verified'])

    def test_orchestration_three_volumes_and_repeat_never_reinitializes(self):
        docker = FakeDocker(self.root, self.snapshot)
        ready, count = tool.prepare_volumes(docker, self.receipt, self.snapshot, True)
        self.assertTrue(ready); self.assertEqual(count, 3)
        self.assertEqual(sum(init for _, init, _ in docker.helpers), 3)
        ready, count = tool.prepare_volumes(docker, self.receipt, self.snapshot, True)
        self.assertTrue(ready); self.assertEqual(count, 0)
        self.assertEqual(sum(init for _, init, _ in docker.helpers), 3)

    def test_existing_partial_volume_is_rejected_before_creating_missing_ones(self):
        docker = FakeDocker(self.root, self.snapshot)
        tool.prepare_volumes(docker, self.receipt, self.snapshot, True)
        del docker.values[self.receipt['volume_names']['maintenance']]
        docker.commands.clear(); docker.fail_probe = 'database'
        with self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_UID_RO_OR_EXACT_BYTES_NOT_VERIFIED$'):
            tool.prepare_volumes(docker, self.receipt, self.snapshot, True)
        self.assertEqual(docker.commands, [])

    def test_without_apply_missing_volume_and_owner_conflict_and_changed_volume(self):
        docker = FakeDocker(self.root, self.snapshot)
        self.assertEqual(tool.prepare_volumes(docker, self.receipt, self.snapshot, False), (False, 0))
        self.assertEqual(docker.commands, [])
        tool.prepare_volumes(docker, self.receipt, self.snapshot, True)
        name = self.receipt['volume_names']['database']; saved = docker.values[name]['Labels']
        docker.values[name]['Labels'] = {'UNMANAGED': 'user'}
        with self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_VOLUME_OWNERSHIP_MISMATCH$'):
            tool.prepare_volumes(docker, self.receipt, self.snapshot, True)
        docker.values[name]['Labels'] = saved; docker.changed_volume = True
        with self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_VOLUME_CHANGED$'):
            tool.prepare_volumes(docker, self.receipt, self.snapshot, True)

    def test_incomplete_swapped_duplicate_and_extra_probe_proof_rejected(self):
        docker = FakeDocker(self.root, self.snapshot)
        good = docker.helper(self.receipt, 'database', '')
        for raw in (good.replace(b'TLS_SUPPLY_OK:database', b'TLS_SUPPLY_OK:runtime'),
                    good.splitlines()[0] + b'\n', good + b'EXTRA\n', good + good,
                    good.replace(tool.candidate.sha(self.snapshot['server.key']).encode(), b'0' * 64)):
            with self.assertRaises(tool.SupplyError): tool.verify_probe(raw, 'database', self.snapshot)

    def test_initializer_limits_new_volume_permissions_and_cross_uid_probe(self):
        script = tool.initializer('database')
        self.assertLess(script.index('chmod 0700'), script.index('chown 999:999'))
        self.assertLess(script.index('chmod 0700'), script.index('cat /input/'))
        self.assertIn('umask 077', script)
        self.assertIn('set -C', script); self.assertIn('test -z', script)
        self.assertNotIn('ca.key', script)
        runtime = tool.probe_script('runtime')
        self.assertIn('65532', runtime); self.assertIn('Read-only file system', runtime)
        self.assertIn('ls /supply/database', runtime); self.assertIn('ls /supply/maintenance', runtime)
        self.assertIn('0 0 4294967295', runtime)

    def test_dry_run_prepare_replay_and_production_recheck_orchestration(self):
        docker = FakeDocker(self.root, self.snapshot)
        before = docker.snapshot()
        observation = (before, self.containers, self.receipt['probe_image'], json.dumps([self.raw]).encode())
        with patch.object(tool, 'checked_source', return_value=('SYNTHETIC_REVISION', self.manifest)), \
             patch.object(tool, 'observe', return_value=observation):
            planned = tool.prepare(self.root, False, lambda _: docker)
            self.assertEqual(planned['status'], 'planned'); self.assertEqual(docker.commands[0][:2], ['network', 'inspect'])
            self.assertFalse(planned['tls_supply_volumes_ready'])
            first = tool.prepare(self.root, True, lambda _: docker)
            again = tool.prepare(self.root, True, lambda _: docker)
        self.assertEqual(first['status'], 'prepared'); self.assertEqual(again['status'], 'already_prepared')
        self.assertEqual(first['native_supply_probes_passed'], 3)
        self.assertEqual(first['native_cross_uid_denials_passed'], 6)
        self.assertTrue(first['offline_probe_helpers_removed'])
        for flag in tool.NO_CHANGES: self.assertIs(first[flag], False)
        self.assertFalse(first['recipe_is_deployable'])
        docker.snapshot = lambda: {'camera-api': {'id': 'changed'}}
        with patch.object(tool, 'checked_source', return_value=('SYNTHETIC_REVISION', self.manifest)), \
             patch.object(tool, 'observe', return_value=observation), \
             self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_PRODUCTION_OR_SOURCE_CHANGED$'):
            tool.prepare(self.root, False, lambda _: docker)


class TLSHelperCommandTest(unittest.TestCase):
    def receipt(self):
        return {'supply_sha256': 'b' * 64, 'supply_directory': '/tmp/private-synthetic',
                'probe_image': 'sha256:' + 'f' * 64,
                'volume_names': {role: 'synthetic-' + role for role in tool.ROLES}}

    def test_offline_read_only_uid_and_minimal_initializer_capabilities(self):
        docker = tool.SupplyDocker(Path('/tmp'))
        for initialize, own_only in ((True, False), (False, False), (False, True)):
            commands = []
            def run(args, **kwargs):
                commands.append(args)
                return b''
            with patch.object(docker, 'run', side_effect=run):
                docker.helper(self.receipt(), 'runtime', 'SYNTHETIC_SCRIPT', initialize=initialize, own_only=own_only)
            command = commands[0]
            self.assertIn('--read-only', command); self.assertIn('none', command)
            self.assertIn('no-new-privileges:true', command)
            self.assertEqual(command[command.index('--user') + 1], '0:0' if initialize else '65532:65532')
            self.assertEqual(command[command.index('--pull') + 1], 'never')
            self.assertIn('--tmpfs', command)
            if initialize:
                self.assertEqual([command[i+1] for i, x in enumerate(command) if x == '--cap-add'], ['CHOWN', 'DAC_OVERRIDE'])
                self.assertIn('source=/tmp/private-synthetic/runtime,target=/input,readonly', ' '.join(command))
            else:
                self.assertNotIn('--cap-add', command)
                self.assertEqual(sum(x == '--mount' for x in command), 1 if own_only else 3)

    def test_uncertain_run_removes_only_exact_owned_helper_and_anonymous_volumes(self):
        docker = tool.SupplyDocker(Path('/tmp')); commands = []; name = None
        receipt = self.receipt()
        def run(args, **kwargs):
            nonlocal name
            commands.append(args)
            if args[0] == 'run':
                name = args[args.index('--name') + 1]; raise tool.SupplyError('SYNTHETIC_TIMEOUT')
            if args[0] == 'ps': return b'abc123\n'
            if args[0] == 'inspect':
                return json.dumps([{'Name': '/' + name, 'Config': {'Labels': {
                    tool.LABEL: receipt['supply_sha256'], tool.LABEL + '.project': docker.project,
                    tool.LABEL + '.helper': 'offline-supply-only'}}}]).encode()
            if args[0] == 'rm': return b''
            raise AssertionError(args)
        with patch.object(docker, 'run', side_effect=run), self.assertRaisesRegex(tool.SupplyError, '^SYNTHETIC_TIMEOUT$'):
            docker.helper(receipt, 'runtime', '')
        self.assertEqual(commands[-1], ['rm', '-f', '-v', 'abc123'])

    def test_unmanaged_name_collision_and_cleanup_failure_cannot_pass(self):
        docker = tool.SupplyDocker(Path('/tmp')); commands = []; name = None
        def run(args, **kwargs):
            nonlocal name
            commands.append(args)
            if args[0] == 'run': name = args[args.index('--name') + 1]; return b'TLS_SUPPLY_OK:runtime\n'
            if args[0] == 'ps': return b'abc123\n'
            if args[0] == 'inspect': return json.dumps([{'Name': '/' + name, 'Config': {'Labels': {'UNMANAGED': 'user'}}}]).encode()
            raise AssertionError(args)
        with patch.object(docker, 'run', side_effect=run), \
             self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_HELPER_OWNERSHIP_MISMATCH$'):
            docker.helper(self.receipt(), 'runtime', '')
        self.assertFalse(any(args[0] == 'rm' for args in commands))
        with patch.object(docker, 'run', side_effect=[b'TLS_SUPPLY_OK:runtime\n', tool.SupplyError('SYNTHETIC_CLEANUP_FAILED')]), \
             self.assertRaisesRegex(tool.SupplyError, '^SYNTHETIC_CLEANUP_FAILED$'):
            docker.helper(self.receipt(), 'runtime', '')

    def test_safe_cli_errors_never_print_secret_or_untrusted_paths(self):
        for error in (RuntimeError('PRIVATE_KEY_SENTINEL postgres://private-secret@host'),
                      tool.SupplyError('PRIVATE_KEY_SENTINEL postgres://private-secret@host'),
                      tool.SupplyError('TLS_SUPPLY_VOLUME_OWNERSHIP_MISMATCH')):
            out = io.StringIO()
            with patch.object(sys_module(), 'argv', ['prepare_camera_database_tls_supply.py']), \
                 patch.object(tool, 'prepare', side_effect=error), contextlib.redirect_stderr(out):
                self.assertEqual(tool.main(), 1)
            self.assertNotIn('PRIVATE_KEY_SENTINEL', out.getvalue()); self.assertNotIn('postgres://', out.getvalue())
            value = json.loads(out.getvalue()); self.assertFalse(value['tls_supply_volumes_ready'])
            self.assertFalse(value['activation_allowed'])

    def test_docker_errors_are_sanitized(self):
        docker = tool.SupplyDocker(Path('/tmp'))
        with patch.object(tool.Docker, 'run', side_effect=tool.ActivationError('PRIVATE_SECRET_COMMAND_ERROR')), \
             self.assertRaisesRegex(tool.SupplyError, '^TLS_SUPPLY_DOCKER_COMMAND_FAILED$'):
            docker.run(['synthetic'])


def sys_module():
    import sys
    return sys


if __name__ == '__main__': unittest.main()
