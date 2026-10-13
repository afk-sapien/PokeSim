"""The game Trading page: the automatic trading switch, then a Make a trade tab and a History tab."""
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

    def __init__(self, page, url, *, starts_now=True, mine_key='box-1', viewer_only=False, busy=''):
        self.page, self.url = page, url
        self.busy = busy
        self.cancelled = []
        self.viewer_only = viewer_only
        self.limits_held = None
        self.reads = {'auto': 0}
        self.starts_now = starts_now
        self.mine_key = mine_key
        self.posted = []
        self.saved = []
        self.queued = []
        self.held = {}
        self.request_reads = []
        self.auto = {'adventure_id': FROM, 'enabled': True, 'viewer_only': False}
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
        page.route(re.compile(r'/api/v1/interactions/trade-builder(\?|$)'), self.build)
        page.route(re.compile(r'/api/v1/interactions/trade-builder/pokemon(\?|$)'), self.pokemon)
        page.route(re.compile(r'/api/v1/interactions/trade-builder/targets(\?|$)'), self.targets)
        page.route(re.compile(r'/api/v1/interactions/trade-builder/limits(\?|$)'), self.limits)
        page.route(re.compile(r'/api/v1/interactions/auto-settings(\?|$)'), self.auto_settings)
        page.route(re.compile(r'/api/v1/interactions/trade-builder/[0-9a-f]{32}/cancel$'), self.cancel)
        # Ask me first is gone. Any call to its old API is recorded and answered as the library does.
        page.route(re.compile(r'/api/v1/interactions/trade-requests(/|\?|$)'),
                   lambda route: self.request_reads.append(route.request.url) or self.json(route, {'detail': 'Not Found'}, 404))

    @staticmethod
    def json(route, data, status=200):
        route.fulfill(status=status, body=json.dumps(data), content_type=JSON)

    def open(self, query=''):
        self.page.goto(f'{self.url}/games/{FROM}/trading{query}')

    def interactions(self, route):
        self.json(route, {'adventure': {'id': FROM, 'version': 'crystal', 'state': 'running', 'archived': False},
                          'active': [], 'queued': self.queued, 'auto_enabled': self.auto['enabled'], 'recent_failures': [
                              {'phase': 'aborted', 'decision': 'ABORT', 'peer_name': 'Busy Blue', 'updated_at': 2000,
                               'failure_reason': 'Busy Blue could not reach the Cable Club.'}],
                          'history': [{'phase': 'completed', 'decision': 'COMMIT', 'peer_name': 'Second Red',
                                       'peer_id': RED, 'updated_at': 1000,
                                       'sent': {'name': 'Abra', 'dex': 63, 'level': 12},
                                       'received': {'name': 'Kadabra', 'dex': 64, 'level': 12}}]})

    def side(self, aid, name, mon):
        return {'adventure_id': aid, 'adventure_name': name, 'sprite_url': None, **mon}

    def build(self, route):
        body = json.loads(route.request.post_data)
        self.posted.append(body)
        trade = {'id': body.get('request_id') or 'd' * 32, 'state': 'queued', 'left_id': FROM, 'right_id': body['to_id'],
                 'left_key': body['from_key'], 'right_key': body['to_key'], 'position': 1}
        self.queued.append({'id': trade['id'], 'state': 'queued', 'position': 1, 'peer_id': RED,
                            'peer_name': 'Second Red', 'created_at': 3000, 'cancellable': True, 'busy': bool(self.busy)})
        self.json(route, trade)

    def cancel(self, route):
        mid = route.request.url.rsplit('/', 2)[-2]
        self.cancelled.append((route.request.method, mid))
        self.queued = [entry for entry in self.queued if entry['id'] != mid]
        self.json(route, {'id': mid, 'state': 'cancelled', 'cancellable': False})

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
             'reason': MEGANIUM if key == 'party-0' else '', 'busy': self.busy},
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
                          'starts_now': self.starts_now, 'viewer_only': False, 'blocked': {}, 'busy': self.busy})

    def auto_settings(self, route):
        if route.request.method == 'GET':
            self.reads['auto'] += 1
        if route.request.method == 'PUT':
            change = json.loads(route.request.post_data)
            self.saved.append(change)
            self.auto.update(change)
        self.json(route, self.auto)


def on_screen(page, selector):
    expect(page.locator(selector)).to_be_in_viewport()


def tabs(page):
    return page.get_by_role('tablist', name='Trading').get_by_role('tab')


