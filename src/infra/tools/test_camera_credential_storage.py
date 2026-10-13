#!/usr/bin/env python3
"""Verify credential storage in one disposable native Docker project; no production keys/DB IO."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import subprocess
import sys
import tempfile

from camera_activation import ActivationError, atomic_write, private_directory, safe

PACKAGE = 'vms.local/platform/camera/internal/storage'
EXPECTED_TESTS = (
    'TestCredentialTargetAndPrivateStoreConfiguration',
    'TestCredentialVersionPersistenceAndSafeReplay',
    'TestCredentialImmutableVersionsAndExactTarget',
    'TestCredentialAuthorizationAppliesToReplayAndReference',
    'TestCredentialRevokeGuardAndParentProtection',
    'TestCredentialMutationFailureKeepsCommittedBudget',
    'TestCredentialBudgetBoundsAndDisabledKey',
    'TestCredentialRestartAndHistoricalFingerprintKeys',
    'TestCredentialPermissionRecheckedAfterReservation',
    'TestNativeCredentialLeastPrivilegeAndGrantLoss',
    'TestNativeCredentialConcurrentBudgetAndReceipts',
    'TestNativeCredentialParentDeletionWinsBeforeMutation',
    'TestNativeCredentialMutationBlocksParentDeletion',
)
SCOPE = 'camera_credential_storage_native_postgresql'
GO_COMMAND = 'cp -a /source/. /work/; go test -p 1 -race -count=1 -json ./...; go vet ./...'


class VerificationError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise VerificationError(code)


def checked_project(root):
    safe(root)
    path = root / 'project-manifest.json'
    safe(path)
    value = json.loads(path.read_text())
    require(value.get('storage_revision') == 'step11b2-credential-storage-20261002'
            and value.get('storage_schema_version') == 8
            and value.get('credential_storage_implemented') is True
            and value.get('credential_api_implemented') is False,
            'STEP11_B2_PROJECT_REQUIRED')
    files = value.get('files')
    require(isinstance(files, dict) and 'src/infra/tools/test_camera_credential_storage.py' in files, 'PROJECT_MANIFEST_INVALID')
    for relative, expected in files.items():
        name = PurePosixPath(relative)
        require(name.parts and not name.is_absolute() and '..' not in name.parts
                and str(name) == relative and '\\' not in relative
                and name.parts[0] not in ('.env', 'var', 'build', '.git'), 'PROJECT_MANIFEST_INVALID')
        item = root / relative
        safe(item)
        require(item.is_file() and hashlib.sha256(item.read_bytes()).hexdigest() == expected,
                'PROJECT_FILE_CHANGED')
    for item in (root / 'src/platform').rglob('*'):
        if item.suffix in ('.go', '.sql'):
            safe(item)
            require(item.is_file() and item.relative_to(root).as_posix() in files,
                    'UNREVIEWED_PLATFORM_CODE_PRESENT')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_log(path):
    tests, package_results = {}, {}
    failed = False
    with path.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get('Action') not in ('pass', 'fail', 'skip'):
                continue
            failed = failed or row['Action'] == 'fail'
            key = (row.get('Package'), row.get('Test'))
            if row.get('Test'):
                tests[key] = row['Action']
            else:
                package_results[row.get('Package')] = row['Action']
    require(not failed, 'GO_TEST_FAILED')
    require(package_results.get(PACKAGE) == 'pass'
            and all(tests.get((PACKAGE, name)) == 'pass' for name in EXPECTED_TESTS),
            'NATIVE_CREDENTIAL_TESTS_REQUIRED')
    return {'top_level_tests_passed': sum(result == 'pass' and '/' not in test
                                         for (_, test), result in tests.items()),
            'subtests_passed': sum(result == 'pass' and '/' in test
                                  for (_, test), result in tests.items()),
            'required_credential_tests_passed': len(EXPECTED_TESTS),
            'native_roles_and_concurrency_verified': True}


def verify(root, run=subprocess.run, *, summarize=summarize_log, scope=SCOPE):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_project(root)
    directory = root / 'var/camera/credential-storage-checks'
    private_directory(directory)
    project = 'vms-credential-storage-test-' + secrets.token_hex(6)
    descriptor, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(descriptor)
    log = Path(name)
    env = {key: value for key, value in os.environ.items() if not key.startswith('COMPOSE_')}
    env['VMS_CAMERA_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.test.yaml')]
    completed = cleaned = False
    summary = {}
    failure = None
    try:
        with log.open('wb') as output:
            result = run(command + ['run', '--rm', 'camera-storage-test', 'sh', '-ec', GO_COMMAND],
                         env=env, stdout=output, stderr=subprocess.STDOUT, timeout=900)
            completed = result.returncode == 0
        if completed:
            summary = summarize(log)
            require(checked_project(root) == revision, 'PROJECT_CHANGED_DURING_CHECK')
        else:
            failure = 'NATIVE_TEST_OR_VET_FAILED'
    except VerificationError as error:
        failure = str(error)
    except (ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        failure = 'NATIVE_CHECK_INTERRUPTED_OR_UNAVAILABLE'
    finally:
        try:
            with log.open('ab') as output:
                result = run(command + ['down', '--volumes', '--remove-orphans', '--timeout', '5'],
                             env=env, stdout=output, stderr=subprocess.STDOUT, timeout=60)
                cleaned = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
            cleaned = False
    if not cleaned:
        failure = 'ISOLATED_CLEANUP_INCOMPLETE'
    if failure:
        summary = {}
    report = {'status': 'passed' if failure is None else 'failed', 'scope': scope, 'project': project,
              'storage_schema_version': 8, 'checked_revision': revision,
              'go_race_passed': completed and bool(summary), 'go_vet_passed': completed, **summary,
              'production_services_modified': False, 'production_database_modified': False,
              'production_keys_loaded': False, 'credential_api_activated': False,
              'business_runtime_ready': False, 'isolated_resources_removed': cleaned,
              'log': str(log)}
    if failure:
        report['code'] = failure
    path = directory / (project + '.json')
    report['report'] = str(path)
    atomic_write(path, (json.dumps(report, indent=2) + '\n').encode())
    return report


def main():
    root = Path(__file__).resolve().parents[3]
    try:
        result = verify(root)
        print(json.dumps(result))
        return 0 if result['status'] == 'passed' else 1
    except (VerificationError, ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE,
                          'code': 'NATIVE_CREDENTIAL_STORAGE_CHECK_FAILED',
                          'production_services_modified': False,
                          'production_database_modified': False,
                          'production_keys_loaded': False,
                          'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
