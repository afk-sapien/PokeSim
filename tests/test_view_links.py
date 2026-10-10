"""View links: /view/<adventure>/ serves the same game pages, read-only."""
import re
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import httpx
import pytest

from pokesim import config
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from pokesim.web.app import create_app as game_app
from pokesim.web.security import VIEWER_HEADER

SAFE = {'GET', 'HEAD'}


def fill(path, value='1'):
    return re.sub(r'\{[^}]+\}', value, path)


def writes(app, value='1'):
    """Every non-read method and path the app routes, so a new endpoint is covered."""
    return sorted({(method, fill(route.path, value)) for route in app.routes if isinstance(route, APIRoute)
                   for method in route.methods - SAFE})


def worker(tmp_path, emu=None):
    shots = tmp_path / 'shots'
    shots.mkdir(exist_ok=True)
    (tmp_path / 'states').mkdir(exist_ok=True)
    events = [{'id': 42, 'title': 'A partner', 'body': 'Caught safely', 'map': 'Town', 'ts': 1000,
               'playtime': '1:02', 'priority': 4, 'type': 'catch', 'shot': '42.png', 'state': 'event-42.state'}]
    store = SimpleNamespace(shots=shots, states=tmp_path / 'states', event=lambda _: events[0],
                            events=lambda **_: events, get=lambda _: None, trade_preferences=lambda: {},
                            progress=lambda: {'state': 'exploring'})
    emu = emu or SimpleNamespace(status=lambda: {'viewer_only': False, 'version': 'test'})
    return game_app(emu, store, base_path='/games/red-two', adventure_id='red-two', adventure_name='Second Red')


@pytest.fixture(autouse=True)
def instance_controls(monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)


@pytest.fixture
def managed(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('fixture', 'sha1', 'red')
    adventure = manager.registry.create('View test', 'fixture', {}, identifier())
    manager.registry.update(adventure['id'], state='running')
    forwarded = []

    async def child(request):
        forwarded.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b'public response'))

    original_client = httpx.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(child), **kwargs))
    monkeypatch.setattr(manager.supervisor, 'child',
                        lambda aid: SimpleNamespace(url='http://127.0.0.1:12345', token='private-worker-token'))
    application = create_app(manager)
    with TestClient(application) as client:
        # A valid session and CSRF token, so a refusal below is the view boundary and not CSRF.
        client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
        yield SimpleNamespace(client=client, aid=adventure['id'], forwarded=forwarded, app=application)


@pytest.mark.parametrize('method,path', [
    ('GET', ''), ('GET', 'api/state'), ('GET', 'api/events'), ('GET', 'api/events/42'), ('GET', 'events/42'),
    ('GET', 'api/progress'), ('GET', 'api/pokedex/status'), ('GET', 'api/trading'), ('GET', 'pc'),
    ('GET', 'journal'), ('GET', 'stats'), ('GET', 'static/app.js'), ('GET', 'shots/42.png'),
    ('GET', 'stream'), ('HEAD', 'frame.jpg'), ('GET', 'feed.xml'),
])
def test_view_link_reads_reach_the_game_marked_view_only(managed, method, path):
    response = managed.client.request(method, f'/view/{managed.aid}/{path}?after=3')
    assert response.status_code == 200
    [request] = managed.forwarded
    assert request.url.path == '/' + path
    assert request.url.query == b'after=3'
    assert request.headers[VIEWER_HEADER] == '1'


@pytest.mark.parametrize('method,path', [('GET', ''), ('GET', 'api/state'), ('POST', 'api/control')])
def test_game_paths_are_unchanged(managed, method, path):
    assert managed.client.request(method, f'/games/{managed.aid}/{path}').status_code == 200
    [request] = managed.forwarded
    assert VIEWER_HEADER.lower() not in request.headers


@pytest.mark.parametrize('path', ['api/states', 'api/export-save'])
def test_view_link_never_reads_saves(managed, path):
    assert managed.client.get(f'/view/{managed.aid}/{path}').status_code == 403
    assert managed.forwarded == []


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_every_game_write_is_refused_under_view(managed, tmp_path, method):
    routes = writes(worker(tmp_path)) + [(method, path) for path in ('/api/control', '/api/trading/preferences',
                                                                     '/api/export-save', '/api/trade')]
    assert ('POST', '/api/control') in routes
    for write_method, path in routes:
        for verb in {write_method, method}:
            response = managed.client.request(verb, f'/view/{managed.aid}{path}', json={'action': 'pause'})
            assert response.status_code == 403, (verb, path)
    assert managed.forwarded == []


def test_every_library_api_is_refused_under_view(managed):
    routes = writes(managed.app, managed.aid)
    assert ('POST', '/api/v1/adventures') in routes and ('PATCH', '/api/v1/settings') in routes
    for method, path in routes:
        for target in (f'/view/{managed.aid}{path}', '/view' + path):
            assert managed.client.request(method, target, json={}).status_code == 403, (method, target)
    # The library's own reads are not part of a view link either.
    for path in ('/api/v1/adventures', '/api/v1/settings', '/api/v1/backups', '/api/v1/session'):
        assert managed.client.get(f'/view/{managed.aid}{path}').status_code == 404
    assert managed.forwarded == []
    assert managed.client.get('/api/v1/adventures').json()['adventures'][0]['name'] == 'View test'


def test_stopped_adventure_view_link_shows_no_library(managed):
    managed.app.state.manager.registry.update(managed.aid, state='stopped')
    response = managed.client.get(f'/view/{managed.aid}/')
    assert response.status_code == 409
    assert 'not running' in response.text and 'library' not in response.text.lower()


def test_view_trading_page_stays_under_view(managed):
    response = managed.client.get(f'/view/{managed.aid}/trading')
    assert response.status_code == 200
    assert f'/view/{managed.aid}/static/' in response.text and f'/games/{managed.aid}/' not in response.text


def test_worker_refuses_every_write_and_save_read_for_a_view_request(tmp_path):
    emu = Mock()
    app = worker(tmp_path, emu)
    client = TestClient(app, headers={VIEWER_HEADER: '1'})
    for method, path in writes(app):
        assert client.request(method, path, json={'action': 'pause'}).status_code == 403, (method, path)
    assert client.get('/api/states').status_code == 403
    assert emu.mock_calls == []


def test_worker_marks_view_requests_view_only_and_scopes_pages(tmp_path):
    client = TestClient(worker(tmp_path))
    viewer = {VIEWER_HEADER: '1'}
    assert client.get('/api/state').json()['viewer_only'] is False
    assert client.get('/api/state', headers=viewer).json()['viewer_only'] is True
    owner = client.get('/').text
    assert 'id="copy-view-link"' in owner and 'data-view-link="/view/red-two/"' in owner
    assert 'id="adventure-switcher"' in owner
    page = client.get('/', headers=viewer).text
    assert 'copy-view-link' not in page and 'adventure-switcher' not in page
    assert '/view/red-two/static/routes.js' in page and '/games/red-two' not in page
    assert client.get('/team', headers=viewer, follow_redirects=False).headers['location'] == '/view/red-two/#team'
    event = client.get('/events/42', headers=viewer).text
    assert 'id="rewind"' not in event and '/view/red-two/shots/42.png' in event
    assert 'id="rewind"' in client.get('/events/42').text


def test_instance_viewer_only_still_applies_everywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    client = TestClient(worker(tmp_path))
    assert client.get('/api/state').json()['viewer_only'] is True
    assert client.post('/api/control', json={'action': 'pause'}).status_code == 403
    assert client.get('/api/states').status_code == 403
