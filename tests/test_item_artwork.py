"""Item artwork uses the bounded optional downloader without changing portraits."""
import json
import os
import threading

from fastapi.testclient import TestClient
import pytest

from pokesim.activity_ledger import ITEMS, MACHINE_MOVES
from pokesim.app.item_artwork import GEN2_IMAGES, IMAGES, SETS, VERSION_SETS
from pokesim.app.manager import STATIC, create_app
from pokesim.app.portrait_packs import REVISION, PortraitPacks
from pokesim.app.registry import identifier
from pokesim.pokemon import TYPES
from pokesim.strategy_data import MOVES
from test_portrait_packs import manager, upstream, png


def test_mapping_covers_items_and_uses_generation_one_move_types():
    assert set(IMAGES) == set(ITEMS)
    moves = {move['name']: move for move in MOVES.values()}
    for item, name in MACHINE_MOVES.items():
        prefix = 'hm-' if item < 201 else 'tm-'
        assert IMAGES[item] == prefix + TYPES[moves[name]['type']].lower() + '.png'
    assert IMAGES[222] == 'tm-grass.png'
    assert IMAGES[198] == 'hm-water.png'
    assert IMAGES[75] == 'exp-share.png'


def test_generation_two_mapping_uses_only_shared_upstream_names():
    assert len(GEN2_IMAGES) == 203 and set(GEN2_IMAGES) <= set(range(1, 250))
    # Johto berries take the name each one became in Generation III.
    assert GEN2_IMAGES[74] == 'pecha-berry.png' and GEN2_IMAGES[173] == 'oran-berry.png'
    assert GEN2_IMAGES[55] == IMAGES[71] == 'dowsing-machine.png'
    # TM01 Dynamic Punch, TM30 Shadow Ball, HM07 Waterfall. TM03 Curse has no disc colour.
    assert (GEN2_IMAGES[191], GEN2_IMAGES[222], GEN2_IMAGES[249]) == ('tm-fighting.png', 'tm-ghost.png', 'hm-water.png')
    assert 193 not in GEN2_IMAGES
    assert set(VERSION_SETS.values()) == set(SETS)


@pytest.mark.skipif(not os.environ.get('GEN2_DATA_DIR'), reason='Set GEN2_DATA_DIR to generated local game data')
@pytest.mark.parametrize('game', ['gold', 'silver', 'crystal'])
def test_generation_two_discs_follow_the_cartridge_move_types(game):
    from pokesim.gen2.data import GameData
    data = GameData.load(os.environ['GEN2_DATA_DIR'], game)
    moves = {move['constant']: move for move in data.moves.values()}
    discs = {item: constant for constant, item in data.items.items() if constant.startswith(('TM_', 'HM_'))}
    for item, filename in GEN2_IMAGES.items():
        if item in discs:
            move = moves[discs[item].split('_', 1)[1]]
            assert filename == f"{discs[item][:2].lower()}-{data.type_names[move['type']].lower()}.png"


def test_install_deduplicates_discs_and_keeps_portraits_independent(manager, monkeypatch):
    requests = upstream(monkeypatch)
    pack = manager.assets.item_artwork
    assert pack.begin()
    pack.install()
    assert pack.status()['active'] == 'community'
    assert pack.status()['completed'] == pack.status()['total'] == 125 + 203
    # Both generations share one upstream folder, so a shared file is fetched once.
    fetched = len(set(IMAGES.values()) | set(GEN2_IMAGES.values())) + 1
    assert len(requests) == fetched
    assert pack.path(222).read_bytes() == png()
    assert pack.path(198).read_bytes() == png()
    assert pack.path(0) is None and pack.path(251) is None
    assert pack.path(109, version='crystal').read_bytes() == png()
    assert pack.path(109, version='red') is None
    assert pack.path(250, version='gold') is None
    assert manager.assets.portraits.status()['active'] == 'default'
    reopened = PortraitPacks(manager.registry, threading.Event(), sets=SETS, legacy='generation-i',
                             versions=VERSION_SETS, pack='item-artwork', setting='item_artwork')
    assert reopened.path(222) == pack.path(222)
    pack.restore()
    assert pack.path(222) is None
    assert not pack.begin()
    assert pack.path(222)
    assert len(requests) == fetched


