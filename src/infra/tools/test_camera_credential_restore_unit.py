import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_credential_restore as tool


def records(phase):
    return [{'Package': tool.PACKAGE, 'Test': tool.TEST, 'Action': 'run'},
            {'Package': tool.PACKAGE, 'Test': tool.TEST, 'Action': 'output',
             'Output': '    rehearsal: CREDENTIAL_REHEARSAL_PHASE_OK:' + phase + '\n'},
            {'Package': tool.PACKAGE, 'Test': tool.TEST, 'Action': 'pass'}]


class CredentialRestoreRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        self.root.mkdir()
        files = {}
        for name in ('src/infra/tools/test_camera_credential_storage.py',
                     'src/infra/tools/test_camera_credential_restore.py',
                     'src/infra/postgresql/compose.credential-rehearsal.yaml',
                     'src/platform/camera/internal/storage/credential_restore_rehearsal_test.go'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic reviewed fixture\n')
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        (self.root / 'project-manifest.json').write_text(json.dumps({
            'storage_revision': 'step11b2-credential-storage-20261002',
            'storage_schema_version': 8, 'credential_storage_implemented': True,
            'credential_api_implemented': False, 'credential_restore_rehearsal_revision': tool.REVISION,
            'files': files}))
        (self.root / '.env').write_bytes(b'SYNTHETIC_ENV_ONLY\n')
        private = self.root / 'var/camera/credential-keys'
        private.mkdir(parents=True)
        (private / 'key-bundle.json').write_bytes(b'SYNTHETIC_PROTECTED_SENTINEL_ONLY\n')
        self.log = self.root / 'synthetic.log'

    def transcript(self, phases=tool.PHASES):
        return [row for phase in phases for row in records(phase)]

    def summary(self, rows):
        self.log.write_text('\n'.join(json.dumps(row) for row in rows))
        return tool.summarize_log(self.log)

    def test_complete_ordered_native_evidence(self):
        self.assertEqual(self.summary(self.transcript())['rehearsal_phases_passed'], 8)

    def test_missing_reordered_or_duplicate_phases_rejected(self):
        for phases in (tool.PHASES[1:], tuple(reversed(tool.PHASES)), tool.PHASES + ('resumed',)):
            with self.subTest(phases=phases), self.assertRaises(tool.VerificationError):
                self.summary(self.transcript(phases))

    def test_skip_or_failure_cannot_be_hidden_by_pass(self):
        for action in ('fail', 'skip'):
            rows = [{'Package': tool.PACKAGE, 'Test': tool.TEST, 'Action': action}] + self.transcript()
            with self.subTest(action=action), self.assertRaises(tool.VerificationError):
                self.summary(rows)

    def test_phase_marker_alone_or_wrong_package_rejected(self):
        rows = self.transcript()
        for row in rows:
            if row['Action'] == 'pass':
                row['Package'] = 'other/package'
        with self.assertRaises(tool.VerificationError):
            self.summary(rows)

    def test_pass_without_phase_marker_rejected(self):
        with self.assertRaises(tool.VerificationError):
            self.summary([row for row in self.transcript() if row['Action'] != 'output'])

    def test_duplicate_marker_or_unfinished_phase_rejected(self):
        for rows in (self.transcript()[:-1], [records('seed')[0], records('seed')[1], records('seed')[1]]):
            with self.assertRaises(tool.VerificationError):
                self.summary(rows)

    def test_synthetic_rotation_retains_independent_key_history(self):
        old = tool.synthetic_bundle()
        fresh, missing = tool.rotate_synthetic_bundle(old)
        values = [*fresh['encryption']['keys'].values(), *fresh['idempotency']['keys'].values()]
        self.assertEqual(len(set(values)), 4)
        self.assertTrue(all(len(base64.b64decode(v, validate=True)) == 32 for v in values))
        self.assertEqual(fresh['encryption']['keys'][tool.OLD_ENC], old['encryption']['keys'][tool.OLD_ENC])
        self.assertEqual(fresh['idempotency']['keys'][tool.OLD_MAC], old['idempotency']['keys'][tool.OLD_MAC])
        self.assertEqual(set(missing['encryption']['keys']), {tool.NEW_ENC})
        self.assertEqual(set(missing['idempotency']['keys']), {tool.NEW_MAC})
        self.assertNotEqual(tool.synthetic_bundle(), old)

    def test_preparation_builds_json_tool_when_precompiled_tool_is_absent(self):
        # Execute the preparation shell with an empty tool directory, like the
        # observed local toolchain. Only Go compilation and chown are mocked;
        # file copying/modes and shell failure propagation remain real.
        def prepare(script):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for name in ('keys', 'backup-keys', 'exchange', 'synthetic', 'source', 'work', 'bin', 'tool-dir'):
                    (root / name).mkdir()
                (root / 'synthetic/old.json').write_text('{}\n')
                (root / 'source/go.mod').write_text('module synthetic\n')
                go = root / 'bin/go'
                go.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
if args == ['env', 'GOTOOLDIR']:
    print(os.environ['TEST_PREPARE_TOOL_DIR'])
elif args and args[0] in ('test', 'build'):
    output = pathlib.Path(args[args.index('-o') + 1])
    output.write_text('synthetic compiled tool\\n')
elif args != ['vet', './...']:
    sys.exit(2)
''')
                go.chmod(0o755)
                chown = root / 'bin/chown'
                chown.write_text('#!/bin/sh\nexit 0\n')
                chown.chmod(0o755)
                for name in ('backup-keys', 'synthetic', 'exchange', 'source', 'keys', 'work'):
                    script = script.replace('/' + name, shlex.quote(str(root / name)))
                env = os.environ.copy()
                env['PATH'] = str(root / 'bin') + os.pathsep + env['PATH']
                env['TEST_PREPARE_TOOL_DIR'] = str(root / 'tool-dir')
                result = subprocess.run(['sh', '-ec', script], env=env, capture_output=True, text=True)
                outputs = []
                for name in ('storage.test', 'test2json'):
                    path = root / 'exchange' / name
                    outputs.append(stat.S_IMODE(path.stat().st_mode) if path.exists() else None)
                return result, outputs
        previous = tool.PREPARE.replace('go build -o /exchange/test2json cmd/test2json',
                                        'cp "$(go env GOTOOLDIR)/test2json" /exchange/test2json')
        old, _ = prepare(previous)
        self.assertNotEqual(old.returncode, 0)
        self.assertIn('test2json', old.stderr)
        current, outputs = prepare(tool.PREPARE)
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(outputs, [0o755, 0o755])

    def mocked_run(self, *, fail_at=None, exception=None, cleanup=0, drift=False, omitted=None):
        calls, passwords, inputs = [], [], []
        def run(command, **kwargs):
            index = len(calls)
            calls.append(command)
            env = kwargs['env']
            self.assertNotIn('COMPOSE_PROJECT_NAME', env)
            self.assertNotIn('CAMERA_TEST_DATABASE_URL', env)
            self.assertNotIn('VMS_REHEARSAL_ATTACK', env)
            self.assertEqual(command[0:3], ['docker', 'compose', '--project-name'])
            self.assertTrue(command[3].startswith('vms-credential-restore-test-'))
            self.assertNotEqual(command[3], 'vms-project')
            self.assertIn('/dev/null', command)
            directory = Path(env['VMS_REHEARSAL_INPUT'])
            inputs.append(directory)
            for p in directory.iterdir():
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            passwords.extend((env['VMS_REHEARSAL_PASSWORD'], env['VMS_REHEARSAL_ROLE_PASSWORD']))
            if 'down' in command:
                return subprocess.CompletedProcess(command, cleanup)
            if fail_at == index:
                if exception:
                    raise exception
                return subprocess.CompletedProcess(command, 1)
            phases = [arg.split('=', 1)[1] for arg in command if arg.startswith('CAMERA_CREDENTIAL_REHEARSAL_PHASE=')]
            if phases:
                phase = phases[0]
                if phase != omitted:
                    kwargs['stdout'].write(('\n'.join(json.dumps(row) for row in records(phase)) + '\n').encode())
                self.assertEqual(env['VMS_REHEARSAL_DATABASE'], 'vms_camera_test' if phase in ('seed', 'advance') else 'vms_camera_restore')
            if tool.RESTORE_KEYS in command:
                old = json.loads((directory / 'old.json').read_text())
                fresh = json.loads((directory / 'fresh.json').read_text())
                self.assertEqual(old['encryption']['keys'][tool.OLD_ENC], fresh['encryption']['keys'][tool.OLD_ENC])
            if drift and phases == ['recreated']:
                (self.root / 'src/platform/camera/internal/storage/credential_restore_rehearsal_test.go').write_bytes(b'concurrent edit\n')
            return subprocess.CompletedProcess(command, 0)
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                patch.dict(tool.os.environ, {'COMPOSE_PROJECT_NAME': 'vms-project',
                                             'CAMERA_TEST_DATABASE_URL': 'SYNTHETIC_PRODUCTION_DSN',
                                             'VMS_REHEARSAL_ATTACK': 'SYNTHETIC_ATTACK'}):
            result = tool.verify(self.root, run=run)
        self.assertEqual((self.root / '.env').read_bytes(), b'SYNTHETIC_ENV_ONLY\n')
        self.assertEqual((self.root / 'var/camera/credential-keys/key-bundle.json').read_bytes(), b'SYNTHETIC_PROTECTED_SENTINEL_ONLY\n')
        self.assertTrue(all(not p.exists() for p in inputs))
        self.assertEqual(stat.S_IMODE(Path(result['report']).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(result['log']).stat().st_mode), 0o600)
        self.assertTrue(all(value not in json.dumps(result) for value in passwords))
        self.assertFalse(result['production_keys_loaded'])
        self.assertFalse(result['production_database_modified'])
        self.assertFalse(result['production_restore_fence_implemented'])
        return result, calls

    def test_mocked_full_rehearsal_fence_before_restore_and_resume_last(self):
        result, calls = self.mocked_run()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(calls), 15)
        all_arguments = [x for c in calls for x in c]
        self.assertLess(all_arguments.index(tool.FENCE), all_arguments.index(tool.RESTORE))
        self.assertLess(all_arguments.index(tool.RESTORE), all_arguments.index(tool.RESTORE_KEYS))
        self.assertLess(all_arguments.index('CAMERA_CREDENTIAL_REHEARSAL_PHASE=enrolled'), all_arguments.index(tool.RESUME))
        self.assertLess(all_arguments.index(tool.RESUME), all_arguments.index('CAMERA_CREDENTIAL_REHEARSAL_PHASE=resumed'))
        self.assertEqual(calls[-1][-5:], ['down', '--volumes', '--remove-orphans', '--timeout', '5'])

    def test_every_stage_failure_stops_further_admission_and_cleans(self):
        stages = ('prepare_tools', 'seed', 'backup_database', 'advance', 'fence_writers',
                  'restore_database', 'restore_keys', 'blocked_1', 'blocked_2',
                  'enrolled_1', 'enrolled_2', 'resume_roles', 'resumed', 'recreated')
        for index in range(14):
            with self.subTest(index=index):
                result, calls = self.mocked_run(fail_at=index)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(len(calls), index + 2)
                self.assertTrue(result['isolated_resources_removed'])
                self.assertNotIn('rehearsal_phases_passed', result)
                self.assertEqual(result['failed_stage'], stages[index])
                self.assertEqual(result['last_completed_stage'], stages[index - 1] if index else None)
                self.assertEqual(result['failed_command_exit_code'], 1)

    def test_timeout_or_interrupt_still_cleans(self):
        for error in (subprocess.TimeoutExpired('synthetic', 120), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                result, _ = self.mocked_run(fail_at=5, exception=error)
                self.assertEqual(result['status'], 'failed')
                self.assertTrue(result['isolated_resources_removed'])
                self.assertEqual(result['failed_stage'], 'restore_database')
                self.assertNotIn('failed_command_exit_code', result)

    def test_cleanup_failure_rejects_pass(self):
        result, _ = self.mocked_run(cleanup=1)
        self.assertEqual(result['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertFalse(result['isolated_resources_removed'])
        self.assertNotIn('rehearsal_phases_passed', result)
        self.assertEqual(result['failed_stage'], 'cleanup')
        self.assertEqual(result['last_completed_stage'], 'verify_source')
        interrupted, _ = self.mocked_run(fail_at=5, cleanup=1)
        self.assertEqual(interrupted['code'], 'ISOLATED_CLEANUP_INCOMPLETE')
        self.assertEqual(interrupted['failed_stage'], 'restore_database')
        self.assertEqual(interrupted['last_completed_stage'], 'fence_writers')
        self.assertEqual(interrupted['failed_command_exit_code'], 1)

    def test_missing_proof_rejects_successful_command_status(self):
        result, _ = self.mocked_run(omitted='resumed')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_stage'], 'verify_transcript')

    def test_source_drift_rejects_receipt(self):
        result, _ = self.mocked_run(drift=True)
        self.assertEqual(result['code'], 'PROJECT_FILE_CHANGED')
        self.assertEqual(result['failed_stage'], 'verify_source')

    def test_source_integrity_checked_before_docker(self):
        (self.root / 'src/platform/camera/internal/storage/credential_restore_rehearsal_test.go').write_bytes(b'user edit\n')
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                self.assertRaisesRegex(tool.VerificationError, 'PROJECT_FILE_CHANGED'):
            tool.verify(self.root, run=lambda *args, **kwargs: self.fail('executed before integrity check'))

    def test_wrong_stage_rejected_before_docker(self):
        manifest = self.root / 'project-manifest.json'
        m = json.loads(manifest.read_text())
        m.pop('credential_restore_rehearsal_revision')
        manifest.write_text(json.dumps(m))
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
                self.assertRaisesRegex(tool.VerificationError, 'STEP11_B3B_PROJECT_REQUIRED'):
            tool.verify(self.root, run=lambda *args, **kwargs: self.fail('executed wrong stage'))

    def test_cli_error_hides_exception_data(self):
        with patch.object(tool, 'verify', side_effect=OSError('SYNTHETIC_PRIVATE_DIAGNOSTIC')), \
                patch('sys.stderr') as output:
            self.assertEqual(tool.main(), 1)
            text = ''.join(c.args[0] for c in output.write.call_args_list)
            self.assertNotIn('PRIVATE_DIAGNOSTIC', text)
            self.assertIn('CREDENTIAL_RESTORE_REHEARSAL_UNAVAILABLE', text)


if __name__ == '__main__':
    unittest.main()
