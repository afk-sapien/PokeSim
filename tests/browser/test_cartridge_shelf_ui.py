"""The Settings cartridge shelf and the game picker in New adventure, in real Chromium."""
import hashlib
import os
from pathlib import Path

import pytest

from pokesim import cartridges
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from conftest import serve


JOHTO = {'gold', 'silver', 'crystal'}


def synthetic(version):
    """A made-up cartridge image that only stands in for a real one inside these tests."""
    return f'synthetic {version} cartridge for browser tests'.encode() * 64


@pytest.fixture
def library(tmp_path, monkeypatch):
    fake = tuple(cartridges.Cartridge(version, 2 if version in JOHTO else 1, hashlib.sha1(synthetic(version)).hexdigest(),
                                      f'Pokémon {version.capitalize()}',
                                      cartridges.JOHTO_STARTERS if version in JOHTO else cartridges.KANTO_STARTERS)
                 for version in ('red', 'blue', 'gold', 'silver', 'crystal'))
    monkeypatch.setattr(cartridges, 'CARTRIDGES', fake)
    managers = []

    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        monkeypatch.setattr(manager.assets, 'install_portraits_quietly', lambda raw: 0)
        managers.append(manager)
        return create_app(manager)
    with serve(factory) as url:
        yield url, managers[0]


def shot(page, name):
    folder = Path(os.environ.get('POKESIM_SHOTS_DIR') or '/tmp/pokesim-cartridge-shelf')
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f'{name}.png'), full_page=True)


def no_sideways_scroll(page):
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'page scrolls sideways'


WIDTHS = [320, 390, 768, 1024, 1280, 1920]

# Groups visible elements by their top edge, so each group is one row of the grid.
ROWS = """(selector) => {
  const rows = {}
  for (const node of document.querySelectorAll(selector)) {
    const box = node.getBoundingClientRect()
    if (!box.width) continue
    const top = Math.round(node.closest('.cartridge-slot, .game-card').getBoundingClientRect().top)
    ;(rows[top] = rows[top] || []).push({top: Math.round(box.top * 10) / 10, height: Math.round(box.height * 10) / 10,
      clipped: node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1})
  }
  return Object.values(rows)
}"""


def assert_even_keys(page):
    rows = page.evaluate(ROWS, '.cartridge-actions > :first-child')
    assert rows and sum(map(len, rows)) == 6
    for row in rows:
        assert len({item['top'] for item in row}) == 1, row
    keys = [item for row in page.evaluate(ROWS, '.cartridge-actions .key') for item in row]
    assert len({item['height'] for item in keys}) == 1, keys
    assert not any(item['clipped'] for item in keys), keys


def rom_file(version, name=None):
    return {'name': name or f'{version}.gb', 'mimeType': 'application/octet-stream', 'buffer': synthetic(version)}


def upload(page, version, payload):
    with page.expect_file_chooser() as chooser:
        page.locator(f'#cartridge-{version} [data-cartridge-upload]').click()
    chooser.value.set_files(payload)


