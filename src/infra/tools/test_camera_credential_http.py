#!/usr/bin/env python3
"""Check credential write HTTP and existing storage in disposable PostgreSQL only."""
import json
from pathlib import Path
import subprocess
import sys

from camera_activation import ActivationError
import test_camera_credential_storage as storage

SCOPE = 'camera_credential_write_http_native_postgresql'
HTTP_PACKAGE = 'vms.local/platform/camera/internal/app'
CONTRACT_PACKAGE = 'vms.local/platform/camera/internal/contracts'
HTTP_TESTS = (
    'TestCredentialHTTPWriteAndReplay', 'TestCredentialHTTPValidationOrder',
    'TestCredentialHTTPAuthorization', 'TestCredentialHTTPStoreErrorsAreSafe',
    'TestCredentialHTTPNoImplicitActivation', 'TestCredentialHTTPRejectsInconsistentReceipt',
    'TestCredentialHTTPActualTLS',
)
CONTRACT_TESTS = (
    'TestCredentialWriteExactInput', 'TestCredentialWriteRejectsAmbiguousJSON',
    'TestCredentialWriteSemanticValidation', 'TestCredentialWriteDisclosureAndClear',
    'TestCredentialTargetSyntax',
)


def summarize_log(path):
    result = storage.summarize_log(path)
    terminal = {}
    with path.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('Action') in ('pass', 'fail', 'skip'):
                terminal[(row.get('Package'), row.get('Test'))] = row['Action']
    for package, tests in ((HTTP_PACKAGE, HTTP_TESTS), (CONTRACT_PACKAGE, CONTRACT_TESTS)):
        storage.require(terminal.get((package, None)) == 'pass'
                        and all(terminal.get((package, name)) == 'pass' for name in tests),
                        'CREDENTIAL_HTTP_TESTS_REQUIRED')
    result.update(required_credential_http_tests_passed=len(HTTP_TESTS),
                  required_credential_contract_tests_passed=len(CONTRACT_TESTS),
                  actual_http_tls_verified=True, strict_secret_input_verified=True,
                  safe_receipts_and_errors_verified=True, unadmitted_store_rejected=True,
                  implicit_route_activation_rejected=True,
                  http_writer_success_uses_synthetic_store=True,
                  native_admitted_store_http_writes_verified=False)
    return result


def verify(root, run=subprocess.run):
    storage.checked_project(root)
    manifest = json.loads((root / 'project-manifest.json').read_text())
    storage.require(manifest.get('credential_write_http_implemented') is True,
                    'CREDENTIAL_WRITE_HTTP_PROJECT_REQUIRED')
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
                          'code': 'CREDENTIAL_HTTP_CHECK_FAILED',
                          'production_services_modified': False,
                          'production_database_modified': False,
                          'production_keys_loaded': False,
                          'credential_api_activated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
