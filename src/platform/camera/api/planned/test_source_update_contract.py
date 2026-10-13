"""Validate planned request/response examples; no HTTP, database or service calls."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT/'source-update.schema.json').read_text())
EXAMPLES = json.loads((ROOT/'source-update.examples.json').read_text())
CURRENT = json.loads((ROOT.parent/'openapi.json').read_text())


class SourceUpdateContractTest(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(SCHEMA)
        self.body = copy.deepcopy(EXAMPLES['requests'][0]['body'])

    def test_request_examples_and_identifier_rules(self):
        Draft202012Validator.check_schema(SCHEMA)
        identity = Draft202012Validator(CURRENT['components']['schemas']['SourceCreate']['properties']['source_id'])
        for example in EXAMPLES['requests']:
            with self.subTest(example=example['name']):
                self.validator.validate(example['body'])
                identity.validate(example['source_id'])
                self.assertTrue(1 <= len(example['idempotency_key']) <= 128)
                self.assertTrue(all(33 <= ord(c) <= 126 for c in example['idempotency_key']))

    def test_missing_and_null_fields(self):
        for field in SCHEMA['required']:
            body = dict(self.body)
            del body[field]
            with self.subTest(field=field, value='missing'):
                self.assertFalse(self.validator.is_valid(body))
            with self.subTest(field=field, value=None):
                self.assertFalse(self.validator.is_valid({**self.body, field:None}))

    def test_identity_profiles_transport_and_secrets_are_rejected(self):
        fields = {'source_id':'s1','device_id':'d1','channel_key':'ch2','transport':'RTSP','input_mode':'PULL',
                  'motion_mode':'FIXED','profiles':[],'primary_profile_id':'main','profile_id':'sub',
                  'version':2,'created_at':'2026-09-30T08:00:00Z','updated_at':'2026-09-30T08:00:00Z',
                  'deleted_at':None,'device_kind':'CCTV','capabilities':{},'registration_state':'REGISTERED',
                  'runtime_verified':False,'rtsp_url':'rtsp://example.invalid/stream','username':'name',
                  'password':'not-a-secret','token':'not-a-secret','credential_ref':'reference'}
        for field, value in fields.items():
            with self.subTest(field=field):
                self.assertFalse(self.validator.is_valid({**self.body, field:value}))

    def test_version_bounds_and_types(self):
        for value in (0, -1, 9223372036854775808, 1.5, '1', True, [], {}):
            with self.subTest(value=value):
                self.assertFalse(self.validator.is_valid({**self.body, 'expected_version':value}))
        for value in (1, 9223372036854775807):
            self.validator.validate({**self.body, 'expected_version':value})

    def test_display_name_boundaries_and_unicode(self):
        for value in ('', ' ', '\t\r\n', '\u3000\u00a0', '가'*129, 'name\u0000', 1, True, []):
            with self.subTest(value=value):
                self.assertFalse(self.validator.is_valid({**self.body, 'display_name':value}))
        for value in ('가'*128, '📷'*128, '  출입구 영상  ', 'e\u0301'):
            self.validator.validate({**self.body, 'display_name':value})

    def test_name_validation_matches_source_create(self):
        self.assertEqual(SCHEMA['properties']['display_name'],
                         CURRENT['components']['schemas']['SourceCreate']['properties']['display_name'])

    def test_wrong_schema_case_and_top_level_types(self):
        self.assertFalse(self.validator.is_valid({**self.body, 'schema_version':'v2'}))
        for field in SCHEMA['required']:
            body = dict(self.body)
            body[field.upper()] = body.pop(field)
            self.assertFalse(self.validator.is_valid(body))
        for value in (None, [], 'source', 1):
            self.assertFalse(self.validator.is_valid(value))

    def test_reserved_and_invalid_source_ids(self):
        identity = Draft202012Validator(CURRENT['components']['schemas']['SourceCreate']['properties']['source_id'])
        for value in ('validate', '', 'a'*65, '한글', 'a/b', ' source'):
            self.assertFalse(identity.is_valid(value))
        for value in ('Validate', 'validate-1', 'a'*64):
            identity.validate(value)

    def test_success_example_reuses_full_source_response(self):
        response = EXAMPLES['first_success']
        validator = Draft202012Validator({'$ref':'#/components/schemas/SourceResponse',
                                          'components':CURRENT['components']}, format_checker=FormatChecker())
        validator.validate(response['body'])
        self.assertEqual(response['http_status'],200)
        self.assertEqual(response['headers']['Idempotency-Replayed'],'false')
        self.assertEqual(response['headers']['X-Request-ID'],response['body']['request_id'])
        self.assertNotIn('Location',response['headers'])
        source, request = response['body']['source'], EXAMPLES['requests'][0]
        self.assertEqual(source['source_id'],request['source_id'])
        self.assertEqual(source['display_name'],request['body']['display_name'])
        self.assertEqual(source['version'],request['body']['expected_version']+1)
        for field in ('profiles','registration_state','runtime_verified'):
            value = copy.deepcopy(response['body'])
            del (value['source'] if field=='profiles' else value)[field]
            self.assertFalse(validator.is_valid(value))


if __name__ == '__main__':
    unittest.main(verbosity=2)
