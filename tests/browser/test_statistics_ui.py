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
    expect(page.locator('#statistics-charts')).to_contain_text('Total collection Stat Power')
    expect(page.locator('#statistics-charts')).to_contain_text('Average DV score')
    expect(page.locator('#statistics-charts')).to_contain_text('Not recorded')
    expect(page.locator('#road')).to_be_visible()
    assert page.locator('#events').count() == 0
    assert page.locator('.progress-chart').count() == 18
    assert page.locator('.progress-chart:visible').count() == 18
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
    power = page.locator('#statistics-charts .progress-row').filter(has_text='Total collection Stat Power')
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


@pytest.mark.parametrize('width', [320, 1280])
def test_marathon_records_and_current_clock(page, game, monkeypatch, width):
    from pokesim.policies.collection import Collection
    from pokesim.policies import marathon
    url, _, emu, _ = game
    collection = Collection()
    collection.marathon_records = {'completed': 2, 'best_frames': 75360,
                                  'last': {'frames': 75360, 'finished': True, 'personal_best': True}}
    collection.project = marathon.candidate()
    collection.project.update(checkpoint=5, race_frames=3660)
    collection.project['gains']['checkpoints'] = 4
    original = emu.status
    monkeypatch.setattr(emu, 'status', lambda: {**original(), 'strategy': {'collection': collection.details()}})
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/journal/stats')
    expect(page.locator('#marathon-best')).to_have_text('20:56')
    expect(page.locator('#marathon-current')).to_have_text('1:01')
    expect(page.locator('#marathon-checkpoints')).to_have_text('4 of 11 checkpoints')
    expect(page.locator('#marathon-last')).to_have_text('20:56')
    expect(page.locator('#marathon-result')).to_have_text('Finished · Personal best')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'/tmp/pokesim-marathon-records-{width}.png', full_page=True)
    collection.marathon_records['last'] = {'frames': 3600, 'finished': False}
    collection.project = None
    page.reload()
    expect(page.locator('#marathon-best')).to_have_text('20:56')
    expect(page.locator('#marathon-current')).to_have_text('Not racing')
    expect(page.locator('#marathon-result')).to_have_text('Did not finish')
    collection.marathon_records = {}
    collection.project = marathon.candidate()
    page.reload()
    expect(page.locator('#marathon-best')).to_have_text('No finish yet')
    expect(page.locator('#marathon-current')).to_have_text('Heading to start')
    expect(page.locator('#marathon-last')).to_have_text('No attempts yet')


@pytest.mark.parametrize('width', [320, 780, 1280])
def test_step_activity_and_mew_progress(page, game, width):
    url, _, _, _ = game
    page.set_viewport_size({'width': width, 'height': 1000})
    data = {'history': [], 'event_returns': {'enabled': True, 'interval': 100000, 'activities': [
        {'key': 'eevee', 'ready': False, 'remaining': 25000},
        {'key': 'dojo', 'ready': True, 'remaining': 0},
        {'key': 'fossil', 'ready': False, 'remaining': 0},
        {'key': 'trade_4', 'ready': True, 'remaining': 0},
        {'key': 'trade_5', 'ready': True, 'remaining': 0},
        {'key': 'trade_6', 'ready': True, 'remaining': 0}]},
        'mew_returns': {'enabled': True, 'interval': 1000000, 'league_required': False, 'remaining': 265775}}
    page.route('**/api/statistics', lambda route: route.fulfill(json=data))
    page.goto(url + '/journal/stats')
    expect(page.locator('[data-return="dojo"]')).to_contain_text('Ready to revisit')
    expect(page.locator('[data-return="fossil"]')).to_contain_text('Pending')
    expect(page.locator('[data-return="fossil"]')).not_to_contain_text('Ready to revisit')
    expect(page.locator('[data-return="eevee"] progress')).to_have_attribute('value', '75000')
    expect(page.locator('[data-return="mew"] progress')).to_have_attribute('value', '734225')
    expect(page.locator('#event-return-summary')).to_have_text('4 ready to revisit')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#event-returns').screenshot(path=f'/tmp/pokesim-return-cards-{width}.png')
    page.get_by_role('button', name='Dark', exact=True).click()
    page.locator('#event-returns').screenshot(path=f'/tmp/pokesim-return-cards-{width}-dark.png')
    data['mew_returns'].update(league_required=True, remaining=0)
    page.reload()
    expect(page.locator('[data-return="mew"]')).to_contain_text('Win the League')
    expect(page.locator('[data-return="mew"] progress')).to_have_attribute('value', '1000000')
    data['mew_returns'].update(first_gift=True, league_required=False)
    page.reload()
    expect(page.locator('[data-return="mew"]')).to_contain_text('Become Champion')
    assert page.locator('[data-return="mew"] progress').count() == 0
    data['event_returns'].update(activities=[])
    data['mew_returns'].update(enabled=False)
    page.reload()
    expect(page.locator('#event-return-list')).to_contain_text('Complete original events')
    data['event_returns'].update(enabled=False)
    page.reload()
    expect(page.locator('#event-returns')).not_to_be_visible()


