"""Failure, transcript and synthetic fixture checks; Docker orchestration is mocked."""
import contextlib
import copy
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_camera_registry_tls_cutover as tool


def events(name, phases=(), action='pass'):
    return ([{'Action': 'run', 'Package': tool.PACKAGE, 'Test': name}]
        + [{'Action': 'output', 'Package': tool.PACKAGE, 'Test': name,
            'Output': tool.GO_PREFIX + phase + '\n'} for phase in phases]
        + [{'Action': action, 'Package': tool.PACKAGE, 'Test': name},
           {'Action': 'pass', 'Package': tool.PACKAGE}])


def transcript():
    return (events('TestRegistryTLSInputPolicy')
        + events(tool.GO_PARENTS[0], tool.GO_PHASES[:2])
        + events(tool.GO_PARENTS[2], tool.GO_PHASES[2:4])
        + events(tool.GO_PARENTS[4], tool.GO_PHASES[4:]))


class RegistryTLSRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='registry-tls-unit-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / 'log.jsonl'
        self.project = tool.PREFIX + 'a' * 12

    def summary(self, rows):
        self.log.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        return tool.summarize_go(self.log)

    def test_complete_transcript_requires_all_native_peers_and_policy(self):
        self.assertEqual(self.summary(transcript()), {'required_go_policy_tests_passed': 1,
            'required_native_peer_tests_passed': 3, 'native_transport_phases_passed': 5})

    def test_missing_duplicate_reordered_and_wrong_parent_markers_rejected(self):
        original = transcript()
        index = next(i for i, r in enumerate(original) if r['Action'] == 'output')
        cases = [original[:index] + original[index+1:], original[:index] + [original[index]] + original[index:]]
        for field, value in (('Output', tool.GO_PREFIX + tool.GO_PHASES[1] + '\n'),
                             ('Test', tool.GO_PARENTS[2]), ('Package', 'foreign')):
            changed = [dict(r) for r in original]; changed[index][field] = value; cases.append(changed)
        for rows in cases:
            with self.subTest(rows=rows[index]), self.assertRaises(tool.CheckError): self.summary(rows)

    def test_fail_skip_missing_terminal_or_policy_cannot_pass(self):
        for name in (*set(tool.GO_PARENTS), 'TestRegistryTLSInputPolicy'):
            for action in ('skip', 'fail', 'missing'):
                rows = transcript(); index = next(i for i, r in enumerate(rows) if r.get('Test') == name and r['Action'] == 'pass')
                if action == 'missing': del rows[index]
                else: rows[index]['Action'] = action
                with self.subTest(name=name, action=action), self.assertRaises(tool.CheckError): self.summary(rows)

    def test_local_prefix_cannot_pass_native_acceptance(self):
        rows = transcript()
        for r in rows:
            if r['Action'] == 'output': r['Output'] = 'LOCAL_' + r['Output']
        with self.assertRaises(tool.CheckError): self.summary(rows)

    def test_unfinished_or_duplicate_native_parent_rejected(self):
        for rows in (transcript()[:-2], transcript() + events(tool.GO_PARENTS[0], tool.GO_PHASES[:2])):
            with self.assertRaises(tool.CheckError): self.summary(rows)

    def test_acceptance_gate_requires_current_d1c_server_evidence(self):
        evidence = {'credential_database_tls_supply_server_verified': True,
            'validated_credential_database_tls_supply_project_sha256': tool.ACCEPTED_SUPPLY,
            'credential_registry_tls_cutover_rehearsal_implemented': True}
        with patch.object(tool.supply, 'checked_source', return_value=('revision', evidence)):
            self.assertEqual(tool.checked_source(self.root), 'revision')
        for field in evidence:
            bad = dict(evidence); bad[field] = False
            with patch.object(tool.supply, 'checked_source', return_value=('revision', bad)), self.assertRaises(tool.CheckError):
                tool.checked_source(self.root)

    def test_hba_requires_distinct_sources_and_explicit_cn_role_map(self):
        body = tool.hba('172.30.50.3', '172.30.50.4', True).decode()
        self.assertIn('camera_runtime 172.30.50.3/32 scram-sha-256', body)
        self.assertIn('camera_migrator 172.30.50.4/32 cert map=registry_migrator', body)
        self.assertTrue(body.endswith('host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n'))
        with self.assertRaises(tool.CheckError): tool.hba('172.30.50.3', '172.30.50.3', True)

    def recipe(self, tls=False):
        return tool.compose_recipe(self.root / 'source', self.root / 'test', self.project, self.project + '-storage',
            ['172.30.50.2', '172.30.50.3', '172.30.50.4', '172.30.50.5'],
            'sha256:' + 'a'*64, 'sha256:' + 'b'*64, 'SYNTHETIC_TOKEN', 12345, tls)

    def test_recipe_uses_exact_images_same_volume_private_port_and_no_production_supply(self):
        old, new = self.recipe(), self.recipe(True)
        for name in ('camera-api', 'camera-db', 'camera-migrate'):
            self.assertEqual(old['services'][name]['image'], new['services'][name]['image'])
        self.assertEqual(old['volumes'], new['volumes'])
        self.assertEqual(new['services']['camera-api']['ports'], ['127.0.0.1:12345:8080'])
        self.assertIn('camera-data:/var/lib/postgresql/data', new['services']['camera-db']['volumes'])
        self.assertNotIn('vms-project_camera-data', json.dumps(new))
        self.assertNotIn('database-tls-supply', json.dumps(new))
        self.assertIn('wrong-db.vms.internal', new['services']['camera-db']['networks']['storage']['aliases'])

    def test_recipe_enforces_distinct_uids_read_only_mounts_and_no_owner_runtime_dsn(self):
        services = self.recipe(True)['services']
        for name, uid in (('camera-api', 65532), ('camera-migrate', 10002), ('probe-maintenance', 10002), ('probe-offsource', 10003)):
            self.assertEqual(services[name]['user'], f'{uid}:{uid}')
            self.assertTrue(services[name]['read_only'])
            self.assertTrue(all(v.endswith(':ro') for v in services[name]['volumes']))
        self.assertEqual(services['camera-api']['environment']['CAMERA_DATABASE_URL_FILE'], '/registry-runtime/runtime-dsn')
        self.assertNotIn('camera_admin', json.dumps(services['camera-api']))
        self.assertEqual(services['files-owner']['network_mode'], 'none')
        self.assertIn('CGO_ENABLED=0 go test -c', tool.BUILD)
        self.assertIn('go test -race', tool.BUILD)

    def test_http_network_is_separate_and_only_api_has_access(self):
        for tls in (False, True):
            recipe = self.recipe(tls)
            self.assertEqual(recipe['networks']['http'], {'name': self.project+'-http', 'driver': 'bridge', 'internal': False})
            self.assertEqual(set(recipe['services']['camera-api']['networks']), {'http', 'storage'})
            for service in ('camera-db', 'camera-migrate', 'probe-maintenance', 'probe-offsource'):
                self.assertEqual(set(recipe['services'][service]['networks']), {'storage'})
                self.assertNotIn('ports', recipe['services'][service])
            self.assertEqual(recipe['services']['camera-api']['networks']['storage']['ipv4_address'], '172.30.50.3')
            self.assertEqual(recipe['services']['camera-db']['networks']['storage']['ipv4_address'], '172.30.50.2')

    def test_mutable_image_tags_rejected(self):
        with self.assertRaises(tool.CheckError):
            tool.compose_recipe(self.root, self.root, self.project, 'network', [], 'camera:latest', 'db:latest', 'token', 1)

    def test_compose_and_command_failures_keep_diagnostics_private(self):
        self.log.touch(mode=0o600)
        def run(args, **kwargs): return subprocess.CompletedProcess(args, 1, b'', b'PRIVATE_PASSWORD_SENTINEL')
        docker = tool.RehearsalDocker(self.root, self.project, self.root / 'production', self.log, run)
        with self.assertRaisesRegex(tool.CheckError, '^ISOLATED_REGISTRY_TLS_COMMAND_FAILED$'):
            docker.compose(['run', '--rm', 'camera-migrate'])
        self.assertIn(b'PRIVATE_PASSWORD_SENTINEL', self.log.read_bytes())
        self.assertEqual(docker.last_exit, 1)

    def test_separate_workspace_and_project_prefix_required(self):
        for root, project, production in ((self.root, 'vms-project', self.root / 'prod'),
            (self.root, self.project, self.root), (self.root / 'nested', self.project, self.root)):
            with self.assertRaises(tool.CheckError): tool.RehearsalDocker(root, project, production, self.log)

    def test_empty_namespace_rejects_collision_without_mutation(self):
        class Existing:
            project = self.project
            def run(self, args): return b'EXISTING_RESOURCE'
        with self.assertRaisesRegex(tool.CheckError, 'ISOLATED_NAMESPACE_ALREADY_EXISTS'): tool.empty_namespace(Existing())

    def test_fresh_fixture_required(self):
        (self.root / 'existing').write_bytes(b'SENTINEL')
        with self.assertRaises(tool.CheckError): tool.prepare_fixture(self.root, self.root, [])

    def exercise(self, fail=None, cleanup_fail=False, namespace_collision=False):
        production = self.root / 'production'; production.mkdir()
        (production / '.env').write_bytes(b'PRODUCTION_SENTINEL')
        instances = []
        class Fake:
            def __init__(inner, root, project, production_root, log):
                inner.root, inner.project, inner.log, inner.last_exit = root, project, log, None
                inner.calls, inner.created, inner.migrations = [], False, 0; instances.append(inner)
            def preflight(inner): return 'daemon'
            def run(inner, args):
                inner.calls.append(args)
                if args[:2] == ['network', 'create']:
                    inner.created = True
                    if fail == 'uncertain_network': raise tool.CheckError('ISOLATED_COMMAND_TIMEOUT_OR_UNAVAILABLE')
                    return b'CREATED'
                if args[:2] == ['network', 'inspect']: return b'[{"Subnet":"172.30.50.0/24","Gateway":"172.30.50.1"}]'
                if args[:2] == ['volume', 'inspect']: return b'[{"Name":"synthetic-data"}]'
                if args[:2] == ['network', 'rm']:
                    if cleanup_fail: raise tool.CheckError('ISOLATED_REGISTRY_TLS_COMMAND_FAILED')
                    inner.created = False; return b''
                if args[:2] == ['network', 'ls'] and '--format' in args:
                    return ((('a'*12+' '+inner.project+'-storage\n').encode()) if inner.created else b'')
                if namespace_collision: return b'EXISTING'
                return b''
            def compose(inner, args, **kwargs):
                inner.calls.append(args)
                if fail == 'migration' and 'camera-migrate' in args:
                    inner.last_exit = 1
                    with inner.log.open('ab') as f: f.write(b'PRIVATE_PASSWORD_SENTINEL\n')
                    raise tool.CheckError('ISOLATED_REGISTRY_TLS_COMMAND_FAILED')
                if 'probe-build' in args: rows = events('TestRegistryTLSInputPolicy')
                elif 'exec' in args and any('-test.run=^'+n+'$' in args for n in set(tool.GO_PARENTS)):
                    name = next(n for n in set(tool.GO_PARENTS) if '-test.run=^'+n+'$' in args)
                    phases = [p for n, p in zip(tool.GO_PARENTS, tool.GO_PHASES) if n == name]
                    rows = events(name, phases if fail != 'partial_transcript' else phases[:1])
                else: rows = []
                with inner.log.open('ab') as f:
                    for row in rows: f.write((json.dumps(row)+'\n').encode())
                if 'camera-migrate' in args:
                    inner.migrations += 1
                    return json.dumps({'version': 7, 'applied': 7 if inner.migrations == 1 else 0}).encode()
                return b''
        class Prod:
            def __init__(inner, root): pass
            def preflight(inner): return 'daemon'
            def snapshot(inner): return {'camera-api': 'UNCHANGED'}
            def run(inner, args): return b'PRODUCTION_NETWORK'
        state = ({'camera-api': 'UNCHANGED'}, {'camera-api': {'Image': 'sha256:'+'a'*64}}, 'sha256:'+'b'*64, b'PRODUCTION_NETWORK')
        def sql(docker, statement): return 'on' if "current_setting('ssl')" in statement else '0'
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(tool, 'checked_source', return_value='revision'))
            stack.enter_context(patch.object(tool, 'activation_lock', side_effect=lambda root: contextlib.nullcontext()))
            stack.enter_context(patch.object(tool.supply, 'SupplyDocker', Prod))
            stack.enter_context(patch.object(tool.supply, 'observe', return_value=state))
            stack.enter_context(patch.object(tool, 'sql', side_effect=sql))
            for name in ('check_schema', 'verify_runtime_grants', 'verify_version'):
                failure = tool.ActivationError('CAMERA_REGISTRY_READINESS_FAILED') if fail == 'readiness' and name == 'verify_version' else None
                stack.enter_context(patch.object(tool.registry, name, side_effect=failure))
            failure = tool.CheckError('ISOLATED_HTTP_PORT_NOT_PUBLISHED') if fail == 'unpublished' else None
            stack.enter_context(patch.object(tool, 'verify_http_binding', side_effect=failure))
            stack.enter_context(patch.object(tool, 'readiness_diagnostic', return_value={'exception_type': 'URLError'}))
            stack.enter_context(patch.object(tool.registry, 'registry_fingerprint', return_value='FINGERPRINT'))
            campaign_error = None
            if fail == 'http_seed':
                campaign_error = tool.RegistryHTTPError('REGISTRY_SEED_OR_MUTATION_FAILED', 'devices', 'PATCH',
                    'before-tls-device', 400, 'INPUT_INVALID')
            elif fail == 'legacy_helper': campaign_error = tool.ActivationError('INVALID_TEST_RESOURCE')
            stack.enter_context(patch.object(tool, 'campaign', return_value={'synthetic': True}, side_effect=campaign_error))
            stack.enter_context(patch.object(tool, 'replay'))
            stack.enter_context(patch.object(tool, 'runtime_tls_sessions'))
            result = tool.verify(production, Fake, lambda *args: None)
        self.assertEqual((production / '.env').read_bytes(), b'PRODUCTION_SENTINEL')
        self.assertEqual(Path(result['report']).stat().st_mode & 0o777, 0o600)
        if 'retained_workspace' in result: self.addCleanup(__import__('shutil').rmtree, result['retained_workspace'])
        return result, instances[0]

    def test_mock_orchestration_checks_drain_replay_recreation_and_cleanup(self):
        result, docker = self.exercise()
        self.assertEqual(result['status'], 'passed'); self.assertEqual(result['cutover_phases_passed'], 10)
        self.assertTrue(result['isolated_resources_removed']); self.assertTrue(result['synthetic_input_removed'])
        self.assertFalse(result['native_probe_race_enabled'])
        self.assertEqual(result['isolated_http_binding_checks_passed'], 4)
        for name in tool.NO_CHANGES: self.assertFalse(result[name], name)
        self.assertTrue(any('stop' in c and 'camera-api' in c for c in docker.calls))
        self.assertGreaterEqual(sum('--force-recreate' in c and 'camera-api' in c for c in docker.calls), 3)
        self.assertFalse(docker.root.exists())

    def test_failed_command_records_stage_exit_and_removes_only_test_resources(self):
        result, _ = self.exercise(fail='migration')
        self.assertEqual(result['status'], 'failed'); self.assertEqual(result['failed_stage'], 'schema7_migration')
        self.assertEqual(result['last_command_exit_code'], 1)
        self.assertTrue(result['isolated_resources_removed'])
        self.assertNotIn('PRIVATE_PASSWORD_SENTINEL', json.dumps(result))
        self.assertIn('PRIVATE_PASSWORD_SENTINEL', Path(result['log']).read_text())
        self.assertNotIn('native_transport_phases_passed', result)

    def test_uncertain_network_create_is_cleaned(self):
        result, docker = self.exercise(fail='uncertain_network')
        self.assertEqual(result['failed_stage'], 'isolated_network'); self.assertTrue(result['isolated_resources_removed'])
        self.assertTrue(any(c[:2] == ['network', 'rm'] for c in docker.calls))

    def test_cleanup_failure_does_not_report_success_or_discard_fixture(self):
        result, docker = self.exercise(cleanup_fail=True)
        self.assertEqual(result['code'], 'ISOLATED_REGISTRY_TLS_CLEANUP_FAILED')
        self.assertFalse(result['isolated_resources_removed']); self.assertFalse(result['synthetic_input_removed'])
        self.assertEqual(result['retained_workspace'], str(docker.root)); self.assertTrue(docker.root.exists())

    def test_partial_native_transcript_blocks_success_and_cleans(self):
        result, _ = self.exercise(fail='partial_transcript')
        self.assertEqual(result['status'], 'failed'); self.assertEqual(result['failed_stage'], 'tls_api_and_native_probes')
        self.assertTrue(result['isolated_resources_removed'])

    def test_http_failure_reports_only_method_resource_status_and_safe_api_code(self):
        result, _ = self.exercise(fail='http_seed')
        self.assertEqual(result['code'], 'REGISTRY_SEED_OR_MUTATION_FAILED')
        self.assertEqual(result['failed_stage'], 'plaintext_registry_seed')
        self.assertEqual(result['exception_type'], 'RegistryHTTPError')
        self.assertEqual(result['failed_http_step'], {'collection': 'devices', 'method': 'PATCH',
            'resource_id': 'before-tls-device', 'status': 400, 'api_error_code': 'INPUT_INVALID'})
        self.assertTrue(result['isolated_resources_removed']); self.assertTrue(result['isolated_diagnostics_collected'])

    def test_legacy_helper_activation_error_code_is_preserved_without_raw_detail(self):
        result, _ = self.exercise(fail='legacy_helper')
        self.assertEqual(result['code'], 'INVALID_TEST_RESOURCE')
        self.assertEqual(result['exception_type'], 'ActivationError')
        self.assertEqual(result['failed_stage'], 'plaintext_registry_seed')
        self.assertTrue(result['isolated_resources_removed'])

    def test_unpublished_port_fails_before_http_seed_and_still_cleans(self):
        result, _ = self.exercise(fail='unpublished')
        self.assertEqual(result['code'], 'ISOLATED_HTTP_PORT_NOT_PUBLISHED')
        self.assertEqual(result['failed_stage'], 'plaintext_http_binding')
        self.assertEqual(result['isolated_http_binding_checks_passed'], 0)
        self.assertNotIn('http_readiness_probe', result)
        self.assertTrue(result['isolated_resources_removed'])

    def test_readiness_failure_records_allowlisted_http_probe_after_binding(self):
        result, _ = self.exercise(fail='readiness')
        self.assertEqual(result['code'], 'CAMERA_REGISTRY_READINESS_FAILED')
        self.assertEqual(result['failed_stage'], 'plaintext_registry_seed')
        self.assertEqual(result['isolated_http_binding_checks_passed'], 1)
        self.assertEqual(result['http_readiness_probe'], {'exception_type': 'URLError'})
        self.assertTrue(result['isolated_resources_removed'])

    def test_namespace_collision_is_never_deleted(self):
        result, docker = self.exercise(namespace_collision=True)
        self.assertEqual(result['code'], 'ISOLATED_NAMESPACE_ALREADY_EXISTS')
        self.assertFalse(any('down' in c or c[:2] == ['network', 'rm'] for c in docker.calls))

    def test_preflight_public_error_is_generic(self):
        stream = io.StringIO()
        with patch.object(tool, 'verify', side_effect=RuntimeError('PRIVATE_SENTINEL')), contextlib.redirect_stderr(stream):
            self.assertEqual(tool.main(), 1)
        self.assertNotIn('PRIVATE_SENTINEL', stream.getvalue())


