"""The Trading page tabs: pick a trade, answer offers, set automatic trading and read history."""
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import pytest

from pokesim.web.pages import render_game_page
from test_flows import expect

FROM = 'a' * 32
RED = 'b' * 32
BLUE = 'c' * 32
REASON = 'Busy Blue is busy finishing another trade'
# The reason Busy Blue gives for the shiny Meganium, which is not a Gen I species.
MEGANIUM = 'Meganium cannot go to a Red, Blue or Yellow game. Meganium did not exist in Gen I'
CABLE = 'Time Capsule sessions between Gen I and Gen II are not yet supported.'
CRYSTAL = 'd' * 32
JSON = 'application/json'


def shoot(page, name):
    """Screenshots for review, only when POKESIM_SHOTS names a folder."""
    folder = os.environ.get('POKESIM_SHOTS')
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        # A sticky rail repeats down a full-page capture. Pin it to the top for the picture.
        page.add_style_tag(content='.rail { position: static }')
        page.screenshot(path=str(Path(folder) / f'{name}.png'), full_page=True)


class Library:
    """The library API the managed Trading page talks to, with the real game worker behind it."""

    def __init__(self, page, url, *, starts_now=True, mine_key='box-1', viewer_only=False):
        self.page, self.url = page, url
        self.viewer_only = viewer_only
        self.starts_now = starts_now
        self.mine_key = mine_key
        self.posted = []
        self.saved = []
        self.offers = []
        self.held = {}
        self.auto = {'adventure_id': FROM, 'enabled': True, 'wishlist': [], 'wishes': [], 'viewer_only': False,
                     'species': [{'dex': 1, 'name': 'Bulbasaur'}, {'dex': 16, 'name': 'Pidgey'}, {'dex': 25, 'name': 'Pikachu'}]}
        trading = render_game_page('adventure-trading.html', base_path=f'/games/{FROM}', adventure_id=FROM,
                                   adventure_name='Crystal')
        pc = render_game_page('pc.html', base_path=f'/games/{FROM}', adventure_id=FROM, adventure_name='Crystal')
        page.route(f'**/games/{FROM}/**', lambda route: route.continue_(url=route.request.url.replace(f'/games/{FROM}/', '/')))
        page.route(re.compile(rf'/games/{FROM}/trading(\?|$)'), lambda route: route.fulfill(body=trading, content_type='text/html'))
        page.route(re.compile(rf'/games/{FROM}/pc(\?|$)'), lambda route: route.fulfill(body=pc, content_type='text/html'))
        page.route(re.compile(rf'/games/{FROM}/api/interactions(\?|$)'), self.interactions)
        page.route(re.compile(r'/api/v1/session(\?|$)'), lambda route: self.json(route, {'csrf_token': 'test'}))
        page.route(re.compile(r'/api/v1/adventures(\?|$)'), lambda route: self.json(route, {'adventures': [
            {'id': FROM, 'name': 'Crystal', 'version': 'crystal', 'archived': False}]}))
        page.route(re.compile(r'/api/v1/interactions/trade-offers(\?|$)'), self.trade_offers)
        page.route(re.compile(r'/api/v1/interactions/trade-offers/pokemon(\?|$)'), self.pokemon)
        page.route(re.compile(r'/api/v1/interactions/trade-offers/targets(\?|$)'), self.targets)
        page.route(re.compile(r'/api/v1/interactions/trade-offers/limits(\?|$)'), self.limits)
        page.route(re.compile(r'/api/v1/interactions/auto-settings(\?|$)'), self.auto_settings)
        page.route(re.compile(rf'/games/{FROM}/api/cable(\?|$)'), lambda route: self.json(route, {
            'adventure': {'id': FROM, 'name': 'Crystal', 'version': 'crystal', 'state': 'running'}, 'reason': '', 'session': None}))
        page.route(re.compile(r'/api/v1/interactions/cable-sessions/partners(\?|$)'), lambda route: self.json(route, {
            'adventure_id': FROM, 'partners': [
                {'id': CRYSTAL, 'name': 'Second Crystal', 'version': 'crystal', 'reason': ''},
                {'id': RED, 'name': 'Second Red', 'version': 'red', 'reason': CABLE}]}))

    @staticmethod
    def json(route, data, status=200):
        route.fulfill(status=status, body=json.dumps(data), content_type=JSON)

    def open(self, query=''):
        self.page.goto(f'{self.url}/games/{FROM}/trading{query}')

    def interactions(self, route):
        self.json(route, {'adventure': {'id': FROM, 'version': 'crystal', 'state': 'running', 'archived': False},
                          'active': [], 'auto_enabled': self.auto['enabled'], 'recent_failures': [
                              {'phase': 'aborted', 'decision': 'ABORT', 'peer_name': 'Busy Blue', 'updated_at': 2000,
                               'failure_reason': 'Busy Blue could not reach the Cable Club.'}],
                          'history': [{'phase': 'completed', 'decision': 'COMMIT', 'peer_name': 'Second Red',
                                       'peer_id': RED, 'updated_at': 1000,
                                       'sent': {'name': 'Abra', 'dex': 63, 'level': 12},
                                       'received': {'name': 'Kadabra', 'dex': 64, 'level': 12}}]})

    def side(self, aid, name, mon):
        return {'adventure_id': aid, 'adventure_name': name, 'sprite_url': None, **mon}

    def trade_offers(self, route):
        if route.request.method == 'POST':
            body = json.loads(route.request.post_data)
            self.posted.append(body)
            offer = {'id': 'd' * 32, 'status': 'accepted' if self.starts_now else 'pending', 'reason': None,
                     'from': self.side(FROM, 'Crystal', {'name': 'Bulbasaur', 'level': 5}),
                     'to': self.side(RED, 'Second Red', {'name': 'Pidgey', 'level': 9}), 'updated_at': 3000}
            self.offers.append(offer)
            return self.json(route, offer)
        self.json(route, {'adventure_id': FROM, 'incoming': [], 'outgoing': self.offers, 'viewer_only': False})

    def pokemon(self, route):
        rows = [{'key': self.mine_key, 'name': 'Bulbasaur', 'nickname': 'BUD', 'dex': 1, 'level': 5, 'box': 1, 'blocked': ''},
                {'key': 'party-0', 'name': 'Meganium', 'dex': 154, 'level': 30, 'location': 'party', 'shiny': True, 'blocked': ''},
                {'key': 'egg', 'name': 'Egg', 'location': 'party', 'blocked': 'Eggs cannot be traded'}]
        self.json(route, {'adventure_id': FROM, 'reason': '', 'pokemon': [self.side(FROM, 'Crystal', row) for row in rows],
                          'viewer_only': self.viewer_only})

    def targets(self, route):
        key = parse_qs(urlparse(route.request.url).query)['from_key'][0]
        reason = MEGANIUM if key == 'party-0' else REASON
        body = {'adventures': [
            {'id': RED, 'name': 'Second Red', 'version': 'red', 'generation': 1, 'available': key != 'party-0',
             'reason': MEGANIUM if key == 'party-0' else ''},
            {'id': BLUE, 'name': 'Busy Blue', 'version': 'blue', 'generation': 1, 'available': False, 'reason': reason}],
            'from_key': key, 'viewer_only': False}
        if key in self.held:
            # Held back so a test can answer it late, after another Pokémon was picked.
            self.held[key] = (route, body)
            return
        self.json(route, body)

    def limits(self, route):
        self.json(route, {'pokemon': [self.side(RED, 'Second Red', {'key': '1', 'name': 'Pidgey', 'dex': 16, 'level': 9, 'blocked': ''}),
                                      self.side(RED, 'Second Red', {'key': '2', 'name': 'Mew', 'dex': 151, 'level': 5,
                                                                    'blocked': 'Mew stays in this game'})],
                          'to': {'adventure_id': RED, 'adventure_name': 'Second Red', 'viewer_only': not self.starts_now},
                          'starts_now': self.starts_now, 'viewer_only': False, 'blocked': {}})

    def auto_settings(self, route):
        if route.request.method == 'PUT':
            change = json.loads(route.request.post_data)
            self.saved.append(change)
            self.auto.update(change)
            names = {row['dex']: row['name'] for row in self.auto['species']}
            self.auto['wishes'] = [{'dex': dex, 'name': names[dex]} for dex in self.auto['wishlist']]
        self.json(route, self.auto)


