"""Container health probe using the Python standard library."""
import os
import sys
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def main():
    port = int(os.environ.get('PORT', '8000'))
    managed = '--manager' in sys.argv[1:]
    path = '/health/ready' if managed else '/healthz'
    default_host = '127.0.0.1' if managed else 'localhost'
    public = os.environ.get('PUBLIC_URL', f'http://{default_host}:{port}')
    headers = {'Host': urlsplit(public).netloc}
    request = Request(f'http://127.0.0.1:{port}{path}', headers=headers)
    with build_opener(ProxyHandler({})).open(request, timeout=4) as response:
        if response.status != 200:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
