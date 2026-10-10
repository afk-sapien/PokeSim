"""The Cable Club page starts a session, sends each controller's buttons to its side and shows every phase."""
import io
import json
import re

import pytest
from PIL import Image

from pokesim.web.pages import render_game_page
from test_flows import expect

GOLD = 'a' * 32
SILVER = 'b' * 32
SID = 'c' * 32


def frame():
    buffer = io.BytesIO()
    Image.new('RGB', (160, 144), (40, 80, 40)).save(buffer, 'JPEG')
    return buffer.getvalue()


def status(phase, **extra):
    return {'id': SID, 'kind': 'cable_session', 'phase': phase, 'reason': None, 'decision': None,
            'left_id': GOLD, 'right_id': SILVER, 'trades': 0, 'controls_live': phase == 'in_session',
            'idle_seconds_left': 300 if phase == 'in_session' else None, 'display': None,
            'adventures': {GOLD: {'name': 'Gold Run', 'version': 'gold'}, SILVER: {'name': 'Silver Run', 'version': 'silver'}},
            'cancellable': phase not in {'done', 'rolled_back'}, **extra}


def club(page, url, viewer=False, session=None):
    html = render_game_page('cable-club.html', base_path=f'/{"view" if viewer else "games"}/{GOLD}', adventure_id=GOLD,
                            adventure_name='Gold Run', viewer=viewer, viewer_flag='true' if viewer else 'false')
    state = {'session': session, 'inputs': [], 'created': [], 'finished': 0, 'cancelled': 0, 'streams': [], 'polls': []}
    json_reply = lambda route, body, code=200: route.fulfill(status=code, body=json.dumps(body), content_type='application/json')
    page.route(re.compile(r'/cable-page(\?|$)'), lambda route: route.fulfill(body=html, content_type='text/html'))
    page.route(re.compile(r'/(games|view)/[0-9a-f]{32}/static/'),
               lambda route: route.continue_(url=re.sub(r'/(games|view)/[0-9a-f]{32}/static/', '/static/', route.request.url)))
    def stream(route):
        state['streams'].append(route.request.url.split('/', 3)[-1])
        route.fulfill(body=frame(), content_type='image/jpeg')
    page.route(re.compile(r'/(games|view)/[0-9a-f]{32}/stream(\?|$)'), stream)
    page.route(re.compile(r'/api/v1/session$'), lambda route: json_reply(route, {'csrf_token': 'token', 'role': 'owner'}))
    page.route(re.compile(r'/api/v1/adventures$'), lambda route: json_reply(route, {'adventures': []}))

    def cable(route):
        state['polls'].append(route.request.url.split('/', 3)[-1])
        json_reply(route, {'adventure': {'id': GOLD, 'name': 'Gold Run', 'version': 'gold'}, 'reason': '', 'session': state['session']})
    page.route(re.compile(rf'/games/{GOLD}/api/cable$|/view/{GOLD}/api/cable$'), cable)

    def create(route):
        state['created'].append(json.loads(route.request.post_data))
        state['session'] = status('travelling', preparation={GOLD: 'travelling', SILVER: 'ready'})
        json_reply(route, state['session'])
    page.route(re.compile(r'/api/v1/interactions/cable-sessions$'), create)
    page.route(re.compile(rf'/api/v1/interactions/cable-sessions/{SID}$'), lambda route: route.fulfill(status=401, body='{}'))

    def act(route):
        action = route.request.url.rsplit('/', 1)[-1]
        if action == 'input':
            state['inputs'].append(json.loads(route.request.post_data))
            state['session'] = status('in_session', trades=1 if len(state['inputs']) > 2 else 0)
        elif action == 'finish':
            state['finished'] += 1
            state['session'] = status('done', trades=1, decision='COMMIT')
        else:
            state['cancelled'] += 1
            state['session'] = status('rolled_back', reason='The session was cancelled. Both adventures went back to their Pokémon Center saves.')
        json_reply(route, state['session'])
    page.route(re.compile(rf'/api/v1/interactions/cable-sessions/{SID}/(input|finish|cancel)$'), act)
    page.goto(f'{url}/cable-page?with={SILVER}')
    return state


