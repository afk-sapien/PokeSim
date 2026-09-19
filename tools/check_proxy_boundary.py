"""Verify the real authenticated TLS proxy using disposable containers and data."""
import argparse
import base64
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, ProxyHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[1]


def available_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    args = parser.parse_args()
    project = 'pokesim-security-' + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    hashed = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none',
        'caddy:2.11.4-alpine', 'caddy', 'hash-password', '--plaintext', password], text=True).strip()
    port = available_port()
    origin = f'https://localhost:{port}'
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        root = Path(temporary)
        override = root / 'compose.json'
        override.write_text(json.dumps({
            'services': {'pokesim': {'volumes': ['application-data:/data'],
                                      'healthcheck': {'interval': '2s'}}},
            'volumes': {'application-data': {}},
        }))
        empty = root / 'empty.env'
        empty.write_text('')
        env = {**os.environ, 'POKESIM_IMAGE': args.image, 'DATA_PATH': str(root / 'unused'),
               'PUBLIC_URL': origin, 'SITE_ADDRESS': 'localhost', 'PROXY_BIND_ADDRESS': '127.0.0.1',
               'PROXY_HTTPS_PORT': str(port), 'PROXY_HTTP_PORT': '0', 'AUTH_USER': 'security-test',
               'AUTH_HASH': hashed}
        command = ['docker', 'compose', '-p', project, '--env-file', str(empty),
                   '-f', str(ROOT / 'compose.proxy.yaml'), '-f', str(override)]

        def compose(*arguments, timeout=120):
            return subprocess.check_output([*command, *arguments], env=env, text=True,
                                           stderr=subprocess.STDOUT, timeout=timeout).strip()

        try:
            compose('build', '--pull', 'proxy', timeout=600)
            compose('up', '-d', '--wait', '--wait-timeout', '60')
            proxy = compose('ps', '-q', 'proxy')
            certificate = root / 'root.crt'
            for attempt in range(30):
                copied = subprocess.run(['docker', 'cp',
                    f'{proxy}:/data/caddy/pki/authorities/local/root.crt', str(certificate)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if copied.returncode == 0:
                    break
                time.sleep(0.2)
            context = ssl.create_default_context(cafile=str(certificate))
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), HTTPCookieProcessor(CookieJar()))
            authorization = 'Basic ' + base64.b64encode(f'security-test:{password}'.encode()).decode()

            def request(path, *, auth=None, method='GET', payload=None, headers=None):
                fields = dict(headers or {})
                if auth:
                    fields['Authorization'] = auth
                body = None
                if payload is not None:
                    body = json.dumps(payload).encode()
                    fields['Content-Type'] = 'application/json'
                try:
                    with opener.open(Request(origin + path, data=body, headers=fields, method=method), timeout=10) as response:
                        return response.status, response.headers, response.read()
                except HTTPError as error:
                    return error.code, error.headers, error.read()

            for path in ('/', '/static/library.js', '/api/v1/session', '/api/v1/backups', '/health/ready',
                         '/games/example/stream', '/games/example/feed.xml', '/games/example/shots/1.png',
                         '/games/example/%2e/internal/health'):
                for auth in (None, 'Basic ' + base64.b64encode(b'wrong:wrong').decode()):
                    status, _, _ = request(path, auth=auth)
                    assert status == 401, (path, status)
            assert request('/api/v1/settings', method='PATCH', payload={'max_running': 3})[0] == 401
            status, headers, _ = request('/', auth=authorization)
            assert status == 200
            assert "script-src 'self'" in headers['Content-Security-Policy']
            token = json.loads(request('/api/v1/session', auth=authorization)[2])['csrf_token']
            assert request('/api/v1/settings', auth=authorization, method='PATCH', payload={'max_running': 3})[0] == 403
            assert request('/api/v1/settings', auth=authorization, method='PATCH', payload={'max_running': 3},
                           headers={'X-PokeSim-CSRF': token, 'Origin': origin})[0] == 200
            assert request('/api/v1/settings', auth=authorization, method='PATCH', payload={'max_running': 2},
                           headers={'X-PokeSim-CSRF': token, 'Origin': 'https://evil.example'})[0] == 403
            assert request('/api/v1/session', auth=authorization, headers={'Sec-Fetch-Site': 'cross-site'})[0] == 403
            assert request('/games/example/%2e/internal/health', auth=authorization)[0] == 404
            application = compose('ps', '-q', 'pokesim')
            inspection = json.loads(subprocess.check_output(['docker', 'inspect', application], text=True))[0]
            assert not inspection['HostConfig']['PortBindings']
            assert inspection['Config']['User'] == '10001:10001'
            assert inspection['HostConfig']['ReadonlyRootfs']
            assert 'ALL' in inspection['HostConfig']['CapDrop']
            assert 'no-new-privileges:true' in inspection['HostConfig']['SecurityOpt']
            print('Proxy passed: verified TLS, authentication on all routes, CSRF, origins, private routes, and isolated backend')
        except BaseException:
            print(compose('logs', '--no-color', '--tail', '30'))
            raise
        finally:
            compose('down', '-v', '--remove-orphans')


if __name__ == '__main__':
    main()
