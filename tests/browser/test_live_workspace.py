"""Keep the live columns aligned and partner inspection separate from game input."""
from dataclasses import replace

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
    if width > 850:
        assert abs(game_box['y'] - team_box['y']) < 1
        assert abs(game_box['height'] - team_box['height']) < 1
    # The trainer, badge and totals summary sits above the game and party panels.
    assert trainer_box['y'] + trainer_box['height'] <= min(game_box['y'], team_box['y'])
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')

    team_height = page.locator('#team').bounding_box()['height']
    partner = page.get_by_role('button', name='View PARTNER 1 moves and stats')
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