def on_tab(page, name):
    """The named tab is selected, its panel shows and the other panel is hidden."""
    other = 'history' if name == 'make' else 'make'
    expect(page.locator(f'#tab-{name}')).to_have_attribute('aria-selected', 'true')
    expect(page.locator(f'#tab-{other}')).to_have_attribute('aria-selected', 'false')
    expect(page.locator(f'#panel-{name}')).to_be_visible()
    expect(page.locator(f'#panel-{other}')).to_be_hidden()


@pytest.mark.parametrize('width', [1280, 390])
def test_trading_has_the_switch_up_top_then_make_a_trade_and_history_tabs(page, game, width):
    url = game[0]
    library = Library(page, url)
    page.set_viewport_size({'width': width, 'height': 844})
    library.open()
    overview = page.locator('.trade-overview')
    expect(overview.get_by_role('switch', name=re.compile('Auto trading'))).to_be_enabled()
    # The status box is the switch and nothing else: no headline, no explanation, no wish list.
    assert overview.inner_text().split() == ['Auto', 'trading', 'On'], overview.inner_text()
    expect(page.locator('main .trade-help, .page-lede, #trade-status, #trade-activity, [id^="wish"]')).to_have_count(0)
    expect(page.locator('#auto-list, #auto-setting, .trade-setting')).to_have_count(0)
    # Under the switch, two tabs. Make a trade is the default and the URL keeps no hash for it.
    expect(tabs(page)).to_have_text(['Make a trade', re.compile(r'^History \(2\)$')])
    expect(page.locator('#tab-history')).to_have_attribute('title', '1 completed, 1 did not complete')
    order = page.evaluate("""[...document.querySelectorAll('main > *')].map(el => el.id || el.className)""")
    assert order[1:] == ['trade-overview', 'trade-connection-note', 'trade-tabs', 'panel-make', 'panel-history'], order
    on_tab(page, 'make')
    expect(page.locator('#make-trade')).to_be_visible()
    expect(page.locator('#trade-history')).to_be_hidden()
    assert urlparse(page.url).fragment == ''
    # The tabs sit on their divider and the switch sits above them.
    strip = page.locator('.trade-tabs').bounding_box()
    chosen = page.locator('#tab-make').bounding_box()
    assert abs(chosen['y'] + chosen['height'] - (strip['y'] + strip['height'])) <= 1, (chosen, strip)
    assert overview.bounding_box()['y'] + overview.bounding_box()['height'] <= strip['y']
    shoot(page, f'trading-make-{width}')
    # A click shows History alone and writes #history.
    page.locator('#tab-history').click()
    on_tab(page, 'history')
    expect(page.locator('#make-trade')).to_be_hidden()
    expect(page.locator('#trade-history')).to_contain_text('Busy Blue could not reach the Cable Club')
    # History lists failed attempts and completed trades together, newest first.
    text = page.locator('#trade-history').inner_text()
    assert text.index('Busy Blue') < text.index('Second Red')
    # A finished trade's partner link opens the partner's History.
    expect(page.locator('#trade-history').get_by_role('link', name='Second Red')).to_have_attribute(
        'href', f'/games/{RED}/trading#history')
    assert urlparse(page.url).fragment == 'history'
    shoot(page, f'trading-history-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    # A reload keeps the tab.
    page.reload()
    on_tab(page, 'history')
    # Arrow keys move between the tabs, wrapping around, and Home and End jump.
    page.locator('#tab-history').focus()
    page.keyboard.press('ArrowRight')
    on_tab(page, 'make')
    expect(page.locator('#tab-make')).to_be_focused()
    assert urlparse(page.url).fragment == 'make'
    page.keyboard.press('ArrowLeft')
    on_tab(page, 'history')
    expect(page.locator('#tab-history')).to_be_focused()
    page.keyboard.press('Home')
    on_tab(page, 'make')
    page.keyboard.press('End')
    on_tab(page, 'history')
    # Only the selected tab is in the Tab order.
    expect(page.locator('#tab-make')).to_have_attribute('tabindex', '-1')
    expect(page.locator('#tab-history')).to_have_attribute('tabindex', '0')
    # A link to #make, or a hash change on the page, picks the tab too.
    library.open('#make')
    on_tab(page, 'make')
    page.evaluate("location.hash = '#history'")
    on_tab(page, 'history')
    # An old ?tab=history link opens History.
    library.open('?tab=history')
    on_tab(page, 'history')
    assert urlparse(page.url).fragment == 'history'


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
    expect(page.locator('#pick-summary')).to_be_hidden()
    expect(confirm).to_have_attribute('title', 'Choose a game to trade with.')
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
    expect(confirm).to_have_attribute('title', 'Choose a game to trade with.')
    # With a Pokémon chosen, every game is checked against it.
    expect(option(page, BLUE)).to_contain_text(REASON)
    expect(option(page, RED)).not_to_have_attribute('disabled', '')
    page.locator('#pick-game').select_option(RED)
    expect(page.locator('#slot-get-game')).to_have_text('In Second Red')
    expect(confirm).to_have_attribute('title', 'Choose a Pokémon to get.')
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
    expect(page.locator('#pick-summary')).to_be_hidden()
    expect(confirm).to_have_attribute('title', '')
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
    # The trade is queued at once and the page scrolls to it under Current exchange, on Make a trade.
    on_screen(page, '#current-exchange-section')
    on_tab(page, 'make')
    assert library.posted[0] | {'request_id': None} == {'from_id': FROM, 'from_key': 'box-1', 'to_id': RED, 'to_key': '1',
                                                         'request_id': None}
    current = page.locator('#current-exchange-section')
    expect(current).to_be_visible()
    expect(current).to_contain_text('Waiting for the Cable Club')
    expect(current).to_contain_text('Second Red')
    shoot(page, f'history-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1280, 390])
def test_a_game_busy_with_a_trade_can_be_picked_and_its_queued_trade_cancelled(page, game, width):
    busy = 'Busy with a trade. Your trade will wait in line.'
    library = Library(page, game[0], busy=busy)
    page.set_viewport_size({'width': width, 'height': 844})
    library.open()
    # Busy is not a limit: the game can be chosen, and says its trade will wait.
    expect(option(page, RED)).not_to_have_attribute('disabled', '')
    expect(option(page, RED)).to_have_text('Second Red, red, busy with a trade')
    choose(page, 'mine', 'box-1')
    page.locator('#pick-game').select_option(RED)
    expect(page.locator('#pick-game-reason')).to_have_text(f'Second Red: {busy}')
    choose(page, 'theirs', '1')
    confirm = page.locator('#pick-confirm')
    expect(confirm).to_be_enabled()
    expect(page.locator('#pick-summary')).to_have_text(busy)
    shoot(page, f'trade-busy-{width}')
    confirm.click()
    on_screen(page, '#current-exchange-section')
    card = page.locator('#current-exchange-section .queued-card')
    expect(card).to_contain_text('Waiting for the Cable Club')
    expect(card).to_contain_text(busy)
    cancel = card.get_by_role('button', name='Cancel trade')
    expect(cancel).to_be_visible()
    shoot(page, f'history-busy-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    cancel.click()
    expect(page.locator('#current-exchange-section')).to_be_hidden()
    assert library.cancelled == [('POST', library.posted[0]['request_id'])]


def test_their_pokemon_can_be_chosen_first_and_clear_empties_both_slots(page, game):
    library = Library(page, game[0])
    library.open()
    page.locator('#pick-game').select_option(RED)
    choose(page, 'theirs', '1')
    expect(page.locator('#pick-confirm')).to_have_attribute('title', 'Choose a Pokémon to send.')
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


def test_a_view_only_adventure_is_a_disabled_choice_with_its_reason(page, game):
    library = Library(page, game[0], starts_now=False)
    view_only = 'This adventure is view-only, so it cannot trade'

    def targets(route):
        # The library marks a view-only adventure unavailable. Its reason shows in the list.
        library.json(route, {'adventures': [
            {'id': RED, 'name': 'Second Red', 'version': 'red', 'generation': 1, 'available': True, 'reason': ''},
            {'id': BLUE, 'name': 'Watched Blue', 'version': 'blue', 'generation': 1, 'available': False, 'reason': view_only}],
            'from_key': None, 'viewer_only': False})
    page.unroute(re.compile(r'/api/v1/interactions/trade-builder/targets(\?|$)'))
    page.route(re.compile(r'/api/v1/interactions/trade-builder/targets(\?|$)'), targets)
    library.open()
    expect(option(page, BLUE)).to_have_attribute('disabled', '')
    expect(option(page, BLUE)).to_contain_text(view_only)
    # Should a partner turn view-only after it was chosen, the Trade key stays off and says why.
    choose(page, 'mine', 'box-1')
    page.locator('#pick-game').select_option(RED)
    choose(page, 'theirs', '1')
    expect(page.locator('#pick-confirm')).to_be_disabled()
    expect(page.locator('#pick-confirm')).to_have_text('Trade')
    expect(page.locator('#pick-summary')).to_contain_text('view-only')
    assert library.posted == []


def test_trade_link_in_the_pc_opens_the_trade_builder_with_that_pokemon_chosen(page, game):
    url = game[0]
    library = Library(page, url)
    page.goto(f'{url}/games/{FROM}/pc?scope=all')
    page.locator('#pc-grid .pc-mon').filter(has_text='BUD').click()
    link = page.locator('#pc-trade-action').get_by_role('link', name='Trade…')
    href = link.get_attribute('href')
    assert href.startswith(f'/games/{FROM}/trading?tab=trade&mon=')
    library.mine_key = href.split('mon=', 1)[1]
    link.click()
    on_tab(page, 'make')
    on_screen(page, '#make-trade')
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
def test_automatic_trades_run_without_asking(page, game, width):
    library = Library(page, game[0])
    page.set_viewport_size({'width': width, 'height': 844})
    library.open('?tab=auto')
    on_screen(page, '.trade-overview')
    expect(page.locator('#trade-lamp')).to_have_attribute('title', 'On')
    expect(page.locator('#auto-switch')).to_be_enabled()
    # There is no Ask me first switch and no suggested trades to accept or dismiss.
    expect(page.get_by_role('switch')).to_have_count(1)
    expect(page.get_by_text('Ask me first')).to_have_count(0)
    expect(page.locator('#trade-requests-section, .request-card, [data-request-action]')).to_have_count(0)
    shoot(page, f'auto-on-{width}')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.get_by_role('button', name=re.compile('Accept|Dismiss'))).to_have_count(0)
    page.wait_for_timeout(300)
    assert library.request_reads == []


@pytest.mark.parametrize('width', [1280, 390])
def test_status_box_switch_turns_auto_trading_off(page, game, width):
    library = Library(page, game[0])
    page.set_viewport_size({'width': width, 'height': 844})
    library.open()
    switch = page.locator('.trade-overview').get_by_role('switch', name=re.compile('Auto trading'))
    expect(switch).to_have_attribute('aria-checked', 'true')
    switch.click()
    expect(switch).to_have_attribute('aria-checked', 'false')
    expect(page.locator('#auto-switch-state')).to_have_text('Off')
    expect(page.locator('#trade-lamp')).to_have_attribute('title', 'Off')
    assert library.saved == [{'enabled': False}]
    # Saving says nothing. The switch shows the state.
    expect(page.locator('#auto-note')).to_be_hidden()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1280, 390])
