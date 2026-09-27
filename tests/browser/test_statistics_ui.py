"""Journal subpages show durable stats at phone and desktop sizes."""
from dataclasses import replace
import time

import pytest
from test_flows import expect

from pokesim.statistics import StatisticsTracker


@pytest.mark.parametrize('width,theme', [(1280, 'light'), (320, 'dark')])
def test_journal_entries_and_stats(page, game, width, theme):
    url, store, emu, _ = game
    tracker = StatisticsTracker(store)
    now = time.time()
    tracker.observe(emu.snapshot, now=now - 3600)
    tracker.observe(replace(emu.snapshot, frame=930, x=6), now=now - 3599)
    tracker.value['counters']['steps'] = 10_000_000_000
    tracker.flush(now=now)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/journal')
    page.get_by_role('button', name=theme.title(), exact=True).click()
    expect(page.locator('#events')).to_be_visible()
    assert page.locator('#road').count() == 0
    page.get_by_role('navigation', name='Journal pages').get_by_role('link', name='Stats').click()
    expect(page.get_by_role('heading', name='Adventure stats')).to_be_visible()
    expect(page.locator('#statistics-charts')).to_contain_text('10,000,000,000')
    expect(page.locator('#statistics-charts')).to_contain_text('Total collection power')
    expect(page.locator('#statistics-charts')).to_contain_text('Average DV score')
    expect(page.locator('#statistics-charts')).to_contain_text('Not recorded')
    expect(page.locator('#road')).to_be_visible()
    assert page.locator('#events').count() == 0
    assert page.locator('.progress-chart').count() == 18
    assert page.locator('#statistics-charts .progress-label').evaluate_all(
        'labels => labels.every(label => label.scrollWidth <= label.clientWidth)')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'/tmp/pokesim-journal-stats-{width}.png', full_page=True)
    page.get_by_role('navigation', name='Journal pages').get_by_role('link', name='Entries').click()
    expect(page.locator('#events')).to_contain_text('Caught a partner')


def test_unavailable_current_value_is_not_replaced_by_historical_value(page, game):
    url, _, _, _ = game
    now = time.time()
    page.route('**/api/statistics', lambda route: route.fulfill(json={
        'started_at': now - 3600, 'updated_at': now,
        'current': {'collection_power': None, 'average_dv': 69},
        'history': [{'ts': now - 3600, 'collection_power': 12345, 'average_dv': 68},
                    {'ts': now, 'collection_power': None, 'average_dv': 69}],
    }))
    page.goto(url + '/journal/stats')
    power = page.locator('#statistics-charts .progress-row').filter(has_text='Total collection power')
    expect(power.locator('.readout')).to_have_text('Not recorded')
    dv = page.locator('#statistics-charts .progress-row').filter(has_text='Average DV score')
    expect(dv).to_contain_text('+1 pp since first record')
    expect(dv.locator('.trend-scale')).to_have_text('67 to 70%')
    expect(page.locator('#statistics-window')).not_to_be_empty()


@pytest.mark.parametrize('width', [320, 1280])
def test_legendary_return_progress_is_readable_and_lists_available_hunts(page, game, width):
    from pokesim.legendary_returns import KEY, STEPS
    url, store, _, _ = game
    store.set(STEPS, {'available': True, 'total': 1250000, 'started_at': time.time()})
    store.set(KEY, {'cycle': 1, 'interval': 1000000, 'next_at': 2000000,
                   'tickets': {'150': {'state': 'available', 'cycle': 1}}})
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/journal/stats')
    expect(page.locator('#legendary-returns')).to_be_visible()
    expect(page.locator('#legendary-summary')).to_have_text('750,000 steps until the next return')
    expect(page.locator('#legendary-ready')).to_have_text('Ready to revisit: Mewtwo.')
    expect(page.locator('#legendary-meter')).to_have_attribute('value', '250000')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'/tmp/pokesim-legendary-returns-{width}.png', full_page=True)
