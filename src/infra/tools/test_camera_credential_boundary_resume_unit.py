import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_boundary_resume as tool
from test_camera_credential_storage import EXPECTED_TESTS


def transcript():
    rows = [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'}
            for name in (*EXPECTED_TESTS, *tool.UNIT_TESTS)]
    # The regression run skips phase-only fixtures. Later real runs must supply proof.
    for name in tool.NATIVE_TESTS:
        rows += [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'},
                 {'Package': tool.PACKAGE, 'Test': name, 'Action': 'skip'}]
    rows.append({'Package': 'vms.local/platform/camera/internal/credentialcrypto', 'Test': 'TestCredentialRestoreSuccessorMaterial', 'Action': 'pass'})
    for name, prefix, phase in tool.EVENTS:
        rows += [{'Package': tool.PACKAGE, 'Test': name, 'Action': 'run'},
                 {'Package': tool.PACKAGE, 'Test': name, 'Action': 'output',
                  'Output': 'fixture.go:1: ' + prefix + phase + '\n'},
                 {'Package': tool.PACKAGE, 'Test': name, 'Action': 'pass'}]
    rows.append({'Package': tool.PACKAGE, 'Action': 'pass'})
    return rows


class CredentialBoundaryResumeRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        files = {}
        for name in ('src/infra/tools/test_camera_credential_storage.py',
                     'src/infra/tools/test_camera_credential_boundary.py',
                     'src/infra/postgresql/compose.credential-boundary-resume-test.yaml',
                     'src/platform/camera/internal/storage/maintenance_fixture.go'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic source\n')
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest = {'storage_revision': 'step11b2-credential-storage-20261002',
                         'storage_schema_version': 8, 'credential_storage_implemented': True,
                         'credential_api_implemented': False, 'files': files,
                         'credential_boundary_resume_revision': tool.REVISION,
                         'credential_boundary_restore_native_verified': True,
                         'validated_credential_boundary_restore_project_sha256': '172e084b609aa8a06940cd8d4f4670c7f1b850844260f14752094ab1e46c11da',
                         'credential_restore_open_authorization_implemented': True,
                         'credential_boundary_native_verified': True,
                         'validated_credential_boundary_project_sha256': '08d9f3ae44d7a7f7d3d77a0d47606bfba6208ab47e3bf7385ba1e9144f148002',
                         'credential_restore_candidate_preparation_implemented': True,
                         'credential_maintenance_native_verified': True,
                         'validated_credential_maintenance_project_sha256':
                             'a2116e85a9d93b03ea54e65c4209d3b5b82b946c27e2f2377f6fe64e5e812e0d',
                         'credential_maintenance_hba_policy_implemented': True,
                         'credential_maintenance_mtls_opener_implemented': True,
                         'credential_runtime_admission_guard_implemented': True}
        self.write_manifest()
        (self.root / '.env').write_bytes(b'SYNTHETIC_ENV_SENTINEL')
        p = self.root / 'var/camera/credential-keys/key-bundle.json'
        p.parent.mkdir(parents=True)
        p.write_bytes(b'SYNTHETIC_KEY_SENTINEL')
        self.log = self.root / 'fixture.log'

    def write_manifest(self):
        (self.root / 'project-manifest.json').write_text(json.dumps(self.manifest))

    def summarize(self, rows):
        self.log.write_text('build progress\n' + '\n'.join(json.dumps(x) for x in rows))
        return tool.summarize_log(self.log)

    def test_complete_proof(self):
        result = self.summarize(transcript())
        self.assertEqual(result['native_boundary_resume_phases_passed'], 24)
        self.assertEqual(result['required_resume_tests_passed'], 12)
        self.assertEqual(result['required_credential_tests_passed'], 13)

    def test_missing_order_duplicate_phase_rejected(self):
        for mode in ('missing', 'order', 'duplicate'):
            rows = transcript()
            i = next(i for i, r in enumerate(rows) if r.get('Action') == 'output')
            if mode == 'missing': rows.pop(i)
            elif mode == 'order': rows[i]['Output'] = 'fixture: ' + tool.PREFIX + 'seed\n'
            else: rows.insert(i, rows[i].copy())
            with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_wrong_test_and_package_markers_rejected(self):
        for field, value in (('Test', 'TestSyntheticSelector'), ('Package', 'private.invalid/package')):
            rows = transcript()
            next(r for r in rows if r.get('Action') == 'output')[field] = value
            with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_skip_failure_and_truncation_rejected(self):
        for action in ('skip', 'fail'):
            rows = transcript()
            next(r for r in rows if r.get('Test') in tool.NATIVE_TESTS and r.get('Action') == 'pass')['Action'] = action
            with self.assertRaises(tool.VerificationError): self.summarize(rows)
        with self.assertRaises(tool.VerificationError): self.summarize(transcript()[:-2])

    def test_duplicate_native_run_cannot_override_previous(self):
        rows = transcript()
        name = tool.FIXTURE_TEST
        rows += [r.copy() for r in rows if r.get('Test') == name]
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_output_before_run_rejected(self):
        rows = transcript()
        i = next(i for i, r in enumerate(rows) if r.get('Action') == 'output') - 1
        rows[i], rows[i+1] = rows[i+1], rows[i]
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_missing_legacy_test_or_package_cannot_pass(self):
        for absent in (EXPECTED_TESTS[0], None, tool.UNIT_TESTS[0]):
            with self.assertRaises(tool.VerificationError):
                self.summarize([r for r in transcript() if r.get('Test') != absent])

    def test_earlier_failure_cannot_be_hidden_by_later_pass(self):
        rows = [{'Package': tool.PACKAGE, 'Test': 'TestEarlier', 'Action': 'fail'}] + transcript()
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_manifest_requires_accepted_operation_revision(self):
        for name, value in (('credential_boundary_restore_native_verified', False),
                            ('validated_credential_boundary_restore_project_sha256', 'wrong'),
                            ('credential_boundary_resume_revision', 'wrong'),
                            ('credential_restore_open_authorization_implemented', False)):
            original = self.manifest[name]
            self.manifest[name] = value
            self.write_manifest()
            with self.assertRaises(tool.VerificationError): tool.checked_revision(self.root)
            self.manifest[name] = original
        self.write_manifest()

    def test_source_edit_prevents_any_docker_call(self):
        (self.root / 'src/platform/camera/internal/storage/maintenance_fixture.go').write_bytes(b'user edit')
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), self.assertRaises(tool.VerificationError):
            tool.verify(self.root, run=lambda *a, **k: self.fail('command before integrity check'))

    def mock_run(self, fail_stage=None, cleanup=0, drift=False, timeout=False, malformed=False, diagnostics=0):
        calls = []
        stages = ('build_tools', 'prepare_fixture', 'own_fixture_files', 'start_isolated_peers',
                  'regression', 'prepare_synthetic_keys', 'seed_boundary', 'seed_credential_history', 'backup_database_and_keys', 'advance_budget_after_snapshot', 'verify_initial_credentials', 'fence_and_install_hba',
                  'verify_closed_boundary', 'restore_under_maintenance_boundary', 'verify_reopened_boundary',
                  'persist_prepared_candidate', 'prepare_restored_database', 'prepare_runtime_supply', 'authorize_open', 'verify_interrupted_closed', 'retry_interrupted_open', 'verify_retry_still_closed', 'install_runtime_boundary_and_enable_roles', 'runtime_write_replay_reference', 'retry_account_enable', 'verify_budget_after_open_retry', 'recreate_runtime_and_replay', 'verify_final_budget_history')
        def run(args, **kwargs):
            calls.append(args)
            self.assertTrue(args[3].startswith('vms-boundary-resume-test-'))
            self.assertEqual(args[3], calls[0][3])
            self.assertEqual(args[5], '/dev/null')
            for key in ('COMPOSE_PROJECT_NAME', 'CAMERA_TEST_DATABASE_URL', 'PGPASSWORD', 'VMS_PRODUCTION_PASSWORD'):
                self.assertNotIn(key, kwargs['env'])
            if 'down' in args: return subprocess.CompletedProcess(args, cleanup)
            if 'ps' in args or 'logs' in args:
                if diagnostics == 'timeout': raise subprocess.TimeoutExpired(args, 1)
                if diagnostics == 'error': raise OSError('synthetic diagnostic unavailable')
                if diagnostics == 'interrupt': raise KeyboardInterrupt()
                kwargs['stdout'].write(b'synthetic peer diagnostic; private fixture output\n')
                return subprocess.CompletedProcess(args, diagnostics)
            stage = stages[len(calls)-1]
            if timeout: raise subprocess.TimeoutExpired(args, 1)
            if stage == 'verify_final_budget_history':
                rows = transcript() if not malformed else transcript()[:-2]
                kwargs['stdout'].write(('\n'.join(json.dumps(r) for r in rows) + '\n').encode())
                if drift:
                    (self.root / 'src/platform/camera/internal/storage/maintenance_fixture.go').write_bytes(b'concurrent edit')
            if stage == fail_stage:
                kwargs['stdout'].write((json.dumps({'Package': tool.PACKAGE, 'Test': tool.OWNER_TEST, 'Action': 'fail'})+'\n').encode())
            return subprocess.CompletedProcess(args, 1 if stage == fail_stage else 0)
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), patch.dict(tool.os.environ,
            {'COMPOSE_PROJECT_NAME': 'vms-project', 'CAMERA_TEST_DATABASE_URL': 'synthetic-production',
             'PGPASSWORD': 'synthetic-private', 'VMS_PRODUCTION_PASSWORD': 'synthetic-private'}):
            result = tool.verify(self.root, run=run)
        self.assertEqual((self.root / '.env').read_bytes(), b'SYNTHETIC_ENV_SENTINEL')
        self.assertEqual((self.root / 'var/camera/credential-keys/key-bundle.json').read_bytes(), b'SYNTHETIC_KEY_SENTINEL')
        for field in ('production_services_modified', 'production_database_modified', 'production_keys_loaded',
                      'production_admission_state_created', 'credential_api_activated', 'production_restore_fence_implemented',
                      'business_runtime_ready', 'network_packet_filter_verified',
                      'production_hba_modified'):
            self.assertFalse(result[field])
        for field in ('log', 'report'):
            self.assertEqual(stat.S_IMODE(Path(result[field]).stat().st_mode), 0o600)
        self.assertEqual(calls[-1][-5:], ['down', '--volumes', '--remove-orphans', '--timeout', '5'])
        if fail_stage:
            self.assertEqual(len(calls), stages.index(fail_stage)+4)
            self.assertEqual(calls[-3][-2:], ['ps', '--all'])
            self.assertEqual(calls[-2][-7:], ['logs', '--no-color', '--tail', '100', 'boundary-db', 'boundary-owner', 'boundary-client'])
            self.assertEqual(result['last_command_exit_code'], 1)
        self.calls = calls
        return result

    def test_success_and_protected_files(self):
        result = self.mock_run()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['native_boundary_resume_phases_passed'], 24)

    def test_vet_failure_stops_and_cleans(self):
        result = self.mock_run(fail_stage='build_tools')
        self.assertEqual(result['failed_stage'], 'build_tools')
        self.assertFalse(result['go_vet_passed'])
        self.assertTrue(result['isolated_resources_removed'])

    def test_native_failure_has_fixed_safe_test_name(self):
        result = self.mock_run(fail_stage='fence_and_install_hba')
        self.assertEqual(result['failed_native_test'], tool.OWNER_TEST)
        self.assertFalse(result['go_race_passed'])
        self.assertTrue(result['go_vet_passed'])
        self.assertNotIn('native_boundary_resume_phases_passed', result)

    def test_timeout_cleans(self):
        result = self.mock_run(timeout=True)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['isolated_resources_removed'])

    def test_incomplete_transcript_cancels_command_success(self):
        self.assertEqual(self.mock_run(malformed=True)['status'], 'failed')

    def test_source_drift_cancels_pass(self):
        self.assertEqual(self.mock_run(drift=True)['code'], 'PROJECT_FILE_CHANGED')

    def test_cleanup_failure_cancels_pass(self):
        result = self.mock_run(cleanup=1)
        self.assertEqual(result['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertNotIn('native_boundary_resume_phases_passed', result)

    def test_untrusted_test_label_is_not_reported(self):
        rows = [{'Package': tool.PACKAGE, 'Test': 'postgres://synthetic-private', 'Action': 'fail'},
                {'Package': 'private.invalid', 'Test': tool.FIXTURE_TEST, 'Action': 'fail'}]
        self.log.write_text('\n'.join(json.dumps(r) for r in rows))
        self.assertIsNone(tool.failed_native_test(self.log))
        self.log.write_text('\n'.join(json.dumps({'Package': tool.PACKAGE, 'Test': name, 'Action': 'fail'}) for name in tool.NATIVE_TESTS))
        self.assertIsNone(tool.failed_native_test(self.log))

    def test_local_probe_proof_cannot_be_accepted_as_native(self):
        rows = transcript()
        for row in rows:
            if row.get('Action') == 'output' and row.get('Test') == tool.CLIENT_TEST:
                row['Output'] = row['Output'].replace(tool.PREFIX, 'LOCAL_BOUNDARY_PHASE_OK:')
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_local_resume_receipts_cannot_pass_native(self):
        rows = transcript()
        for row in rows:
            if row.get('Action') == 'output' and row.get('Test') in (tool.RESUME_OWNER, tool.RESUME_RUNTIME):
                row['Output'] = row['Output'].replace(tool.RESUME_PREFIX, 'LOCAL_BOUNDARY_RESUME_PHASE_OK:')
        with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_missing_or_wrong_resume_order_rejected(self):
        for mode in ('missing', 'order'):
            rows = transcript()
            i = next(i for i,r in enumerate(rows) if r.get('Action')=='output' and r.get('Test')==tool.RESUME_OWNER)
            if mode=='missing': rows.pop(i)
            else: rows[i]['Output']='fixture: '+tool.RESUME_PREFIX+'enable\n'
            with self.assertRaises(tool.VerificationError): self.summarize(rows)

    def test_runtime_failure_preserves_completed_restore_without_claiming_admission(self):
        result = self.mock_run(fail_stage='runtime_write_replay_reference')
        self.assertTrue(result['database_and_key_restore_performed'])
        self.assertEqual(result['isolated_restore_outcome'], 'completed')
        self.assertNotIn('public_whole_operation_admission_verified', result)
        self.assertFalse(result['business_runtime_ready'])

    def test_each_command_failure_stops_at_stage_and_cleans(self):
        for stage in ('prepare_fixture', 'own_fixture_files', 'start_isolated_peers', 'regression',
                      'seed_boundary', 'verify_initial_credentials', 'verify_closed_boundary',
                      'restore_under_maintenance_boundary', 'verify_reopened_boundary', 'persist_prepared_candidate',
                      'prepare_restored_database', 'prepare_runtime_supply', 'authorize_open', 'verify_interrupted_closed', 'retry_interrupted_open', 'verify_retry_still_closed', 'install_runtime_boundary_and_enable_roles', 'runtime_write_replay_reference', 'retry_account_enable', 'verify_budget_after_open_retry', 'recreate_runtime_and_replay', 'verify_final_budget_history',
                      'prepare_synthetic_keys', 'seed_credential_history', 'backup_database_and_keys', 'advance_budget_after_snapshot'):
            with self.subTest(stage=stage):
                result = self.mock_run(fail_stage=stage)
                self.assertEqual(result['failed_stage'], stage)
                self.assertTrue(result['isolated_resources_removed'])
                self.assertNotIn('native_boundary_resume_phases_passed', result)

    def test_stable_container_exec_and_no_production_files_supplied(self):
        self.mock_run()
        for args in self.calls[5:-1]:
            self.assertIn('exec', args)
            self.assertNotIn('run', args)
        encoded = json.dumps(self.calls)
        self.assertNotIn('key-bundle', encoded)
        self.assertNotIn('vms-project', encoded)

    def test_startup_failure_preserves_diagnostics_stage_and_exit(self):
        result = self.mock_run(fail_stage='start_isolated_peers')
        self.assertTrue(result['isolated_diagnostics_collected'])
        self.assertTrue(result['go_vet_passed'])
        self.assertFalse(result['go_race_passed'])
        self.assertEqual(result['failed_stage'], 'start_isolated_peers')
        self.assertEqual(result['last_completed_stage'], 'own_fixture_files')
        content = Path(result['log']).read_text()
        self.assertIn('ISOLATED_BOUNDARY_DIAGNOSTIC:ps', content)
        self.assertIn('ISOLATED_BOUNDARY_DIAGNOSTIC:logs', content)
        self.assertIn('private fixture output', content)
        self.assertNotIn('private fixture output', json.dumps(result))

    def test_failed_or_interrupted_diagnostics_still_clean_and_keep_cause(self):
        for reason in (1, 'timeout', 'error', 'interrupt'):
            with self.subTest(reason=reason):
                result = self.mock_run(fail_stage='start_isolated_peers', diagnostics=reason)
                self.assertFalse(result['isolated_diagnostics_collected'])
                self.assertEqual(result['code'], 'ISOLATED_BOUNDARY_COMMAND_FAILED')
                self.assertEqual(result['last_command_exit_code'], 1)
                self.assertTrue(result['isolated_resources_removed'])

    def test_restore_failure_is_uncertain_and_blocks_candidate_steps(self):
        result = self.mock_run(fail_stage='restore_under_maintenance_boundary')
        self.assertEqual(result['isolated_restore_outcome'], 'uncertain')
        self.assertFalse(result['database_and_key_restore_performed'])
        self.assertFalse(any('CAMERA_BOUNDARY_RESTORE_PHASE=prepare' in args for args in self.calls))

    def test_later_failure_preserves_completed_restore_fact(self):
        result = self.mock_run(fail_stage='prepare_restored_database')
        self.assertEqual(result['isolated_restore_outcome'], 'completed')
        self.assertTrue(result['database_and_key_restore_performed'])
        self.assertNotIn('native_boundary_resume_phases_passed', result)

    def test_success_is_open_only_in_disposable_fixture(self):
        result = self.mock_run()
        self.assertEqual(result['final_admission_state'], 'OPEN')
        self.assertEqual(result['final_candidate_budget_uses'], 1)
        self.assertTrue(result['public_whole_operation_admission_verified'])
        self.assertFalse(result['business_runtime_ready'])
        self.assertFalse(result['production_restore_fence_implemented'])

    def test_all_owner_phases_use_clean_launcher(self):
        self.mock_run()
        owners = [args for args in self.calls if 'exec' in args and 'boundary-owner' in args]
        self.assertEqual(len(owners), 16)
        for args in owners:
            i = args.index('boundary-owner')
            self.assertEqual(args[i+1:i+5], ['sh', '-ec', tool.OWNER_ENV, 'camera-boundary-owner'])
            self.assertEqual(args[i+5], '/exchange/test2json')
        clients = [args for args in self.calls if 'exec' in args and 'boundary-client' in args]
        self.assertEqual(len(clients), 7)
        self.assertTrue(all(tool.OWNER_ENV not in args for args in clients))

    def test_success_does_not_collect_failure_diagnostics(self):
        result = self.mock_run()
        self.assertFalse(result['isolated_diagnostics_collected'])
        self.assertFalse(any('ps' in args or 'logs' in args for args in self.calls))


class CredentialBoundaryStartupContractTest(unittest.TestCase):
    def test_official_entrypoint_cleared_host_cannot_select_a_custom_socket(self):
        # The official docker_process_sql clears PGHOST and PGHOSTADDR. This
        # subprocess exercises that shell contract, not a Docker/DB claim.
        import re
        compose = (Path(__file__).resolve().parents[1] / 'postgresql/compose.credential-boundary-resume-test.yaml').read_text()
        socket = re.search(r'unix_socket_directories=([^,\]\s]+)', compose).group(1)
        code = r"""
set -eu
psql() { test "${PGHOST:-/var/run/postgresql}" = "$TEST_LISTEN_SOCKET"; }
docker_process_sql() {
 local query_runner=( psql )
 PGHOST= PGHOSTADDR= "${query_runner[@]}" "$@"
}
PGHOST=/socket PGHOSTADDR=127.0.0.1 docker_process_sql
"""
        with patch.dict(tool.os.environ, {}, clear=True):
            env = {'TEST_LISTEN_SOCKET': '/socket'}
            old = subprocess.run(['/bin/bash', '-c', code], env=env, capture_output=True)
            self.assertNotEqual(old.returncode, 0)
            env['TEST_LISTEN_SOCKET'] = socket
            fixed = subprocess.run(['/bin/bash', '-c', code], env=env, capture_output=True)
            self.assertEqual(fixed.returncode, 0)
        self.assertIn('socket:' + socket + ':ro', compose)
        self.assertIn('socket:' + socket + '\n', compose)
        self.assertIn('CAMERA_BOUNDARY_SOCKET: ' + socket, compose)
        self.assertIn('chown postgres:postgres ' + socket, tool.OWN_FILES)
        self.assertNotIn('PGHOST:', compose)

    def test_healthcheck_waits_for_final_tcp_server(self):
        compose = (Path(__file__).resolve().parents[1] / 'postgresql/compose.credential-boundary-resume-test.yaml').read_text()
        # A socket-only initialization server must not satisfy --wait before it
        # shuts down. The final server is the one whose TCP listener we need.
        health = next(line for line in compose.splitlines() if 'pg_isready' in line)
        self.assertIn('-h 127.0.0.1', health)
        self.assertNotIn('-h /', health)


if __name__ == '__main__':
    unittest.main()


class CredentialOwnerEnvironmentTest(unittest.TestCase):
    def environment(self):
        import os
        return {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                'CAMERA_TEST_DATABASE_URL': 'postgres://synthetic:synthetic@fixture:5432/vms_camera_test?sslmode=disable',
                'CAMERA_TEST_ALLOW_SCHEMA_RESET': '1', 'CAMERA_BOUNDARY_BASE': '/exchange/boundary',
                'CAMERA_BOUNDARY_SOCKET': '/var/run/postgresql', 'CAMERA_BOUNDARY_RESTORE_ONLY': '1', 'CAMERA_BOUNDARY_RESUME_ONLY': '1',
                'CAMERA_BOUNDARY_PHASE': 'seed',
                'PG_MAJOR': '17', 'PG_VERSION': '17.11-1.pgdg12+2', 'PGDATA': '/var/lib/postgresql/data',
                'PGPASSWORD': 'synthetic-private', 'PGOPTIONS': '-c role=synthetic',
                'PGSERVICEFILE': '/synthetic/service', 'PG_FUTURE_SETTING': 'unknown',
                'VMS_PRODUCTION_PASSWORD': 'synthetic-private'}

    def launch(self, env, script, *args):
        import sys
        command = tool.owner_process_args([sys.executable, '-c', script, *args])
        command[0] = '/bin/sh'
        return subprocess.run(command,
                              env=env, capture_output=True, text=True, timeout=10)

    def test_pg_image_defaults_and_unknown_pg_variables_are_removed(self):
        env = self.environment()
        result = self.launch(env, 'import json,os; print(json.dumps(dict(os.environ)))')
        self.assertEqual(result.returncode, 0, result.stderr)
        child = json.loads(result.stdout)
        self.assertFalse(any(name.startswith('PG') for name in child))
        self.assertNotIn('VMS_PRODUCTION_PASSWORD', child)
        for name in ('PATH', 'CAMERA_TEST_DATABASE_URL', 'CAMERA_TEST_ALLOW_SCHEMA_RESET',
                     'CAMERA_BOUNDARY_BASE', 'CAMERA_BOUNDARY_SOCKET', 'CAMERA_BOUNDARY_RESTORE_ONLY',
                     'CAMERA_BOUNDARY_PHASE', 'CAMERA_BOUNDARY_RESUME_ONLY'):
            self.assertEqual(child[name], env[name])
        self.assertEqual(child['CAMERA_BOUNDARY_RESTORE_PHASE'], '')
        self.assertEqual(child['CAMERA_BOUNDARY_LOCAL_ONLY'], '')

    def test_owner_launcher_preserves_literal_arguments_and_phase(self):
        env = self.environment()
        env.update(CAMERA_BOUNDARY_RESTORE_PHASE='restore', CAMERA_BOUNDARY_LOCAL_ONLY='1')
        args = ('space argument', '$(exit 9)', 'literal; exit 9', '*.json', 'line1\nline2')
        result = self.launch(env, 'import json,os,sys; print(json.dumps([sys.argv[1:],os.environ["CAMERA_BOUNDARY_RESTORE_PHASE"],os.environ["CAMERA_BOUNDARY_LOCAL_ONLY"]]))', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [list(args), 'restore', '1'])

    def test_missing_explicit_fixture_values_stop_before_child(self):
        for name in ('PATH', 'CAMERA_TEST_DATABASE_URL', 'CAMERA_TEST_ALLOW_SCHEMA_RESET',
                     'CAMERA_BOUNDARY_BASE', 'CAMERA_BOUNDARY_SOCKET', 'CAMERA_BOUNDARY_RESTORE_ONLY', 'CAMERA_BOUNDARY_RESUME_ONLY'):
            env = self.environment(); env[name] = ''
            result = self.launch(env, 'print("CHILD_MUST_NOT_RUN")')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('CHILD_MUST_NOT_RUN', result.stdout)
