"""Validate the planned request contract only; no HTTP or database implementation."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT/'device-update.schema.json').read_text())
EXAMPLES = json.loads((ROOT/'device-update.examples.json').read_text())
CURRENT = json.loads((ROOT.parent/'openapi.json').read_text())


class DeviceUpdateContractTest(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(SCHEMA)
        self.body = copy.deepcopy(EXAMPLES[0]['body'])

    def test_schema_examples_and_current_identifier_rules(self):
        Draft202012Validator.check_schema(SCHEMA)
        identity = Draft202012Validator(CURRENT['components']['schemas']['Device']['properties']['device_id'])
        for example in EXAMPLES:
            self.validator.validate(example['body'])
            identity.validate(example['device_id'])
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

    def test_immutable_observed_and_secret_fields_are_rejected(self):
        for field in ('device_id','device_kind','version','created_at','updated_at','deleted_at',
                      'capabilities','source_id','profiles','rtsp_url','password','token','credential_ref'):
            with self.subTest(field=field):
                self.assertFalse(self.validator.is_valid({**self.body, field:'not-accepted'}))

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
        for value in ('가'*128, '📷'*128, '  출입구  ', 'e\u0301'):
            self.validator.validate({**self.body, 'display_name':value})

    def test_create_and_update_keep_same_name_validation(self):
        self.assertEqual(SCHEMA['properties']['display_name'],
                         CURRENT['components']['schemas']['DeviceCreate']['properties']['display_name'])

    def test_wrong_schema_case_and_top_level_types(self):
        self.assertFalse(self.validator.is_valid({**self.body, 'schema_version':'v2'}))
        renamed = dict(self.body)
        renamed['Display_Name'] = renamed.pop('display_name')
        self.assertFalse(self.validator.is_valid(renamed))
        for value in (None, [], 'device', 1):
            self.assertFalse(self.validator.is_valid(value))

    def test_current_openapi_does_not_claim_patch_is_implemented(self):
        self.assertNotIn('patch', CURRENT['paths']['/api/v1/devices/{device_id}'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
