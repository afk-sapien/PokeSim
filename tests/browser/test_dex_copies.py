"""Each Pokémon listed under "With you right now" opens the PC's own popup, and that popup links to its PC slot."""
import os
import re

import pytest

from test_flows import expect
from test_pc_detail import check_fits, gen2_payload

SHOTS = os.environ.get('POKESIM_DEX_COPIES_SHOTS')
SIZES = [(1280, 900), (390, 844)]


def open_entry(page, url, dex):
    page.goto(f'{url}/pokedex#{dex:03d}')
    expect(page.locator('#detail')).to_be_visible()
    rows = page.locator('#detail-body .copy-open')
    expect(rows.first).to_be_visible()
    return rows


def shoot(page, name):
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, name))


@pytest.mark.parametrize('width,height', SIZES)
def test_copy_opens_the_pc_popup_and_closes_back_to_the_entry(page, game, width, height):
    url, _, _, _ = game
    page.set_viewport_size({'width': width, 'height': height})
    rows = open_entry(page, url, 1)
    expect(rows).to_have_count(3)
    fern = rows.nth(2)
    expect(fern).to_have_attribute('aria-label', 'Open FERN, level 20, Box 1, 1-star DVs')
    fern.scroll_into_view_if_needed()
    scrolled = page.locator('#detail').evaluate('node => node.scrollTop')
    fern.click()
    popup = page.locator('#mon-detail')
    expect(popup).to_be_visible()
    expect(popup.locator('#pc-detail-name')).to_have_text('FERN')
    expect(popup.locator('.pc-detail-line')).to_contain_text('Level 20')
    expect(popup.locator('.pc-detail-id .micro')).to_contain_text('Box 1, slot 2')
    # The full record, drawn by the shared popup: moves and individual stats.
    expect(popup.locator('.pc-move')).to_have_count(2)
    expect(popup.locator('.individual-stats')).to_be_visible()
    # The popup is already on the Pokédex, so it offers no Pokédex key, only the PC.
    expect(popup.locator('.pc-trade-action a[href*="/pokedex"]')).to_have_count(0)
    show = popup.locator('.pc-show-link')
    expect(show).to_have_attribute('href', re.compile(r'/pc\?box=1&slot=2$'))
    check_fits(page, '#mon-detail', '#mon-detail-action')
    box = popup.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width
    shoot(page, f'after-{width}.png')

    page.keyboard.press('Escape')
    expect(popup).to_be_hidden()
    expect(page.locator('#detail')).to_be_visible()
    expect(page.locator('#detail-name')).to_have_text('Bulbasaur')
    expect(fern).to_be_focused()
    assert page.locator('#detail').evaluate('node => node.scrollTop') == scrolled

    # The Close key closes it too, and Show in PC lands on that box with the card marked and open.
    fern.click()
    popup.locator('#mon-close').click()
    expect(popup).to_be_hidden()
    expect(fern).to_be_focused()
    fern.click()
    show.click()
    expect(page).to_have_url(re.compile(r'/pc\?box=1'))
    expect(page.locator('#pc-heading')).to_have_text('Box 1')
    expect(page.locator('.pc-mon.is-target')).to_contain_text('FERN')
    expect(page.locator('#pc-detail')).to_be_visible()
    expect(page.locator('#pc-detail-name')).to_have_text('FERN')
    page.keyboard.press('Escape')
    expect(page.locator('.pc-mon.is-target')).to_be_focused()


def test_keyboard_enter_opens_a_party_copy_and_its_link_opens_the_party(page, game):
    url, _, _, _ = game
    page.set_viewport_size({'width': 1280, 'height': 900})
    rows = open_entry(page, url, 1)
    rows.first.focus()
    page.keyboard.press('Enter')
    popup = page.locator('#mon-detail')
    expect(popup.locator('#pc-detail-name')).to_have_text('LEAF')
    expect(popup.locator('.pc-detail-id .micro')).to_contain_text('Party, slot 1')
    expect(popup.locator('.pc-show-link')).to_have_attribute('href', re.compile(r'/pc\?box=party&slot=1$'))
    # Arrow keys belong to the popup now and do not step the Pokédex entry behind it.
    page.keyboard.press('ArrowRight')
    expect(page.locator('#detail-name')).to_have_text('Bulbasaur')
    popup.locator('.pc-show-link').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#pc-heading')).to_have_text('Party')
    expect(page.locator('#pc-detail-name')).to_have_text('LEAF')


