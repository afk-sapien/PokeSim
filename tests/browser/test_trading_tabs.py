"""The Trading page tabs: build a trade, answer offers and suggestions, set automatic trading and read history."""
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


def shoot(page, name, full_page=True):
    """Screenshots for review, only when POKESIM_SHOTS names a folder. A modal is shot as the viewport shows it."""
    folder = os.environ.get('POKESIM_SHOTS')
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        # A sticky rail repeats down a full-page capture. Pin it to the top for the picture.
        page.add_style_tag(content='.rail { position: static }')
        page.screenshot(path=str(Path(folder) / f'{name}.png'), full_page=full_page)


class Library:
    """The library API the managed Trading page talks to, with the real game worker behind it."""

    def __init__(self, page, url, *, starts_now=True, mine_key='box-1', viewer_only=False):
        self.page, self.url = page, url
        self.viewer_only = viewer_only
        self.limits_held = None
        self.reads = {'auto': 0, 'cable': 0}
        self.starts_now = starts_now
        self.mine_key = mine_key
        self.posted = []
        self.saved = []
        self.offers = []
        self.held = {}
        self.ask_first = True
        self.answered = []
        self.requests = []
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
        page.route(re.compile(r'/api/v1/interactions/cable-sessions/partners(\?|$)'), self.partners)
        page.route(re.compile(r'/api/v1/interactions/trade-requests(/|\?|$)'), self.trade_requests)

    def trade_requests(self, route):
        path = urlparse(route.request.url).path
        if path.endswith('/settings'):
            self.ask_first = json.loads(route.request.post_data)['ask_first']
            if not self.ask_first:
                self.requests = []
            return self.json(route, {'ask_first': self.ask_first})
        if route.request.method == 'POST':
            rid, action = path.rsplit('/', 2)[-2:]
            self.answered.append((rid, action))
            row = next(row for row in self.requests if row['id'] == rid)
            self.requests.remove(row)
            return self.json(route, {**row, 'status': 'accepted' if action == 'accept' else 'dismissed'})
        self.json(route, {'ask_first': self.ask_first, 'requests': self.requests, 'viewer_only': False})

    def request(self, rid='e' * 32):
        return {'id': rid, 'status': 'pending', 'reason': None, 'created_at': 1000, 'updated_at': 1000, 'manual_id': None,
                'reasons': ['New Pokédex entry for Second Red: Bulbasaur', 'Crystal has no Pidgey right now'],
                'left': self.side(FROM, 'Crystal', {'key': 'box-1', 'name': 'Bulbasaur', 'nickname': 'BUD', 'dex': 1, 'level': 5}),
                'right': self.side(RED, 'Second Red', {'key': '1', 'name': 'Pidgey', 'dex': 16, 'level': 9})}

    def partners(self, route):
        self.reads['cable'] += 1
        self.json(route, {
            'adventure_id': FROM, 'partners': [
                {'id': CRYSTAL, 'name': 'Second Crystal', 'version': 'crystal', 'reason': ''},
                {'id': RED, 'name': 'Second Red', 'version': 'red', 'reason': CABLE}]})

    @staticmethod
    def json(route, data, status=200):
        route.fulfill(status=status, body=json.dumps(data), content_type=JSON)

    def open(self, query=''):
        self.page.goto(f'{self.url}/games/{FROM}/trading{query}')

    def interactions(self, route):
        self.json(route, {'adventure': {'id': FROM, 'version': 'crystal', 'state': 'running', 'archived': False},
                          'active': [], 'auto_enabled': self.auto['enabled'], 'ask_first': self.ask_first, 'recent_failures': [
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
        if parse_qs(urlparse(route.request.url).query)['adventure_id'][0] == RED:
            rows = [{'key': '1', 'name': 'Pidgey', 'dex': 16, 'level': 9, 'box': 1, 'blocked': ''},
                    {'key': '2', 'name': 'Mew', 'dex': 151, 'level': 5, 'box': 1, 'blocked': 'Mew stays in this game'}]
            return self.json(route, {'adventure_id': RED, 'reason': '', 'pokemon': [self.side(RED, 'Second Red', row) for row in rows],
                                     'viewer_only': False})
        rows = [{'key': self.mine_key, 'name': 'Bulbasaur', 'nickname': 'BUD', 'dex': 1, 'level': 5, 'box': 1, 'blocked': ''},
                {'key': 'party-0', 'name': 'Meganium', 'dex': 154, 'level': 30, 'location': 'party', 'shiny': True, 'blocked': ''},
                {'key': 'egg', 'name': 'Egg', 'location': 'party', 'blocked': 'Eggs cannot be traded'}]
        self.json(route, {'adventure_id': FROM, 'reason': '', 'pokemon': [self.side(FROM, 'Crystal', row) for row in rows],
                          'viewer_only': self.viewer_only})

    def targets(self, route):
        key = parse_qs(urlparse(route.request.url).query).get('from_key', [None])[0]
        reason = MEGANIUM if key == 'party-0' else REASON
        body = {'adventures': [
            {'id': RED, 'name': 'Second Red', 'version': 'red', 'generation': 1, 'available': key != 'party-0',
             'reason': MEGANIUM if key == 'party-0' else ''},
            {'id': BLUE, 'name': 'Busy Blue', 'version': 'blue', 'generation': 1, 'available': False, 'reason': reason}],
            'from_key': key, 'viewer_only': False}
        if key is not None and key in self.held:
            # Held back so a test can answer it late, after another Pokémon was picked.
            self.held[key] = (route, body)
            return
        self.json(route, body)

    def limits(self, route):
        if self.limits_held is not None and not self.limits_held:
            # The first answer is held so a test can send it after a newer request.
            self.limits_held.append(route)
            return
        self.json(route, {'pokemon': [self.side(RED, 'Second Red', {'key': '1', 'name': 'Pidgey', 'dex': 16, 'level': 9, 'blocked': ''}),
                                      self.side(RED, 'Second Red', {'key': '2', 'name': 'Mew', 'dex': 151, 'level': 5,
                                                                    'blocked': 'Mew stays in this game'})],
                          'from': {'key': parse_qs(urlparse(route.request.url).query)['from_key'][0], 'blocked': ''},
                          'to': {'adventure_id': RED, 'adventure_name': 'Second Red', 'viewer_only': not self.starts_now},
                          'starts_now': self.starts_now, 'viewer_only': False, 'blocked': {}})

    def auto_settings(self, route):
        if route.request.method == 'GET':
            self.reads['auto'] += 1
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


SLOTS = {'mine': '#slot-send', 'theirs': '#slot-get'}


def open_picker(page, side):
    page.locator(f'{SLOTS[side]} [data-slot]').click()
    picker = page.locator('#pick-dialog')
    expect(picker).to_be_visible()
    expect(page.locator(f'#pick-{side}-pane')).to_be_visible()
    return picker


def choose(page, side, key):
    """Pick one card the way a player does: open the slot's picker, then press the card."""
    picker = open_picker(page, side)
    picker.locator(f'#pick-{side} [data-key="{key}"]').click()
    expect(picker).to_be_hidden()


def option(page, aid):
    return page.locator(f'#pick-game option[value="{aid}"]')


@pytest.mark.parametrize('width', [1280, 390])
def test_trade_builder_picks_both_slots_in_a_modal_and_starts_an_owned_trade(page, game, width):
    url = game[0]
    library = Library(page, url)
    page.set_viewport_size({'width': width, 'height': 844})
    library.open()
    confirm = page.locator('#pick-confirm')
    expect(page.locator('#slot-send')).to_contain_text('Choose a Pokémon')
    expect(page.locator('#slot-get .slot-empty')).to_be_disabled()
    expect(confirm).to_be_disabled()
    expect(page.locator('#pick-summary')).to_contain_text('Choose a game to trade with')
    # Before a Pokémon is chosen, only the game's own limits grey a game out.
    expect(option(page, BLUE)).to_have_attribute('disabled', '')
    expect(option(page, BLUE)).to_contain_text(REASON)
    shoot(page, f'trade-{width}')
    picker = open_picker(page, 'mine')
    mine = page.locator('#pick-mine')
    # The PC page's cards and filters, inside the modal.
    expect(mine.locator('.pc-mon')).to_have_count(3)
    expect(page.locator('#pick-mine-count')).to_have_text('3 Pokémon')
    expect(page.locator('#pick-mine-search')).to_be_focused()
    box = picker.bounding_box()
    assert box['width'] <= width and box['height'] <= 844
    egg = mine.locator('[data-key="egg"]')
    expect(egg).to_have_attribute('aria-disabled', 'true')
    expect(egg).to_contain_text('Eggs cannot be traded')
    shoot(page, f'modal-{width}', full_page=False)
    page.locator('#pick-mine-search').fill('bud')
    expect(mine.locator('.pc-mon')).to_have_count(1)
    expect(page.locator('#pick-mine-count')).to_have_text('1 of 3 Pokémon')
    page.locator('#pick-mine-search').fill('')
    page.locator('#pick-mine-rating').select_option('shiny')
    expect(mine.locator('.pc-mon')).to_contain_text('Meganium')
    page.locator('#pick-mine-rating').select_option('all')
    page.locator('#pick-mine-sort').select_option('level')
    expect(mine.locator('.pc-mon').first).to_contain_text('Meganium')
    page.locator('#pick-mine-order').select_option('asc')
    expect(mine.locator('.pc-mon').first).to_contain_text('BUD')
    # A blocked card stays in the modal and says why.
    egg.click(force=True)
    expect(picker).to_be_visible()
    expect(page.locator('#pick-dialog-note')).to_contain_text('Eggs cannot be traded')
    page.keyboard.press('Escape')
    expect(picker).to_be_hidden()
    choose(page, 'mine', 'box-1')
    expect(page.locator('#slot-send .pc-mon')).to_contain_text('BUD')
    expect(page.locator('#pick-summary')).to_contain_text('Choose a game to trade with')
    # With a Pokémon chosen, every game is checked against it.
    expect(option(page, BLUE)).to_contain_text(REASON)
    expect(option(page, RED)).not_to_have_attribute('disabled', '')
    page.locator('#pick-game').select_option(RED)
    expect(page.locator('#slot-get-game')).to_have_text('In Second Red')
    expect(page.locator('#pick-summary')).to_contain_text('Choose a Pokémon to get')
    picker = open_picker(page, 'theirs')
    mew = page.locator('#pick-theirs [data-key="2"]')
    expect(mew).to_have_attribute('aria-disabled', 'true')
    expect(mew).to_contain_text('Mew stays in this game')
    mew.click(force=True)
    expect(page.locator('#pick-dialog-note')).to_contain_text('Mew stays in this game')
    expect(page.locator('#pick-theirs-count')).to_have_text('2 Pokémon')
    shoot(page, f'modal-theirs-{width}', full_page=False)
    page.locator('#pick-dialog-close').click()
    choose(page, 'theirs', '1')
    expect(page.locator('#slot-get .pc-mon')).to_contain_text('Pidgey')
    expect(confirm).to_be_enabled()
    expect(confirm).to_have_text('Trade')
    expect(page.locator('#pick-summary')).to_contain_text('starts as soon as both games are ready')
    shoot(page, f'trade-confirm-{width}')
    # A chosen card opens the shared detail panel.
    page.locator('#slot-send .pc-mon').click()
    dialog = page.locator('#trade-detail')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('Bulbasaur')
    shoot(page, f'trade-detail-{width}', full_page=False)
    page.locator('#trade-detail-close').click()
    expect(dialog).to_be_hidden()
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


def test_their_pokemon_can_be_chosen_first_and_clear_empties_both_slots(page, game):
    library = Library(page, game[0])
    library.open()
    page.locator('#pick-game').select_option(RED)
    choose(page, 'theirs', '1')
    expect(page.locator('#pick-summary')).to_contain_text('Choose a Pokémon to send')
    expect(page.locator('#pick-confirm')).to_be_disabled()
    choose(page, 'mine', 'box-1')
    expect(page.locator('#pick-confirm')).to_be_enabled()
    # The detail panel offers another pick.
    page.locator('#slot-get .pc-mon').click()
    page.locator('#trade-detail').get_by_role('button', name='Choose another Pokémon').click()
    expect(page.locator('#pick-theirs-pane')).to_be_visible()
    page.keyboard.press('Escape')
    page.locator('#pick-reset').click()
    expect(page.locator('#slot-send')).to_contain_text('Choose a Pokémon')
    expect(page.locator('#slot-get')).to_contain_text('Choose a Pokémon')
    expect(page.locator('#pick-confirm')).to_be_disabled()


def test_a_trade_with_a_view_only_adventure_becomes_an_offer(page, game):
    url = game[0]
    library = Library(page, url, starts_now=False)
    library.open()
    choose(page, 'mine', 'box-1')
    page.locator('#pick-game').select_option(RED)
    choose(page, 'theirs', '1')
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
    expect(page.locator('#slot-send .pc-mon')).to_contain_text('BUD')
    expect(option(page, BLUE)).to_have_attribute('disabled', '')
    expect(option(page, RED)).not_to_have_attribute('disabled', '')


def test_a_late_answer_for_an_earlier_pokemon_does_not_replace_the_current_one(page, game):
    url = game[0]
    library = Library(page, url)
    library.held['party-0'] = None
    library.open()
    choose(page, 'mine', 'party-0')
    page.wait_for_function('document.querySelector("#slot-send").textContent.includes("Meganium")')
    choose(page, 'mine', 'box-1')
    expect(option(page, BLUE)).to_contain_text(REASON)
    route, body = library.held['party-0']
    library.json(route, body)
    page.wait_for_timeout(200)
    expect(page.locator('#slot-send .pc-mon')).to_contain_text('BUD')
    expect(option(page, BLUE)).to_contain_text(REASON)
    expect(page.locator('#pick-game')).not_to_contain_text('Meganium')
    expect(option(page, RED)).not_to_have_attribute('disabled', '')


def test_a_view_only_adventure_cannot_fill_the_send_slot(page, game):
    library = Library(page, game[0], viewer_only=True)
    library.open()
    expect(page.locator('#pick-note')).to_contain_text('view-only')
    expect(page.locator('#slot-send .slot-empty')).to_be_disabled()
    expect(page.locator('#pick-confirm')).to_be_disabled()


@pytest.mark.parametrize('late', ['answer', 'error'])
def test_a_late_limits_answer_does_not_replace_the_newer_list(page, game, late):
    library = Library(page, game[0])
    library.limits_held = []
    library.open()
    choose(page, 'mine', 'box-1')
    page.locator('#pick-game').select_option(RED)
    page.wait_for_function('document.querySelector("#pick-theirs").textContent.includes("Reading")')
    # Pick again, so the first answer now belongs to an earlier pick.
    choose(page, 'mine', 'box-1')
    expect(page.locator('#pick-theirs')).to_contain_text('Pidgey')
    old = library.limits_held[0]
    if late == 'error':
        library.json(old, {'detail': 'An old answer failed'}, 500)
    else:
        library.json(old, {'pokemon': [library.side(RED, 'Second Red', {'key': '9', 'name': 'Rattata', 'dex': 19, 'blocked': ''})],
                           'to': {'adventure_id': RED, 'adventure_name': 'Second Red'}, 'starts_now': True})
    page.wait_for_timeout(200)
    expect(page.locator('#pick-theirs')).to_contain_text('Pidgey')
    expect(page.locator('#pick-theirs')).not_to_contain_text('Rattata')
    expect(page.locator('#pick-theirs')).not_to_contain_text('old answer')


@pytest.mark.parametrize('width', [1280, 390])
def test_suggested_trades_wait_at_the_top_until_accepted_or_dismissed(page, game, width):
    library = Library(page, game[0])
    library.requests = [library.request(), library.request('f' * 32)]
    page.set_viewport_size({'width': width, 'height': 844})
    library.open()
    section = page.locator('#trade-requests-section')
    expect(section).to_be_visible()
    expect(page.locator('#trade-status')).to_have_text('On · Asks before trading')
    cards = section.locator('.request-card')
    expect(cards).to_have_count(2)
    first = cards.first
    expect(first).to_contain_text('Bulbasaur')
    expect(first).to_contain_text('Pidgey')
    expect(first).to_contain_text('New Pokédex entry for Second Red: Bulbasaur')
    shoot(page, f'requests-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    first.get_by_role('button', name='Accept').click()
    expect(page.locator('#requests-note')).to_contain_text('Trade started')
    expect(cards).to_have_count(1)
    cards.first.get_by_role('button', name='Dismiss').click()
    expect(page.locator('#requests-note')).to_contain_text('will not be suggested again')
    expect(section).to_be_hidden()
    assert library.answered == [('e' * 32, 'accept'), ('f' * 32, 'dismiss')]


def test_ask_me_first_switch_in_the_auto_tab(page, game):
    library = Library(page, game[0])
    library.requests = [library.request()]
    library.open('?tab=auto')
    switch = page.get_by_role('switch', name=re.compile('Ask me first'))
    expect(switch).to_have_attribute('aria-checked', 'true')
    switch.click()
    expect(switch).to_have_attribute('aria-checked', 'false')
    expect(page.locator('#auto-note')).to_contain_text('Ask me first is off')
    expect(page.locator('#trade-requests-section')).to_be_hidden()
    expect(page.locator('#trade-status')).to_have_text('On · No approvals needed')
    assert library.ask_first is False


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
    # Each Pokémon is a PC card with its setting stamp. The popup changes the setting.
    bud = page.locator('#auto-list .pc-mon').filter(has_text='BUD')
    expect(bud.locator('.trade-tag')).to_have_text('Can trade')
    bud.click()
    dialog = page.locator('#trade-detail')
    setting = dialog.get_by_label('Trade setting for BUD')
    setting.select_option('keep')
    # The saved setting shows in the popup, not in a toast over the list.
    expect(dialog.locator('.trade-saved')).to_contain_text('Never trade')
    expect(page.locator('#trade-setting-status')).to_contain_text('Never trade')
    expect(page.locator('#toast')).to_be_hidden()
    assert any(value['state'] == 'locked' for value in store.trade_preferences().values())
    shoot(page, f'auto-detail-{width}')
    page.locator('#trade-detail-close').click()
    expect(bud.locator('.trade-tag')).to_have_text('Never trade')
    page.locator('#auto-setting').select_option('keep')
    expect(page.locator('#auto-list .pc-mon')).to_have_count(1)
    expect(page.locator('#auto-list .pc-mon')).to_contain_text('BUD')
    expect(page.locator('#auto-list')).not_to_contain_text('Kept by')
    shoot(page, f'auto-{width}')
    page.locator('#auto-setting').select_option('all')
    page.get_by_role('button', name='Remove Pikachu from the wish list').click()
    expect(page.locator('#wish-list')).not_to_contain_text('Pikachu')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_auto_and_cable_tabs_read_again_on_every_visit(page, game):
    library = Library(page, game[0])
    library.open('?tab=auto')
    expect(page.locator('#auto-switch')).to_be_enabled()
    page.get_by_role('tab', name='Cable Club').click()
    expect(page.locator('#cable-games')).to_contain_text('Second Crystal')
    library.auto['enabled'] = False
    page.get_by_role('tab', name='Auto').click()
    expect(page.locator('#auto-switch-state')).to_have_text('Off')
    page.get_by_role('tab', name='Cable Club').click()
    expect(page.locator('#cable-games')).to_contain_text('Second Crystal')
    assert library.reads['auto'] >= 2
    page.wait_for_timeout(100)
    assert library.reads['cable'] >= 2


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
