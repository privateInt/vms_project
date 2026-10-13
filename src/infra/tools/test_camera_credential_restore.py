#!/usr/bin/env python3
"""Native, disposable DB/key restore rehearsal using synthetic secrets only."""
import base64
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

SCOPE = 'camera_credential_key_supply_restore_native_postgresql'
REVISION = 'step11b3b-key-supply-restore-rehearsal-20261002'
TEST = 'TestNativeCredentialKeySupplyRestoreRehearsal'
PHASES = ('seed', 'advance', 'blocked', 'blocked', 'enrolled', 'enrolled', 'resumed', 'recreated')
OLD_ENC, OLD_MAC = 'enc-1111111111111161', 'idem-2222222222222262'
NEW_ENC, NEW_MAC = 'enc-3333333333333363', 'idem-4444444444444464'
PREPARE = '''set -eu
umask 077
mkdir -p /keys/old /backup-keys/old /exchange
cp /synthetic/old.json /keys/old/key-bundle.json
cp /synthetic/old.json /backup-keys/old/key-bundle.json
chown -R 10001:10001 /keys /backup-keys /exchange
chmod 0700 /keys /backup-keys /exchange
chmod 0500 /keys/old /backup-keys/old
chmod 0400 /keys/old/key-bundle.json /backup-keys/old/key-bundle.json
cp -a /source/. /work/
go test -race -c -o /exchange/storage.test ./camera/internal/storage
go vet ./...
go build -o /exchange/test2json cmd/test2json
chmod 0755 /exchange/storage.test /exchange/test2json
'''
RESTORE_KEYS = '''set -eu
umask 077
mkdir -p /keys/restored /keys/fresh /keys/missing
cp /backup-keys/old/key-bundle.json /keys/restored/key-bundle.json
cp /synthetic/fresh.json /keys/fresh/key-bundle.json
cp /synthetic/missing.json /keys/missing/key-bundle.json
chown -R 10001:10001 /keys
chmod 0500 /keys/restored /keys/fresh /keys/missing
chmod 0400 /keys/restored/key-bundle.json /keys/fresh/key-bundle.json /keys/missing/key-bundle.json
cmp /keys/restored/key-bundle.json /backup-keys/old/key-bundle.json
'''
DUMP = '''set -eu
umask 077
chmod 0700 /rehearsal-backup
pg_dump -U vms_camera_test -d vms_camera_test --format=custom --file=/rehearsal-backup/camera.pgdump
chmod 0600 /rehearsal-backup/camera.pgdump
pg_restore --list /rehearsal-backup/camera.pgdump >/dev/null
'''
FENCE = '''REVOKE CONNECT ON DATABASE vms_camera_test FROM PUBLIC, camera_credential_writer, camera_credential_budget;
ALTER ROLE camera_credential_writer NOLOGIN;
ALTER ROLE camera_credential_budget NOLOGIN;
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE usename IN ('camera_credential_writer','camera_credential_budget') AND pid<>pg_backend_pid();'''
RESTORE = '''set -eu
createdb -U vms_camera_test -T template0 vms_camera_restore
pg_restore -U vms_camera_test -d vms_camera_restore --single-transaction --exit-on-error /rehearsal-backup/camera.pgdump
psql -X -U vms_camera_test -d vms_camera_restore -v ON_ERROR_STOP=1 -c 'UPDATE camera.credential_encryption_budgets SET enabled=false'
'''
RESUME = 'ALTER ROLE camera_credential_writer LOGIN; ALTER ROLE camera_credential_budget LOGIN;'


def synthetic_bundle():
    def key():
        return base64.b64encode(secrets.token_bytes(32)).decode('ascii')
    return {'format_version': 1,
            'encryption': {'active_key_id': OLD_ENC, 'keys': {OLD_ENC: key()}},
            'idempotency': {'active_key_id': OLD_MAC, 'keys': {OLD_MAC: key()}}}