def selected(page, name):
    expect(page.get_by_role('tab', name=name)).to_have_attribute('aria-selected', 'true')


@pytest.mark.parametrize('width', [1280, 390])
def test_tabs_move_with_the_keyboard_and_remember_the_last_one(page, game, width):
    url = game[0]
    library = Library(page, url)
    page.set_viewport_size({'width': width, 'height': 844})
    library.open()
    selected(page, 'Trade')
    expect(page.locator('#panel-trade')).to_be_visible()
    expect(page.locator('#tab-cable')).to_be_enabled()
    tab = page.get_by_role('tab', name='Trade')
    tab.focus()
    tab.press('ArrowRight')
    selected(page, 'Offers')
    expect(page.get_by_role('tab', name=re.compile('Offers'))).to_be_focused()
    expect(page.locator('#panel-offers')).to_be_visible()
    expect(page.locator('#panel-trade')).to_be_hidden()
    page.keyboard.press('End')
    selected(page, 'Cable Club')
    page.keyboard.press('ArrowLeft')
    selected(page, 'History')
    expect(page.locator('#trade-history')).to_contain_text('Busy Blue could not reach the Cable Club')
    # History lists failed attempts and completed trades together, newest first.
    text = page.locator('#trade-history').inner_text()
    assert text.index('Busy Blue') < text.index('Second Red')
    page.keyboard.press('ArrowRight')
    selected(page, 'Cable Club')
    page.keyboard.press('ArrowRight')
    selected(page, 'Trade')
    page.keyboard.press('ArrowLeft')
    selected(page, 'Cable Club')
    page.get_by_role('tab', name='Auto').click()
    page.reload()
    selected(page, 'Auto')
    library.open('?tab=history')
    selected(page, 'History')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1280, 390])
