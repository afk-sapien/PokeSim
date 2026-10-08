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


def _live_keys(page):
    return page.evaluate('''() => {
      const deck = document.querySelector('.deck.controls')
      const edge = deck.getBoundingClientRect()
      const keys = [...deck.querySelectorAll('.key, .live-speed select')].filter(el => el.offsetParent)
        .map(el => {
          const box = el.getBoundingClientRect()
          let clipped = el.scrollWidth > el.clientWidth + 1
          if (el.tagName !== 'SELECT') {
            const range = document.createRange()
            range.selectNodeContents(el)
            clipped = clipped || range.getClientRects().length > 1
          }
          return {id: el.id, top: box.top, left: box.left, right: box.right,
                  width: box.width, height: box.height, clipped}
        })
      return {keys, left: edge.left, right: edge.right, wide: deck.scrollWidth > deck.clientWidth}
    }''')


@pytest.mark.parametrize('width', [1024, 1280, 1920])
def test_live_controls_are_equal_keys_on_desktop(page, game, width):
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(game[0])
    expect(page.locator('#take-control')).to_be_visible()
    deck = _live_keys(page)
    keys = deck['keys']
    rows = {round(k['top']) for k in keys}
    # Five keys share one row; the standalone page's sixth (Download .sav) makes it 3 x 2.
    assert len(rows) == (1 if len(keys) == 5 else 2)
    assert max(k['width'] for k in keys) - min(k['width'] for k in keys) <= 1
    assert not any(k['clipped'] for k in keys)


@pytest.mark.parametrize('width', [320, 390, 480, 640, 700, 768, 820])
def test_live_controls_are_an_even_grid_that_never_clips(page, game, width):
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(game[0])
    expect(page.locator('#take-control')).to_be_visible()
    for _ in range(2):
        deck = _live_keys(page)
        keys = deck['keys']
        assert {round(k['height']) for k in keys} == {44}
        assert not any(k['clipped'] for k in keys), [k['id'] for k in keys if k['clipped']]
        assert all(k['left'] >= deck['left'] - 1 and k['right'] <= deck['right'] + 1 for k in keys)
        rows = {}
        for k in keys:
            rows.setdefault(round(k['top']), []).append(k)
        # Every row fills the same span: no ragged or offset rows.
        left, right = min(k['left'] for k in keys), max(k['right'] for k in keys)
        assert all(abs(min(k['left'] for k in row) - left) <= 1 and abs(max(k['right'] for k in row) - right) <= 1
                   for row in rows.values())
        assert not deck['wide']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        # Then the other runtime labels each key can show.
        page.evaluate("""() => {
          document.querySelector('#take-control').textContent = 'Let AI play'
          document.querySelector('#pause').textContent = 'Resume'
          document.querySelector('#sound').textContent = 'Sound: On'
        }""")
