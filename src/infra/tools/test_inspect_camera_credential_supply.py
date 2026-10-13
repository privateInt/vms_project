"""Failure-boundary tests for the read-only production inventory, with synthetic inputs."""
import copy
import builtins
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import inspect_camera_credential_supply as supply

SOURCE = Path(__file__).resolve().parents[3]
API_ID, DB_ID = 'a'*64, 'b'*64
API_IMAGE, DB_IMAGE = 'sha256:'+'c'*64, 'sha256:'+'d'*64
TOKEN = 'SYNTHETIC_TOKEN_NOT_FOR_PRODUCTION_123456789'


class FakeDocker:
    project = 'vms-project'
    def __init__(self, root):
        self.root = root; self.calls = []; self.snapshots = 0
        self.before = {name: {'id': cid, 'image': image, 'running': True,
            'started_at': 'synthetic-start', 'restarts': 0}
            for name, cid, image in (('camera-api', API_ID, API_IMAGE), ('camera-db', DB_ID, DB_IMAGE))}
        self.config = {'services': {'camera-api': {'image': API_IMAGE,
            'environment': {'VMS_API_TOKEN': TOKEN, 'CAMERA_DATABASE_URL_FILE': '/run/secrets/camera_runtime_dsn'},
            'ports': [{'target': 8080, 'published': '18081', 'host_ip': '127.0.0.1'}]}}}
        self.camera = {'Id': API_ID, 'Config': {'User': '65532:65532', 'Env': [
            'CAMERA_DATABASE_URL_FILE=/run/secrets/camera_runtime_dsn', 'VMS_API_TOKEN='+TOKEN]},
            'HostConfig': {'ReadonlyRootfs': True}, 'Mounts': [{'Type': 'bind',
            'Source': str(root/'var/camera/secrets/runtime-dsn'),
            'Destination': '/run/secrets/camera_runtime_dsn', 'RW': False}]}
        self.db = {'Id': DB_ID, 'State': {'Health': {'Status': 'healthy'}},
            'Mounts': [{'Type': 'volume', 'Name': 'vms-project_camera-data',
            'Destination': '/var/lib/postgresql/data'}]}
        self.database = {'database': 'vms_camera', 'session_user': 'camera_admin',
            'current_user': 'camera_admin', 'transaction_read_only': True,
            'postgres_version_num': 170011, 'tls_enabled': False,
            'hba_path_lexically_outside_data': False, 'credential_storage_present': False,
            'credential_roles': [], 'migrations': [{'version': i, 'name': 'migrations/'+name,
            'checksum': supply.sha(root/'src/platform/camera/internal/storage/migrations'/name)}
            for i, name in enumerate(supply.MIGRATIONS, 1)]}
        self.after_sql = lambda: None
        self.after_snapshot = lambda: None

    def preflight(self): self.calls.append('preflight'); return 'synthetic-daemon'
    def volume_exists(self): return True
    def snapshot(self):
        self.snapshots += 1
        if self.snapshots == 2: self.after_snapshot()
        return copy.deepcopy(self.before)
    def compose(self, args):
        assert args == ['config', '--format', 'json']
        self.calls.append(args); return json.dumps(self.config).encode()
    def run(self, args, **kwargs):
        self.calls.append(args)
        if args == ['inspect', API_ID]: return json.dumps([self.camera]).encode()
        if args == ['inspect', DB_ID]: return json.dumps([self.db]).encode()
        assert args == ['exec', DB_ID, *supply.SQL_ARGS, supply.READ_ONLY_SQL]
        self.after_sql(); return json.dumps(self.database).encode()


def fixture(root, *, with_key=True):
    names = {'src/infra/tools/inspect_camera_credential_supply.py', 'src/infra/tools/camera_activation.py',
        'src/platform/camera/api/openapi.json', 'src/platform/camera/internal/app/app.go',
        'src/platform/camera/compose.active.yaml', 'src/infra/postgresql/compose.camera.yaml'}
    names.update('src/platform/camera/internal/storage/migrations/'+n for n in supply.MIGRATIONS)
    hashes = {}
    for name in names:
        p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes((SOURCE/name).read_bytes())
        hashes[name] = supply.sha(p)
    manifest = {'version': supply.VERSION, 'storage_schema_version': 8,
        'credential_boundary_resume_native_verified': True,
        'validated_credential_boundary_resume_project_sha256': '7d3168b40749aa886f6c359cf12a1bd43e0dda634188fdd1e2998a554669e277',
        'credential_boundary_resume_production_orchestration_implemented': False,
        'business_runtime_implemented': False, 'files': hashes}
    (root/'project-manifest.json').write_text(json.dumps(manifest))
    (root/'.env').write_text('SYNTHETIC_ENV_SECRET='+TOKEN)
    camera = root/'var/camera'; camera.mkdir(parents=True); camera.chmod(0o700)
    receipt = {'status': 'activated', 'stage': 'completed', 'scope': 'camera_device_delete',
        'project': 'vms-project', 'schema_version': 7, 'device_delete_activated': True,
        'candidate_image': API_IMAGE, 'database_image': DB_IMAGE}
    (root/supply.RECEIPT).write_text(json.dumps(receipt))
    if with_key:
        directory = root/'var/camera/credential-keys'; directory.mkdir(); directory.chmod(0o700)
        p = root/supply.KEY; p.write_bytes(b'SYNTHETIC_KEY_BYTES_NEVER_PARSED_OR_HASHED'); p.chmod(0o600)


class SupplyInspectionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)/'project'; self.root.mkdir()
        fixture(self.root); self.docker = FakeDocker(self.root)
        self.api = patch.object(supply, 'read_api', side_effect=self.read_api); self.api.start(); self.addCleanup(self.api.stop)

    def read_api(self, base, path, token=None):
        self.assertEqual(base, 'http://127.0.0.1:18081')
        if path == '/health/ready':
            return 200, {'ready': True, 'scope': 'camera_registry', 'business_runtime_ready': False}, {}
        if path == '/api/v1/platform':
            self.assertEqual(token, TOKEN)
            return 200, {'version': supply.VERSION, 'stage': 'P1_DEVICE_DELETE', 'capabilities': supply.CAPABILITIES}, {}
        self.assertEqual(path, '/openapi.json')
        return 200, json.loads((self.root/'src/platform/camera/api/openapi.json').read_text()), {}

    def inspect(self): return supply.inspect_supply(self.root, self.docker)
    def rejected(self, code):
        with self.assertRaisesRegex(supply.ActivationError, '^'+code+'$'): self.inspect()

    def test_completed_inventory_is_blocked_and_never_leaks_secrets(self):
        before = (self.root/supply.KEY).read_bytes()
        result = self.inspect(); text = json.dumps(result)
        self.assertEqual(result['status'], 'inspected'); self.assertEqual(result['readiness'], 'blocked')
        self.assertFalse(result['production_supply_ready']); self.assertFalse(result['activation_allowed'])
        self.assertEqual(result['host_key_bundle']['status'], 'metadata_valid')
        self.assertFalse(result['host_key_bundle']['key_material_integrity_verified'])
        self.assertEqual(result['database']['missing_credential_roles'], list(supply.ROLES))
        self.assertFalse(result['runtime']['actual_execution_uid_verified'])
        self.assertNotIn(TOKEN, text); self.assertNotIn(before.decode(), text)
        self.assertEqual((self.root/supply.KEY).read_bytes(), before)
        self.assertFalse((self.root/supply.REPORT).exists())
        self.assertTrue(all(result[k] is False for k in supply.NO_CHANGES))

    def test_source_edit_is_rejected_before_docker(self):
        (self.root/'src/platform/camera/internal/app/app.go').write_text('SYNTHETIC_USER_EDIT')
        self.rejected('SOURCE_FILE_CHANGED'); self.assertEqual(self.docker.calls, [])

    def test_unlisted_go_source_is_rejected(self):
        (self.root/'src/platform/camera/internal/app/unreviewed.go').write_text('package app')
        self.rejected('UNREVIEWED_PLATFORM_SOURCE_PRESENT')

    def test_manifest_path_escape_is_rejected(self):
        p = self.root/'project-manifest.json'; m = json.loads(p.read_text()); m['files']['../escape'] = 'a'*64
        p.write_text(json.dumps(m)); self.rejected('SOURCE_MANIFEST_PATH_INVALID')

    def test_missing_host_key_is_inventory_blocker_without_creation(self):
        (self.root/supply.KEY).unlink()
        self.assertIn('HOST_KEY_BUNDLE_MISSING', self.inspect()['blockers'])
        self.assertFalse((self.root/supply.KEY).exists())

    def test_key_contents_are_not_opened_even_when_not_json(self):
        original = os.open
        def forbidden(path, *args, **kwargs):
            self.assertNotEqual(str(path), 'key-bundle.json')
            self.assertNotEqual(str(path), str(self.root/supply.KEY))
            return original(path, *args, **kwargs)
        def refuse_key(original_open):
            def guarded(path, *args, **kwargs):
                self.assertNotEqual(str(path), str(self.root/supply.KEY))
                return original_open(path, *args, **kwargs)
            return guarded
        with patch.object(os, 'open', side_effect=forbidden), \
                patch.object(io, 'open', side_effect=refuse_key(io.open)), \
                patch.object(builtins, 'open', side_effect=refuse_key(builtins.open)):
            self.assertEqual(self.inspect()['host_key_bundle']['status'], 'metadata_valid')

    def test_key_file_symlink_rejected_without_reading_target(self):
        key = self.root/supply.KEY; key.unlink(); key.symlink_to(self.root/'.env')
        self.rejected('KEY_FILE_LINK_OR_TYPE_REJECTED')

    def test_key_directory_symlink_rejected(self):
        key = self.root/supply.KEY; key.unlink(); key.parent.rmdir(); key.parent.symlink_to(self.root)
        self.rejected('KEY_DIRECTORY_SYMLINK_OR_TYPE_REJECTED')

    def test_key_hardlink_rejected(self):
        os.link(self.root/supply.KEY, self.root/'synthetic-second-link')
        self.rejected('KEY_FILE_LINK_OR_TYPE_REJECTED')

    def test_key_mode_is_rejected_without_repair(self):
        key = self.root/supply.KEY; key.chmod(0o640)
        self.rejected('KEY_FILE_OWNER_OR_MODE_REJECTED'); self.assertEqual(key.stat().st_mode & 0o777, 0o640)

    def test_key_directory_mode_is_rejected_without_repair(self):
        directory = (self.root/supply.KEY).parent; directory.chmod(0o750)
        self.rejected('KEY_DIRECTORY_OWNER_OR_MODE_REJECTED'); self.assertEqual(directory.stat().st_mode & 0o777, 0o750)

    def test_key_size_limits(self):
        for body in (b'', b'x'*32769):
            with self.subTest(size=len(body)):
                (self.root/supply.KEY).write_bytes(body); self.rejected('KEY_FILE_SIZE_REJECTED')

    def test_key_content_change_detected_by_metadata(self):
        self.docker.after_sql = lambda: (self.root/supply.KEY).write_bytes(b'SYNTHETIC_CHANGED')
        self.rejected('KEY_METADATA_CHANGED_DURING_INSPECTION')

    def test_input_change_detected_after_query(self):
        self.docker.after_sql = lambda: (self.root/'.env').write_text('SYNTHETIC_CONCURRENT_EDIT')
        self.rejected('INSPECTION_INPUT_CHANGED')

    def test_container_recreation_is_rejected(self):
        self.docker.after_snapshot = lambda: self.docker.before['camera-api'].update(id='e'*64)
        self.rejected('PRODUCTION_CONTAINERS_CHANGED_DURING_INSPECTION')

    def test_previous_activation_image_must_match(self):
        self.docker.before['camera-api']['image'] = 'sha256:'+'f'*64
        self.rejected('DEVICE_DELETE_ACCEPTANCE_MISMATCH')

    def test_database_schema_checksum_mismatch_rejected(self):
        self.docker.database['migrations'][6]['checksum'] = 'e'*64
        self.rejected('ACCEPTED_SCHEMA_7_REQUIRED')

    def test_read_only_and_admin_session_required(self):
        for change in ({'transaction_read_only': False}, {'current_user': 'unexpected'}, {'database': 'postgres'}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.docker.database); self.docker.database.update(change)
                self.rejected('READ_ONLY_DATABASE_IDENTITY_MISMATCH'); self.docker.database = original

    def test_malformed_role_results_rejected(self):
        for roles in (None, [{'name': 'unexpected'}], [{'name': supply.ROLES[0], 'login': 'true'}]):
            with self.subTest(roles=roles):
                self.docker.database['credential_roles'] = roles; self.rejected('DATABASE_ROLE_INVENTORY_INVALID')

    def test_tls_enabled_or_present_roles_do_not_authorize_activation(self):
        self.docker.database['tls_enabled'] = True
        self.docker.database['credential_roles'] = [{ 'name': name, **{k: False for k in
            ('login', 'superuser', 'create_database', 'create_role', 'replication', 'bypass_rls')}} for name in supply.ROLES]
        result = self.inspect()
        self.assertNotIn('DATABASE_TLS_DISABLED', result['blockers'])
        self.assertNotIn('CREDENTIAL_DATABASE_ROLES_MISSING', result['blockers'])
        self.assertFalse(result['activation_allowed']); self.assertFalse(result['database']['active_hba_authentication_verified'])

    def test_writable_registry_secret_mount_is_rejected(self):
        self.docker.camera['Mounts'][0]['RW'] = True; self.rejected('REGISTRY_DSN_MOUNT_MISMATCH')

    def test_key_mount_presence_is_not_key_supply_proof(self):
        self.docker.camera['Mounts'].append({'Type': 'bind', 'Source': str(self.root/supply.KEY),
            'Destination': '/synthetic-key', 'RW': False})
        result = self.inspect(); self.assertTrue(result['runtime']['credential_key_bind_mount_present'])
        self.assertFalse(result['runtime']['credential_key_supply_verified'])

    def test_named_container_user_does_not_invent_uid(self):
        self.docker.camera['Config']['User'] = 'synthetic-user'
        self.assertIsNone(self.inspect()['runtime']['configured_uid'])

    def test_failed_report_cannot_keep_old_success_or_include_exception_secret(self):
        error = supply.ActivationError('BAD_RESULT: '+TOKEN)
        with patch.object(supply, 'InventoryDocker', return_value=self.docker), patch.object(supply, 'inspect_supply', side_effect=error):
            with self.assertRaises(supply.ActivationError): supply.run_inspection(self.root)
        p = self.root/supply.REPORT; text = p.read_text(); value = json.loads(text)
        self.assertEqual(value['status'], 'failed'); self.assertEqual(value['code'], 'BAD_RESULT')
        self.assertNotIn(TOKEN, text); self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_report_is_private_and_repeat_does_not_change_key_or_environment(self):
        protected = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.root/supply.KEY, self.root/'.env')}
        with patch.object(supply, 'InventoryDocker', side_effect=lambda root: FakeDocker(root)):
            for _ in range(2): self.assertEqual(supply.run_inspection(self.root)['status'], 'inspected')
        self.assertEqual((self.root/supply.REPORT).stat().st_mode & 0o777, 0o600)
        for p, state in protected.items(): self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), state)


