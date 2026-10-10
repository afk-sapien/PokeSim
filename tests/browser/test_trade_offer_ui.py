"""Offering a Pokémon greys out every game that cannot take it, before its PC opens."""
import json
import re

import pytest

from pokesim.web.pages import render_game_page
from test_flows import expect

FROM = 'a' * 32
RED = 'b' * 32
BLUE = 'c' * 32
REASON = 'LEAF cannot go to a Red, Blue or Yellow game. Chikorita did not exist in Gen I'


@pytest.mark.parametrize('width', [1280, 390])
def test_offer_picker_disables_games_that_cannot_take_the_chosen_pokemon(page, game, width):
    url, _, _, _ = game
    # The real owner PC page, with the synthetic adventure API behind its game routes.
    html = render_game_page('pc.html', base_path=f'/games/{FROM}', adventure_id=FROM, adventure_name='Crystal')
    page.route(f'**/games/{FROM}/**', lambda route: route.continue_(url=route.request.url.replace(f'/games/{FROM}/', '/')))
    page.route(re.compile(r'/managed-pc(\?|$)'), lambda route: route.fulfill(body=html, content_type='text/html'))
    asked = []

    def targets(route):
        asked.append(route.request.url)
        chosen = 'from_key=' in route.request.url
        rows = [{'id': RED, 'name': 'Second Red', 'version': 'red', 'generation': 1,
                 'available': not chosen, 'reason': REASON if chosen else ''},
                {'id': BLUE, 'name': 'Busy Blue', 'version': 'blue', 'generation': 1, 'available': False,
                 'reason': 'Busy finishing a trade with Second Red — available again once it finishes'}]
        route.fulfill(body=json.dumps({'adventures': rows, 'viewer_only': False}), content_type='application/json')
    page.route(re.compile(r'/api/v1/interactions/trade-offers/targets(\?|$)'), targets)
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(url + '/managed-pc?box=party')
    page.locator('.pc-mon').first.click()
    page.locator('#pc-trade-action').get_by_role('button', name='Offer trade').click()
    dialog = page.locator('#offer-dialog')
    red = dialog.locator(f'[data-offer-target="{RED}"]')
    expect(red).to_be_disabled()
    expect(red).to_contain_text(REASON)
    busy = dialog.locator(f'[data-offer-target="{BLUE}"]')
    expect(busy).to_be_disabled()
    expect(busy).to_contain_text('Busy finishing a trade with Second Red')
    assert any('from_key=' in address for address in asked)
    # A forced click on the greyed game still does not open its PC.
    red.click(force=True)
    page.wait_for_timeout(200)
    expect(dialog).to_be_visible()
    assert RED not in page.url
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