@pytest.mark.parametrize('width', WIDTHS)
def test_shelf_places_uploads_by_hash_and_rejects_unknown_files(page, library, width):
    from playwright.sync_api import expect
    url, manager = library
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(f'{url}/settings#cartridges')
    grid = page.locator('#cartridge-grid')
    expect(grid.locator('.cartridge-slot')).to_have_count(6)
    names = grid.locator('.cartridge-name').all_inner_texts()
    assert [name.lower() for name in names] == [f'pokémon {game}' for game in ('red', 'blue', 'yellow', 'gold', 'silver', 'crystal')]
    expect(page.locator('#cartridge-yellow')).to_contain_text('Coming in this release')
    no_sideways_scroll(page)
    if width == 390:
        shot(page, 'settings-empty-390')

    upload(page, 'red', rom_file('red'))
    red = page.locator('#cartridge-red')
    expect(red).to_have_attribute('data-state', 'installed')
    expect(red).to_contain_text('Pokémon Red added')
    expect(red).to_contain_text(hashlib.sha1(synthetic('red')).hexdigest()[:8])
    expect(red).to_contain_text('KiB')

    upload(page, 'gold', rom_file('silver', 'mystery.gbc'))
    silver = page.locator('#cartridge-silver')
    expect(silver).to_have_attribute('data-state', 'installed')
    expect(silver).to_contain_text('not Pokémon Gold, so it went into the Silver slot')
    expect(page.locator('#cartridge-gold')).to_have_attribute('data-state', 'empty')
    expect(page.locator('#cartridge-gold')).to_contain_text('It went into the Silver slot')

    upload(page, 'crystal', {'name': 'notes.gb', 'mimeType': 'application/octet-stream', 'buffer': b'not a game at all' * 40})
    crystal = page.locator('#cartridge-crystal')
    expect(crystal.locator('.cartridge-feedback.is-error')).to_contain_text('This file is not a game PokeSim can play')
    expect(crystal).to_contain_text('Red, Blue, Gold, Silver or Crystal')
    expect(crystal).to_have_attribute('data-state', 'empty')
    expect(page.locator('#notice')).to_be_hidden()
    assert_even_keys(page)
    assert sorted(row['version'] for row in manager.registry.roms()) == ['red', 'silver']
    no_sideways_scroll(page)
    shot(page, f'settings-shelf-{width}')


def test_drop_onto_any_slot_lands_in_the_right_one(page, library):
    from playwright.sync_api import expect
    url, manager = library
    page.set_viewport_size({'width': 1280, 'height': 900})
    page.goto(f'{url}/settings')
    expect(page.locator('#cartridge-red')).to_have_attribute('data-state', 'empty')
    handle = page.evaluate_handle("""bytes => {
      const data = new DataTransfer()
      data.items.add(new File([new Uint8Array(bytes)], 'crystal.gbc'))
      return data
    }""", list(synthetic('crystal')))
    page.locator('#cartridge-red').dispatch_event('dragover', {'dataTransfer': handle})
    expect(page.locator('#cartridge-red')).to_have_class('cartridge-slot is-dragging')
    page.locator('#cartridge-red').dispatch_event('drop', {'dataTransfer': handle})
    expect(page.locator('#cartridge-crystal')).to_have_attribute('data-state', 'installed')
    expect(page.locator('#cartridge-red')).to_have_attribute('data-state', 'empty')
    assert [row['version'] for row in manager.registry.roms()] == ['crystal']