def test_single_set_install_keeps_red_icons_and_adds_johto_icons(manager, monkeypatch):
    # Before Gold, Silver and Crystal icons, the pack held Red item images at its root.
    directory = manager.assets.item_artwork.directory
    directory.mkdir(parents=True)
    for item in IMAGES:
        (directory / f'{item}.png').write_bytes(png())
    (directory / 'manifest.json').write_text(json.dumps({'revision': REVISION, 'count': len(IMAGES)}))
    manager.registry.set_setting('item_artwork', True)
    pack = manager.assets.item_artwork
    assert pack.path(222) == directory / '222.png'
    assert pack.path(109, version='crystal') is None
    status = pack.status()
    assert status['active'] == 'community' and not status['installed']
    assert status['sets'] == {'generation-i': True, 'generation-ii': False}
    # Settings keeps the download button for this partial pack, even while it is active.
    script = (STATIC / 'library.js').read_text(encoding='utf-8')
    script = script[script.index('function renderItemArtwork'):script.index('async function refreshItemArtwork')]
    assert "install.hidden = data.active === 'community' && data.installed && !data.busy" in script
    assert "'Download icons for all games'" in script
    requests = upstream(monkeypatch)
    assert pack.begin()
    pack.install()
    assert pack.status()['installed']
    assert pack.path(109, version='crystal').is_file()
    # The Red images were carried over, so only the Johto set and the notice were fetched.
    assert len(requests) == len(set(GEN2_IMAGES.values())) + 1


def test_a_johto_adventure_reads_its_own_item_icons(manager, monkeypatch):
    upstream(monkeypatch)
    manager.registry.add_rom('johto', 'sha1', 'crystal')
    aid = manager.registry.create('Johto icons', 'johto', {}, identifier())['id']
    manager.assets.item_artwork.begin()
    manager.assets.item_artwork.install()
    with TestClient(create_app(manager)) as client:
        assert client.get(f'/games/{aid}/item-artwork/109.png').content == png()
        # Red has an item 250 (TM50), Crystal does not.
        assert client.get(f'/games/{aid}/item-artwork/250.png').status_code == 404
    script = (STATIC / 'activity.js').read_text(encoding='utf-8')
    assert 'generation === 2) itemArtwork = null' not in script


def test_item_routes_require_owner_action_and_serve_only_active_pack(manager, monkeypatch):
    requests = upstream(monkeypatch)
    with TestClient(create_app(manager)) as client:
        assert client.get('/api/v1/item-artwork').json()['active'] == 'default'
        assert client.get('/api/v1/item-artwork/images/222.png').status_code == 404
        assert not requests
        assert client.post('/api/v1/item-artwork/install').status_code == 403
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        held = []
        monkeypatch.setattr(manager, 'background', lambda function: held.append(function))
        assert client.post('/api/v1/item-artwork/install', headers=headers).json()['busy']
        assert client.post('/api/v1/item-artwork/install', headers=headers).status_code == 409
        assert not requests
        held[0]()
        response = client.get('/api/v1/item-artwork/images/222.png')
        assert response.content == png() and response.headers['content-type'] == 'image/png'
        cached = client.get('/api/v1/item-artwork/images/222.png?v=pinned')
        assert cached.headers['cache-control'] == 'private, max-age=86400'
        assert client.get('/api/v1/item-artwork/images/251.png').status_code == 404
        assert client.post('/api/v1/item-artwork/default', headers=headers).json()['active'] == 'default'
        assert client.get('/api/v1/item-artwork/images/222.png').status_code == 404


def test_view_links_read_item_artwork_without_the_library_api(manager, monkeypatch):
    # A proxy opens only /view/ to anonymous watchers, so the item ledger reads artwork there.
    upstream(monkeypatch)
    manager.registry.add_rom('fixture', 'sha1', 'red')
    aid = manager.registry.create('Artwork', 'fixture', {}, identifier())['id']
    with TestClient(create_app(manager)) as client:
        for base in (f'/view/{aid}', f'/games/{aid}'):
            assert client.get(base + '/item-artwork').json() == {'active': 'default', 'revision': REVISION}
            assert client.get(base + '/item-artwork/222.png').status_code == 404
        manager.assets.item_artwork.begin()
        manager.assets.item_artwork.install()
        for base in (f'/view/{aid}', f'/games/{aid}'):
            assert client.get(base + '/item-artwork').json()['active'] == 'community'
            response = client.get(base + '/item-artwork/222.png?v=pinned')
            assert response.content == png() and response.headers['cache-control'] == 'private, max-age=86400'
            assert client.get(base + '/item-artwork/251.png').status_code == 404
            assert client.get(base + '/item-artwork/..%2F..%2Fapi%2Fv1%2Fsettings').status_code == 404
        assert client.post(f'/view/{aid}/item-artwork').status_code == 403
    script = (STATIC / 'activity.js').read_text(encoding='utf-8')
    assert '/api/v1/' not in script and "PokeSim.fetch('/item-artwork'" in script
