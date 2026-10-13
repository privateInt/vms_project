#!/usr/bin/env python3
"""Actual admitted credential HTTP, disposable schema9/UID/RO/TLS only."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

from camera_activation import ActivationError, atomic_write, private_directory
import test_camera_credential_versions as versions

storage = versions.storage
PACKAGE = versions.HTTP_PACKAGE
SCOPE = 'camera_credential_admitted_management_http_native_postgresql'
POLICY_TESTS = (
    'TestCredentialManagementConfiguration', 'TestCredentialManagementVerifiedPeerAndScope',
    'TestCredentialManagementRejectsUnverifiedPeer', 'TestCredentialManagementReplacementAndRecheck',
    'TestCredentialManagementConcurrentReplacement', 'TestCredentialManagementExplicitRegistrationAndTLS',
)
NATIVE_TEST = 'TestNativeCredentialManagementHTTP'
PHASES = ('schema9-role-key-authority', 'actual-runtime-bindings',
          'http-write-metadata-revoke-replay', 'policy-and-usage-denials',
          'whole-http-lease-and-drain', 'recreated-http-replay',
          'actual-grant-and-marker-loss', 'fenced-and-recreated-denial')
PREFIX = 'CREDENTIAL_MANAGEMENT_PHASE_OK:'
BUILD = ('set -eu\numask 077\nchmod 0755 /exchange\ncp -a /source/. /work/\n'
         'go vet ./...\ngo test -race -c -o /exchange/storage.test ./camera/internal/storage\n'
         'go test -race -c -o /exchange/app.test ./camera/internal/app\n'
         'go build -o /exchange/test2json cmd/test2json\n'
         'chmod 0755 /exchange/storage.test /exchange/app.test /exchange/test2json\n')
REGRESSION = 'cp -a /source/. /work/; go test -p 1 -race -count=1 -json ./...'
OWN_TLS_KEY = 'chown postgres:postgres /exchange/fixture/tls/server.key; chmod 0400 /exchange/fixture/tls/server.key'


def checked_revision(root):
    revision = storage.checked_project(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    storage.require(value.get('credential_management_http_implemented') is True
                    and value.get('credential_runtime_admission_guard_implemented') is True
                    and value.get('credential_management_http_registered_in_current_main') is False,
                    'CREDENTIAL_MANAGEMENT_PROJECT_REQUIRED')
    return revision


def summarize_log(path):
    # Historical C1/C2 component tests remain mandatory; their synthetic store
    # declarations are preserved separately from this new native transcript.
    component = versions.summarize_log(path)
    pending, accepted, terminal = None, [], {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        storage.require(row.get('Action') != 'fail', 'GO_TEST_FAILED')
        if row.get('Package') != PACKAGE:
            continue
        name, action = row.get('Test'), row.get('Action')
        if action in ('pass', 'skip'):
            terminal[name] = action
        if name != NATIVE_TEST:
            continue
        if action == 'run':
            storage.require(pending is None, 'MANAGEMENT_TRANSCRIPT_INVALID')
            pending = []
        elif action == 'output' and PREFIX in str(row.get('Output', '')):
            storage.require(pending is not None, 'MANAGEMENT_TRANSCRIPT_INVALID')
            pending.append(row['Output'].split(PREFIX, 1)[1].strip())
        elif action in ('pass', 'skip'):
            storage.require(pending is not None, 'MANAGEMENT_TRANSCRIPT_INVALID')
            if action == 'pass':
                storage.require(tuple(pending) == PHASES, 'COMPLETE_MANAGEMENT_PHASES_REQUIRED')
                accepted.extend(pending)
            else:
                storage.require(not pending, 'MANAGEMENT_PHASE_NOT_PASSED')
            pending = None
    storage.require(pending is None and tuple(accepted) == PHASES,
                    'COMPLETE_MANAGEMENT_PHASES_REQUIRED')
    storage.require(terminal.get(None) == 'pass'
                    and all(terminal.get(name) == 'pass' for name in (*POLICY_TESTS, NATIVE_TEST)),
                    'COMPLETE_MANAGEMENT_TESTS_REQUIRED')
    component['c1_c2_component_native_admitted_http_verified'] = False
    component.update(required_management_policy_tests_passed=len(POLICY_TESTS),
                     required_native_management_tests_passed=1,
                     native_management_phases_passed=len(PHASES),
                     native_admitted_store_http_writes_verified=True,
                     native_admitted_store_version_http_verified=True,
                     concrete_management_policy_verified=True,
                     verified_mtls_peer_and_device_manage_binding_verified=True,
                     policy_replacement_denies_success_replay=True,
                     schema_9_marker_two_role_tls_and_read_only_receipts_verified=True,
                     runtime_owner_dsn_absence_verified=True,
                     http_revoke_lease_and_maintenance_drain_verified=True,
                     actual_grant_and_marker_loss_denied_without_budget_use=True,
                     recreated_http_replay_preserves_budget=True,
                     fenced_http_and_recreated_runtime_denied=True,
                     usage_guard_success_is_fixture_only=True,
                     production_managed_reference_usage_guard_implemented=False,
                     enterprise_iam_integration_verified=False)
    return component


def verify(root, run=subprocess.run):
    revision = checked_revision(root)
    storage.require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    directory = root / 'var/camera/credential-management-checks'
    private_directory(directory)
    project = 'vms-credential-management-test-' + secrets.token_hex(6)
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_', 'CAMERA_', 'PG'))}
    env['VMS_BINDINGS_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-management-test.yaml')]
    failure, summary, cleaned, completed = None, {}, False, False
    stage, last_completed, failed_stage, exit_code = 'build_tools', None, None, None

    def execute(label, args, timeout):
        nonlocal stage, last_completed, exit_code
        stage = label
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output,
                         stderr=subprocess.STDOUT, timeout=timeout)
        exit_code = result.returncode
        storage.require(exit_code == 0, 'ISOLATED_MANAGEMENT_COMMAND_FAILED')
        last_completed = label

    try:
        execute('build_tools', ['run', '--rm', '--no-deps', 'bindings-build', 'sh', '-ec', BUILD], 900)
        execute('prepare_fixture', ['run', '--rm', '--no-deps', '-e', 'CAMERA_BINDING_TEST_PHASE=prepare',
                'bindings-build', '/exchange/test2json', '-t', '-p', storage.PACKAGE,
                '/exchange/storage.test', '-test.v=test2json', '-test.count=1',
                '-test.run=^TestNativeCredentialBindingFixture$', '-test.timeout=60s'], 120)
        execute('own_tls_key', ['run', '--rm', '--no-deps', 'bindings-owner', 'sh', '-ec', OWN_TLS_KEY], 60)
        execute('start_tls_database', ['up', '--detach', '--wait', '--wait-timeout', '90', 'bindings-db'], 120)
        execute('regression', ['run', '--rm', '--no-deps', 'bindings-build', 'sh', '-ec', REGRESSION], 900)
        execute('admitted_management_http', ['run', '--rm', 'management-owner', '/exchange/test2json',
                '-t', '-p', PACKAGE, '/exchange/app.test', '-test.v=test2json', '-test.count=1',
                '-test.run=^' + NATIVE_TEST + '$', '-test.timeout=180s'], 210)
        stage = 'verify_transcript'
        summary = summarize_log(log)
        last_completed = stage
        stage = 'verify_source'
        storage.require(checked_revision(root) == revision, 'PROJECT_CHANGED_DURING_CHECK')
        last_completed = stage
        completed = True
    except storage.VerificationError as error:
        failure = str(error)
    except (ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        failure = 'ISOLATED_MANAGEMENT_CHECK_INTERRUPTED'
    finally:
        if failure:
            failed_stage = stage
        try:
            with log.open('ab') as output:
                result = run(command + ['down', '--volumes', '--remove-orphans', '--timeout', '5'],
                             env=env, stdout=output, stderr=subprocess.STDOUT, timeout=60)
            cleaned = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
            cleaned = False
    if not cleaned:
        failure = 'ISOLATED_CLEANUP_INCOMPLETE'
        failed_stage = failed_stage or 'cleanup'
    if failure:
        summary = {}
    report = {'status': 'passed' if failure is None else 'failed', 'scope': SCOPE,
              'project': project, 'checked_revision': revision, 'management_database_schema_version': 9,
              'legacy_storage_schema_version': 8, 'go_race_passed': completed,
              'go_vet_passed': completed, **summary, 'production_services_modified': False,
              'production_database_modified': False, 'production_keys_loaded': False,
              'production_admission_state_created': False, 'credential_api_activated': False,
              'business_runtime_ready': False, 'isolated_resources_removed': cleaned, 'log': str(log)}
    if failure:
        report.update(code=failure, failed_stage=failed_stage, last_completed_stage=last_completed)
        if exit_code is not None:
            report['last_command_exit_code'] = exit_code
    path = directory / (project + '.json')
    report['report'] = str(path)
    atomic_write(path, (json.dumps(report, indent=2) + '\n').encode())
    return report


def main():
    try:
        result = verify(Path(__file__).resolve().parents[3])
        print(json.dumps(result))
        return 0 if result['status'] == 'passed' else 1
    except (storage.VerificationError, ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': 'MANAGEMENT_HTTP_CHECK_FAILED',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
