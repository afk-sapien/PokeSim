"""Bulk storage reads and bounded, immutable decoding caches."""
from dataclasses import dataclass
from functools import lru_cache

from .gen1 import decode_text, individual_data


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
