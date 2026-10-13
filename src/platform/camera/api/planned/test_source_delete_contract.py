"""Static deletion contract checks; no HTTP, database or service operations."""
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'source-delete.schema.json').read_text())
EXAMPLES = json.loads((ROOT / 'source-delete.examples.json').read_text())
CURRENT = json.loads((ROOT.parent / 'openapi.json').read_text())
MAX_VERSION = 9223372036854775807
FORMATS = FormatChecker()


@FORMATS.checks('date-time', raises=ValueError)
def valid_utc_timestamp(value):
    # jsonschema's optional RFC3339 dependency is not required by this project.
    # Check calendar validity explicitly, including on Python 3.10; fractional
    # precision is validated without converting timestamps through floats.
    if not isinstance(value, str):
        return True
    match = re.fullmatch(
        r'([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?Z', value)
    if match is None:
        return False
    datetime(*(int(part) for part in match.groups()))
    return True


def definition(name):
    return Draft202012Validator(
        {'$ref': '#/$defs/' + name, '$defs': SCHEMA['$defs']},
        format_checker=FORMATS)


class SourceDeleteContractTest(unittest.TestCase):
    def setUp(self):
        self.request = Draft202012Validator(SCHEMA)
        self.response = definition('SourceDeleteResponse')
        self.body = copy.deepcopy(EXAMPLES['requests'][0]['body'])
        self.success = copy.deepcopy(EXAMPLES['first_success']['body'])

    def test_schema_and_request_examples(self):
        Draft202012Validator.check_schema(SCHEMA)
        current_id = Draft202012Validator(
            CURRENT['components']['schemas']['SourceCreate']['properties']['source_id'])
        for example in EXAMPLES['requests']:
            with self.subTest(example=example['name']):
                self.request.validate(example['body'])
                definition('SourceID').validate(example['source_id'])
                current_id.validate(example['source_id'])
                self.assertEqual(example['method'], 'DELETE')
                self.assertTrue(1 <= len(example['idempotency_key']) <= 128)
                self.assertTrue(all(33 <= ord(c) <= 126 for c in example['idempotency_key']))

    def test_required_fields_types_and_schema_version(self):
        for field in ('schema_version', 'expected_version'):
            body = dict(self.body)
            del body[field]
            self.assertFalse(self.request.is_valid(body))
            self.assertFalse(self.request.is_valid({**self.body, field: None}))
            body = dict(self.body)
            body[field.upper()] = body.pop(field)
            self.assertFalse(self.request.is_valid(body))
        self.assertFalse(self.request.is_valid({**self.body, 'schema_version': 'v2'}))
        for value in (None, [], 'source', 1, True):
            self.assertFalse(self.request.is_valid(value))

    def test_version_boundaries_without_float_rounding(self):
        for value in (0, -1, MAX_VERSION + 1, 1.5, '2', True, [], {}):
            with self.subTest(value=value):
                self.assertFalse(self.request.is_valid({**self.body, 'expected_version': value}))
        for value in (1, MAX_VERSION - 1, MAX_VERSION):
            self.request.validate({**self.body, 'expected_version': value})

    def test_force_purge_identity_and_secret_inputs_are_rejected(self):
        fields = {
            'force': True, 'purge': True, 'cascade': True, 'restore': True,
            'delete_recordings': True, 'skip_usage_check': True,
            'source_id': 's1', 'device_id': 'd1', 'channel_key': 'ch1',
            'display_name': 'name', 'profiles': [], 'primary_profile_id': 'main',
            'version': 3, 'deleted_at': '2026-10-01T04:00:00Z',
            'registration_state': 'DELETED', 'runtime_verified': True,
            'session_id': 'session', 'consumer_id': 'consumer',
            'rtsp_url': 'rtsp://example.invalid/stream', 'password': 'example',
            'token': 'example', 'credential_ref': 'reference',
        }
        for field, value in fields.items():
            with self.subTest(field=field):
                self.assertFalse(self.request.is_valid({**self.body, field: value}))

    def test_source_identifier_boundaries_and_reserved_path(self):
        validator = definition('SourceID')
        for value in ('validate', '', 'a' * 65, '한글', 'a/b', 'a\n', 'a ', '_a', None):
            with self.subTest(value=value):
                self.assertFalse(validator.is_valid(value))
        for value in ('a', 'a' * 64, 'Validate', 'validate-1', 'source_1.a-b'):
            validator.validate(value)

    def test_success_and_replay_examples_have_same_receipt(self):
        first, replay = EXAMPLES['first_success'], EXAMPLES['same_key_replay']
        for example in (first, replay):
            self.response.validate(example['body'])
            self.assertEqual(example['http_status'], 200)
            self.assertEqual(example['headers']['X-Request-ID'], example['body']['request_id'])
            self.assertNotIn('Location', example['headers'])
        request = EXAMPLES['requests'][0]
        self.assertEqual(first['body']['deletion']['source_id'], request['source_id'])
        self.assertEqual(first['body']['deletion']['version'], request['body']['expected_version'] + 1)
        self.assertEqual(first['headers']['Idempotency-Replayed'], 'false')
        self.assertEqual(replay['headers']['Idempotency-Replayed'], 'true')
        self.assertNotEqual(first['body']['request_id'], replay['body']['request_id'])
        self.assertEqual({k: v for k, v in first['body'].items() if k != 'request_id'},
                         {k: v for k, v in replay['body'].items() if k != 'request_id'})

    def test_response_required_fields_and_deleted_state(self):
        for location, fields in (((), SCHEMA['$defs']['SourceDeleteResponse']['required']),
                                 (('deletion',), SCHEMA['$defs']['SourceDeletion']['required'])):
            for field in fields:
                for replacement in ('missing', 'null'):
                    body = copy.deepcopy(self.success)
                    node = body['deletion'] if location else body
                    if replacement == 'missing':
                        del node[field]
                    else:
                        node[field] = None
                    with self.subTest(location=location, field=field, replacement=replacement):
                        self.assertFalse(self.response.is_valid(body))
        for field, value in (('registration_state', 'REGISTERED'), ('registration_state', 'DELETING'),
                             ('runtime_verified', True), ('request_id', ''), ('source', {})):
            self.assertFalse(self.response.is_valid({**self.success, field: value}))
        body = copy.deepcopy(self.success)
        body['deletion']['profiles'] = []
        self.assertFalse(self.response.is_valid(body))

    def test_receipt_version_and_utc_timestamp_boundaries(self):
        for value in (1, 0, MAX_VERSION + 1, '3', True, 2.5):
            body = copy.deepcopy(self.success)
            body['deletion']['version'] = value
            self.assertFalse(self.response.is_valid(body))
        for value in (2, MAX_VERSION):
            body = copy.deepcopy(self.success)
            body['deletion']['version'] = value
            self.response.validate(body)
        for value in ('2026-10-01T04:00:00Z', '2026-10-01T04:00:00.123456789Z'):
            body = copy.deepcopy(self.success)
            body['deletion']['deleted_at'] = value
            self.response.validate(body)
        for value in ('2026-02-30T04:00:00Z', '2026-10-01', '2026-10-01T04:00:00',
                      '2026-10-01T04:00:00+09:00', '2026-10-01T04:00:00.1234567890Z',
                      '2026-10-01T04:00:00Z\n'):
            body = copy.deepcopy(self.success)
            body['deletion']['deleted_at'] = value
            with self.subTest(timestamp=value):
                self.assertFalse(self.response.is_valid(body))


if __name__ == '__main__':
    unittest.main(verbosity=2)
