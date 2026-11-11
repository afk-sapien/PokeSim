"""The first answer fills Stats in place: what sits below the first sections keeps its position.
The Trading check is in test_trading_tabs.py, which has the library the page talks to."""
import pytest

from test_flows import expect


# Desktop only: on a phone the overview's notes arrive with the answer and can wrap to two lines.
@pytest.mark.parametrize('width', [1280, 1024])
def test_the_first_stats_answer_leaves_the_page_where_it_was(page, game, width):
    held, released = [], []

    # Hold every data request, so the page shows only what it draws before an answer.
    def hold(route):
        if released:
            route.continue_()
        else:
            held.append(route)

    page.set_viewport_size({'width': width, 'height': 900})
    page.route('**/api/**', hold)
    page.goto(game[0] + '/stats')
    page.wait_for_timeout(300)
    below = page.locator('section[aria-labelledby="recent-heading"]')
    before = below.bounding_box()
    expect(page.locator('#milestone-list .milestone-row')).to_have_count(7)
    released.append(True)
    for route in held:
        route.continue_()
    expect(page.locator('#stats-held')).not_to_have_text('—')
    expect(page.locator('#milestone-list')).not_to_contain_text('—')
    page.wait_for_timeout(300)
    assert below.bounding_box()['y'] == before['y']
