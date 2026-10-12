"""The owner's Copy view link is a small key in the top rail, not a row under the game controls."""
import re

import pytest

from pokesim.web.pages import GEN2_CONTEXT, render_game_page
from test_flows import expect

ID = 'd' * 32


def managed_live_page(page, url):
    live = render_game_page('index.html', base_path=f'/games/{ID}', adventure_id=ID, adventure_name='Crystal', **GEN2_CONTEXT)
    page.route(f'**/games/{ID}/**', lambda route: route.continue_(url=route.request.url.replace(f'/games/{ID}/', '/')))
    page.route(re.compile(rf'/games/{ID}/?(\?|$)'), lambda route: route.fulfill(body=live, content_type='text/html'))
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url)
    page.goto(f'{url}/games/{ID}/')


@pytest.mark.parametrize('width', [1280, 390])
def test_view_link_sits_in_the_rail(page, game, width):
    url = game[0]
    page.set_viewport_size({'width': width, 'height': 844})
    managed_live_page(page, url)
    key = page.locator('.rail #copy-view-link')
    expect(key).to_be_visible()
    expect(key).to_have_attribute('aria-label', 'Copy view link')
    assert page.locator('.deck #copy-view-link').count() == 0
    # The controls deck stays one row of game keys, with nothing hanging under it.
    expect(page.locator('.deck.controls')).not_to_contain_text('view link', ignore_case=True)
    box, rail = key.bounding_box(), page.locator('.rail').bounding_box()
    assert rail['y'] <= box['y'] and box['y'] + box['height'] <= rail['y'] + rail['height']
    assert box['width'] <= 40 and box['height'] <= 40
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    # No tab label is clipped. On a phone the tabs scroll sideways inside their own strip instead.
    nav = page.locator('.rail nav:not(.breadcrumb)')
    assert nav.evaluate('nav => [...nav.querySelectorAll("a")].every(tab => tab.scrollWidth <= tab.clientWidth + 1)')
    assert nav.evaluate('nav => nav.scrollWidth <= nav.clientWidth || getComputedStyle(nav).overflowX === "auto"')

    key.click()
    expect(key.locator('.rail-key-note')).to_have_text('Copied')
    expect(key).to_have_attribute('data-copied', '')
    assert page.evaluate('navigator.clipboard.readText()') == f'{url}/view/{ID}/'
    expect(key.locator('.rail-key-note')).to_have_text('', timeout=4000)
