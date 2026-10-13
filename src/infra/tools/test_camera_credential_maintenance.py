#!/usr/bin/env python3
"""Disposable privileged DB fence and noncooperative drain; never production IO."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

from camera_activation import ActivationError, atomic_write, private_directory
from test_camera_credential_storage import checked_project, summarize_log as storage_summary, VerificationError, require, PACKAGE

SCOPE = 'camera_credential_maintenance_fence_native_postgresql'
REVISION = 'step11b3c3d1-maintenance-database-fence-20261007'
UNIT_TEST = 'TestCredentialMaintenanceRejectsWithoutIO'
PHASES = {
    'TestNativeCredentialMaintenanceAuthorityAndIdentity': ('authority-rejection', 'unsafe-role-rejection'),
    'TestNativeCredentialMaintenanceFenceAndRetry': ('no-login-existing-session', 'closed-database-drain', 'interrupted-fence-retry'),
    'TestNativeCredentialMaintenancePreparedTransactions': ('prepared-transaction-rejection', 'prepared-drain-retry'),
}
PREFIX = 'CREDENTIAL_MAINTENANCE_PHASE_OK:'
COPY = 'set -eu\ncp -a /source/. /work/\n'
VET = COPY + 'go vet ./...\n'
NATIVE = COPY + 'go test -p 1 -race -count=1 -json ./...\n'


def checked_revision(root):
    revision = checked_project(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_maintenance_revision') == REVISION
            and value.get('credential_operation_native_verified') is True
            and value.get('validated_credential_operation_project_sha256') ==
                '0765dfb6560779e289c129f96d1a656b6da3cc79c7e31ed64ffc74678aff28f0'
            and value.get('credential_maintenance_database_fence_implemented') is True
            and value.get('credential_runtime_admission_guard_implemented') is True,
            'STEP11_B3C3D1_PROJECT_REQUIRED')
    return revision


def summarize_log(path):
    result = storage_summary(path)
    pending, completed, actions = {}, {}, {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get('Package') != PACKAGE:
            continue
        name, action = row.get('Test'), row.get('Action')
        if action in ('pass', 'fail', 'skip'):
            actions[name] = action
        if name not in PHASES:
            continue
        if action == 'run':
            require(name not in pending and name not in completed, 'MAINTENANCE_TRANSCRIPT_INVALID')
            pending[name] = []
        elif action == 'output' and PREFIX in str(row.get('Output', '')):
            require(name in pending, 'MAINTENANCE_TRANSCRIPT_INVALID')
            pending[name].append(row['Output'].split(PREFIX, 1)[1].strip())
        elif action in ('pass', 'skip', 'fail'):
            require(name in pending and action == 'pass', 'NATIVE_MAINTENANCE_TESTS_REQUIRED')
            require(tuple(pending.pop(name)) == PHASES[name], 'COMPLETE_MAINTENANCE_PHASES_REQUIRED')
            completed[name] = True
    require(not pending and set(completed) == set(PHASES)
            and all(actions.get(name) == 'pass' for name in (UNIT_TEST, *PHASES))
            and actions.get(None) == 'pass', 'NATIVE_MAINTENANCE_TESTS_REQUIRED')
    return {**result, 'required_maintenance_tests_passed': len(PHASES) + 1,
            'native_maintenance_phases_passed': sum(map(len, PHASES.values())),
            'external_fenced_before_database_changes_verified': True,
            'unsafe_authority_and_endpoint_rejected': True,
            'no_login_existing_session_limitation_reproduced': True,
            'target_database_new_connections_blocked': True,
            'noncooperative_runtime_and_owner_sessions_drained': True,
            'cross_database_credential_sessions_drained': True,
            'committed_fence_retry_verified': True,
            'prepared_transactions_rejected': True,
            'committed_rows_and_budget_preserved': True}


def failed_native_test(path):
    names = set()
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (isinstance(row, dict) and row.get('Package') == PACKAGE
                    and row.get('Action') == 'fail' and row.get('Test') in PHASES):
                names.add(row['Test'])
    except OSError:
        return None
    return next(iter(names)) if len(names) == 1 else None


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_revision(root)
    directory = root / 'var/camera/credential-maintenance-checks'
    private_directory(directory)
    project = 'vms-credential-maintenance-test-' + secrets.token_hex(6)
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_', 'CAMERA_', 'PG'))}
    env['VMS_CAMERA_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-maintenance-test.yaml')]
    stage, last_completed, exit_code = 'go_vet', None, None
    failure, failed_stage, summary = None, None, {}
    vet_passed = completed = cleaned = False

    def execute(label, script):
        nonlocal stage, last_completed, exit_code
        stage = label
        with log.open('ab') as output:
            result = run(command + ['run', '--rm', 'camera-maintenance-test', 'sh', '-ec', script],
                         env=env.copy(), stdout=output, stderr=subprocess.STDOUT, timeout=900)
        exit_code = result.returncode
        require(exit_code == 0, 'ISOLATED_MAINTENANCE_COMMAND_FAILED')
        last_completed = stage

    try:
        execute('go_vet', VET)
        vet_passed = True
        execute('native_maintenance_and_regression', NATIVE)
        stage = 'verify_transcript'
        summary = summarize_log(log)
        last_completed = stage
        stage = 'verify_source'
        require(checked_revision(root) == revision, 'PROJECT_CHANGED_DURING_CHECK')
        last_completed = stage
        completed = True
    except VerificationError as error:
        failure = str(error)
    except (ActivationError, OSError, ValueError, TypeError, subprocess.TimeoutExpired, KeyboardInterrupt):
        failure = 'ISOLATED_MAINTENANCE_CHECK_INTERRUPTED'
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
    report = {'status': 'passed' if failure is None else 'failed', 'scope': SCOPE, 'project': project,
              'checked_revision': revision, 'maintenance_database_schema_version': 9,
              'legacy_storage_schema_version': 8, 'go_race_passed': completed,
              'go_vet_passed': vet_passed, **summary, 'production_services_modified': False,
              'production_database_modified': False, 'production_keys_loaded': False,
              'production_admission_state_created': False, 'credential_api_activated': False,
              'production_restore_fence_implemented': False, 'business_runtime_ready': False,
              'database_and_key_restore_performed': False, 'network_fence_verified': False,
              'isolated_resources_removed': cleaned, 'log': str(log)}
    if failure:
        report.update(code=failure, failed_stage=failed_stage, last_completed_stage=last_completed)
        test = failed_native_test(log)
        if test is not None:
            report['failed_native_test'] = test
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
    except (VerificationError, ActivationError, OSError, ValueError, TypeError, subprocess.TimeoutExpired, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': 'NATIVE_MAINTENANCE_CHECK_FAILED',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