def rotate_synthetic_bundle(old):
    fresh = synthetic_bundle()
    fresh['encryption'] = {'active_key_id': NEW_ENC, 'keys': {
        **old['encryption']['keys'], NEW_ENC: fresh['encryption']['keys'][OLD_ENC]}}
    fresh['idempotency'] = {'active_key_id': NEW_MAC, 'keys': {
        **old['idempotency']['keys'], NEW_MAC: fresh['idempotency']['keys'][OLD_MAC]}}
    missing = {'format_version': 1,
               'encryption': {'active_key_id': NEW_ENC, 'keys': {NEW_ENC: fresh['encryption']['keys'][NEW_ENC]}},
               'idempotency': {'active_key_id': NEW_MAC, 'keys': {NEW_MAC: fresh['idempotency']['keys'][NEW_MAC]}}}
    return fresh, missing


def summarize_log(path):
    pending, seen, failed = None, [], False
    with path.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get('Action') == 'fail':
                failed = True
            if row.get('Package') != PACKAGE or row.get('Test') != TEST:
                continue
            if row.get('Action') == 'run':
                require(pending is None, 'REHEARSAL_TRANSCRIPT_INVALID')
                pending = ''
            elif row.get('Action') == 'output' and 'CREDENTIAL_REHEARSAL_PHASE_OK:' in row.get('Output', ''):
                require(pending == '', 'REHEARSAL_TRANSCRIPT_INVALID')
                pending = row['Output'].split('CREDENTIAL_REHEARSAL_PHASE_OK:', 1)[1].strip()
            elif row.get('Action') == 'pass':
                require(pending in PHASES, 'REHEARSAL_PHASE_PROOF_REQUIRED')
                seen.append(pending)
                pending = None
            elif row.get('Action') == 'skip':
                failed = True
    require(not failed and pending is None and tuple(seen) == PHASES,
            'COMPLETE_NATIVE_REHEARSAL_REQUIRED')
    return {'rehearsal_phases_passed': len(seen), 'read_only_key_mount_verified': True,
            'execution_uid_verified': True, 'separate_role_dsns_verified': True,
            'database_and_key_restore_verified': True, 'snapshot_budget_rewind_reproduced': True,
            'historical_ciphertext_and_replay_verified': True,
            'old_key_writes_rejected': True, 'fresh_key_writes_verified': True,
            'interrupted_restore_retry_verified': True, 'process_recreation_verified': True}


