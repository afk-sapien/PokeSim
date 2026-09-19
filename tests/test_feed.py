from html.parser import HTMLParser
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from pokesim import config
from pokesim.events import Event
from pokesim.store import Store
from pokesim.web.app import create_app
from pokesim.web.feed import ATOM_NAMESPACE, render_feed
from test_events import snap

NS = {'atom': ATOM_NAMESPACE}


def feed_event(**changes):
    event = {
        'id': 42, 'ts': 1000, 'title': 'A new partner', 'body': 'Caught safely',
        'map': 'Pallet Town', 'playtime': '1:02:03', 'type': 'catch',
        'priority': 4, 'shot': '42.png',
    }
    return event | changes


def test_empty_feed_has_stable_timestamp_and_no_entries():
    root = ElementTree.fromstring(render_feed([], 'https://example.test/', 'Adventure'))
    assert root.tag == f'{{{ATOM_NAMESPACE}}}feed'
    assert root.findtext('atom:title', namespaces=NS) == 'Adventure'
    assert root.findtext('atom:updated', namespaces=NS) == '1970-01-01T00:00:00Z'
    assert root.findtext('atom:id', namespaces=NS) == 'https://example.test/feed.xml'
    assert root.findall('atom:entry', NS) == []


def test_feed_round_trips_xml_special_characters():
    base = 'https://example.test/a&b'
    title = 'Red & Blue <adventures>'
    event = feed_event(title=title, type='catch&obtain', shot='42&partner.png')
    root = ElementTree.fromstring(render_feed([event], base, title))
    assert root.findtext('atom:title', namespaces=NS) == title
    entry = root.find('atom:entry', NS)
    assert entry.findtext('atom:title', namespaces=NS) == title
    assert entry.find('atom:link', NS).get('href') == f'{base}/events/42'
    assert entry.find('atom:category', NS).get('term') == 'catch&obtain'
    assert entry.find("atom:link[@rel='enclosure']", NS).get('href') == f'{base}/shots/42&partner.png'


def test_feed_html_content_keeps_event_text_out_of_markup():
    class ContentParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []
            self.text = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

        def handle_data(self, data):
            self.text.append(data)

    event = feed_event(body='<script>bad()</script>', map='<b>Town</b>',
                       playtime='<img src=bad>', shot='42" onerror="bad.png')
    root = ElementTree.fromstring(render_feed([event], 'https://example.test', 'Adventure'))
    content = root.find('atom:entry/atom:content', NS)
    assert content.get('type') == 'html'
    parser = ContentParser()
    parser.feed(content.text)
    assert [tag for tag, attrs in parser.tags] == ['p', 'img', 'p', 'p', 'small']
    assert parser.tags[1][1] == {
        'src': 'https://example.test/shots/42" onerror="bad.png',
        'alt': '', 'width': '640', 'height': '576',
    }
    assert '<script>bad()</script>' in parser.text
    assert '<b>Town</b> · play time <img src=bad>' in parser.text


def test_feed_without_screenshot_omits_enclosure():
    root = ElementTree.fromstring(render_feed([feed_event(shot=None)], 'https://example.test', 'Adventure'))
    entry = root.find('atom:entry', NS)
    assert entry.find("atom:link[@rel='enclosure']", NS) is None
    assert '<img' not in entry.findtext('atom:content', namespaces=NS)


def test_feed_route_preserves_filters_and_content_type(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'PUBLIC_URL', 'https://example.test/a&b')
    store = Store(tmp_path)
    try:
        store.add_event(Event('map', 'Arrived', priority=2), snap(), None, None)
        store.add_event(Event('catch', 'Caught & kept', priority=4), snap(), b'image', None)
        with TestClient(create_app(None, store)) as client:
            response = client.get('/feed.xml?types=catch&min_priority=4&limit=1')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/atom+xml'
        root = ElementTree.fromstring(response.content)
        entries = root.findall('atom:entry', NS)
        assert len(entries) == 1
        assert entries[0].findtext('atom:title', namespaces=NS) == 'Caught & kept'
    finally:
        store.close()
