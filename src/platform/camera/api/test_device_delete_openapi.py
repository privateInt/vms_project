"""Check the executable OpenAPI against the agreed deletion contract; no services."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'device_delete_planned', ROOT / 'planned/test_device_delete_contract.py')
planned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planned)
OPENAPI = json.loads((ROOT / 'openapi.json').read_text())
SCHEMAS = OPENAPI['components']['schemas']


def validator(name):
    return Draft202012Validator(
        {'$ref': '#/components/schemas/' + name, 'components': OPENAPI['components']},
        format_checker=planned.FORMATS)


class DeviceDeleteOpenAPIContractTest(planned.DeviceDeleteContractTest):
    # Re-run all agreed request/response cases against the runtime definitions.
    def setUp(self):
        self.request = validator('DeviceDelete')
        self.response = validator('DeviceDeleteResponse')
        self.body = copy.deepcopy(planned.EXAMPLES['requests'][0]['body'])
        self.success = copy.deepcopy(planned.EXAMPLES['first_success']['body'])

    def test_runtime_schemas_preserve_the_agreed_contract(self):
        expected = copy.deepcopy(planned.SCHEMA)
        for key in ('$schema', '$id', '$comment', 'title', '$defs'):
            expected.pop(key)
        runtime = copy.deepcopy(SCHEMAS['DeviceDelete'])
        runtime.pop('description')
        self.assertEqual(runtime, expected)
        receipt = copy.deepcopy(planned.SCHEMA['$defs']['DeviceDeletion'])
        receipt['properties']['device_id'] = planned.SCHEMA['$defs']['DeviceID']
        self.assertEqual(SCHEMAS['DeviceDeletion'], receipt)
        response = copy.deepcopy(planned.SCHEMA['$defs']['DeviceDeleteResponse'])
        response['properties']['deletion']['$ref'] = '#/components/schemas/DeviceDeletion'
        self.assertEqual(SCHEMAS['DeviceDeleteResponse'], response)

    def test_delete_operation_and_headers(self):
        self.assertEqual(OPENAPI['info']['version'], '0.7.0-device-delete')
        resource = OPENAPI['paths']['/api/v1/devices/{device_id}']
        operation = resource['delete']
        self.assertEqual(operation['operationId'], 'deleteDevice')
        self.assertTrue(operation['requestBody']['required'])
        self.assertEqual(operation['requestBody']['content']['application/json']['schema'],
                         {'$ref': '#/components/schemas/DeviceDelete'})
        self.request.validate(operation['requestBody']['content']['application/json']['example'])
        path, key = operation['parameters']
        self.assertEqual((path['in'], path['name'], path['required']), ('path', 'device_id', True))
        for identifier in ('validate', 'Validate', 'validate-1'):
            Draft202012Validator(path['schema']).validate(identifier)
        self.assertEqual((key['in'], key['name'], key['required']), ('header', 'Idempotency-Key', True))
        self.assertEqual(set(operation['responses']),
                         {'200', '400', '401', '404', '405', '409', '413', '415', '422', '503'})
        for status, response in operation['responses'].items():
            headers = response['headers']
            self.assertIn('X-Request-ID', headers)
            self.assertEqual(headers['Cache-Control']['schema']['const'], 'no-store')
            self.assertNotIn('Location', headers)
            if status != '200':
                self.assertNotIn('Idempotency-Replayed', headers)
        success = operation['responses']['200']
        self.assertEqual(success['content']['application/json']['schema'],
                         {'$ref': '#/components/schemas/DeviceDeleteResponse'})
        self.response.validate(success['content']['application/json']['example'])
        for method in ('get', 'patch', 'delete'):
            self.assertEqual(resource[method]['responses']['405']['headers']['Allow']['schema']['const'],
                             'GET, PATCH, DELETE')
        self.assertIn('DEVICE_HAS_ACTIVE_SOURCES', operation['responses']['409']['description'])
        self.assertIn('DEVICE_USAGE_UNAVAILABLE', operation['responses']['503']['description'])

    def test_source_delete_remains_documented(self):
        resource = OPENAPI['paths']['/api/v1/sources/{source_id}']
        self.assertEqual(resource['delete']['operationId'], 'deleteSource')
        self.assertEqual(resource['delete']['parameters'][0]['schema']['not'], {'const': 'validate'})
        self.assertEqual(resource['delete']['responses']['200']['content']['application/json']['schema'],
                         {'$ref': '#/components/schemas/SourceDeleteResponse'})
        for method in ('get', 'patch', 'delete'):
            self.assertEqual(resource[method]['responses']['405']['headers']['Allow']['schema']['const'],
                             'GET, PATCH, DELETE')

    def test_document_references_and_component_schemas(self):
        def walk(value):
            if isinstance(value, dict):
                if '$ref' in value:
                    ref = value['$ref']
                    self.assertTrue(ref.startswith('#/'))
                    target = OPENAPI
                    for part in ref[2:].split('/'):
                        target = target[part.replace('~1', '/').replace('~0', '~')]
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(OPENAPI)
        for schema in SCHEMAS.values():
            Draft202012Validator.check_schema(schema)


if __name__ == '__main__':
    unittest.main(verbosity=2)
