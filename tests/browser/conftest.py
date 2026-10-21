"""Serve real application pages and APIs with a synthetic cartridge boundary."""
from contextlib import contextmanager
import io
import os
import re
from pathlib import Path
import socket
import threading
import time

import pytest
from PIL import Image
import uvicorn

from pokesim import config
from pokesim.broker import inventory, routine
from pokesim.events import Event
from pokesim.ram import PartyMon, Snapshot, StoredMon
from pokesim.store import Store
from pokesim.trade import preferences
from pokesim.web import trading
from pokesim.web.app import create_app
from pokesim.web.pokedex import live_status


@pytest.fixture(scope='session')
def browser():
    if os.environ.get('POKESIM_BROWSER_TESTS') != '1':
        pytest.skip('Set POKESIM_BROWSER_TESTS=1 to run the real Chromium checks')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def pytest_configure(config):
    config.addinivalue_line('markers', 'expected_errors(*patterns): browser errors this test causes on purpose. '
                                       'Each pattern is a regular expression that must match at least one error.')


class BrowserErrors:
    """Every script error, failed request and error response one page sees.

    Each error is one line, "kind url text", so a test can declare the ones it causes on purpose
    with a regular expression. Requests cut off by a navigation are not errors: the browser cancels
    the old page's polls and streams whenever the test moves to another page.
    """

    def __init__(self, page):
        self.found = []
        self.patterns = []
        self.navigations = 0
        self.closing = False
        self.started = {}
        page.on('framenavigated', self.navigated)
        page.on('request', lambda request: self.started.setdefault(request, self.navigations))
        page.on('console', self.console)
        page.on('pageerror', lambda error: self.add('pageerror', page.url, f'{error.name}: {error.message}'))
        page.on('response', self.response)
        page.on('requestfailed', self.failed)

    def navigated(self, frame):
        if frame.parent_frame is None:
            self.navigations += 1

    def add(self, kind, url, text):
        if not self.closing:
            self.found.append(f'{kind} {url} {text}'.strip())

    def console(self, message):
        if message.type == 'error':
            self.add('console', message.location.get('url', ''), message.text)

    def response(self, response):
        if response.status >= 400:
            self.add(f'http {response.status}', response.url, response.request.method)

    def failed(self, request):
        text = request.failure or ''
        # A navigation cancels what the old page was loading, and the live screen drops a frame
        # it has already replaced. Neither is a failure.
        cancelled = text == 'net::ERR_ABORTED' and (
            self.started.get(request, self.navigations) != self.navigations or request.resource_type == 'image')
        if not cancelled:
            self.add('requestfailed', request.url, f'{request.method} {text}')

    def expect(self, *patterns):
        self.patterns += [re.compile(pattern) for pattern in patterns]

    def check(self):
        unexpected = [line for line in self.found if not any(p.search(line) for p in self.patterns)]
        unused = [p.pattern for p in self.patterns if not any(p.search(line) for line in self.found)]
        problems = []
        if unexpected:
            problems.append(f'{len(unexpected)} unexpected browser errors:\n' + '\n'.join(f'  {line}' for line in unexpected))
        if unused:
            problems.append('expected_errors patterns that matched nothing:\n' + '\n'.join(f'  {p}' for p in unused))
        return '\n'.join(problems)


def refused(path, status):
    """Patterns for one error response a test causes on purpose: the response and Chromium's console line for it."""
    path = re.escape(path)
    return (rf'^http {status} \S*{path}',
            rf'^console \S*{path}\S* Failed to load resource: the server responded with a status of {status}\b')


def frame_png():
    image = io.BytesIO()
    Image.new('RGBA', (56, 56), (40, 120, 60, 255)).save(image, 'PNG')
    return image.getvalue()


def frame_jpeg():
    image = io.BytesIO()
    Image.new('RGB', (160, 144), '#99aa77').save(image, 'JPEG')
    return image.getvalue()


def serve_screens(page):
    """Library cards marked running show their game screen. No game process runs behind these registries."""
    frame = frame_jpeg()
    page.route('**/frame.jpg', lambda route: route.fulfill(body=frame, content_type='image/jpeg'))


