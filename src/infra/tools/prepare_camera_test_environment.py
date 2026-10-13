"""Isolate Camera Streamlit; optionally restore only three logged shared versions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BEFORE = {'streamlit': '1.50.0', 'cachetools': '6.2.1', 'protobuf': '7.36.0'}
AFTER = {'streamlit': '1.45.1', 'cachetools': '5.5.2', 'protobuf': '6.33.6'}
SHARED_PREFIX = '/home/shshin/miniforge3/envs/sh_test'
VERSION_PROBE = """import importlib.metadata as m,json,sys
names=('streamlit','cachetools','protobuf')
def version(n):
 try:return m.version(n)
 except m.PackageNotFoundError:return None
print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,'versions':{n:version(n) for n in names}}))
"""


class SetupError(Exception):
    pass


def safe(path):
    for item in (path, *path.parents):
        if item.is_symlink():
            raise SetupError('SYMLINK_PATH_REJECTED')
    return path


def probe(python):
    result = subprocess.run([str(python), '-I', '-B', '-c', VERSION_PROBE], capture_output=True,
                            text=True, check=True, timeout=15)
    return json.loads(result.stdout)


def shared_plan(state):
    if state['prefix'] != SHARED_PREFIX or state['prefix'] != state['base_prefix']:
        raise SetupError('LOGGED_SHARED_ENVIRONMENT_REQUIRED')
    versions = state['versions']
    if set(versions) != set(BEFORE) or any(versions[n] not in (BEFORE[n], AFTER[n]) for n in BEFORE):
        raise SetupError('SHARED_PACKAGE_VERSION_CHANGED')
    return {n: BEFORE[n] for n in BEFORE if versions[n] != BEFORE[n]}


def atomic_json(path, value):
    safe(path)
    fd, name = tempfile.mkstemp(prefix='.ui-env-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def command(args, log, timeout=300):
    # Package tools and synthetic tests do not inherit platform credentials.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('VMS_', 'CAMERA_', 'COMPOSE_', 'STREAMLIT_'))
           and k not in ('PYTHONPATH', 'PYTHONHOME')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, cwd=ROOT, timeout=timeout)
    log.write(result.stdout)
    log.flush()
    if result.returncode:
        raise SetupError('ENVIRONMENT_COMMAND_FAILED')
    return result.stdout.decode('utf-8', errors='replace')


def prepare(root, log, run=command, inspect=probe):
    requirements = safe(root / 'src/platform/camera/test_streamlit/requirements.txt')
    if requirements.read_bytes() != b'streamlit==1.45.1\n':
        raise SetupError('REVIEWED_UI_REQUIREMENTS_REQUIRED')
    home = safe(root / 'var/test-streamlit')
    marker = safe(home / 'owner.json')
    identity = {'format_version': 1, 'owner': 'vms-camera-test-ui',
                'requirements_sha256': hashlib.sha256(requirements.read_bytes()).hexdigest()}
    if marker.exists():
        if not marker.is_file() or json.loads(marker.read_text()) != identity:
            raise SetupError('UI_ENVIRONMENT_OWNER_MISMATCH')
    elif home.exists():
        raise SetupError('EXISTING_UI_DIRECTORY_NOT_MANAGED')
    else:
        home.mkdir(parents=True, mode=0o700)
        atomic_json(marker, identity)
    venv = safe(home / 'python')
    config = safe(venv / 'pyvenv.cfg')
    if not config.exists():
        run([sys.executable, '-I', '-B', '-m', 'venv', venv], log)
    if not config.is_file() or not re.search(r'^include-system-site-packages\s*=\s*false\s*$', config.read_text(), re.M):
        raise SetupError('UI_ENVIRONMENT_NOT_ISOLATED')
    python = venv / 'bin/python'
    state = inspect(python)
    if Path(state['prefix']).resolve() != venv.resolve() or state['prefix'] == state['base_prefix']:
        raise SetupError('UI_ENVIRONMENT_NOT_ISOLATED')
    if state['versions']['streamlit'] not in (None, '1.45.1'):
        raise SetupError('UI_PACKAGE_VERSION_CHANGED')
    run([python, '-I', '-B', '-m', 'pip', '--isolated', 'install', '-r', requirements], log)
    run([python, '-I', '-B', '-m', 'pip', '--isolated', 'check'], log)
    if inspect(python)['versions']['streamlit'] != '1.45.1':
        raise SetupError('UI_PACKAGE_VERSION_CHANGED')
    transcript = run([python, '-I', '-B', '-m', 'unittest', 'discover', '-s',
                      root / 'src/platform/camera/test_streamlit', '-p', 'test_camera*.py', '-q'], log)
    if not re.search(r'^Ran 22 tests in ', transcript, re.M) or not re.search(r'^OK\s*$', transcript, re.M):
        raise SetupError('COMPLETE_UI_TESTS_REQUIRED')
    return {'python': str(python), 'isolated': True, 'dependencies_verified': True, 'tests_passed': 22}


def restore_shared(root, state, log, run=command, inspect=probe):
    changes = shared_plan(state)
    if not changes:
        return {'status': 'already_restored', 'versions': BEFORE, 'scope': 'logged_versions_only'}
    parent = safe(root / 'var/test-streamlit-recovery')
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='step11ui1a-', dir=parent))
    previous, original = backup / 'before', backup / 'original'
    previous.mkdir(mode=0o700)
    original.mkdir(mode=0o700)
    # Download both sets before changing the shared environment. No dependency upgrades.
    for target, versions in ((previous, state['versions']), (original, BEFORE)):
        run([sys.executable, '-I', '-B', '-m', 'pip', '--isolated', 'download', '--only-binary=:all:',
             '--no-deps', '--dest', target, *[n + '==' + v for n, v in versions.items()]], log)
    receipt = {'format_version': 1, 'before_versions': state['versions'], 'restore_versions': BEFORE,
               'files': {p.relative_to(backup).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(backup.rglob('*.whl'))}, 'status': 'prepared'}
    atomic_json(backup / 'receipt.json', receipt)
    if inspect(sys.executable) != state:
        raise SetupError('SHARED_ENVIRONMENT_CHANGED_DURING_PREPARATION')
    try:
        run([sys.executable, '-I', '-B', '-m', 'pip', '--isolated', 'install', '--no-index',
             '--find-links', original, '--no-deps', *[n + '==' + v for n, v in changes.items()]], log)
        if inspect(sys.executable)['versions'] != BEFORE:
            raise SetupError('SHARED_RESTORE_NOT_VERIFIED')
    except BaseException:
        receipt['status'] = 'restore_failed'
        atomic_json(backup / 'receipt.json', receipt)
        raise
    receipt['status'] = 'restored'
    atomic_json(backup / 'receipt.json', receipt)
    return {'status': 'restored', 'versions': BEFORE, 'scope': 'logged_versions_only', 'backup': str(backup),
            'shared_dependency_consistency_claimed': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--restore-shared', action='store_true')
    args = parser.parse_args()
    report = {'scope': 'camera_test_python_environment', 'service_restart_performed': False,
              'database_modified': False, 'production_keys_loaded': False,
              'browser_acceptance': 'deferred', 'shared_environment_modified': False}
    try:
        state = probe(sys.executable)
        changes = shared_plan(state) if args.restore_shared else {}
        report.update(status='planned', shared_restore_plan=changes)
        if not args.apply:
            print(json.dumps(report))
            return 0
        safe(ROOT / 'var')
        log_path = safe(ROOT / 'var/test-streamlit-setup.log')
        log_path.parent.mkdir(exist_ok=True)
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(descriptor, 0o600)
        report['log'] = str(log_path)
        with os.fdopen(descriptor, 'wb') as log:
            report['ui'] = prepare(ROOT, log)
            # Isolated preparation and all UI tests must pass before shared restoration.
            if args.restore_shared:
                report['shared_environment_modified'] = None if changes else False
                report['shared'] = restore_shared(ROOT, state, log)
                report['shared_environment_modified'] = bool(changes)
        report.update(status='prepared', log=str(log_path))
        atomic_json(ROOT / 'var/test-streamlit-environment.json', report)
        print(json.dumps(report))
        return 0
    except (SetupError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        if report['shared_environment_modified'] is None:
            try:
                report['shared_environment_modified'] = probe(sys.executable)['versions'] != state['versions']
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                pass
        report.update(status='failed', code=str(exc) if isinstance(exc, SetupError) else 'ENVIRONMENT_PREPARATION_FAILED')
        print(json.dumps(report))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
