#!/usr/bin/env python3
"""Disposable maintenance-only HBA boundary; synthetic certificates/roles/authority only."""
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
from test_camera_credential_storage import summarize_log as storage_summary

SCOPE = 'camera_credential_maintenance_hba_boundary_native_postgresql'
REVISION = 'step11b3c3d2a-maintenance-hba-boundary-20261007'
STARTUP_REVISION = 'step11b3c3d2a-default-socket-diagnostics-fix-20261007'
UNIT_TESTS = ('TestCredentialMaintenanceHBAExactPolicy', 'TestCredentialMaintenanceConnectionConfiguration')
FIXTURE_TEST = 'TestNativeCredentialMaintenanceBoundaryFixture'
OWNER_TEST = 'TestNativeCredentialMaintenanceBoundaryOwner'
CLIENT_TEST = 'TestNativeCredentialMaintenanceBoundaryClient'
NATIVE_TESTS = (FIXTURE_TEST, OWNER_TEST, CLIENT_TEST)
PHASES = ('prepare', 'seed', 'client-before', 'fence', 'client-closed', 'reopen', 'client-open', 'retry')
PHASE_PARENTS = (FIXTURE_TEST, OWNER_TEST, CLIENT_TEST, OWNER_TEST, CLIENT_TEST, OWNER_TEST, CLIENT_TEST, OWNER_TEST)
PREFIX = 'CREDENTIAL_BOUNDARY_PHASE_OK:'
BUILD = 'set -eu\numask 077\nchmod 0755 /exchange\ncp -a /source/. /work/\ngo vet ./...\ngo test -race -c -o /exchange/storage.test ./camera/internal/storage\ngo build -o /exchange/test2json cmd/test2json\nchmod 0755 /exchange/storage.test /exchange/test2json\n'
REGRESSION = 'set -eu\ncp -a /source/. /work/\ngo test -p 1 -race -count=1 -json ./...\n'
OWN_FILES = 'set -eu\nchown postgres:postgres /exchange/boundary/tls/server.key\nchmod 0400 /exchange/boundary/tls/server.key\nchown postgres:postgres /var/run/postgresql\nchmod 0755 /var/run/postgresql\n'


def checked_revision(root):
    revision = checked_project(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_boundary_revision') == REVISION
            and value.get('credential_boundary_startup_revision') == STARTUP_REVISION
            and value.get('credential_maintenance_native_verified') is True
            and value.get('validated_credential_maintenance_project_sha256') ==
                'a2116e85a9d93b03ea54e65c4209d3b5b82b946c27e2f2377f6fe64e5e812e0d'
            and value.get('credential_maintenance_hba_policy_implemented') is True
            and value.get('credential_maintenance_mtls_opener_implemented') is True,
            'STEP11_B3C3D2A_PROJECT_REQUIRED')
    return revision


def failed_native_test(path):
    names = set()
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (isinstance(row, dict) and row.get('Package') == PACKAGE
                    and row.get('Action') == 'fail' and row.get('Test') in NATIVE_TESTS):
                names.add(row['Test'])
    except OSError:
        return None
    return next(iter(names)) if len(names) == 1 else None


