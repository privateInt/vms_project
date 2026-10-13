#!/usr/bin/env python3
"""Disposable DB/key restore under maintenance-only HBA; synthetic inputs only."""
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

SCOPE = 'camera_credential_boundary_restore_native_postgresql'
REVISION = 'step11b3c3d2b-boundary-restore-candidate-20261007'
OWNER_ENV_REVISION = 'step11b3c3d2b-explicit-owner-environment-fix-20261007'
UNIT_TESTS = ('TestCredentialMaintenanceHBAExactPolicy', 'TestCredentialMaintenanceConnectionConfiguration',
              'TestCredentialRestoreCandidateRejectsMissingAuthority')
FIXTURE_TEST = 'TestNativeCredentialMaintenanceBoundaryFixture'
OWNER_TEST = 'TestNativeCredentialMaintenanceBoundaryOwner'
CLIENT_TEST = 'TestNativeCredentialMaintenanceBoundaryClient'
RESTORE_TEST = 'TestNativeCredentialBoundaryRestore'
NATIVE_TESTS = (FIXTURE_TEST, OWNER_TEST, CLIENT_TEST, RESTORE_TEST)
PREFIX = 'CREDENTIAL_BOUNDARY_PHASE_OK:'
RESTORE_PREFIX = 'CREDENTIAL_BOUNDARY_RESTORE_PHASE_OK:'
EVENTS = ((FIXTURE_TEST, PREFIX, 'prepare'), (RESTORE_TEST, RESTORE_PREFIX, 'keys'),
          (OWNER_TEST, PREFIX, 'seed'), (RESTORE_TEST, RESTORE_PREFIX, 'history'),
          (RESTORE_TEST, RESTORE_PREFIX, 'backup'), (RESTORE_TEST, RESTORE_PREFIX, 'advance'),
          (CLIENT_TEST, PREFIX, 'client-before'), (OWNER_TEST, PREFIX, 'fence'),
          (CLIENT_TEST, PREFIX, 'client-closed'), (RESTORE_TEST, RESTORE_PREFIX, 'restore'),
          (CLIENT_TEST, PREFIX, 'client-open'), (RESTORE_TEST, RESTORE_PREFIX, 'prepare'),
          (RESTORE_TEST, RESTORE_PREFIX, 'commit'), (RESTORE_TEST, RESTORE_PREFIX, 'retry'),
          (CLIENT_TEST, PREFIX, 'client-closed'))
BUILD = 'set -eu\numask 077\nchmod 0755 /exchange\ncp -a /source/. /work/\ngo vet ./...\ngo test -race -c -o /exchange/storage.test ./camera/internal/storage\ngo build -o /exchange/test2json cmd/test2json\nchmod 0755 /exchange/storage.test /exchange/test2json\n'
REGRESSION = 'set -eu\ncp -a /source/. /work/\ngo test -p 1 -race -count=1 -json ./...\n'
# The PostgreSQL client image defines PG_MAJOR/PG_VERSION/PGDATA. The Go
# administrative opener deliberately rejects every ambient PG* variable.
# Compose's host environment filtering cannot remove image defaults: start
# owner test processes with an explicit allowlist. Keep the product guard strict.
OWNER_ENV = r"""exec env -i \
 PATH="${PATH:?}" \
 CAMERA_TEST_DATABASE_URL="${CAMERA_TEST_DATABASE_URL:?}" \
 CAMERA_TEST_ALLOW_SCHEMA_RESET="${CAMERA_TEST_ALLOW_SCHEMA_RESET:?}" \
 CAMERA_BOUNDARY_BASE="${CAMERA_BOUNDARY_BASE:?}" \
 CAMERA_BOUNDARY_SOCKET="${CAMERA_BOUNDARY_SOCKET:?}" \
 CAMERA_BOUNDARY_RESTORE_ONLY="${CAMERA_BOUNDARY_RESTORE_ONLY:?}" \
 CAMERA_BOUNDARY_PHASE="${CAMERA_BOUNDARY_PHASE-}" \
 CAMERA_BOUNDARY_RESTORE_PHASE="${CAMERA_BOUNDARY_RESTORE_PHASE-}" \
 CAMERA_BOUNDARY_LOCAL_ONLY="${CAMERA_BOUNDARY_LOCAL_ONLY-}" \
 "$@"
"""


