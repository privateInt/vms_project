#!/usr/bin/env python3
"""Disposable PostgreSQL TLS/role/source rehearsal using new synthetic PKI only."""
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

from camera_activation import ActivationError, Docker, atomic_write, private_directory
from test_camera_credential_storage import VerificationError, require, PACKAGE
import prepare_camera_database_tls_candidate as candidate

SCOPE = 'camera_database_tls_role_source_native_postgresql'
DATABASE = 'vms_camera_tls_test'
OWNER = 'vms_camera_tls_owner'
RUNTIME = 'TestNativeDatabaseTLSRuntime'
MAINTENANCE = 'TestNativeDatabaseTLSMaintenance'
OFFSOURCE = 'TestNativeDatabaseTLSOffSource'
NATIVE_TESTS = (RUNTIME, MAINTENANCE, OFFSOURCE)
UNIT_TESTS = ('TestCredentialEndpointCanonicalHashAndPrivacy',
              'TestCredentialEndpointRejectsUnsupportedProfilesAndDSNs',
              'TestCredentialEndpointActualTLSVerification',
              'TestCredentialMaintenanceHBAExactPolicy', 'TestCredentialMaintenanceConnectionConfiguration')
PHASES = ('runtime-supply-ro-uid', 'runtime-two-role-tls', 'runtime-denials',
          'maintenance-supply-ro-uid', 'maintenance-mtls-target-control', 'maintenance-denials',
          'offsource-supply-ro-uid', 'offsource-denials', 'runtime-recreated')
PARENTS = (RUNTIME, RUNTIME, RUNTIME, MAINTENANCE, MAINTENANCE, MAINTENANCE, OFFSOURCE, OFFSOURCE, RUNTIME)
PREFIX = 'DATABASE_TLS_PHASE_OK:'
BUILD = ('set -eu\numask 077\nchmod 0755 /exchange\ncp -a /source/. /work/\n'
         'go vet ./...\ngo test -race -c -o /exchange/storage.test ./camera/internal/storage\n'
         'go build -o /exchange/test2json cmd/test2json\nchmod 0755 /exchange/storage.test /exchange/test2json\n'
         'go test -race -count=1 -json ./camera/internal/storage -run "^(' + '|'.join(UNIT_TESTS) + ')$"\n')
OWN_FILES = ('set -eu\numask 077\n'
             'for name in db control runtime maintenance offsource; do\n'
             '  cp /input/$name/* /$name/\n'
             'done\n'
             'chown -R 999:999 /db /control\nchown -R 10001:10001 /runtime\n'
             'chown -R 10002:10002 /maintenance\nchown -R 10003:10003 /offsource\n'
             'chmod 0700 /db /control /runtime /maintenance /offsource\n'
             'chmod 0400 /db/* /control/* /runtime/* /maintenance/* /offsource/*\n')
VERIFY_DATABASE = (
    'set -eu\n'
    'awk \'$1=="Uid:" {if($3!=999)exit 1;u=1} $1=="Gid:" {if($3!=999)exit 1;g=1} END{if(!u||!g)exit 1}\' /proc/1/status\n'
    'awk \'$5=="/db-tls" || $5=="/tls-control" {n++;if($6 !~ /(^|,)ro(,|$)/)exit 1} END{if(n!=2)exit 1}\' /proc/1/mountinfo\n'
    'test ! -e /db-tls/ca.key\ntest ! -e /tls-control/ca.key\n')
NO_CHANGES = {name: False for name in (
    'production_services_modified', 'service_restart_performed', 'production_database_modified',
    'database_schema_modified', 'production_key_material_read', 'production_keys_loaded',
    'production_admission_state_created', 'production_hba_modified', 'environment_modified',
    'production_network_modified', 'credential_api_activated', 'business_runtime_ready',
    'production_supply_ready', 'activation_allowed', 'production_runtime_mount_verified',
    'database_tls_activated', 'production_endpoint_and_sources_reserved', 'approved_binding_created')}


def checked_revision(root):
    revision = candidate.checked_revision(root)
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_tls_candidate_server_verified') is True
            and value.get('validated_credential_tls_candidate_project_sha256') ==
            'bee8f71859c99c31e81997009c950f7360e441b82eff3acf09420998430adf04'
            and value.get('credential_database_tls_boundary_implemented') is True,
            'DATABASE_TLS_BOUNDARY_PROJECT_REQUIRED')
    return revision


