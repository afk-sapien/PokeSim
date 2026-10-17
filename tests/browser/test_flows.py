"""Exercise browser behavior against the real HTTP routes and persisted preferences."""
import hashlib
import re

import pytest

from pokesim import config, desktop, desktop_setup
from pokesim.web.app import create_app
from conftest import refused, serve


def expect(value):
    from playwright.sync_api import expect as assertion
    return assertion(value)


@pytest.mark.parametrize('width', [1280, 390])
def test_pc_popup_locks_a_pokemon_and_the_lock_persists_even_when_trading_is_offline(page, game, width):
    url, store, emu, _ = game
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(url + '/pc?scope=all')
    bud = page.locator('#pc-grid .pc-mon').filter(has_text='BUD')
    expect(bud.locator('.pc-lock')).to_have_count(0)
    bud.click()
    # The lock lives in the popup. Trade… still links to the game's Trading page.
    link = page.locator('#pc-trade-action').get_by_role('link', name='Trade…')
    expect(link).to_have_attribute('href', re.compile(r'/trading\?tab=trade&mon=.+'))
    # The key's face is the state: an open padlock and Tradeable, or a shut one and Locked. No helper text.
    lock = page.locator('#pc-detail .lock-toggle')
    expect(lock).to_have_text('Tradeable')
    expect(lock).to_have_attribute('data-locked', 'false')
    lock.focus()
    page.keyboard.press('Enter')
    expect(lock).to_have_text('Locked')
    expect(lock).to_have_attribute('data-locked', 'true')
    expect(page.locator('#pc-detail .lock-note')).to_have_count(0)
    assert any(value['state'] == 'locked' for value in store.trade_preferences().values())
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#pc-detail .close-detail').click()
    expect(bud.locator('.pc-lock')).to_have_count(1)
    expect(bud).to_have_attribute('aria-label', re.compile('locked, never traded automatically'))
    page.reload()
    bud.click()
    expect(lock).to_have_text('Locked')
    page.keyboard.press('Escape')
    bud.click()
    lock.click()
    expect(lock).to_have_text('Tradeable')
    expect(page.locator('#pc-detail .lock-note')).to_have_count(0)
    assert all(value['state'] != 'locked' for value in store.trade_preferences().values())


def test_trading_page_is_one_page_and_viewers_cannot_lock(page, game, monkeypatch):
    url, store, emu, _ = game
    # Old Trading addresses, the Auto view among them, open the one page.
    page.goto(url + '/trading?view=block')
    expect(page.locator('#trade-connection-note')).to_contain_text('not connected')
    expect(page.get_by_role('tablist')).to_have_count(0)
    expect(page.locator('#trade-setting, .trade-setting')).to_have_count(0)
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    page.goto(url + '/pc?scope=all')
    page.locator('#pc-grid .pc-mon').filter(has_text='FERN').click()
    lock = page.locator('#pc-detail .lock-toggle')
    expect(lock).to_be_disabled()
    expect(lock).to_have_attribute('title', 'Only the owner can lock Pokémon.')
    assert emu.commands == []


# The game refuses the first rewind on purpose.
@pytest.mark.expected_errors(*refused('/api/control', 409))
def test_rewind_rejection_keeps_event_page_and_retry_navigates(page, game):
    url, store, emu, eid = game
    page.goto(f'{url}/events/{eid}')
    button = page.get_by_role('button', name='Rewind the live game to this moment')
    expect(button).to_be_visible()
    # A hold can begin after the page was rendered. Exercise the server rejection.
    store.set('trade_hold', {'id': '123'})
    dialog = page.get_by_role('dialog', name='Rewind to this moment?')
    # The question comes first, and keeping play sends nothing.
    button.click()
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('Everything it did after that is lost')
    expect(dialog.get_by_role('button', name='Keep playing')).to_be_focused()
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    expect(button).to_be_focused()
    button.click()
    dialog.get_by_role('button', name='Keep playing').click()
    expect(dialog).to_be_hidden()
    assert emu.commands == []
    button.click()
    dialog.get_by_role('button', name='Rewind and lose progress').click()
    expect(page.get_by_role('alert')).to_contain_text('holding this adventure')
    assert page.url == f'{url}/events/{eid}' and emu.commands == []
    store.set('trade_hold', None)
    button.click()
    dialog.get_by_role('button', name='Rewind and lose progress').click()
    page.wait_for_url(url + '/')
    assert emu.commands == [('load_state', f'event-{eid}.state')]


# Desktop setup refuses the file that is not a game.
@pytest.mark.expected_errors(*refused('/desktop/rom?starter=random', 400))
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
        expect(page.get_by_role('alert')).to_contain_text('This file is not a game PokeSim can play')
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
