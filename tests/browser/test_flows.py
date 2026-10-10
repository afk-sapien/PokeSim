"""Exercise browser behavior against the real HTTP routes and persisted preferences."""
import hashlib
import re

import pytest

from pokesim import config, desktop, desktop_setup
from pokesim.web.app import create_app
from conftest import serve


def expect(value):
    from playwright.sync_api import expect as assertion
    return assertion(value)


@pytest.mark.parametrize('width', [1280, 390])
def test_pc_links_to_trading_where_the_setting_persists_even_when_trading_is_offline(page, game, width):
    url, store, emu, _ = game
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(url + '/pc?scope=all')
    # The PC only links to trading. Everything about trading lives on the Trading page.
    page.locator('#pc-grid .pc-mon').filter(has_text='BUD').click()
    link = page.locator('#pc-trade-action').get_by_role('link', name='Trade…')
    expect(link).to_have_attribute('href', re.compile(r'/trading\?tab=trade&mon=.+'))
    expect(page.locator('#pc-trade-action button')).to_have_count(0)
    link.click()
    setting = page.get_by_label('Trade setting for BUD')
    expect(setting).to_be_enabled()
    setting.select_option('keep')
    expect(page.locator('#toast')).to_contain_text('never trades it')
    assert any(value['state'] == 'locked' for value in store.trade_preferences().values())
    page.reload()
    expect(setting).to_have_value('keep')
    setting.select_option('auto')
    expect(setting).to_have_value('auto')
    expect(page.locator('#toast')).to_contain_text('Auto decides')
    assert all(value['state'] != 'locked' for value in store.trade_preferences().values())
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_trading_availability_and_viewer_mode_reach_real_controls(page, game, monkeypatch):
    url, store, emu, _ = game
    page.goto(url + '/trading?view=block')
    expect(page.locator('#trade-connection-note')).to_contain_text('not connected')
    # The old Trading block address opens the Auto tab.
    expect(page.get_by_role('tab', name='Auto')).to_have_attribute('aria-selected', 'true')
    emu.connected = True
    page.reload()
    setting = page.get_by_label('Trade setting for FERN')
    setting.select_option('first')
    expect(page.locator('#toast')).to_contain_text('Trade first')
    assert any(value['state'] == 'offered' for value in store.trade_preferences().values())
    page.get_by_role('tab', name='Auto').press('ArrowRight')
    expect(page.get_by_role('tab', name='Opportunities')).to_be_focused()
    expect(page.get_by_role('tab', name='Opportunities')).to_have_attribute('aria-selected', 'true')
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    page.goto(url + '/trading')
    expect(page.get_by_label('Trade setting for FERN')).to_be_disabled()
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
