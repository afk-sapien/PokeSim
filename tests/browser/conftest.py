"""Serve real application pages and APIs with a synthetic cartridge boundary."""
from contextlib import contextmanager
import io
import os
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


@pytest.fixture
def page(browser, tmp_path):
    context = browser.new_context()
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        yield page
    finally:
        context.tracing.stop(path=str(tmp_path / 'browser-trace.zip'))
        context.close()
    assert errors == [], errors


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
        Image.new('RGB', (160, 144), '#96ad84').save(image, 'JPEG')
        self.frame_jpeg = image.getvalue()
        self.frame_seq = 1

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
