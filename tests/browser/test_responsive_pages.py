"""Exercise intermediate window sizes as well as phone and desktop layouts."""
from dataclasses import replace
from pathlib import Path
import time

import pytest

from test_flows import expect
from test_pokedex_panel import portraits
from pokesim.statistics import StatisticsTracker


WIDTHS = [320, 390, 640, 641, 800, 860, 861, 1000, 1100, 1101, 1280, 1600]


@pytest.mark.parametrize('width', WIDTHS)
def test_pc_uses_available_width_in_both_views(page, game, width):
    url, store, emu, _ = game
    portraits(store)
    residents = tuple(replace(emu.snapshot.stored_details[0], position=i, nick=f'PARTNER{i:02}') for i in range(20))
    emu.snapshot = replace(emu.snapshot, stored_details=residents,
                           stored_pokemon=tuple((p.box, p.species, p.level, p.nick) for p in residents),
                           box_counts=(20,) + (0,) * 11)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/pc?scope=all')
    cards = page.locator('#pc-grid .pc-mon')
    expect(cards).to_have_count(21)
    grid = page.locator('#pc-grid').bounding_box()
    workspace = page.locator('#pc-workspace').bounding_box()
    assert grid['width'] == pytest.approx(workspace['width'], abs=1)
    boxes = cards.evaluate_all('(cards) => cards.map(card => card.getBoundingClientRect().toJSON())')
    first_row = [box for box in boxes if abs(box['y'] - boxes[0]['y']) < 1]
    # A readable horizontal card needs 280 pixels, with an 8 pixel gap.
    expected_columns = max(1, int((grid['width'] + 8) // 288))
    assert len(first_row) == expected_columns
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert cards.evaluate_all('(cards) => cards.every(card => card.scrollWidth <= card.clientWidth)')
    folder = Path('/tmp/pokesim-responsive-ui')
    folder.mkdir(exist_ok=True)
    page.screenshot(path=str(folder / f'pc-all-{width}.png'))
    cards.first.click()
    expect(page.locator('#pc-detail')).to_be_visible()
    assert page.locator('#pc-detail').evaluate('(node) => node.scrollWidth <= node.clientWidth')
    page.keyboard.press('Escape')
    page.goto(url + '/pc?scope=box&box=1')
    expect(cards).to_have_count(20)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert cards.evaluate_all('(cards) => cards.every(card => card.scrollWidth <= card.clientWidth)')
    page.screenshot(path=str(folder / f'pc-box-{width}.png'))
    page.get_by_role('button', name='All Pokémon', exact=True).click()
    expect(cards).to_have_count(21)
    assert page.locator('#pc-grid').bounding_box()['width'] == pytest.approx(workspace['width'], abs=1)


@pytest.mark.parametrize('width', [320, 640, 800, 1000, 1100, 1280, 1600])
def test_game_pages_fit_intermediate_windows(page, game, width):
    url, store, emu, _ = game
    portraits(store)
    tracker = StatisticsTracker(store)
    tracker.observe(emu.snapshot, now=time.time())
    tracker.flush(now=time.time())
    page.set_viewport_size({'width': width, 'height': 900})
    for path, ready in [('/pokedex', '.dex-card'), ('/journal', '#events'),
                        ('/journal/stats', '#statistics-charts .progress-row'),
                        ('/trading', '#trade-connection-note')]:
        page.goto(url + path)
        expect(page.locator(ready).first).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (path, width)
        folder = Path('/tmp/pokesim-responsive-ui')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'{path.strip("/").replace("/", "-")}-{width}.png'))


@pytest.mark.parametrize('width', [1280, 1024, 800, 768])
def test_live_controls_sit_on_one_row(page, game, width):
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(game[0])
    expect(page.locator('#take-control')).to_be_visible()
    boxes = page.evaluate('''() => {
      const deck = document.querySelector('.deck.controls')
      const rows = [...deck.children].filter(el => el.offsetParent)
        .map(el => el.getBoundingClientRect())
      const edge = deck.getBoundingClientRect()
      return {rows, left: edge.left, right: edge.right, wide: deck.scrollWidth > deck.clientWidth}
    }''')
    assert len(boxes['rows']) >= 5
    assert max(box['top'] for box in boxes['rows']) - min(box['top'] for box in boxes['rows']) <= 2
    assert all(box['left'] >= boxes['left'] - 1 and box['right'] <= boxes['right'] + 1 for box in boxes['rows'])
    assert not boxes['wide']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [320, 390, 480, 640, 700])
def test_live_controls_are_an_even_touch_grid_on_phones(page, game, width):
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(game[0])
    expect(page.locator('#take-control')).to_be_visible()
    boxes = page.evaluate('''() => [...document.querySelectorAll('.deck.controls > *')]
      .filter(el => el.offsetParent).map(el => el.getBoundingClientRect().toJSON())''')
    assert all(box['height'] >= 44 for box in boxes)
    assert len({round(box['left']) for box in boxes if box['width'] < boxes[0]['width'] - 20}) <= 2
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not page.evaluate("(() => { const d = document.querySelector('.deck.controls'); return d.scrollWidth > d.clientWidth })()")
