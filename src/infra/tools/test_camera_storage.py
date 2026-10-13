#!/usr/bin/env python3
"""Run native PostgreSQL storage and device/source deletion API tests in a disposable Compose project."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys


def main():
    if shutil.which('docker') is None:
        print('Docker is required for isolated native PostgreSQL verification.', file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[3]
    project = 'vms-storage-test-' + secrets.token_hex(6)
    env = {k: v for k, v in os.environ.items() if not k.startswith('COMPOSE_')}
    env['VMS_CAMERA_TEST_PASSWORD'] = secrets.token_hex(24)
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.test.yaml')]
    try:
        result = subprocess.run(command + ['run', '--rm', 'camera-storage-test'],
                                env=env, timeout=900)
        code = result.returncode
    except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
        print('Storage verification interrupted or unavailable.', file=sys.stderr)
        code = 1
    finally:
        try:
            cleanup = subprocess.run(command + ['down', '--volumes', '--remove-orphans', '--timeout', '5'],
                                     env=env, timeout=60)
            if cleanup.returncode:
                print('Cleanup failed for test project ' + project, file=sys.stderr)
                code = 1
        except (OSError, subprocess.TimeoutExpired):
            print('Cleanup incomplete for test project ' + project, file=sys.stderr)
            code = 1
    print(json.dumps({'status': 'passed' if code == 0 else 'failed',
                      'scope': 'camera_device_delete_http_native_postgresql',
                      'project': project, 'production_services_modified': False}))
    return code


if __name__ == '__main__':
    sys.exit(main())
