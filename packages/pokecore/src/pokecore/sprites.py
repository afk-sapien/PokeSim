"""Decode the 151 front portraits out of a Red, Blue or Yellow cartridge.

The artwork is in the ROM the owner supplied, so there is nothing to ship and nothing to
download. Pictures come back as rows of colour indices 0 (lightest) to 3 (darkest), and
:func:`png` writes any such picture as a PNG with the standard library alone. Ported from pret/pokered `home/uncompress.asm`: a picture is two 1bpp chunks,
each written two bits at a time down byte-columns over four passes, then differentially
decoded row by row and merged into one 2bpp image.

Verified against pret's own reference PNGs at the pinned revision: all 151 decode
pixel-for-pixel, including Mew, whose header sits outside the base-stats table because it
was squeezed into 300 bytes of leftover space late in development. Yellow keeps the
same table and picture banks, with Mew's header inside the table and its picture in bank 9.
"""
from __future__ import annotations

import zlib

from .identity import GEN1_INDEX
from .rom import rom_offset
from .yellow import is_yellow

BASE_STATS = 0x383DE
MEW_BASE_STATS = 0x0425B
MEW_DEX = 151
ENTRY = 28
MEW_INTERNAL = 0x15

# Lightest to darkest RGBA, the default palette for :func:`png`. The lightest shade is
# transparent so one portrait works on any background.
SHADES = ((255, 255, 255, 0), (168, 168, 160, 255), (88, 88, 84, 255), (16, 16, 16, 255))


def sprite_bank(internal: int, yellow: bool = False) -> int:
    """Which ROM bank holds a species' picture, keyed by its internal index."""
    if internal == MEW_INTERNAL and not yellow:
        return 0x01
    if internal < 0x1F:
        return 0x9
    if internal < 0x4A:
        return 0xA
    if internal < 0x74:
        return 0xB
    if internal < 0x99:
        return 0xC
    return 0xD


class _Bits:
    __slots__ = ('data', 'pos')

    def __init__(self, data, offset):
        self.data, self.pos = data, offset * 8

    def bit(self):
        value = (self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return value

    def read(self, n):
        value = 0
        for _ in range(n):
            value = (value << 1) | self.bit()
        return value


class _Chunk:
    """One 1bpp plane: byte-column major, four passes writing two bits each."""

    def __init__(self, columns, height):
        self.buf = bytearray(columns * height)
        self.columns, self.height = columns, height
        self.col = self.y = 0
        self.offset = 3
        self.done = False

    def write(self, pair):
        self.buf[self.col * self.height + self.y] |= pair << (self.offset * 2)
        self.y += 1
        if self.y == self.height:
            self.y = 0
            if self.offset:
                self.offset -= 1
            else:
                self.offset = 3
                self.col += 1
                if self.col == self.columns:
                    self.done = True


def _fill(bits, chunk):
    """Alternate runs of zero pairs and literal pairs until the plane is full."""
    rle = bits.bit() == 0
    while not chunk.done:
        if rle:
            ones = 0
            while bits.bit():
                ones += 1
            count = bits.read(ones + 1) + (1 << (ones + 1)) - 1
            for _ in range(count):
                if chunk.done:
                    break
                chunk.write(0)
        else:
            while not chunk.done:
                pair = bits.read(2)
                if pair == 0:
                    break
                chunk.write(pair)
        rle = not rle


def _differential(chunk):
    """Row by row, left to right: a 1 toggles the running bit, a 0 keeps it."""
    height, columns, buf = chunk.height, chunk.columns, chunk.buf
    for y in range(height):
        state = 0
        for col in range(columns):
            index = col * height + y
            byte, out = buf[index], 0
            for bit in range(7, -1, -1):
                if (byte >> bit) & 1:
                    state ^= 1
                out |= state << bit
            buf[index] = out


def _xor(target, source):
    for i, value in enumerate(source.buf):
        target.buf[i] ^= value


def base_stats(rom: bytes, dex: int, yellow: bool = False) -> bytes:
    """The 28-byte base stats entry for ``dex``. Red and Blue keep Mew's outside the table."""
    if dex == MEW_DEX and not yellow:
        return rom[MEW_BASE_STATS:MEW_BASE_STATS + ENTRY]
    offset = BASE_STATS + (dex - 1) * ENTRY
    return rom[offset:offset + ENTRY]


def decode(rom: bytes, bank: int, pointer: int) -> tuple[list[list[int]], int, int]:
    """Return colour indices 0..3, plus the picture's width and height in tiles."""
    bits = _Bits(rom, rom_offset(bank, pointer))
    head = bits.read(8)
    width, height = head >> 4, head & 0x0F
    if not (1 <= width <= 7 and 1 <= height <= 7):
        raise ValueError(f'Implausible picture header {width}x{height}')
    rows = height * 8
    first, second = _Chunk(width, rows), _Chunk(width, rows)

    order = bits.bit()
    _fill(bits, second if order else first)
    mode = 0 if bits.bit() == 0 else (1 if bits.bit() == 0 else 2)
    _fill(bits, first if order else second)

    primary = second if order else first
    other = first if primary is second else second
    if mode == 0:
        _differential(first)
        _differential(second)
    elif mode == 1:
        _differential(primary)
        _xor(other, primary)
    else:
        _differential(other)
        _differential(primary)
        _xor(other, primary)

    pixels = []
    for y in range(rows):
        row = []
        for col in range(width):
            low, high = first.buf[col * rows + y], second.buf[col * rows + y]
            for bit in range(7, -1, -1):
                row.append((((high >> bit) & 1) << 1) | ((low >> bit) & 1))
        pixels.append(row)
    return pixels, width, height


def front_sprite(rom: bytes, dex: int, internal: int | None = None, yellow: bool | None = None):
    """Decode Pokédex number ``dex``: colour indices, then width and height in tiles.

    ``internal`` is the species index and defaults to :data:`identity.GEN1_INDEX`. ``yellow``
    defaults to whether ``rom`` is the Yellow cartridge.
    """
    if yellow is None:
        yellow = is_yellow(rom)
    if internal is None:
        internal = GEN1_INDEX[dex]
    entry = base_stats(rom, dex, yellow)
    if entry[0] != dex:
        raise ValueError('The cartridge base stats table does not match the Pokédex')
    return decode(rom, sprite_bank(internal, yellow), int.from_bytes(entry[11:13], 'little'))


def png(pixels, palette=SHADES) -> bytes:
    """A minimal RGBA PNG of rows of palette indices, so no imaging library is needed."""
    height, width = len(pixels), len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for value in row:
            raw.extend(palette[value])

    def chunk(kind, payload):
        body = kind + payload
        return len(payload).to_bytes(4, 'big') + body + zlib.crc32(body).to_bytes(4, 'big')

    header = width.to_bytes(4, 'big') + height.to_bytes(4, 'big') + bytes((8, 6, 0, 0, 0))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def portraits(rom: bytes) -> dict[int, list[list[int]]]:
    """Every front portrait the cartridge holds, as Pokédex number -> colour index rows."""
    yellow = is_yellow(rom)
    return {dex: front_sprite(rom, dex, GEN1_INDEX[dex], yellow)[0] for dex in range(1, MEW_DEX + 1)}