@pytest.mark.parametrize('width', [320, 1280])
def test_pokedex_coverage_and_journal_individual_counts(page, game, width):
    from pokesim import catches, shiny
    from pokesim.milestones import MilestoneTracker
    from pokesim.strategy_data import SPECIES
    url, store, emu, _ = game
    sid = lambda dex: next(key for key, mon in SPECIES.items() if mon['dex'] == dex)
    base = emu.snapshot.party[0]
    emu.snapshot = replace(emu.snapshot, party=(
        replace(base, species=sid(3), dvs=(15,) * 5),
        replace(base, species=sid(134), dvs=(0, 10, 10, 10, 10))))
    tracker = MilestoneTracker(store)
    tracker.observe(emu.snapshot)
    tracker.observe(emu.snapshot)
    store.set(catches.KEY, {'total': 42, 'counts': {'3': 42}, 'available': True,
                            'complete_history': False, 'started_at': time.time()})
    store.set(shiny.KEY, {**shiny.empty(), 'seen': 7, 'acquired': 4, 'available': True,
                          'acquired_species': [134], 'seen_species': [150]})
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/pokedex')
    expect(page.locator('#sum-perfect')).to_have_text('3/151')
    expect(page.locator('#sum-shiny')).to_have_text('2/151')
    assert page.locator('.bank .readout').count() == 5
    assert all(text.endswith('/151') for text in page.locator('.bank .readout').all_text_contents())
    assert page.locator('#sum-caught, .shiny-collection').count() == 0
    page.locator('#status-filter').select_option('perfect')
    expect(page.locator('.dex-card')).to_have_count(3)
    page.locator('#status-filter').select_option('shiny')
    expect(page.locator('.dex-card')).to_have_count(2)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/pokesim-collection-dex-{width}.png', full_page=True)
    page.goto(url + '/journal/stats')
    expect(page.locator('#stats-caught')).to_have_text('42')
    expect(page.locator('#stats-perfect')).to_have_text('1+')
    expect(page.locator('#stats-shiny-seen')).to_have_text('7')
    expect(page.locator('#stats-shiny-acquired')).to_have_text('4')
    expect(page.locator('#stats-shiny-held')).to_have_text('1')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/pokesim-collection-stats-{width}.png', full_page=True)


@pytest.mark.parametrize('width', [320, 1280])
def test_stats_overview_milestones_and_recent_selector(page, game, monkeypatch, width):
    from pokesim.adventure_records import RecordTracker
    from pokesim.legendary_returns import STEPS
    url, store, emu, _ = game
    tracker = RecordTracker(store)
    for _ in range(2):
        tracker.observe(emu.snapshot)
    emu.snapshot = replace(emu.snapshot, badges=1)
    for _ in range(2):
        tracker.observe(emu.snapshot, {'seconds': 7380})
    store.set(STEPS, {'available': True, 'total': 123456, 'started_at': time.time()})
    original = emu.status
    monkeypatch.setattr(emu, 'status', lambda: {**original(), 'play_clock': {'seconds': 999000, 'lower_bound': True},
                                               'league_rewards': {'wins': 123}})
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/journal/stats')
    expect(page.locator('#stats-playtime')).to_have_text('277h 30m+')
    expect(page.locator('#stats-league')).to_have_text('123')
    expect(page.locator('[data-milestone="first_badge"]')).to_contain_text('2h 3m')
    expect(page.locator('[data-milestone="champion"]')).to_contain_text('Not reached')
    expect(page.locator('#stats-highlights a')).to_have_count(2)
    assert page.locator('#stats-highlights a').first.get_attribute('href').startswith('/pc?scope=all')
    page.locator('#recent-period').select_option('week')
    expect(page.locator('#recent-note')).to_contain_text('Partial history')
    assert page.locator('details').count() == 0
    expect(page.locator('#collection-details .readout').first).to_be_visible()
    expect(page.locator('#activity-list')).to_be_visible()
    expect(page.locator('#activity-list')).to_contain_text('123,456')
    page.evaluate('scrollTo(0, 0)')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/pokesim-stats-overview-{width}.png', full_page=True)
