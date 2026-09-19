"""Exercise the installed library launcher without a Pokémon ROM."""
import argparse
import json
from http.cookiejar import CookieJar
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error('Supply pokesim-desktop or python -m pokesim.desktop')
    cookies = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
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
                        identity = json.loads((root / 'manager.json').read_text())
                        url = identity['url']
                        with opener.open(url + '/health/ready', timeout=1) as response:
                            assert json.load(response)['ok']
                        break
                    except (OSError, ValueError, URLError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Library did not become ready')
                        time.sleep(0.1)
                with opener.open(url) as response:
                    assert b'Your adventure library' in response.read()
                for path in ('/static/library.js', '/static/library.css'):
                    with opener.open(url + path) as response:
                        assert response.status == 200
                with opener.open(url + '/api/v1/session') as response:
                    session = json.load(response)
                assert session['csrf_token']
                assert list(cookies), 'Session endpoint did not set a cookie'
                assert not (root / 'owner.token').exists()
                try:
                    opener.open(Request(url + '/api/v1/shutdown', data=b'{}', method='POST'))
                    raise AssertionError('Shutdown without CSRF protection was allowed')
                except HTTPError as error:
                    assert error.code in (401, 403)
                second = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                assert second.returncode == 0, second.stderr
                with opener.open(Request(url + '/api/v1/shutdown', data=b'{}', method='POST',
                                 headers={'X-PokeSim-CSRF': session['csrf_token'],
                                          'Origin': url, 'Content-Type': 'application/json'})) as response:
                    assert json.load(response)['ok']
                assert process.wait(timeout=30) == 0
                print('Python launcher smoke passed: keyless library, assets, duplicate launch, CSRF-protected shutdown, clean exit')
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
