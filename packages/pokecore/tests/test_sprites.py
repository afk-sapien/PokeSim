"""Portrait decoding for both generations, on hand-built data. Cartridge checks are in test_sprites_roms.py."""
import zlib

import pytest

from pokecore import sprites
from pokecore.gen2 import sprites as gen2_sprites
from pokecore.sprites import MEW_INTERNAL, png, sprite_bank


def test_pictures_live_in_the_bank_their_internal_index_selects():
    assert sprite_bank(MEW_INTERNAL) == 0x01, 'Mew was slotted in on its own'
    assert sprite_bank(MEW_INTERNAL, yellow=True) == 0x9
    assert sprite_bank(0x1E) == 0x9
    assert sprite_bank(0x1F) == 0xA
    assert sprite_bank(0x49) == 0xA
    assert sprite_bank(0x4A) == 0xB
    assert sprite_bank(0x73) == 0xB
    assert sprite_bank(0x74) == 0xC
    assert sprite_bank(0x98) == 0xC
    assert sprite_bank(0x99) == 0xD


def _idat(data):
    start = data.index(b'IDAT') + 4
    length = int.from_bytes(data[start - 8:start - 4], 'big')
    return zlib.decompress(data[start:start + length])


def test_the_lightest_shade_is_written_transparent():
    """One portrait has to sit on a light panel and a dark one, so it supplies no ground."""
    data = png([[0, 1], [2, 3]])
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert (int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')) == (2, 2)
    assert data[24] == 8 and data[25] == 6, '8-bit RGBA'
    raw = _idat(data)
    assert raw[0] == 0 and raw[1:5] == bytes((255, 255, 255, 0)), 'shade 0 is transparent'
    assert raw[5:9][3] == 255, 'every darker shade is opaque'


def test_png_takes_any_palette():
    raw = _idat(png([[1]], palette=((0, 0, 0, 0), (10, 20, 30, 255))))
    assert raw == bytes((0, 10, 20, 30, 255))


def test_implausible_gen1_picture_headers_are_refused():
    with pytest.raises(ValueError, match='Implausible'):
        sprites.decode(bytes(0x8000), 1, 0x4000)


def test_gen1_base_stats_must_match_the_pokedex():
    with pytest.raises(ValueError, match='base stats'):
        sprites.front_sprite(bytes(0x80000), 1, 0x99, yellow=False)


def test_gen2_offsets_are_banked_except_bank_zero():
    assert gen2_sprites.offset(0, 0x1234) == 0x1234
    assert gen2_sprites.offset(0x14, 0x5424) == 0x14 * 0x4000 + 0x1424


def test_gen2_picture_banks_are_remapped_as_the_game_does():
    assert gen2_sprites.pic_bank('crystal', 0x1D) == 0x53
    assert gen2_sprites.pic_bank('gold', 0x13) == 0x1F
    assert gen2_sprites.pic_bank('silver', 0x1F) == 0x2E
    assert gen2_sprites.pic_bank('gold', 0x1E) == 0x1E


@pytest.mark.parametrize('stream, expected', [
    (bytes([0x02, 1, 2, 3, 0xFF]), bytes([1, 2, 3])),                     # literal
    (bytes([0x23, 9, 0xFF]), bytes([9] * 4)),                               # repeat a byte
    (bytes([0x44, 1, 2, 0xFF]), bytes([1, 2, 1, 2, 1])),                    # alternate two bytes
    (bytes([0x61, 0xFF]), bytes(2)),                                        # zeros
    (bytes([0x01, 1, 2, 0x81, 0x81, 0xFF]), bytes([1, 2, 1, 2])),           # copy, relative
    (bytes([0x01, 1, 2, 0xA1, 0x00, 0x00, 0xFF]), bytes([1, 2, 0x80, 0x40])),  # bit-reversed copy
    (bytes([0x01, 1, 2, 0xC1, 0x80, 0xFF]), bytes([1, 2, 2, 1])),           # backwards copy
    (bytes([0xE0, 0x02, 7, 8, 9, 0xFF]), bytes([7, 8, 9])),               # long form literal
])
def test_gen2_decompress_commands(stream, expected):
    assert gen2_sprites.decompress(stream, 0) == expected


def test_gen2_decompress_refuses_bad_streams():
    with pytest.raises(ValueError, match='Truncated'):
        gen2_sprites.decompress(bytes([0x00, 1]), 0)
    with pytest.raises(ValueError, match='back reference'):
        gen2_sprites.decompress(bytes([0x81, 0x80, 0xFF]), 0)
    with pytest.raises(ValueError, match='size limit'):
        gen2_sprites.decompress(bytes([0x7F, 0xFF]), 0, limit=8)


def _gen2_rom(version='crystal', dex=1, size=0x11):
    rom = bytearray(0x200000)
    base = gen2_sprites.offset(*gen2_sprites.LABELS[version]['BaseData']) + (dex - 1) * 32
    rom[base], rom[base + 17] = dex, size
    pointers = gen2_sprites.offset(*gen2_sprites.LABELS[version]['PokemonPicPointers']) + (dex - 1) * 6
    rom[pointers:pointers + 3] = bytes([0x12, 0x00, 0x50])                  # bank 0x12 + 0x36 = 0x48
    picture = gen2_sprites.offset(0x48, 0x5000)
    tile = bytes([0xFF, 0x00] * 4 + [0x00, 0xFF] * 4)                      # top half 1, bottom half 2
    rom[picture:picture + 18] = bytes([0x0F]) + tile + bytes([0xFF])
    colours = gen2_sprites.offset(*gen2_sprites.LABELS[version]['PokemonPalettes']) + dex * 8
    rom[colours:colours + 8] = bytes([0x1F, 0x00, 0xE0, 0x03, 0x00, 0x7C, 0xFF, 0x7F])
    return bytes(rom)


def test_gen2_picture_and_portrait_on_a_built_cartridge():
    rom = _gen2_rom()
    rows, width, height = gen2_sprites.picture(rom, 'crystal', 1)
    assert (width, height) == (1, 1)
    assert rows == [[1] * 8] * 4 + [[2] * 8] * 4
    canvas, palette = gen2_sprites.portrait(rom, 'crystal', 1)
    assert len(canvas) == 56 and {len(row) for row in canvas} == {56}
    assert canvas[48][24:32] == [1] * 8 and canvas[55][24:32] == [2] * 8, 'centred on the bottom edge'
    assert canvas[47] == [0] * 56 and canvas[55][23] == 0
    assert palette == ((255, 255, 255, 0), (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 0, 255))
    assert gen2_sprites.palette(rom, 'crystal', 1, shiny=True)[1:3] == ((0, 0, 255, 255), (255, 255, 255, 255))


def test_gen2_base_data_must_match_the_pokedex():
    rom = bytearray(_gen2_rom())
    with pytest.raises(ValueError, match='base data'):
        gen2_sprites.picture(bytes(rom), 'crystal', 2)
    rom[gen2_sprites.offset(*gen2_sprites.LABELS['crystal']['BaseData']) + 17] = 0x81
    with pytest.raises(ValueError, match='dimensions'):
        gen2_sprites.picture(bytes(rom), 'crystal', 1)
