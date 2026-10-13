#!/usr/bin/env python3
"""Prepare an incomplete review worksheet, never a deployable SupplyPlan.

Refresh accepted read-only facts; derive fixed policies from the camera contract.
Unknown choices stay null. Unverified observations appear only as candidates.
No key/CA/DSN contents, referenced locations or authority records are opened.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from urllib.error import URLError

import inspect_camera_credential_supply_facts as facts
from camera_activation import ActivationError, activation_lock, private_directory, safe

SCOPE = 'camera_credential_production_supply_review'
DIRECTORY = 'var/camera/credential-supply-reviews'
ACCEPTED_FACTS = '0e8a55880d8a40e6802260f8b2791c7db046741c309c75f6ed2cd72610ec468e'
SCHEMA = 'src/platform/camera/api/planned/credential-supply.schema.json'
MAX_REVIEW_BYTES = 65536
require = facts.require
NO_CHANGES = {**facts.NO_CHANGES, 'review_is_deployable': False,
    'referenced_supply_files_created': False, 'authority_bootstrapped': False}
VERIFICATIONS = [
    'CONTAINER_UID_MAPPING_AND_EXECUTION_IDENTITIES',
    'SOURCE_KEY_INTEGRITY_AND_EXACT_RUNTIME_COPY',
    'ACTUAL_MOUNT_TLS_SOURCE_ROLE_AND_AUTHORITY_BINDINGS',
    'PHYSICAL_PATH_AND_COMPLETE_BACKUP_TOPOLOGY',
    'FIRST_DEPLOYMENT_AND_DATABASE_CUTOVER_PRECONDITIONS',
]


def checked_source(root):
    revision = facts.checked_source(root)
    manifest = json.loads((root/'project-manifest.json').read_text())
    require(manifest.get('credential_production_supply_facts_server_verified') is True
        and manifest.get('validated_credential_production_supply_facts_project_sha256') == ACCEPTED_FACTS
        and manifest.get('credential_production_supply_review_implemented') is True,
        'ACCEPTED_SUPPLY_FACTS_REQUIRED')
    require('src/infra/tools/prepare_camera_credential_supply_review.py' in manifest['files'],
        'SUPPLY_REVIEW_SOURCE_MANIFEST_INCOMPLETE')
    return revision


def schema_template(schema):
    """Every required leaf is a contract constant, an enforced empty list or null."""
    policies = []
    def visit(node, path, depth=0):
        require(depth <= 32 and isinstance(node, dict), 'SUPPLY_REVIEW_SCHEMA_INVALID')
        if '$ref' in node:
            ref = node['$ref']
            require(isinstance(ref, str) and ref.startswith('#/$defs/')
                and '/' not in ref[len('#/$defs/'):], 'SUPPLY_REVIEW_SCHEMA_INVALID')
            return visit(schema['$defs'][ref[len('#/$defs/'):]], path, depth+1)
        if 'const' in node:
            policies.append(path); return copy.deepcopy(node['const'])
        if node.get('type') == 'array' and node.get('maxItems') == 0:
            policies.append(path); return []
        if node.get('type') == 'object':
            names = node.get('required')
            require(isinstance(names, list) and len(names) <= 64 and len(names) == len(set(names))
                and all(isinstance(x, str) and x in node.get('properties', {}) for x in names),
                'SUPPLY_REVIEW_SCHEMA_INVALID')
            return {name: visit(node['properties'][name], path+'.'+name if path else name, depth+1)
                    for name in names}
        require(node.get('type') in ('string', 'integer', 'array'), 'SUPPLY_REVIEW_SCHEMA_INVALID')
        return None
    return visit(schema, ''), sorted(policies)


def unresolved_fields(value):
    result = []
    def visit(item, path):
        if isinstance(item, dict):
            for name, child in item.items(): visit(child, path+'.'+name if path else name)
        elif item is None: result.append(path)
    visit(value, '')
    return sorted(result)


def build_review(root, observation, revision):
    require(observation.get('scope') == facts.SCOPE and observation.get('status') == 'inspected'
        and observation.get('inspection_completed') is True and observation.get('checked_revision') == revision
        and observation.get('project') == 'vms-project' and observation.get('activation_allowed') is False
        and all(observation.get(k) is False for k in facts.NO_CHANGES), 'SUPPLY_REVIEW_FRESH_FACTS_REQUIRED')
    schema = json.loads((root/SCHEMA).read_text())
    template, policies = schema_template(schema)
    template['inventory_basis']['source_sha256'] = revision
    template['project_root'] = str(root)
    key = observation['host_key_bundle']
    observed_fields = ['inventory_basis.source_sha256', 'project_root']
    if key['status'] == 'metadata_valid':
        template['key_supply']['source_file'] = key['source_file']
        template['key_supply']['source_owner_uid'] = key['owner_uid']
        observed_fields += ['key_supply.source_file', 'key_supply.source_owner_uid']
    # Container IDs, transient counts, PIDs and peer names do not enter the draft.
    # This keeps retries stable while preserving the unverified namespace boundary.
    candidates = [{
        'field': 'database.host_data_directory',
        'observed_value': observation['database_volume']['daemon_declared_host_data_directory'],
        'basis': 'daemon-declared-volume-path', 'verification_required': True,
    }]
    for service, fields in (('camera-api', ('runtime.uid', 'runtime.gid', 'authority.runtime_gid')),
                            ('camera-db', ('database.server_uid',))):
        process = observation['processes'][service]
        identities = {json.dumps(x, sort_keys=True) for x in process['effective_identities']}
        identities.update(json.dumps(x, sort_keys=True) for x in process['end_effective_identities'])
        identities = [json.loads(x) for x in sorted(identities)]
        for field in fields:
            candidates.append({'field': field, 'observed_value': identities,
                'basis': 'docker-daemon-host-effective-identities', 'verification_required': True})
    network = observation['storage_network']
    for service, field in (('camera-db', 'database.host_ip'), ('camera-api', 'runtime.source_ip')):
        candidates.append({'field': field, 'observed_value': network['observed_container_addresses'][service],
            'basis': 'current-unpinned-network-addresses', 'verification_required': True})
    missing = unresolved_fields(template)
    require(missing and template['key_supply']['expected_source_sha256'] is None
        and template['tls']['expected_ca_sha256'] is None, 'INCOMPLETE_SUPPLY_REVIEW_REQUIRED')
    return {'format_version': 1, 'document_kind': 'camera-credential-supply-review',
        'intent': 'review-only-incomplete', 'scope': SCOPE, 'plan_state': 'incomplete',
        'checked_revision': revision, 'accepted_facts_revision': ACCEPTED_FACTS,
        'partial_supply_plan': template, 'contract_policy_fields': policies,
        'observed_metadata_fields': sorted(observed_fields), 'unresolved_fields': missing,
        'observation_candidates': sorted(candidates, key=lambda x: x['field']),
        'required_verifications': VERIFICATIONS,
        'registry_basis': {'api_version': facts.inventory.VERSION, 'schema_version': 7,
            'camera_image': observation['inventory']['camera_image'],
            'database_image': observation['inventory']['database_image'],
            'blockers': observation['inventory']['blockers']},
        'readiness': 'blocked', 'production_supply_ready': False, 'activation_allowed': False,
        **NO_CHANGES}


def encoded_review(review):
    body = (json.dumps(review, ensure_ascii=True, indent=2, sort_keys=True)+'\n').encode()
    require(len(body) <= MAX_REVIEW_BYTES, 'SUPPLY_REVIEW_TOO_LARGE')
    return body


def same_existing(path, body):
    """Check the exact generated destination; refuse links/modes and preserve edits."""
    safe(path)
    s = path.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_uid == os.getuid()
        and stat.S_IMODE(s.st_mode) == 0o600, 'SUPPLY_REVIEW_FILE_OWNER_MODE_OR_LINK_REJECTED')
    require(s.st_size <= MAX_REVIEW_BYTES, 'SUPPLY_REVIEW_EXISTING_FILE_TOO_LARGE')
    def identity(v):
        return (v.st_dev, v.st_ino, v.st_uid, v.st_gid, v.st_mode, v.st_nlink,
                v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        require(identity(os.fstat(stream.fileno())) == identity(s), 'SUPPLY_REVIEW_FILE_CHANGED')
        value = stream.read(MAX_REVIEW_BYTES+1)
        require(identity(os.fstat(stream.fileno())) == identity(s) and identity(path.lstat()) == identity(s),
                'SUPPLY_REVIEW_FILE_CHANGED')
    require(value == body, 'SUPPLY_REVIEW_EXISTING_CONTENT_CONFLICT')


def publish_review(root, body, *, directory=DIRECTORY):
    """Publish a create-only private review in the caller's fixed directory."""
    directory = root/directory
    private_directory(directory)
    path = directory/('review-'+hashlib.sha256(body).hexdigest()+'.json')
    safe(path)
    if path.exists():
        same_existing(path, body); return 'already_prepared', path
    fd, temporary = tempfile.mkstemp(prefix='.review-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        # Link publication cannot overwrite an edit or a concurrently created file.
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            os.unlink(temporary); same_existing(path, body)
            return 'already_prepared', path
        os.unlink(temporary)
        dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(dfd)
        finally: os.close(dfd)
        return 'prepared', path
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def prepare_review(root, *, apply=False):
    revision = checked_source(root)
    with activation_lock(root):
        docker = facts.FactsDocker(root)
        try:
            observation = facts.inspect_facts(root, docker)
        except BaseException as exc:
            stage = getattr(docker, 'inspection_stage', None)
            if stage in facts.STAGES: exc.inspection_stage = stage
            raise
        review = build_review(root, observation, revision)
        body = encoded_review(review)
        require(checked_source(root) == revision, 'INSPECTION_INPUT_CHANGED')
        status, path = publish_review(root, body) if apply else ('planned', None)
    return {'status': status, 'scope': SCOPE, 'checked_revision': revision,
        'review_file_created': status == 'prepared', 'review_available': path is not None,
        'review_file': str(path) if path else None, 'review_sha256': hashlib.sha256(body).hexdigest(),
        'plan_state': 'incomplete', 'unresolved_field_count': len(review['unresolved_fields']),
        'unresolved_fields': review['unresolved_fields'],
        'observation_candidates': review['observation_candidates'],
        'required_verifications': VERIFICATIONS, 'readiness': 'blocked',
        'production_supply_ready': False, 'activation_allowed': False, **NO_CHANGES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='save only the private incomplete review worksheet')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        print(json.dumps(prepare_review(root, apply=args.apply), ensure_ascii=False))
        return 0  # Incomplete planning input is an expected result.
    except (ActivationError, OSError, ValueError, KeyError, TypeError, IndexError,
            AttributeError, URLError, KeyboardInterrupt) as exc:
        stage = getattr(exc, 'inspection_stage', None)
        code = facts.failure_code(exc) if isinstance(exc, ActivationError) else 'SUPPLY_REVIEW_PREPARATION_UNAVAILABLE'
        result = {'status': 'failed', 'scope': SCOPE, 'code': code,
            'review_file_created': False, 'activation_allowed': False, **NO_CHANGES}
        if stage in facts.STAGES: result['failed_stage'] = stage
        print(json.dumps(result), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
