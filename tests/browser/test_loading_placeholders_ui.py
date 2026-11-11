"""Until the first answer arrives the counters show a dash, so nothing reads as a real zero."""
import pytest

from test_flows import expect

PAGES = {
    '': {'#badge-count': '— / 8', '#dex-count': '—/151', '#areas': '—', '#league-wins': '—', '#money': '₽—',
         '#playtime': '—:—'},
    '/pc': {'#pc-total': '—'},
    '/pokedex': {'#sum-seen': '—/151', '#sum-owned': '—/151', '#sum-shiny': '—/151'},
    '/stats': {'#stats-playtime': '—', '#stats-held': '—', '#stats-catch-pace': '—'},
}


@pytest.mark.parametrize('path', PAGES)
def test_counters_show_a_dash_until_the_data_arrives(page, game, path):
    url = game[0]
    held, released = [], []

    # Hold every data request, so the page shows only what it draws before an answer.
    def hold(route):
        if released:
            route.continue_()
        else:
            held.append(route)

    page.route('**/api/**', hold)
    page.goto(url + path, wait_until='domcontentloaded')
    for selector, text in PAGES[path].items():
        expect(page.locator(selector)).to_have_text(text)
    page.wait_for_timeout(300)
    for selector, text in PAGES[path].items():
        expect(page.locator(selector)).to_have_text(text)
    released.append(True)
    for route in held:
        route.continue_()
    # The real answers then replace the dashes.
    selector, text = next(iter(PAGES[path].items()))
    expect(page.locator(selector)).not_to_have_text(text)
