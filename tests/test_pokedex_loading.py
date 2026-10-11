"""The PC and Pokédex load fast: reference data revalidates by ETag, and nothing unused is built."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
import httpx
import pytest

from pokesim import config
from pokesim.app.manager import Manager, cache_policy, create_app as manager_app
from pokesim.app.registry import identifier
from pokesim.gen2 import web as gen2_web
from pokesim.store import Store
from pokesim.web.app import create_app, fast_json


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    store = Store(tmp_path)
    emu = Mock()
    emu.status.return_value = {'game': None, 'strategy': {}}
    try:
        with TestClient(create_app(emu, store)) as client:
            yield client
    finally:
        store.close()


def test_pokedex_reference_answers_a_matching_etag_with_304(client):
    first = client.get('/api/pokedex')
    assert first.status_code == 200 and len(first.json()['entries']) == 151
    etag = first.headers['etag']
    assert etag.startswith('"') and first.headers['cache-control'] == 'private, no-cache'

    again = client.get('/api/pokedex', headers={'If-None-Match': etag})
    assert again.status_code == 304 and again.content == b'' and again.headers['etag'] == etag
    assert client.get('/api/pokedex', headers={'If-None-Match': f'"stale", W/{etag}'}).status_code == 304
    assert client.get('/api/pokedex', headers={'If-None-Match': '"stale"'}).status_code == 200
    # Each version has its own data and its own validator.
    assert client.get('/api/pokedex?version=red').headers['etag'] != client.get('/api/pokedex?version=blue').headers['etag']


def test_managed_pokedex_reference_is_revalidated_not_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    assert cache_policy('/games/a1/api/pokedex', '', 'application/json') == 'private, no-cache'
    assert cache_policy('/view/a1/api/pokedex', '', 'application/json') == 'private, no-cache'
    assert cache_policy('/games/a1/api/pokedex/status', 'view=pc', 'application/json') == 'no-store'

    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('fixture', 'sha1', 'red')
    adventure = manager.registry.create('Cache test', 'fixture', {}, identifier())
    manager.registry.update(adventure['id'], state='running')
    seen = []

    async def child(request):
        seen.append(request.headers.get('if-none-match'))
        if request.headers.get('if-none-match') == '"abc"':
            return httpx.Response(304, headers={'ETag': '"abc"'})
        return httpx.Response(200, headers={'ETag': '"abc"', 'Content-Type': 'application/json'}, content=b'{"entries":[]}')

    original = httpx.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient',
                        lambda **kwargs: original(transport=httpx.MockTransport(child), **kwargs))
    monkeypatch.setattr(manager.supervisor, 'child', lambda aid: SimpleNamespace(url='http://127.0.0.1:1', token='t'))
    with TestClient(manager_app(manager)) as client:
        path = f'/games/{adventure["id"]}/api/pokedex'
        first = client.get(path)
        assert first.status_code == 200 and first.headers['etag'] == '"abc"'
        assert first.headers['cache-control'] == 'private, no-cache'
        again = client.get(path, headers={'If-None-Match': '"abc"'})
        assert again.status_code == 304 and again.content == b''
        # Live status never revalidates: it is always fresh.
        client.get(f'/games/{adventure["id"]}/api/pokedex/status', headers={'If-None-Match': '"abc"'})
    assert seen == [None, '"abc"', None]


def test_managed_pages_carry_the_portrait_stamp(tmp_path, monkeypatch):
    from pokesim.web.pages import render_game_page
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('fixture', 'sha1', 'red')
    adventure = manager.registry.create('Stamp test', 'fixture', {}, identifier())
    manager.registry.update(adventure['id'], state='running')
    page = render_game_page('pc.html', base_path=f'/games/{adventure["id"]}', adventure_id=adventure['id'])
    assert '<meta name="pokesim-sprites" content="rom-portraits-1">' in page

    async def child(request):
        return httpx.Response(200, headers={'Content-Type': 'text/html; charset=utf-8'}, content=page.encode())

    original = httpx.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient',
                        lambda **kwargs: original(transport=httpx.MockTransport(child), **kwargs))
    monkeypatch.setattr(manager.supervisor, 'child', lambda aid: SimpleNamespace(url='http://127.0.0.1:1', token='t'))
    stamp = manager.assets.sprite_version(adventure['id'])
    with TestClient(manager_app(manager)) as client:
        for path in ('pc', 'trading'):
            served = client.get(f'/games/{adventure["id"]}/{path}')
            assert served.status_code == 200 and served.headers['cache-control'] == 'no-store'
            assert f'<meta name="pokesim-sprites" content="{stamp}">' in served.text


def test_fast_json_matches_fastapi_and_falls_back_for_other_values():
    payload = {'party': [{'dvs': (15, 15), 'name': 'Pokémon', 'level': 5.5, 'counts': {25: 2}}], 'plan': None}
    response = fast_json(payload)
    assert json.loads(response.body) == json.loads(json.dumps(jsonable_encoder(payload)))
    assert 'Pokémon' in response.body.decode()
    unusual = {'species': {1, 2}}
    assert fast_json(unusual) is unusual


def test_gen2_pc_status_skips_the_pokedex_plan(monkeypatch):
    def refuse(*_):
        raise AssertionError('The PC never draws the plan')

    monkeypatch.setattr(gen2_web, 'dex_plan', refuse)
    data = SimpleNamespace(game='crystal')
    game = {'party': [{'species': 1, 'egg': True}], 'storage': {'pokemon': []}, 'dex_owned': [1]}
    status = gen2_web.live_status(game, {}, data=data, plan=False)
    assert status['plan'] == [] and status['owned'] == [1] and status['party'][0]['slot'] == 1
    monkeypatch.setattr(gen2_web, 'dex_plan', lambda *_: [{'dex': 1}])
    assert gen2_web.live_status(game, {}, data=data)['plan'] == [{'dex': 1}]
