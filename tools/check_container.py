"""Check the container image, the Docker quick start and a first run in an empty library.

Only the standard library loads at import. The quick start check runs this file inside its container
with python -c to make the first run check there, and python -c has no __file__.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from urllib.request import ProxyHandler, Request, build_opener, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1] if '__file__' in globals() else None


def compose_check(args):
    """Exercise the Compose lifecycle with disposable data and PyBoy's demo ROM."""
    project = 'pokesim-smoke-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        root = Path(temporary)
        rom = root / 'demo.gb'
        rom.write_bytes(subprocess.check_output([
            'docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', args.image,
            '-c', 'from pokecore.emulator import demo_rom\nimport sys\n'
            'sys.stdout.buffer.write(demo_rom().read_bytes())',
        ], timeout=30))
        rom.chmod(0o644)
        override = root / 'compose.json'
        override.write_text(json.dumps({
            'services': {
                'pokesim': {'volumes': ['audit-data:/data'], 'healthcheck': {'interval': '2s'}},
                'prepare-data': {'volumes': ['audit-data:/data'], 'network_mode': 'bridge',
                                 'command': ['python', '-m', 'pokesim.prepare_data', '--download']},
            },
            'volumes': {'audit-data': {}},
        }), encoding='utf-8')
        settings = root / 'empty.env'
        settings.write_text('', encoding='utf-8')
        env = {**os.environ, 'POKESIM_IMAGE': args.image, 'ROM_FILE': str(rom),
               'DATA_PATH': str(root / 'unused'), 'BIND_ADDRESS': '127.0.0.1',
               'HTTP_PORT': '0', 'POLICY': 'guided_random', 'SPEED': '1',
               'PUBLIC_URL': 'http://localhost:8930', 'NTFY_URL': '', 'NTFY_TOKEN': '', 'TRADING_URL': '', 'TRADING_INSTANCE': '',
               'VIEWER_ONLY': '1', 'AUTOSAVE_SECONDS': '2', 'KEEP_AUTOSAVES': '3'}
        command = ['docker', 'compose', '--project-name', project, '--env-file', str(settings),
                   '-f', str(ROOT / 'compose.legacy.yaml'), '-f', str(override)]

        def compose(*arguments, capture=False, timeout=120):
            return subprocess.run([*command, *arguments], env=env, check=True, timeout=timeout,
                                  text=True, stdout=subprocess.PIPE if capture else None).stdout

        def ready():
            compose('up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '60', 'pokesim')
            address = compose('port', 'pokesim', '8000', capture=True).strip()
            with urlopen(Request(f'http://{address}/healthz', headers={'Host': 'localhost:8930'}), timeout=5) as response:
                assert response.status == 200
            with urlopen(Request(f'http://{address}/', headers={'Host': 'localhost:8930'}), timeout=5) as response:
                assert b'<html' in response.read().lower()

        try:
            compose('--profile', 'setup', 'run', '--rm', '--pull', 'never', 'prepare-data')
            offline = root / 'offline.json'
            offline.write_text(json.dumps({'services': {'prepare-data': {'network_mode': 'none'}}}), encoding='utf-8')
            subprocess.run([*command, '-f', str(offline), '--profile', 'setup',
                            'run', '--rm', '--pull', 'never', 'prepare-data'],
                           env=env, check=True, timeout=30)
            ready()
            compose('stop', 'pokesim')
            container = compose('ps', '-a', '-q', 'pokesim', capture=True).strip()
            code = subprocess.check_output(['docker', 'inspect', '--format', '{{.State.ExitCode}}',
                                            container], text=True).strip()
            assert code == '0', f'Container shutdown failed with exit code {code}'
            probe = ('from pathlib import Path\nimport hashlib\nimport json\n'
                     'saves = list(Path("/data/states").glob("auto-*.state"))\n'
                     'assert saves, "Shutdown did not save the adventure"\n'
                     'for save in saves:\n'
                     '    metadata = json.loads(save.with_suffix(".json").read_text())\n'
                     '    assert metadata["sha256"] == hashlib.sha256(save.read_bytes()).hexdigest()\n')
            compose('run', '--rm', '--no-deps', '--entrypoint', 'python', 'pokesim', '-c', probe)
            ready()
            logs = compose('logs', '--no-color', 'pokesim', capture=True)
            assert 'resumed from auto-' in logs, 'Restart did not restore the saved adventure'
            print('Legacy Compose passed: setup, offline retry, health, clean save, and resume')
            subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                            '--cap-drop', 'ALL', '--tmpfs', '/tmp:size=256m,mode=1777',
                            '-v', project + '_audit-data:/data',
                            '-v', str(ROOT / 'tools/check_install.py') + ':/check_install.py:ro',
                            '--entrypoint', 'python', args.image, '/check_install.py', 'runtime'],
                           check=True, timeout=180)
            compose('down', '--remove-orphans')
            override.write_text(json.dumps({
                'services': {'pokesim': {'volumes': ['audit-data:/data'],
                    'command': ['python', '-m', 'pokesim', 'serve', '--data-dir', '/data/library', '--host', '0.0.0.0'],
                    'healthcheck': {'interval': '2s'}}},
                'volumes': {'audit-data': {}},
            }), encoding='utf-8')
            command[command.index(str(ROOT / 'compose.legacy.yaml'))] = str(ROOT / 'compose.yaml')
            for attempt in range(2):
                compose('up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '60', 'pokesim')
                address = compose('port', 'pokesim', '8000', capture=True).strip()
                for path in ('/', '/health/ready', '/static/library.js', '/api/v1/session'):
                    request = Request(f'http://{address}{path}', headers={'Host': 'localhost:8930'})
                    with urlopen(request, timeout=5) as response:
                        assert response.status == 200
                        if path == '/':
                            assert b'Your adventure library' in response.read()
                compose('stop', 'pokesim')
                container = compose('ps', '-a', '-q', 'pokesim', capture=True).strip()
                exit_code = subprocess.check_output(['docker', 'inspect', '--format',
                    '{{.State.ExitCode}}', container], text=True).strip()
                # Uvicorn re-raises SIGTERM after graceful shutdown when running under init.
                assert exit_code in {'0', '143'}, f'Library shutdown failed: {exit_code}'
            print('Library Compose passed: first launch, assets, session, graceful shutdown, and restart')
        except BaseException:
            subprocess.run([*command, 'logs', '--no-color', '--tail', '100'], env=env, timeout=30)
            raise
        finally:
            # Remove only this uniquely named test project's disposable resources.
            subprocess.run([*command, 'down', '--volumes', '--remove-orphans'],
                           env=env, check=True, timeout=60)


def compose_environment(image, port):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('COMPOSE_')
           and key not in {'DATA_PATH', 'PUBLIC_URL', 'NTFY_URL', 'NTFY_TOKEN', 'NTFY_MUTE'}}
    env.update(POKESIM_IMAGE=image, HTTP_PORT=str(port), BIND_ADDRESS='127.0.0.1')
    return env