def gen2_holders():
    payload = gen2_payload()
    stored = dict(payload['party'][0], nick='TIDEPOOL', level=33, box=3, position=7, trade_key='g2-2')
    stored.pop('slot')
    payload['storage'] = {'active_box': 3, 'box_counts': [0, 0, 1] + [0] * 11, 'pokemon': [stored]}
    return payload


@pytest.mark.parametrize('width,height', SIZES)
def test_gen2_copies_open_their_own_records(page, game, width, height):
    url, _, _, _ = game
    page.route(re.compile(r'/api/pokedex/status(\?|$)'), lambda route: route.fulfill(json=gen2_holders()))
    page.set_viewport_size({'width': width, 'height': height})
    rows = open_entry(page, url, 121)
    expect(rows).to_have_count(2)
    rows.nth(1).click()
    popup = page.locator('#mon-detail')
    expect(popup.locator('#pc-detail-name')).to_have_text('TIDEPOOL')
    expect(popup.locator('.pc-detail-line')).to_contain_text('Level 33')
    expect(popup.locator('.pc-detail-line')).to_contain_text('Holding Leftovers')
    expect(popup.locator('.pc-detail-id .micro')).to_contain_text('Box 3, slot 7')
    expect(popup.locator('.individual-stats tbody tr')).to_have_count(6)
    expect(popup.locator('.pc-show-link')).to_have_attribute('href', re.compile(r'/pc\?box=3&slot=7$'))
    check_fits(page, '#mon-detail', '#mon-detail-action')
    popup.locator('.pc-show-link').click()
    expect(page.locator('#pc-heading')).to_have_text('Box 3')
    expect(page.locator('#pc-detail-name')).to_have_text('TIDEPOOL')


def test_a_copy_that_moved_says_so_and_still_links_to_the_pc(page, game):
    url, _, _, _ = game
    holders = gen2_holders()
    moved = gen2_holders()
    moved['storage']['pokemon'][0]['position'] = 8

    def answer(route):
        route.fulfill(json=moved if 'view=pc' in route.request.url else holders)

    page.route(re.compile(r'/api/pokedex/status(\?|$)'), answer)
    page.set_viewport_size({'width': 390, 'height': 844})
    rows = open_entry(page, url, 121)
    rows.nth(1).click()
    popup = page.locator('#mon-detail')
    expect(popup.locator('.pc-detail-line')).to_contain_text('It has moved')
    expect(popup.locator('#pc-detail-name')).to_have_text('TIDEPOOL')
    expect(popup.locator('.pc-show-link')).to_be_visible()


@pytest.mark.parametrize('width,height', SIZES)
def test_gen2_pokedex_marks_shiny_species_from_the_receipts(page, game, tmp_path, width, height):
    from pokesim import shiny
    from pokesim.gen2.tracking import apply
    from pokesim.store import Store
    store = Store(tmp_path / 'gen2')
    with store.db:
        shiny.start(store.db, 2, available=True, fresh=True)
        shiny.record(store.db, 'acquired', 'hatch', 121, generation=2)
        shiny.record(store.db, 'seen', 'wild', 118, generation=2)
    # The Gen II Pokédex status as the server builds it.
    payload = apply(gen2_payload(), store)
    store.close()
    url, _, _, _ = game
    page.route(re.compile(r'/api/pokedex/status(\?|$)'), lambda route: route.fulfill(json=payload))
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(f'{url}/pokedex')
    starmie, goldeen, staryu = (page.locator(f'.dex-card[data-dex="{dex}"]') for dex in (121, 118, 120))
    expect(starmie.locator('.shiny-badge')).to_have_text('★ Shiny')
    expect(starmie).to_have_attribute('aria-label', re.compile(', shiny species found,'))
    expect(goldeen.locator('.shiny-badge')).to_have_text('★ Shiny seen')
    expect(goldeen).to_have_attribute('aria-label', re.compile(', shiny seen,'))
    expect(staryu.locator('.shiny-badge')).to_have_count(0)
    expect(page.locator('#sum-shiny')).to_have_text('1/151')
    goldeen.click()
    expect(page.locator('#detail-body .detail-head .shiny-badge')).to_have_text('★ Shiny seen')
    page.keyboard.press('Escape')
    page.locator('#status-filter').select_option('shiny')
    expect(page.locator('.dex-card')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    shoot(page, f'shiny-{width}.png')