@pytest.mark.parametrize('width', WIDTHS)
def test_new_adventure_with_no_one_and_many_cartridges(page, library, width):
    from playwright.sync_api import expect
    url, manager = library
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url)
    expect(page.locator('#empty-needs-cartridge')).to_be_visible()
    expect(page.locator('#empty-needs-cartridge')).to_contain_text('Add a game cartridge first')
    no_sideways_scroll(page)
    shot(page, f'library-none-{width}')
    page.get_by_role('button', name='+ New adventure', exact=True).click()
    dialog = page.get_by_role('dialog', name='New adventure')
    expect(dialog.locator('#create-needs-cartridge')).to_be_visible()
    expect(dialog.locator('#create-needs-cartridge')).to_contain_text('Add a game cartridge first')
    expect(dialog.get_by_role('button', name='Create adventure', exact=True)).to_be_hidden()
    assert dialog.evaluate('node => node.scrollWidth <= node.clientWidth')
    shot(page, f'create-none-{width}')
    dialog.locator('#create-add-cartridge').click()
    page.wait_for_url('**/settings#cartridges')
    expect(page.locator('#cartridge-red')).to_be_visible()

    manager.assets.add_cartridge(synthetic('gold'))
    page.goto(url)
    expect(page.locator('#empty-ready')).to_be_visible()
    page.get_by_role('button', name='+ New adventure', exact=True).click()
    expect(dialog).to_be_visible()
    gold = dialog.get_by_role('radio', name='Pokémon Gold')
    expect(gold).to_be_checked()
    expect(dialog.locator('.game-card.is-missing')).to_have_count(5)
    expect(dialog.locator('.game-card[data-version="red"] a')).to_have_attribute('href', '/settings#cartridge-red')
    assert dialog.locator('#starter option').all_inner_texts() == ['Surprise me', 'Chikorita', 'Cyndaquil', 'Totodile']
    assert dialog.evaluate('node => node.scrollWidth <= node.clientWidth')
    shot(page, f'create-one-{width}')
    dialog.get_by_label('Start this adventure now', exact=True).uncheck()
    dialog.get_by_role('button', name='Create adventure', exact=True).click()
    expect(dialog).not_to_be_visible()
    first, = manager.registry.adventures()
    assert first['rom_id'] == hashlib.sha256(synthetic('gold')).hexdigest()

    manager.assets.add_cartridge(synthetic('blue'))
    manager.assets.add_cartridge(synthetic('crystal'))
    page.get_by_role('button', name='+ New adventure', exact=True).click()
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role('radio')).to_have_count(3)
    for name in ('Pokémon Blue', 'Pokémon Gold', 'Pokémon Crystal'):
        expect(dialog.get_by_role('radio', name=name)).not_to_be_checked()
    dialog.get_by_label('Adventure name', exact=True).fill('Kanto again')
    dialog.get_by_label('Start this adventure now', exact=True).uncheck()
    dialog.get_by_role('button', name='Create adventure', exact=True).click()
    expect(dialog.locator('.dialog-feedback')).to_contain_text('Choose the game')
    dialog.locator('.game-card[data-version="blue"]').click()
    expect(dialog.get_by_role('radio', name='Pokémon Blue')).to_be_checked()
    assert dialog.locator('#starter option').all_inner_texts() == ['Surprise me', 'Bulbasaur', 'Charmander', 'Squirtle']
    dialog.locator('#starter').select_option('squirtle')
    heights = {card.bounding_box()['height'] for card in dialog.locator('.game-card').all()}
    assert len(heights) == 1, heights
    assert dialog.evaluate('node => node.scrollWidth <= node.clientWidth')
    shot(page, f'create-many-{width}')
    dialog.get_by_role('button', name='Create adventure', exact=True).click()
    expect(dialog).not_to_be_visible()
    second = next(row for row in manager.registry.adventures() if row['name'] == 'Kanto again')
    assert second['rom_id'] == hashlib.sha256(synthetic('blue')).hexdigest()
    assert second['settings']['starter'] == 'squirtle'
    no_sideways_scroll(page)


def test_remove_is_confirmed_and_blocked_while_an_adventure_uses_it(page, library):
    from playwright.sync_api import expect
    url, manager = library
    red = manager.assets.add_cartridge(synthetic('red'))['rom']
    manager.assets.add_cartridge(synthetic('blue'))
    manager.registry.create('Pallet run', red['id'], {'starter': 'random'}, identifier())
    page.set_viewport_size({'width': 390, 'height': 900})
    page.goto(f'{url}/settings')
    page.locator('#cartridge-red [data-cartridge-remove]').click()
    dialog = page.locator('#cartridge-remove-dialog')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('Pokémon Red is in use')
    expect(dialog).to_contain_text('Pallet run')
    expect(dialog.locator('#cartridge-remove-confirm')).to_be_disabled()
    shot(page, 'remove-blocked-390')
    dialog.get_by_role('button', name='Keep cartridge').click()
    expect(page.locator('#cartridge-red')).to_have_attribute('data-state', 'installed')

    page.locator('#cartridge-blue [data-cartridge-remove]').click()
    expect(dialog).to_contain_text('Remove Pokémon Blue?')
    dialog.locator('#cartridge-remove-confirm').click()
    expect(dialog).not_to_be_visible()
    expect(page.locator('#cartridge-blue')).to_have_attribute('data-state', 'empty')
    assert [row['version'] for row in manager.registry.roms()] == ['red']
