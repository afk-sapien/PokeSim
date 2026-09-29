"""Keep the live columns aligned and partner inspection separate from game input."""
from dataclasses import replace
import re

import pytest

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


@pytest.mark.parametrize('width', [1280, 900, 390, 320])
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
    partner = page.get_by_role('button', name='View PARTNER 1 battle stats')
    partner.click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.keyboard.press('ArrowUp')
    page.keyboard.press('z')
    assert emu.commands == []
    emu.snapshot = replace(emu.snapshot, party=(replace(emu.snapshot.party[0], hp=12), *emu.snapshot.party[1:]))
    expect(page.locator('.partner-detail-head')).to_contain_text('12 / 30 HP')
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
