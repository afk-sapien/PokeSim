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


def test_no_page_scrolls_sideways_on_a_phone(page, game):
    url, store, emu, eid = game
    portraits(store)
    tracker = StatisticsTracker(store)
    tracker.observe(emu.snapshot, now=time.time())
    tracker.flush(now=time.time())
    page.set_viewport_size({'width': 390, 'height': 844})
    for path, ready in [('/', '#take-control'), ('/journal', '#events'), ('/journal/stats', '#statistics-charts'),
                        ('/pokedex', '.dex-card'), ('/pc', '#pc-grid'), ('/trading', '#trade-connection-note'),
                        (f'/events/{eid}', '#rewind')]:
        page.goto(url + path)
        expect(page.locator(ready).first).to_be_attached()
        page.wait_for_timeout(400)
        wide = page.evaluate('''() => [...document.querySelectorAll('body *')]
          .filter(el => el.getBoundingClientRect().right > innerWidth + 1 && el.offsetParent
                  && !el.closest('[class*="scroll"], .rail-nav, nav'))
          .slice(0, 3).map(el => el.tagName + '.' + el.className)''')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (path, wide)
    # The adventure tabs scroll inside their strip and the current one is in view.
    page.goto(url + '/pokedex')
    current = page.locator('[aria-current="page"]').first
    expect(current).to_be_in_viewport()


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
    # Five keys share one row. The standalone page's sixth (Download .sav) makes it 3 x 2.
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


@pytest.mark.parametrize('width,height', [(360, 800), (390, 844), (640, 900), (768, 1024), (1024, 768),
                                          (1100, 900), (1280, 900), (1600, 900), (844, 390)])
def test_game_screen_scales_by_whole_pixels(page, game, width, height):
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(game[0])
    expect(page.locator('#screen')).to_be_visible()
    box = page.evaluate('''() => {
      const well = document.querySelector('#screen').getBoundingClientRect()
      const picture = document.querySelector('#screen img').getBoundingClientRect()
      const rail = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--rail-h')) || 0
      return {well: well.width, width: picture.width, height: picture.height, rail}
    }''')
    assert box['height'] == pytest.approx(box['width'] * 144 / 160, abs=1)
    if box['well'] >= 320:
        # From 2x up the picture is a whole multiple of 160x144, never a blurry 3.5x.
        assert box['width'] % 160 == pytest.approx(0, abs=0.5), box
    else:
        assert box['width'] == pytest.approx(box['well'], abs=1)
    if height < 500:
        # A phone on its side pins only the tab strip and the whole picture fits under it.
        assert box['rail'] <= 60
        assert box['height'] + box['rail'] <= height
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [641, 768, 1024, 1099])
def test_pc_summary_readings_share_one_row(page, game, width):
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(game[0] + '/pc')
    expect(page.locator('#pc-total')).to_be_visible()
    tops = page.locator('.pc-summary .stat').evaluate_all('(stats) => stats.map(stat => Math.round(stat.getBoundingClientRect().top))')
    assert len(tops) == 2 and tops[0] == tops[1]