def test_trade_tab_greys_out_games_that_cannot_take_it_and_starts_an_owned_trade(page, game, width):
    url = game[0]
    library = Library(page, url)
    page.set_viewport_size({'width': width, 'height': 844})
    library.open()
    mine = page.locator('#pick-mine')
    expect(mine.locator('[data-key="egg"]')).to_be_disabled()
    expect(mine.locator('[data-key="egg"]')).to_contain_text('Eggs cannot be traded')
    page.locator('#pick-mine-search').fill('bud')
    expect(mine.locator('.pick-item')).to_have_count(1)
    mine.locator('[data-key="box-1"]').click()
    expect(mine.locator('[data-key="box-1"]')).to_have_attribute('aria-checked', 'true')
    blue = page.locator(f'[data-game="{BLUE}"]')
    expect(blue).to_be_disabled()
    expect(blue).to_contain_text(REASON)
    shoot(page, f'trade-{width}')
    blue.click(force=True)
    expect(page.locator('#pick-theirs-step')).to_be_hidden()
    page.locator(f'[data-game="{RED}"]').click()
    expect(page.locator('#pick-theirs [data-key="2"]')).to_be_disabled()
    page.locator('#pick-theirs [data-key="1"]').click()
    confirm = page.locator('#pick-confirm')
    expect(confirm).to_have_text('Trade now')
    expect(page.locator('#pick-summary')).to_contain_text('Pidgey')
    shoot(page, f'trade-confirm-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    confirm.click()
    selected(page, 'Offers')
    assert library.posted[0] | {'request_id': None} == {'from_id': FROM, 'from_key': 'box-1', 'to_id': RED, 'to_key': '1',
                                                         'request_id': None}
    expect(page.locator('#offers-outgoing')).to_contain_text('Accepted')
    expect(page.locator('#offers-count')).to_have_text('1')
    shoot(page, f'offers-{width}')
    page.get_by_role('tab', name='History').click()
    shoot(page, f'history-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_a_trade_with_a_view_only_adventure_becomes_an_offer(page, game):
    url = game[0]
    library = Library(page, url, starts_now=False)
    library.open()
    page.locator('#pick-mine [data-key="box-1"]').click()
    page.locator(f'[data-game="{RED}"]').click()
    page.locator('#pick-theirs [data-key="1"]').click()
    expect(page.locator('#pick-confirm')).to_have_text('Send offer')
    expect(page.locator('#pick-summary')).to_contain_text('view-only')
    page.locator('#pick-confirm').click()
    expect(page.locator('#offers-outgoing')).to_contain_text('Waiting for an answer')


def test_trade_link_in_the_pc_opens_the_trade_tab_with_that_pokemon_chosen(page, game):
    url = game[0]
    library = Library(page, url)
    page.goto(f'{url}/games/{FROM}/pc?scope=all')
    page.locator('#pc-grid .pc-mon').filter(has_text='BUD').click()
    link = page.locator('#pc-trade-action').get_by_role('link', name='Trade…')
    href = link.get_attribute('href')
    assert href.startswith(f'/games/{FROM}/trading?tab=trade&mon=')
    library.mine_key = href.split('mon=', 1)[1]
    link.click()
    selected(page, 'Trade')
    expect(page.locator('#pick-mine [aria-checked="true"]')).to_contain_text('BUD')
    expect(page.locator(f'[data-game="{BLUE}"]')).to_be_disabled()
    expect(page.locator(f'[data-game="{RED}"]')).to_be_enabled()


@pytest.mark.parametrize('width', [1280, 390])
def test_auto_tab_switch_wish_list_and_settings(page, game, width):
    url, store = game[0], game[1]
    library = Library(page, url)
    page.set_viewport_size({'width': width, 'height': 844})
    library.open('?tab=auto')
    switch = page.get_by_role('switch', name=re.compile('Auto trading'))
    expect(switch).to_have_attribute('aria-checked', 'true')
    switch.click()
    expect(switch).to_have_attribute('aria-checked', 'false')
    expect(page.locator('#auto-switch-state')).to_have_text('Off')
    expect(page.locator('#trade-status')).to_have_text('Off')
    assert library.saved[-1] == {'enabled': False}
    page.locator('#wish-input').fill('Pikachu')
    page.locator('#wish-add').click()
    expect(page.locator('#wish-list')).to_contain_text('Pikachu')
    assert library.saved[-1] == {'wishlist': [25]}
    setting = page.get_by_label('Trade setting for BUD')
    setting.select_option('keep')
    # The saved setting shows under its own row, not in a toast over the list.
    expect(page.locator('#auto-list .trade-saved')).to_contain_text('never trades it')
    expect(page.locator('#trade-setting-status')).to_contain_text('never trades it')
    expect(page.locator('#toast')).to_be_hidden()
    assert any(value['state'] == 'locked' for value in store.trade_preferences().values())
    expect(page.locator('#auto-list')).not_to_contain_text('Kept by')
    shoot(page, f'auto-{width}')
    page.get_by_role('button', name='Remove Pikachu from the wish list').click()
    expect(page.locator('#wish-list')).not_to_contain_text('Pikachu')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_a_late_answer_for_an_earlier_pokemon_does_not_replace_the_current_one(page, game):
    url = game[0]
    library = Library(page, url)
    library.held['party-0'] = None
    library.open()
    page.locator('#pick-mine [data-key="party-0"]').click()
    page.wait_for_function('document.querySelector("#pick-games").textContent.includes("Checking")')
    page.locator('#pick-mine [data-key="box-1"]').click()
    blue = page.locator(f'[data-game="{BLUE}"]')
    expect(blue).to_contain_text(REASON)
    route, body = library.held['party-0']
    library.json(route, body)
    page.wait_for_timeout(200)
    expect(page.locator('#pick-mine [aria-checked="true"]')).to_contain_text('BUD')
    expect(blue).to_contain_text(REASON)
    expect(page.locator('#pick-games')).not_to_contain_text('Meganium')
    expect(page.locator(f'[data-game="{RED}"]')).to_be_enabled()


def test_a_view_only_adventure_keeps_its_pokemon_disabled_after_a_search(page, game):
    library = Library(page, game[0], viewer_only=True)
    library.open()
    expect(page.locator('#pick-note')).to_contain_text('view-only')
    bud = page.locator('#pick-mine [data-key="box-1"]')
    expect(bud).to_be_disabled()
    page.locator('#pick-mine-search').fill('bud')
    expect(page.locator('#pick-mine .pick-item')).to_have_count(1)
    expect(bud).to_be_disabled()
    page.locator('#pick-mine-search').fill('')
    expect(page.locator('#pick-mine .pick-item')).to_have_count(3)
    for button in page.locator('#pick-mine .pick-item').all():
        expect(button).to_be_disabled()
    expect(page.locator('#pick-game-step')).to_be_hidden()


@pytest.mark.parametrize('width', [1280, 390])
def test_cable_club_tab_links_supported_games_and_greys_out_the_rest(page, game, width):
    url = game[0]
    library = Library(page, url)
    page.set_viewport_size({'width': width, 'height': 844})
    library.open('?tab=cable')
    selected(page, 'Cable Club')
    games = page.locator('#cable-games')
    link = games.get_by_role('link', name=re.compile('Second Crystal'))
    expect(link).to_have_attribute('href', f'/games/{FROM}/cable?with={CRYSTAL}')
    red = games.locator(f'[data-cable="{RED}"]')
    expect(red).to_have_attribute('aria-disabled', 'true')
    expect(red).to_contain_text('not yet supported')
    expect(games.get_by_role('link', name=re.compile('Second Red'))).to_have_count(0)
    shoot(page, f'cable-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
