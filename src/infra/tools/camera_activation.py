"""Camera-only activation primitives shared with the disposable Docker checker."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

ACTIVE = './src/platform/camera/compose.active.yaml'
BASE = './src/platform/camera/compose.yaml'
FLAG = 'VMS_CAMERA_COMPOSE_FILE'
DATABASE_IMAGE = 'postgres:17.11-bookworm'
MANAGED = {'camera-api', 'camera-db', 'camera-migrate'}


class ActivationError(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ActivationError('SYMLINK_PATH_REJECTED')


def private_directory(path):
    safe(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ActivationError('PRIVATE_DIRECTORY_MUST_BE_OWNED_AND_MODE_0700')


def atomic_write(path, body, mode=0o600):
    safe(path)
    fd, name = tempfile.mkstemp(prefix='.camera-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def activation_lock(root):
    directory = root / 'var/camera'
    private_directory(directory)
    path = directory / 'activation.lock'
    safe(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ActivationError('ANOTHER_ACTIVATION_IS_RUNNING') from None
        yield


def enabled_environment(body):
    text = body.decode('utf-8')
    if re.search(r'^\s*(?:export\s+)?(?:VMS_CAMERA_IMAGE|COMPOSE_FILE|COMPOSE_PROJECT_NAME)\s*=', text, re.M):
        raise ActivationError('CUSTOM_COMPOSE_CONFIGURATION_REQUIRES_REVIEW')
    matches = re.findall(r'^\s*(?:export\s+)?VMS_CAMERA_COMPOSE_FILE\s*=\s*(.*?)\s*$', text, re.M)
    if matches:
        if len(matches) != 1 or matches[0].strip('\"\'') != ACTIVE:
            raise ActivationError('EXISTING_CAMERA_COMPOSE_SETTING_CONFLICTS')
        return body
    return body + (b'\n' if body and not body.endswith(b'\n') else b'') + (FLAG+'='+ACTIVE+'\n').encode()


def verify_project(root):
    safe(root)
    manifest = root / 'project-manifest.json'
    data = json.loads(manifest.read_text())
    if data.get('activation_revision') != 'step04-camera-activation-20260930':
        raise ActivationError('STEP04_PROJECT_REQUIRED')
    for relative, expected in data['files'].items():
        path = root / relative
        safe(path)
        if not path.is_file() or sha(path) != expected:
            raise ActivationError('PROJECT_FILE_CHANGED: '+relative)
    return sha(manifest)


def prepare_secrets(root, volume_exists):
    directory = root / 'var/camera/secrets'
    safe(directory)
    names = ('admin-password', 'migration-password', 'runtime-password')
    if not directory.exists():
        if volume_exists:
            raise ActivationError('EXISTING_VOLUME_WITHOUT_MATCHING_SECRETS')
        temporary = Path(tempfile.mkdtemp(prefix='.secrets-', dir=directory.parent))
        try:
            values = {name: secrets.token_hex(32) for name in names}
            values['migration-dsn'] = 'postgres://camera_migrator:'+values['migration-password']+'@camera-db:5432/vms_camera?sslmode=disable'
            values['runtime-dsn'] = 'postgres://camera_runtime:'+values['runtime-password']+'@camera-db:5432/vms_camera?sslmode=disable'
            for name, value in values.items():
                # File bind mounts retain host mode. The parent is private 0700;
                # individual read-only mounts are readable by container UID 65532.
                atomic_write(temporary/name, (value+'\n').encode(), 0o444)
            atomic_write(temporary/'identity.json', b'{"format":1,"database":"vms_camera"}\n')
            os.rename(temporary, directory)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    private_directory(directory)
    values = {}
    for name in (*names, 'migration-dsn', 'runtime-dsn', 'identity.json'):
        path = directory/name
        safe(path)
        if not path.is_file() or path.stat().st_uid != os.getuid():
            raise ActivationError('SECRET_SET_INCOMPLETE_OR_WRONG_OWNER')
        mode = 0o600 if name == 'identity.json' else 0o444
        if stat.S_IMODE(path.stat().st_mode) != mode:
            raise ActivationError('SECRET_FILE_MODE_MISMATCH')
        values[name] = path.read_text().strip()
    if json.loads(values['identity.json']) != {'format':1,'database':'vms_camera'}:
        raise ActivationError('SECRET_IDENTITY_MISMATCH')
    if any(not re.fullmatch('[0-9a-f]{64}', values[name]) for name in names):
        raise ActivationError('SECRET_VALUE_INVALID')
    for prefix, role in [('migration','camera_migrator'),('runtime','camera_runtime')]:
        expected = 'postgres://'+role+':'+values[prefix+'-password']+'@camera-db:5432/vms_camera?sslmode=disable'
        if values[prefix+'-dsn'] != expected:
            raise ActivationError('SECRET_DSN_MISMATCH')
    return values


class Docker:
    def __init__(self, root, project='vms-project'):
        self.root = root
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]+', project):
            raise ActivationError('INVALID_PROJECT_NAME')
        self.project = project
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('COMPOSE_', 'VMS_', 'CAMERA_', 'PG'))}
        self.redact = []

    def run(self, args, *, input=None, stdout=None, timeout=120, extra=None):
        env = dict(self.env)
        env.update(extra or {})
        try:
            result = subprocess.run(['docker', *args], cwd=self.root, env=env,
                                    input=input, stdout=stdout or subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise ActivationError('DOCKER_COMMAND_UNAVAILABLE_OR_TIMEOUT') from None
        if result.returncode:
            detail = result.stderr.decode(errors='replace')
            for value in self.redact:
                detail = detail.replace(value, '[redacted]')
            raise ActivationError('DOCKER_COMMAND_FAILED: '+detail[-1500:].strip())
        return result.stdout or b''

    def compose(self, args, *, active=True, image=None, **kwargs):
        extra = {FLAG: ACTIVE} if active else {}
        if image:
            extra['VMS_CAMERA_IMAGE'] = image
        return self.run(['compose', '--project-name', self.project, '--project-directory', str(self.root),
                         '--env-file', str(self.root/'.env'), '--file', str(self.root/'compose.yaml'), *args], extra=extra, **kwargs)

    def preflight(self):
        if not shutil.which('docker'):
            raise ActivationError('DOCKER_REQUIRED')
        host = self.env.get('DOCKER_HOST')
        if not host or self.env.get('DOCKER_CONTEXT'):
            data = json.loads(self.run(['context','inspect']))
            host = data[0]['Endpoints']['docker']['Host']
        if not host.startswith('unix://'):
            raise ActivationError('LOCAL_UNIX_DOCKER_REQUIRED')
        daemon = self.run(['info','--format','{{.ID}}']).decode().strip()
        if not daemon:
            raise ActivationError('DOCKER_DAEMON_ID_UNAVAILABLE')
        for name in ('compose.override.yaml','compose.override.yml','docker-compose.override.yml','docker-compose.override.yaml'):
            if (self.root/name).exists():
                raise ActivationError('CUSTOM_COMPOSE_OVERRIDE_REQUIRES_REVIEW')
        return daemon

    def snapshot(self):
        ids = self.run(['ps','-aq','--filter','label=com.docker.compose.project='+self.project]).decode().split()
        if not ids:
            return {}
        result = {}
        for obj in json.loads(self.run(['inspect', *ids])):
            labels = obj['Config'].get('Labels') or {}
            if labels.get('com.docker.compose.project.working_dir') != str(self.root):
                raise ActivationError('PROJECT_CONTAINER_BELONGS_TO_ANOTHER_DIRECTORY')
            service = labels.get('com.docker.compose.service','')
            if service == 'camera-migrate':
                continue
            if service in result:
                raise ActivationError('MULTIPLE_CONTAINERS_FOR_SERVICE')
            result[service] = {'id':obj['Id'],'image':obj['Image'], 'started_at':obj['State']['StartedAt'],
                               'running':obj['State']['Running'],'restarts':obj['RestartCount']}
        return result

    def volume_exists(self):
        name = self.project+'_camera-data'
        names = self.run(['volume','ls','--format','{{.Name}}','--filter','name=^'+name+'$']).decode().split()
        if not names:
            return False
        data = json.loads(self.run(['volume','inspect',name]))[0]
        labels = data.get('Labels') or {}
        if labels.get('com.docker.compose.project') != self.project or labels.get('com.docker.compose.volume') != 'camera-data':
            raise ActivationError('VOLUME_OWNERSHIP_MISMATCH')
        return True


def protected(snapshot):
    return {k:v for k,v in snapshot.items() if k not in MANAGED}


def config_endpoint(config):
    service = config['services']['camera-api']
    candidates = [p for p in service.get('ports',[]) if p['target']==8080]
    if len(candidates)!=1:
        raise ActivationError('CAMERA_HTTP_PORT_AMBIGUOUS')
    port = candidates[0]
    host = port.get('host_ip') or '127.0.0.1'
    if host in ('0.0.0.0','::'):
        host = '127.0.0.1'
    if ':' in host:
        host = '['+host+']'
    published = int(port['published'])
    if not 1<=published<=65535:
        raise ActivationError('CAMERA_HTTP_PORT_INVALID')
    return 'http://'+host+':'+str(published), service['environment']['VMS_API_TOKEN']


def request(base, path, token=None, body=None, key=None):
    data = json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    req = Request(base+path,data=data)
    if token:
        req.add_header('Authorization','Bearer '+token)
    if data is not None:
        req.add_header('Content-Type','application/json')
    if key:
        req.add_header('Idempotency-Key',key)
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        response = build_opener(ProxyHandler({}), NoRedirect()).open(req,timeout=3)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.load(response), response.headers


def verify_api(base, token):
    deadline = time.monotonic()+45
    while time.monotonic()<deadline:
        try:
            code,value,_ = request(base,'/health/ready')
            if code==200 and value.get('scope')=='camera_registry' and value.get('ready') and value.get('business_runtime_ready') is False:
                break
        except (URLError, OSError, ValueError):
            pass
        time.sleep(0.25)
    else:
        raise ActivationError('CAMERA_REGISTRY_READINESS_FAILED')
    code,value,_ = request(base,'/api/v1/devices?limit=1',token)
    if code!=200 or not isinstance(value.get('items'),list):
        raise ActivationError('DEVICE_READ_FAILED')
    code,value,_ = request(base,'/api/v1/platform',token)
    if code!=200 or value.get('capabilities',{}).get('device_registry')!='implemented':
        raise ActivationError('DEVICE_CAPABILITY_NOT_ENABLED')


def backup_database(docker, directory):
    path = directory/'camera.pgdump'
    fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        docker.compose(['exec','-T','camera-db','pg_dump','-U','camera_admin','-d','vms_camera','-Fc'],stdout=stream,timeout=300)
        stream.flush();os.fsync(stream.fileno())
    if path.read_bytes()[:5]!=b'PGDMP':
        raise ActivationError('DATABASE_BACKUP_INVALID')
    docker.compose(['exec','-T','camera-db','pg_restore','--list'],input=path.read_bytes())
    return path


def activate(root, docker):
    """Caller holds activation_lock and has verified the native-check receipt."""
    env_path = root/'.env';safe(env_path)
    if not env_path.is_file():
        raise ActivationError('EXISTING_ENV_REQUIRED')
    original = env_path.read_bytes()
    desired = enabled_environment(original)
    before = docker.snapshot()
    values = prepare_secrets(root,docker.volume_exists())
    docker.redact.extend(values.values())
    config = json.loads(docker.compose(['config','--format','json']))
    candidate_image=config['services']['camera-api']['image']
    if candidate_image!=docker.project+'-camera-control:step04':
        raise ActivationError('UNEXPECTED_CAMERA_IMAGE_TAG')
    base,token = config_endpoint(config)
    docker.redact.append(token)
    if len(token)<24 or token.startswith('CHANGE_ME'):
        raise ActivationError('VALID_EXISTING_API_TOKEN_REQUIRED')
    backup_root = root/'var/camera/activation-backups';private_directory(backup_root)
    directory = Path(tempfile.mkdtemp(prefix='step04-',dir=backup_root))
    atomic_write(directory/'env.before',original)
    atomic_write(directory/'containers.before.json',json.dumps(before,indent=2).encode())
    old_camera = before.get('camera-api')
    switched = False
    changed_env = False
    built = False
    try:
        print('camera activation: build camera image',flush=True)
        docker.compose(['build','camera-api'],timeout=900)
        built=True
        print('camera activation: start private persistent database',flush=True)
        docker.compose(['up','-d','--no-deps','--wait','--wait-timeout','90','camera-db'],timeout=150)
        backup = backup_database(docker,directory)
        print('camera activation: migrate and grant runtime access',flush=True)
        migration = json.loads(docker.compose(['run','--rm','--no-deps','camera-migrate'],timeout=90))
        if migration.get('version')!=2:
            raise ActivationError('UNEXPECTED_SCHEMA_VERSION')
        if protected(docker.snapshot())!=protected(before):
            raise ActivationError('OTHER_SERVICES_CHANGED_BEFORE_SWITCH')
        if env_path.read_bytes()!=original:
            raise ActivationError('ENV_CHANGED_DURING_ACTIVATION')
        if desired!=original:
            atomic_write(env_path,desired,stat.S_IMODE(env_path.stat().st_mode));changed_env=True
        switched=True
        print('camera activation: switch camera API',flush=True)
        docker.compose(['up','-d','--no-deps','--no-build','--wait','--wait-timeout','60','camera-api'],timeout=100)
        verify_api(base,token)
        after=docker.snapshot()
        if protected(after)!=protected(before):
            raise ActivationError('OTHER_SERVICES_CHANGED_DURING_ACTIVATION')
        result={'status':'activated','scope':'camera_device_registry','project':docker.project,
                'endpoint':base,'schema_version':2,'migration_applied':migration.get('applied'),
                'backup':str(backup),'other_services_unchanged':True,'business_runtime_ready':False}
        atomic_write(directory/'result.json',json.dumps(result,indent=2).encode())
        return result
    except BaseException as exc:
        recovery='not_needed'
        if switched or changed_env or (built and old_camera):
            try:
                expected_env=desired if changed_env else original
                if env_path.read_bytes()!=expected_env:
                    raise ActivationError('CONCURRENT_ENV_EDIT_PRESERVED')
                if changed_env:
                    atomic_write(env_path,original,stat.S_IMODE(env_path.stat().st_mode))
                if built and old_camera:
                    docker.run(['image','tag',old_camera['image'],candidate_image])
                if switched:
                    if old_camera:
                        docker.compose(['up','-d','--no-deps','--no-build','camera-api'],active=False,image=old_camera['image'])
                        if not old_camera['running']:
                            docker.compose(['stop','camera-api'],active=False)
                        restored = docker.snapshot().get('camera-api', {})
                        if restored.get('image') != old_camera['image'] or restored.get('running') != old_camera['running']:
                            raise ActivationError('PREVIOUS_CAMERA_STATE_NOT_RESTORED')
                    else:
                        docker.compose(['rm','--stop','--force','camera-api'])
                recovery='previous_camera_configuration_restored'
            except BaseException:
                recovery='manual_recovery_required'
        record={'status':'failed','recovery':recovery,'backup_directory':str(directory),
                'database_and_secrets_retained':True,'automatic_database_restore':False}
        atomic_write(directory/'result.json',json.dumps(record,indent=2).encode())
        print(json.dumps(record),flush=True)
        raise exc
