"""A reload paints the PC and Pokédex as last seen at once, then swaps in fresh data."""
import re

from test_flows import expect

STATUS = re.compile(r'/api/pokedex/status(\?|$)')
REFERENCE = re.compile(r'/api/pokedex(\?|$)')


def saved(page, name):
    page.wait_for_function(f"PokeSim.recall('{name}').then(Boolean)")


def hold(page, pattern):
    """Keep matching requests waiting until the test lets them through."""
    held = []
    page.route(pattern, lambda route: held.append(route))
    return held


def test_reloaded_pc_paints_the_saved_copy_then_refreshes(page, game):
    url, _, _, _ = game
    page.goto(url + '/pc?box=party')
    expect(page.locator('#status')).to_have_text('Running')
    first = page.locator('#pc-grid .pc-mon').first.get_attribute('aria-label')
    saved(page, 'pc')

    held = hold(page, STATUS)
    page.goto(url + '/pc?box=party')
    # The saved PC shows while the server has not answered yet, marked as updating.
    expect(page.locator('#pc-grid .pc-mon').first).to_have_attribute('aria-label', first)
    expect(page.locator('#status')).to_have_text('Updating…')
    assert held
    # Saved data is for looking only: its detail offers no Trade… key.
    page.locator('#pc-grid .pc-mon').first.click()
    expect(page.locator('#pc-detail')).to_be_visible()
    expect(page.locator('#pc-trade-action .pc-trade-link')).to_have_count(0)
    page.locator('#pc-close').click()

    for route in held:
        route.fulfill(json={'started': True, 'generation': 1, 'version': 'red', 'party': [
            {'dex': 25, 'species': 84, 'name': 'Pikachu', 'nick': 'FRESH', 'level': 9, 'slot': 1,
             'type_names': ['Electric']}], 'storage': {'active_box': 1, 'box_counts': [0] * 12, 'pokemon': []}})
    page.unroute(STATUS)
    expect(page.locator('#status')).to_have_text('Running')
    expect(page.locator('#pc-grid .pc-mon')).to_have_count(1)
    expect(page.locator('#pc-grid .pc-name')).to_have_text('FRESH')


def test_unreadable_saved_copy_is_ignored(page, game):
    url, _, _, _ = game
    page.add_init_script('Object.defineProperty(window, "indexedDB", {get() { throw new Error("blocked") }})')
    page.goto(url + '/pc?box=party')
    expect(page.locator('#status')).to_have_text('Running')
    expect(page.locator('#pc-grid .pc-mon').first).to_be_visible()


def test_reloaded_pokedex_paints_the_saved_copy_then_refreshes(page, game):
    url, _, _, _ = game
    page.goto(url + '/pokedex')
    expect(page.locator('#status')).to_have_text('Running')
    expect(page.locator('.dex-card[data-dex="151"]')).to_have_count(1)
    saved(page, 'dex-reference')
    # The status is saved as the page is left.
    page.evaluate('''() => {
        Object.defineProperty(document, 'hidden', {configurable: true, get: () => true})
        document.dispatchEvent(new Event('visibilitychange'))
    }''')
    saved(page, 'dex-status')

    held = hold(page, STATUS)
    page.route(REFERENCE, lambda route: held.append(route))
    page.goto(url + '/pokedex')
    expect(page.locator('#status')).to_have_text('Updating…')
    expect(page.locator('.dex-card[data-dex="1"]')).to_have_count(1)
    for route in held:
        route.continue_()
    page.unroute(STATUS)
    page.unroute(REFERENCE)
    expect(page.locator('#status')).to_have_text('Running')
