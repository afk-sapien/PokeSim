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


COLORS = {'red-blue': (200, 40, 40, 255), 'yellow': (230, 200, 30, 255), 'gold': (180, 140, 20, 255),
          'silver': (150, 150, 160, 255), 'crystal': (60, 160, 220, 255)}
IMAGES = 151 + 151 + 3 * 251


def png(size=(96, 96), color=(80, 140, 60, 255)):
    result = io.BytesIO()
    Image.new('RGBA', size, color).save(result, 'PNG')
    return result.getvalue()


def art(name):
    return png(color=COLORS[name])


def upstream(monkeypatch, fail=None):
    requests = []
    def respond(request):
        requests.append(str(request.url))
        if request.url.path.endswith('/LICENCE.txt'):
            return httpx.Response(200, content=b'Synthetic source notice')
        if fail and request.url.path.endswith('/51.png'):
            return fail
        for name, (folder, _) in portrait_packs.PORTRAIT_SETS.items():
            if folder in request.url.path:
                return httpx.Response(200, content=art(name))
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
    shared = manager.root / 'assets' / 'sprites'
    shared.mkdir(parents=True)
    (shared / '25.png').write_bytes(b'cartridge portrait')
    (shared / '4.png').write_bytes(b'cartridge charmander')
    override = manager.root / 'adventures' / row['id'] / 'sprites'
    override.mkdir()
    (override / '4.png').write_bytes(b'hand-installed override')
    assert not requests
    assert packs.status()['active'] == 'default'
    assert packs.begin()
    assert packs.status()['busy']
    with pytest.raises(ValueError, match='already downloading'):
        packs.begin()
    with pytest.raises(ValueError, match='Wait'):
        packs.restore()
    assert assets.sprite_path(row['id'], 25).read_bytes() == b'cartridge portrait'
    packs.install()
    assert len(requests) == IMAGES + 1
    assert all(url.startswith(portrait_packs.RAW + '/') for url in requests)
    for folder, images in portrait_packs.PORTRAIT_SETS.values():
        assert sum(folder in url for url in requests) == len(images)
    status = packs.status()
    assert status['active'] == 'community' and status['installed']
    assert status['completed'] == status['total'] == IMAGES
    assert status['sets'] == dict.fromkeys(portrait_packs.PORTRAIT_SETS, True)
    assert status['source'] == portrait_packs.SOURCE + '/sprites/pokemon/versions'
    assert status['license'].endswith(portrait_packs.REVISION + '/LICENCE.txt')
    assert assets.sprite_path(row['id'], 25).read_bytes() == art('red-blue')
    assert assets.sprite_path(row['id'], 4).read_bytes() == b'hand-installed override'
    assert (packs.directory / 'LICENCE.txt').read_bytes() == b'Synthetic source notice'
    assert not (packs.directory.parent / ('.install-' + portrait_packs.REVISION)).exists()
    reopened = portrait_packs.PortraitPacks.portraits(manager.registry, threading.Event())
    assert reopened.status()['active'] == 'community' and reopened.status()['installed']
    packs.restore()
    assert assets.sprite_path(row['id'], 25).read_bytes() == b'cartridge portrait'
    assert not packs.begin()
    assert len(requests) == IMAGES + 1
    assert packs.status()['active'] == 'community'


def test_each_adventure_uses_the_pack_set_of_its_own_version(manager, monkeypatch):
    upstream(monkeypatch)
    assets = manager.assets
    rows = {}
    for version in ('red', 'blue', 'gold', 'silver', 'crystal'):
        assets.registry.add_rom(version, 'sha1-' + version, version)
        rows[version] = assets.registry.create(version.title(), version, {}, identifier())['id']
    # Yellow adventures arrive separately. The pack only needs the version key.
    rows['yellow'] = assets.registry.create('Yellow', 'red', {}, identifier())['id']
    with assets.registry.lock, assets.registry.db:
        assets.registry.db.execute("UPDATE adventures SET version='yellow' WHERE id=?", (rows['yellow'],))
    for version in ('gold', 'silver', 'crystal'):
        cartridge = manager.root / 'assets' / 'sprites' / version
        cartridge.mkdir(parents=True)
        (cartridge / '200.png').write_bytes(b'cartridge ' + version.encode())
    crystal_override = manager.root / 'adventures' / rows['crystal'] / 'sprites'
    crystal_override.mkdir()
    (crystal_override / '201.png').write_bytes(b'crystal override')
    assert assets.sprite_path(rows['gold'], 200).read_bytes() == b'cartridge gold'
    assert assets.sprite_path(rows['crystal'], 201).read_bytes() == b'crystal override'
    packs = assets.portraits
    packs.begin()
    packs.install()
    expected = {'red': 'red-blue', 'blue': 'red-blue', 'yellow': 'yellow',
                'gold': 'gold', 'silver': 'silver', 'crystal': 'crystal'}
    for version, name in expected.items():
        assert assets.sprite_path(rows[version], 25).read_bytes() == art(name), version
    for version in ('gold', 'silver', 'crystal'):
        assert assets.sprite_path(rows[version], 251).read_bytes() == art(version)
    assert assets.sprite_path(rows['red'], 200) is None
    assert assets.sprite_path(rows['yellow'], 152) is None
    assert assets.sprite_path(rows['crystal'], 201).read_bytes() == b'crystal override'
    assert packs.path(25, version='unknown') is None
    packs.restore()
    assert assets.sprite_path(rows['gold'], 200).read_bytes() == b'cartridge gold'
    assert assets.sprite_path(rows['silver'], 25) is None