class SyntheticFixtureTest(unittest.TestCase):
    def test_real_pki_role_selection_no_signing_key_export_and_source_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='registry-tls-pki-unit-') as temp:
            root = Path(temp); synthetic = root / 'synthetic'; synthetic.mkdir(mode=0o700)
            source = root / 'source'; script = source / 'src/infra/postgresql/camera-init.sh'
            script.parent.mkdir(parents=True); script.write_bytes(b'#!/bin/sh\n# SYNTHETIC_INIT\n')
            inputs = tool.prepare_fixture(synthetic, source, ['172.30.50.2','172.30.50.3','172.30.50.4','172.30.50.5'])
            self.assertFalse(list(inputs.rglob('ca.key')))
            self.assertEqual(len(list((inputs/'runtime').iterdir())), 7)
            self.assertEqual(len(list((inputs/'maintenance').iterdir())), 8)
            self.assertEqual(len(list((inputs/'offsource').iterdir())), 6)
            for path in inputs.rglob('*'):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
            self.assertEqual((inputs/'control/10-camera.sh').read_bytes(), script.read_bytes())
            self.assertEqual((inputs/'control/pg_ident.conf').read_bytes(), b'registry_migrator camera_maintenance camera_migrator\n')
            self.assertNotEqual((inputs/'runtime/ca.pem').read_bytes(), (inputs/'runtime/wrong-ca.pem').read_bytes())
            self.assertNotEqual((inputs/'maintenance/maintenance.pem').read_bytes(), (inputs/'maintenance/wrong-client.pem').read_bytes())


