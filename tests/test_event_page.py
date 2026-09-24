from html.parser import HTMLParser
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.events import Event
from pokesim.store import Store
from pokesim.web.app import create_app
from pokesim.web.event_page import render_event
from test_events import snap


class PageParser(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_event_content_is_text_and_state_is_data():
    event = dict(title='<b>Catch</b>', body='<script>bad()</script>',
                 map='<img src=bad>', playtime='<b>1:02</b>', type='<svg>',
                 priority=4, ts=1000, shot='42" onerror="bad.png',
                 state='event-42" onclick="bad.state')
    page = PageParser(render_event(event, can_rewind=True))
    assert '<script>bad()</script>' in page.text
    assert not any('onclick' in attrs or 'onerror' in attrs for _, attrs in page.tags)
    assert [attrs for tag, attrs in page.tags if tag == 'img'] == [
        {'class': 'shot', 'src': '/shots/' + event['shot'], 'alt': ''}]
    assert [attrs for tag, attrs in page.tags
            if tag == 'button' and 'data-theme-choice' not in attrs] == [
        {'id': 'rewind', 'data-state': event['state']}]
    assert [attrs for tag, attrs in page.tags if tag == 'script'] == [
        {'src': '/static/routes.js'}, {'src': '/static/panel.js?v=panel-3'},
        {'src': '/static/event.js?v=panel-2', 'defer': None}]
    assert not any(tag in {'b', 'svg'} for tag, _ in page.tags)


@pytest.mark.parametrize(('viewer', 'barrier', 'saved', 'visible'), [
    (False, None, True, True),
    (True, None, True, False),
    (False, '123', True, False),
    (False, None, False, False),
])
def test_event_route_preserves_rewind_restrictions(tmp_path, monkeypatch, viewer, barrier, saved, visible):
    monkeypatch.setattr(config, 'VIEWER_ONLY', viewer)
    store = Store(tmp_path)
    emu = Mock()
    try:
        eid = store.add_event(Event('catch', 'A partner', priority=4), snap(), None,
                              b'state' if saved else None)
        if barrier:
            store.set('trade_barrier', barrier)
        with TestClient(create_app(emu, store)) as client:
            response = client.get(f'/events/{eid}')
            assert response.status_code == 200
            assert ('id="rewind"' in response.text) == visible
            assert '/static/event.js' in response.text
            assert '<img' not in response.text
            assert client.get('/events/999999').status_code == 404
            if saved:
                result = client.post('/api/control', json={
                    'action': 'load_state', 'value': f'event-{eid}.state'})
                assert result.status_code == (403 if viewer else 409 if barrier else 200)
                if visible:
                    emu.command.assert_called_once_with('load_state', f'event-{eid}.state')
                else:
                    emu.command.assert_not_called()
            assert client.get('/static/event.js').status_code == 200
    finally:
        store.close()
