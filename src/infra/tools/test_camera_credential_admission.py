#!/usr/bin/env python3
"""Disposable native Linux admission check; synthetic metadata, no DB or keys."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

from camera_activation import ActivationError, atomic_write, private_directory
from test_camera_credential_storage import VerificationError, checked_project, require

SCOPE = 'camera_credential_admission_native_linux'
REVISION = 'step11b3c2-external-state-and-leases-20261002'
PACKAGE = 'vms.local/platform/camera/internal/credentialadmission'
NATIVE_TEST = 'TestNativeReadOnlyMount'
REQUIRED = frozenset((
    'TestParseContractExamples', 'TestStrictRawParser', 'TestSemanticRecordValidation',
    'TestMonotonicTransitionsAndRetry', 'TestCASRejectsHistoryGenerationAndOperationEdits',
    'TestNoPrivateValuesInErrors', 'TestBootstrapCreateOnlyAndDurableModes',
    'TestBootstrapRejectsHistoryAndExistingArtifacts', 'TestMaintenanceCASAndIdempotency',
    'TestIndependentSharedDescriptorsAndDeadlines', 'TestReadIntentRejectsFencedPreparedAndStaleExpected',
    'TestPermissionsTypesLinksOwnersAndBounds', 'TestStableLockReceiptRejectsReplacementBeforeOrDuringLease',
    'TestDirectoryAndComponentReplacement', 'TestAtomicCommitFailureAndReacquisition',
    'TestConcurrentCASHasOneWinner', 'TestMultipleProcessesDrainAndKilledWriterKeepsFence',
))
PREPARE = '''set -eu
umask 077
mkdir -p /work /exchange /authority/control
chown 0:10001 /authority/control
chmod 0750 /authority/control
chmod 0755 /exchange
cp -a /source/. /work/
go test -race -c -o /exchange/admission.test ./camera/internal/credentialadmission
go vet ./...
go build -o /exchange/test2json cmd/test2json
chmod 0755 /exchange/admission.test /exchange/test2json
cd /work/camera/internal/credentialadmission
/exchange/test2json -t -p vms.local/platform/camera/internal/credentialadmission /exchange/admission.test -test.v=test2json -test.count=1 -test.timeout=90s
VMS_ADMISSION_NATIVE_PHASE=prepare /exchange/test2json -t -p vms.local/platform/camera/internal/credentialadmission /exchange/admission.test -test.v=test2json -test.count=1 -test.run=^TestNativeReadOnlyMount$ -test.timeout=30s
'''


def summarize_log(path):
    running, passed, phases = set(), set(), []
    phase = None
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        require(row.get('Action') not in ('fail', 'skip'), 'ADMISSION_TEST_FAILED_OR_SKIPPED')
        if row.get('Package') != PACKAGE or not isinstance(row.get('Test'), str):
            continue
        name, action = row['Test'], row.get('Action')
        if action == 'run':
            require(name not in running, 'ADMISSION_TRANSCRIPT_INVALID')
            running.add(name)
        elif action == 'output' and 'ADMISSION_NATIVE_PHASE_OK:' in row.get('Output', ''):
            require(name == NATIVE_TEST and name in running and phase is None,
                    'ADMISSION_TRANSCRIPT_INVALID')
            phase = row['Output'].strip().split('ADMISSION_NATIVE_PHASE_OK:', 1)[1]
            require(phase in ('prepare', 'read'), 'ADMISSION_TRANSCRIPT_INVALID')
        elif action == 'pass':
            require(name in running, 'ADMISSION_TRANSCRIPT_INVALID')
            running.remove(name)
            if name == NATIVE_TEST and phase is not None:
                phases.append(phase)
                phase = None
            elif '/' not in name:
                passed.add(name)
    require(not running and phase is None and REQUIRED <= passed and phases == ['prepare', 'read'],
            'COMPLETE_ADMISSION_CHECK_REQUIRED')
    return {'required_admission_tests_passed': len(REQUIRED), 'native_phases_passed': 2,
            'read_only_control_mount_verified': True, 'separate_maintenance_runtime_uid_verified': True,
            'public_reader_verified': True, 'runtime_metadata_writes_rejected': True,
            'stable_lock_and_process_drain_verified': True, 'uncertain_commit_retry_verified': True}


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_project(root)
    manifest = json.loads((root / 'project-manifest.json').read_text())
    require(manifest.get('credential_admission_foundation_revision') == REVISION,
            'STEP11_B3C2_PROJECT_REQUIRED')
    directory = root / 'var/camera/credential-admission-checks'
    private_directory(directory)
    project = 'vms-credential-admission-test-' + secrets.token_hex(6)
    descriptor, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(descriptor)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_ADMISSION_', 'CAMERA_'))}
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/compose.credential-admission-test.yaml')]
    failure, summary, cleaned = None, {}, False
    stage, last, failed_stage, failed_exit = 'prepare_tools_and_fixture', None, None, None

    def execute(label, args, timeout):
        nonlocal stage, last, failed_exit
        if label != 'cleanup':
            stage = label
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output,
                         stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode != 0 and label != 'cleanup':
            failed_exit = result.returncode
        require(result.returncode == 0, 'ISOLATED_ADMISSION_COMMAND_FAILED')
        if label != 'cleanup':
            last = label

    try:
        execute('prepare_tools_and_fixture', ['run', '--rm', '--no-deps', 'admission-prepare',
                'sh', '-ec', PREPARE], 900)
        execute('read_only_runtime', ['run', '--rm', '--no-deps', 'admission-runtime',
                '/exchange/test2json', '-t', '-p', PACKAGE, '/exchange/admission.test',
                '-test.v=test2json', '-test.count=1', '-test.run=^' + NATIVE_TEST + '$',
                '-test.timeout=30s'], 90)
        stage = 'verify_transcript'
        summary = summarize_log(log)
        last = stage
        stage = 'verify_source'
        require(checked_project(root) == revision, 'PROJECT_CHANGED_DURING_CHECK')
        last = stage
    except VerificationError as error:
        failure = str(error)
    except (ActivationError, OSError, ValueError, TypeError, subprocess.TimeoutExpired, KeyboardInterrupt):
        failure = 'ISOLATED_ADMISSION_INTERRUPTED_OR_UNAVAILABLE'
    finally:
        if failure:
            failed_stage = stage
        try:
            execute('cleanup', ['down', '--volumes', '--remove-orphans', '--timeout', '5'], 60)
            cleaned = True
        except (VerificationError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
            cleaned = False
    if not cleaned:
        failure = 'ISOLATED_CLEANUP_INCOMPLETE'
        failed_stage = failed_stage or 'cleanup'
    if failure:
        summary = {}
    report = {'status': 'failed' if failure else 'passed', 'scope': SCOPE, 'project': project,
              'checked_revision': revision, 'go_race_passed': failure is None,
              'go_vet_passed': failure is None, **summary,
              'production_services_modified': False, 'production_database_modified': False,
              'production_keys_loaded': False, 'production_admission_state_created': False,
              'credential_api_activated': False, 'production_restore_fence_implemented': False,
              'business_runtime_ready': False, 'isolated_resources_removed': cleaned, 'log': str(log)}
    if failure:
        report.update(code=failure, failed_stage=failed_stage, last_completed_stage=last)
        if failed_exit is not None:
            report['failed_command_exit_code'] = failed_exit
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
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': 'ADMISSION_CHECK_UNAVAILABLE',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'production_admission_state_created': False,
                          'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