@pytest.fixture
def expected_errors(request):
    """Declare browser errors the test causes on purpose, for example a faked refusal or an aborted request."""
    return request.node.stash[ERRORS].expect


ERRORS = pytest.StashKey()


@pytest.fixture
def page(browser, tmp_path, request):
    context = browser.new_context()
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    errors = request.node.stash[ERRORS] = BrowserErrors(page)
    for marker in request.node.iter_markers('expected_errors'):
        errors.expect(*marker.args)
    try:
        yield page
    finally:
        # Closing the page cancels its live polls and streams, which are not errors.
        errors.closing = True
        context.tracing.stop(path=str(tmp_path / 'browser-trace.zip'))
        context.close()
    problems = errors.check()
    assert not problems, problems


@contextmanager
def serve(factory):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        url = f'http://127.0.0.1:{listener.getsockname()[1]}'
        app = factory(url)
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', timeout_graceful_shutdown=2))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, 'Test server did not start'
            yield url
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), 'Test server did not stop'


class SyntheticEmulator:
    def __init__(self, store):
        self.store = store
        self.commands = []
        self.connected = False
        party = (PartyMon(153, 30, 30, 15, 'LEAF', dvs=(8,) * 5, stat_exp=(0,) * 5, trainer_id=100),)
        boxed = tuple(StoredMon(0, i, 153, level, name, (33, 45, 0, 0), level ** 3,
                                (i + 1,) * 5, (0,) * 5, 100)
                      for i, level, name in [(0, 5, 'BUD'), (1, 20, 'FERN')])
        self.snapshot = Snapshot(frame=900, map=1, x=5, y=5, badges=0, party=party,
                                 owned=frozenset({1}), seen=frozenset({1}), money=3000, items=(),
                                 in_battle=0, battle_type=0, enemy_species=0, enemy_level=0,
                                 opponent=0, player_name='RED', rival_name='BLUE', playtime=(0, 5, 0),
                                 textbox=False, start_menu=False, stored_details=boxed,
                                 stored_pokemon=tuple((p.box, p.species, p.level, p.nick) for p in boxed),
                                 box_counts=(2,) + (0,) * 11)
        image = io.BytesIO()
        Image.new('RGB', (160, 144), '#96ad84').save(image, 'PNG')
        self.frame_image = image.getvalue()
        self.frame_seq = 1
        self.watched = 0

    def watch(self):
        """The real emulator only encodes frames while something is asking for them."""
        self.watched += 1

    def current_frame(self, timeout: float = 1.0) -> bytes:
        self.watch()
        return self.frame_image

    def status(self):
        return dict(game=self.snapshot.to_dict(), strategy={'collection': {'version': 'red'}},
                    viewer_only=config.VIEWER_ONLY, paused=False, speed=1, frame=900,
                    version='browser-test', uptime=1, manual_mode=False, health=self.health(),
                    reloads=0, areas_discovered=1)

    def health(self):
        return {'ok': True}

    def command(self, name, value=None):
        self.commands.append((name, value))

    def set_trade_preference(self, key, state):
        preferences.update(self.store, live_status(self.snapshot.to_dict()), key, state)

    def board(self):
        if not self.connected:
            raise ValueError('Disconnected for this scenario')
        payload = preferences.apply(live_status(self.snapshot.to_dict()), self.store.trade_preferences())
        local = inventory.normalise('red', '', payload)
        return {'instances': [{**local.summary(), 'offers': routine.listings(local)}],
                'routine_proposals': [], 'trading': {'enabled': True, 'state': 'ready'}}


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    monkeypatch.setattr(config, 'TRADING_INSTANCE', 'red')
    monkeypatch.setattr(config, 'TRADING_URL', '')
    store = Store(tmp_path / 'game')
    emu = SyntheticEmulator(store)
    monkeypatch.setattr(trading, 'board', emu.board)
    eid = store.add_event(Event('catch', 'Caught a partner', priority=4), emu.snapshot, None, b'checkpoint')
    try:
        with serve(lambda url: create_app(emu, store, browser_origin=url)) as url:
            yield url, store, emu, eid
    finally:
        store.close()
