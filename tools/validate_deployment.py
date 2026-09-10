"""Exercise an isolated HTTPS deployment and a backup-based version rollback."""
import argparse
import base64
import json
import os
import secrets
import shutil
import ssl
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--old-image', default='pokesim:0.1.0')
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stream-seconds', type=int, default=600)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    data = root / 'data'
    data.mkdir()
    password = secrets.token_urlsafe(24)
    hashed = run('docker', 'run', '--rm', 'caddy:2.11.4-alpine', 'caddy', 'hash-password', '--plaintext', password)
    environment = root / 'proxy.env'
    environment.write_text('\n'.join([
        f'POKESIM_IMAGE={args.image}', f'ROM_FILE={args.rom.resolve()}', f'DATA_PATH={data}',
        'PROXY_HTTPS_PORT=19443', 'PROXY_HTTP_PORT=19080', 'SITE_ADDRESS=localhost',
        'PUBLIC_URL=https://localhost:19443', 'AUTH_USER=release-test',
        f"AUTH_HASH='{hashed}'", 'SPEED=1', 'AUTOSAVE_SECONDS=10',
    ]) + '\n')
    environment.chmod(0o600)
    project = 'pokesim-release-validation'
    compose = ['docker', 'compose', '-p', project, '--env-file', str(environment), '-f', 'compose.proxy.yaml']
    report = {'image': args.image, 'old_image': args.old_image, 'checks': {}}
    headers = {'Authorization': 'Basic ' + base64.b64encode(f'release-test:{password}'.encode()).decode()}
    context = None
    container = 'pokesim-upgrade-validation'

    def request(path, credentials=headers, payload=None, port=19443):
        url = f'https://localhost:{port}{path}'
        return urlopen(Request(url, headers=dict(credentials, **({'Content-Type': 'application/json'} if payload else {})),
                               data=json.dumps(payload).encode() if payload else None), context=context, timeout=15)

    def healthy(fetch):
        for attempt in range(60):
            try:
                result = fetch()
                if result['health']['ok']:
                    return result
            except Exception:
                pass
            time.sleep(1)
        raise AssertionError('Service did not become healthy')

    def direct_state():
        with urlopen('http://127.0.0.1:18942/api/state', timeout=5) as response:
            return json.load(response)

    def ownership(path):
        run('docker', 'run', '--rm', '--user', '0', '-v', f'{path}:/target', '--entrypoint', 'chown', args.image, '-R', '10001:10001', '/target')

    def copy_backup(source, target):
        target.mkdir()
        script = (
            "import os, shutil\n"
            "from pathlib import Path\n"
            "shutil.copytree('/source', '/target', dirs_exist_ok=True)\n"
            "for path in [Path('/target'), *Path('/target').rglob('*')]:\n"
            f"    os.chown(path, {os.getuid()}, {os.getgid()})\n"
        )
        run('docker', 'run', '--rm', '--user', '0', '-v', f'{source}:/source:ro',
            '-v', f'{target}:/target', args.image, 'python', '-c', script)

    def start_direct(image, path):
        run('docker', 'run', '-d', '--name', container, '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:size=64m,mode=1777',
            '-p', '127.0.0.1:18942:8000', '-v', f'{path}:/data', '-v', f'{args.rom.resolve()}:/roms/pokered.gb:ro',
            '-e', 'SPEED=1', '-e', 'AUTOSAVE_SECONDS=10', image)
        return healthy(direct_state)

    try:
        ownership(data)
        run('docker', 'run', '--rm', '--network', 'none', '--read-only', '-v', f'{data}:/data',
            '-v', f'{args.source.resolve()}:/source:ro', args.image, 'python', '-m', 'pokesim.prepare_data', '/source')
        run(*compose, 'config', '--quiet')
        run(*compose, 'up', '-d')
        proxy = run(*compose, 'ps', '-q', 'proxy')
        for attempt in range(30):
            try:
                run('docker', 'cp', f'{proxy}:/data/caddy/pki/authorities/local/root.crt', str(root / 'root.crt'))
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        context = ssl.create_default_context(cafile=str(root / 'root.crt'))
        def proxy_state():
            with request('/api/state') as response:
                return json.load(response)
        state = healthy(proxy_state)
        report['checks']['tls_verified'] = True
        protected = ['/', '/api/state', '/api/control', '/stream', '/frame.jpg', '/feed.xml', '/shots/1.png', '/healthz']
        for path in protected:
            for credentials in ({}, {'Authorization': 'Basic ' + base64.b64encode(b'wrong:wrong').decode()}):
                try:
                    request(path, credentials).close()
                    raise AssertionError(f'Unprotected route: {path}')
                except HTTPError as error:
                    assert error.code == 401, (path, error.code)
        report['checks']['authentication'] = protected
        with request('/api/control', payload={'action': 'pause'}) as response:
            assert json.load(response)['ok']
        time.sleep(1)
        assert proxy_state()['paused']
        request('/api/control', payload={'action': 'resume'}).close()
        with request('/feed.xml') as response:
            assert b'https://localhost:19443' in response.read()
        app = run(*compose, 'ps', '-q', 'pokesim')
        ports = json.loads(run('docker', 'inspect', '--format', '{{json .HostConfig.PortBindings}}', app))
        assert not ports
        report['checks']['backend_has_no_host_port'] = True
        streamed = [0]
        def consume():
            try:
                with request('/stream') as response:
                    while chunk := response.read(8192):
                        streamed[0] += len(chunk)
            except Exception:
                pass
        thread = threading.Thread(target=consume, daemon=True)
        thread.start()
        start = time.monotonic()
        time.sleep(args.stream_seconds)
        assert streamed[0] > 100000, streamed
        report['checks']['stream'] = {'duration_seconds': round(time.monotonic() - start, 1), 'bytes': streamed[0]}
        previous = proxy_state()['frame']
        start = time.monotonic()
        run(*compose, 'stop', 'pokesim')
        elapsed = time.monotonic() - start
        assert elapsed < 15, elapsed
        exit_code = int(run('docker', 'inspect', '--format', '{{.State.ExitCode}}', app))
        assert exit_code in (0, 143), exit_code
        assert list((data / 'states').glob('auto-v1-*.json'))
        report['checks']['shutdown_with_active_stream_seconds'] = round(elapsed, 2)
        thread.join(timeout=20)
        assert not thread.is_alive()
        run(*compose, 'start', 'pokesim')
        restored = healthy(proxy_state)
        assert restored['frame'] >= previous
        with request('/stream') as response:
            assert b'Content-Type: image/jpeg' in response.read(4096)
        report['checks']['restart_and_stream_reconnect'] = True
        run(*compose, 'down', '-v')

        upgrade = root / 'upgrade'
        upgrade.mkdir()
        ownership(upgrade)
        first = start_direct(args.old_image, upgrade)
        assert first['version'] == '0.1.0'
        time.sleep(20)
        prior = direct_state()['frame']
        run('docker', 'stop', '--time', '15', container)
        run('docker', 'rm', container)
        saved = max((upgrade / 'states').glob('auto-v1-*.json'), key=lambda p: p.stat().st_mtime)
        backup = root / 'pre-upgrade-backup'
        copy_backup(upgrade, backup)
        original_checkpoint = json.loads((backup / 'states' / saved.name).read_text())
        run('docker', 'run', '--rm', '--network', 'none', '--read-only', '-v', f'{upgrade}:/data',
            '-v', f'{args.source.resolve()}:/source:ro', args.image, 'python', '-m', 'pokesim.prepare_data', '/source')
        upgraded = start_direct(args.image, upgrade)
        assert upgraded['version'] != first['version']
        assert upgraded['frame'] >= prior
        time.sleep(15)
        assert direct_state()['frame'] > upgraded['frame']
        run('docker', 'stop', '--time', '15', container)
        run('docker', 'rm', container)
        rollback = root / 'rollback'
        shutil.copytree(backup, rollback)
        ownership(rollback)
        rolled_back = start_direct(args.old_image, rollback)
        assert rolled_back['version'] == '0.1.0'
        assert rolled_back['frame'] >= prior
        report['checks']['upgrade_and_backup_rollback'] = {
            'from': first['version'], 'to': upgraded['version'], 'restored': rolled_back['version'],
            'before_frame': prior, 'upgraded_frame': upgraded['frame'], 'rollback_frame': rolled_back['frame'],
            'checkpoint_sha256': original_checkpoint['sha256'],
        }
        report['passed'] = True
    finally:
        for command in ([*compose, 'down', '-v'], ['docker', 'stop', '--time', '15', container], ['docker', 'rm', container]):
            try:
                run(*command)
            except subprocess.CalledProcessError:
                pass
        environment.unlink(missing_ok=True)
        (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