def test_pc_popup_lock_shows_on_the_grid_and_party(page, game, width):
    url, store = game[0], game[1]
    Library(page, url)
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(f'{url}/games/{FROM}/pc?scope=all')
    bud = page.locator('#pc-grid .pc-mon').filter(has_text='BUD')
    bud.click()
    lock = page.get_by_role('button', name='Tradeable')
    lock.press('Space')
    expect(page.locator('#pc-detail .lock-toggle')).to_have_text('Locked')
    assert any(value['state'] == 'locked' for value in store.trade_preferences().values())
    shoot(page, f'pc-lock-popup-{width}', full_page=False)
    page.keyboard.press('Escape')
    expect(bud.locator('.pc-lock')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    shoot(page, f'pc-lock-grid-{width}')


@pytest.mark.parametrize('tab', ['offers', 'cable', 'auto'])
def test_an_old_tab_link_or_remembered_tab_still_opens_the_page(page, game, tab):
    library = Library(page, game[0])
    page.goto(f'{game[0]}/games/{FROM}/trading')
    page.evaluate(f'localStorage.setItem("pokesim-trading-tab", "{tab}")')
    library.open(f'?tab={tab}')
    on_tab(page, 'make')
    expect(page.locator('#make-trade')).to_be_visible()
    expect(page.locator('#auto-switch')).to_be_enabled()


@pytest.mark.parametrize('width', [1280, 390])
def test_a_deep_link_that_chooses_a_pokemon_lands_on_make_a_trade(page, game, width):
    library = Library(page, game[0])
    page.set_viewport_size({'width': width, 'height': 844})
    # Even from a page left on History, a ?mon= link opens Make a trade with that Pokémon chosen.
    library.open('#history')
    on_tab(page, 'history')
    library.open('?tab=trade&mon=box-1#history')
    on_tab(page, 'make')
    on_screen(page, '#make-trade')
    expect(page.locator('#slot-send .pc-mon')).to_contain_text('BUD')
    assert urlparse(page.url).fragment == 'make'
    # A plain Trading link, as the nav bar has, opens Make a trade.
    library.open()
    on_tab(page, 'make')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
