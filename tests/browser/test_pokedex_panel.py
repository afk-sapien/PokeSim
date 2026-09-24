"""The Pokédex on the Bench Instrument panel: no sideways scroll, whole-pixel
portraits, discrete stat meters, and a detail sheet that fits the screen."""
from PIL import Image
import pytest

from test_flows import expect


def portraits(store):
    folder = store.dir / 'sprites'
    folder.mkdir(parents=True, exist_ok=True)
    for dex in range(1, 13):
        # A 96px pack: 56px of art centred on the canvas, like the common packs.
        pack = Image.new('RGBA', (96, 96))
        pack.paste(Image.new('RGBA', (40, 48), (40, 120, 60, 255)), (28, 24))
        pack.save(folder / f'{dex}.png')


@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_pokedex_panel_fits_and_scales_portraits(page, game, width):
    url, store, _, _ = game
    portraits(store)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/pokedex')
    expect(page.locator('.dex-card')).to_have_count(151)
    page.wait_for_function("document.querySelector('.dex-card[data-dex=\"1\"] .plate img').style.width !== ''")
    # A padded pack is scaled as the 56px picture inside it, by a whole number.
    scale = page.evaluate("(() => { const i = document.querySelector('.dex-card[data-dex=\"1\"] .plate img'); return parseFloat(i.style.width) / i.naturalWidth })()")
    assert scale == 2
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    expect(page.locator('#sum-owned .unit')).to_have_text('/151')

    page.locator('.dex-card[data-dex="1"]').click()
    expect(page.locator('#detail')).to_be_visible()
    expect(page.locator('#close-detail')).to_be_focused()
    rows = page.locator('#detail-body .stat-row')
    expect(rows.first.locator('.meter i')).to_have_count(19)
    starts = page.evaluate("[...document.querySelectorAll('#detail-body .stat-row .meter')].map(m => Math.round(m.getBoundingClientRect().left))")
    assert len(set(starts)) == 1
    hero = page.evaluate("(() => { const i = document.querySelector('.plate--hero img'); return parseFloat(i.style.width) / i.naturalWidth })()")
    assert hero == 3
    box = page.locator('#detail').bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width
    assert page.evaluate("document.querySelector('#detail').scrollWidth <= document.querySelector('#detail').clientWidth")
    page.keyboard.press('ArrowRight')
    expect(page.locator('#detail-name')).to_have_text('Ivysaur')
    page.keyboard.press('Escape')
    expect(page.locator('#detail')).to_be_hidden()
