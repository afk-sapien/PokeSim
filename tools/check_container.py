"""Exercise the Compose lifecycle with disposable data and PyBoy's demo ROM."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    args = parser.parse_args()
    project = 'pokesim-smoke-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        root = Path(temporary)
        rom = root / 'demo.gb'
        rom.write_bytes(subprocess.check_output([
            'docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', args.image,
            '-c', 'from pathlib import Path\nimport pyboy\nimport sys\n'
            'sys.stdout.buffer.write(Path(pyboy.__file__).with_name("default_rom.gb").read_bytes())',
        ], timeout=30))
        rom.chmod(0o644)
        override = root / 'compose.json'
        override.write_text(json.dumps({
            'services': {
                'pokesim': {'volumes': ['audit-data:/data'], 'healthcheck': {'interval': '2s'}},
                'prepare-data': {'volumes': ['audit-data:/data']},
            },
            'volumes': {'audit-data': {}},
        }))
        settings = root / 'empty.env'
        settings.write_text('')
        env = {**os.environ, 'POKESIM_IMAGE': args.image, 'ROM_FILE': str(rom),
               'DATA_PATH': str(root / 'unused'), 'BIND_ADDRESS': '127.0.0.1',
               'HTTP_PORT': '0', 'POLICY': 'guided_random', 'SPEED': '1',
               'NTFY_URL': '', 'NTFY_TOKEN': '', 'TRADING_URL': '', 'TRADING_INSTANCE': '',
               'VIEWER_ONLY': '1', 'AUTOSAVE_SECONDS': '2', 'KEEP_AUTOSAVES': '3'}
        command = ['docker', 'compose', '--project-name', project, '--env-file', str(settings),
                   '-f', str(ROOT / 'compose.yaml'), '-f', str(override)]

        def compose(*arguments, capture=False, timeout=120):
            return subprocess.run([*command, *arguments], env=env, check=True, timeout=timeout,
                                  text=True, stdout=subprocess.PIPE if capture else None).stdout

        def ready():
            compose('up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '60', 'pokesim')
            address = compose('port', 'pokesim', '8000', capture=True).strip()
            with urlopen(f'http://{address}/healthz', timeout=5) as response:
                assert response.status == 200
            with urlopen(f'http://{address}/', timeout=5) as response:
                assert b'<html' in response.read().lower()

        try:
            compose('--profile', 'setup', 'run', '--rm', '--pull', 'never', 'prepare-data')
            offline = root / 'offline.json'
            offline.write_text(json.dumps({'services': {'prepare-data': {'network_mode': 'none'}}}))
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
            print('Compose passed: verified setup, offline retry, HTTP health, clean save, and resume')
        except BaseException:
            subprocess.run([*command, 'logs', '--no-color', '--tail', '100'], env=env, timeout=30)
            raise
        finally:
            # Remove only this uniquely named test project's disposable resources.
            subprocess.run([*command, 'down', '--volumes', '--remove-orphans'],
                           env=env, check=True, timeout=60)


if __name__ == '__main__':
    main()