class RegistryHTTPClientTest(unittest.TestCase):
    """Real loopback HTTP packets; this server is a response fixture, not the Go API."""
    def setUp(self):
        self.received = []; self.reply = (200, {'received': True}, {})
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner): inner.exchange()
            def do_POST(inner): inner.exchange()
            def do_PATCH(inner): inner.exchange()
            def do_DELETE(inner): inner.exchange()
            def exchange(inner):
                raw = inner.rfile.read(int(inner.headers.get('Content-Length', '0')))
                owner.received.append((inner.command, inner.path, dict(inner.headers), json.loads(raw) if raw else None))
                status, value, headers = owner.reply
                body = json.dumps(value, ensure_ascii=False).encode() if not isinstance(value, bytes) else value
                inner.send_response(status)
                for key, value in headers.items(): inner.send_header(key, value)
                inner.send_header('Content-Length', str(len(body))); inner.end_headers(); inner.wfile.write(body)
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def call(self, collection='devices', method='PATCH', identifier='before-tls-device', body=None, base=None):
        if body is None: body = {'schema_version': 'v1', 'expected_version': 1, 'display_name': '한글 이름'}
        return tool.api_call(base or self.base, 'SYNTHETIC_TOKEN', collection, method, identifier, body, 'synthetic-key')

    def test_all_campaign_ids_send_post_patch_delete_without_legacy_fixed_id_gate(self):
        with patch.object(tool.registry, 'mutation_request', side_effect=AssertionError('legacy helper called')):
            for prefix in ('before-tls', 'retained', 'after-tls'):
                for collection, suffix, key in (('devices', '-device', 'device_id'), ('sources', '-source', 'source_id')):
                    identifier = prefix + suffix
                    for method in ('POST', 'PATCH', 'DELETE'):
                        body = {key: identifier, 'display_name': '한글'} if method == 'POST' else {'schema_version': 'v1', 'expected_version': 1}
                        code, _, _ = self.call(collection, method, identifier, body)
                        self.assertEqual(code, 200)
                        packet = self.received[-1]
                        self.assertEqual(packet[0], method)
                        self.assertEqual(packet[1], '/api/v1/'+collection+('' if method == 'POST' else '/'+identifier))
                        self.assertEqual(packet[2]['Authorization'], 'Bearer SYNTHETIC_TOKEN')
                        self.assertEqual(packet[2]['Idempotency-Key'], 'synthetic-key')
                        self.assertEqual(packet[2]['Content-Type'], 'application/json')
                        self.assertEqual(packet[3], body)
        self.assertEqual(len(self.received), 18)

    def test_http_error_returns_safe_contract_response_instead_of_transport_failure(self):
        self.reply = (409, {'error': {'code': 'DEVICE_HAS_ACTIVE_SOURCES'}, 'request_id': 'synthetic-request'},
            {'X-Request-ID': 'synthetic-request', 'Cache-Control': 'no-store'})
        response = self.call(method='DELETE')
        tool.registry.expect_error(response, 409, 'DEVICE_HAS_ACTIVE_SOURCES')

    def test_redirect_is_not_followed_and_proxy_environment_is_ignored(self):
        self.reply = (302, {'received': 'redirect'}, {'Location': self.base+'/redirect-target'})
        with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1'}):
            code, _, _ = self.call()
        self.assertEqual(code, 302); self.assertEqual(len(self.received), 1)

    def test_unknown_collection_method_legacy_or_path_injection_ids_are_rejected_before_network(self):
        for collection, method, identifier in (('unsafe', 'PATCH', 'before-tls-device'),
            ('devices', 'PUT', 'before-tls-device'), ('devices', 'PATCH', 'upgrade-test'),
            ('devices', 'PATCH', '../before-tls-device'), ('devices', 'PATCH', 'before-tls-device?unsafe=1'),
            ('sources', 'DELETE', 'before-tls-device')):
            with self.subTest(identifier=identifier), self.assertRaises(tool.CheckError): self.call(collection, method, identifier)
        self.assertEqual(self.received, [])

    def test_non_loopback_credentials_query_fragment_or_path_endpoints_rejected(self):
        for base in ('https://127.0.0.1:12345', 'http://example.com:12345',
            'http://token@127.0.0.1:12345', self.base+'/?unsafe=1', self.base+'#fragment', self.base+'/prefix'):
            with self.subTest(base=base), self.assertRaises(tool.CheckError): self.call(base=base)
        self.assertEqual(self.received, [])

    def test_invalid_json_or_non_object_body_reports_request_context_without_body(self):
        for value in (b'PRIVATE_RESPONSE_SENTINEL', []):
            self.reply = (200, value, {})
            with self.subTest(value=value), self.assertRaises(tool.RegistryHTTPError) as caught: self.call()
            self.assertEqual(str(caught.exception), 'REGISTRY_HTTP_RESPONSE_INVALID')
            self.assertEqual(caught.exception.step['resource_id'], 'before-tls-device')
            self.assertNotIn('PRIVATE_RESPONSE_SENTINEL', json.dumps(caught.exception.step))

    def test_network_failure_reports_context_without_token_url_or_raw_exception(self):
        with patch.object(tool, 'build_opener', side_effect=OSError('PRIVATE_EXCEPTION_TOKEN_DSN')):
            with self.assertRaises(tool.RegistryHTTPError) as caught: self.call()
        self.assertEqual(str(caught.exception), 'REGISTRY_HTTP_TRANSPORT_FAILED')
        self.assertEqual(caught.exception.step, {'collection': 'devices', 'method': 'PATCH', 'resource_id': 'before-tls-device'})
        self.assertNotIn('PRIVATE_EXCEPTION_TOKEN_DSN', str(caught.exception))

    def test_campaign_response_failure_diagnostic_excludes_request_and_response_values(self):
        self.reply = (400, {'error': {'code': 'INPUT_INVALID', 'message': 'PRIVATE_SERVER_MESSAGE'},
            'token': 'PRIVATE_RESPONSE_TOKEN'}, {})
        with self.assertRaises(tool.RegistryHTTPError) as caught: tool.campaign(self.base, 'SYNTHETIC_TOKEN', 'before-tls')
        self.assertEqual(caught.exception.step, {'collection': 'devices', 'method': 'POST',
            'resource_id': 'before-tls-device', 'status': 400, 'api_error_code': 'INPUT_INVALID'})
        self.assertNotIn('PRIVATE_', json.dumps(caught.exception.step))

    def test_ready_diagnostic_preserves_only_known_scope_and_boolean_fields(self):
        self.reply = (200, {'scope': 'camera_registry', 'platform': 'camera', 'ready': True,
            'business_runtime_ready': False, 'token': 'PRIVATE_TOKEN', 'dsn': 'PRIVATE_DSN'}, {})
        result = tool.readiness_diagnostic(self.base)
        self.assertEqual(result, {'response_is_object': True, 'status': 200, 'scope': 'camera_registry',
            'platform': 'camera', 'ready': True, 'business_runtime_ready_present': True, 'business_runtime_ready': False})
        self.assertNotIn('PRIVATE_', json.dumps(result))

    def test_ready_diagnostic_distinguishes_database_not_ready_and_invalid_scope(self):
        self.reply = (503, {'scope': 'camera_registry', 'platform': 'camera', 'ready': False, 'business_runtime_ready': False}, {})
        self.assertEqual(tool.readiness_diagnostic(self.base)['ready'], False)
        self.reply = (200, {'scope': 'PRIVATE_SCOPE', 'platform': 'PRIVATE_PLATFORM', 'ready': 'PRIVATE_READY'}, {})
        result = tool.readiness_diagnostic(self.base)
        self.assertEqual(result['scope'], 'other'); self.assertEqual(result['platform'], 'other')
        self.assertIsNone(result['ready']); self.assertFalse(result['business_runtime_ready_present'])
        self.assertNotIn('PRIVATE_', json.dumps(result))

    def test_ready_diagnostic_transport_failure_emits_class_without_raw_exception(self):
        with patch.object(tool.registry, 'request', side_effect=OSError('PRIVATE_DSN_EXCEPTION')):
            self.assertEqual(tool.readiness_diagnostic(self.base), {'exception_type': 'OSError'})


