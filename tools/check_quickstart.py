"""Verify the documented Docker quick start with a fresh, disposable named volume."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from urllib.request import ProxyHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[1]


def compose_environment(image, port):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('COMPOSE_')
           and key not in {'DATA_PATH', 'PUBLIC_URL', 'NTFY_URL', 'NTFY_TOKEN', 'NTFY_MUTE'}}
    env.update(POKESIM_IMAGE=image, HTTP_PORT=str(port), BIND_ADDRESS='127.0.0.1')
    return env


def compose_command(root, project):
    return ['docker', 'compose', '--project-name', project, '--env-file', str(root / '.env'),
            '-f', str(root / 'compose.yaml')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    args = parser.parse_args()
    project = 'pokesim-quickstart-' + uuid.uuid4().hex[:12]
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        root = Path(temporary)
        shutil.copyfile(ROOT / 'compose.quickstart.yaml', root / 'compose.yaml')
        (root / '.env').write_text('')
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
                    probe = (ROOT / 'tools/check_first_run.py').read_text()
                    compose('exec', '-T', 'pokesim', 'python', '-c', probe, '--data-dir', '/data')
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


if __name__ == '__main__':
    main()
