"""Exercise an installed or bundled launcher without supplying a Pokémon ROM."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error('Supply an executable or python -m pokesim.desktop')
    with tempfile.TemporaryDirectory(prefix='pokesim-smoke-') as temporary:
        root = Path(temporary)
        command = [*args.command, '--no-browser', '--data-dir', str(root)]
        with (root / 'process.log').open('w') as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 60
                while True:
                    if process.poll() is not None:
                        raise RuntimeError((root / 'process.log').read_text())
                    try:
                        instance = json.loads((root / 'instance.json').read_text())
                        url = f'http://127.0.0.1:{instance["port"]}'
                        with urlopen(url + '/desktop/status', timeout=1) as response:
                            assert json.load(response)['state'] == 'setup'
                        break
                    except (OSError, ValueError, URLError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Launcher did not become ready')
                        time.sleep(0.1)
                for path, expected in [('/desktop', b'Your desktop adventure'),
                                       ('/desktop/assets/desktop.js', b'poll()'),
                                       ('/desktop/assets/desktop.css', b'color-scheme')]:
                    with urlopen(url + path) as response:
                        assert expected in response.read()
                try:
                    urlopen(Request(url + '/desktop/quit', data=b'', method='POST'))
                    raise AssertionError('Unauthenticated shutdown was allowed')
                except HTTPError as error:
                    assert error.code == 403
                second = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                assert second.returncode == 0, second.stderr
                with urlopen(url + '/desktop/status') as response:
                    assert json.load(response)['state'] == 'setup'
                with urlopen(Request(url + '/desktop/quit', data=b'', method='POST',
                                     headers={'X-PokeSim-Token': instance['token']})) as response:
                    assert json.load(response)['ok']
                assert process.wait(timeout=30) == 0
                assert not (root / 'instance.json').exists()
                print('Desktop smoke passed: setup, assets, duplicate launch, protected shutdown, clean exit')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == '__main__':
    main()
