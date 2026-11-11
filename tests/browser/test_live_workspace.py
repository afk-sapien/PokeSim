"""Keep the live columns aligned and partner inspection separate from game input."""
from dataclasses import replace
import re

import pytest

from conftest import refused

from pokesim import config
from test_flows import expect


@pytest.fixture
def live_game(game):
    url, store, emu, eid = game
    emu.snapshot = replace(emu.snapshot, party=tuple(
        replace(emu.snapshot.party[0], nick=f'PARTNER {index + 1}') for index in range(6)))
    original = emu.status

    def status():
        return {**original(), 'strategy': {'objective': {'title': 'Train the team'},
                                          'action': 'training', 'collection': {'version': 'red'}}}

    emu.status = status
    return url, emu


@pytest.mark.parametrize('width', [1600, 1280, 1100, 1000, 900, 800, 640, 390, 320])
def test_live_columns_and_partner_details(page, live_game, width):
    url, emu = live_game
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url)
    expect(page.locator('#party-count')).to_have_text('6 / 6')
    expect(page.locator('#objective')).to_have_text('Train the team')
    assert page.locator('.adventure-workspace, #route-map, #bag-items').count() == 0
    game_box = page.locator('.game-card').bounding_box()
    team_box = page.locator('.watch-companions').bounding_box()
    trainer_box = page.locator('#journey-progress').bounding_box()
    plan_box = page.locator('#strategy-panel').bounding_box()
    if width >= 1280:
        # Side by side, the screen's housing tops out level with the first bay
        # and the stage and the party end on the same line.
        first_bay = page.locator('#party > li').first.bounding_box()
        last_bay = page.locator('#party > li').last.bounding_box()
        assert abs(page.locator('.bezel').bounding_box()['y'] - first_bay['y']) < 1
        assert abs(game_box['y'] + game_box['height'] - (last_bay['y'] + last_bay['height'])) < 1
        assert abs(game_box['x'] + game_box['width'] - team_box['x']) <= 32
    else:
        # Stacked, the party follows the stage.
        assert team_box['y'] >= game_box['y'] + game_box['height']
    # The plan is its own full-width row under both.
    assert plan_box['y'] >= max(game_box['y'] + game_box['height'], team_box['y'] + team_box['height'])
    assert abs(plan_box['x'] - min(game_box['x'], team_box['x'])) < 1
    assert abs(plan_box['x'] + plan_box['width'] - max(game_box['x'] + game_box['width'], team_box['x'] + team_box['width'])) < 1
    # The trainer, badge and totals summary sits above the game and party panels.
    assert trainer_box['y'] + trainer_box['height'] <= min(game_box['y'], team_box['y'])
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')

    team_height = page.locator('#team').bounding_box()['height']
    partner = page.get_by_role('button', name='View PARTNER 1 details')
    partner.click()
    expect(page.get_by_role('dialog')).to_be_visible()
    expect(page.locator('#mon-detail .lock-toggle')).to_be_visible()
    page.keyboard.press('ArrowUp')
    page.keyboard.press('z')
    assert emu.commands == []
    emu.snapshot = replace(emu.snapshot, party=(replace(emu.snapshot.party[0], hp=12), *emu.snapshot.party[1:]))
    expect(page.locator('#mon-detail .pc-sum-meter').first).to_contain_text('12/30')
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).to_be_hidden()
    expect(partner).to_be_focused()
    assert page.locator('#team').bounding_box()['height'] == team_height


def test_viewer_only_live_page_keeps_the_game_visible(page, live_game, monkeypatch):
    url, emu = live_game
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    page.goto(url)
    expect(page.locator('#take-control')).to_be_hidden()
    expect(page.locator('#screen')).to_be_visible()
    expect(page.locator('#party-count')).to_have_text('6 / 6')


