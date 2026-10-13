"""A party member on the Live page opens the PC page's detail popup, lock included."""
from dataclasses import replace
import re

import pytest

from pokesim import config
from test_flows import expect
from test_pc_detail import check_fits, gen2_payload


@pytest.mark.parametrize('width,height', [(1280, 900), (390, 844)])
def test_live_party_member_opens_the_pc_popup_and_locks_it(page, game, width, height):
    url, store, emu, _ = game
    # Tackle and Growl, with Tackle spent.
    emu.snapshot = replace(emu.snapshot, party=(replace(emu.snapshot.party[0], moves=(33, 45), pp=(0, 40), max_pp=(35, 40)),))
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url)
    partner = page.get_by_role('button', name='View LEAF details')
    partner.click()
    dialog = page.get_by_role('dialog', name='LEAF')
    expect(dialog).to_be_visible()
    # The same popup as the PC: moves, the stats table with DVs and stat experience, the footer keys.
    expect(dialog.locator('.pc-detail-head')).to_contain_text('Party, slot 1')
    expect(dialog.locator('.pc-move')).to_have_count(2)
    expect(dialog.locator('.pc-move').first).to_contain_text('Tackle')
    expect(dialog.locator('.individual-stats tbody tr')).to_have_count(5)
    expect(dialog.locator('.individual-stats tfoot')).to_contain_text('40')
    expect(dialog.locator('.pc-trade-action').get_by_role('link', name='Trade…')).to_have_attribute(
        'href', re.compile(r'/trading\?tab=trade&mon=.+'))
    check_fits(page, '#mon-detail', '#mon-detail-action')
    lock = dialog.get_by_role('button', name='Locked: never traded')
    expect(lock).to_have_attribute('aria-pressed', 'false')
    lock.click()
    expect(lock).to_have_attribute('aria-pressed', 'true')
    expect(dialog.locator('.lock-note')).to_have_text('Locked. It is never traded automatically.')
    assert any(value['state'] == 'locked' for value in store.trade_preferences().values())
    # Game keys stay with the popup while it is open, and Escape hands focus back to the bay.
    page.keyboard.press('z')
    assert emu.commands == []
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    expect(partner).to_be_focused()
    # The lock shows again on the next visit.
    partner.click()
    expect(lock).to_have_attribute('aria-pressed', 'true')
    page.locator('#mon-close').click()
    expect(dialog).to_be_hidden()


def test_view_only_live_popup_shows_the_lock_state_without_the_toggle(page, game, monkeypatch):
    url, store, emu, _ = game
    page.goto(url)
    page.get_by_role('button', name='View LEAF details').click()
    page.locator('#mon-detail').get_by_role('button', name='Locked: never traded').click()
    expect(page.locator('#mon-detail .lock-toggle')).to_have_attribute('aria-pressed', 'true')
    page.keyboard.press('Escape')
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    page.reload()
    page.get_by_role('button', name='View LEAF details').click()
    dialog = page.locator('#mon-detail')
    expect(dialog.locator('.individual-stats')).to_be_visible()
    expect(dialog.locator('.pc-detail-tags .trade-tag--keep')).to_have_text('Locked')
    expect(dialog.locator('.lock-toggle')).to_have_count(0)


@pytest.mark.parametrize('width,height', [(1280, 900), (390, 844)])
def test_gen2_party_member_shows_hidden_power_and_held_item(page, game, width, height):
    url, *_ = game
    live = page.request.get(url + '/api/state').json()['game']['party'][0]
    payload = gen2_payload()
    payload['party'][0].update(species=live['species'], nick=live['nick'])
    page.route(re.compile(r'/api/pokedex/status\?view=party$'), lambda route: route.fulfill(json=payload))
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url)
    page.get_by_role('button', name='View LEAF details').click()
    dialog = page.locator('#mon-detail')
    expect(dialog.locator('.pc-detail-line')).to_contain_text('Holding Leftovers')
    expect(dialog.locator('.pc-move').filter(has_text='Hidden Power')).to_contain_text('Fire')
    expect(dialog.locator('.individual-stats tbody tr')).to_have_count(6)
    expect(dialog.locator('.lock-toggle')).to_be_enabled()
    check_fits(page, '#mon-detail', '#mon-detail-action')


def test_popup_closes_when_the_partner_leaves_the_slot(page, game):
    url, store, emu, _ = game
    page.goto(url)
    page.get_by_role('button', name='View LEAF details').click()
    expect(page.locator('#mon-detail')).to_be_visible()
    emu.snapshot = replace(emu.snapshot, party=(replace(emu.snapshot.party[0], nick='SPROUT'),))
    expect(page.locator('#mon-detail')).to_be_hidden()