def owner_process_args(args):
    # Positional arguments are preserved exactly, never interpolated as code.
    return ['sh', '-ec', OWNER_ENV, 'camera-boundary-owner', *args]

OWN_FILES = 'set -eu\nchown postgres:postgres /exchange/boundary/tls/server.key\nchmod 0400 /exchange/boundary/tls/server.key\nchown postgres:postgres /var/run/postgresql\nchmod 0755 /var/run/postgresql\n'


def checked_revision(root):
    revision = checked_project(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_boundary_restore_revision') == REVISION
            and value.get('credential_boundary_native_verified') is True
            and value.get('validated_credential_boundary_project_sha256') ==
                '08d9f3ae44d7a7f7d3d77a0d47606bfba6208ab47e3bf7385ba1e9144f148002'
            and value.get('credential_restore_candidate_preparation_implemented') is True
            and value.get('credential_boundary_restore_owner_environment_revision') == OWNER_ENV_REVISION,
            'STEP11_B3C3D2B_PROJECT_REQUIRED')
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
    actions, events, pending = {}, [], {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        require(row.get('Action') != 'fail', 'GO_TEST_FAILED')
        name, action, package = row.get('Test'), row.get('Action'), row.get('Package')
        if action in ('pass', 'skip'):
            actions[package, name] = action
        if package != PACKAGE or name not in NATIVE_TESTS:
            continue
        if action == 'run':
            require(name not in pending, 'RESTORE_TRANSCRIPT_INVALID')
            pending[name] = None
        elif action == 'output':
            for prefix in (PREFIX, RESTORE_PREFIX):
                if prefix not in str(row.get('Output', '')):
                    continue
                require(name in pending and pending[name] is None, 'RESTORE_TRANSCRIPT_INVALID')
                pending[name] = (name, prefix, row['Output'].split(prefix, 1)[1].strip())
        elif action in ('pass', 'skip'):
            require(name in pending, 'RESTORE_TRANSCRIPT_INVALID')
            event = pending.pop(name)
            if event is not None:
                require(action == 'pass' and len(events) < len(EVENTS) and event == EVENTS[len(events)],
                        'COMPLETE_BOUNDARY_RESTORE_PHASES_REQUIRED')
                events.append(event)
            else:
                require(action == 'skip', 'RESTORE_PHASE_PROOF_REQUIRED')
    require(not pending and tuple(events) == EVENTS
            and all(actions.get((PACKAGE, name)) == 'pass' for name in UNIT_TESTS)
            and actions.get(('vms.local/platform/camera/internal/credentialcrypto',
                             'TestCredentialRestoreSuccessorMaterial')) == 'pass'
            and actions.get((PACKAGE, None)) == 'pass', 'COMPLETE_RESTORE_TESTS_REQUIRED')
    return {**result, 'required_restore_tests_passed': len(UNIT_TESTS) + len(NATIVE_TESTS) + 1,
            'native_boundary_restore_phases_passed': len(EVENTS),
            'actual_dump_and_key_restore_verified': True,
            'snapshot_budget_rewind_reproduced': True,
            'external_authority_and_hba_preserved': True,
            'off_source_authentication_rejected_through_restore': True,
            'historical_ciphertext_and_hmac_preserved': True,
            'independent_fresh_key_and_incarnation_verified': True,
            'prepared_before_budget_and_marker_verified': True,
            'restored_old_keys_disabled': True,
            'same_candidate_process_retry_verified': True,
            'used_candidate_budget_reset_rejected': True,
            'used_candidate_open_rejected_without_reset': True,
            'wrong_backup_marker_rejected': True,
            'corrupt_archive_rejected_without_data_change': True,
            'final_admission_state': 'PREPARED', 'final_target_database_closed': True,
            'runtime_roles_remain_nologin': True,
            'owner_pg_environment_absence_verified': True}


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_revision(root)
    directory = root / 'var/camera/credential-boundary-restore-checks'
    private_directory(directory)
    project = 'vms-boundary-restore-test-' + secrets.token_hex(6)
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_', 'CAMERA_', 'PG'))}
    env['VMS_BOUNDARY_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-boundary-restore-test.yaml')]
    failure, summary, cleaned, completed = None, {}, False, False
    vet_completed, diagnostics_collected = False, False
    restore_started, restore_completed = False, False
    stage, last_completed, failed_stage, exit_code = 'build_tools', None, None, None

    def execute(label, args, timeout):
        nonlocal stage, last_completed, exit_code, vet_completed, restore_started, restore_completed
        stage = label
        if label == "restore_under_maintenance_boundary":
            restore_started = True
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output,
                         stderr=subprocess.STDOUT, timeout=timeout)
        exit_code = result.returncode
        require(exit_code == 0, 'ISOLATED_BOUNDARY_COMMAND_FAILED')
        last_completed = label
        if label == 'build_tools':
            vet_completed = True
        if label == 'restore_under_maintenance_boundary':
            restore_completed = True

    def test_args(name):
        return ['/exchange/test2json', '-t', '-p', PACKAGE, '/exchange/storage.test',
                '-test.v=test2json', '-test.count=1', '-test.run=^' + name + '$', '-test.timeout=90s']

    def owner(label, phase):
        execute(label, ['exec', '-T', '-e', 'CAMERA_BOUNDARY_PHASE=' + phase,
                        'boundary-owner', *owner_process_args(test_args(OWNER_TEST))], 120)

    def client(label, probe):
        execute(label, ['exec', '-T', '-e', 'CAMERA_BOUNDARY_PROBE=' + probe,
                        'boundary-client', *test_args(CLIENT_TEST)], 120)

    def restore(label, phase):
        execute(label, ['exec', '-T', '-e', 'CAMERA_BOUNDARY_RESTORE_PHASE=' + phase,
                        'boundary-owner', *owner_process_args(test_args(RESTORE_TEST))], 120)

    try:
        execute('build_tools', ['run', '--rm', '--no-deps', 'boundary-build', 'sh', '-ec', BUILD], 900)
        execute('prepare_fixture', ['run', '--rm', '--no-deps', '-e', 'CAMERA_BOUNDARY_PHASE=prepare',
                'boundary-build', *test_args(FIXTURE_TEST)], 120)
        execute('own_fixture_files', ['run', '--rm', '--no-deps', 'boundary-files-owner', 'sh', '-ec', OWN_FILES], 60)
        execute('start_isolated_peers', ['up', '--detach', '--wait', '--wait-timeout', '90',
                'boundary-db', 'boundary-owner', 'boundary-client'], 120)
        execute('regression', ['run', '--rm', '--no-deps', 'boundary-build', 'sh', '-ec', REGRESSION], 900)
        restore('prepare_synthetic_keys', 'keys')
        owner('seed_boundary', 'seed')
        restore('seed_credential_history', 'history')
        restore('backup_database_and_keys', 'backup')
        restore('advance_budget_after_snapshot', 'advance')
        client('verify_initial_credentials', 'before')
        owner('fence_and_install_hba', 'fence')
        client('verify_closed_boundary', 'closed')
        restore('restore_under_maintenance_boundary', 'restore')
        client('verify_reopened_boundary', 'open')
        restore('persist_prepared_candidate', 'prepare')
        restore('prepare_restored_database', 'commit')
        restore('retry_candidate_and_close_target', 'retry')
        client('verify_final_closed_boundary', 'closed')
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
              'project': project, 'checked_revision': revision, 'restore_database_schema_version': 9,
              'legacy_storage_schema_version': 8, 'go_race_passed': completed,
              'go_vet_passed': vet_completed, **summary, 'production_services_modified': False,
              'production_database_modified': False, 'production_keys_loaded': False,
              'production_admission_state_created': False, 'credential_api_activated': False,
              'production_restore_fence_implemented': False, 'business_runtime_ready': False,
              'database_and_key_restore_performed': restore_completed,
              'isolated_restore_outcome': ('completed' if restore_completed else 'uncertain' if restore_started else 'not_started'), 'network_packet_filter_verified': False,
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
                          'code': 'NATIVE_BOUNDARY_RESTORE_CHECK_FAILED',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
