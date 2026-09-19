"""Exercise browser behavior against the real HTTP routes and persisted preferences."""
import hashlib

import pytest

from pokesim import config, desktop, desktop_setup
from pokesim.web.app import create_app
from conftest import serve


def expect(value):
    from playwright.sync_api import expect as assertion
    return assertion(value)


@pytest.mark.parametrize('width', [1280, 390])
def test_pc_lock_persists_after_refresh_even_when_trading_is_offline(page, game, width):
    url, store, emu, _ = game
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(url + '/pc?scope=all')
    row = page.locator('.pc-list-row').filter(has_text='BUD')
    expect(row.get_by_role('button', name='Lock Pokémon', exact=True)).to_be_enabled()
    row.get_by_role('button', name='Lock Pokémon', exact=True).click()
    expect(row.get_by_role('button', name='Unlock Pokémon', exact=True)).to_be_visible()
    assert any(value['state'] == 'locked' for value in store.trade_preferences().values())
    page.reload()
    expect(row.get_by_role('button', name='Unlock Pokémon', exact=True)).to_be_visible()
    row.get_by_role('button', name='Unlock Pokémon', exact=True).click()
    expect(row.get_by_role('button', name='Lock Pokémon', exact=True)).to_be_visible()
    assert all(value['state'] != 'locked' for value in store.trade_preferences().values())


def test_trading_availability_and_viewer_mode_reach_real_controls(page, game, monkeypatch):
    url, store, emu, _ = game
    page.goto(url + '/trading')
    expect(page.locator('#trade-connection-note')).to_contain_text('not connected')
    expect(page.get_by_role('button', name='Withdraw offer').first).to_be_disabled()
    emu.connected = True
    page.reload()
    offer = page.get_by_role('button', name='Withdraw offer').first
    expect(offer).to_be_enabled()
    offer.click()
    expect(page.locator('#toast')).to_contain_text('Offer withdrawn')
    assert any(value['state'] == 'withdrawn' for value in store.trade_preferences().values())
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    page.goto(url + '/pc?scope=all')
    expect(page.get_by_role('button', name='Lock Pokémon', exact=True).first).to_be_disabled()
    assert emu.commands == []


def test_rewind_rejection_keeps_event_page_and_retry_navigates(page, game):
    url, store, emu, eid = game
    page.goto(f'{url}/events/{eid}')
    button = page.get_by_role('button', name='Rewind the live game to this moment')
    expect(button).to_be_visible()
    # A hold can begin after the page was rendered. Exercise the server rejection.
    store.set('trade_hold', {'id': '123'})
    button.click()
    expect(page.get_by_role('alert')).to_contain_text('holding this adventure')
    assert page.url == f'{url}/events/{eid}' and emu.commands == []
    store.set('trade_hold', None)
    button.click()
    page.wait_for_url(url + '/')
    assert emu.commands == [('load_state', f'event-{eid}.state')]


def test_desktop_upload_validation_retry_and_shutdown(page, game, tmp_path, monkeypatch):
    _, _, emu, _ = game
    raw = b'synthetic-browser-cartridge'
    monkeypatch.setitem(desktop_setup.ROM_NAMES, hashlib.sha1(raw).hexdigest(), 'Synthetic')
    root = tmp_path / 'desktop'
    root.mkdir()
    holders = {}

    def factory(url):
        adventure = desktop.Adventure(root, url)
        attempts = []

        def start():
            attempts.append(desktop_setup.read_settings(root)['starter'])
            adventure.error = 'Synthetic setup failure. Try again.' if len(attempts) == 1 else None
            adventure.state = 'error' if adventure.error else 'ready'
            adventure.game = None if adventure.error else create_app(emu, emu.store)

        adventure.start = start
        holders.update(adventure=adventure, attempts=attempts)
        return desktop.create_desktop_app(adventure, 'browser-test-token')

    with serve(factory) as url:
        page.goto(url + '/desktop')
        expect(page.locator('#setup')).to_be_visible()
        page.locator('#rom').set_input_files({'name': 'bad.gb', 'mimeType': 'application/octet-stream', 'buffer': b'bad'})
        page.get_by_role('button', name='Start my adventure').click()
        expect(page.get_by_role('alert')).to_contain_text('clean Pokémon')
        page.locator('#starter').select_option('charmander')
        page.locator('#rom').set_input_files({'name': 'test.gb', 'mimeType': 'application/octet-stream', 'buffer': raw})
        page.get_by_role('button', name='Start my adventure').click()
        expect(page.get_by_role('button', name='Try again')).to_be_visible()
        page.get_by_role('button', name='Try again').click()
        page.wait_for_url(url + '/')
        assert (root / 'rom.gb').read_bytes() == raw
        assert holders['attempts'] == ['charmander', 'charmander']
        page.goto(url + '/desktop')
        page.get_by_role('button', name='Save and quit').click()
        expect(page.locator('#message')).to_contain_text('PokeSim has closed')