class ReadOnlyAllowlistTest(unittest.TestCase):
    def setUp(self): self.docker = supply.InventoryDocker(Path('/synthetic-project'))

    def test_mutations_and_sql_substitution_rejected_before_subprocess(self):
        self.docker.database_id = DB_ID
        commands = (['compose', 'up'], ['restart', API_ID], ['build', '.'],
            ['exec', API_ID, *supply.SQL_ARGS, supply.READ_ONLY_SQL],
            ['exec', DB_ID, *supply.SQL_ARGS, 'SELECT 1; DELETE FROM camera.devices;'],
            ['exec', DB_ID, 'sh', '-c', 'SYNTHETIC_COMMAND'], ['image', 'tag', API_IMAGE, 'synthetic'])
        with patch.object(supply.Docker, 'run') as run:
            for args in commands:
                with self.subTest(args=args), self.assertRaises(supply.ActivationError): self.docker.run(args)
            run.assert_not_called()

    def test_extra_environment_and_input_rejected(self):
        with patch.object(supply.Docker, 'run') as run:
            for kwargs in ({'input': b''}, {'extra': {'PGOPTIONS': 'synthetic'}}, {'stdout': 1}, {'unknown': 1}):
                with self.subTest(kwargs=kwargs), self.assertRaises(supply.ActivationError):
                    self.docker.run(['info', '--format', '{{.ID}}'], **kwargs)
            run.assert_not_called()

    def test_fixed_read_only_sql_allowed_only_after_database_identification(self):
        args = ['exec', DB_ID, *supply.SQL_ARGS, supply.READ_ONLY_SQL]
        with patch.object(supply.Docker, 'run', return_value=b'{}') as run:
            with self.assertRaises(supply.ActivationError): self.docker.run(args)
            self.docker.database_id = DB_ID; self.assertEqual(self.docker.run(args), b'{}'); run.assert_called_once()

    def test_docker_stderr_is_discarded(self):
        with patch.object(supply.Docker, 'run', side_effect=supply.ActivationError('DOCKER_COMMAND_FAILED: '+TOKEN)):
            with self.assertRaisesRegex(supply.ActivationError, '^READ_ONLY_DOCKER_COMMAND_UNAVAILABLE$'):
                self.docker.run(['info', '--format', '{{.ID}}'])

    def test_compose_mutations_rejected(self):
        with self.assertRaises(supply.ActivationError): self.docker.compose(['up', '-d'])
        with self.assertRaises(supply.ActivationError): self.docker.compose(['config', '--format', 'json'], active=True)

    def test_remote_endpoint_and_http_mutation_rejected(self):
        with patch.object(supply, 'request') as request:
            for base, path in (('http://192.0.2.1:8080', '/health/ready'),
                    ('http://127.0.0.1:18081', '/api/v1/credentials'),
                    ('http://127.0.0.1:18081', '/health/ready?synthetic=1')):
                with self.subTest(base=base, path=path), self.assertRaises(supply.ActivationError):
                    supply.read_api(base, path)
            request.assert_not_called()


if __name__ == '__main__': unittest.main()
