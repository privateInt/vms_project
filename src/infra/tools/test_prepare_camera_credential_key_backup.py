"""Private synthetic key fixtures; no Docker, DB or production key access."""
import base64
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import prepare_camera_credential_key_backup as tool


class CredentialKeyBackupTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vms-key-backup-unit-')
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)
        self.root = self.parent / 'project'
        self.root.mkdir(mode=0o700)
        (self.root / '.env').write_bytes(b'SYNTHETIC_ENV_ONLY\n')
        (self.root / '.env').chmod(0o600)
        tool.keys.prepare(self.root, True)
        self.source = self.root.joinpath(*tool.keys.KEY_DIRECTORY)
        self.key = self.source / tool.keys.KEY_FILE
        self.body = self.key.read_bytes()
        self.directory = self.source.parent / tool.BACKUP_DIRECTORY
        self.target = self.directory / ('bundle-' + hashlib.sha256(self.body).hexdigest())

    def assert_preserved(self):
        self.assertEqual(self.key.read_bytes(), self.body)
        self.assertEqual(stat.S_IMODE(self.key.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o700)
        self.assertEqual((self.root / '.env').read_bytes(), b'SYNTHETIC_ENV_ONLY\n')

    def test_without_apply_creates_no_backup(self):
        result = tool.backup(self.root)
        self.assertEqual(result['status'], 'not_backed_up')
        self.assertFalse(result['backup_ready'])
        self.assertFalse(self.directory.exists())
        self.assert_preserved()

    def test_exact_backup_repeat_and_inspect_are_private_and_preserve_source(self):
        first = tool.backup(self.root, True)
        saved = {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
                 for p in self.target.iterdir()}
        self.assertEqual(first['status'], 'backed_up')
        self.assertEqual(tool.backup(self.root, True)['status'], 'already_backed_up')
        self.assertEqual(tool.backup(self.root)['status'], 'validated')
        self.assertEqual(saved, {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
                                 for p in self.target.iterdir()})
        self.assertEqual((self.target / tool.keys.KEY_FILE).read_bytes(), self.body)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        self.assertTrue(all(info[1] == 0o600 for info in saved.values()))
        for field in ('keys_activated_in_api', 'service_restart_performed', 'database_schema_modified',
                      'environment_modified', 'database_backup_included', 'restore_ready', 'restore_fence_implemented'):
            self.assertFalse(first[field], field)
        self.assertTrue(first['backup_matches_source'])
        self.assert_preserved()

    def test_public_report_and_backup_manifest_contain_no_raw_key_material(self):
        result = tool.backup(self.root, True)
        safe = json.dumps(result) + (self.target / tool.MANIFEST).read_text()
        value = json.loads(self.body)
        for purpose in ('encryption', 'idempotency'):
            for encoded in value[purpose]['keys'].values():
                self.assertNotIn(encoded, safe)
        self.assert_preserved()

    def test_history_is_retained_and_new_bundle_gets_a_separate_backup(self):
        tool.backup(self.root, True)
        value = json.loads(self.body)
        for purpose, prefix, byte in (('encryption', 'enc-', 7), ('idempotency', 'idem-', 8)):
            identity = prefix + 'ffffffffffffffff'
            value[purpose]['keys'][identity] = base64.b64encode(bytes([byte])*32).decode()
            value[purpose]['active_key_id'] = identity
        self.key.write_text(json.dumps(value))
        changed = self.key.read_bytes()
        result = tool.backup(self.root, True)
        self.assertEqual(result['encryption_key_count'], 2)
        self.assertEqual(result['idempotency_key_count'], 2)
        self.assertEqual((Path(result['backup_directory']) / tool.keys.KEY_FILE).read_bytes(), changed)
        self.assertEqual((self.target / tool.keys.KEY_FILE).read_bytes(), self.body)
        self.assertEqual(self.key.read_bytes(), changed)

    def test_source_exclusive_preparation_lock_blocks_backup(self):
        with (self.source / tool.keys.LOCK_FILE).open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'PREPARATION_LOCKED'):
                tool.backup(self.root, True)
        self.assertFalse(self.directory.exists())
        self.assert_preserved()

    def test_backup_exclusive_lock_blocks_second_operation(self):
        tool.backup(self.root, True)
        with (self.directory / tool.BACKUP_LOCK).open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'BACKUP_LOCKED'):
                tool.backup(self.root, True)
        self.assert_preserved()

    def test_source_permissions_are_rejected_without_repair(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'PERMISSIONS'):
            tool.backup(self.root, True)
        self.assertEqual(self.key.read_bytes(), self.body)
        self.assertEqual(stat.S_IMODE(self.key.stat().st_mode), 0o644)
        self.assertFalse(self.directory.exists())

    def test_source_foreign_owner_or_unknown_content_is_rejected(self):
        with patch.object(tool.keys.os, 'getuid', return_value=os.getuid()+1):
            with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'OWNER'):
                tool.backup(self.root, True)
        (self.source / 'unexpected').write_bytes(b'SYNTHETIC_ONLY')
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'CONTENTS'):
            tool.backup(self.root, True)
        self.assertFalse(self.directory.exists())
        self.assert_preserved()

    def test_source_invalid_bundle_does_not_generate_or_copy_keys(self):
        self.key.write_bytes(b'SYNTHETIC_PRIVATE_INVALID')
        with self.assertRaises(tool.keys.KeyPreparationError):
            tool.backup(self.root, True)
        self.assertEqual(self.key.read_bytes(), b'SYNTHETIC_PRIVATE_INVALID')
        self.assertFalse(self.directory.exists())

    def test_source_symlink_hardlink_and_fifo_are_rejected(self):
        for kind in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                self.key.unlink(missing_ok=True)
                external = self.parent / kind
                external.write_bytes(self.body)
                external.chmod(0o600)
                if kind == 'symlink': self.key.symlink_to(external)
                elif kind == 'hardlink': os.link(external, self.key)
                else: os.mkfifo(self.key, 0o600)
                with self.assertRaises((OSError, tool.keys.KeyPreparationError)):
                    tool.backup(self.root, True)
                self.assertEqual(external.read_bytes(), self.body)
                self.assertFalse(self.directory.exists())

    def test_backup_base_symlink_or_wrong_permissions_are_rejected(self):
        external = self.parent / 'external'; external.mkdir(mode=0o700)
        self.directory.symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError): tool.backup(self.root, True)
        self.assertEqual(list(external.iterdir()), [])
        self.directory.unlink(); self.directory.mkdir(mode=0o755)
        # mkdir applies the caller's umask; establish this negative fixture's
        # exact mode without changing the process umask or production paths.
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'PERMISSIONS'):
            tool.backup(self.root, True)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o755)
        self.assert_preserved()

    def test_backup_lock_symlink_and_hardlink_are_rejected(self):
        tool.backup(self.root, True)
        lock = self.directory / tool.BACKUP_LOCK
        external = self.parent / 'external-lock'; external.write_bytes(b''); external.chmod(0o600)
        for kind in ('symlink', 'hardlink'):
            lock.unlink()
            if kind == 'symlink': lock.symlink_to(external)
            else: os.link(external, lock)
            with self.assertRaises((OSError, tool.keys.KeyPreparationError)):
                tool.backup(self.root, True)
        self.assert_preserved()

    def test_backup_malformed_partial_or_unknown_files_are_never_repaired(self):
        tool.backup(self.root, True)
        receipt = self.target / tool.MANIFEST
        original = receipt.read_bytes()
        receipt.write_bytes(b'SYNTHETIC_TAMPERED_MANIFEST')
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'MISMATCH'): tool.backup(self.root, True)
        self.assertEqual(receipt.read_bytes(), b'SYNTHETIC_TAMPERED_MANIFEST')
        receipt.unlink()
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'INCOMPLETE'): tool.backup(self.root, True)
        self.assertFalse(receipt.exists())
        receipt.write_bytes(original); receipt.chmod(0o600)
        (self.target / 'unknown').write_bytes(b'SYNTHETIC_ONLY')
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'INCOMPLETE'): tool.backup(self.root)
        self.assert_preserved()

    def test_backup_key_mismatch_permissions_and_redirect_are_rejected(self):
        tool.backup(self.root, True)
        saved = self.target / tool.keys.KEY_FILE
        saved.write_bytes(b'SYNTHETIC_TAMPERED_KEY')
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'MISMATCH'): tool.backup(self.root, True)
        saved.write_bytes(self.body); saved.chmod(0o644)
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'PERMISSIONS'): tool.backup(self.root, True)
        saved.unlink(); saved.symlink_to(self.key)
        with self.assertRaises(OSError): tool.backup(self.root, True)
        self.assert_preserved()

    def test_write_failure_leaves_rejected_partial_backup_and_source_intact(self):
        original = tool.write_new_file
        def interrupted(directory, name, body):
            if name == tool.MANIFEST: raise OSError('SYNTHETIC_PRIVATE_FAILURE')
            return original(directory, name, body)
        with patch.object(tool, 'write_new_file', side_effect=interrupted), self.assertRaises(OSError):
            tool.backup(self.root, True)
        self.assertEqual((self.target / tool.keys.KEY_FILE).read_bytes(), self.body)
        self.assertFalse((self.target / tool.MANIFEST).exists())
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'INCOMPLETE'): tool.backup(self.root, True)
        self.assert_preserved()

    def test_source_mutation_before_completion_is_detected_and_not_overwritten(self):
        original = tool.write_new_file
        changed = self.body + b'\n'
        def mutate(directory, name, body):
            original(directory, name, body)
            if name == tool.MANIFEST: self.key.write_bytes(changed)
        with patch.object(tool, 'write_new_file', side_effect=mutate):
            with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'SOURCE_CHANGED'):
                tool.backup(self.root, True)
        self.assertEqual(self.key.read_bytes(), changed)
        self.assertEqual((self.target / tool.keys.KEY_FILE).read_bytes(), self.body)

    def test_backup_directory_replacement_is_detected(self):
        original = tool.verify_snapshot
        calls = 0
        def replace(*args):
            nonlocal calls
            original(*args); calls += 1
            if calls == 1:
                self.directory.rename(self.parent / 'retained-backup')
                self.directory.mkdir(mode=0o700)
        with patch.object(tool, 'verify_snapshot', side_effect=replace):
            with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'PATH_CHANGED'):
                tool.backup(self.root, True)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assert_preserved()

    def test_missing_keys_or_project_redirect_do_not_prepare_keys(self):
        self.key.unlink()
        with self.assertRaises((FileNotFoundError, tool.keys.KeyPreparationError)): tool.backup(self.root, True)
        self.assertFalse(self.key.exists())
        self.assertFalse(self.directory.exists())
        alias = self.parent / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): tool.backup(alias, True)

    def test_empty_existing_destination_and_unknown_base_content_are_not_overwritten(self):
        self.directory.mkdir(mode=0o700); self.target.mkdir(mode=0o700)
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'INCOMPLETE'): tool.backup(self.root, True)
        self.assertEqual(list(self.target.iterdir()), [])
        (self.directory / 'unexpected').write_bytes(b'SYNTHETIC_ONLY')
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'CONTENTS'): tool.backup(self.root, True)
        self.assert_preserved()

    def test_main_reports_fixed_error_without_paths_or_secret_causes(self):
        for error, expected in ((OSError('SYNTHETIC_PRIVATE_KEY_PATH_AND_VALUE'), 'KEY_BACKUP_UNAVAILABLE'),
                                (tool.keys.KeyPreparationError('KEY_BACKUP_INCOMPLETE'), 'KEY_BACKUP_INCOMPLETE'),
                                (tool.keys.KeyPreparationError('/SYNTHETIC_PRIVATE_KEY_PATH'), 'KEY_BACKUP_UNAVAILABLE'),
                                (KeyboardInterrupt(), 'KEY_BACKUP_UNAVAILABLE')):
            output = io.StringIO()
            with patch.object(tool.sys, 'argv', ['backup']), patch.object(tool, 'backup', side_effect=error),\
                 patch.object(tool.sys, 'stderr', output):
                self.assertEqual(tool.main(), 1)
            value = json.loads(output.getvalue())
            self.assertEqual(value['code'], expected)
            self.assertNotIn('SYNTHETIC_PRIVATE', output.getvalue())

    def test_backup_snapshot_directory_redirect_and_hardlinked_receipt_are_rejected(self):
        tool.backup(self.root, True)
        moved = self.parent / 'retained-snapshot'
        self.target.rename(moved)
        self.target.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(OSError): tool.backup(self.root, True)
        self.target.unlink(); moved.rename(self.target)
        os.link(self.target / tool.MANIFEST, self.parent / 'linked-receipt')
        with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'TYPE'): tool.backup(self.root, True)
        self.assert_preserved()

    def test_source_directory_replacement_is_detected(self):
        original = tool.check_source
        calls = 0
        def replace(*args):
            nonlocal calls
            original(*args); calls += 1
            if calls == 1:
                self.source.rename(self.parent / 'retained-source')
                self.source.mkdir(mode=0o700)
        with patch.object(tool, 'check_source', side_effect=replace):
            with self.assertRaisesRegex(tool.keys.KeyPreparationError, 'SOURCE_PATH_CHANGED'):
                tool.backup(self.root, True)
        self.assertEqual(list(self.source.iterdir()), [])
        self.assertEqual((self.parent / 'retained-source' / tool.keys.KEY_FILE).read_bytes(), self.body)


if __name__ == '__main__':
    unittest.main()
