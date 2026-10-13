#!/usr/bin/env python3
"""Check version metadata/revoke HTTP and native storage in disposable PostgreSQL."""
import json
from pathlib import Path
import subprocess
import sys

from camera_activation import ActivationError
import test_camera_credential_http as write

storage = write.storage
SCOPE = 'camera_credential_version_metadata_revoke_http_native_postgresql'
HTTP_PACKAGE = write.HTTP_PACKAGE
CONTRACT_PACKAGE = write.CONTRACT_PACKAGE
HTTP_TESTS = (
    'TestCredentialVersionsHTTPMetadata', 'TestCredentialVersionsHTTPRevokeReplay',
    'TestCredentialVersionsHTTPValidationOrder', 'TestCredentialVersionsHTTPPermission',
    'TestCredentialVersionsHTTPStoreErrors', 'TestCredentialVersionsHTTPConfiguration',
    'TestCredentialVersionsHTTPReceiptValidation', 'TestCredentialVersionsHTTPActualTLS',
)
CONTRACT_TESTS = (
    'TestCredentialVersionPathTokens', 'TestCredentialRevokeStrictJSON',
    'TestCredentialRevokeSemantics',
)
METADATA_TESTS = (
    'TestCredentialMetadataRequiresLeaseWithoutIO',
    'TestCredentialMetadataInspectionAndRevocation',
    'TestCredentialMetadataAuthorizationAndUnwind',
    'TestNativeCredentialMetadataRoleAndGrantLoss',
)


def summarize_log(path):
    result = write.summarize_log(path)
    terminal = {}
    with path.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('Action') in ('pass', 'fail', 'skip'):
                terminal[(row.get('Package'), row.get('Test'))] = row['Action']
    for package, tests in ((HTTP_PACKAGE, HTTP_TESTS), (CONTRACT_PACKAGE, CONTRACT_TESTS),
                           (storage.PACKAGE, METADATA_TESTS)):
        storage.require(terminal.get((package, None)) == 'pass'
                        and all(terminal.get((package, name)) == 'pass' for name in tests),
                        'CREDENTIAL_VERSION_HTTP_TESTS_REQUIRED')
    result.update(required_credential_version_http_tests_passed=len(HTTP_TESTS),
                  required_credential_revoke_contract_tests_passed=len(CONTRACT_TESTS),
                  required_credential_metadata_tests_passed=len(METADATA_TESTS),
                  exact_version_metadata_verified=True, revoked_metadata_history_verified=True,
                  metadata_inspection_does_not_reserve_budget=True,
                  metadata_management_authorization_verified=True,
                  metadata_native_role_and_grant_loss_verified=True,
                  revoke_guard_forwarding_verified=True, revoke_replay_http_verified=True,
                  version_http_success_uses_synthetic_store=True,
                  metadata_store_test_admission_uses_synthetic_guard=True,
                  native_admitted_store_version_http_verified=False)
    return result


def verify(root, run=subprocess.run):
    storage.checked_project(root)
    manifest = json.loads((root / 'project-manifest.json').read_text())
    storage.require(manifest.get('credential_write_http_implemented') is True
                    and manifest.get('credential_version_http_implemented') is True,
                    'CREDENTIAL_VERSION_HTTP_PROJECT_REQUIRED')
    return storage.verify(root, run=run, summarize=summarize_log, scope=SCOPE)


def main():
    root = Path(__file__).resolve().parents[3]
    try:
        result = verify(root)
        print(json.dumps(result))
        return 0 if result['status'] == 'passed' else 1
    except (storage.VerificationError, ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt):
        print(json.dumps({'status': 'failed', 'scope': SCOPE,
                          'code': 'CREDENTIAL_VERSION_HTTP_CHECK_FAILED',
                          'production_services_modified': False,
                          'production_database_modified': False,
                          'production_keys_loaded': False,
                          'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
