from html.parser import HTMLParser
from types import SimpleNamespace
from xml.etree import ElementTree

from fastapi.testclient import TestClient
import pytest

from pokesim.web.app import create_app
from pokesim.web.library import render_library


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.urls = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.urls.extend(value for key, value in attrs if key in {'src', 'href'} and value)


def app(tmp_path, **kwargs):
    shots = tmp_path / 'shots'
    shots.mkdir(exist_ok=True)
    events = [{'id': 42, 'title': 'A partner', 'body': 'Caught safely', 'map': 'Town',
               'ts': 1000, 'playtime': '1:02', 'priority': 4, 'type': 'catch',
               'shot': '42.png', 'state': None}]
    store = SimpleNamespace(shots=shots, event=lambda _: events[0], events=lambda **_: events, get=lambda _: None,
                            trade_preferences=lambda: {})
    return create_app(SimpleNamespace(status=lambda: {}), store, **kwargs)


@pytest.mark.parametrize('path', ['/', '/pc', '/pokedex', '/journal', '/trading', '/events/42'])
def test_managed_pages_scope_all_game_resources_and_navigation(tmp_path, path):
    client = TestClient(app(tmp_path, base_path='/games/red-two', adventure_id='red-two', adventure_name='Second Red'))
    response = client.get(path)
    assert response.status_code == 200
    urls = Links(response.text).urls
    assert '/games/red-two/static/routes.js' in urls
    assert '/games/red-two/journal' in urls
    assert '${' not in response.text
    assert all(url.startswith(('/games/red-two/', '#', 'https://')) or url == '/' for url in urls)
    assert 'Second Red' in response.text
    assert 'id="adventure-switcher"' in response.text


def test_standalone_html_and_redirects_keep_root_routes(tmp_path):
    client = TestClient(app(tmp_path))
    assert '/static/routes.js' in Links(client.get('/').text).urls
    assert 'id="adventure-switcher"' not in client.get('/').text
    assert client.get('/team', follow_redirects=False).headers['location'] == '/#team'
    assert client.get('/trading').status_code == 200


def test_managed_redirects_and_feed_keep_identity(tmp_path, monkeypatch):
    from pokesim import config
    monkeypatch.setattr(config, 'PUBLIC_URL', 'https://pokesim.example')
    client = TestClient(app(tmp_path, base_path='/games/blue-three', adventure_id='blue-three'))
    assert client.get('/team', follow_redirects=False).headers['location'] == '/games/blue-three/#team'
    assert client.get('/journey', follow_redirects=False).headers['location'] == '/games/blue-three/#journey-progress'
    assert client.get('/trading', follow_redirects=False).status_code == 200
    feed = ElementTree.fromstring(client.get('/feed.xml').content)
    links = [element.attrib['href'] for element in feed.iter() if 'href' in element.attrib]
    assert all(link.startswith('https://pokesim.example/games/blue-three/') for link in links)


def test_adventure_name_cannot_inject_markup(tmp_path):
    client = TestClient(app(tmp_path, base_path='/games/a', adventure_id='a', adventure_name='<script>bad()</script>'))
    assert '<script>bad()' not in client.get('/').text


def test_base_path_validation_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        app(tmp_path, base_path='/games/../other')


def test_manager_templates_render_without_game_setup():
    for page in ('library', 'trading', 'settings', 'stopped'):
        output = render_library(page, {'id': 'red-one'})
        assert f'data-page="{page}"' in output
        assert '${' not in output
        assert 'data-adventure="red-one"' in output


def test_managed_local_offers_do_not_require_a_legacy_broker(tmp_path, monkeypatch):
    from pokesim.web import trading
    application = app(tmp_path, base_path='/games/a', adventure_id='a')
    monkeypatch.setattr(trading, 'board', lambda: pytest.fail('Managed offers must not contact the old broker'))
    monkeypatch.setattr(trading, 'unavailable', lambda payload, instance, message: {
        'connected': False, 'instance': instance, 'offers': [], 'message': message})
    payload = {'version': 'red', 'owned': [], 'seen': [], 'party': [], 'storage': None}
    application.state.participant = SimpleNamespace(runtime=SimpleNamespace(call=lambda operation: payload), inventory=lambda: payload)
    monkeypatch.setattr('pokesim.web.app.live_status', lambda *args: payload)
    monkeypatch.setattr('pokesim.web.app.preferences.apply', lambda data, _: data)
    result = TestClient(application).get('/api/trading').json()
    assert result['connected'] is True
    assert result['managed'] is True
    assert result['trading'] == {'managed': True, 'enabled': True}
