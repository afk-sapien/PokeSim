"""Bulk storage reads and bounded, immutable decoding caches."""
from dataclasses import dataclass
from functools import lru_cache

from .gen1 import (BOX_CAPACITY, BOX_COUNT, BOX_DATA_SIZE, BOX_MONS_OFFSET, BOX_NICKS_OFFSET,
                   S_BOXES, W_BOX_COUNT, W_CURRENT_BOX, decode_text, individual_data)
from .yellow import red_layout


def memory_bytes(memory, bank, start, size):
    """Read a block without changing banks, with a scalar-adapter fallback.

    A snapshot memory (see memory_snapshot) serves banked blocks from its per-step copy.
    """
    if size == 0:
        return b''
    if bank is not None:
        window = getattr(memory, 'snapshot_window', None)
        if window is not None:
            block = window(bank, start, size)
            if block is not None:
                return bytes(block)
    try:
        key = slice(start, start + size)
        values = memory[key] if bank is None else memory[bank, key]
        if not isinstance(values, int):
            result = bytes(values)
            if len(result) != size:
                raise ValueError('Incomplete memory block')
            return result
    except TypeError:
        pass
    return bytes(memory[address] if bank is None else memory[bank, address]
                 for address in range(start, start + size))


@dataclass(frozen=True)
class BoxMon:
    position: int
    species: int
    level: int
    hp: int
    status: int
    types: tuple[int, ...]
    moves: tuple[int, ...]
    pp: tuple[int, ...]
    nick: str
    trainer_id: int
    experience: int
    dvs: tuple[int, ...]
    stat_exp: tuple[int, ...]


@lru_cache(maxsize=128)
def decode_box(structs: bytes, names: bytes) -> tuple[BoxMon, ...]:
    """Cache by immutable bytes, never by emulator identity or elapsed time.

    Raw records are not filtered by species or level. Consumers decide how to
    handle invalid or unavailable data. No mutable object escapes the cache.
    """
    if not isinstance(structs, bytes) or not isinstance(names, bytes):
        raise TypeError('Box decoding requires immutable bytes')
    count, remainder = divmod(len(structs), 33)
    if remainder or count > 20 or len(names) != count * 11:
        raise ValueError('Box records and nicknames must have matching lengths')
    out = []
    for index in range(count):
        block = structs[index * 33:(index + 1) * 33]
        data = individual_data(block)
        out.append(BoxMon(index, block[0], block[3], int.from_bytes(block[1:3], 'big'),
                          block[4], tuple(block[5:7]), tuple(data['moves']),
                          tuple(value & 63 for value in block[29:33]),
                          decode_text(names[index * 11:(index + 1) * 11]),
                          data['trainer_id'], data['experience'], tuple(data['dvs']), tuple(data['stat_exp'])))
    return tuple(out)


@dataclass(frozen=True)
class BoxRecords:
    """One Gen I box's raw bytes: the 33-byte records and 11-byte nicknames of its counted Pokémon."""
    box: int
    structs: bytes
    names: bytes

    @property
    def count(self) -> int:
        return len(self.structs) // 33

    @property
    def mons(self) -> tuple[BoxMon, ...]:
        return decode_box(self.structs, self.names)


def box_location(box, active):
    """The (bank, address) of a Gen I box's count byte, with boxes counted from 0.

    The active box is the WRAM copy at wBoxCount, read with bank None. Every other box,
    and every box when ``active`` is None, is its cartridge RAM copy.
    """
    if box == active:
        return None, W_BOX_COUNT
    return 2 + box // 6, S_BOXES + (box % 6) * BOX_DATA_SIZE


def _byte(memory, bank, address):
    return memory[address] if bank is None else memory[bank, address]


def read_box_counts(memory, *, version=None) -> tuple[int, ...]:
    """Counted Pokémon in each Gen I box, or () before a box is selected.

    Inactive boxes count 0 until the game has initialized the boxes, which bit 7 of
    wCurrentBoxNum marks. Their counts are the raw bytes, and only the active box is
    clamped to BOX_CAPACITY. Memory without cartridge RAM banks, such as a flat test
    buffer, reports BOX_CAPACITY for every inactive box.
    """
    memory = red_layout(memory, version)
    current = memory[W_CURRENT_BOX]
    active = current & 0x7F
    if active >= BOX_COUNT:
        return ()
    counts = [0] * BOX_COUNT
    if current & 0x80:
        try:
            counts = [_byte(memory, *box_location(box, None)) for box in range(BOX_COUNT)]
        except TypeError:
            counts = [BOX_CAPACITY] * BOX_COUNT
    counts[active] = min(memory[W_BOX_COUNT], BOX_CAPACITY)
    return tuple(counts)


def read_box_records(memory, counts=None, *, version=None) -> tuple[BoxRecords, ...]:
    """Raw records of every Gen I box that holds Pokémon, in box order.

    ``counts`` defaults to ``read_box_counts`` and each count is clamped to BOX_CAPACITY.
    A box in a cartridge RAM bank the memory cannot serve is left out. Records are not
    filtered by species or level, and nothing switches banks or writes memory.
    """
    memory = red_layout(memory, version)
    counts = read_box_counts(memory) if counts is None else counts
    active = memory[W_CURRENT_BOX] & 0x7F
    out = []
    for box, count in enumerate(counts):
        count = min(count, BOX_CAPACITY)
        if not count:
            continue
        bank, base = box_location(box, active)
        try:
            structs = memory_bytes(memory, bank, base + BOX_MONS_OFFSET, count * 33)
            names = memory_bytes(memory, bank, base + BOX_NICKS_OFFSET, count * 11)
        except TypeError:
            continue
        out.append(BoxRecords(box, structs, names))
    return tuple(out)
