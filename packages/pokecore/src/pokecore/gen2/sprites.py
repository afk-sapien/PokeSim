"""Decode Gold, Silver and Crystal front portraits from the owner's cartridge.

Pictures come back as rows of colour indices 0 (lightest) to 3 (darkest) with the species'
own RGBA palette, in which index 0 is transparent. :func:`pokecore.sprites.png` writes
either as a PNG with the standard library alone.

The ROM tables are found through :data:`LABELS`, from the pinned pret symbol files. Each
game keeps a front and back picture pointer per species, with a bank that the game remaps
before reading: Crystal adds 0x36 and Gold and Silver move three banks (``FixPicBank``).
Unown's portrait is its letter A unless ``unown`` names another letter, 0 to 25.
"""
from __future__ import annotations

from ..rom import rom_offset as offset

_GOLD = {'BaseData': (0x14, 0x5B0B), 'PokemonPalettes': (0x02, 0x6D3D),
         'PokemonPicPointers': (0x12, 0x4000), 'UnownPicPointers': (0x1F, 0x4000)}
LABELS = {
    'gold': _GOLD,
    'silver': _GOLD,
    'crystal': {'BaseData': (0x14, 0x5424), 'PokemonPalettes': (0x02, 0x68CE),
                'PokemonPicPointers': (0x48, 0x4000), 'UnownPicPointers': (0x49, 0x4000)},
}
# Gold and Silver ``FixPicBank``: the stored bank to the bank that holds the picture.
_GS_PIC_BANKS = {0x13: 0x1F, 0x14: 0x20, 0x1F: 0x2E}
UNOWN = 201
SIZE = 56


def decompress(raw, start, limit=65536):
    """Expand Gen II LZ picture data from ``start`` to its 0xFF terminator."""
    result = bytearray()
    position = start
    while position < len(raw):
        command = raw[position]
        position += 1
        if command == 255:
            return bytes(result)
        kind = command >> 5
        length = (command & 31) + 1
        if kind == 7:
            kind = (command >> 2) & 7
            length = ((command & 3) << 8 | raw[position]) + 1
            position += 1
        if len(result) + length > limit:
            raise ValueError('Gen II sprite expands beyond its size limit')
        if kind == 0:
            result.extend(raw[position:position + length])
            position += length
        elif kind == 1:
            result.extend([raw[position]] * length)
            position += 1
        elif kind == 2:
            pair = raw[position:position + 2]
            result.extend(pair[index & 1] for index in range(length))
            position += 2
        elif kind == 3:
            result.extend(bytes(length))
        else:
            address = raw[position]
            position += 1
            if address & 128:
                address = len(result) - (address & 127) - 1
            else:
                address = (address << 8) | raw[position]
                position += 1
            for _ in range(length):
                if not 0 <= address < len(result):
                    raise ValueError('Invalid Gen II sprite back reference')
                value = result[address]
                if kind == 5:
                    value = int(f'{value:08b}'[::-1], 2)
                result.append(value)
                address += -1 if kind == 6 else 1
    raise ValueError('Truncated Gen II sprite')


def pic_bank(version, stored):
    """The bank a picture pointer's stored bank names once the game remaps it."""
    if version == 'crystal':
        return stored + 0x36
    return _GS_PIC_BANKS.get(stored, stored)


def _label(version, name):
    return offset(*LABELS[version][name])


def dimensions(rom, version, dex):
    """The front picture's width and height in tiles, from the base data."""
    entry = _label(version, 'BaseData') + (dex - 1) * 32
    if rom[entry] != dex:
        raise ValueError('The cartridge base data does not match the Pokédex')
    width, height = rom[entry + 17] >> 4, rom[entry + 17] & 15
    if not 1 <= width <= 7 or not 1 <= height <= 7:
        raise ValueError('Invalid Gen II portrait dimensions')
    return width, height


def front_pointer(rom, version, dex, unown=0):
    """The ROM offset of a species' compressed front picture."""
    if dex == UNOWN:
        entry = _label(version, 'UnownPicPointers') + unown * 6
    else:
        entry = _label(version, 'PokemonPicPointers') + (dex - 1) * 6
    return offset(pic_bank(version, rom[entry]), int.from_bytes(rom[entry + 1:entry + 3], 'little'))


def palette(rom, version, dex, *, shiny=False):
    """Four RGBA colours, lightest first. Index 0 is transparent white and index 3 black."""
    at = _label(version, 'PokemonPalettes') + dex * 8 + (4 if shiny else 0)
    colours = [(255, 255, 255, 0)]
    for index in (0, 2):
        colour = int.from_bytes(rom[at + index:at + index + 2], 'little')
        colours.append(tuple(((colour >> shift) & 31) * 255 // 31 for shift in (0, 5, 10)) + (255,))
    return tuple(colours + [(0, 0, 0, 255)])


def picture(rom, version, dex, *, unown=0):
    """Decode a front picture: colour index rows, then width and height in tiles."""
    width, height = dimensions(rom, version, dex)
    data = decompress(rom, front_pointer(rom, version, dex, unown))
    if len(data) < width * height * 16:
        raise ValueError('Gen II sprite is shorter than its dimensions')
    rows = [[0] * (width * 8) for _ in range(height * 8)]
    for tx in range(width):
        for ty in range(height):
            tile = (tx * height + ty) * 16
            for y in range(8):
                low, high = data[tile + y * 2:tile + y * 2 + 2]
                row = rows[ty * 8 + y]
                for x in range(8):
                    bit = 7 - x
                    row[tx * 8 + x] = (low >> bit & 1) | ((high >> bit & 1) << 1)
    return rows, width, height


def portrait(rom, version, dex, *, shiny=False, unown=0):
    """A 56 by 56 portrait as the game frames it, centred and on the bottom edge.

    Returns colour index rows and the species' :func:`palette`. The margin is index 0.
    """
    rows, width, height = picture(rom, version, dex, unown=unown)
    left, top = (SIZE - width * 8) // 2, SIZE - height * 8
    canvas = [[0] * SIZE for _ in range(SIZE)]
    for y, row in enumerate(rows):
        canvas[top + y][left:left + len(row)] = row
    return canvas, palette(rom, version, dex, shiny=shiny)