def summarize_log(path):
    result = storage_summary(path)
    actions, phases, pending = {}, [], {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        require(row.get('Action') != 'fail', 'GO_TEST_FAILED')
        if row.get('Package') != PACKAGE:
            continue
        name, action = row.get('Test'), row.get('Action')
        if action in ('pass', 'fail', 'skip'):
            actions[name] = action
        if name not in NATIVE_TESTS:
            continue
        if action == 'run':
            require(name not in pending, 'BOUNDARY_TRANSCRIPT_INVALID')
            pending[name] = None
        elif action == 'output' and PREFIX in str(row.get('Output', '')):
            require(name in pending and pending[name] is None, 'BOUNDARY_TRANSCRIPT_INVALID')
            pending[name] = row['Output'].split(PREFIX, 1)[1].strip()
        elif action in ('pass', 'skip'):
            require(name in pending, 'BOUNDARY_TRANSCRIPT_INVALID')
            phase = pending.pop(name)
            if phase is not None:
                require(action == 'pass' and len(phases) < len(PHASES)
                        and name == PHASE_PARENTS[len(phases)] and phase == PHASES[len(phases)],
                        'COMPLETE_BOUNDARY_PHASES_REQUIRED')
                phases.append(phase)
            else:
                require(action == 'skip', 'BOUNDARY_PHASE_PROOF_REQUIRED')
    require(not pending and tuple(phases) == PHASES
            and all(actions.get(name) == 'pass' for name in UNIT_TESTS)
            and actions.get(None) == 'pass', 'COMPLETE_BOUNDARY_TESTS_REQUIRED')
    return {**result, 'required_boundary_tests_passed': len(UNIT_TESTS) + len(NATIVE_TESTS),
            'native_boundary_phases_passed': len(PHASES),
            'fenced_database_before_hba_change_verified': True,
            'hba_outside_database_data_verified': True,
            'actual_maintenance_mtls_authentication_verified': True,
            'valid_credentials_from_other_source_rejected': True,
            'wrong_role_missing_certificate_wrong_cn_plaintext_and_socket_rejected': True,
            'fresh_authentication_after_reload_verified': True,
            'maintenance_only_target_reconnect_verified': True,
            'recreated_control_connection_and_lease_verified': True,
            'external_fenced_and_budget_preserved': True,
            'separate_probe_uid_and_read_only_mount_verified': True}


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_revision(root)
    directory = root / 'var/camera/credential-boundary-checks'
    private_directory(directory)
    project = 'vms-credential-boundary-test-' + secrets.token_hex(6)
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_', 'CAMERA_', 'PG'))}
    env['VMS_BOUNDARY_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-boundary-test.yaml')]
    failure, summary, cleaned, completed = None, {}, False, False
    vet_completed, diagnostics_collected = False, False
    stage, last_completed, failed_stage, exit_code = 'build_tools', None, None, None

    def execute(label, args, timeout):
        nonlocal stage, last_completed, exit_code, vet_completed
        stage = label
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output,
                         stderr=subprocess.STDOUT, timeout=timeout)
        exit_code = result.returncode
        require(exit_code == 0, 'ISOLATED_BOUNDARY_COMMAND_FAILED')
        last_completed = label
        if label == 'build_tools':
            vet_completed = True

    def test_args(name):
        return ['/exchange/test2json', '-t', '-p', PACKAGE, '/exchange/storage.test',
                '-test.v=test2json', '-test.count=1', '-test.run=^' + name + '$', '-test.timeout=90s']

    def owner(label, phase):
        execute(label, ['exec', '-T', '-e', 'CAMERA_BOUNDARY_PHASE=' + phase,
                        'boundary-owner', *test_args(OWNER_TEST)], 120)

    def client(label, probe):
        execute(label, ['exec', '-T', '-e', 'CAMERA_BOUNDARY_PROBE=' + probe,
                        'boundary-client', *test_args(CLIENT_TEST)], 120)

    try:
        execute('build_tools', ['run', '--rm', '--no-deps', 'boundary-build', 'sh', '-ec', BUILD], 900)
        execute('prepare_fixture', ['run', '--rm', '--no-deps', '-e', 'CAMERA_BOUNDARY_PHASE=prepare',
                'boundary-build', *test_args(FIXTURE_TEST)], 120)
        execute('own_fixture_files', ['run', '--rm', '--no-deps', 'boundary-files-owner', 'sh', '-ec', OWN_FILES], 60)
        execute('start_isolated_peers', ['up', '--detach', '--wait', '--wait-timeout', '90',
                'boundary-db', 'boundary-owner', 'boundary-client'], 120)
        execute('regression', ['run', '--rm', '--no-deps', 'boundary-build', 'sh', '-ec', REGRESSION], 900)
        owner('seed_boundary', 'seed')
        client('verify_initial_credentials', 'before')
        owner('fence_and_install_hba', 'fence')
        client('verify_closed_boundary', 'closed')
        owner('maintenance_target_reconnect', 'reopen')
        client('verify_reopened_boundary', 'open')
        owner('retry_and_refence', 'retry')
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
        failure = 'ISOLATED_BOUNDARY_CHECK_INTERRUPTED'
    finally:
        if failure:
            failed_stage = stage
            # Preserve actual peer output before down removes the failed containers.
            # Diagnostics never advance stages or overwrite the failed command exit.
            diagnostics_collected = True
            for label, args in (
                    ('ps', ['ps', '--all']),
                    ('logs', ['logs', '--no-color', '--tail', '100',
                              'boundary-db', 'boundary-owner', 'boundary-client'])):
                try:
                    with log.open('ab') as output:
                        output.write(('\nISOLATED_BOUNDARY_DIAGNOSTIC:' + label + '\n').encode())
                        output.flush()
                        result = run(command + args, env=env.copy(), stdout=output,
                                     stderr=subprocess.STDOUT, timeout=30)
                    diagnostics_collected = diagnostics_collected and result.returncode == 0
                except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                    diagnostics_collected = False
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
              'project': project, 'checked_revision': revision, 'boundary_database_schema_version': 9,
              'legacy_storage_schema_version': 8, 'go_race_passed': completed,
              'go_vet_passed': vet_completed, **summary, 'production_services_modified': False,
              'production_database_modified': False, 'production_keys_loaded': False,
              'production_admission_state_created': False, 'credential_api_activated': False,
              'production_restore_fence_implemented': False, 'business_runtime_ready': False,
              'database_and_key_restore_performed': False, 'network_packet_filter_verified': False,
              'production_hba_modified': False, 'isolated_resources_removed': cleaned,
              'isolated_diagnostics_collected': diagnostics_collected,
              'log': str(log)}
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
    except (VerificationError, ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE,
                          'code': 'NATIVE_BOUNDARY_CHECK_FAILED',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
