"""Static contract and failure boundaries only; no production profile is supplied."""
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
import credential_supply_contract as contract

ROOT = Path(__file__).parent
EXAMPLES = json.loads((ROOT/'credential-supply.examples.json').read_text())


class CredentialSupplyContractTest(unittest.TestCase):
    def setUp(self): self.profile = copy.deepcopy(EXAMPLES['profiles'][0]['profile'])
    def reject(self, value=None, code=None):
        value = self.profile if value is None else value
        raw = json.dumps(value).encode()
        with self.assertRaises(contract.SupplyContractError) as raised: contract.parse_supply_profile(raw)
        if code: self.assertEqual(str(raised.exception), code)
        return str(raised.exception)

    def test_schema_references_are_local_and_contract_is_review_only(self):
        Draft202012Validator.check_schema(contract.SCHEMA)
        def walk(node):
            if isinstance(node, dict):
                if '$ref' in node:
                    self.assertTrue(node['$ref'].startswith('#/$defs/'))
                    self.assertIn(node['$ref'].split('/')[-1], contract.SCHEMA['$defs'])
                for v in node.values(): walk(v)
            elif isinstance(node, list):
                for v in node: walk(v)
        walk(contract.SCHEMA)
        self.assertEqual(contract.SCHEMA['x-vms-contract-status'], 'planned')
        self.assertIn('not HTTP', contract.SCHEMA['x-vms-contract-scope'])

    def test_synthetic_examples_validate_without_authorizing_anything(self):
        self.assertTrue(EXAMPLES['synthetic_only'])
        for row in EXAMPLES['profiles']:
            result = contract.parse_supply_profile(json.dumps(row['profile']).encode())
            self.assertEqual(result, row['profile']); self.assertEqual(result['intent'], 'review-only')
            self.assertNotIn('activation_allowed', result); self.assertNotIn('approved', result)

    def test_all_nested_fields_are_required_and_nonnull(self):
        for name in ('SupplyPlan',):
            definition = contract.SCHEMA['$defs'][name]
            for field in definition['required']:
                with self.subTest(field=field):
                    value = copy.deepcopy(self.profile); del value[field]; self.reject(value)
                    value = copy.deepcopy(self.profile); value[field] = None; self.reject(value)
        for section, original in self.profile.items():
            if not isinstance(original, dict): continue
            for field in original:
                with self.subTest(section=section, field=field):
                    value = copy.deepcopy(self.profile); del value[section][field]; self.reject(value)

    def test_roles_and_control_target_are_fixed(self):
        for section, field in (('runtime','writer_role'), ('runtime','budget_role'),
                              ('maintenance','database_role'), ('maintenance','control_database')):
            with self.subTest(section=section, field=field):
                value = copy.deepcopy(self.profile)
                value[section][field] = 'vms_camera' if field == 'control_database' else 'postgres'
                self.reject(value)
        self.profile['runtime']['writer_role'] = 'camera_credential_budget'; self.reject()

    def test_runtime_must_be_nonroot_and_distinct_from_maintenance(self):
        self.profile['runtime']['uid'] = 0; self.reject()
        self.profile['runtime']['uid'] = self.profile['maintenance']['uid'] = 2000
        self.profile['authority']['owner_uid'] = 2000
        self.reject(code='SUPPLY_UID_OR_GROUP_CONFLICT')

    def test_authority_owner_and_runtime_group_must_match_designated_processes(self):
        self.profile['authority']['owner_uid'] = 3000; self.reject(code='SUPPLY_UID_OR_GROUP_CONFLICT')
        self.profile['authority']['owner_uid'] = self.profile['maintenance']['uid']
        self.profile['authority']['runtime_gid'] += 1; self.reject(code='SUPPLY_UID_OR_GROUP_CONFLICT')

    def test_uid_gid_ranges_and_bool_types(self):
        for section, field in (('runtime','uid'), ('runtime','gid'), ('maintenance','uid'), ('key_supply','source_owner_uid')):
            for value in (-1, 4294967295, True, '1000'):
                with self.subTest(section=section, field=field, value=value):
                    profile = copy.deepcopy(self.profile); profile[section][field] = value; self.reject(profile)

    def test_parser_rejects_decimal_exponent_and_nonfinite_numbers(self):
        raw = json.dumps(self.profile).encode()
        for token in (b'1.0', b'1e0', b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(token=token), self.assertRaisesRegex(contract.SupplyContractError, '^SUPPLY_NONINTEGER_NUMBER$'):
                contract.parse_supply_profile(raw.replace(b'"format_version": 1', b'"format_version": '+token))
        self.profile['runtime']['uid'] = 65532.0
        with self.assertRaisesRegex(contract.SupplyContractError, '^SUPPLY_INTEGER_TYPE_INVALID$'):
            contract.validate_supply_profile(self.profile)

    def test_duplicate_and_escaped_alias_fields_rejected(self):
        raw = json.dumps(self.profile).encode()
        for replacement in (b'"format_version":1,"format_version":1', b'"format_version":1,"format_\\u0076ersion":1'):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(contract.SupplyContractError, '^SUPPLY_DUPLICATE_FIELD$'):
                contract.parse_supply_profile(raw.replace(b'"format_version": 1', replacement))

    def test_input_size_utf8_syntax_and_roots(self):
        for raw in (b'', b'x'*(contract.MAX_BYTES+1), b'\xff', b'{} trailing', b'[]', b'null', b'true', b'"synthetic"'):
            with self.subTest(raw_size=len(raw)), self.assertRaises(contract.SupplyContractError): contract.parse_supply_profile(raw)
        with self.assertRaises(contract.SupplyContractError): contract.parse_supply_profile(json.dumps(self.profile))

    def test_secrets_and_dsns_rejected_at_all_object_levels_without_disclosure(self):
        marker = 'SYNTHETIC_SECRET_NEVER_ECHO'
        for section in (None, 'runtime', 'maintenance', 'tls', 'authority', 'key_supply', 'database'):
            for field in ('password','dsn','token','private_key','encryption_key','hmac_key'):
                with self.subTest(section=section, field=field):
                    value = copy.deepcopy(self.profile); target = value if section is None else value[section]
                    target[field] = marker; self.assertNotIn(marker, self.reject(value))

    def test_bypass_and_approval_claim_fields_rejected(self):
        for field in ('force','skip_fence','approved','activation_allowed','business_runtime_ready','restore_ready','auto_bootstrap','lock_device','lock_inode'):
            with self.subTest(field=field):
                self.reject({**self.profile, field: True})
        self.profile['intent'] = 'approved'; self.reject()

    def test_only_production_verify_full_without_fallback(self):
        for mode in ('disable','prefer','require','verify-ca'):
            with self.subTest(mode=mode):
                value = copy.deepcopy(self.profile); value['tls']['mode'] = mode; self.reject(value)
        self.profile['tls']['minimum_version'] = 'TLS1.0'; self.reject()

    def test_canonical_ipv4_ipv6_and_distinct_source_policy(self):
        v = copy.deepcopy(self.profile)
        for section, field, ip in (('database','host_ip','2001:db8::10'),('maintenance','source_ip','2001:db8::20'),('runtime','source_ip','2001:db8::30')):
            v[section][field] = ip
        self.assertEqual(contract.parse_supply_profile(json.dumps(v).encode()), v)
        self.profile['runtime']['source_ip'] = self.profile['maintenance']['source_ip']; self.reject(code='SUPPLY_SOURCE_BOUNDARY_CONFLICT')

    def test_dns_multi_ip_unspecified_multicast_mapped_and_scoped_ip_rejected(self):
        for ip in ('db.example.invalid','192.0.2.10,192.0.2.11','0.0.0.0','::','224.0.0.1','ff02::1','::ffff:192.0.2.1','fe80::1%eth0','192.000.2.1','2001:0DB8::10'):
            with self.subTest(ip=ip):
                value = copy.deepcopy(self.profile); value['database']['host_ip'] = ip
                self.reject(value, 'SUPPLY_IP_NOT_CANONICAL')

    def test_mixed_source_address_families_rejected(self):
        self.profile['runtime']['source_ip'] = '2001:db8::30'; self.reject(code='SUPPLY_SOURCE_BOUNDARY_CONFLICT')

    def test_tls_identity_rules(self):
        for name in ('DB.example.invalid','bad_name','-db.example','db..example','db.example.','db.example\n','https://db.example.invalid'):
            with self.subTest(name=name):
                value = copy.deepcopy(self.profile); value['tls']['server_name'] = name; self.reject(value)
        for name in ('192.0.2.10','2001:db8::10','db.example.invalid'):
            value = copy.deepcopy(self.profile); value['tls']['server_name'] = name
            contract.parse_supply_profile(json.dumps(value).encode())

    def test_ports_database_schema_and_hashes(self):
        for port in (0,65536,True,'5432'):
            value = copy.deepcopy(self.profile); value['database']['port'] = port; self.reject(value)
        for schema in (7,8,10,'9',True):
            value = copy.deepcopy(self.profile); value['database']['target_schema_version'] = schema; self.reject(value)
        for digest in ('a'*63,'A'*64,'sha256:'+'a'*64,'a'*64+'\n'):
            value = copy.deepcopy(self.profile); value['tls']['expected_ca_sha256'] = digest; self.reject(value)

    def test_path_syntax_absolute_clean_and_non_uri(self):
        for path in ('/','relative/key','/srv/../control','/srv/./control','//srv/control','/srv//control','/srv/control/','/srv/control\n','postgres://synthetic:secret@db/vms_camera','/srv/%2e%2e/control','/srv/key*'):
            with self.subTest(path=path):
                value = copy.deepcopy(self.profile); value['authority']['host_directory'] = path; self.reject(value)

    def test_authority_and_lock_receipt_outside_project_data_key_and_snapshot_roots(self):
        fences = [self.profile['project_root'], self.profile['database']['host_data_directory'],
            str(Path(self.profile['key_supply']['source_file']).parent),
            self.profile['key_supply']['runtime_directory']['host_path'],
            self.profile['declared_snapshot_roots'][0]]
        for field in ('host_directory','lock_receipt_host_file'):
            for fence in fences:
                with self.subTest(field=field, fence=fence):
                    value = copy.deepcopy(self.profile); value['authority'][field] = fence+'/synthetic-control'
                    self.reject(value, 'SUPPLY_AUTHORITY_SNAPSHOT_OVERLAP')

    def test_authority_ancestor_of_snapshot_is_also_rejected(self):
        self.profile['authority']['host_directory'] = '/srv'; self.reject(code='SUPPLY_AUTHORITY_SNAPSHOT_OVERLAP')

    def test_path_prefix_is_not_directory_ancestry(self):
        self.profile['authority']['host_directory'] = self.profile['project_root']+'-control'
        contract.parse_supply_profile(json.dumps(self.profile).encode())

    def test_lock_receipt_cannot_live_inside_replaceable_authority(self):
        self.profile['authority']['lock_receipt_host_file'] = self.profile['authority']['host_directory']+'/lock-receipt.json'
        self.reject(code='SUPPLY_LOCK_RECEIPT_INSIDE_AUTHORITY')

    def test_runtime_key_copy_cannot_relabel_source_directory(self):
        self.profile['key_supply']['runtime_directory']['host_path'] = str(Path(self.profile['key_supply']['source_file']).parent)
        self.reject(code='SUPPLY_KEY_SOURCE_COPY_OVERLAP')

    def test_database_hba_and_tls_controls_outside_host_and_container_data(self):
        for name in ('hba_file','server_certificate_file','server_private_key_file'):
            for kind, root in (('host_path',self.profile['database']['host_data_directory']),
                               ('container_path',self.profile['database']['container_data_directory'])):
                with self.subTest(name=name,kind=kind):
                    value = copy.deepcopy(self.profile); value['database'][name][kind] = root+'/synthetic-file'
                    self.reject(value, 'SUPPLY_DATABASE_CONTROL_INSIDE_DATA')

    def test_database_controls_cannot_rewind_with_project_or_declared_snapshots(self):
        for root in (self.profile['project_root'], self.profile['declared_snapshot_roots'][0],
                     self.profile['key_supply']['runtime_directory']['host_path']):
            with self.subTest(root=root):
                value = copy.deepcopy(self.profile)
                value['database']['hba_file']['host_path'] = root+'/pg_hba.conf'
                self.reject(value, 'SUPPLY_DATABASE_CONTROL_SNAPSHOT_OVERLAP')

    def test_runtime_host_file_cannot_hide_inside_authority_or_key_directory(self):
        for directory in (self.profile['authority']['host_directory'],
                          self.profile['key_supply']['runtime_directory']['host_path']):
            with self.subTest(directory=directory):
                value = copy.deepcopy(self.profile)
                value['runtime']['writer_dsn_file']['host_path'] = directory+'/writer-dsn'
                self.reject(value, 'SUPPLY_HOST_PATH_OVERLAP')

    def test_maintenance_private_files_cannot_be_runtime_host_mounts(self):
        self.profile['runtime']['writer_dsn_file']['host_path'] = self.profile['maintenance']['client_private_key_file']['host_path']
        self.reject(code='SUPPLY_HOST_MOUNT_ALIAS')

    def test_separate_role_files_required(self):
        self.profile['runtime']['writer_dsn_file']['host_path'] = self.profile['runtime']['budget_dsn_file']['host_path']
        self.reject(code='SUPPLY_HOST_MOUNT_ALIAS')

    def test_mount_parent_child_shadowing_rejected(self):
        self.profile['runtime']['writer_dsn_file']['container_path'] = self.profile['key_supply']['runtime_directory']['container_path']+'/dsn'
        self.reject(code='SUPPLY_CONTAINER_MOUNT_OVERLAP')

    def test_mounts_permissions_capabilities_and_environment_are_fixed_policies(self):
        for section, field, value in (('runtime','rootfs_read_only',False), ('runtime','linux_capabilities',['CAP_DAC_OVERRIDE']),
                ('runtime','no_new_privileges',False), ('runtime','ambient_pg_environment','inherit'),
                ('key_supply','runtime_directory_mode','0755'), ('key_supply','runtime_file_mode','0644'),
                ('authority','runtime_mount_read_only',False), ('authority','maintenance_mount_read_only',True)):
            with self.subTest(section=section,field=field):
                profile = copy.deepcopy(self.profile); profile[section][field] = value; self.reject(profile)
        self.profile['runtime']['writer_dsn_file']['read_only'] = False; self.reject()

    def test_snapshot_roots_are_required_bounded_unique_and_explicit(self):
        for roots in ([], ['/srv/snapshot']*2, ['/srv/snapshot-'+str(i) for i in range(33)], ['/'], ['relative']):
            with self.subTest(roots=roots):
                value = copy.deepcopy(self.profile); value['declared_snapshot_roots'] = roots; self.reject(value)

    def test_parser_does_not_read_referenced_files_or_touch_environment(self):
        raw = json.dumps(self.profile).encode()
        with patch.object(io, 'open', side_effect=AssertionError('referenced-file IO forbidden')):
            self.assertEqual(contract.parse_supply_profile(raw), self.profile)

    def test_current_api_is_unchanged_without_supply_or_credential_routes(self):
        api = json.loads((ROOT.parent/'openapi.json').read_text())
        self.assertEqual(api['info']['version'], '0.7.0-device-delete')
        for path in api['paths']:
            self.assertNotIn('credential', path); self.assertNotIn('admission', path); self.assertNotIn('supply', path)


if __name__ == '__main__': unittest.main()
