"""Portraits decoded from the owner's own cartridge.

The pixel-exact check needs a ROM and a pret/pokered checkout, so it is skipped where
either is missing. Everything else runs anywhere.
"""
import os
import zlib
from pathlib import Path

import pytest

from pokesim.sprites import MEW_DEX, MEW_INTERNAL, _png, extract, front_sprite, sprite_bank

ROM = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb'))
REFERENCE = Path(os.environ.get('POKERED_REFERENCE', '.reference/pokered'))
ALIAS = {29: 'nidoranf', 32: 'nidoranm', 83: 'farfetchd', 122: 'mr.mime'}


def test_pictures_live_in_the_bank_their_internal_index_selects():
    assert sprite_bank(MEW_INTERNAL) == 0x01, 'Mew was slotted in on its own'
    assert sprite_bank(0x1E) == 0x9
    assert sprite_bank(0x1F) == 0xA
    assert sprite_bank(0x49) == 0xA
    assert sprite_bank(0x4A) == 0xB
    assert sprite_bank(0x73) == 0xB
    assert sprite_bank(0x74) == 0xC
    assert sprite_bank(0x98) == 0xC
    assert sprite_bank(0x99) == 0xD


def test_the_lightest_shade_is_written_transparent():
    """One portrait has to sit on a light panel and a dark one, so it supplies no ground."""
    png = _png([[0, 1], [2, 3]])
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    width = int.from_bytes(png[16:20], 'big')
    height = int.from_bytes(png[20:24], 'big')
    assert (width, height) == (2, 2)
    assert png[24] == 8 and png[25] == 6, '8-bit RGBA'

    start = png.index(b'IDAT') + 4
    length = int.from_bytes(png[start - 8:start - 4], 'big')
    raw = zlib.decompress(png[start:start + length])
    assert raw[0] == 0 and raw[1:5] == bytes((255, 255, 255, 0)), 'shade 0 is transparent'
    assert raw[5:9][3] == 255, 'every darker shade is opaque'


@pytest.mark.skipif(not ROM.exists(), reason='no ROM')
def test_every_portrait_decodes_to_a_plausible_picture():
    from pokesim.strategy_data import SPECIES

    portraits = extract(ROM.read_bytes(), SPECIES)
    assert len(portraits) == 151
    for dex, png in portraits.items():
        assert png[:8] == b'\x89PNG\r\n\x1a\n', dex
        side = int.from_bytes(png[16:20], 'big')
        assert 8 <= side <= 56 and side % 8 == 0, (dex, side)


@pytest.mark.skipif(not ROM.exists(), reason='no ROM')
def test_mew_is_read_from_its_own_header_outside_the_table():
    from pokesim.strategy_data import SPECIES

    by_dex = {entry['dex']: internal for internal, entry in SPECIES.items() if entry.get('dex')}
    pixels, width, height = front_sprite(ROM.read_bytes(), MEW_DEX, by_dex[MEW_DEX])
    assert (width, height) == (5, 5)
    assert any(value for row in pixels for value in row), 'Mew decoded to an empty picture'


@pytest.mark.skipif(not ROM.exists() or not (REFERENCE / 'gfx/pokemon/front').is_dir(),
                    reason='needs a ROM and a pret/pokered checkout')
def test_every_portrait_matches_the_reference_art_pixel_for_pixel():
    from PIL import Image

    from pokesim.strategy_data import SPECIES

    rom = ROM.read_bytes()
    by_dex = {entry['dex']: internal for internal, entry in SPECIES.items() if entry.get('dex')}
    names = {entry['dex']: entry['name'].lower().replace(' ', '').replace('.', '')
             .replace("'", '').replace('-', '') for entry in SPECIES.values() if entry.get('dex')}

    checked = 0
    for dex in range(1, 152):
        reference = REFERENCE / 'gfx/pokemon/front' / f'{ALIAS.get(dex, names[dex])}.png'
        if not reference.exists():
            pytest.fail(f'no reference art for {dex} ({names[dex]})')
        pixels, width, height = front_sprite(rom, dex, by_dex[dex])
        art = Image.open(reference).convert('L')
        # Game Boy index 0 is the lightest shade, so rank the palette brightest first.
        order = {value: index for index, value in enumerate(sorted(set(art.tobytes()), reverse=True))}
        expected = [[order[art.getpixel((x, y))] for x in range(art.width)] for y in range(art.height)]
        assert (art.width, art.height) == (width * 8, height * 8), dex
        assert pixels == expected, f'dex {dex} ({names[dex]}) does not match the reference'
        checked += 1
    assert checked == 151


@pytest.mark.skipif(not ROM.exists(), reason='no ROM')
def test_installing_a_rom_lays_down_portraits_without_replacing_a_supplied_pack(tmp_path):
    from types import SimpleNamespace

    from pokesim.app.assets import Assets

    registry = SimpleNamespace(root=tmp_path, add_rom=lambda *a: {'id': a[0]}, roms=lambda: [])
    assets = Assets(registry)
    mine = assets.root / 'sprites' / '1.png'
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_bytes(b'a pack the owner installed by hand')

    written = assets.install_portraits(ROM.read_bytes())

    assert written == 150, 'every portrait except the one already there'
    assert mine.read_bytes() == b'a pack the owner installed by hand'
    assert (assets.root / 'sprites' / '151.png').exists()
    assert len(list((assets.root / 'sprites').glob('*.png'))) == 151
