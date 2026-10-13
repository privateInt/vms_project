#!/usr/bin/env python3
"""Disposable full credential operation leases; synthetic authority and DB only."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

from camera_activation import ActivationError, atomic_write, private_directory
from test_camera_credential_storage import checked_project, VerificationError, require, PACKAGE
from test_camera_credential_bindings import summarize_log as binding_summary

SCOPE = 'camera_credential_operation_leases_native_postgresql'
REVISION = 'step11b3c3c-credential-operation-leases-20261007'
DIAGNOSTIC_REVISION = 'step11b3c3c-signal-and-diagnostics-fix-20261007'
FAILURE_PREFIX = 'CREDENTIAL_OPERATION_FAILURE_COMPONENT:'
FAILURE_COMPONENTS = frozenset(('owner_signal', 'child_start', 'child_protocol', 'child_wait',
    'child_identity', 'child_keys', 'child_authority_pin', 'child_database_setup',
    'child_endpoint', 'child_restart_fixture', 'child_approved_pools', 'child_constructor',
    'child_ready', 'child_failure_unwind', 'child_required_grants', 'child_create',
    'child_write_replay', 'child_reference', 'child_revoke', 'child_revoke_replay',
    'child_append', 'child_interrupted_write', 'child_recreated', 'child_unknown'))
TESTS = ('TestCredentialOperationRequiresLeaseWithoutIO',
         'TestCredentialOperationPinsOwnedPolicy',
         'TestCredentialOperationLeaseReleasedOnErrorAndPanic',
         'TestNativeCredentialOperationRequiredGrants',
         'TestNativeCredentialOperationLeases')
PHASES = ('failure-unwind', 'create', 'write-replay', 'reference', 'revoke',
          'revoke-replay', 'append', 'death-drain-budget', 'stale-recreation')
FIXTURE_TEST = 'TestNativeCredentialBindingFixture'
BINDING_TEST = 'TestNativeCredentialApprovedBindings'
BUILD = 'set -eu\numask 077\nchmod 0755 /exchange\ncp -a /source/. /work/\ngo vet ./...\ngo test -race -c -o /exchange/storage.test ./camera/internal/storage\ngo build -o /exchange/test2json cmd/test2json\nchmod 0755 /exchange/storage.test /exchange/test2json\n'
REGRESSION = 'cp -a /source/. /work/; go test -p 1 -race -count=1 -json ./...'
OWN_TLS_KEY = 'chown postgres:postgres /exchange/fixture/tls/server.key; chmod 0400 /exchange/fixture/tls/server.key'


def checked_revision(root):
    revision = checked_project(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_operation_revision') == REVISION
            and value.get('credential_operation_diagnostic_revision') == DIAGNOSTIC_REVISION
            and value.get('credential_binding_native_verified') is True
            and value.get('credential_runtime_admission_guard_implemented') is True
            and isinstance(value.get('credential_operation_native_verified'), bool),
            'STEP11_B3C3C_PROJECT_REQUIRED')
    return revision


def native_failure_component(path):
    components = set()
    try:
        with path.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (not isinstance(row, dict) or row.get('Package') != PACKAGE
                        or row.get('Test') != TESTS[-1] or row.get('Action') != 'output'):
                    continue
                output = row.get('Output', '')
                if not isinstance(output, str) or FAILURE_PREFIX not in output:
                    continue
                value = output.split(FAILURE_PREFIX, 1)[1].strip()
                if value in FAILURE_COMPONENTS:
                    components.add(value)
    except OSError:
        return None
    return next(iter(components)) if len(components) == 1 else None


def summarize_log(path):
    result = binding_summary(path)
    actions, phases, pending = {}, [], None
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        require(row.get('Action') != 'fail', 'GO_TEST_FAILED')
        require(not (row.get('Package') == PACKAGE and row.get('Test') == TESTS[-1]
                     and row.get('Action') == 'output'
                     and FAILURE_PREFIX in str(row.get('Output', ''))),
                'NATIVE_OPERATION_FAILURE_REPORTED')
        if row.get('Package') != PACKAGE:
            continue
        name, action = row.get('Test'), row.get('Action')
        if action in ('pass', 'fail', 'skip'):
            actions[name] = action
        if name != TESTS[-1]:
            continue
        if action == 'run':
            require(pending is None, 'OPERATION_TRANSCRIPT_INVALID')
            pending = []
        elif action == 'output' and 'CREDENTIAL_OPERATION_PHASE_OK:' in row.get('Output', ''):
            require(pending is not None, 'OPERATION_TRANSCRIPT_INVALID')
            pending.append(row['Output'].split('CREDENTIAL_OPERATION_PHASE_OK:', 1)[1].strip())
        elif action in ('pass', 'skip'):
            require(pending is not None, 'OPERATION_TRANSCRIPT_INVALID')
            if action == 'pass':
                require(tuple(pending) == PHASES, 'COMPLETE_OPERATION_PHASES_REQUIRED')
                phases.extend(pending)
            else:
                require(not pending, 'OPERATION_PHASE_NOT_PASSED')
            pending = None
    require(pending is None and tuple(phases) == PHASES, 'COMPLETE_OPERATION_PHASES_REQUIRED')
    require(all(actions.get(name) == 'pass' for name in TESTS)
            and actions.get(None) == 'pass', 'COMPLETE_OPERATION_TESTS_REQUIRED')
    return {**result, 'required_operation_tests_passed': len(TESTS),
            'native_operation_phases_passed': len(PHASES),
            'full_operation_lease_verified': True,
            'write_replay_reference_revoke_leases_verified': True,
            'maintenance_wait_and_normal_drain_verified': True,
            'panic_error_and_cancellation_unwind_verified': True,
            'process_death_drain_verified': True,
            'interrupted_budget_preserved_without_data_commit': True,
            'fenced_process_recreation_denied': True,
            'unadmitted_business_calls_rejected': True}


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_revision(root)
    directory = root / 'var/camera/credential-operation-checks'
    private_directory(directory)
    project = 'vms-credential-operations-test-' + secrets.token_hex(6)
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_BINDINGS_', 'VMS_ADMISSION_', 'VMS_OPERATIONS_', 'CAMERA_', 'PG'))}
    env['VMS_BINDINGS_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-operation-test.yaml')]
    failure, summary, cleaned, completed = None, {}, False, False
    stage, last_completed, failed_stage, exit_code = 'build_tools', None, None, None

    def execute(label, args, timeout):
        nonlocal stage, last_completed, exit_code
        stage = label
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output,
                         stderr=subprocess.STDOUT, timeout=timeout)
        exit_code = result.returncode
        require(exit_code == 0, 'ISOLATED_OPERATION_COMMAND_FAILED')
        last_completed = label

    try:
        execute('build_tools', ['run', '--rm', '--no-deps', 'bindings-build', 'sh', '-ec', BUILD], 900)
        execute('prepare_fixture', ['run', '--rm', '--no-deps', '-e', 'CAMERA_BINDING_TEST_PHASE=prepare',
                'bindings-build', '/exchange/test2json', '-t', '-p', PACKAGE,
                '/exchange/storage.test', '-test.v=test2json', '-test.count=1',
                '-test.run=^' + FIXTURE_TEST + '$', '-test.timeout=60s'], 120)
        execute('own_tls_key', ['run', '--rm', '--no-deps', 'bindings-owner', 'sh', '-ec', OWN_TLS_KEY], 60)
        execute('start_tls_database', ['up', '--detach', '--wait', '--wait-timeout', '90', 'bindings-db'], 120)
        execute('regression', ['run', '--rm', '--no-deps', 'bindings-build', 'sh', '-ec', REGRESSION], 900)
        execute('runtime_tls_bindings', ['run', '--rm', 'bindings-runtime', '/exchange/test2json', '-t', '-p', PACKAGE,
                '/exchange/storage.test', '-test.v=test2json', '-test.count=1',
                '-test.run=^' + BINDING_TEST + '$', '-test.timeout=120s'], 180)
        execute('runtime_operation_leases', ['run', '--rm', 'operations-owner', '/exchange/test2json', '-t', '-p', PACKAGE,
                '/exchange/storage.test', '-test.v=test2json', '-test.count=1',
                '-test.run=^' + TESTS[-1] + '$', '-test.timeout=170s'], 210)
        stage = 'verify_transcript'
        summary = summarize_log(log)
        last_completed = stage
        stage = 'verify_source'
        require(checked_revision(root) == revision, 'PROJECT_CHANGED_DURING_CHECK')
        last_completed = stage
        completed = True
    except VerificationError as error:
        failure = str(error)
    except (ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        failure = 'ISOLATED_OPERATION_CHECK_INTERRUPTED'
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
              'project': project, 'checked_revision': revision, 'operation_database_schema_version': 9,
              'legacy_storage_schema_version': 8, 'go_race_passed': completed,
              'go_vet_passed': completed, **summary, 'production_services_modified': False,
              'production_database_modified': False, 'production_keys_loaded': False,
              'production_admission_state_created': False, 'credential_api_activated': False,
              'production_restore_fence_implemented': False, 'business_runtime_ready': False,
              'runtime_admission_guard_implemented': True, 'isolated_resources_removed': cleaned,
              'log': str(log)}
    if failure:
        report.update(code=failure, failed_stage=failed_stage, last_completed_stage=last_completed)
        component = native_failure_component(log)
        if component is not None:
            report['failed_native_component'] = component
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
    except (VerificationError, ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE,
                          'code': 'NATIVE_OPERATION_CHECK_FAILED',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
