"""Gold, Silver and Crystal details on the live and stats pages, at phone width."""
from test_flows import expect


def gen2_state(status):
    def patched():
        state = status()
        game = state['game']
        partner = {**game['party'][0], 'nick': 'SHRIMPDESK', 'name': 'Staryu', 'dex': 120, 'level': 100}
        egg = {**game['party'][0], 'nick': 'EGG', 'name': 'Sneasel', 'dex': 215, 'egg': True,
               'type_names': ['Dark', 'Ice'], 'status_label': 'Egg'}
        return {**state, 'build': {'revision': '95f4a11' + '0' * 33},
                'game': {**game, 'party': [partner, egg], 'map_name': 'Azalea Pokémon Center 1F', 'dex_total': 251},
                'game_clock': {'weekday': 'Tuesday', 'hours': 8, 'minutes': 14, 'time_of_day': 'Morning'},
                'strategy': {**state['strategy'], 'objective': {'key': 'daycare', 'label': 'Visit the Day Care',
                                                                'reason': 'Visit the Day Care'}}}
    return patched


def test_gen2_live_page_at_phone_width(page, game, monkeypatch):
    url, _, emu, _ = game
    monkeypatch.setattr(emu, 'status', gen2_state(emu.status))
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(url + '/')
    expect(page.locator('#objective')).to_have_text('Visit the Day Care')
    expect(page.locator('#game-clock')).to_have_text('Tuesday 08:14 · Morning')
    expect(page.locator('#app-version')).to_have_text('vbrowser-test · 95f4a11')
    party = page.locator('#party')
    expect(party).to_contain_text('SHRIMPDESK')
    expect(party.locator('.egg-plate')).to_have_count(1)
    expect(party).not_to_contain_text('Sneasel')
    assert party.locator('.mon-head .name').evaluate_all(
        'names => names.every(name => name.scrollWidth <= name.clientWidth)')
    heading = page.locator('#live-heading')
    expect(heading).to_have_text('Azalea Pokémon Center 1F')
    assert heading.evaluate('node => node.scrollWidth <= node.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


def test_stats_page_hides_the_marathon_without_one(page, game):
    url, _, _, _ = game
    page.route('**/api/statistics', lambda route: route.fulfill(json={
        'started_at': None, 'updated_at': None, 'current': {}, 'history': [], 'marathon': None,
        'collection_records': {'shiny': {'available': False, 'seen': None, 'acquired': None, 'held': 2}}}))
    page.goto(url + '/stats')
    expect(page.locator('#stats-shiny-held')).to_have_text('2')
    expect(page.locator('#stats-shiny-acquired')).to_have_text('Not tracked')
    expect(page.locator('#marathon-records')).to_be_hidden()
