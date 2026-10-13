"""Incomplete plan and protected, create-only publication; all inputs synthetic."""
import builtins
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import prepare_camera_credential_supply_review as review
import test_inspect_camera_credential_supply_facts as legacy

SOURCE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SOURCE/'src/platform/camera/api/planned'))
import credential_supply_contract as contract


def fixture(root):
    legacy.fixture(root)
    p = root/'project-manifest.json'; manifest = json.loads(p.read_text())
    name = 'src/infra/tools/prepare_camera_credential_supply_review.py'
    target = root/name; target.write_bytes((SOURCE/name).read_bytes())
    manifest['files'][name] = review.facts.sha(target)
    manifest.update(credential_production_supply_facts_server_verified=True,
        validated_credential_production_supply_facts_project_sha256=review.ACCEPTED_FACTS,
        credential_production_supply_review_implemented=True)
    p.write_text(json.dumps(manifest))


class SupplyReviewTest(unittest.TestCase):
    read_api = legacy.SupplyFactsTest.read_api

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'; self.root.mkdir(); fixture(self.root)
        api = patch.object(review.facts.inventory, 'read_api', side_effect=self.read_api)
        api.start(); self.addCleanup(api.stop)
        docker = patch.object(review.facts, 'FactsDocker', side_effect=lambda root: legacy.FakeDocker(root))
        docker.start(); self.addCleanup(docker.stop)

    def prepare(self, apply=False): return review.prepare_review(self.root, apply=apply)

    def generated(self):
        value = self.prepare(True)
        return value, Path(value['review_file']), json.loads(Path(value['review_file']).read_text())

    def rejected(self, code):
        with self.assertRaisesRegex(review.ActivationError, '^'+code+'$'): self.prepare(True)

    def test_preview_does_not_create_review_file(self):
        value = self.prepare()
        self.assertEqual(value['status'], 'planned'); self.assertIsNone(value['review_file'])
        self.assertFalse(value['review_file_created']); self.assertFalse((self.root/review.DIRECTORY).exists())
        self.assertEqual(value['plan_state'], 'incomplete'); self.assertFalse(value['activation_allowed'])

    def test_every_required_schema_leaf_is_present_without_example_defaults(self):
        _, _, value = self.generated(); draft = value['partial_supply_plan']
        schema = json.loads((self.root/review.SCHEMA).read_text())
        empty, policies = review.schema_template(schema)
        def shape(item): return {k: shape(v) for k, v in item.items()} if isinstance(item, dict) else None
        self.assertEqual(shape(draft), shape(empty)); self.assertEqual(value['contract_policy_fields'], policies)
        self.assertIsNone(draft['maintenance']['uid']); self.assertIsNone(draft['maintenance']['source_ip'])
        self.assertIsNone(draft['tls']['server_name']); self.assertIsNone(draft['declared_snapshot_roots'])
        self.assertIsNone(draft['key_supply']['expected_source_sha256'])
        self.assertIsNone(draft['tls']['expected_ca_sha256'])
        self.assertEqual(draft['key_supply']['runtime_directory_mode'], '0500')
        self.assertEqual(draft['tls']['mode'], 'verify-full')

    def test_incomplete_review_and_partial_profile_rejected_by_supply_contract(self):
        _, _, value = self.generated()
        for payload in (value, value['partial_supply_plan']):
            with self.subTest(kind=payload.get('document_kind')), self.assertRaises(contract.SupplyContractError):
                contract.parse_supply_profile(json.dumps(payload).encode())
        self.assertFalse(value['review_is_deployable']); self.assertFalse(value['supply_plan_created'])

    def test_unverified_uid_ip_and_volume_values_stay_candidates(self):
        _, _, value = self.generated(); draft = value['partial_supply_plan']
        for group, name in (('database', 'server_uid'), ('database', 'host_ip'), ('database', 'host_data_directory'),
                            ('runtime', 'uid'), ('runtime', 'gid'), ('runtime', 'source_ip'), ('authority', 'runtime_gid')):
            self.assertIsNone(draft[group][name])
        candidates = {x['field']: x for x in value['observation_candidates']}
        self.assertEqual(candidates['database.server_uid']['observed_value'], [{'uid': 999, 'gid': 999}])
        self.assertTrue(all(x['verification_required'] for x in candidates.values()))
        self.assertEqual(candidates['runtime.source_ip']['observed_value']['ipv4'], '172.22.0.2/16')

    def test_verified_host_metadata_is_linked_without_reading_key_material(self):
        _, _, value = self.generated(); draft = value['partial_supply_plan']
        self.assertEqual(draft['project_root'], str(self.root))
        self.assertEqual(draft['key_supply']['source_owner_uid'], os.getuid())
        self.assertEqual(draft['key_supply']['source_file'], str(self.root/review.facts.inventory.KEY))
        self.assertEqual(draft['inventory_basis']['source_sha256'], review.checked_source(self.root))
        self.assertFalse(value['production_key_material_read']); self.assertFalse(value['production_keys_loaded'])

    def test_missing_key_metadata_stays_unknown_without_creating_bundle(self):
        path = self.root/review.facts.inventory.KEY; path.unlink()
        _, _, value = self.generated(); key = value['partial_supply_plan']['key_supply']
        self.assertIsNone(key['source_owner_uid']); self.assertIsNone(key['source_file'])
        self.assertIn('HOST_KEY_BUNDLE_MISSING', value['registry_basis']['blockers']); self.assertFalse(path.exists())

    def test_no_key_or_other_supply_contents_are_opened(self):
        def guarded(original):
            def call(path, *args, **kwargs):
                self.assertNotIn(str(path), ('key-bundle.json', str(self.root/review.facts.inventory.KEY)))
                self.assertFalse(str(path).startswith('/var/lib/docker'))
                return original(path, *args, **kwargs)
            return call
        with patch.object(os, 'open', side_effect=guarded(os.open)), \
                patch.object(io, 'open', side_effect=guarded(io.open)), \
                patch.object(builtins, 'open', side_effect=guarded(builtins.open)):
            self.prepare(True)

    def test_source_gate_requires_server_facts_acceptance_before_queries(self):
        p = self.root/'project-manifest.json'; m = json.loads(p.read_text())
        m['credential_production_supply_facts_server_verified'] = False; p.write_text(json.dumps(m))
        with patch.object(review.facts, 'FactsDocker') as docker:
            self.rejected('ACCEPTED_SUPPLY_FACTS_REQUIRED'); docker.assert_not_called()

    def test_modified_review_source_rejected_before_queries(self):
        (self.root/'src/infra/tools/prepare_camera_credential_supply_review.py').write_text('SYNTHETIC_EDIT')
        with patch.object(review.facts, 'FactsDocker') as docker:
            self.rejected('SOURCE_FILE_CHANGED'); docker.assert_not_called()

    def test_previously_written_facts_report_is_never_used_as_fresh_input(self):
        path = self.root/review.facts.REPORT; path.write_text('SYNTHETIC_INVALID_OLD_REPORT'); path.chmod(0o600)
        value = self.prepare(True)
        self.assertEqual(value['status'], 'prepared'); self.assertEqual(path.read_text(), 'SYNTHETIC_INVALID_OLD_REPORT')

    def test_stale_or_activated_observation_cannot_enter_draft(self):
        original = review.facts.inspect_facts
        for change in ({'checked_revision': 'a'*64}, {'activation_allowed': True}, {'production_keys_loaded': True}):
            with self.subTest(change=change):
                def changed(root, docker): return {**original(root, docker), **change}
                with patch.object(review.facts, 'inspect_facts', side_effect=changed):
                    self.rejected('SUPPLY_REVIEW_FRESH_FACTS_REQUIRED')
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_report_and_directory_modes_and_name_match_content_hash(self):
        summary, path, _ = self.generated()
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600); self.assertEqual(path.stat().st_nlink, 1)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary['review_sha256'], digest); self.assertEqual(path.name, 'review-'+digest+'.json')

    def test_repeat_preserves_content_mtime_and_protected_state(self):
        protected = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in
            (self.root/review.facts.inventory.KEY, self.root/'.env', self.root/review.facts.inventory.RECEIPT)}
        value, path, data = self.generated(); before = path.read_bytes(), path.stat().st_mtime_ns
        again = self.prepare(True); self.assertEqual(again['status'], 'already_prepared')
        self.assertFalse(again['review_file_created']); self.assertEqual(again['review_file'], str(path))
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        for p, state in protected.items(): self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), state)
        self.assertTrue(all(data[k] is False for k in review.NO_CHANGES))

    def test_user_edit_in_generated_destination_is_preserved(self):
        _, path, _ = self.generated(); path.write_text('SYNTHETIC_USER_EDIT')
        self.rejected('SUPPLY_REVIEW_EXISTING_CONTENT_CONFLICT'); self.assertEqual(path.read_text(), 'SYNTHETIC_USER_EDIT')

    def test_existing_symlink_and_hardlink_rejected_without_reading_target(self):
        _, path, _ = self.generated(); path.unlink(); path.symlink_to(self.root/'.env')
        self.rejected('SYMLINK_PATH_REJECTED'); path.unlink()
        other = self.root/'synthetic-other-file'; other.write_bytes(b'SYNTHETIC_OTHER'); other.chmod(0o600)
        os.link(other, path)
        self.rejected('SUPPLY_REVIEW_FILE_OWNER_MODE_OR_LINK_REJECTED')

    def test_wrong_report_permissions_rejected_without_repair(self):
        _, path, _ = self.generated(); path.chmod(0o640)
        self.rejected('SUPPLY_REVIEW_FILE_OWNER_MODE_OR_LINK_REJECTED')
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_wrong_directory_permissions_rejected_without_repair(self):
        _, path, _ = self.generated(); path.parent.chmod(0o750)
        self.rejected('PRIVATE_DIRECTORY_MUST_BE_OWNED_AND_MODE_0700')
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o750)

    def test_changed_key_metadata_cannot_publish_success(self):
        docker = legacy.FakeDocker(self.root)
        docker.after_first_network = lambda: (self.root/review.facts.inventory.KEY).write_bytes(b'SYNTHETIC_CHANGE')
        with patch.object(review.facts, 'FactsDocker', return_value=docker):
            self.rejected('KEY_METADATA_CHANGED_DURING_INSPECTION')
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_transient_worker_count_does_not_change_generated_review(self):
        first, path, _ = self.generated()
        docker = legacy.FakeDocker(self.root)
        docker.top[legacy.legacy.DB_ID] += b'104 999 999\n'
        with patch.object(review.facts, 'FactsDocker', return_value=docker): second = self.prepare(True)
        self.assertEqual(second['status'], 'already_prepared'); self.assertEqual(second['review_sha256'], first['review_sha256'])

    def test_new_observation_creates_new_version_without_overwriting_old_review(self):
        first, path, _ = self.generated(); body = path.read_bytes()
        docker = legacy.FakeDocker(self.root); docker.db['Mounts'][0]['Source'] = '/synthetic/other-data'
        with patch.object(review.facts, 'FactsDocker', return_value=docker): second = self.prepare(True)
        self.assertEqual(second['status'], 'prepared'); self.assertNotEqual(second['review_file'], str(path))
        self.assertEqual(path.read_bytes(), body)

    def test_publish_race_preserves_concurrent_file_and_cleans_temporary(self):
        def race(src, dest, **kwargs):
            Path(dest).write_bytes(b'SYNTHETIC_CONCURRENT_EDIT'); Path(dest).chmod(0o600)
            raise FileExistsError()
        with patch.object(os, 'link', side_effect=race): self.rejected('SUPPLY_REVIEW_EXISTING_CONTENT_CONFLICT')
        directory = self.root/review.DIRECTORY
        self.assertEqual(len(list(directory.iterdir())), 1)
        self.assertEqual(next(directory.iterdir()).read_bytes(), b'SYNTHETIC_CONCURRENT_EDIT')

    def test_oversized_existing_file_is_rejected_without_repair(self):
        _, path, _ = self.generated(); path.write_bytes(b'x'*65537)
        self.rejected('SUPPLY_REVIEW_EXISTING_FILE_TOO_LARGE'); self.assertEqual(path.stat().st_size, 65537)

    def test_failed_refresh_identifies_stage_and_publishes_no_review(self):
        docker = legacy.FakeDocker(self.root)
        docker.top[legacy.legacy.API_ID] = b'PID EUID EGID\n101 BAD BAD\n'
        with patch.object(review.facts, 'FactsDocker', return_value=docker):
            with self.assertRaises(review.ActivationError) as caught: self.prepare(True)
        self.assertEqual(caught.exception.inspection_stage, 'process_identity_observation')
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_stdout_and_file_do_not_include_secret_bytes_or_peer_names(self):
        summary, path, _ = self.generated(); text = json.dumps(summary)+path.read_text()
        self.assertNotIn(legacy.legacy.TOKEN, text); self.assertNotIn(legacy.KEY_MARKER, text)
        self.assertNotIn('process_count', text); self.assertNotIn('pids', text)


class ReviewTemplateTest(unittest.TestCase):
    def test_external_and_cyclic_schema_refs_rejected(self):
        for schema in ({'$ref': 'https://example.invalid/schema'},
                       {'$ref': '#/$defs/Loop', '$defs': {'Loop': {'$ref': '#/$defs/Loop'}}}):
            with self.subTest(schema=schema), self.assertRaises(review.ActivationError): review.schema_template(schema)

    def test_empty_capabilities_is_fixed_policy_and_required_array_is_unknown(self):
        value, policies = review.schema_template({'type': 'object', 'required': ['caps', 'snapshots'],
            'properties': {'caps': {'type': 'array', 'maxItems': 0},
                           'snapshots': {'type': 'array', 'minItems': 1}}})
        self.assertEqual(value, {'caps': [], 'snapshots': None}); self.assertEqual(policies, ['caps'])
        self.assertEqual(review.unresolved_fields(value), ['snapshots'])

    def test_review_size_is_bounded(self):
        with self.assertRaisesRegex(review.ActivationError, '^SUPPLY_REVIEW_TOO_LARGE$'):
            review.encoded_review({'synthetic': 'x'*65537})


if __name__ == '__main__': unittest.main()
