"""Gold, Silver and Crystal details on the live and stats pages, at phone width."""
import os

from test_flows import expect


def gen2_state(status):
    def patched():
        state = status()
        game = state['game']
        partner = {**game['party'][0], 'nick': 'SHRIMPDESK', 'name': 'Staryu', 'dex': 120, 'level': 100}
        egg = {**game['party'][0], 'nick': 'EGG', 'name': 'Egg', 'dex': None, 'egg': True,
               'type_names': [], 'status_label': 'Egg'}
        return {**state, 'build': {'revision': '95f4a11' + '0' * 33},
                'game': {**game, 'party': [partner, egg], 'map_name': 'Azalea Pokémon Center 1F', 'dex_total': 251},
                'clock': {'weekday': 'Tuesday', 'hour': 8, 'minute': 14, 'period': 'Morning'},
                'strategy': {**state['strategy'], 'objective': {'key': 'daycare', 'label': 'Visit the Day Care',
                                                                'reason': 'Visit the Day Care'}}}
    return patched


def test_gen2_live_page_at_phone_width(page, game, monkeypatch):
    url, _, emu, _ = game
    monkeypatch.setattr(emu, 'status', gen2_state(emu.status))
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(url + '/')
    expect(page.locator('#objective')).to_have_text('Visit the Day Care')
    expect(page.locator('#game-clock-day')).to_have_text('Tue')
    expect(page.locator('#game-clock-time')).to_have_text('08:14')
    expect(page.locator('#game-clock-period')).to_have_text('Morning')
    expect(page.locator('#app-version')).to_have_text('vbrowser-test (95f4a11)')
    party = page.locator('#party')
    expect(party).to_contain_text('SHRIMPDESK')
    expect(party.locator('.egg-plate')).to_have_count(1)
    assert party.locator('img[src*="sprites/None"]').count() == 0
    assert party.locator('.mon-head .name').evaluate_all(
        'names => names.every(name => name.scrollWidth <= name.clientWidth)')
    heading = page.locator('#live-heading')
    expect(heading).to_have_text('Azalea Pokémon Center 1F')
    assert heading.evaluate('node => node.scrollWidth <= node.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


def test_game_clock_shares_the_live_heading_row(page, game, monkeypatch):
    url, _, emu, _ = game
    heights = {}
    for width, height in ((1280, 900), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        page.goto(url + '/')
        expect(page.locator('#live-heading')).not_to_be_empty()
        expect(page.locator('#game-clock')).to_be_hidden()
        heights[width] = page.locator('.bezel-head').evaluate('node => node.getBoundingClientRect().height')
    plain = emu.status
    monkeypatch.setattr(emu, 'status', gen2_state(plain))
    for width, height in ((1280, 900), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        page.goto(url + '/')
        clock = page.locator('#game-clock')
        expect(clock).to_be_visible()
        expect(page.locator('#game-clock-day')).to_have_text('Tue')
        expect(page.locator('#game-clock-time')).to_have_text('08:14')
        head = page.locator('.bezel-head')
        assert head.evaluate('node => node.getBoundingClientRect().height') <= heights[width] + 1
        box, heading = clock.bounding_box(), page.locator('#live-heading').bounding_box()
        assert box['y'] < heading['y'] + heading['height'] and heading['y'] < box['y'] + box['height']
        assert page.locator('#live-heading').evaluate('node => node.scrollWidth <= node.clientWidth')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        if os.environ.get('SHOT_DIR'):
            page.screenshot(path=f"{os.environ['SHOT_DIR']}/live-{width}.png")


def test_stats_page_shows_the_marathon_before_any_race(page, game):
    url, _, _, _ = game
    page.route('**/api/statistics', lambda route: route.fulfill(json={
        'started_at': None, 'updated_at': None, 'current': {}, 'history': [], 'marathon': {},
        'collection_records': {'shiny': {'available': False, 'seen': None, 'acquired': None, 'held': 2}}}))
    page.goto(url + '/stats')
    # Arrivals were not counted, so the overview shows the two shinies held rather than "Not tracked".
    expect(page.locator('#stats-shiny-label')).to_have_text('Shinies held')
    expect(page.locator('#stats-shiny-acquired')).to_have_text('2')
    expect(page.locator('#stats-shiny-held-cell')).to_be_hidden()
    expect(page.locator('#marathon-records')).to_be_visible()
    expect(page.locator('#marathon-last')).to_have_text('No attempts yet')
