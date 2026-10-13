"""Fresh metadata, incomplete backup scopes and private create-only publication."""
import builtins
import copy
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import prepare_camera_credential_backup_review as review
import test_inspect_camera_database_storage_mapping as legacy

SOURCE = Path(__file__).resolve().parents[3]


def fixture(root):
    legacy.fixture(root)
    path = root/'project-manifest.json'; manifest = json.loads(path.read_text())
    names = {review.SOURCE, review.TOOLS+'prepare_camera_credential_supply_review.py',
        *(review.TOOLS+name for name, _, _ in review.CODE_LOCATIONS)}
    for name in names:
        target = root/name; target.write_bytes((SOURCE/name).read_bytes())
        manifest['files'][name] = review.mapping.sha(target)
    manifest.update(camera_database_storage_mapping_server_verified=True,
        validated_camera_database_storage_mapping_project_sha256=review.ACCEPTED_MAPPING,
        credential_production_backup_review_implemented=True)
    path.write_text(json.dumps(manifest))


class BackupReviewTest(unittest.TestCase):
    read_api = legacy.MappingInspectionTest.read_api

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'project'; self.root.mkdir(); fixture(self.root)
        self.docker = legacy.FakeDocker(self.root); self.reader = legacy.FakeReader(self.docker)
        for target, field, value in ((review.mapping.inventory, 'read_api', self.read_api),
            (review.mapping.layout, 'LayoutDocker', lambda root: self.docker),
            (review.mapping.topology, 'MountReader', lambda: self.reader),
            (review.mapping.topology, 'AssistedMountReader', lambda root: self.reader)):
            context = patch.object(target, field, side_effect=value)
            context.start(); self.addCleanup(context.stop)

    def prepare(self, apply=False, privileged=False):
        return review.prepare_review(self.root, apply=apply, privileged=privileged)

    def generated(self):
        summary = self.prepare(True); path = Path(summary['review_file'])
        return summary, path, json.loads(path.read_text())

    def rejected(self, code):
        with self.assertRaisesRegex(review.ActivationError, '^'+code+'$'): self.prepare(True)

    def test_preview_refreshes_actual_mapping_without_review_file(self):
        summary = self.prepare()
        self.assertEqual(summary['status'], 'planned'); self.assertTrue(summary['current_storage_verified'])
        self.assertFalse(summary['review_file_created']); self.assertIsNone(summary['review_file'])
        self.assertFalse((self.root/review.DIRECTORY).exists())
        self.assertEqual(self.docker.catalog_calls, 6); self.assertEqual(self.docker.metadata_calls, 6)
        self.assertTrue(all(summary[field] is False for field in review.NO_CHANGES))

    def test_full_backup_inventory_and_exclusions_remain_unknown(self):
        summary, _, value = self.generated()
        required = value['required_declarations']
        self.assertEqual(len(value['known_code_locations']), 8)
        self.assertEqual(len(summary['unresolved_fields']), 22)
        self.assertIsNone(required['declared_snapshot_roots'])
        self.assertIsNone(required['backup_jobs']); self.assertIsNone(required['restore_jobs'])
        self.assertIsNone(required['snapshot_jobs'])
        self.assertEqual(set(required['external_controls']), set(review.CONTROL_FIELDS))
        self.assertTrue(all(item is None for item in required['external_controls'].values()))
        self.assertEqual(value['unresolved_backup_topology'], review.mapping.UNRESOLVED)
        self.assertTrue(all(value[field] is False for field in review.NO_CHANGES))
        self.assertEqual(summary['readiness'], 'blocked'); self.assertFalse(summary['activation_allowed'])

    def test_code_declared_locations_are_candidates_without_existence_or_physical_claim(self):
        _, _, value = self.generated()
        self.assertEqual(sum(row['purpose'] == 'database-dump-destination'
            for row in value['known_code_locations']), 7)
        for row in value['known_code_locations']:
            self.assertEqual(row['basis'], 'tracked-code-declaration-only')
            self.assertFalse(row['existence_verified']); self.assertFalse(row['physical_path_verified'])
            self.assertFalse(row['operator_inventory_inclusion_reviewed'])
        self.assertFalse(value['project_recursive_copy_scope_candidate']['operator_job_declared'])
        self.assertFalse(value['key_source_file_reference']['key_material_integrity_verified'])

    def test_current_mapping_uses_fresh_exact_metadata_without_private_signatures(self):
        summary, path, value = self.generated()
        self.assertEqual(value['current_storage']['basis'], 'fresh-fixed-path-metadata-inspection')
        for name, host, container in zip(('pgdata', 'wal'), review.mapping.HOSTS, review.mapping.PATHS):
            row = value['current_storage']['mapping'][name]
            self.assertEqual((row['host_path'], row['container_path']), (host, container))
            self.assertTrue(row['same_directory_identity_verified']); self.assertTrue(row['host_path_verified'])
        self.assertEqual(value['checked_revision'], review.checked_source(self.root))
        self.assertEqual(value['accepted_mapping_revision'], review.ACCEPTED_MAPPING)
        text = json.dumps(summary)+path.read_text()
        for marker in (legacy.TOKEN, legacy.legacy.DB_ID, '"signature":', '"pid":', '"inode":', '"device":'):
            self.assertNotIn(marker, text)

    def test_supply_contract_rejects_new_review_as_a_deployable_plan(self):
        _, _, value = self.generated()
        sys.path.insert(0, str(SOURCE/'src/platform/camera/api/planned'))
        import credential_supply_contract as contract
        for body in (value, value['required_declarations']):
            with self.assertRaises(contract.SupplyContractError): contract.parse_supply_profile(json.dumps(body).encode())
        self.assertFalse(value['review_is_deployable']); self.assertFalse(value['supply_plan_created'])

    def test_accepted_server_mapping_and_implemented_flag_required_before_queries(self):
        path = self.root/'project-manifest.json'; original = json.loads(path.read_text())
        for field, value in (('camera_database_storage_mapping_server_verified', False),
            ('validated_camera_database_storage_mapping_project_sha256', 'a'*64),
            ('credential_production_backup_review_implemented', False)):
            with self.subTest(field=field):
                path.write_text(json.dumps({**original, field: value}))
                self.rejected('ACCEPTED_PHYSICAL_MAPPING_REQUIRED')
                self.assertEqual(self.docker.calls, [])
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_missing_tracked_backup_code_is_rejected_before_queries(self):
        path = self.root/'project-manifest.json'; manifest = json.loads(path.read_text())
        del manifest['files'][review.TOOLS+'activate_camera_sources.py']; path.write_text(json.dumps(manifest))
        self.rejected('BACKUP_REVIEW_SOURCE_MANIFEST_INCOMPLETE'); self.assertEqual(self.docker.calls, [])

    def test_source_edit_is_rejected_before_query_or_publication(self):
        (self.root/review.SOURCE).write_text(legacy.TOKEN)
        self.rejected('SOURCE_FILE_CHANGED'); self.assertEqual(self.docker.calls, [])

    def test_changed_code_declaration_cannot_publish_guessed_location(self):
        path = self.root/(review.TOOLS+'activate_camera_sources.py')
        path.write_text(path.read_text().replace('var/camera/source-activation-backups', 'var/camera/other-backups'))
        manifest_path = self.root/'project-manifest.json'; manifest = json.loads(manifest_path.read_text())
        manifest['files'][path.relative_to(self.root).as_posix()] = review.mapping.sha(path)
        manifest_path.write_text(json.dumps(manifest))
        self.rejected('BACKUP_REVIEW_CODE_DECLARATION_CHANGED')
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_stale_parent_reports_are_never_read_or_replaced(self):
        parents = (review.mapping.REPORT, review.mapping.layout.REPORT,
            review.mapping.topology.REPORT, review.publication.facts.REPORT)
        for relative in parents:
            path = self.root/relative; path.write_text('SYNTHETIC_STALE_REPORT'); path.chmod(0o600)
        self.generated()
        for relative in parents: self.assertEqual((self.root/relative).read_text(), 'SYNTHETIC_STALE_REPORT')

    def test_key_backup_and_external_reference_contents_are_not_opened_or_listed(self):
        key = self.root/review.mapping.inventory.KEY
        forbidden = [str(key), *(str(self.root/relative) for _, relative, _ in review.CODE_LOCATIONS)]
        def guarded(original):
            def call(path, *args, **kwargs):
                if not isinstance(path, int):
                    text = os.fspath(path)
                    self.assertFalse(any(text == name or text.startswith(name+'/') for name in forbidden), text)
                return original(path, *args, **kwargs)
            return call
        with patch.object(os, 'open', side_effect=guarded(os.open)), \
            patch.object(builtins, 'open', side_effect=guarded(builtins.open)), \
            patch.object(io, 'open', side_effect=guarded(io.open)), \
            patch.object(os, 'listdir', side_effect=AssertionError('directory listing forbidden')):
            self.generated()

    def test_initial_host_metadata_unavailable_creates_no_review(self):
        self.reader.errors[review.mapping.HOSTS[1]] = OSError(errno.EACCES, legacy.TOKEN)
        summary = self.prepare(True)
        self.assertEqual(summary['status'], 'blocked'); self.assertFalse(summary['current_storage_verified'])
        self.assertFalse(summary['review_available']); self.assertFalse((self.root/review.DIRECTORY).exists())
        self.assertNotIn(legacy.TOKEN, json.dumps(summary))

    def test_failed_live_mapping_publishes_no_success_review(self):
        self.reader.values[review.mapping.HOSTS[1]]['signature'] = \
            self.reader.values[review.mapping.HOST]['signature']+((1, 9999, 999, 999, 0o40700),)
        with self.assertRaises(review.ActivationError) as caught: self.prepare(True)
        self.assertEqual(caught.exception.inspection_stage, 'physical_mapping_comparison')
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_new_archive_profile_or_tablespace_requires_review_without_file(self):
        self.docker.catalog_value['archive_mode'] = 'on'
        self.rejected('CURRENT_STORAGE_LAYOUT_REVIEW_REQUIRED')
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_source_changed_after_inspection_is_rejected(self):
        original = review.mapping.inspect_mapping
        def changed(root, docker, factory):
            result = original(root, docker, factory)
            path = root/'project-manifest.json'; value = json.loads(path.read_text())
            value['synthetic_unreviewed_change'] = True; path.write_text(json.dumps(value))
            return result
        with patch.object(review.mapping, 'inspect_mapping', side_effect=changed):
            self.rejected('INSPECTION_INPUT_CHANGED')
        self.assertFalse((self.root/review.DIRECTORY).exists())

    def test_new_review_directory_and_exact_file_are_private(self):
        summary, path, _ = self.generated()
        self.assertEqual(path.parent, self.root/review.DIRECTORY)
        self.assertFalse((self.root/review.publication.DIRECTORY).exists())
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(path.name, 'review-'+summary['review_sha256']+'.json')

    def test_idempotent_retry_preserves_environment_keys_receipt_and_prior_review(self):
        protected = {path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode) for path in (
            self.root/'.env', self.root/review.mapping.inventory.KEY, self.root/review.mapping.inventory.RECEIPT)}
        _, path, _ = self.generated(); before = path.read_bytes(), path.stat().st_mtime_ns
        again = self.prepare(True)
        self.assertEqual(again['status'], 'already_prepared'); self.assertFalse(again['review_file_created'])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        for target, expected in protected.items():
            self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns, target.stat().st_mode), expected)

    def test_source_revision_change_keeps_old_review_and_creates_new_version(self):
        first, path, _ = self.generated(); body = path.read_bytes()
        manifest_path = self.root/'project-manifest.json'; manifest = json.loads(manifest_path.read_text())
        manifest['synthetic_review_revision'] = 2; manifest_path.write_text(json.dumps(manifest))
        second = self.prepare(True)
        self.assertNotEqual(second['review_sha256'], first['review_sha256'])
        self.assertEqual(second['status'], 'prepared'); self.assertEqual(path.read_bytes(), body)

    def test_user_edit_in_content_named_file_is_preserved(self):
        _, path, _ = self.generated(); path.write_text('SYNTHETIC_USER_EDIT')
        self.rejected('SUPPLY_REVIEW_EXISTING_CONTENT_CONFLICT'); self.assertEqual(path.read_text(), 'SYNTHETIC_USER_EDIT')

    def test_symlink_and_hardlink_destinations_are_rejected(self):
        _, path, _ = self.generated(); path.unlink(); path.symlink_to(self.root/'.env')
        self.rejected('SYMLINK_PATH_REJECTED'); path.unlink()
        other = self.root/'other'; other.write_bytes(b'SYNTHETIC_OTHER'); other.chmod(0o600); os.link(other, path)
        self.rejected('SUPPLY_REVIEW_FILE_OWNER_MODE_OR_LINK_REJECTED')

    def test_wrong_directory_and_file_modes_are_not_repaired(self):
        _, path, _ = self.generated(); path.chmod(0o640)
        self.rejected('SUPPLY_REVIEW_FILE_OWNER_MODE_OR_LINK_REJECTED')
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        path.chmod(0o600); path.parent.chmod(0o750)
        self.rejected('PRIVATE_DIRECTORY_MUST_BE_OWNED_AND_MODE_0700')
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o750)

    def test_publish_race_preserves_concurrent_edit(self):
        def race(source, destination, **kwargs):
            Path(destination).write_text('SYNTHETIC_CONCURRENT_EDIT'); Path(destination).chmod(0o600)
            raise FileExistsError()
        with patch.object(review.publication.os, 'link', side_effect=race):
            self.rejected('SUPPLY_REVIEW_EXISTING_CONTENT_CONFLICT')
        files = list((self.root/review.DIRECTORY).iterdir())
        self.assertEqual(len(files), 1); self.assertEqual(files[0].read_text(), 'SYNTHETIC_CONCURRENT_EDIT')

    def test_oversized_existing_review_is_not_read_or_repaired(self):
        _, path, _ = self.generated(); path.write_bytes(b'x'*(review.publication.MAX_REVIEW_BYTES+1))
        self.rejected('SUPPLY_REVIEW_EXISTING_FILE_TOO_LARGE')
        self.assertEqual(path.stat().st_size, review.publication.MAX_REVIEW_BYTES+1)

    def test_privileged_wrapper_uses_existing_fixed_observer(self):
        with patch.object(review.os, 'geteuid', return_value=1006), \
            patch.object(review.mapping.topology, 'AssistedMountReader', return_value=self.reader) as assisted:
            summary = self.prepare(privileged=True)
        self.assertTrue(summary['privileged_directory_observer_requested']); assisted.assert_called()
        self.assertTrue(set(self.reader.calls) & set(review.mapping.HOSTS))

    def test_root_guard_runs_before_lock_or_docker(self):
        with patch.object(review.os, 'geteuid', return_value=0), patch.object(review, 'activation_lock') as lock:
            with self.assertRaisesRegex(review.ActivationError, '^RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER$'):
                self.prepare(True, privileged=True)
            lock.assert_not_called(); self.assertEqual(self.docker.calls, [])

    def test_cli_option_routing_and_safe_failure_output(self):
        with patch.object(sys, 'argv', ['prepare', '--apply', '--privileged-directory-metadata']), \
            patch.object(review, 'prepare_review', return_value={}) as prepare, patch.object(sys, 'stdout', io.StringIO()):
            self.assertEqual(review.main(), 0)
            self.assertEqual(prepare.call_args.kwargs, {'apply': True, 'privileged': True})
        error = review.ActivationError('SYNTHETIC_SECRET\n'+legacy.TOKEN)
        error.inspection_stage = 'backup_review_publish'
        with patch.object(sys, 'argv', ['prepare']), patch.object(review, 'prepare_review', side_effect=error), \
            patch.object(sys, 'stderr', io.StringIO()) as stream:
            self.assertEqual(review.main(), 1)
        self.assertNotIn(legacy.TOKEN, stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())['failed_stage'], 'backup_review_publish')


