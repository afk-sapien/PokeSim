"""Item artwork uses the bounded optional downloader without changing portraits."""
import threading

from fastapi.testclient import TestClient

from pokesim.activity_ledger import ITEMS, MACHINE_MOVES
from pokesim.app.item_artwork import IMAGES
from pokesim.app.manager import create_app
from pokesim.app.portrait_packs import PortraitPacks
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


def test_install_deduplicates_discs_and_keeps_portraits_independent(manager, monkeypatch):
    requests = upstream(monkeypatch)
    pack = manager.assets.item_artwork
    assert pack.begin()
    pack.install()
    assert pack.status()['active'] == 'community'
    assert pack.status()['completed'] == pack.status()['total'] == 125
    assert len(requests) == len(set(IMAGES.values())) + 1
    assert pack.path(222).read_bytes() == png()
    assert pack.path(198).read_bytes() == png()
    assert pack.path(0) is None and pack.path(251) is None
    assert manager.assets.portraits.status()['active'] == 'default'
    reopened = PortraitPacks(manager.registry, threading.Event(), images=IMAGES,
                             folder='/sprites/items/', pack='item-artwork', setting='item_artwork')
    assert reopened.path(222) == pack.path(222)
    pack.restore()
    assert pack.path(222) is None
    assert not pack.begin()
    assert pack.path(222)
    assert len(requests) == len(set(IMAGES.values())) + 1


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
