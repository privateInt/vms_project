#!/usr/bin/env python3
"""Check real HTTP processes. --launch builds and starts isolated local Go services."""
import argparse
import copy
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
PLATFORMS = ('camera', 'model', 'analysis', 'operation')


def read_env():
    path = ROOT / '.env'
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({k:v for k,v in os.environ.items() if k.startswith('VMS_')})
    return values


def call(base, path, token=None, body=None, method=None, media='application/json', key=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    request = Request(base+path, data=data, method=method or ('POST' if data is not None else 'GET'))
    if token is not None:
        request.add_header('Authorization', 'Bearer '+token)
    if data is not None:
        request.add_header('Content-Type', media)
    if key is not None:
        request.add_header('Idempotency-Key', key)
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.load(response), response.headers


def checks(bases, token):
    passed = []
    def expect(label, result, status, predicate=lambda value: True):
        code, value, headers = result
        if code != status or not predicate(value) or not headers.get('X-Request-ID'):
            raise RuntimeError(f'{label}: expected HTTP {status}, received {code} or unexpected response')
        passed.append(label)
    for name, base in bases.items():
        expect(name+'.live', call(base, '/health/live'), 200, lambda v:v['platform']==name)
        ready_scopes = {'http_api_foundation', 'camera_registry'} if name == 'camera' else {'http_api_foundation'}
        expect(name+'.ready_scope', call(base, '/health/ready'), 200, lambda v:v['ready'] and v['scope'] in ready_scopes and v['business_runtime_ready'] is False)
        expect(name+'.unauthorized', call(base, '/api/v1/platform'), 401)
        expect(name+'.wrong_token', call(base, '/api/v1/platform', 'wrong-token'), 401)
        expected_stage = 'P1_DEVICE_DELETE' if name == 'camera' else 'P0_API_FOUNDATION'
        expect(name+'.manifest', call(base, '/api/v1/platform', token), 200, lambda v:v['platform']==name and v['stage']==expected_stage)
        expect(name+'.openapi', call(base, '/openapi.json'), 200, lambda v:v['openapi']=='3.1.0')
        expect(name+'.unknown_route', call(base, '/api/v1/not-implemented', token), 404)
    camera, analysis = bases['camera'], bases['analysis']
    update_path = '/api/v1/devices/smoke-device'
    update = {'schema_version': 'v1', 'expected_version': 1, 'display_name': 'smoke'}
    expect('device_update.auth', call(camera, update_path, body=update, method='PATCH'), 401)
    expect('device_update.key', call(camera, update_path, token, update, method='PATCH'), 400, lambda v:v['error']['code']=='IDEMPOTENCY_KEY_INVALID')
    expect('device_update.integer_token', call(camera, update_path, token, b'{"schema_version":"v1","expected_version":1.0,"display_name":"smoke"}', method='PATCH', key='smoke-update'), 400, lambda v:v['error']['code']=='INVALID_JSON')
    update['expected_version'] = 0
    expect('device_update.version', call(camera, update_path, token, update, method='PATCH', key='smoke-update'), 422, lambda v:v['error']['code']=='CONTRACT_INVALID')
    update_path = '/api/v1/sources/smoke-source'
    update = {'schema_version': 'v1', 'expected_version': 1, 'display_name': 'smoke'}
    expect('source_update.auth', call(camera, update_path, body=update, method='PATCH'), 401)
    expect('source_update.key', call(camera, update_path, token, update, method='PATCH'), 400, lambda v:v['error']['code']=='IDEMPOTENCY_KEY_INVALID')
    expect('source_update.integer_token', call(camera, update_path, token, b'{"schema_version":"v1","expected_version":1e0,"display_name":"smoke"}', method='PATCH', key='smoke-source-update'), 400, lambda v:v['error']['code']=='INVALID_JSON')
    update['expected_version'] = 0
    expect('source_update.version', call(camera, update_path, token, update, method='PATCH', key='smoke-source-update'), 422, lambda v:v['error']['code']=='CONTRACT_INVALID')
    reserved = call(camera, '/api/v1/sources/%76alidate', token, update, method='PATCH', key='smoke-source-update')
    expect('source_update.reserved', reserved, 405, lambda v:v['error']['code']=='METHOD_NOT_ALLOWED')
    if reserved[2].get('Allow') != 'POST':
        raise RuntimeError('source_update.reserved: Allow changed')
    delete_path = '/api/v1/sources/smoke-source'
    deletion = {'schema_version': 'v1', 'expected_version': 1}
    expect('source_delete.auth', call(camera, delete_path, body=deletion, method='DELETE'), 401)
    expect('source_delete.key', call(camera, delete_path, token, deletion, method='DELETE'), 400, lambda v:v['error']['code']=='IDEMPOTENCY_KEY_INVALID')
    expect('source_delete.integer_token', call(camera, delete_path, token, b'{"schema_version":"v1","expected_version":1.0}', method='DELETE', key='smoke-source-delete'), 400, lambda v:v['error']['code']=='INVALID_JSON')
    deletion['expected_version'] = 0
    expect('source_delete.version', call(camera, delete_path, token, deletion, method='DELETE', key='smoke-source-delete'), 422, lambda v:v['error']['code']=='CONTRACT_INVALID')
    reserved = call(camera, '/api/v1/sources/%76alidate', token, deletion, method='DELETE', key='smoke-source-delete')
    expect('source_delete.reserved', reserved, 405, lambda v:v['error']['code']=='METHOD_NOT_ALLOWED')
    if reserved[2].get('Allow') != 'POST':
        raise RuntimeError('source_delete.reserved: Allow changed')
    delete_path = '/api/v1/devices/validate'
    deletion = {'schema_version': 'v1', 'expected_version': 1}
    expect('device_delete.auth', call(camera, delete_path, body=deletion, method='DELETE'), 401)
    expect('device_delete.key', call(camera, delete_path, token, deletion, method='DELETE'), 400, lambda v:v['error']['code']=='IDEMPOTENCY_KEY_INVALID')
    expect('device_delete.integer_token', call(camera, delete_path, token, b'{"schema_version":"v1","expected_version":1e0}', method='DELETE', key='smoke-device-delete'), 400, lambda v:v['error']['code']=='INVALID_JSON')
    deletion['expected_version'] = 0
    expect('device_delete.version', call(camera, delete_path, token, deletion, method='DELETE', key='smoke-device-delete'), 422, lambda v:v['error']['code']=='CONTRACT_INVALID')
    # An omitted DELETE body must not turn into an unconditional deletion.
    expect('device_delete.no_body', call(camera, delete_path, token, b'', method='DELETE', key='smoke-device-delete'), 400, lambda v:v['error']['code']=='INVALID_JSON')
    source_path = '/api/v1/sources/validate'
    for filename in ('source-cctv.json', 'source-xr.json'):
        source = json.loads((ROOT/'src/platform/camera/api/examples'/filename).read_text())
        expect(filename, call(camera, source_path, token, source), 200, lambda v:v['valid'] and not v['resource_created'] and not v['runtime_verified'])
    source['input_mode'] = 'PULL'
    expect('xr.invalid_mode', call(camera, source_path, token, source), 422)
    expect('source.wrong_method', call(camera, source_path, token), 405)
    expect('source.unknown_field', call(camera, source_path, token, {'unknown':True}), 400)
    expect('source.body_limit', call(camera, source_path, token, b'{"display_name":"'+b'x'*65536+b'"}'), 413)
    expect('source.media_type', call(camera, source_path, token, {}, media='text/plain'), 415)
    job_path = '/api/v1/analysis-jobs/validate'
    job = json.loads((ROOT/'src/platform/analysis/api/examples/analysis-job-xr.json').read_text())
    expect('job.xr', call(analysis, job_path, token, job), 200, lambda v:v['valid'] and not v['references_verified'])
    unpinned = copy.deepcopy(job)
    del unpinned['deployment_refs'][0]['model_version_id']
    expect('job.unpinned_version', call(analysis, job_path, token, unpinned), 422)
    duplicate = copy.deepcopy(job)
    duplicate['deployment_refs'].append(duplicate['deployment_refs'][0])
    expect('job.duplicate_role', call(analysis, job_path, token, duplicate), 422)
    job['generation'] = 0
    expect('job.invalid_generation', call(analysis, job_path, token, job), 422)
    return passed


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def launch(go):
    token = secrets.token_urlsafe(36)
    processes, logs, bases = [], [], {}
    with tempfile.TemporaryDirectory(prefix='vms-smoke-') as temporary:
        try:
            for name in PLATFORMS:
                binary = str(Path(temporary)/(name+'-api'))
                subprocess.run([go,'build','-buildvcs=false','-trimpath','-o',binary,f'./{name}/cmd/{name}-api'],cwd=ROOT/'src/platform',check=True,timeout=180)
                port = unused_port()
                env = dict(os.environ, VMS_API_TOKEN=token, HTTP_ADDR=f'127.0.0.1:{port}')
                env.pop('CAMERA_DATABASE_URL', None)
                env.pop('CAMERA_DATABASE_URL_FILE', None)
                log = open(Path(temporary)/(name+'.log'),'wb')
                logs.append(log)
                proc = subprocess.Popen([binary],env=env,stdout=log,stderr=log)
                processes.append(proc)
                base = f'http://127.0.0.1:{port}'
                bases[name] = base
                deadline = time.monotonic()+10
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(f'{name} exited before readiness')
                    try:
                        if call(base,'/health/ready')[0]==200:
                            break
                    except (URLError, TimeoutError, ConnectionError):
                        pass
                    if time.monotonic()>deadline:
                        raise RuntimeError(f'{name} readiness timed out')
                    time.sleep(0.05)
                subprocess.run([binary,'--healthcheck'],env=env,check=True,timeout=5)
            passed = checks(bases, token)
            for name,proc in zip(PLATFORMS, processes):
                proc.send_signal(signal.SIGTERM)
                if proc.wait(timeout=8)!=0:
                    raise RuntimeError(f'{name} did not shut down cleanly')
                passed.append(name+'.graceful_shutdown')
            return passed
        finally:
            for proc in processes:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            for log in logs:
                log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--go', default='go')
    parser.add_argument('--host', default='127.0.0.1', help='Host for an already-running Compose stack')
    args = parser.parse_args()
    try:
        if args.launch:
            passed = launch(args.go)
        else:
            env = read_env()
            token = env.get('VMS_API_TOKEN','')
            if len(token)<24 or token.startswith('CHANGE_ME'):
                raise RuntimeError('Create a valid local .env first')
            bases = {name:f'http://{args.host}:{int(env.get("VMS_"+name.upper()+"_PORT",18081+i))}' for i,name in enumerate(PLATFORMS)}
            passed = checks(bases,token)
        print(json.dumps({'status':'passed','checks':len(passed),'scope':'http_api_and_contracts','business_runtime_verified':False,'passed':passed},ensure_ascii=False,indent=2))
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Smoke check failed: {exc}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