class HTTPBindingMetadataTest(unittest.TestCase):
    """Selected Docker metadata fixtures, including the internal-only failure shape."""
    def setUp(self):
        self.root = Path('/synthetic-isolated-project')
        self.project = tool.PREFIX + 'a'*12
        self.addresses = ['172.30.50.2','172.30.50.3','172.30.50.4','172.30.50.5']
        self.storage = self.project + '-storage'; self.http = self.project + '-http'
        self.api_id, self.db_id = 'c'*64, 'd'*64
        self.api_image, self.db_image = 'sha256:'+'a'*64, 'sha256:'+'b'*64
        self.binding = {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '12345'}]}
        self.networks = [{'Id': '1'*64, 'Name': self.http, 'Internal': False, 'Driver': 'bridge',
            'Labels': {'com.docker.compose.project': self.project}, 'Containers': {self.api_id: {}}},
            {'Id': '2'*64, 'Name': self.storage, 'Internal': True, 'Driver': 'bridge',
            'Labels': {'com.docker.compose.project': self.project}}]
        self.rows = []
        for i, service, image, identity, ip in ((0,'camera-api',self.api_image,self.api_id,self.addresses[1]),
            (1,'camera-db',self.db_image,self.db_id,self.addresses[0])):
            networks = {self.storage: {'NetworkID': '2'*64, 'IPAddress': ip}}
            if i == 0: networks[self.http] = {'NetworkID': '1'*64, 'IPAddress': '172.31.60.2'}
            self.rows.append({'Id': identity, 'Image': image, 'Running': True,
                'Labels': {'com.docker.compose.project': self.project, 'com.docker.compose.service': service,
                    'com.docker.compose.project.working_dir': str(self.root)}, 'Networks': networks,
                'Ports': copy.deepcopy(self.binding) if i == 0 else {'5432/tcp': None},
                'PortBindings': copy.deepcopy(self.binding) if i == 0 else {}})

    def verify(self, rows=None, networks=None):
        owner = self
        class Docker:
            project, root = owner.project, owner.root
            def compose(inner, args):
                assert args[:2] == ['ps', '-q']
                return (owner.api_id if args[2] == 'camera-api' else owner.db_id).encode()
            def run(inner, args):
                if args[0] == 'inspect':
                    assert args[1:3] == ['--format', tool.HTTP_BINDING_FORMAT]
                    return ('\n'.join(json.dumps(r) for r in (rows if rows is not None else owner.rows))+'\n').encode()
                assert args == ['network', 'inspect', owner.http, owner.storage]
                return json.dumps(networks if networks is not None else owner.networks).encode()
        tool.verify_http_binding(Docker(), self.storage, self.addresses, 12345, self.api_image, self.db_image)

    def test_exact_loopback_binding_dual_network_and_fixed_database_source_pass(self):
        self.verify()
        self.assertNotIn('.Config.Env', tool.HTTP_BINDING_FORMAT)

    def test_declared_binding_without_actual_published_port_cannot_pass(self):
        rows = copy.deepcopy(self.rows); rows[0]['Ports'] = {}
        with self.assertRaisesRegex(tool.CheckError, 'ISOLATED_HTTP_PORT_NOT_PUBLISHED'): self.verify(rows)

    def test_wildcard_other_port_or_extra_ipv6_publication_rejected(self):
        for binding in ({'8080/tcp': [{'HostIp': '0.0.0.0','HostPort': '12345'}]},
            {'8080/tcp': [{'HostIp': '127.0.0.1','HostPort': '18081'}]},
            {'8080/tcp': self.binding['8080/tcp']+[{'HostIp':'::','HostPort':'12345'}]}):
            rows = copy.deepcopy(self.rows); rows[0]['Ports'] = binding
            with self.subTest(binding=binding), self.assertRaises(tool.CheckError): self.verify(rows)

    def test_database_port_publication_or_http_network_attachment_rejected(self):
        for mode in ('port', 'network'):
            rows = copy.deepcopy(self.rows)
            if mode == 'port': rows[1]['Ports'] = {'5432/tcp': [{'HostIp':'127.0.0.1','HostPort':'5432'}]}
            else: rows[1]['Networks'][self.http] = {'NetworkID':'1'*64,'IPAddress':'172.31.60.3'}
            with self.subTest(mode=mode), self.assertRaises(tool.CheckError): self.verify(rows)

    def test_internal_http_or_external_storage_network_rejected(self):
        for index in (0,1):
            networks = copy.deepcopy(self.networks); networks[index]['Internal'] = not networks[index]['Internal']
            with self.subTest(index=index), self.assertRaises(tool.CheckError): self.verify(networks=networks)

    def test_changed_database_source_role_network_or_container_binding_rejected(self):
        for mode in ('source', 'network_id', 'image', 'labels', 'stopped'):
            rows = copy.deepcopy(self.rows)
            if mode == 'source': rows[0]['Networks'][self.storage]['IPAddress'] = self.addresses[2]
            elif mode == 'network_id': rows[0]['Networks'][self.storage]['NetworkID'] = 'f'*64
            elif mode == 'image': rows[0]['Image'] = self.db_image
            elif mode == 'labels': rows[0]['Labels']['com.docker.compose.project'] = 'vms-project'
            else: rows[0]['Running'] = False
            with self.subTest(mode=mode), self.assertRaises(tool.CheckError): self.verify(rows)

    def test_foreign_http_peer_missing_metadata_or_unknown_network_rejected(self):
        networks = copy.deepcopy(self.networks); networks[0]['Containers']['f'*64] = {}
        with self.assertRaises(tool.CheckError): self.verify(networks=networks)
        with self.assertRaises(tool.CheckError): self.verify(rows=[])
        networks = copy.deepcopy(self.networks); networks[1]['Name'] = 'foreign-network'
        with self.assertRaises(tool.CheckError): self.verify(networks=networks)


if __name__ == '__main__': unittest.main()