def legacy_install(manager):
    """The layout 0.4.x left behind: Red/Blue images at the pack root and no set list."""
    import json
    directory = manager.assets.portraits.directory
    directory.mkdir(parents=True)
    for dex in range(1, 152):
        (directory / f'{dex}.png').write_bytes(png(color=(1, 2, 3, 255)))
    (directory / 'LICENCE.txt').write_bytes(b'Older notice')
    (directory / 'manifest.json').write_text(json.dumps({
        'revision': portrait_packs.REVISION, 'source': portrait_packs.SOURCE, 'count': 151}))
    manager.registry.set_setting('community_portraits', True)
    return directory


def test_single_set_install_keeps_working_and_upgrades_without_refetching(manager, monkeypatch):
    requests = upstream(monkeypatch)
    legacy_install(manager)
    assets = manager.assets
    for version in ('red', 'crystal'):
        assets.registry.add_rom(version, 'sha1-' + version, version)
    red = assets.registry.create('Red', 'red', {}, identifier())['id']
    crystal = assets.registry.create('Crystal', 'crystal', {}, identifier())['id']
    packs = assets.portraits
    status = packs.status()
    assert status['active'] == 'community' and not status['installed']
    assert status['sets'] == {'red-blue': True, 'yellow': False, 'gold': False, 'silver': False, 'crystal': False}
    assert assets.sprite_path(red, 25).read_bytes() == png(color=(1, 2, 3, 255))
    assert assets.sprite_path(crystal, 25) is None
    assert packs.begin()
    packs.install()
    assert not any('/red-blue/' in url for url in requests)
    assert len(requests) == IMAGES - 151 + 1
    assert packs.status()['installed'] and packs.status()['completed'] == IMAGES
    assert assets.sprite_path(red, 25).read_bytes() == png(color=(1, 2, 3, 255))
    assert assets.sprite_path(crystal, 25).read_bytes() == art('crystal')
    assert not (packs.directory / '25.png').exists()
    assert (packs.directory / 'red-blue' / '25.png').is_file()
    assert not [path for path in packs.directory.parent.iterdir() if path.name.startswith('.install-')]


@pytest.mark.parametrize('failure', [
    httpx.Response(404), httpx.Response(302, headers={'Location': 'https://example.com/image'}),
    httpx.Response(200, content=b'not a PNG'),
    httpx.Response(200, content=b'x' * (portrait_packs.MAX_IMAGE_BYTES + 1)),
    httpx.Response(200, content=png((257, 256))),
])
def test_failed_download_never_activates_a_partial_pack(manager, monkeypatch, failure):
    first = upstream(monkeypatch, failure)
    packs = manager.assets.portraits
    assert packs.begin()
    packs.install()
    status = packs.status()
    assert status['error'] and not status['busy']
    assert 'Finished images are kept' in status['error']
    assert status['active'] == 'default' and not status['installed']
    assert not packs.directory.exists()
    assert [path.name for path in packs.directory.parent.iterdir()] == ['.install-' + portrait_packs.REVISION]
    assert packs.begin()
    second = upstream(monkeypatch)
    packs.install()
    assert not packs.status()['busy']
    assert packs.status()['active'] == 'community'
    assert packs.status()['completed'] == IMAGES
    fetched = {url for url in first if not url.endswith('/51.png')}
    assert not fetched & set(second)
    assert len(fetched) + len(second) >= IMAGES + 1


def test_resume_refetches_a_damaged_staged_image(manager, monkeypatch):
    upstream(monkeypatch, httpx.Response(404))
    packs = manager.assets.portraits
    packs.begin()
    packs.install()
    staged = packs.directory.parent / ('.install-' + portrait_packs.REVISION)
    damaged = next(path for path in staged.glob('*/*.png'))
    damaged.write_bytes(b'truncated')
    folder = portrait_packs.PORTRAIT_SETS[damaged.parent.name][0]
    requests = upstream(monkeypatch)
    packs.begin()
    packs.install()
    assert any(url.endswith(folder + damaged.name) for url in requests)
    assert packs.status()['installed']
    portrait_packs.validate_png((packs.directory / damaged.parent.name / damaged.name).read_bytes())


def test_pack_size_is_bounded(manager, monkeypatch):
    upstream(monkeypatch)
    monkeypatch.setattr(portrait_packs, 'MAX_PACK_BYTES', 50 * len(png()))
    packs = manager.assets.portraits
    packs.begin()
    packs.install()
    assert packs.status()['error'] and not packs.status()['installed']


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
        assert image.content == art('red-blue') and image.headers['cache-control'] == 'no-store'
        assert client.get('/api/v1/portraits/preview/152.png').status_code == 404
        assert client.post('/api/v1/portraits/default', headers=headers).json()['active'] == 'default'
        assert len(requests) == IMAGES + 1


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
        assert installed.content == art('red-blue')
        assert installed.headers['etag'] != before.headers['etag']
        assert installed.headers['cache-control'] == 'private, no-cache'
        packs.restore()
        assert client.get(url).content == before.content


def test_shutdown_cancellation_keeps_defaults_and_activates_nothing(manager, monkeypatch):
    upstream(monkeypatch)
    packs = manager.assets.portraits
    packs.begin()
    packs.cancelled.set()
    packs.install()
    assert packs.status()['active'] == 'default'
    assert not packs.status()['busy']
    assert not packs.directory.exists()


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
