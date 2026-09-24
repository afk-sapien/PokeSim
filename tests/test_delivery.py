"""Pages load from cache where they safely can, and the plumbing never stalls a request."""
import os
import re
import socket

from pokesim.app.manager import cache_policy
from pokesim.web import pages


def test_stamped_assets_are_immutable_and_live_data_is_not_cached():
    assert cache_policy('/static/panel.css', 'v=4a20d18c0760', 'text/css') == 'public, max-age=31536000, immutable'
    assert cache_policy('/games/a1/static/pc.js', 'v=abc', 'text/javascript').endswith('immutable')
    assert cache_policy('/games/a1/static/fonts/pokesim-panel.woff2', '', 'font/woff2') == 'public, max-age=604800'
    assert cache_policy('/games/a1/static/panel.css', '', 'text/css') == 'no-cache'
    assert cache_policy('/games/a1/sprites/25.png', '', 'image/png') == 'private, max-age=86400'
    # A placeholder portrait is replaced once the cartridge is read.
    assert cache_policy('/games/a1/sprites/25.png', '', 'image/svg+xml') == 'no-store'
    assert cache_policy('/games/a1/shots/7.png', '', 'image/png') == 'private, no-cache'
    for path in ('/games/a1/api/state', '/games/a1/frame.jpg', '/games/a1/', '/api/v1/adventures', '/'):
        assert cache_policy(path, 'v=1', 'application/json') == 'no-store'


def test_the_stamp_follows_the_file(tmp_path, monkeypatch):
    (tmp_path / 'a.css').write_text('one')
    monkeypatch.setattr(pages, 'STATIC', tmp_path)
    first = pages.stamp('<link href="/static/a.css?v=old"><script src="/static/missing.js"></script>')
    assert '/static/missing.js"' in first
    (tmp_path / 'a.css').write_text('two')
    os.utime(tmp_path / 'a.css', ns=(1, 1))
    second = pages.stamp('<link href="/static/a.css">')
    assert first.split('"')[1] != second.split('"')[1]
    assert second.split('"')[1].startswith('/static/a.css?v=')


def test_every_page_preloads_the_panel_font():
    # The preload only helps if it names the exact address tokens.css asks for,
    # version included; bump both together when the font changes.
    font = re.search(r'url\("(fonts/pokesim-panel\.woff2[^"]*)"\)', (pages.STATIC / 'tokens.css').read_text())[1]
    for name in ('index.html', 'pc.html', 'pokedex.html', 'journal.html', 'event.html',
                 'trading.html', 'adventure-trading.html', 'library.html'):
        assert f'{font}" as="font"' in (pages.STATIC / name).read_text()


def test_accepted_sockets_inherit_no_delay():
    # The listeners rely on Linux and Windows passing TCP_NODELAY to accepted sockets.
    with socket.socket() as listener:
        listener.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        with socket.create_connection(listener.getsockname()):
            accepted, _ = listener.accept()
            with accepted:
                assert accepted.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
