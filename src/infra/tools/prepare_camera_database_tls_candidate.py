#!/usr/bin/env python3
"""Create/validate a private DB PKI candidate; never deploy it or contact a DB."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import threading

SCOPE = 'camera_database_tls_candidate'
DIRECTORY = ('var', 'camera', 'database-tls-candidates')
CANDIDATE = 'candidate-v1'
LOCK = '.prepare.lock'
SERVER_NAME = 'camera-db.vms.internal'
CLIENT_NAME = 'camera_maintenance'
PEM_FILES = ('ca.pem', 'ca.key', 'server.pem', 'server.key', 'maintenance.pem', 'maintenance.key')
FILES = (*PEM_FILES, 'candidate.json')
MAX_BYTES = 32768
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
NO_CHANGES = {name: False for name in (
    'production_services_modified', 'service_restart_performed', 'production_database_modified',
    'database_schema_modified', 'production_key_material_read', 'production_keys_loaded',
    'production_admission_state_created', 'production_hba_modified', 'environment_modified',
    'network_modified', 'credential_api_activated', 'business_runtime_ready',
    'production_supply_ready', 'activation_allowed', 'runtime_mount_verified',
    'database_tls_activated', 'endpoint_and_sources_reserved', 'approved_binding_created')}


class CandidateError(Exception):
    pass


def require(value, code):
    if not value:
        raise CandidateError(code)


def owned(info, mode=None, regular=False):
    require(info.st_uid == os.getuid(), 'TLS_PATH_OWNER_INVALID')
    require((stat.S_ISREG(info.st_mode) and info.st_nlink == 1) if regular
            else stat.S_ISDIR(info.st_mode), 'TLS_PATH_TYPE_INVALID')
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode, 'TLS_PATH_PERMISSIONS_INVALID')


def directory(root, create):
    root = Path(root).absolute()
    require('..' not in root.parts, 'PROJECT_ROOT_INVALID')
    fd = os.open('/', DIR_FLAGS)
    try:
        for name in root.parts[1:]:
            child = os.open(name, DIR_FLAGS, dir_fd=fd)
            os.close(fd); fd = child
        owned(os.fstat(fd))
        for index, name in enumerate(DIRECTORY):
            if create:
                try: os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(name, DIR_FLAGS, dir_fd=fd)
            os.close(fd); fd = child
            owned(os.fstat(fd), 0o700 if index == 2 else None)
        return fd, root.joinpath(*DIRECTORY)
    except BaseException:
        os.close(fd)
        raise


def read_file(fd, name):
    file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(file); owned(before, 0o600, True)
        require(0 < before.st_size <= MAX_BYTES, 'TLS_FILE_SIZE_INVALID')
        body = b''
        while len(body) <= MAX_BYTES:
            chunk = os.read(file, MAX_BYTES + 1 - len(body))
            if not chunk: break
            body += chunk
        after = os.fstat(file)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                and len(body) == before.st_size, 'TLS_FILE_CHANGED')
        return body
    finally:
        os.close(file)


def write_new(fd, name, body):
    file = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                   0o600, dir_fd=fd)
    with os.fdopen(file, 'wb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    os.fsync(fd)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def openssl(fd, args, input=None):
    # Absolute executable and clean environment: caller OPENSSL_CONF/provider
    # settings cannot change signing. Never forward stderr or private bytes.
    binary = shutil.which('openssl', path=os.defpath)
    require(binary is not None, 'OPENSSL_REQUIRED')
    try:
        result = subprocess.run([binary, *args], cwd='/proc/self/fd/' + str(fd),
                                pass_fds=(fd,), input=input, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30, umask=0o077,
                                env={'PATH': os.defpath, 'LANG': 'C', 'OPENSSL_CONF': '/dev/null'})
    except (OSError, subprocess.TimeoutExpired):
        raise CandidateError('TLS_OPENSSL_UNAVAILABLE') from None
    require(result.returncode == 0, 'TLS_OPENSSL_CHECK_FAILED')
    require(len(result.stdout) <= MAX_BYTES, 'TLS_OPENSSL_OUTPUT_INVALID')
    return result.stdout


def receipt(fd):
    return {
        'format_version': 1, 'kind': 'camera-database-tls-candidate', 'intent': 'candidate-only',
        'server_name': SERVER_NAME, 'maintenance_common_name': CLIENT_NAME,
        'minimum_tls_version': 'TLS1.2', 'key_algorithm': 'RSA-3072',
        'ca_days': 397, 'leaf_days': 365,
        # The static IPs are proposals in the previously observed subnet.
        # No current Docker observation, address reservation or approval here.
        'endpoint_proposal': {'database': 'vms_camera', 'database_ip': '192.168.96.2',
                              'port': 5432, 'runtime_source_ip': '192.168.96.3',
                              'maintenance_source_ip': '192.168.96.4',
                              'address_state': 'proposal-unreserved', 'sslmode': 'verify-full'},
        'files_sha256': {name: sha(read_file(fd, name)) for name in PEM_FILES},
    }


def generate(fd):
    # An interrupted/failed generation leaves a blocked partial candidate.
    # Never replace, regenerate or silently repair any existing candidate.
    configs = {
        'ca.cnf': '[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ca\n[dn]\nCN=VMS Camera Database Candidate CA\n[ca]\nbasicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n',
        'server.cnf': '[leaf]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:' + SERVER_NAME + '\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n',
        'maintenance.cnf': '[leaf]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n',
    }
    for name, body in configs.items(): write_new(fd, name, body.encode())
    for prefix in ('ca', 'server', 'maintenance'):
        write_new(fd, prefix + '.key', openssl(fd, ['genpkey', '-algorithm', 'RSA',
                                                   '-pkeyopt', 'rsa_keygen_bits:3072']))
    write_new(fd, 'ca.pem', openssl(fd, ['req', '-new', '-x509', '-key', 'ca.key', '-sha256',
                                       '-days', '397', '-set_serial', '0x1' + secrets.token_hex(16),
                                       '-config', 'ca.cnf']))
    for prefix, cn in (('server', SERVER_NAME), ('maintenance', CLIENT_NAME)):
        write_new(fd, prefix + '.csr', openssl(fd, ['req', '-new', '-key', prefix + '.key',
                                                   '-subj', '/CN=' + cn]))
        write_new(fd, prefix + '.pem', openssl(fd, ['x509', '-req', '-in', prefix + '.csr',
                 '-CA', 'ca.pem', '-CAkey', 'ca.key', '-set_serial', '0x1' + secrets.token_hex(16),
                 '-days', '365', '-sha256', '-extfile', prefix + '.cnf', '-extensions', 'leaf']))
    for name in (*configs, 'server.csr', 'maintenance.csr'): os.unlink(name, dir_fd=fd)
    for name in PEM_FILES:
        file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try: os.fsync(file)
        finally: os.close(file)
    write_new(fd, 'candidate.json', encoded(receipt(fd)))


def inspect(fd):
    owned(os.fstat(fd), 0o700)
    require(set(os.listdir(fd)) == set(FILES), 'TLS_CANDIDATE_INCOMPLETE_OR_UNKNOWN_FILES')
    before = {name: read_file(fd, name) for name in FILES}
    require(before['candidate.json'] == encoded(receipt(fd)), 'TLS_CANDIDATE_RECEIPT_MISMATCH')
    public_keys = []
    for prefix in ('ca', 'server', 'maintenance'):
        key = openssl(fd, ['pkey', '-in', prefix + '.key', '-pubout'])
        cert_key = openssl(fd, ['x509', '-in', prefix + '.pem', '-pubkey', '-noout'])
        require(key == cert_key, 'TLS_CERTIFICATE_KEY_MISMATCH')
        info = openssl(fd, ['pkey', '-in', prefix + '.key', '-text_pub', '-noout'])
        require(re.match(rb'(?:RSA )?Public-Key: \(3072 bit\)\nModulus:', info) is not None,
                'TLS_KEY_PROFILE_INVALID')
        constraints = openssl(fd, ['x509', '-in', prefix + '.pem', '-ext', 'basicConstraints', '-noout'])
        expected = b'CA:TRUE, pathlen:0' if prefix == 'ca' else b'CA:FALSE'
        require(constraints.strip().endswith(expected) and b'critical' in constraints,
                'TLS_CERTIFICATE_PROFILE_INVALID')
        if prefix != 'ca':
            purpose = openssl(fd, ['x509', '-in', prefix + '.pem', '-ext', 'extendedKeyUsage', '-noout'])
            expected = b'TLS Web Server Authentication' if prefix == 'server' else b'TLS Web Client Authentication'
            require(purpose.strip().splitlines()[-1].strip() == expected, 'TLS_CERTIFICATE_PROFILE_INVALID')
        public_keys.append(key)
    require(len(set(public_keys)) == 3, 'TLS_PRIVATE_KEYS_NOT_INDEPENDENT')
    openssl(fd, ['verify', '-x509_strict', '-check_ss_sig', '-CAfile', 'ca.pem', 'ca.pem'])
    openssl(fd, ['verify', '-x509_strict', '-purpose', 'sslserver', '-verify_hostname', SERVER_NAME,
                 '-CAfile', 'ca.pem', 'server.pem'])
    san = openssl(fd, ['x509', '-in', 'server.pem', '-ext', 'subjectAltName', '-noout'])
    require(san.strip().splitlines()[-1].strip() == ('DNS:' + SERVER_NAME).encode(),
            'TLS_SERVER_NAME_INVALID')
    openssl(fd, ['verify', '-x509_strict', '-purpose', 'sslclient', '-CAfile', 'ca.pem', 'maintenance.pem'])
    subject = openssl(fd, ['x509', '-in', 'maintenance.pem', '-subject', '-noout', '-nameopt', 'RFC2253'])
    require(subject.strip() == ('subject=CN=' + CLIENT_NAME).encode(), 'TLS_MAINTENANCE_IDENTITY_INVALID')
    # Require at least one day remaining; renewal is a separate explicit unit.
    for prefix in ('ca', 'server', 'maintenance'):
        openssl(fd, ['x509', '-in', prefix + '.pem', '-checkend', '86400', '-noout'])
    require({name: read_file(fd, name) for name in FILES} == before, 'TLS_CANDIDATE_CHANGED')
    return before


def contexts(fd):
    path = '/proc/self/fd/' + str(fd) + '/'
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version = ssl.TLSVersion.TLSv1_2
    server.verify_mode = ssl.CERT_REQUIRED
    server.load_verify_locations(cafile=path + 'ca.pem')
    server.load_cert_chain(path + 'server.pem', path + 'server.key')
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.minimum_version = ssl.TLSVersion.TLSv1_2
    client.load_verify_locations(cafile=path + 'ca.pem')
    client.load_cert_chain(path + 'maintenance.pem', path + 'maintenance.key')
    return server, client


def exchange(server_context, client_context, server_name=SERVER_NAME):
    # A real SSL exchange on a Unix socketpair: no listening port, DB, Docker
    # session or service probing. Application bytes force TLS1.3 alerts to surface.
    left, right = socket.socketpair()
    left.settimeout(4); right.settimeout(4)
    outcome = {}
    def serve():
        try:
            with server_context.wrap_socket(left, server_side=True) as stream:
                outcome['client_sha256'] = sha(stream.getpeercert(binary_form=True))
                require(stream.recv(1) == b'?','TLS_PROBE_INVALID')
                stream.sendall(b'!')
        except (ssl.SSLError, OSError, CandidateError):
            outcome['server_failed'] = True
        finally: left.close()
    worker = threading.Thread(target=serve, daemon=True); worker.start()
    try:
        with client_context.wrap_socket(right, server_hostname=server_name) as stream:
            stream.sendall(b'?'); require(stream.recv(1) == b'!', 'TLS_PROBE_INVALID')
            outcome['server_sha256'] = sha(stream.getpeercert(binary_form=True))
            outcome['tls_version'] = stream.version()
    except (ssl.SSLError, OSError, CandidateError):
        outcome['client_failed'] = True
    finally:
        right.close(); worker.join(5)
    require(not worker.is_alive(), 'TLS_PROBE_DID_NOT_FINISH')
    return outcome


def probe(fd, snapshot):
    server, client = contexts(fd)
    result = exchange(server, client)
    server_der = ssl.PEM_cert_to_DER_cert(snapshot['server.pem'].decode())
    client_der = ssl.PEM_cert_to_DER_cert(snapshot['maintenance.pem'].decode())
    require(result.get('server_sha256') == sha(server_der)
            and result.get('client_sha256') == sha(client_der)
            and result.get('tls_version') in ('TLSv1.2', 'TLSv1.3')
            and not result.get('server_failed') and not result.get('client_failed'),
            'TLS_CANDIDATE_EXCHANGE_FAILED')
    wrong_name = exchange(*contexts(fd), server_name='wrong.vms.internal')
    require(wrong_name.get('client_failed') is True, 'TLS_WRONG_HOSTNAME_NOT_REJECTED')
    untrusted = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    untrusted.minimum_version = ssl.TLSVersion.TLSv1_2
    require(exchange(contexts(fd)[0], untrusted).get('client_failed') is True,
            'TLS_UNTRUSTED_CA_NOT_REJECTED')
    no_certificate = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    no_certificate.minimum_version = ssl.TLSVersion.TLSv1_2
    no_certificate.load_verify_locations(cadata=snapshot['ca.pem'].decode())
    require(exchange(contexts(fd)[0], no_certificate).get('client_failed') is True,
            'TLS_MISSING_CLIENT_CERTIFICATE_NOT_REJECTED')
    require({name: read_file(fd, name) for name in FILES} == snapshot, 'TLS_CANDIDATE_CHANGED')
    return {'actual_socketpair_mtls_verified': True, 'wrong_hostname_rejected': True,
            'untrusted_ca_rejected': True, 'missing_client_certificate_rejected': True,
            'tls_version': result['tls_version'], 'server_certificate_sha256': sha(server_der),
            'maintenance_certificate_sha256': sha(client_der), 'ca_pem_sha256': sha(snapshot['ca.pem'])}


def prepare(root, apply=False):
    try: fd, path = directory(root, apply)
    except FileNotFoundError:
        if apply: raise
        return {'status': 'not_prepared', 'scope': SCOPE, 'code': 'EXPLICIT_APPLY_REQUIRED', **NO_CHANGES}
    lock = candidate = None
    try:
        lock = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_CREAT if apply else 0),
                       0o600, dir_fd=fd)
        owned(os.fstat(lock), 0o600, True)
        try: fcntl.flock(lock, (fcntl.LOCK_EX if apply else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError: raise CandidateError('TLS_PREPARATION_LOCKED') from None
        require(set(os.listdir(fd)) <= {LOCK, CANDIDATE}, 'TLS_CANDIDATE_DIRECTORY_INVALID')
        created = False
        try: candidate = os.open(CANDIDATE, DIR_FLAGS, dir_fd=fd)
        except FileNotFoundError:
            if not apply:
                return {'status': 'not_prepared', 'scope': SCOPE, 'code': 'EXPLICIT_APPLY_REQUIRED', **NO_CHANGES}
            require(shutil.which('openssl', path=os.defpath) is not None, 'OPENSSL_REQUIRED')
            os.mkdir(CANDIDATE, 0o700, dir_fd=fd)
            candidate = os.open(CANDIDATE, DIR_FLAGS, dir_fd=fd)
            owned(os.fstat(candidate), 0o700)
            generate(candidate); created = True
        snapshot = inspect(candidate)
        proof = probe(candidate, snapshot)
        # Reopen the path chain after signing/probing to reject directory replacement.
        current, _ = directory(root, False)
        with contextlib.ExitStack() as cleanup:
            cleanup.callback(os.close, current)
            reopened = os.open(CANDIDATE, DIR_FLAGS, dir_fd=current)
            cleanup.callback(os.close, reopened)
            for old, new in ((fd, current), (candidate, reopened)):
                a, b = os.fstat(old), os.fstat(new)
                require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), 'TLS_CANDIDATE_PATH_CHANGED')
            require({name: read_file(reopened, name) for name in FILES} == snapshot,
                    'TLS_CANDIDATE_CHANGED')
        os.fsync(fd)
        return {'status': 'prepared' if created else ('already_prepared' if apply else 'validated'),
                'scope': SCOPE, 'candidate_directory': str(path / CANDIDATE),
                'candidate_sha256': sha(snapshot['candidate.json']), 'candidate_ready': True,
                'directory_permissions': '0700', 'file_permissions': '0600',
                'existing_candidate_preserved': not created, 'server_name': SERVER_NAME,
                'maintenance_common_name': CLIENT_NAME, 'endpoint_state': 'proposal-unreserved',
                'candidate_private_keys_loaded_for_local_probe': True, **proof, **NO_CHANGES}
    finally:
        if candidate is not None: os.close(candidate)
        if lock is not None: os.close(lock)
        os.close(fd)


def checked_revision(root):
    import test_camera_credential_storage as storage
    try: revision = storage.checked_project(root)
    except storage.VerificationError as exc: raise CandidateError(str(exc)) from None
    value = json.loads((root / 'project-manifest.json').read_text())
    require(value.get('credential_management_http_server_verified') is True
            and value.get('validated_credential_management_http_project_sha256') ==
            '0b2891f179dddca6d3e43a09e253c915b7babd32b8a437fc6d61b5d3f4dd50aa'
            and value.get('credential_tls_candidate_preparation_implemented') is True
            and value.get('credential_management_http_registered_in_current_main') is False,
            'TLS_CANDIDATE_PROJECT_REQUIRED')
    require('src/infra/tools/prepare_camera_database_tls_candidate.py' in value['files'],
            'TLS_CANDIDATE_PROJECT_REQUIRED')
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        revision = checked_revision(args.project_root)
        result = prepare(args.project_root, args.apply)
        result['checked_revision'] = revision
        print(json.dumps(result))
        return 2 if result['status'] == 'not_prepared' else 0
    except Exception as exc:
        # Public output never includes OpenSSL stderr, PEM, DSNs or arbitrary paths.
        code = str(exc) if isinstance(exc, CandidateError) else 'TLS_CANDIDATE_UNAVAILABLE'
        if not re.fullmatch('[A-Z][A-Z0-9_]{1,80}', code): code = 'TLS_CANDIDATE_UNAVAILABLE'
        print(json.dumps({'status': 'failed', 'scope': SCOPE, 'code': code, **NO_CHANGES}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