@pytest.mark.parametrize('width,height', [(1920, 1080), (900, 700), (390, 844)])
def test_fullscreen_fills_viewport_without_stretching_picture(page, live_game, width, height):
    url, _ = live_game
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url)
    expect(page.locator('#screen img')).to_have_attribute('src', re.compile(r'.+'))
    page.locator('#fullscreen').click()
    expect(page.locator('#screen:fullscreen')).to_be_visible()
    page.screenshot(path=f'/tmp/pokesim-fullscreen-{width}.png')
    well = page.locator('#screen').bounding_box()
    assert well['width'] == pytest.approx(width, abs=1)
    assert well['height'] == pytest.approx(height, abs=1)
    picture = page.locator('#screen img').bounding_box()
    assert picture['width'] <= width
    assert picture['height'] <= height
    assert page.locator('#screen img').evaluate('(image) => getComputedStyle(image).objectFit') == 'contain'
    page.screenshot(path=f'/tmp/pokesim-fullscreen-{width}.png')
    page.evaluate('document.exitFullscreen()')
    expect(page.locator('#screen:fullscreen')).to_have_count(0)


# The test answers one download with a busy refusal.
@pytest.mark.expected_errors(*refused('/api/export-save', 409))
def test_download_save_and_busy_message(page, live_game, tmp_path):
    url, emu = live_game
    page.route('**/api/export-save', lambda route: route.fulfill(
        body=bytes(32768), content_type='application/octet-stream',
        headers={'Content-Disposition': 'attachment' + chr(59) + ' filename="Red.sav"'}))
    page.goto(url)
    with page.expect_download() as downloaded:
        page.get_by_role('button', name='Download .sav').click()
    download = downloaded.value
    assert download.suggested_filename == 'Red.sav'
    target = tmp_path / 'Red.sav'
    download.save_as(target)
    assert target.read_bytes() == bytes(32768)
    assert emu.commands == []
    page.unroute('**/api/export-save')
    page.route('**/api/export-save', lambda route: route.fulfill(
        status=409, json={'detail': 'Wait for the battle to finish.'}))
    page.get_by_role('button', name='Download .sav').click()
    expect(page.locator('#toast')).to_have_text('Wait for the battle to finish.')
    expect(page.get_by_role('button', name='Download .sav')).to_be_enabled()


def test_live_pause_resume_and_save_have_clear_actions(page, live_game):
    url, emu = live_game
    original = emu.status
    state = {'paused': False, 'manual_mode': False}
    emu.status = lambda: {**original(), **state}
    def command(name, value=None):
        emu.commands.append((name, value))
        if name == 'pause':
            state.update(paused=True, manual_mode=False)
        elif name == 'resume':
            state.update(paused=False, manual_mode=False)
    emu.command = command
    page.goto(url)
    # One play status, under the screen. No Live tag over it and no Running in the rail.
    status = page.locator('#control-mode')
    expect(status).to_have_text('AI is playing')
    expect(page.locator('#connection')).to_be_hidden()
    assert page.locator('#on-air-label, .on-air').count() == 0
    page.get_by_role('button', name='Pause', exact=True).click()
    expect(page.locator('#pause')).to_have_text('Resume')
    expect(status).to_have_text('Game paused')
    expect(page.locator('#connection')).to_be_hidden()
    page.get_by_role('button', name='Resume', exact=True).click()
    expect(page.locator('#pause')).to_have_text('Pause')
    assert emu.commands == [('pause', None), ('resume', None)]
    page.get_by_role('button', name='Save now', exact=True).click()
    expect(page.locator('#toast')).to_contain_text('Checkpoint save requested')
    assert emu.commands[-1] == ('save', None)


# The test refuses one speed change.
@pytest.mark.expected_errors(*refused('/api/control', 409))
def test_live_speed_changes_and_failed_updates(page, live_game):
    url, emu = live_game
    original = emu.status
    speed = [1]
    emu.status = lambda: {**original(), 'speed': speed[0]}
    def command(name, value=None):
        emu.commands.append((name, value))
        if name == 'speed':
            speed[0] = value
    emu.command = command
    page.goto(url)
    select = page.get_by_role('combobox', name='Simulation speed', exact=True)
    expect(select).to_have_value('1')
    # The speed key says what it sets in plain sight, not only in a tooltip.
    expect(page.locator('.live-speed-label')).to_be_visible()
    expect(page.locator('.live-speed-label')).to_have_text('Speed')
    select.select_option('4')
    expect(page.locator('#toast')).to_have_text('Simulation speed set to 4×.')
    assert emu.commands[-1] == ('speed', 4)
    select.select_option('0')
    expect(page.locator('#toast')).to_have_text('Simulation speed set to Max.')
    assert emu.commands[-1] == ('speed', 0)
    page.route('**/api/control', lambda route: route.fulfill(
        status=409, content_type='application/json', body='{"detail":"Adventure is busy"}'))
    select.select_option('16')
    expect(page.locator('#toast')).to_have_text('Adventure is busy')
    expect(select).to_have_value('0')
    expect(select).to_be_enabled()


