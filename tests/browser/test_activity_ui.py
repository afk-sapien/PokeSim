"""Separate Stats pages keep large item and species lists usable on phones."""
import re

import pytest
from test_flows import expect

from pokesim.activity_ledger import KEY, increment
from pokesim.catches import CatchTracker, SUPPORTED


@pytest.mark.parametrize('width', [320, 1280])
def test_activity_pages_search_sort_and_navigation(page, game, width):
    url, store, _, _ = game
    store.set(KEY, {'started_at': 1700000000, 'available': True})
    tracker = CatchTracker(store, sorted(SUPPORTED)[0])
    tracker.record('browser-catch', 25)
    with store.db:
        increment(store.db, 'wild', 25, 123)
        increment(store.db, 'trainer', 25, 3)
        increment(store.db, 'defeated', 25, 90)
        increment(store.db, 'traded_in', 25, 12)
        increment(store.db, 'traded_out', 25, 7)
        increment(store.db, 'bought', 4, 500)
        increment(store.db, 'used', 4, 345)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/journal')
    assert page.get_by_role('navigation', name='Journal pages').count() == 0
    main = page.get_by_role('navigation', name='Main navigation')
    main.get_by_role('link', name='Stats', exact=True).click()
    expect(page).to_have_url(url + '/stats')
    expect(main.get_by_role('link', name='Stats')).to_have_attribute('aria-current', 'page')
    page.get_by_role('navigation', name='Stats pages').get_by_role('link', name='Pokémon', exact=True).click()
    expect(page.locator('#ledger-rows tr')).to_have_count(151)
    expect(page.locator('#ledger-coverage')).to_contain_text('Earlier activity is not estimated')
    page.locator('#ledger-sort').select_option('wild')
    expect(page.locator('#ledger-rows tr').first).to_have_attribute('data-id', '25')
    page.locator('#ledger-sort').select_option('traded_in')
    expect(page.locator('#ledger-rows tr').first).to_have_attribute('data-id', '25')
    expect(page.locator('#ledger-head')).to_contain_text('Traded out')
    expect(page.locator('#ledger-rows tr').first.locator('td').nth(5)).to_have_text('12')
    expect(page.locator('#ledger-rows tr').first.locator('td').nth(6)).to_have_text('7')
    # 123 wild Pikachu for its one catch.
    expect(page.locator('#ledger-head')).to_contain_text('Encounters per catch')
    expect(page.locator('#ledger-rows tr').first.locator('td').nth(8)).to_have_text('123')
    page.locator('#ledger-sort').select_option('per_catch')
    expect(page.locator('#ledger-rows tr').last.locator('td').nth(8)).to_have_text('No catches')
    page.locator('#ledger-search').fill('pikachu')
    expect(page.locator('#ledger-rows tr')).to_have_count(1)
    expect(page.locator('#ledger-rows')).to_contain_text('123')
    expect(page.locator('#ledger-rows')).to_contain_text('90')
    page.reload()
    expect(page.locator('#ledger-search')).to_have_value('pikachu')
    expect(page.locator('#ledger-rows tr')).to_have_count(1)
    page.locator('#ledger-search').fill('not a pokemon')
    expect(page.locator('#ledger-rows')).to_contain_text('No matching records')
    page.locator('#ledger-search').fill('')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/pokesim-pokemon-ledger-{width}.png')
    page.get_by_role('navigation', name='Stats pages').get_by_role('link', name='Items', exact=True).click()
    page.locator('#ledger-search').fill('#4')
    expect(page.locator('#ledger-rows tr')).to_have_count(1)
    expect(page.locator('#ledger-rows')).to_contain_text('500')
    expect(page.locator('#ledger-rows')).to_contain_text('345')
    page.locator('#ledger-search').fill('Bicycle')
    expect(page.locator('#ledger-rows')).to_contain_text('Not counted')
    page.locator('#ledger-search').fill('')
    page.locator('#ledger-filter').select_option('recorded')
    page.locator('#ledger-sort').select_option('bought')
    expect(page.locator('#ledger-rows tr').first).to_have_attribute('data-id', '4')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/pokesim-item-ledger-{width}.png')
    main.get_by_role('link', name='Journal', exact=True).click()
    expect(page.locator('#events')).to_be_visible()


def test_unavailable_activity_does_not_imply_zero_and_legacy_stats_redirects(page, game):
    url, _, _, _ = game
    page.goto(url + '/journal/stats')
    expect(page).to_have_url(url + '/stats')
    page.get_by_role('navigation', name='Stats pages').get_by_role('link', name='Items', exact=True).click()
    expect(page.locator('#ledger-coverage')).to_contain_text('Action tracking begins')
    page.locator('#ledger-search').fill('#4')
    first = page.locator('#ledger-rows td').first
    expect(first).to_have_text('Not tracked yet')
    expect(first).to_have_attribute('title', re.compile('Gold, Silver, or Crystal'))


def gen2_ledger(started_at, counting_since):
    def row(id, name, **values):
        return {'id': id, 'name': name, **values}
    count = 0 if started_at else None
    return {'started_at': started_at, 'counting_since': counting_since, 'available': True, 'generation': 2,
            'trade_records': {'npc_since': started_at, 'missing_history': 0},
            'captures_since': None, 'captures_available': bool(started_at), 'champion_shop': None,
            # A Kanto number, so the Red test server has its sprite.
            'pokemon': [row(25, 'Pikachu', wild=3 if started_at else None, trainer=count, defeated=count,
                            caught=count, gift=count, traded_in=count, traded_out=count, held=1)],
            'items': [row(18, 'Potion', bought=count, used=count, bag=2),
                      row(7, 'Bicycle', bought=count, used=None, bag=1)]}


@pytest.mark.parametrize('width', [320, 1280])
def test_gen2_counts_say_since_when_and_why_a_cell_is_blank(page, game, width):
    url, _, _, _ = game
    since = 1_790_000_000
    page.route('**/api/statistics/activity', lambda route: route.fulfill(json=gen2_ledger(since, since)))
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/stats/pokemon')
    expect(page.locator('#ledger-coverage')).to_contain_text('Counting since')
    expect(page.locator('#ledger-coverage')).to_contain_text('when this adventure was already under way')
    expect(page.locator('#ledger-coverage')).to_contain_text('Trades include verified cable history')
    head = page.locator('#ledger-head th')
    expect(head.nth(1)).to_contain_text('Since')
    expect(head.nth(8)).not_to_contain_text('Since')
    wild = page.locator('#ledger-rows tr').first.locator('td').first
    expect(wild).to_have_text('3')
    expect(wild).to_have_attribute('title', re.compile('Earlier play is not included'))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.goto(url + '/stats/items')
    expect(page.locator('#ledger-help')).to_contain_text('bought at shops and vending machines')
    page.locator('#ledger-search').fill('Bicycle')
    used = page.locator('#ledger-rows tr').first.locator('td').nth(1)
    expect(used).to_have_text('Not counted')
    expect(used).to_have_attribute('title', 'Reusable items are not used up, so uses are not counted.')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/pokesim-gen2-item-ledger-{width}.png')


def test_gen2_adventure_that_has_not_run_since_tracking_began(page, game):
    url, _, _, _ = game
    page.route('**/api/statistics/activity', lambda route: route.fulfill(json=gen2_ledger(None, None)))
    page.goto(url + '/stats/pokemon')
    expect(page.locator('#ledger-coverage')).to_contain_text('Action tracking begins when this adventure next runs')
    expect(page.locator('#ledger-head')).not_to_contain_text('Since')
    expect(page.locator('#ledger-rows tr').first.locator('td').first).to_have_text('Not tracked yet')
