#!/usr/bin/env python3
"""Disposable native schema 9 marker check; no production paths, keys or ports."""
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

SCOPE = 'camera_credential_admission_database_native_postgresql'
REVISION = 'step11b3c3a-admission-database-20261007'
TESTS = ('TestNativeAdmissionDatabaseUpgradeAndPreservation',
         'TestNativeAdmissionDatabaseMarkerConstraints',
         'TestNativeAdmissionDatabaseActualRolesAndBinding',
         'TestNativeAdmissionDatabaseHistoryAndGrantLoss')
RESTORE_TEST = 'TestNativeAdmissionDatabaseSnapshotRestore'
BUILD = '''set -eu
umask 077
cp -a /source/. /work/
go test -p 1 -race -count=1 -json ./...
go vet ./...
go test -race -c -o /exchange/storage.test ./camera/internal/storage
go build -o /exchange/test2json cmd/test2json
chmod 0755 /exchange/storage.test /exchange/test2json
'''


def checked_revision(root):
    revision = checked_project(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_admission_database_revision') == REVISION
            and value.get('credential_admission_database_schema_version') == 9
            and value.get('credential_admission_database_implemented') is True
            and value.get('credential_runtime_admission_guard_implemented') is False,
            'STEP11_B3C3A_PROJECT_REQUIRED')
    return revision


def summarize_log(path):
    result = storage_summary(path)
    actions, failed = {}, False
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        failed = failed or row.get('Action') == 'fail'
        if row.get('Package') == PACKAGE and row.get('Action') in ('pass', 'fail', 'skip'):
            actions[row.get('Test')] = row.get('Action')
    require(not failed and all(actions.get(name) == 'pass' for name in (*TESTS, RESTORE_TEST)),
            'COMPLETE_NATIVE_ADMISSION_DATABASE_TESTS_REQUIRED')
    return {**result, 'required_admission_database_tests_passed': 5,
            'schema_8_to_9_upgrade_verified': True, 'existing_registry_and_budget_preserved': True,
            'actual_role_and_marker_permissions_verified': True,
            'marker_and_history_mismatch_rejected': True,
            'native_database_dump_restore_verified': True,
            'old_snapshot_matches_old_authority_limitation_reproduced': True}


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_revision(root)
    directory = root / 'var/camera/credential-admission-database-checks'
    private_directory(directory)
    project = 'vms-admission-db-test-' + secrets.token_hex(6)
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_ADMISSION_', 'CAMERA_', 'PG'))}
    env['VMS_ADMISSION_DB_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-admission-database-test.yaml')]
    failure, summary, cleaned, completed = None, {}, False, False
    stage, last_completed, failed_stage, exit_code = 'build_and_regression', None, None, None

    def execute(label, args, timeout):
        nonlocal stage, last_completed, exit_code
        stage = label
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output,
                         stderr=subprocess.STDOUT, timeout=timeout)
        exit_code = result.returncode
        require(exit_code == 0, 'ISOLATED_ADMISSION_DATABASE_COMMAND_FAILED')
        last_completed = label

    try:
        execute('build_and_regression', ['run', '--rm', 'admission-build', 'sh', '-ec', BUILD], 900)
        dsn = ('postgres://vms_camera_test:' + env['VMS_ADMISSION_DB_TEST_PASSWORD']
               + '@127.0.0.1:5432/vms_camera_test?sslmode=disable')
        execute('native_dump_restore', ['exec', '-T',
                '-e', 'CAMERA_TEST_DATABASE_URL=' + dsn,
                '-e', 'CAMERA_TEST_ALLOW_SCHEMA_RESET=1',
                '-e', 'CAMERA_TEST_ADMISSION_DUMP_RESTORE=1',
                'admission-db', '/exchange/test2json', '-t', '-p', PACKAGE,
                '/exchange/storage.test', '-test.v=test2json', '-test.count=1',
                '-test.run=^' + RESTORE_TEST + '$', '-test.timeout=120s'], 180)
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
        failure = 'ISOLATED_ADMISSION_DATABASE_CHECK_INTERRUPTED'
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
              'project': project, 'checked_revision': revision, 'admission_database_schema_version': 9,
              'legacy_storage_schema_version': 8, 'go_race_passed': completed,
              'go_vet_passed': completed, **summary, 'production_services_modified': False,
              'production_database_modified': False, 'production_keys_loaded': False,
              'production_admission_state_created': False, 'credential_api_activated': False,
              'production_restore_fence_implemented': False, 'business_runtime_ready': False,
              'runtime_admission_guard_implemented': False, 'isolated_resources_removed': cleaned,
              'log': str(log)}
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
    except (VerificationError, ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE,
                          'code': 'NATIVE_ADMISSION_DATABASE_CHECK_FAILED',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