def compose_command(root, project):
    return ['docker', 'compose', '--project-name', project, '--env-file', str(root / '.env'),
            '-f', str(root / 'compose.yaml')]


def quickstart(args):
    """Verify the documented Docker quick start with a fresh, disposable named volume."""
    project = 'pokesim-quickstart-' + uuid.uuid4().hex[:12]
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        root = Path(temporary)
        shutil.copyfile(ROOT / 'compose.quickstart.yaml', root / 'compose.yaml')
        (root / '.env').write_text('', encoding='utf-8')
        env = compose_environment(args.image, port)
        command = compose_command(root, project)

        def compose(*arguments, capture=False):
            return subprocess.run([*command, *arguments], cwd=root, env=env, check=True,
                                  text=True, capture_output=capture, timeout=150)

        opener = build_opener(ProxyHandler({}))
        try:
            for attempt in range(2):
                compose('up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '90')
                for path in ('/', '/health/ready', '/static/library.js', '/api/v1/session'):
                    with opener.open(f'http://localhost:{port}{path}', timeout=10) as response:
                        assert response.status == 200
                        if path == '/':
                            assert b'Your adventure library' in response.read()
                request = Request(f'http://127.0.0.1:{port}/', headers={'Host': f'localhost:{port}'})
                with opener.open(request, timeout=10) as response:
                    assert response.status == 200
                code = ('import os\nfrom pathlib import Path\n'
                        'assert os.getuid() == 10001\n'
                        'p = Path("/data/quickstart-test.txt")\n')
                if attempt == 0:
                    code += 'p.write_text("retained library")\n'
                else:
                    code += 'assert p.read_text() == "retained library"\n'
                compose('exec', '-T', 'pokesim', 'python', '-c', code)
                if attempt == 0:
                    probe = (ROOT / 'tools/check_container.py').read_text(encoding='utf-8')
                    compose('exec', '-T', 'pokesim', 'python', '-c', probe, 'first-run', '--data-dir', '/data')
                container = compose('ps', '-q', 'pokesim', capture=True).stdout.strip()
                compose('stop')
                inspected = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
                assert inspected['State']['ExitCode'] in (0, 143)
                compose('down')
            print('Docker quick start passed: first ROM setup, fresh volume, non-root writes, custom port, health, shutdown, and persistence')
        except BaseException:
            compose('logs', '--no-color', '--tail=100')
            raise
        finally:
            # Only this randomly named test project's disposable volume is removed.
            compose('down', '--volumes', '--remove-orphans')


def first_run(args):
    """Check first ROM upload and automatic setup in an empty application directory."""
    from fastapi.testclient import TestClient
    from pokecore import emulator as pyboy
    from pokesim import desktop_setup, sprites
    from pokesim.app.manager import Manager, create_app
    from pokesim.app.registry import identifier

    raw = (args.rom or pyboy.demo_rom()).read_bytes()
    if not args.rom:
        # Only this isolated probe accepts the redistributable demo cartridge.
        desktop_setup.ROM_NAMES[hashlib.sha1(raw).hexdigest()] = 'Pokémon Red'

        def demo_portraits(rom, species):
            assert rom == raw
            assert all(isinstance(key, int) for key in species)
            assert {entry['dex'] for entry in species.values()} >= set(range(1, 152))
            return {dex: sprites.png([[0]]) for dex in range(1, 152)}

        sprites.extract = demo_portraits

    with tempfile.TemporaryDirectory(prefix='pokesim-first-run-', dir=args.data_dir) as temporary:
        root = Path(temporary)
        os.environ['DATA_DIR'] = str(root / 'legacy')
        os.environ['GAME_DATA_DIR'] = str(root / 'missing-reference')
        manager = Manager(root / 'library', 'http://testserver', game_data_dir=args.game_data)
        with TestClient(create_app(manager)) as client:
            csrf = client.get('/api/v1/session').json()['csrf_token']
            response = client.post('/api/v1/assets/rom', content=raw,
                                   headers={'X-PokeSim-CSRF': csrf})
            assert response.status_code == 200, response.text
            assert not manager.assets.game_data_dir.exists(), 'Upload must not require reference setup'
            assert 'pokesim.strategy_data' not in sys.modules
            rom = response.json()
            adventure = manager.registry.create('First adventure', rom['id'], {}, identifier())
            aid = adventure['id']
            manager.registry.request_lifecycle(aid, 'start', identifier())
            assert manager.start_adventure(aid)['state'] == 'running'
            assert (manager.assets.game_data_dir / 'current.json').is_file()
            portraits = list((manager.assets.root / 'sprites').glob('*.png'))
            assert len(portraits) == 151, len(portraits)
            assert 'pokesim.strategy_data' not in sys.modules
            assert not (root / 'missing-reference').exists()
            assert not (root / 'legacy').exists()
            manager.supervisor.stop(aid)
            assert list((manager.root / 'adventures' / aid / 'states').glob('*.state'))
            custom = manager.assets.root / 'sprites' / '1.png'
            custom_art = sprites.png([[1]])
            custom.write_bytes(custom_art)

            def unexpected_download(*args, **kwargs):
                raise AssertionError('A prepared library must restart without downloading reference data')

            desktop_setup.urlopen = unexpected_download
            manager.registry.request_lifecycle(aid, 'start', identifier())
            assert manager.start_adventure(aid)['state'] == 'running'
            assert custom.read_bytes() == custom_art
            manager.supervisor.stop(aid)
    print('First run passed: upload without legacy data, automatic setup, portraits, worker start, save, and offline restart')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, run in (('compose', compose_check), ('quickstart', quickstart)):
        check = commands.add_parser(name, help=run.__doc__, description=run.__doc__)
        check.add_argument('image')
        check.set_defaults(run=run)
    check = commands.add_parser('first-run', help=first_run.__doc__, description=first_run.__doc__)
    check.add_argument('--data-dir', type=Path)
    check.add_argument('--game-data', type=Path)
    check.add_argument('--rom', type=Path)
    check.set_defaults(run=first_run)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()