def network_addresses(body):
    try:
        value = json.loads(body)
        require(isinstance(value, list) and len(value) == 1, 'ISOLATED_NETWORK_INVALID')
        net = ipaddress.IPv4Network(value[0]['Subnet'], strict=True)
        require(net.is_private and net.num_addresses >= 8 and
                str(net.network_address + 1) == value[0]['Gateway'], 'ISOLATED_NETWORK_INVALID')
        return [str(net.network_address + index) for index in (2, 3, 4, 5)]
    except (ValueError, TypeError, KeyError, IndexError):
        raise VerificationError('ISOLATED_NETWORK_INVALID') from None


def hba(runtime, maintenance):
    require(runtime != maintenance and all(str(ipaddress.IPv4Address(v)) == v for v in (runtime, maintenance)),
            'ISOLATED_SOURCE_INVALID')
    return (f'local all {OWNER} trust\nlocal all all reject\n'
            f'hostssl {DATABASE} camera_credential_writer,camera_credential_budget {runtime}/32 scram-sha-256\n'
            f'hostssl {DATABASE},postgres camera_maintenance {maintenance}/32 scram-sha-256 clientcert=verify-full\n'
            'host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n').encode()


def prepare_fixture(root, addresses, port=5432):
    # root is a brand-new private TemporaryDirectory, never the production root.
    require(root.is_dir() and not list(root.iterdir()), 'FRESH_SYNTHETIC_INPUT_REQUIRED')
    db, runtime, maintenance, offsource = addresses
    require(len(set(addresses)) == 4 and all(str(ipaddress.IPv4Address(v)) == v for v in addresses)
            and type(port) is int and 1 <= port <= 65535, 'ISOLATED_ENDPOINT_INVALID')
    first, wrong = root / 'pki', root / 'wrong-pki'
    first.mkdir(mode=0o700); wrong.mkdir(mode=0o700)
    metadata = candidate.prepare(first, True)
    candidate.prepare(wrong, True)
    pk = first.joinpath(*candidate.DIRECTORY, candidate.CANDIDATE)
    wrong_ca = wrong.joinpath(*candidate.DIRECTORY, candidate.CANDIDATE, 'ca.pem').read_bytes()
    # A correctly CA-signed clientAuth leaf with the wrong CN must fail at PG,
    # independently of the public maintenance opener's earlier input check.
    signer = root / 'wrong-cn'; signer.mkdir(mode=0o700)
    for name in ('ca.pem', 'ca.key', 'maintenance.key'):
        atomic_write(signer / name, (pk / name).read_bytes())
    fd = os.open(signer, candidate.DIR_FLAGS)
    try:
        candidate.write_new(fd, 'wrong.csr', candidate.openssl(fd, ['req', '-new', '-key', 'maintenance.key',
                                                               '-subj', '/CN=wrong_maintenance']))
        candidate.write_new(fd, 'wrong.cnf', b'[leaf]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
        wrong_client = candidate.openssl(fd, ['x509', '-req', '-in', 'wrong.csr', '-CA', 'ca.pem',
                                              '-CAkey', 'ca.key', '-set_serial', '0x1' + secrets.token_hex(16),
                                              '-days', '365', '-sha256', '-extfile', 'wrong.cnf', '-extensions', 'leaf'])
    finally:
        os.close(fd)
    inputs = root / 'input'; inputs.mkdir(mode=0o700)
    for name in ('db', 'control', 'runtime', 'maintenance', 'offsource'):
        (inputs / name).mkdir(mode=0o700)
    state = {'Kind': 'isolated-database-tls', 'Host': db, 'Port': port, 'Database': DATABASE,
             'ServerName': candidate.SERVER_NAME, 'RuntimeIP': runtime, 'MaintenanceIP': maintenance,
             'OffSourceIP': offsource, 'ServerCertificateSHA256': metadata['server_certificate_sha256'],
             'MaintenanceCertificateSHA256': metadata['maintenance_certificate_sha256']}
    passwords = {role: secrets.token_hex(24) for role in
                 (OWNER, 'camera_credential_writer', 'camera_credential_budget', 'camera_maintenance')}
    dsns = {role: (f'postgres://{role}:{password}@{db}:{port}/{DATABASE}?sslmode=verify-full\n').encode()
            for role, password in passwords.items() if role != OWNER}
    for name in ('ca.pem', 'server.pem', 'server.key'):
        atomic_write(inputs / 'db' / name, (pk / name).read_bytes())
    for name in ('runtime', 'maintenance', 'offsource'):
        dest = inputs / name
        atomic_write(dest / 'endpoint.json', candidate.encoded(state))
        atomic_write(dest / 'ca.pem', (pk / 'ca.pem').read_bytes())
        for role in ('camera_credential_writer', 'camera_credential_budget'):
            atomic_write(dest / (role + '-dsn'), dsns[role])
        if name != 'runtime':
            atomic_write(dest / 'camera_maintenance-dsn', dsns['camera_maintenance'])
            for part in ('maintenance.pem', 'maintenance.key'):
                atomic_write(dest / part, (pk / part).read_bytes())
    atomic_write(inputs / 'runtime' / 'wrong-ca.pem', wrong_ca)
    atomic_write(inputs / 'maintenance' / 'wrong-client.pem', wrong_client)
    atomic_write(inputs / 'maintenance' / 'wrong-client.key', (pk / 'maintenance.key').read_bytes())
    sql = ['REVOKE CONNECT ON DATABASE ' + DATABASE + ' FROM PUBLIC;']
    for role in ('camera_credential_writer', 'camera_credential_budget', 'camera_maintenance'):
        privilege = 'SUPERUSER' if role == 'camera_maintenance' else 'NOSUPERUSER'
        sql.append(f"CREATE ROLE {role} LOGIN {privilege} NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{passwords[role]}';")
        sql.append(f'GRANT CONNECT ON DATABASE {DATABASE} TO {role};')
    sql += [f'CREATE SCHEMA tls_probe AUTHORIZATION {OWNER};',
            'CREATE TABLE tls_probe.sentinel(id integer PRIMARY KEY,value text NOT NULL);',
            "INSERT INTO tls_probe.sentinel VALUES(1,'isolated-only');",
            'GRANT USAGE ON SCHEMA tls_probe TO camera_credential_writer,camera_credential_budget;',
            'GRANT SELECT ON tls_probe.sentinel TO camera_credential_writer,camera_credential_budget;']
    atomic_write(inputs / 'control' / '001-init.sql', ('\n'.join(sql) + '\n').encode())
    atomic_write(inputs / 'control' / 'pg_hba.conf', hba(runtime, maintenance))
    atomic_write(inputs / 'control' / 'owner-password', (passwords[OWNER] + '\n').encode())
    require(not list(inputs.rglob('ca.key')), 'CA_SIGNING_KEY_EXPORTED')
    return inputs


def summarize_log(path):
    terminal, pending, phases = {}, {}, []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try: row = json.loads(line)
        except ValueError: continue
        if not isinstance(row, dict): continue
        require(row.get('Action') != 'fail', 'GO_TEST_FAILED')
        if row.get('Package') != PACKAGE: continue
        name, action = row.get('Test'), row.get('Action')
        if action in ('pass', 'skip'): terminal[name] = action
        if name not in NATIVE_TESTS: continue
        if action == 'run':
            require(name not in pending, 'TLS_TRANSCRIPT_INVALID'); pending[name] = []
        elif action == 'output':
            proof = re.search(r'(?:^|\s)' + re.escape(PREFIX) + r'([a-z-]+)\s*$', str(row.get('Output', '')))
            if proof:
                require(name in pending, 'TLS_TRANSCRIPT_INVALID')
                pending[name].append(proof.group(1))
        elif action in ('pass', 'skip'):
            require(name in pending and action == 'pass' and pending[name], 'TLS_NATIVE_TEST_NOT_PASSED')
            for phase in pending.pop(name):
                index = len(phases)
                require(index < len(PHASES) and phase == PHASES[index] and name == PARENTS[index],
                        'TLS_COMPLETE_PHASES_REQUIRED')
                phases.append(phase)
    require(not pending and tuple(phases) == PHASES and terminal.get(None) == 'pass'
            and all(terminal.get(name) == 'pass' for name in (*UNIT_TESTS, *NATIVE_TESTS)),
            'TLS_COMPLETE_TESTS_REQUIRED')
    return {'required_endpoint_and_hba_unit_tests_passed': len(UNIT_TESTS),
            'required_native_peer_tests_passed': len(NATIVE_TESTS), 'native_tls_phases_passed': len(PHASES),
            'synthetic_d1a_pki_profile_verified': True, 'actual_runtime_two_role_tls_verified': True,
            'actual_maintenance_mtls_target_and_control_verified': True, 'exact_leaf_certificates_verified': True,
            'actual_role_source_database_and_tls_identity_verified': True,
            'wrong_password_ca_hostname_plaintext_and_control_database_rejected': True,
            'maintenance_missing_certificate_and_wrong_cn_rejected': True,
            'valid_credentials_from_wrong_source_rejected': True, 'runtime_privilege_escalation_rejected': True,
            'separate_peer_uids_and_read_only_mounts_verified': True,
            'recreated_runtime_fixed_source_and_tls_verified': True, 'hba_outside_pgdata_verified': True}


def verify(root, run=subprocess.run, *, fixture=prepare_fixture):
    require(shutil.which('docker') is not None, 'DOCKER_REQUIRED')
    revision = checked_revision(root)
    Docker(root).preflight()  # Local Unix daemon required for synthetic host bind.
    directory = root / 'var/camera/database-tls-checks'; private_directory(directory)
    project = 'vms-database-tls-test-' + secrets.token_hex(6)
    network = project + '-storage'
    fd, name = tempfile.mkstemp(prefix=project + '-', suffix='.log', dir=directory)
    os.close(fd); log = Path(name)
    env = {key: value for key, value in os.environ.items() if not key.startswith(('COMPOSE_', 'VMS_', 'CAMERA_', 'PG'))}
    command = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
               '--file', str(root / 'src/infra/postgresql/compose.database-tls-test.yaml')]
    stage, last_completed, failed_stage, exit_code = 'create_network', None, None, None
    failure, summary, completed, vetted, cleaned, network_created = None, {}, False, False, False, False
    temporary = tempfile.TemporaryDirectory(prefix=project + '-', dir=directory)
    input_root = Path(temporary.name)

    def capture(args):
        result = run(['docker', *args], env=env.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        require(result.returncode == 0 and len(result.stdout) <= 32768, 'ISOLATED_NETWORK_COMMAND_FAILED')
        return result.stdout

    def execute(label, args, timeout=120):
        nonlocal stage, last_completed, exit_code, vetted
        stage = label
        with log.open('ab') as output:
            result = run(command + args, env=env.copy(), stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        exit_code = result.returncode
        require(exit_code == 0, 'ISOLATED_TLS_COMMAND_FAILED')
        last_completed = label
        if label == 'build_and_unit_tests': vetted = True

    def peer(label, service, test, recreated=False):
        args = ['exec', '-T']
        if recreated: args += ['-e', 'CAMERA_TLS_TEST_RECREATED=1']
        args += [service, '/exchange/test2json', '-t', '-p', PACKAGE, '/exchange/storage.test',
                 '-test.v=test2json', '-test.count=1', '-test.run=^' + test + '$', '-test.timeout=90s']
        execute(label, args)

    try:
        # Docker allocates a fresh non-overlapping subnet. Static peer IPs are
        # pinned only inside this new internal network, not the production plan.
        network_created = True  # Also clean up an uncertain committed create.
        capture(['network', 'create', '--driver', 'bridge', '--internal', '--label',
                 'com.docker.compose.project=' + project, network])
        addresses = network_addresses(capture(['network', 'inspect', '--format', '{{json .IPAM.Config}}', network]))
        last_completed = stage
        stage = 'prepare_synthetic_pki'
        inputs = fixture(input_root, addresses)
        env.update(VMS_TLS_INPUT=str(inputs), VMS_TLS_NETWORK=network,
                   VMS_TLS_DB_IP=addresses[0], VMS_TLS_RUNTIME_IP=addresses[1],
                   VMS_TLS_MAINTENANCE_IP=addresses[2], VMS_TLS_OFFSOURCE_IP=addresses[3])
        last_completed = stage
        execute('copy_and_own_synthetic_files', ['run', '--rm', '--no-deps', 'tls-files-owner', 'sh', '-ec', OWN_FILES])
        execute('build_and_unit_tests', ['run', '--rm', '--no-deps', 'tls-build', 'sh', '-ec', BUILD], 900)
        execute('start_isolated_peers', ['up', '--detach', '--wait', '--wait-timeout', '90',
                'tls-db', 'tls-runtime', 'tls-maintenance', 'tls-offsource'])
        execute('verify_database_identity_and_mounts', ['exec', '-T', '--user', '999:999', 'tls-db', 'sh', '-ec', VERIFY_DATABASE])
        peer('runtime_tls_and_denials', 'tls-runtime', RUNTIME)
        peer('maintenance_mtls_and_denials', 'tls-maintenance', MAINTENANCE)
        peer('offsource_denials', 'tls-offsource', OFFSOURCE)
        execute('recreate_runtime_container', ['up', '--detach', '--no-deps', '--force-recreate', 'tls-runtime'])
        peer('recreated_runtime_tls', 'tls-runtime', RUNTIME, True)
        stage = 'verify_transcript'; summary = summarize_log(log); last_completed = stage
        stage = 'verify_source'; require(checked_revision(root) == revision, 'PROJECT_CHANGED_DURING_CHECK')
        last_completed = stage; completed = True
    except VerificationError as exc: failure = str(exc)
    except (candidate.CandidateError, ActivationError, OSError, ValueError, TypeError,
            subprocess.TimeoutExpired, KeyboardInterrupt): failure = 'ISOLATED_TLS_CHECK_INTERRUPTED'
    finally:
        if failure: failed_stage = stage
        if 'VMS_TLS_INPUT' in env:
            try:
                with log.open('ab') as output:
                    result = run(command + ['down', '--volumes', '--remove-orphans', '--timeout', '5'],
                                 env=env.copy(), stdout=output, stderr=subprocess.STDOUT, timeout=60)
                cleaned = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt): cleaned = False
        else: cleaned = True
        if network_created:
            try:
                # Only remove a matching project-labelled network. This handles
                # create timeouts without deleting an unrelated name collision.
                result = run(['docker', 'network', 'ls', '--filter',
                              'label=com.docker.compose.project=' + project,
                              '--format', '{{.ID}} {{.Name}}'], env=env.copy(),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                require(result.returncode == 0 and len(result.stdout) <= 32768, 'ISOLATED_TLS_CLEANUP_INCOMPLETE')
                for line in result.stdout.decode('ascii').splitlines():
                    fields = line.split()
                    require(len(fields) == 2 and re.fullmatch('[0-9a-f]{12,64}', fields[0]), 'ISOLATED_TLS_CLEANUP_INCOMPLETE')
                    if fields[1] == network:
                        result = run(['docker', 'network', 'rm', fields[0]], env=env.copy(),
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                        cleaned = cleaned and result.returncode == 0
            except (VerificationError, OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt): cleaned = False
        try: temporary.cleanup()
        except OSError: cleaned = False
    if not cleaned:
        failure = 'ISOLATED_TLS_CLEANUP_INCOMPLETE'; failed_stage = failed_stage or 'cleanup'
    if failure: summary = {}
    report = {'status': 'passed' if failure is None else 'failed', 'scope': SCOPE, 'project': project,
              'checked_revision': revision, 'go_race_passed': completed, 'go_vet_passed': vetted,
              **summary, **NO_CHANGES, 'synthetic_pki_only': True, 'production_candidate_files_read': False,
              'isolated_database_uid_and_ro_mount_verified': completed,
              'isolated_network_removed': cleaned, 'isolated_resources_removed': cleaned,
              'synthetic_input_removed': not input_root.exists(), 'log': str(log)}
    if failure:
        report.update(code=failure, failed_stage=failed_stage, last_completed_stage=last_completed)
        if exit_code is not None: report['last_command_exit_code'] = exit_code
    report['report'] = str(directory / (project + '.json'))
    atomic_write(Path(report['report']), candidate.encoded(report))
    return report


def main():
    try:
        result = verify(Path(__file__).resolve().parents[3]); print(json.dumps(result))
        return 0 if result['status'] == 'passed' else 1
    except Exception as exc:
        code = str(exc) if isinstance(exc, (VerificationError, candidate.CandidateError)) else 'NATIVE_TLS_CHECK_FAILED'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code): code = 'NATIVE_TLS_CHECK_FAILED'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': code, **NO_CHANGES}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
