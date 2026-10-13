#!/usr/bin/env python3
"""Prepare an incomplete backup/restore boundary review from fresh fixed-path proof.

No backup/snapshot/job discovery, referenced file IO, installation or activation.
Code-declared locations are candidates, never a complete physical backup inventory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.error import URLError

import inspect_camera_database_storage_mapping as mapping
import prepare_camera_credential_supply_review as publication
from camera_activation import ActivationError, activation_lock

SCOPE = 'camera_credential_backup_boundary_review'
SOURCE = 'src/infra/tools/prepare_camera_credential_backup_review.py'
DIRECTORY = 'var/camera/credential-backup-reviews'
ACCEPTED_MAPPING = '915be4ab56bfef53def591b38b5024920daf745f5525fb35d22f1ca893d1c745'
NO_CHANGES = {**mapping.NO_CHANGES, 'review_is_deployable': False,
    'backup_jobs_discovered': False, 'snapshot_jobs_discovered': False,
    'restore_jobs_discovered': False, 'referenced_backup_locations_opened': False,
    'external_control_exclusion_verified': False, 'paired_database_key_recovery_verified': False}
STAGES = (*mapping.STAGES, 'backup_review_build', 'backup_review_publish')
TOOLS = 'src/infra/tools/'
# These declarations are checked against tracked source literals, never opened
# as directories or treated as existing/current backup jobs.
CODE_LOCATIONS = (
    ('camera_activation.py', 'var/camera/activation-backups', 'database-dump-destination'),
    ('activate_camera_sources.py', 'var/camera/source-activation-backups', 'database-dump-destination'),
    ('activate_camera_source_list.py', 'var/camera/source-list-activation-backups', 'database-dump-destination'),
    ('activate_camera_device_update.py', 'var/camera/device-update-activation-backups', 'database-dump-destination'),
    ('activate_camera_source_update.py', 'var/camera/source-update-activation-backups', 'database-dump-destination'),
    ('activate_camera_source_delete.py', 'var/camera/source-delete-activation-backups', 'database-dump-destination'),
    ('activate_camera_device_delete.py', 'var/camera/device-delete-activation-backups', 'database-dump-destination'),
    ('prepare_camera_credential_key_backup.py', 'var/camera/credential-key-backups', 'key-backup-destination'),
)
CONTROL_FIELDS = (
    'authority_directory', 'stable_lock_receipt_file', 'database_hba_file',
    'database_configuration_files', 'tls_ca_file', 'tls_server_certificate_file',
    'tls_server_private_key_file', 'maintenance_client_certificate_file',
    'maintenance_client_private_key_file', 'maintenance_role_dsn_files',
    'runtime_role_dsn_files',
)
REQUIRED_VERIFICATIONS = (
    'OPERATOR_COMPLETE_BACKUP_SNAPSHOT_AND_RESTORE_JOB_DECLARATIONS',
    'ALL_PHYSICAL_INPUT_OUTPUT_STAGING_AND_REMOTE_DESTINATION_MAPPINGS',
    'NO_SYMLINK_BIND_MOUNT_ALIAS_OR_ANCESTOR_CONTROL_OVERLAP',
    'FILESYSTEM_BLOCK_HOST_AND_VM_SNAPSHOT_SCOPE_AND_EXCLUSIONS',
    'ARCHIVED_WAL_DESTINATIONS_AND_RETENTION_POLICY',
    'COORDINATED_DATABASE_KEY_BACKUP_AND_FENCED_RESTORE_PROCEDURE',
    'FRESH_INDEPENDENT_KEY_INCARNATION_AND_BUDGET_AFTER_RESTORE',
)


def checked_source(root):
    revision = mapping.checked_source(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    mapping.require(manifest.get('camera_database_storage_mapping_server_verified') is True
        and manifest.get('validated_camera_database_storage_mapping_project_sha256') == ACCEPTED_MAPPING
        and manifest.get('credential_production_backup_review_implemented') is True,
        'ACCEPTED_PHYSICAL_MAPPING_REQUIRED')
    names = {SOURCE, TOOLS+'prepare_camera_credential_supply_review.py',
        *(TOOLS+filename for filename, _, _ in CODE_LOCATIONS)}
    mapping.require(names <= manifest['files'].keys(), 'BACKUP_REVIEW_SOURCE_MANIFEST_INCOMPLETE')
    return revision


def code_locations(root):
    """Read tracked code only; do not stat/list/read any referenced backup path."""
    result = []
    for filename, relative, purpose in CODE_LOCATIONS:
        source = TOOLS+filename
        text = (root/source).read_text()
        literal = "BACKUP_DIRECTORY = 'credential-key-backups'" if purpose == 'key-backup-destination' \
            else repr(relative)
        mapping.require(literal in text, 'BACKUP_REVIEW_CODE_DECLARATION_CHANGED')
        result.append({'path': str(root/relative), 'purpose': purpose,
            'source_file': source, 'basis': 'tracked-code-declaration-only',
            'existence_verified': False, 'physical_path_verified': False,
            'operator_inventory_inclusion_reviewed': False})
    return result


def build_review(root, proof, revision):
    mapping.require(proof.get('status') == 'inspected' and proof.get('scope') == mapping.SCOPE
        and proof.get('project') == 'vms-project' and proof.get('checked_revision') == revision
        and proof.get('inspection_completed') is True and proof.get('mapping_readiness') == 'verified'
        and proof.get('individual_host_paths_verified') is True
        and proof.get('current_volume_mount_verified') is True
        and proof.get('current_storage_layout_observed') is True and proof.get('blockers') == []
        and proof.get('activation_allowed') is False and proof.get('production_supply_ready') is False
        and all(proof.get(field) is False for field in mapping.NO_CHANGES),
        'BACKUP_REVIEW_FRESH_MAPPING_REQUIRED')
    rows = proof.get('mapping')
    mapping.require(isinstance(rows, dict) and set(rows) == {'pgdata', 'wal'},
        'BACKUP_REVIEW_FRESH_MAPPING_REQUIRED')
    # Rebuild only supported public metadata; no caller-supplied secrets/paths.
    current = {}
    for name, container, host in zip(('pgdata', 'wal'), mapping.PATHS, mapping.HOSTS):
        row = rows[name]
        expected = {'container_path': container, 'host_path': host,
            'host_path_verified': True, 'host_path_without_symlinks_verified': True,
            'same_directory_identity_verified': True, 'owner_uid': 999, 'owner_gid': 999,
            'permissions': '0700'}
        mapping.require(isinstance(row, dict) and all(
            row.get(k) is v if type(v) is bool else row.get(k) == v for k, v in expected.items())
            and row.get('filesystem_type') in mapping.topology.SUPPORTED_FILESYSTEMS,
            'BACKUP_REVIEW_FRESH_MAPPING_REQUIRED')
        for field in ('privileged_directory_observer_used', 'privileged_sender_uid_verified'):
            mapping.require(type(row.get(field)) is bool, 'BACKUP_REVIEW_FRESH_MAPPING_REQUIRED')
        current[name] = {**expected, 'filesystem_type': row['filesystem_type'],
            'privileged_directory_observer_used': row['privileged_directory_observer_used'],
            'privileged_sender_uid_verified': row['privileged_sender_uid_verified']}
    required = {
        'backup_jobs': None, 'snapshot_jobs': None, 'restore_jobs': None,
        'all_source_roots': None, 'all_backup_destinations': None,
        'all_restore_destinations_and_staging_roots': None,
        'remote_destinations_and_restore_materialization': None,
        'physical_snapshot_scope_and_exclusion_capabilities': None,
        'declared_snapshot_roots': None,
        'archived_wal_destinations_and_retention_policy': None,
        'coordinated_database_key_backup_and_restore_procedure': None,
        'external_controls': {field: None for field in CONTROL_FIELDS},
    }
    return {'format_version': 1, 'document_kind': 'camera-credential-backup-boundary-review',
        'intent': 'review-only-incomplete', 'scope': SCOPE, 'plan_state': 'incomplete',
        'project_root': str(root), 'checked_revision': revision,
        'accepted_mapping_revision': ACCEPTED_MAPPING,
        'current_storage': {'basis': 'fresh-fixed-path-metadata-inspection', 'mapping': current,
            'inspection_is_a_stopped_snapshot': False,
            'profile_requires_in_place_wal_no_custom_tablespace_archive_off': True},
        'known_code_locations': code_locations(root),
        'project_recursive_copy_scope_candidate': {'path': str(root),
            'basis': 'potential-recursive-project-backup-or-restore', 'operator_job_declared': False,
            'physical_path_verified': False},
        'key_source_file_reference': {'path': str(root/mapping.inventory.KEY),
            'basis': 'tracked-inventory-fixed-reference', 'key_material_integrity_verified': False},
        'required_declarations': required,
        'unresolved_fields': publication.unresolved_fields(required),
        'required_verifications': list(REQUIRED_VERIFICATIONS),
        'unresolved_backup_topology': list(mapping.UNRESOLVED),
        'readiness': 'blocked', 'production_supply_ready': False,
        'activation_allowed': False, **NO_CHANGES}


def encoded_review(review):
    body = (json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()
    mapping.require(len(body) <= publication.MAX_REVIEW_BYTES, 'BACKUP_REVIEW_TOO_LARGE')
    return body


def prepare_review(root, *, apply=False, privileged=False):
    if privileged:
        mapping.require(os.geteuid() != 0, 'RUN_STORAGE_INSPECTION_AS_PROJECT_OWNER')
    revision = checked_source(root)
    with activation_lock(root):
        docker = mapping.layout.LayoutDocker(root)
        factory = (lambda: mapping.topology.AssistedMountReader(root)) if privileged else mapping.topology.MountReader
        try:
            proof = mapping.inspect_mapping(root, docker, factory)
            mapping.require(proof['checked_revision'] == revision and checked_source(root) == revision,
                'INSPECTION_INPUT_CHANGED')
            if proof['mapping_readiness'] != 'verified':
                return {'status': 'blocked', 'scope': SCOPE, 'checked_revision': revision,
                    'inspection_completed': True, 'current_storage_verified': False,
                    'review_file_created': False, 'review_available': False, 'review_file': None,
                    'plan_state': 'incomplete', 'blockers': proof['blockers'],
                    'privileged_directory_observer_requested': privileged,
                    'readiness': 'blocked', 'production_supply_ready': False,
                    'activation_allowed': False, **NO_CHANGES}
            docker.inspection_stage = 'backup_review_build'
            review = build_review(root, proof, revision)
            body = encoded_review(review)
            mapping.require(checked_source(root) == revision, 'INSPECTION_INPUT_CHANGED')
            docker.inspection_stage = 'backup_review_publish'
            status, path = publication.publish_review(root, body, directory=DIRECTORY) if apply else ('planned', None)
        except BaseException as exc:
            stage = getattr(docker, 'inspection_stage', 'accepted_source')
            if stage in STAGES: exc.inspection_stage = stage
            raise
    return {'status': status, 'scope': SCOPE, 'checked_revision': revision,
        'inspection_completed': True, 'current_storage_verified': True,
        'review_file_created': status == 'prepared', 'review_available': path is not None,
        'review_file': str(path) if path else None, 'review_sha256': hashlib.sha256(body).hexdigest(),
        'known_code_location_count': len(review['known_code_locations']),
        'plan_state': 'incomplete', 'unresolved_field_count': len(review['unresolved_fields']),
        'unresolved_fields': review['unresolved_fields'], 'required_verifications': list(REQUIRED_VERIFICATIONS),
        'privileged_directory_observer_requested': privileged,
        'readiness': 'blocked', 'production_supply_ready': False, 'activation_allowed': False, **NO_CHANGES}


def failure_code(exc):
    if isinstance(exc, ActivationError) and str(exc).startswith(('BACKUP_REVIEW_', 'SUPPLY_REVIEW_')):
        allowed = {'BACKUP_REVIEW_SOURCE_MANIFEST_INCOMPLETE', 'BACKUP_REVIEW_CODE_DECLARATION_CHANGED',
            'BACKUP_REVIEW_FRESH_MAPPING_REQUIRED', 'BACKUP_REVIEW_TOO_LARGE',
            'SUPPLY_REVIEW_FILE_OWNER_MODE_OR_LINK_REJECTED', 'SUPPLY_REVIEW_EXISTING_FILE_TOO_LARGE',
            'SUPPLY_REVIEW_FILE_CHANGED', 'SUPPLY_REVIEW_EXISTING_CONTENT_CONFLICT'}
        return str(exc) if str(exc) in allowed else 'BACKUP_REVIEW_PREPARATION_UNAVAILABLE'
    return mapping.layout.failure_code(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='save only a private incomplete backup boundary review')
    parser.add_argument('--privileged-directory-metadata', action='store_true',
        help='use the existing fixed two-directory observer when needed')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        print(json.dumps(prepare_review(root, apply=args.apply,
            privileged=args.privileged_directory_metadata), ensure_ascii=False))
        return 0
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError,
            AttributeError, URLError, KeyboardInterrupt) as exc:
        result = {'status': 'failed', 'scope': SCOPE, 'code': failure_code(exc),
            'inspection_completed': False, 'current_storage_verified': False,
            'review_file_created': False, 'review_available': False,
            'readiness': 'blocked', 'production_supply_ready': False, 'activation_allowed': False, **NO_CHANGES}
        stage = getattr(exc, 'inspection_stage', None)
        if stage in STAGES: result['failed_stage'] = stage
        print(json.dumps(result), file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
