"""Real file/PKI checks and mocked Docker orchestration; no production cutover."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import prepare_camera_registry_tls_cutover as tool
import test_prepare_camera_database_tls_supply as previous


class FakeDocker(previous.FakeDocker):
    def __init__(self, root, snapshot):
        super().__init__(root, snapshot)
        self.controls, self.fail_control, self.fail_deny = {}, False, False
        self.current_config = {'services': {name + '-api': {'image': 'synthetic-' + name}
                              for name in ('model', 'analysis', 'operation')}}
        self.alter_config = None

    def run(self, args, **kwargs):
        if args and args[0] == 'compose':
            self.commands.append(args)
            root_recipe = json.loads(Path(args[args.index('-f') + 1]).read_bytes())
            camera = json.loads(Path(root_recipe['include'][0]['path']).read_bytes())
            camera['services'].update(copy.deepcopy(self.current_config['services']))
            for service in camera['services'].values():
                if 'secrets' in service: service['secrets'] = [{'source': n} for n in service['secrets']]
            if self.alter_config: self.alter_config(camera)
            return json.dumps(camera).encode()
        return super().run(args, **kwargs)

    def compose(self, args, active=False):
        assert args == ['config', '--format', 'json'] and active is False
        return json.dumps(self.current_config).encode()

    def helper(self, receipt, role, script, initialize=False, own_only=False):
        if receipt['volume_names'].keys() != {'database'}:
            return super().helper(receipt, role, script, initialize, own_only)
        self.helpers.append((role, initialize, own_only))
        if initialize:
            if self.fail_initialize: raise tool.supply.SupplyError('SYNTHETIC_CONTROL_INTERRUPTED')
            path = Path(receipt['supply_directory']) / 'database'
            self.controls[receipt['volume_names']['database']] = {n: (path / n).read_bytes() for n in tool.CONTROL}
            return b''
        if role == 'database':
            if self.fail_control: return b'INCOMPLETE_CONTROL\n'
            stored = self.controls.get(receipt['volume_names']['database'], {})
            return ('REGISTRY_TLS_CONTROL_OK\n' + ''.join(tool.pki.sha(stored[n]) + '  ' + n + '\n'
                for n in tool.CONTROL if n in stored)).encode()
        if self.fail_deny: return b'NOT_DENIED\n'
        return f'REGISTRY_TLS_CONTROL_DENIED:{tool.supply.ROLES[role][0]}\n'.encode()


class RegistryTLSPreparationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='registry-tls-template-')
        cls.template = Path(cls.temporary.name) / 'project'; cls.template.mkdir(mode=0o700)
        cls.first = tool.pki.prepare(cls.template, True)
        fd = tool.pki.directory(cls.template, False)[0]
        try:
            leaf = os.open(tool.pki.CANDIDATE, tool.pki.DIR_FLAGS, dir_fd=fd)
            try: cls.snapshot = tool.pki.inspect(leaf)
            finally: os.close(leaf)
        finally: os.close(fd)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='registry-tls-case-'); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'; shutil.copytree(self.template, self.root)
        (self.root / '.env').write_bytes(b'VMS_CAMERA_COMPOSE_FILE=./src/platform/camera/compose.active.yaml\n')
        (self.root / '.env').chmod(0o600)
        self.raw, self.containers = previous.fixture_network()
        proposal = json.loads(self.snapshot['candidate.json'])['endpoint_proposal']
        self.network = tool.supply.network_recipe(json.dumps([self.raw]), 'vms-project', self.containers, proposal)
        self.image = 'sha256:' + 'f' * 64
        self.receipt, self.tls_files = tool.supply.bundle(self.root, 'vms-project', self.image,
                                                       self.network, self.snapshot, self.first)
        tool.supply.prepare_bundle(self.root, self.tls_files, True)
        self.manifest = {'credential_database_tls_supply_latest_server_candidate_sha256': self.first['candidate_sha256'],
            'credential_database_tls_supply_latest_server_supply_sha256': self.receipt['supply_sha256'],
            'credential_database_tls_supply_latest_server_tls_supply_volume_names': self.receipt['volume_names'],
            'credential_registry_tls_cutover_latest_server_test_api_image': 'sha256:' + 'e' * 64}
        self.docker = FakeDocker(self.root, self.snapshot)
        tool.supply.prepare_volumes(self.docker, self.receipt, self.snapshot, True)
        self.current = {'network': self.network, 'snapshot': {
            'camera-api': {'id': 'a' * 64, 'image': 'sha256:' + 'e' * 64},
            'camera-db': {'id': 'd' * 64, 'image': self.image}},
            'database_image': self.image, 'http_network': {'Id': 'c' * 64},
            'config_sha256': '1' * 64, 'port': 18081}
        self.values = {'runtime-password': '7' * 64}
        self.plan, self.wanted = tool.bundle(self.root, 'vms-project', '2' * 64,
            self.current, self.receipt, self.values, '3' * 64)
        self.path = self.root.joinpath(*tool.DIRECTORY, tool.PREPARED)

    def test_real_accepted_supply_certificates_keys_and_volumes_rechecked(self):
        result = tool.accepted_supply(self.root, self.manifest, self.docker, self.network, self.image)
        self.assertEqual(result, (self.receipt, self.tls_files))
        self.assertEqual(sum(v[1] for v in self.docker.helpers), 3)

    def test_candidate_receipt_tamper_and_wrong_accepted_supply_are_rejected(self):
        wrong = dict(self.manifest)
        wrong['credential_database_tls_supply_latest_server_candidate_sha256'] = '0' * 64
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_ACCEPTED_CANDIDATE_CHANGED$'):
            tool.accepted_supply(self.root, wrong, self.docker, self.network, self.image)
        wrong = dict(self.manifest)
        wrong['credential_database_tls_supply_latest_server_supply_sha256'] = '0' * 64
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_ACCEPTED_SUPPLY_BINDING_CHANGED$'):
            tool.accepted_supply(self.root, wrong, self.docker, self.network, self.image)

    def test_missing_volume_never_created_and_existing_supply_never_reinitialized(self):
        del self.docker.values[self.receipt['volume_names']['maintenance']]
        self.docker.commands.clear(); before = copy.deepcopy(self.docker.values)
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_PREPARED_SUPPLY_VOLUMES_REQUIRED$'):
            tool.accepted_supply(self.root, self.manifest, self.docker, self.network, self.image)
        self.assertEqual(self.docker.values, before); self.assertEqual(self.docker.commands, [])

    def test_tampered_private_supply_bytes_and_extra_files_rejected(self):
        key = self.root.joinpath(*tool.supply.DIRECTORY, tool.supply.SUPPLY, 'database/server.key')
        original = key.read_bytes(); key.write_bytes(b'USER_KEY_SENTINEL')
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_ACCEPTED_SUPPLY_BYTES_CHANGED$'):
            tool.accepted_supply(self.root, self.manifest, self.docker, self.network, self.image)
        self.assertEqual(key.read_bytes(), b'USER_KEY_SENTINEL'); key.write_bytes(original)
        extra = key.parent / 'extra'; extra.write_bytes(b'USER_SENTINEL')
        with self.assertRaises(tool.supply.SupplyError):
            tool.accepted_supply(self.root, self.manifest, self.docker, self.network, self.image)
        self.assertEqual(extra.read_bytes(), b'USER_SENTINEL')

    def test_ca_signing_key_and_credential_key_are_never_opened(self):
        opened = []; original = os.open
        def observed(path, *args, **kwargs):
            opened.append(str(path)); return original(path, *args, **kwargs)
        with patch.object(tool.os, 'open', side_effect=observed):
            tool.accepted_supply(self.root, self.manifest, self.docker, self.network, self.image)
        self.assertFalse(any(v.endswith('ca.key') or 'credential-keys' in v for v in opened))

    def test_supply_path_network_or_image_change_rejected(self):
        for network, image in (({**self.network, 'network_id': '0' * 64}, self.image),
                               (self.network, 'sha256:' + '0' * 64)):
            with self.subTest(network=network), self.assertRaises(tool.PreparationError):
                tool.accepted_supply(self.root, self.manifest, self.docker, network, image)

    def test_dry_run_creates_no_preparation_directory_or_control(self):
        self.assertEqual(tool.prepare_files(self.root, self.wanted, False), (False, False))
        self.assertFalse(self.path.parent.exists())
        before = copy.deepcopy(self.docker.values)
        self.assertEqual(tool.prepare_control(self.docker, self.root, self.plan, self.wanted, False), (False, 0))
        self.assertEqual(self.docker.values, before)

    def test_real_files_replay_preserves_modes_bytes_and_mtimes(self):
        self.assertEqual(tool.prepare_files(self.root, self.wanted, True), (True, True))
        before = {p.relative_to(self.path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns,
                  stat.S_IMODE(p.stat().st_mode)) for p in self.path.rglob('*') if p.is_file()}
        self.assertEqual(tool.prepare_files(self.root, self.wanted, True), (True, False))
        self.assertEqual(tool.prepare_files(self.root, self.wanted, False), (True, False))
        self.assertEqual(before, {p.relative_to(self.path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns,
            stat.S_IMODE(p.stat().st_mode)) for p in self.path.rglob('*') if p.is_file()})
        self.assertEqual(before['runtime-dsn'][2], 0o444)
        self.assertEqual(before['migrator-dsn'][2], 0o444)
        self.assertEqual(before['receipt.json'][2], 0o600)
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in self.path.rglob('*') if p.is_dir()))

    def test_umask_does_not_change_new_file_modes(self):
        previous_mask = os.umask(0o027)
        try: tool.prepare_files(self.root, self.wanted, True)
        finally: os.umask(previous_mask)
        self.assertEqual(stat.S_IMODE((self.path / 'runtime-dsn').stat().st_mode), 0o444)
        self.assertEqual(stat.S_IMODE((self.path / 'receipt.json').stat().st_mode), 0o600)

    def test_unknown_or_partial_preparation_not_repaired(self):
        self.path.mkdir(parents=True, mode=0o700); self.path.parent.chmod(0o700)
        marker = self.path / 'user'; marker.write_bytes(b'USER_SENTINEL')
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_PREPARATION_INCOMPLETE_OR_UNKNOWN$'):
            tool.prepare_files(self.root, self.wanted, True)
        self.assertEqual(list(self.path.iterdir()), [marker])

    def test_changed_dsn_and_source_revision_are_preserved_and_rejected(self):
        tool.prepare_files(self.root, self.wanted, True)
        path = self.path / 'runtime-dsn'; original = path.read_bytes(); path.unlink()
        path.write_bytes(b'USER_DSN_SENTINEL'); path.chmod(0o444)
        with self.assertRaises(tool.PreparationError): tool.prepare_files(self.root, self.wanted, True)
        self.assertEqual(path.read_bytes(), b'USER_DSN_SENTINEL'); path.unlink()
        path.write_bytes(original); path.chmod(0o444)
        _, changed = tool.bundle(self.root, 'vms-project', '4' * 64, self.current, self.receipt, self.values, '3' * 64)
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_PREPARATION_CHANGED_OR_STALE$'):
            tool.prepare_files(self.root, changed, True)

    def test_symlink_hardlink_and_wrong_permission_rejected(self):
        tool.prepare_files(self.root, self.wanted, True)
        path = self.path / 'runtime-dsn'; original = path.read_bytes(); path.unlink()
        path.symlink_to(self.root / '.env')
        with self.assertRaises(OSError): tool.prepare_files(self.root, self.wanted, True)
        path.unlink(); path.write_bytes(original); path.chmod(0o444)
        other = self.root / 'linked'; os.link(path, other)
        with self.assertRaises(tool.pki.CandidateError): tool.prepare_files(self.root, self.wanted, True)
        other.unlink(); path.chmod(0o600)
        with self.assertRaises(tool.PreparationError): tool.prepare_files(self.root, self.wanted, True)

    def test_symlink_preparation_parent_and_unsafe_path_rejected(self):
        target = self.root / 'elsewhere'; target.mkdir(mode=0o700)
        self.path.parent.symlink_to(target)
        with self.assertRaises(OSError): tool.prepare_files(self.root, self.wanted, True)
        for suffix in ('comma,path', 'dollar$path', 'line\npath'):
            with self.assertRaises(tool.PreparationError): tool.directory(self.root / suffix, (), True)

    def test_exact_tls_dsns_and_migrator_certificate_mapping(self):
        runtime = urlsplit(self.wanted['runtime-dsn'].decode().strip())
        migrator = urlsplit(self.wanted['migrator-dsn'].decode().strip())
        self.assertEqual(runtime.username, 'camera_runtime'); self.assertEqual(runtime.password, '7' * 64)
        self.assertEqual(migrator.username, 'camera_migrator'); self.assertIsNone(migrator.password)
        self.assertEqual(runtime.hostname, tool.pki.SERVER_NAME)
        self.assertEqual(parse_qs(runtime.query), {'sslmode': ['verify-full'], 'sslrootcert': ['/run/camera-tls/ca.pem']})
        self.assertEqual(parse_qs(migrator.query)['sslcert'], ['/run/camera-maintenance-tls/maintenance.pem'])
        hba = self.wanted['database/hba.conf'].decode()
        self.assertIn('camera_runtime 192.168.96.3/32 scram-sha-256', hba)
        self.assertIn('camera_migrator 192.168.96.4/32 cert map=registry_migrator', hba)
        self.assertNotIn('hostnossl', hba)
        self.assertEqual(self.wanted['database/pg_ident.conf'], b'registry_migrator camera_maintenance camera_migrator\n')

    def test_recipe_preserves_external_data_http_and_fixed_sources(self):
        camera = json.loads(self.wanted['compose.camera.json'])
        self.assertEqual(camera['volumes']['camera-data'], {'external': True, 'name': 'vms-project_camera-data'})
        self.assertEqual(camera['networks']['default'], {'name': 'vms-project_default'})
        self.assertEqual(camera['services']['camera-api']['user'], '65532:65532')
        self.assertEqual(camera['services']['camera-db']['user'], '999:999')
        self.assertEqual(camera['services']['camera-migrate']['user'], '10002:10002')
        self.assertEqual(camera['services']['camera-migrate']['profiles'], ['camera-tools'])
        self.assertEqual(camera['services']['camera-api']['ports'][0]['host_ip'], '127.0.0.1')
        self.assertNotIn('ports', camera['services']['camera-db'])
        self.assertFalse(self.plan['activation_allowed']); self.assertFalse(self.plan['recipe_is_deployable'])
        self.assertNotIn('PRIVATE KEY', self.wanted['compose.camera.json'].decode())
        self.assertNotIn('7' * 64, self.wanted['receipt.json'].decode())

    def test_real_compose_semantic_validation_with_normalized_fixture(self):
        tool.prepare_files(self.root, self.wanted, True)
        tool.validate_compose(self.docker, self.root, self.wanted)
        self.assertFalse(any(c[0] in ('exec', 'stop', 'up') for c in self.docker.commands))

    def test_compose_unreviewed_images_mounts_networks_secret_targets_and_other_platform_rejected(self):
        tool.prepare_files(self.root, self.wanted, True)
        for kind in ('image', 'mount', 'network', 'secret_target', 'published', 'other_platform', 'external', 'dsn'):
            def change(config):
                api = config['services']['camera-api']
                if kind == 'image': api['image'] = 'unreviewed:latest'
                if kind == 'mount': api['volumes'][0]['read_only'] = False
                if kind == 'network': api['networks']['camera-storage']['ipv4_address'] = '192.168.96.9'
                if kind == 'secret_target': api['secrets'][0]['target'] = 'wrong-file'
                if kind == 'published': config['services']['camera-db']['ports'] = [{'target': 5432}]
                if kind == 'other_platform': config['services']['model-api']['image'] = 'changed'
                if kind == 'external': config['volumes']['camera-data']['external'] = False
                if kind == 'dsn': api['environment']['CAMERA_DATABASE_URL_FILE'] = '/wrong/dsn'
            self.docker.alter_config = change
            with self.subTest(kind=kind), self.assertRaises(tool.PreparationError):
                tool.validate_compose(self.docker, self.root, self.wanted)

    def test_control_volume_create_replay_and_cross_uid_denials(self):
        tool.prepare_files(self.root, self.wanted, True)
        self.assertEqual(tool.prepare_control(self.docker, self.root, self.plan, self.wanted, True), (True, 1))
        initializations = sum(init for _, init, _ in self.docker.helpers)
        self.assertEqual(tool.prepare_control(self.docker, self.root, self.plan, self.wanted, True), (True, 0))
        self.assertEqual(sum(init for _, init, _ in self.docker.helpers), initializations)

    def test_existing_incomplete_control_and_access_denial_failure_rejected_without_repair(self):
        tool.prepare_files(self.root, self.wanted, True)
        tool.prepare_control(self.docker, self.root, self.plan, self.wanted, True)
        self.docker.fail_control = True; self.docker.commands.clear()
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_CONTROL_UID_RO_BYTES_NOT_VERIFIED$'):
            tool.prepare_control(self.docker, self.root, self.plan, self.wanted, True)
        self.assertEqual(self.docker.commands, [])
        self.docker.fail_control = False; self.docker.fail_deny = True
        with self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_CONTROL_CROSS_UID_ACCESS_NOT_DENIED$'):
            tool.prepare_control(self.docker, self.root, self.plan, self.wanted, True)

    def test_interrupted_control_initialization_retains_only_new_volume_and_cannot_reinitialize(self):
        tool.prepare_files(self.root, self.wanted, True)
        old = copy.deepcopy(self.docker.values); self.docker.fail_initialize = True
        with self.assertRaises(tool.supply.SupplyError):
            tool.prepare_control(self.docker, self.root, self.plan, self.wanted, True)
        self.docker.fail_initialize = False
        with self.assertRaises(tool.PreparationError):
            tool.prepare_control(self.docker, self.root, self.plan, self.wanted, True)
        for name, value in old.items(): self.assertEqual(self.docker.values[name], value)

    def test_control_initializer_and_probe_have_no_network_or_database_commands(self):
        init = tool.control_script(True); probe = tool.control_script(False)
        self.assertIn('set -C', init); self.assertIn('chown 999:999', init)
        self.assertLess(init.index('test -z'), init.index('cat /input/'))
        self.assertIn('Read-only file system', probe)
        self.assertIn('0 0 4294967295', probe)
        self.assertFalse(any(v in init + probe for v in ('psql', 'pg_restore', 'pg_dump', 'ca.key')))

    def test_whole_orchestration_plan_prepare_replay_with_real_supply_files(self):
        before = (self.root / '.env').read_bytes()
        with patch.object(tool, 'checked_source', return_value=('2' * 64, self.manifest)), \
             patch.object(tool, 'current_binding', return_value=self.current), \
             patch.object(tool.activation, 'prepare_secrets', return_value=self.values):
            planned = tool.prepare(self.root, False, lambda _: self.docker)
            first = tool.prepare(self.root, True, lambda _: self.docker)
            again = tool.prepare(self.root, True, lambda _: self.docker)
        self.assertEqual(planned['status'], 'planned'); self.assertEqual(first['status'], 'prepared')
        self.assertEqual(again['status'], 'already_prepared')
        self.assertEqual(first['control_volumes_created'], 1); self.assertEqual(again['control_volumes_created'], 0)
        self.assertEqual(first['preparation_sha256'], again['preparation_sha256'])
        for field in tool.NO_CHANGES: self.assertIs(first[field], False)
        self.assertTrue(first['cutover_preparation_ready'])
        self.assertTrue(first['production_prepared_supply_files_read'])
        self.assertFalse(first['registry_tls_activation_tool_implemented'])
        self.assertEqual(before, (self.root / '.env').read_bytes())
        self.assertFalse(any(c[0] in ('exec', 'up', 'stop') for c in self.docker.commands))

    def test_concurrent_source_environment_or_production_change_prevents_ready(self):
        with patch.object(tool, 'checked_source', side_effect=[('2' * 64, self.manifest), ('4' * 64, self.manifest)]), \
             patch.object(tool, 'current_binding', return_value=self.current), \
             patch.object(tool.activation, 'prepare_secrets', return_value=self.values), \
             self.assertRaisesRegex(tool.PreparationError, '^REGISTRY_TLS_SOURCE_OR_PRODUCTION_CHANGED$'):
            tool.prepare(self.root, True, lambda _: self.docker)

    def test_failed_cli_never_emits_secret_dsn_or_raw_exception_text(self):
        for error in (RuntimeError('PRIVATE_SENTINEL postgres://secret@host'),
                      tool.PreparationError('PRIVATE_SENTINEL postgres://secret@host'),
                      tool.PreparationError('REGISTRY_TLS_PREPARATION_CHANGED_OR_STALE')):
            out = io.StringIO()
            with patch.object(sys, 'argv', ['prepare_camera_registry_tls_cutover.py']), \
                 patch.object(tool, 'prepare', side_effect=error), contextlib.redirect_stderr(out):
                self.assertEqual(tool.main(), 1)
            self.assertNotIn('PRIVATE_SENTINEL', out.getvalue()); self.assertNotIn('postgres://', out.getvalue())
            result = json.loads(out.getvalue())
            self.assertFalse(result['cutover_preparation_ready']); self.assertFalse(result['activation_allowed'])


class CurrentProductionBindingTest(unittest.TestCase):
    def setUp(self):
        self.root = Path('/tmp/synthetic-production-project')
        self.raw, self.containers = previous.fixture_network()
        self.before = {s: {'id': v['Id'], 'image': 'sha256:' + ('d' if s == 'camera-db' else 'e') * 64}
                       for s, v in self.containers.items()}
        self.manifest = {'credential_database_tls_supply_latest_server_fixed_address_recipe': {
            'database_ip': '192.168.96.2', 'runtime_source_ip': '192.168.96.3', 'maintenance_source_ip': '192.168.96.4'},
            'credential_registry_tls_cutover_latest_server_test_api_image': self.before['camera-api']['image'],
            'credential_registry_tls_cutover_latest_server_test_database_image': self.before['camera-db']['image']}
        self.port = {'host_ip': '127.0.0.1', 'published': '18081', 'target': 8080, 'protocol': 'tcp'}
        self.config = {'services': {n: {} for n in ('camera-api', 'camera-db', 'camera-migrate',
                                                  'model-api', 'analysis-api', 'operation-api')}}
        self.config['services']['camera-api'] = {'ports': [self.port]}
        self.http = {'Name': 'vms-project_default', 'Id': 'c' * 64, 'Internal': False,
            'Driver': 'bridge', 'Scope': 'local', 'Labels': {'com.docker.compose.project': 'vms-project',
            'com.docker.compose.network': 'default'}, 'Containers': {'a' * 64: {'IPv4Address': 'synthetic'}}}
        api, db = self.containers['camera-api'], self.containers['camera-db']
        api['NetworkSettings']['Networks']['vms-project_default'] = {'NetworkID': 'c' * 64}
        api['NetworkSettings']['Ports'] = {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18081'}]}
        api['HostConfig'] = {'PortBindings': copy.deepcopy(api['NetworkSettings']['Ports'])}
        db['HostConfig'] = {'PortBindings': {}}; db['NetworkSettings']['Ports'] = {'5432/tcp': None}
        db['Mounts'] = [{'Destination': '/var/lib/postgresql/data', 'Type': 'volume', 'RW': True,
                         'Name': 'vms-project_camera-data'}]
        outer = self
        class Docker:
            project = 'vms-project'
            def compose(self, args, active=False): return json.dumps(outer.config).encode()
            def run(self, args):
                assert args == ['network', 'inspect', 'vms-project_default']
                return json.dumps([outer.http]).encode()
            def volume_exists(self): return True
        self.docker = Docker()

    def observe(self):
        return self.before, self.containers, self.before['camera-db']['image'], json.dumps([self.raw]).encode()

    def inspect(self):
        with patch.object(tool.supply, 'observe', side_effect=lambda *_: self.observe()):
            return tool.current_binding(self.root, self.docker, self.manifest)

    def test_current_schema7_rehearsed_images_published_loopback_and_owned_data(self):
        result = self.inspect()
        self.assertEqual(result['port'], 18081)
        self.assertEqual(result['network']['database_ip'], '192.168.96.2')
        self.assertEqual(result['snapshot'], self.before)

    def test_wrong_image_missing_http_wrong_source_database_publish_and_data_mount_rejected(self):
        original = copy.deepcopy((self.before, self.containers, self.config, self.http))
        for kind in ('image', 'missing_http', 'wildcard', 'source', 'database_publish', 'data', 'extra_network', 'internal_http', 'extra_service'):
            self.before, self.containers, self.config, self.http = copy.deepcopy(original)
            api, db = self.containers['camera-api'], self.containers['camera-db']
            if kind == 'image': self.before['camera-api']['image'] = 'sha256:' + '0' * 64
            if kind == 'missing_http': api['NetworkSettings']['Ports'] = {'8080/tcp': None}
            if kind == 'wildcard': self.config['services']['camera-api']['ports'][0]['host_ip'] = '0.0.0.0'
            if kind == 'source': api['NetworkSettings']['Networks']['vms-project_camera-storage']['IPAddress'] = '192.168.96.8'
            if kind == 'database_publish': db['HostConfig']['PortBindings'] = {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '15432'}]}
            if kind == 'data': db['Mounts'][0]['Name'] = 'wrong-data'
            if kind == 'extra_network': db['NetworkSettings']['Networks']['unexpected'] = {}
            if kind == 'internal_http': self.http['Internal'] = True
            if kind == 'extra_service': self.config['services']['unreviewed'] = {}
            with self.subTest(kind=kind), self.assertRaises((tool.PreparationError, tool.supply.SupplyError)):
                self.inspect()

    def test_accepted_source_requires_full_server_acceptance_and_current_preparation_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            correct = {'credential_registry_tls_cutover_server_verified': True,
                'validated_credential_registry_tls_cutover_project_sha256': tool.ACCEPTED,
                'credential_registry_tls_cutover_latest_server_status': 'passed',
                'credential_registry_tls_cutover_latest_server_checked_revision': tool.ACCEPTED,
                'credential_registry_tls_cutover_preparation_implemented': True,
                'files': {name: '0' * 64 for name in ('src/infra/tools/prepare_camera_registry_tls_cutover.py',
                                                    'src/infra/tools/test_prepare_camera_registry_tls_cutover.py')}}
            manifest = root / 'project-manifest.json'; manifest.write_text(json.dumps(correct))
            with patch.object(tool.rehearsal, 'checked_source', return_value='SYNTHETIC_REVISION'):
                self.assertEqual(tool.checked_source(root), ('SYNTHETIC_REVISION', correct))
                for field, wrong in (('credential_registry_tls_cutover_server_verified', False),
                    ('validated_credential_registry_tls_cutover_project_sha256', '0' * 64),
                    ('credential_registry_tls_cutover_latest_server_status', 'failed'),
                    ('credential_registry_tls_cutover_preparation_implemented', False)):
                    altered = {**correct, field: wrong}; manifest.write_text(json.dumps(altered))
                    with self.subTest(field=field), self.assertRaises(tool.PreparationError): tool.checked_source(root)

    def test_rehearsed_image_pin_is_accepted_without_modifying_environment(self):
        for quote in ('', "'", '\"'):
            body = ('VMS_API_TOKEN=SYNTHETIC_PRIVATE_TOKEN\nVMS_CAMERA_COMPOSE_FILE=' + quote + tool.activation.ACTIVE + quote
                    + '\nVMS_CAMERA_IMAGE=' + quote + self.before['camera-api']['image'] + quote + '\n').encode()
            tool.validate_current_environment(body, self.manifest)
            with self.assertRaisesRegex(tool.activation.ActivationError, 'CUSTOM_COMPOSE_CONFIGURATION_REQUIRES_REVIEW'):
                tool.activation.enabled_environment(body)

    def test_unreviewed_duplicate_image_and_custom_compose_configuration_rejected(self):
        base = ('VMS_CAMERA_COMPOSE_FILE=' + tool.activation.ACTIVE + '\n').encode()
        for addition in (b'VMS_CAMERA_IMAGE=unreviewed:latest\n', b'COMPOSE_FILE=other.yaml\n',
                         b'COMPOSE_PROJECT_NAME=other\n', b'VMS_CAMERA_COMPOSE_FILE=other.yaml\n',
                         b'VMS_CAMERA_IMAGE=sha256:' + b'e' * 64 + b'\nVMS_CAMERA_IMAGE=sha256:' + b'e' * 64 + b'\n'):
            with self.subTest(addition=addition), self.assertRaises(tool.PreparationError):
                tool.validate_current_environment(base + addition, self.manifest)

    def test_preflight_error_stage_and_safe_activation_error_code_are_preserved(self):
        error = tool.activation.ActivationError('ANOTHER_ACTIVATION_IS_RUNNING')
        error.inspection_stage = 'coordination_lock'
        out = io.StringIO()
        with patch.object(sys, 'argv', ['prepare_camera_registry_tls_cutover.py']), \
             patch.object(tool, 'prepare', side_effect=error), contextlib.redirect_stderr(out):
            self.assertEqual(tool.main(), 1)
        result = json.loads(out.getvalue())
        self.assertEqual(result['failed_stage'], 'coordination_lock')
        self.assertEqual(result['code'], 'ANOTHER_ACTIVATION_IS_RUNNING')


if __name__ == '__main__': unittest.main()