def test_plan_action_reads_as_words_apart_from_the_tile_count(page, game):
    url, store, emu, eid = game
    original = emu.status
    emu.status = lambda: {**original(), 'strategy': {'objective': {'title': 'Train the team'}, 'visited_tiles': 31524,
                                                     'action': 'shortcut: choose_move', 'collection': {'version': 'red'}}}
    page.goto(url)
    expect(page.locator('.plan-meta')).to_have_text('Shortcut: choose move, 31,524 tiles explored')


TRAIN = {'key': 'train', 'label': 'Train a Pokemon', 'tier': 'filler', 'species': ['Pikachu', 'Farfetch’d'],
         'stops': [{'key': 'level:30', 'label': 'Until level 30'}]}


@pytest.mark.parametrize('width', [1280, 390])
def test_choose_next_row_is_labelled_and_even(page, live_game, width):
    url, emu = live_game
    page.set_viewport_size({'width': width, 'height': 900})
    page.route('**/api/goals', lambda route: route.fulfill(json={'goals': [
        {'key': 'hunt', 'label': 'Find Clefairy', 'tier': 'progress'}, TRAIN], 'pin': None}))
    page.goto(url)
    row = page.locator('#next-activity')
    goal = row.get_by_role('combobox', name='Goal')
    expect(goal).to_be_visible()
    expect(row.get_by_text('Train a Pokémon')).to_have_count(1)
    species = row.get_by_label('Pokémon', exact=True)
    expect(species).to_be_hidden()
    goal.select_option('train')
    # One searchable species field, with only the species this goal can reach, and the stop condition.
    expect(species).to_be_visible()
    expect(species).to_have_attribute('placeholder', 'Search Pokémon')
    assert page.locator('#next-activity-species-list option').evaluate_all('options => options.map(o => o.value)') == ['Pikachu', 'Farfetch’d']
    expect(row.get_by_role('combobox', name='Stop when')).to_be_visible()
    assert page.locator('#next-activity-kind').count() == 0
    for label in ('Find', 'Goal', 'Pokémon', 'Stop when'):
        expect(row.locator('.plan-pick-field .micro', has_text=label)).to_be_visible()
    # Every control in the row has one height and one face, buttons included.
    looks = page.locator('#next-activity select:visible, #next-activity input:visible, #next-activity button:visible').evaluate_all(
        'controls => controls.map(c => [Math.round(c.getBoundingClientRect().height), getComputedStyle(c).fontFamily, getComputedStyle(c).fontSize])')
    assert len(looks) == 5 and len({tuple(look) for look in looks}) == 1, looks
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1280, 320])
def test_a_waiting_pin_says_why_beside_its_label(page, live_game, width):
    url, emu = live_game
    shown = emu.status
    pin = {'key': 'hunt', 'label': 'Find Clefairy', 'started': False,
           'parked': 'no route found lately, so the planner tries again after the next badge'}
    emu.status = lambda: {**shown(), 'strategy': {**shown()['strategy'], 'pin': pin}}
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url)
    line = page.locator('#next-activity-status')
    expect(line).to_have_text(f'Next: Find Clefairy (waiting: {pin["parked"]})')
    expect(page.locator('#next-activity-cancel')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    # A pin with no reason, as every pin is until the server sends one, shows only its label.
    pin['parked'] = ''
    expect(line).to_have_text('Next: Find Clefairy', timeout=5000)