def verify(root, run=subprocess.run):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_project(root)
    manifest = json.loads((root / 'project-manifest.json').read_text())
    require(manifest.get('credential_restore_rehearsal_revision') == REVISION,
            'STEP11_B3B_PROJECT_REQUIRED')
    directory = root / 'var/camera/credential-restore-checks'
    private_directory(directory)
    project = 'vms-credential-restore-test-' + secrets.token_hex(6)
    descriptor, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(descriptor)
    log = Path(name)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('COMPOSE_', 'VMS_REHEARSAL_', 'CAMERA_'))}
    env.update(VMS_REHEARSAL_PASSWORD=secrets.token_hex(24),
               VMS_REHEARSAL_ROLE_PASSWORD=secrets.token_hex(24),
               VMS_REHEARSAL_DATABASE='vms_camera_test')
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.credential-rehearsal.yaml')]
    failure, summary, cleaned, completed = None, {}, False, False
    stage, last_completed_stage, failed_stage, failed_exit_code = 'prepare_input', None, None, None
    with tempfile.TemporaryDirectory(prefix='synthetic-', dir=directory) as temporary:
        env['VMS_REHEARSAL_INPUT'] = temporary
        def execute(label, args, timeout=120):
            nonlocal stage, last_completed_stage, failed_exit_code
            if label != 'cleanup':
                stage = label
            with log.open('ab') as output:
                result = run(command + args, env=env.copy(), stdout=output,
                             stderr=subprocess.STDOUT, timeout=timeout)
            if result.returncode != 0 and label != 'cleanup':
                failed_exit_code = result.returncode
            require(result.returncode == 0, 'ISOLATED_REHEARSAL_COMMAND_FAILED')
            if label != 'cleanup':
                last_completed_stage = label
        def phase(value, label=None):
            execute(label or value, ['run', '--rm', '-e', 'CAMERA_CREDENTIAL_REHEARSAL_PHASE=' + value,
                     'rehearsal-check', '/exchange/test2json', '-t', '-p', PACKAGE,
                     '/exchange/storage.test', '-test.v=test2json', '-test.count=1',
                     '-test.run=^' + TEST + '$', '-test.timeout=60s'])
        def write_input(name, value):
            atomic_write(Path(temporary) / name, (json.dumps(value) + '\n').encode())
        try:
            old = synthetic_bundle()
            write_input('old.json', old)
            execute('prepare_tools', ['run', '--rm', '--no-deps', 'rehearsal-prepare', 'sh', '-ec', PREPARE], 900)
            phase('seed')
            execute('backup_database', ['exec', '-T', 'rehearsal-db', 'sh', '-ec', DUMP])
            phase('advance')
            execute('fence_writers', ['exec', '-T', 'rehearsal-db', 'psql', '-X', '-U', 'vms_camera_test',
                     '-d', 'vms_camera_test', '-v', 'ON_ERROR_STOP=1', '-c', FENCE])
            execute('restore_database', ['exec', '-T', 'rehearsal-db', 'sh', '-ec', RESTORE])
            stage = 'prepare_fresh_input'
            env['VMS_REHEARSAL_DATABASE'] = 'vms_camera_restore'
            fresh, missing = rotate_synthetic_bundle(old)
            write_input('fresh.json', fresh)
            write_input('missing.json', missing)
            execute('restore_keys', ['run', '--rm', '--no-deps', 'rehearsal-prepare', 'sh', '-ec', RESTORE_KEYS])
            phase('blocked', 'blocked_1')
            phase('blocked', 'blocked_2')
            phase('enrolled', 'enrolled_1')
            phase('enrolled', 'enrolled_2')
            execute('resume_roles', ['exec', '-T', 'rehearsal-db', 'psql', '-X', '-U', 'vms_camera_test',
                     '-d', 'vms_camera_restore', '-v', 'ON_ERROR_STOP=1', '-c', RESUME])
            phase('resumed')
            phase('recreated')
            stage = 'verify_transcript'
            summary = summarize_log(log)
            last_completed_stage = stage
            stage = 'verify_source'
            require(checked_project(root) == revision, 'PROJECT_CHANGED_DURING_CHECK')
            last_completed_stage = stage
            completed = True
        except VerificationError as error:
            failure = str(error)
        except (ActivationError, OSError, ValueError, TypeError,
                subprocess.TimeoutExpired, KeyboardInterrupt):
            failure = 'ISOLATED_REHEARSAL_INTERRUPTED_OR_UNAVAILABLE'
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
        if failed_stage is None:
            failed_stage = 'cleanup'
    if failure:
        summary = {}
    report = {'status': 'passed' if failure is None else 'failed', 'scope': SCOPE,
              'project': project, 'storage_schema_version': 8, 'checked_revision': revision,
              'go_race_passed': completed, 'go_vet_passed': completed, **summary,
              'production_services_modified': False, 'production_database_modified': False,
              'production_keys_loaded': False, 'credential_api_activated': False,
              'production_restore_fence_implemented': False, 'business_runtime_ready': False,
              'isolated_resources_removed': cleaned, 'synthetic_input_removed': True,
              'log': str(log)}
    if failure:
        report['code'] = failure
        report['failed_stage'] = failed_stage
        report['last_completed_stage'] = last_completed_stage
        if failed_exit_code is not None:
            report['failed_command_exit_code'] = failed_exit_code
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
                          'code': 'CREDENTIAL_RESTORE_REHEARSAL_UNAVAILABLE',
                          'production_services_modified': False, 'production_database_modified': False,
                          'production_keys_loaded': False, 'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
