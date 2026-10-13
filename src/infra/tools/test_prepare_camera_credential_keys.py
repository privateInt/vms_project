"""Private temporary fixtures; no production keys, services or database IO."""
import base64
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

import prepare_camera_credential_keys as tool


class CredentialKeyPreparationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vms-key-unit-')
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)
        self.root = self.parent / 'project'
        self.root.mkdir(mode=0o700)
        (self.root / '.env').write_bytes(b'private fixture env\n')
        (self.root / '.env').chmod(0o600)
        self.directory = self.root.joinpath(*tool.KEY_DIRECTORY)
        self.file = self.directory / tool.KEY_FILE

    def start(self):
        return tool.prepare(self.root, True)

    def fixture(self):
        self.start()
        return json.loads(self.file.read_text())

    def invalid(self, value):
        with self.assertRaisesRegex(tool.KeyPreparationError, 'KEY_BUNDLE_INVALID'):
            tool.validate_bundle(json.dumps(value).encode())

    def test_without_apply_creates_no_directory(self):
        value = tool.prepare(self.root)
        self.assertEqual(value['status'], 'not_prepared')
        self.assertFalse((self.root / 'var').exists())
        self.assertEqual((self.root / '.env').read_bytes(), b'private fixture env\n')

    def test_first_prepare_and_repeat_preserve_bytes_modes_and_env(self):
        first = self.start()
        body = self.file.read_bytes()
        second = self.start()
        self.assertEqual(first['status'], 'prepared')
        self.assertEqual(second['status'], 'already_prepared')
        self.assertEqual(tool.prepare(self.root)['status'], 'validated')
        self.assertEqual(self.file.read_bytes(), body)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.directory / tool.LOCK_FILE).stat().st_mode), 0o600)
        self.assertEqual((self.root / '.env').read_bytes(), b'private fixture env\n')
        self.assertEqual(first['active_encryption_key_id'], second['active_encryption_key_id'])
        self.assertFalse(first['keys_activated_in_api'])

    def test_independent_32_byte_keys_and_public_result_has_no_key_material(self):
        result = self.start()
        value = json.loads(self.file.read_text())
        values = []
        for part in (value['encryption'], value['idempotency']):
            encoded = part['keys'][part['active_key_id']]
            self.assertNotIn(encoded, json.dumps(result))
            values.append(base64.b64decode(encoded, validate=True))
            self.assertEqual(len(values[-1]), 32)
        self.assertNotEqual(*values)
        self.assertFalse(result['environment_modified'])
        self.assertFalse(result['database_schema_modified'])
        self.assertFalse(result['service_restart_performed'])

    def test_wrong_file_mode_is_rejected_without_repair_or_regeneration(self):
        self.start(); body = self.file.read_bytes(); self.file.chmod(0o644)
        with self.assertRaisesRegex(tool.KeyPreparationError, 'PERMISSIONS'):
            self.start()
        self.assertEqual(self.file.read_bytes(), body)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o644)

    def test_wrong_directory_mode_is_rejected_without_repair(self):
        self.start(); self.directory.chmod(0o755)
        with self.assertRaisesRegex(tool.KeyPreparationError, 'PERMISSIONS'):
            self.start()
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o755)

    def test_symlink_project_and_parent_are_rejected(self):
        alias = self.parent / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): tool.prepare(alias, True)
        external = self.parent / 'external'; external.mkdir()
        (self.root / 'var').symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError): self.start()
        self.assertEqual(list(external.iterdir()), [])

    def test_symlink_bundle_lock_and_key_directory_are_rejected(self):
        self.start()
        for name in (tool.KEY_FILE, tool.LOCK_FILE):
            target = self.directory / name; original = target.read_bytes()
            target.unlink(); external = self.parent / ('external-' + name)
            external.write_bytes(original); target.symlink_to(external)
            with self.assertRaises(OSError): self.start()
            self.assertEqual(external.read_bytes(), original)
            target.unlink(); target.write_bytes(original); target.chmod(0o600)
        moved = self.parent / 'moved'; self.directory.rename(moved)
        self.directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(OSError): self.start()

    def test_hardlinked_bundle_is_rejected(self):
        self.start(); os.link(self.file, self.parent / 'hardlink')
        with self.assertRaisesRegex(tool.KeyPreparationError, 'TYPE'):
            self.start()

    def test_fifo_bundle_is_rejected_without_blocking(self):
        self.start(); self.file.unlink(); os.mkfifo(self.file, 0o600)
        with self.assertRaisesRegex(tool.KeyPreparationError, 'TYPE'):
            self.start()

    def test_foreign_owner_is_rejected(self):
        self.start()
        with patch.object(tool.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaisesRegex(tool.KeyPreparationError, 'OWNER'):
                self.start()

    def test_lock_contention_does_not_change_keys(self):
        self.start(); body = self.file.read_bytes()
        with (self.directory / tool.LOCK_FILE).open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(tool.KeyPreparationError, 'LOCKED'):
                self.start()
        self.assertEqual(self.file.read_bytes(), body)

    def test_partial_or_unknown_files_block_new_preparation(self):
        self.start(); (self.directory / '.key-bundle-interrupted.tmp').write_bytes(b'fixture')
        body = self.file.read_bytes()
        with self.assertRaisesRegex(tool.KeyPreparationError, 'CONTENTS'):
            self.start()
        self.assertEqual(self.file.read_bytes(), body)

    def test_invalid_json_and_duplicate_escaped_key_rejection(self):
        for body in (b'{}', b'null', b'[]', b'NaN', b'{"format_version":1,"format_\\u0076ersion":1}',
                     b'{"format_version":1} {}', b'\xff', b'x' * (tool.MAX_BYTES + 1)):
            with self.subTest(body=body[:40]), self.assertRaises(tool.KeyPreparationError):
                tool.validate_bundle(body)

    def test_unknown_fields_version_types_and_missing_active_keys(self):
        original = self.fixture()
        for field in (True, 1.0, '1', 2, None):
            self.invalid({**original, 'format_version': field})
        self.invalid({**original, 'password': 'fixture'})
        for purpose in ('encryption', 'idempotency'):
            for change in ({'active_key_id': 'enc-ffffffffffffffff'}, {'keys': {}}, {'password': 'fixture'}):
                value = copy.deepcopy(original); value[purpose].update(change); self.invalid(value)

    def test_bad_base64_length_purpose_and_key_reuse(self):
        original = self.fixture(); enc = original['encryption']['active_key_id']
        for token in ('invalid', '!!!!', base64.b64encode(b'x' * 31).decode(),
                      base64.b64encode(b'x' * 33).decode(), original['encryption']['keys'][enc] + '\n'):
            value = copy.deepcopy(original); value['encryption']['keys'][enc] = token; self.invalid(value)
        value = copy.deepcopy(original); mac = value['idempotency']['active_key_id']
        value['idempotency']['keys'][mac] = value['encryption']['keys'][enc]; self.invalid(value)
        value = copy.deepcopy(original); value['encryption'] = value['idempotency']; self.invalid(value)

    def test_old_keys_are_retained_when_valid_active_ids_change(self):
        value = self.fixture()
        for purpose, prefix in (('encryption', 'enc-'), ('idempotency', 'idem-')):
            identity = prefix + 'ffffffffffffffff'
            value[purpose]['keys'][identity] = base64.b64encode(bytes([7 if purpose == 'encryption' else 8]) * 32).decode()
            value[purpose]['active_key_id'] = identity
        self.file.write_text(json.dumps(value)); body = self.file.read_bytes()
        result = self.start()
        self.assertEqual(result['encryption_key_count'], 2)
        self.assertEqual(result['idempotency_key_count'], 2)
        self.assertEqual(self.file.read_bytes(), body)

    def test_new_destination_race_preserves_foreign_file(self):
        def concurrent(*args, **kwargs):
            self.file.write_bytes(b'concurrent user content')
            self.file.chmod(0o600)
            raise FileExistsError('fixture-only')
        with patch.object(tool.os, 'link', side_effect=concurrent), self.assertRaises(FileExistsError):
            self.start()
        self.assertEqual(self.file.read_bytes(), b'concurrent user content')
        self.assertEqual(set(p.name for p in self.directory.iterdir()), {tool.KEY_FILE, tool.LOCK_FILE})

    def test_directory_replacement_before_completion_is_rejected(self):
        original = tool.read_bundle
        calls = 0
        def replaced(directory):
            nonlocal calls
            value = original(directory); calls += 1
            if calls == 1:
                self.directory.rename(self.parent / 'retained-keys')
                self.directory.mkdir(mode=0o700)
            return value
        self.start()
        with patch.object(tool, 'read_bundle', side_effect=replaced):
            with self.assertRaisesRegex(tool.KeyPreparationError, 'PATH_CHANGED'):
                self.start()
        self.assertTrue((self.parent / 'retained-keys' / tool.KEY_FILE).is_file())

    def test_isolated_copy_restore_reuses_keys_without_regeneration(self):
        first = self.start(); before = self.file.read_bytes()
        restore = self.parent / 'restore'; restore.mkdir(mode=0o700)
        target = restore.joinpath(*tool.KEY_DIRECTORY); target.mkdir(parents=True, mode=0o700)
        shutil.copy2(self.file, target / tool.KEY_FILE)
        restored = tool.prepare(restore, True)
        self.assertEqual(restored['status'], 'already_prepared')
        self.assertEqual(restored['active_encryption_key_id'], first['active_encryption_key_id'])
        self.assertEqual((target / tool.KEY_FILE).read_bytes(), before)
        self.assertEqual(self.file.read_bytes(), before)

    def test_public_failure_is_fixed_code_without_exception_details(self):
        output = io.StringIO()
        with patch.object(tool.sys, 'argv', ['keys', '--apply']), patch.object(tool, 'prepare',
                side_effect=OSError('fixture-password-secret')), patch('sys.stderr', output):
            self.assertEqual(tool.main(), 1)
        self.assertNotIn('fixture-password-secret', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['code'], 'KEY_PREPARATION_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main(verbosity=2)
