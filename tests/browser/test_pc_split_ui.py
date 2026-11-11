"""A first PC visit draws the boxes at once. The PC values wait on the game and join a moment later."""
import re

from test_flows import expect


def test_the_boxes_draw_before_the_pc_values_arrive(page, game):
    url, _store, emu, _eid = game
    # FERN, the second boxed partner, is next in line for release.
    emu.pc_values = lambda: ({(0, 1): {'score': 40, 'text': 'Score 40', 'status': 'spare', 'reason': '',
                                       'next': 1, 'requested': None}}, False)
    held, released = [], []

    # Hold the full answer, the one that waits on the game, and let the quick one through.
    def hold(route):
        if released or 'values=0' in route.request.url:
            route.continue_()
        else:
            held.append(route)

    page.route(re.compile(r'/api/pokedex/status\?view=pc'), hold)
    page.goto(url + '/pc')
    expect(page.locator('#pc-total')).to_have_text('2 / 240')
    expect(page.locator('#pc-grid [data-mon]')).to_have_count(2)
    expect(page.locator('#pc-grid .pc-release-tag')).to_have_count(0)
    assert len(held) == 1
    released.append(True)
    for route in held:
        route.continue_()
    expect(page.locator('#pc-grid .pc-release-tag')).to_have_text('Next 1')