class BuildBoundaryTest(unittest.TestCase):
    def test_review_size_is_bounded(self):
        with self.assertRaisesRegex(review.ActivationError, '^BACKUP_REVIEW_TOO_LARGE$'):
            review.encoded_review({'synthetic': 'x'*(review.publication.MAX_REVIEW_BYTES+1)})

    def test_unknown_review_error_cannot_echo_caller_values(self):
        for prefix in ('BACKUP_REVIEW_', 'SUPPLY_REVIEW_'):
            error = review.ActivationError(prefix+legacy.TOKEN)
            self.assertEqual(review.failure_code(error), 'BACKUP_REVIEW_PREPARATION_UNAVAILABLE')

    def test_stale_or_mutating_proof_cannot_enter_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'project'; root.mkdir(); fixture(root); self.root = root
            docker = legacy.FakeDocker(root); reader = legacy.FakeReader(docker)
            with patch.object(review.mapping.inventory, 'read_api',
                side_effect=lambda *args, **kwargs: legacy.MappingInspectionTest.read_api(self, *args, **kwargs)):
                proof = review.mapping.inspect_mapping(root, docker, lambda: reader)
            revision = proof['checked_revision']
            for change in ({'checked_revision': 'a'*64}, {'activation_allowed': True},
                {'backup_created': True}, {'mapping_readiness': 'blocked'}, {'scope': 'other'}):
                with self.subTest(change=change), self.assertRaisesRegex(review.ActivationError, '^BACKUP_REVIEW_FRESH_MAPPING_REQUIRED$'):
                    review.build_review(root, {**proof, **change}, revision)

    def test_unsupported_public_mapping_fields_cannot_inject_secret_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'project'; root.mkdir(); fixture(root); self.root = root
            docker = legacy.FakeDocker(root); reader = legacy.FakeReader(docker)
            with patch.object(review.mapping.inventory, 'read_api',
                side_effect=lambda *args, **kwargs: legacy.MappingInspectionTest.read_api(self, *args, **kwargs)):
                proof = review.mapping.inspect_mapping(root, docker, lambda: reader)
            proof['mapping']['pgdata']['SYNTHETIC_SECRET_FIELD'] = legacy.TOKEN
            value = review.build_review(root, proof, proof['checked_revision'])
            self.assertNotIn(legacy.TOKEN, json.dumps(value))
            for field, replacement in (('host_path', '/unreviewed'), ('host_path_verified', 1),
                ('privileged_sender_uid_verified', 'yes')):
                changed = copy.deepcopy(proof); changed['mapping']['pgdata'][field] = replacement
                with self.assertRaisesRegex(review.ActivationError, '^BACKUP_REVIEW_FRESH_MAPPING_REQUIRED$'):
                    review.build_review(root, changed, proof['checked_revision'])


if __name__ == '__main__': unittest.main()
