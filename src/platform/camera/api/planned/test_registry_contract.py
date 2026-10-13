"""Planned contract checks; requires the development-only jsonschema package."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'registry.schema.json').read_text())
EXAMPLES = json.loads((ROOT / 'registry.examples.json').read_text())


class RegistryContractTest(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(SCHEMA)

    def test_schema_and_all_examples(self):
        Draft202012Validator.check_schema(SCHEMA)
        for item in EXAMPLES:
            with self.subTest(item=item['name']):
                self.validator.validate(item['body'])
                Draft202012Validator(SCHEMA['$defs'][item['schema']]).validate(item['body'])

    def test_required_fields(self):
        for item in EXAMPLES:
            for field in SCHEMA['$defs'][item['schema']]['required']:
                body = copy.deepcopy(item['body'])
                del body[field]
                with self.subTest(item=item['name'], field=field):
                    self.assertFalse(self.validator.is_valid(body))

    def test_secrets_and_observed_state_cannot_be_submitted(self):
        for item in EXAMPLES:
            for field in ('password', 'token', 'credential_ref', 'rtsp_url', 'source_session_id', 'capabilities'):
                body = dict(item['body'], **{field: 'not-a-real-secret'})
                with self.subTest(item=item['name'], field=field):
                    self.assertFalse(self.validator.is_valid(body))

    def test_wrong_transport_pair_and_profile_bounds(self):
        for item in EXAMPLES:
            if item['schema'] != 'SourceCreate':
                continue
            body = copy.deepcopy(item['body'])
            body['input_mode'] = 'PUSH' if body['transport'] == 'RTSP' else 'PULL'
            self.assertFalse(self.validator.is_valid(body))
            for field, bad in (('fps', 0), ('width', 0), ('height', 16385), ('codec', 'UNKNOWN')):
                body = copy.deepcopy(item['body'])
                body['profiles'][0][field] = bad
                self.assertFalse(self.validator.is_valid(body))

    def test_identifiers_names_and_types(self):
        for item in EXAMPLES:
            for field, bad in (('device_id', '../device'), ('display_name', '   '), ('display_name', 'a' * 129), ('schema_version', 'v2')):
                body = dict(item['body'], **{field: bad})
                self.assertFalse(self.validator.is_valid(body))
            for field in item['body']:
                body = dict(item['body'], **{field: None})
                self.assertFalse(self.validator.is_valid(body))

    def test_multiple_channels_and_xr_without_onvif(self):
        source = copy.deepcopy(EXAMPLES[1]['body'])
        second = dict(source, source_id='source-cctv-002', channel_key='channel-2')
        self.validator.validate(source)
        self.validator.validate(second)
        self.validator.validate(EXAMPLES[3]['body'])
        self.assertNotIn('capabilities', EXAMPLES[3]['body'])

    def test_existing_profile_field_contract_is_preserved(self):
        old = json.loads((ROOT.parent / 'schemas/SourceSpec.schema.json').read_text())
        self.assertEqual(SCHEMA['$defs']['SourceCreate']['properties']['profiles'], old['properties']['profiles'])


if __name__ == '__main__':
    unittest.main()
