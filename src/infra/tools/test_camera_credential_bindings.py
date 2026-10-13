#!/usr/bin/env python3
"""Disposable key receipt and TLS/DB binding check; synthetic fixture only."""
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

SCOPE = 'camera_credential_approved_bindings_native_postgresql'
REVISION = 'step11b3c3b-key-and-endpoint-bindings-20261007'
TESTS = ('TestCredentialEndpointCanonicalHashAndPrivacy',
         'TestCredentialEndpointRejectsUnsupportedProfilesAndDSNs',
         'TestCredentialEndpointActualTLSVerification',
         'TestNativeCredentialEndpointPlaintextAndNoFallback',
         'TestNativeCredentialApprovedBindings')
CRYPTO_PACKAGE = 'vms.local/platform/camera/internal/credentialcrypto'
CRYPTO_TESTS = ('TestProtectedReceiptRequiresActualFileLoad',
                'TestProtectedReceiptBindsExactBytesAndImmutableKeys')
FIXTURE_TEST = 'TestNativeCredentialBindingFixture'
BUILD = 'set -eu\numask 077\nchmod 0755 /exchange\ncp -a /source/. /work/\ngo vet ./...\ngo test -race -c -o /exchange/storage.test ./camera/internal/storage\ngo build -o /exchange/test2json cmd/test2json\nchmod 0755 /exchange/storage.test /exchange/test2json\n'
REGRESSION = 'cp -a /source/. /work/; go test -p 1 -race -count=1 -json ./...'
OWN_TLS_KEY = 'chown postgres:postgres /exchange/fixture/tls/server.key; chmod 0400 /exchange/fixture/tls/server.key'


def checked_revision(root):
    revision = checked_project(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_binding_revision') == REVISION
            and value.get('credential_key_receipt_implemented') is True
            and value.get('credential_endpoint_profile_implemented') is True
            and value.get('credential_admission_database_native_verified') is True
            and value.get('credential_runtime_admission_guard_implemented') is False,
            'STEP11_B3C3B_PROJECT_REQUIRED')
    return revision


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
        package, name, action = row.get('Package'), row.get('Test'), row.get('Action')
        if action in ('pass', 'fail', 'skip'):
            actions[(package, name)] = action
        if package != PACKAGE or name not in (FIXTURE_TEST, TESTS[-1]):
            continue
        if action == 'run':
            require(name not in pending, 'BINDING_TRANSCRIPT_INVALID')
            pending[name] = None
        elif action == 'output' and 'CREDENTIAL_BINDING_PHASE_OK:' in row.get('Output', ''):
            require(name in pending and pending[name] is None, 'BINDING_TRANSCRIPT_INVALID')
            phase = row['Output'].split('CREDENTIAL_BINDING_PHASE_OK:', 1)[1].strip()
            require(phase == ('prepare' if name == FIXTURE_TEST else 'runtime'), 'BINDING_TRANSCRIPT_INVALID')
            pending[name] = phase
        elif action in ('pass', 'skip'):
            require(name in pending, 'BINDING_TRANSCRIPT_INVALID')
            phase = pending.pop(name)
            if phase is not None:
                require(action == 'pass', 'BINDING_PHASE_NOT_PASSED')
                phases.append(phase)
            elif action == 'pass':
                raise VerificationError('BINDING_PHASE_PROOF_REQUIRED')
    require(not pending and phases == ['prepare', 'runtime'], 'COMPLETE_BINDING_PHASES_REQUIRED')
    require(all(actions.get((PACKAGE, name)) == 'pass' for name in TESTS)
            and actions.get((PACKAGE, None)) == 'pass'
            and all(actions.get((CRYPTO_PACKAGE, name)) == 'pass' for name in CRYPTO_TESTS)
            and actions.get((CRYPTO_PACKAGE, None)) == 'pass', 'COMPLETE_BINDING_TESTS_REQUIRED')
    return {**result, 'required_binding_tests_passed': len(TESTS),
            'required_key_receipt_tests_passed': len(CRYPTO_TESTS), 'native_binding_phases_passed': 2,
            'exact_key_bytes_and_loader_origin_verified': True, 'read_only_key_mount_verified': True,
            'separate_runtime_uid_verified': True, 'actual_two_role_tls_bindings_verified': True,
            'wrong_ca_hostname_and_downgrade_rejected': True,
            'marker_key_profile_mismatches_rejected': True, 'inspection_does_not_reserve_budget': True}


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_revision(root)
    directory = root / 'var/camera/credential-binding-checks'
    private_directory(directory)
    project = 'vms-credential-bindings-test-' + secrets.token_hex(6)
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_BINDINGS_', 'VMS_ADMISSION_', 'CAMERA_', 'PG'))}
    env['VMS_BINDINGS_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-bindings-test.yaml')]
    failure, summary, cleaned, completed = None, {}, False, False
    stage, last_completed, failed_stage, exit_code = 'build_tools', None, None, None

    def execute(label, args, timeout):
        nonlocal stage, last_completed, exit_code
        stage = label
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output,
                         stderr=subprocess.STDOUT, timeout=timeout)
        exit_code = result.returncode
        require(exit_code == 0, 'ISOLATED_BINDING_COMMAND_FAILED')
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
                '-test.run=^' + TESTS[-1] + '$', '-test.timeout=120s'], 180)
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
        failure = 'ISOLATED_BINDING_CHECK_INTERRUPTED'
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
              'project': project, 'checked_revision': revision, 'binding_database_schema_version': 9,
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
                          'code': 'NATIVE_BINDING_CHECK_FAILED',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
