"""Regression coverage for browser, worker proxy, and archive trust boundaries."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
import httpx
import pytest

from pokesim.app.backup import extract_archive, file_checksum
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from pokesim.web.app import create_app as game_app
from pokesim.web.security import public_origin


@pytest.fixture
def managed(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('fixture', 'sha1', 'red')
    adventure = manager.registry.create('Security test', 'fixture', {}, identifier())
    manager.registry.update(adventure['id'], state='running')
    forwarded = []

    async def worker(request):
        forwarded.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b'public response'))

    original_client = httpx.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(worker), **kwargs))
    monkeypatch.setattr(manager.supervisor, 'child',
                        lambda aid: SimpleNamespace(url='http://127.0.0.1:12345', token='private-worker-token'))
    with TestClient(create_app(manager)) as client:
        token = client.get('/api/v1/session').json()['csrf_token']
        client.headers['X-PokeSim-CSRF'] = token
        yield client, '/games/' + adventure['id'] + '/', forwarded


@pytest.mark.parametrize('method', ['GET', 'POST', 'HEAD'])
@pytest.mark.parametrize('path', [
    'internal/health', '%2e/internal/health', '%2e/api/trade', '%2e/internal/shutdown',
    '%2e%2e/internal/health', '%252e/internal/health', '%2finternal/health',
    '%5cinternal/health', 'api/state%3f/../internal/health', 'api/state%23/../internal/health',
    'static/%2e%2e/internal/health', 'api/trade', 'docs', 'openapi.json',
])
def test_private_worker_routes_never_receive_browser_requests(managed, method, path):
    client, base, forwarded = managed
    assert client.request(method, base + path).status_code == 404
    assert forwarded == []


@pytest.mark.parametrize('method,path', [
    ('GET', ''), ('GET', 'api/state'), ('GET', 'api/events/42'), ('GET', 'events/42'),
    ('GET', 'static/screen.js'), ('GET', 'shots/42.png'), ('GET', 'stream'),
    ('GET', 'feed.xml'), ('HEAD', 'frame.jpg'), ('POST', 'api/control'),
    ('POST', 'api/trading/preferences'),
])
def test_public_worker_routes_preserve_query_and_private_credentials(managed, method, path):
    client, base, forwarded = managed
    response = client.request(method, base + path + '?value=%2F%23%3F&second=a+b',
                              headers={'Authorization': 'Bearer browser-value'})
    assert response.status_code == 200
    assert len(forwarded) == 1
    request = forwarded[0]
    assert request.url.path == '/' + path
    assert request.url.query == b'value=%2F%23%3F&second=a+b'
    assert request.headers['authorization'] == 'Bearer private-worker-token'
    assert 'private-worker-token' not in response.text


def test_manager_sends_browser_protections(managed):
    client, base, forwarded = managed
    response = client.get('/')
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert response.headers['cross-origin-resource-policy'] == 'same-origin'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('url', [
    'file:///tmp/data', 'http://user:password@localhost', 'http://localhost/path',
    'http://localhost?next=elsewhere', 'http://localhost#fragment', 'http://localhost:0',
    'http://localhost:99999', 'http://localhost:bad', ' http://localhost',
    'http://localhost\n', 'http://localhost\\elsewhere',
])
def test_invalid_public_origin_does_not_open_data(tmp_path, url):
    root = tmp_path / 'new-library'
    with pytest.raises(ValueError, match='PUBLIC_URL'):
        Manager(root, url)
    assert not root.exists()


@pytest.mark.parametrize('url', ['http://127.0.0.1:8000', 'https://pokesim.example/', 'http://[::1]:8000'])
def test_public_origin_accepts_local_and_proxy_addresses(url):
    assert public_origin(url) == url.rstrip('/')


@pytest.mark.parametrize('headers', [
    {'Host': 'evil.example'}, {'Origin': 'https://evil.example'}, {'Origin': 'null'},
    {'Sec-Fetch-Site': 'cross-site'},
])
def test_legacy_browser_boundary_rejects_rebinding_and_cross_site_writes(tmp_path, headers):
    changes = []
    emu = SimpleNamespace(status=lambda: {}, control=lambda *args: changes.append(args))
    client = TestClient(game_app(emu, SimpleNamespace(shots=tmp_path), browser_origin='http://testserver'))
    response = client.post('/api/control', json={'action': 'pause'}, headers=headers)
    assert response.status_code == 403
    assert changes == []
    assert client.get('/', headers=headers).status_code == 403
    assert client.get('/').status_code == 200
    assert client.get('/docs').status_code == 404


@pytest.mark.parametrize('name', ['NUL', 'folder/CON.txt', 'LPT1.png', 'COM¹.txt', 'a./b',
                                 'a /b', './file', 'a//b', 'a\x01b', 'bad?.txt', 'bad*.txt'])
def test_archive_rejects_device_names_and_ambiguous_components(tmp_path, name):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr(name, b'private data')
    with pytest.raises(ValueError, match='unsafe'):
        extract_archive(archive, tmp_path / 'output')


def test_archive_cannot_write_through_an_existing_symlink(tmp_path):
    output = tmp_path / 'output'
    outside = tmp_path / 'outside'
    output.mkdir()
    outside.mkdir()
    try:
        (output / 'redirect').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Creating symbolic links is not permitted on this platform')
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('redirect/private.txt', b'outside data')
    with pytest.raises(ValueError, match='unsafe'):
        extract_archive(archive, output)
    assert not list(outside.iterdir())


def test_backup_checksum_streams_large_members(tmp_path, monkeypatch):
    path = tmp_path / 'large.state'
    payload = b'state data' * 100000
    path.write_bytes(payload)
    monkeypatch.setattr(Path, 'read_bytes', lambda self: pytest.fail('Must not load a full backup member into memory'))
    assert file_checksum(path) == hashlib.sha256(payload).hexdigest()
