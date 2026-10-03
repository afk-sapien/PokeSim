"""Community artwork is explicit, bounded and activated only after a complete install."""
import io
import threading

import httpx
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from pokesim.app import portrait_packs
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier


HTTP_CLIENT = httpx.Client


def png(size=(96, 96)):
    result = io.BytesIO()
    Image.new('RGBA', size, (80, 140, 60, 255)).save(result, 'PNG')
    return result.getvalue()


def upstream(monkeypatch, fail=None):
    requests = []
    def respond(request):
        requests.append(str(request.url))
        if request.url.path.endswith('/LICENCE.txt'):
            return httpx.Response(200, content=b'Synthetic source notice')
        if fail and request.url.path.endswith('/51.png'):
            return fail
        return httpx.Response(200, content=png())
    monkeypatch.setattr(portrait_packs.httpx, 'Client',
                        lambda **kw: HTTP_CLIENT(transport=httpx.MockTransport(respond), **kw))
    return requests


@pytest.fixture
def manager(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    try:
        yield manager
    finally:
        manager.close()


def test_install_switch_restart_and_restore_preserve_originals(manager, monkeypatch):
    requests = upstream(monkeypatch)
    assets = manager.assets
    packs = assets.portraits
    assets.registry.add_rom('rom', 'sha1', 'red')
    row = assets.registry.create('Red', 'rom', {}, identifier())
    defaults = manager.root / 'adventures' / row['id'] / 'sprites'
    defaults.mkdir()
    (defaults / '25.png').write_bytes(b'original local portrait')
    assert not requests
    assert packs.status()['active'] == 'default'
    assert packs.begin()
    assert packs.status()['busy']
    with pytest.raises(ValueError, match='already downloading'):
        packs.begin()
    with pytest.raises(ValueError, match='Wait'):
        packs.restore()
    assert assets.sprite_path(row['id'], 25).read_bytes() == b'original local portrait'
    packs.install()
    assert len(requests) == 152
    assert all(url.startswith(portrait_packs.RAW + '/') for url in requests)
    assert packs.status()['active'] == 'community'
    assert packs.status()['completed'] == 151
    assert assets.sprite_path(row['id'], 25).read_bytes() == png()
    assert (packs.directory / 'LICENCE.txt').read_bytes() == b'Synthetic source notice'
    assert portrait_packs.PortraitPacks(manager.registry, threading.Event()).status()['active'] == 'community'
    packs.restore()
    assert assets.sprite_path(row['id'], 25).read_bytes() == b'original local portrait'
    assert not packs.begin()
    assert len(requests) == 152
    assert packs.status()['active'] == 'community'


@pytest.mark.parametrize('failure', [
    httpx.Response(404), httpx.Response(302, headers={'Location': 'https://example.com/image'}),
    httpx.Response(200, content=b'not a PNG'),
    httpx.Response(200, content=b'x' * (portrait_packs.MAX_IMAGE_BYTES + 1)),
    httpx.Response(200, content=png((257, 256))),
])
def test_failed_download_never_activates_a_partial_pack(manager, monkeypatch, failure):
    upstream(monkeypatch, failure)
    packs = manager.assets.portraits
    assert packs.begin()
    packs.install()
    status = packs.status()
    assert status['error'] and not status['busy']
    assert status['active'] == 'default' and not status['installed']
    assert not list(packs.directory.parent.iterdir())
    assert packs.begin()
    upstream(monkeypatch)
    packs.install()
    assert not packs.status()['busy']
    assert packs.status()['active'] == 'community'


def test_routes_require_csrf_and_do_not_download_on_settings_reads(manager, monkeypatch):
    requests = upstream(monkeypatch)
    with TestClient(create_app(manager)) as client:
        assert client.get('/settings').status_code == 200
        assert client.get('/api/v1/portraits').json()['active'] == 'default'
        assert client.get('/api/v1/portraits/preview/25.png').status_code == 404
        assert not requests
        assert client.post('/api/v1/portraits/community').status_code == 403
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        assert client.post('/api/v1/portraits/default', headers=headers).status_code == 200
        held = []
        monkeypatch.setattr(manager, 'background', lambda function, *args: held.append(function))
        assert client.post('/api/v1/portraits/community', headers=headers).json()['busy']
        assert client.post('/api/v1/portraits/community', headers=headers).status_code == 409
        assert len(held) == 1 and not requests
        held[0]()
        image = client.get('/api/v1/portraits/preview/25.png')
        assert image.content == png() and image.headers['cache-control'] == 'no-store'
        assert client.get('/api/v1/portraits/preview/152.png').status_code == 404
        assert client.post('/api/v1/portraits/default', headers=headers).json()['active'] == 'default'
        assert len(requests) == 152


def test_switch_updates_managed_image_response_and_restores_fallback(manager, monkeypatch):
    upstream(monkeypatch)
    manager.registry.add_rom('rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'rom', {}, identifier())
    defaults = manager.root / 'assets' / 'sprites'
    defaults.mkdir(parents=True)
    (defaults / '25.png').write_bytes(b'cartridge portrait')
    packs = manager.assets.portraits
    with TestClient(create_app(manager)) as client:
        url = f'/games/{row["id"]}/sprites/25.png?v=rom-portraits-1'
        before = client.get(url)
        assert before.content == b'cartridge portrait'
        assert before.headers['cache-control'] == 'private, no-cache'
        packs.begin()
        packs.install()
        installed = client.get(url)
        assert installed.content == png()
        assert installed.headers['etag'] != before.headers['etag']
        assert installed.headers['cache-control'] == 'private, no-cache'
        packs.restore()
        assert client.get(url).content == before.content


def test_shutdown_cancellation_keeps_defaults_and_removes_staging(manager, monkeypatch):
    upstream(monkeypatch)
    packs = manager.assets.portraits
    packs.begin()
    packs.cancelled.set()
    packs.install()
    assert packs.status()['active'] == 'default'
    assert not packs.status()['busy']
    assert not list(packs.directory.parent.iterdir())


def test_backup_during_pack_activation_ignores_moving_download_files(manager, monkeypatch):
    import os
    import shutil
    import zipfile
    from pokesim.app.backup import create_backup, restore_backup
    packs = manager.assets.portraits
    staged = packs.directory.parent / '.install-downloading' / 'pack'
    staged.mkdir(parents=True)
    (staged / '25.png').write_bytes(png())
    original_copy = shutil.copyfile

    def activate_before_copy(source, target, **kwargs):
        if '.install-downloading' in os.fspath(source):
            staged.rename(packs.directory)
        return original_copy(source, target, **kwargs)

    monkeypatch.setattr(shutil, 'copyfile', activate_before_copy)
    result = create_backup(manager)
    with zipfile.ZipFile(result['path']) as archive:
        assert not any('.install-' in name for name in archive.namelist())
    restored = restore_backup(result['path'], manager.root / 'restored-backup')
    assert (restored / 'app.sqlite').is_file()
