"""Planned local record shape only. No file leases, DB, keys or runtime admission IO."""
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'credential-admission.schema.json').read_text())
EXAMPLES = json.loads((ROOT / 'credential-admission.examples.json').read_text())
CURRENT = json.loads((ROOT.parent / 'openapi.json').read_text())
FORMATS = FormatChecker()
MAX_GENERATION = 9223372036854775807


@FORMATS.checks('date-time', raises=ValueError)
def utc_calendar(value):
    if not isinstance(value, str):
        return True
    match = re.fullmatch(r'([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?Z', value)
    if match is None:
        return False
    datetime(*(int(n) for n in match.groups()))
    return True


def validator(name):
    return Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': SCHEMA['$defs']},
                               format_checker=FORMATS)


class CredentialAdmissionContractTest(unittest.TestCase):
    def setUp(self):
        self.records = {row['name']: copy.deepcopy(row['record']) for row in EXAMPLES['records']}
        self.open = self.records['first_open']
        self.binding = self.open['binding']

    def reject(self, name, values):
        for value in values:
            with self.subTest(definition=name):
                self.assertFalse(validator(name).is_valid(value))

    def test_schema_and_local_references_are_planned(self):
        Draft202012Validator.check_schema(SCHEMA)
        def walk(node):
            if isinstance(node, dict):
                if '$ref' in node:
                    self.assertTrue(node['$ref'].startswith('#/$defs/'))
                    self.assertIn(node['$ref'].split('/')[-1], SCHEMA['$defs'])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(SCHEMA)
        self.assertEqual(SCHEMA['x-vms-contract-status'], 'planned')
        self.assertIn('not HTTP', SCHEMA['x-vms-contract-scope'])

    def test_all_synthetic_records_have_valid_shapes(self):
        root = Draft202012Validator(SCHEMA, format_checker=FORMATS)
        for row in EXAMPLES['records']:
            root.validate(row['record'])
        self.assertEqual({r['state'] for r in self.records.values()}, {'FENCED', 'PREPARED', 'OPEN'})

    def test_record_required_fields_and_wrong_roots(self):
        for field in SCHEMA['$defs']['AdmissionRecord']['required']:
            value = dict(self.open)
            del value[field]
            self.reject('AdmissionRecord', [value])
            self.reject('AdmissionRecord', [{**self.open, field: None}])
        self.reject('AdmissionRecord', [None, [], '', 1, True, {}, {**self.open, 'schema_version': 'v2'}])

    def test_uuid4_is_canonical_and_nonempty(self):
        for value in ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'aaaaaaaa-aaaa-4aaa-baaa-aaaaaaaaaaaa'):
            validator('UUID4').validate(value)
        self.reject('UUID4', ['', 'id-1', 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA',
                    '00000000-0000-0000-0000-000000000000',
                    'aaaaaaaa-aaaa-1aaa-8aaa-aaaaaaaaaaaa',
                    'aaaaaaaa-aaaa-4aaa-caaa-aaaaaaaaaaaa',
                    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\n', None, True])

    def test_generation_positive_int64_bounds(self):
        for value in (1, 2, MAX_GENERATION):
            validator('Generation').validate(value)
        self.reject('Generation', [0, -1, MAX_GENERATION + 1, True, '1', 1.5, None])

    def test_utc_calendar_fraction_and_suffix(self):
        for value in ('2026-10-02T06:00:00Z', '2026-10-02T06:00:00.123456789Z'):
            validator('UTC').validate(value)
        self.reject('UTC', ['2026-02-30T06:00:00Z', '2026-10-02', '2026-10-02T06:00:00',
                    '2026-10-02T06:00:00+09:00', '2026-10-02T06:00:00.1234567890Z',
                    '2026-10-02T06:00:00Z\n', True])

    def test_only_fenced_prepared_open_states(self):
        self.reject('AdmissionRecord', [{**self.open, 'state': value} for value in
                    ('READY', 'RESTORED', 'OPENED', 'open', 'AUTO', '', None, True)])

    def test_initial_fenced_record_can_be_unbound(self):
        validator('AdmissionRecord').validate(self.records['bootstrap_fenced'])
        validator('AdmissionRecord').validate({**self.records['bootstrap_fenced'], 'generation': 2})
        self.assertIsNone(self.records['bootstrap_fenced']['binding'])
        self.assertEqual(self.records['bootstrap_fenced']['seen_encryption_key_ids'], [])

    def test_fenced_can_retain_last_binding_without_admitting_it(self):
        validator('AdmissionRecord').validate(self.records['restore_fenced'])
        self.assertEqual(self.records['restore_fenced']['binding'], self.open['binding'])
        self.assertEqual(self.records['restore_fenced']['state'], 'FENCED')

    def test_prepared_and_open_require_binding_and_nonempty_history(self):
        for state in ('PREPARED', 'OPEN'):
            self.reject('AdmissionRecord', [{**self.open, 'state': state, 'binding': None},
                        {**self.open, 'state': state, 'seen_encryption_key_ids': []}])
        self.reject('AdmissionRecord', [{**self.records['restore_fenced'], 'seen_encryption_key_ids': []}])

    def test_binding_requires_all_fields_without_null(self):
        for field in SCHEMA['$defs']['Binding']['required']:
            value = dict(self.binding)
            del value[field]
            self.reject('Binding', [value, {**self.binding, field: None}])
        self.reject('Binding', [None, [], 'bound', True, {}])

    def test_binding_pins_future_schema_9_without_changing_current_api(self):
        self.reject('Binding', [{**self.binding, 'schema_version': v} for v in (7, 8, 10, '9', True, None)])
        validator('Binding').validate({**self.binding, 'schema_version': 9})
        self.assertEqual(CURRENT['info']['version'], '0.7.0-device-delete')
        for path in CURRENT['paths']:
            self.assertNotIn('credential', path)
            self.assertNotIn('admission', path)
            self.assertNotIn('restore', path)

    def test_writer_and_budget_roles_are_fixed_distinct_roles(self):
        self.assertNotEqual(self.binding['writer_role'], self.binding['budget_role'])
        for field in ('writer_role', 'budget_role'):
            self.reject('Binding', [{**self.binding, field: v} for v in
                        ('camera_runtime', 'camera_owner', 'postgres', 'camera_api', 'root', '', None)])
        self.reject('Binding', [{**self.binding, 'writer_role': self.binding['budget_role']}])

    def test_database_names_are_identifiers_without_authorities(self):
        for name in ('vms_camera', 'DB_1', '_' + 'a' * 62):
            validator('DatabaseName').validate(name)
        self.reject('DatabaseName', ['', 'a' * 64, '1db', 'db.invalid', 'db:5432',
                    'postgres://user@db/name', 'db/name', 'db-name', 'DB\n', '카메라', True])

    def test_sha256_hex_digests_only(self):
        validator('SHA256').validate('a' * 64)
        self.reject('SHA256', ['', 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64, 'a' * 64 + '\n',
                    'sha256:' + 'a' * 64, True, None])

    def test_encryption_and_hmac_identifiers_are_not_interchangeable(self):
        old = self.binding['active_encryption_key_id']
        mac = self.binding['active_idempotency_key_id']
        validator('EncryptionKeyID').validate(old)
        validator('IdempotencyKeyID').validate(mac)
        self.reject('EncryptionKeyID', [mac, 'enc-' + '0' * 15, old + '\n', old.upper(), 'enc-key'])
        self.reject('IdempotencyKeyID', [old, 'idem-' + '0' * 17, mac + '\n', mac.upper()])

    def test_seen_history_is_bounded_unique_and_typed(self):
        history = ['enc-' + f'{number:016x}' for number in range(512)]
        validator('AdmissionRecord').validate({**self.open, 'seen_encryption_key_ids': history})
        self.reject('AdmissionRecord', [{**self.open, 'seen_encryption_key_ids': history + ['enc-' + f'{512:016x}']},
                    {**self.open, 'seen_encryption_key_ids': [history[0], history[0]]},
                    {**self.open, 'seen_encryption_key_ids': [self.binding['active_idempotency_key_id']]},
                    {**self.open, 'seen_encryption_key_ids': 'enc-1111111111111161'}])

    def test_counter_policy_cannot_restore_or_reset_old_budget(self):
        self.reject('AdmissionRecord', [{**self.open, 'counter_policy': value} for value in
                    ('reset-counter-v1', 'snapshot-counter-v1', 'AUTO', 'reuse-old-key', None, True)])

    def test_no_secrets_dsns_raw_targets_or_paths_in_record(self):
        for field in ('encryption_key', 'hmac_key', 'key_material', 'password', 'username',
                      'dsn', 'database_url', 'token', 'secret', 'key_file', 'backup_path', 'host', 'port'):
            self.reject('AdmissionRecord', [{**self.open, field: 'synthetic-only'}])
            self.reject('Binding', [{**self.binding, field: 'synthetic-only'}])

    def test_no_runtime_bypass_or_readiness_claim_fields(self):
        for field in ('force', 'skip_fence', 'disable_lock', 'runtime_ready', 'verified', 'restore_ready',
                      'credential_api_activated', 'business_runtime_ready', 'allow_rewind', 'encryption_uses'):
            self.reject('AdmissionRecord', [{**self.open, field: True}])
            self.reject('Binding', [{**self.binding, field: True}])

    def test_example_workflow_preserves_epoch_binding_and_history(self):
        for step in EXAMPLES['workflow']:
            before, after = self.records[step['from']], self.records[step['to']]
            self.assertEqual(before['deployment_id'], after['deployment_id'])
            self.assertTrue(set(before['seen_encryption_key_ids']) <= set(after['seen_encryption_key_ids']))
            self.assertTrue(step['requires'])
            if after['state'] == 'FENCED':
                self.assertEqual(after['generation'], before['generation'] + 1)
                self.assertNotEqual(after['operation_id'], before['operation_id'])
            else:
                self.assertEqual(after['generation'], before['generation'])
                self.assertEqual(after['operation_id'], before['operation_id'])
            if before['state'] == 'PREPARED':
                self.assertEqual(before['binding'], after['binding'])

    def test_restore_example_changes_db_incarnation_and_encryption_material_identity(self):
        old = self.open['binding']
        new = self.records['restore_open']['binding']
        for field in ('database_id', 'key_bundle_sha256', 'active_encryption_key_id'):
            self.assertNotEqual(old[field], new[field])
        self.assertIn(old['active_encryption_key_id'], self.records['restore_open']['seen_encryption_key_ids'])
        self.assertIn(new['active_encryption_key_id'], self.records['restore_open']['seen_encryption_key_ids'])

    def test_shape_validation_does_not_claim_dynamic_admission(self):
        names = set()
        for row in EXAMPLES['structurally_valid_but_disallowed']:
            validator('AdmissionRecord').validate(row['record'])
            self.assertTrue(row['required_future_rejection'].startswith('CREDENTIAL_ADMISSION_'))
            names.add(row['name'])
        self.assertEqual(names, {'binding_key_missing_from_history', 'old_encryption_key_reused_after_fence', 'generation_rollback'})
        # JSON Schema recognizes 1.0 as an integer; the future bounded raw
        # parser, not this static check, must reject the decimal token.
        self.assertTrue(validator('Generation').is_valid(json.loads('1.0')))


if __name__ == '__main__':
    unittest.main()