@pytest.mark.parametrize('width', [1280, 390])
def test_owner_drives_both_controllers_through_a_trade(page, game, width):
    url = game[0]
    page.set_viewport_size({'width': width, 'height': 844})
    state = club(page, url)
    expect(page.locator('#cable-phase')).to_have_text('No session yet')
    page.locator('#cable-start').click()
    expect(page.locator('#cable-phase')).to_have_text('Walking to the Cable Club')
    assert state['created'] == [{'left_id': GOLD, 'right_id': SILVER}]
    expect(page.locator('#cable-left-name')).to_have_text('Gold Run')
    expect(page.locator('#cable-right-screen')).to_have_attribute('src', f'/games/{SILVER}/stream?phase=travelling')
    expect(page.locator('.cable-side[data-side="left"] [data-button="a"]')).to_be_disabled()
    state['session'] = status('in_session')
    expect(page.locator('#cable-phase')).to_have_text('In session. You hold both controllers')
    page.locator('.cable-side[data-side="right"] [data-button="a"]').click()
    page.locator('.cable-side[data-side="left"]').focus()
    page.keyboard.press('ArrowRight')
    page.keyboard.press('x')
    expect(page.locator('#cable-reason')).to_contain_text('Trades so far: 1')
    assert state['inputs'] == [{'side': 'right', 'button': 'a'}, {'side': 'left', 'button': 'right'},
                               {'side': 'left', 'button': 'a'}]
    page.locator('#cable-finish').click()
    expect(page.locator('#cable-phase')).to_have_text('Done. The trade is saved')
    expect(page.locator('#cable-reason')).to_have_text('1 trade saved to both adventures.')
    expect(page.locator('#cable-finish')).to_be_disabled()
    boxes = [page.locator(f'.cable-side[data-side="{side}"]').bounding_box() for side in ('left', 'right')]
    assert (boxes[1]['y'] > boxes[0]['y'] + boxes[0]['height'] - 1) == (width < 720)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_cancel_reports_the_rollback(page, game):
    state = club(page, game[0])
    page.locator('#cable-start').click()
    state['session'] = status('in_session')
    expect(page.locator('#cable-cancel')).to_be_enabled()
    page.locator('#cable-cancel').click()
    expect(page.locator('#cable-phase')).to_have_text('Rolled back')
    expect(page.locator('#cable-reason')).to_contain_text('went back to their Pokémon Center saves')
    assert state['cancelled'] == 1


def test_a_view_link_watches_without_controls(page, game):
    state = club(page, game[0], viewer=True)
    expect(page.locator('#cable-start')).to_be_hidden()
    expect(page.locator('.cable-pad').first).to_be_hidden()
    expect(page.locator('#cable-finish')).to_be_hidden()
    page.keyboard.press('x')
    assert state['inputs'] == [] and state['created'] == []


def test_each_phase_binds_fresh_streams(page, game):
    """The server ends a preview stream when the session moves on, so the page must ask again."""
    state = club(page, game[0])
    page.locator('#cable-start').click()
    expect(page.locator('#cable-left-screen')).to_have_attribute('src', f'/games/{GOLD}/stream?phase=travelling')
    state['session'] = status('in_session')
    expect(page.locator('#cable-left-screen')).to_have_attribute('src', f'/games/{GOLD}/stream?phase=in_session')
    expect(page.locator('#cable-right-screen')).to_have_attribute('src', f'/games/{SILVER}/stream?phase=in_session')
    state['session'] = status('done', trades=1, decision='COMMIT')
    expect(page.locator('#cable-phase')).to_have_text('Done. The trade is saved')
    expect(page.locator('#cable-left-screen')).to_have_attribute('src', f'/games/{GOLD}/stream?phase=done')
    page.wait_for_function('document.querySelector("#cable-left-screen").complete')
    for phase in ('travelling', 'in_session', 'done'):
        assert f'games/{GOLD}/stream?phase={phase}' in state['streams']


def test_a_view_link_follows_the_session_through_its_own_api(page, game):
    state = club(page, game[0], viewer=True, session=status('travelling'))
    expect(page.locator('#cable-phase')).to_have_text('Walking to the Cable Club')
    state['session'] = status('in_session')
    expect(page.locator('#cable-phase')).to_have_text('In session. You hold both controllers')
    expect(page.locator('#cable-left-screen')).to_have_attribute('src', f'/view/{GOLD}/stream?phase=in_session')
    assert len(state['polls']) >= 2 and all(poll == f'view/{GOLD}/api/cable' for poll in state['polls'])
