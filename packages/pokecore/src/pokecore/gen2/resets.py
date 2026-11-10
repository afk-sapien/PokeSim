"""Explicit trusted Gold, Silver and Crystal setup writes, separate from read-only decoders.

These mirror :mod:`pokecore.resets` for Gen II's banked memory. They are not controller
actions, so do not expose them as agent commands. The consumer decides which flags to change,
when and why, and verifies the result. Call only while the emulator is paused or under its
exclusive simulation lock. ``memory`` is written as ``memory[bank, address] = byte``.
"""
from __future__ import annotations

import random

from .ram import Memory, experience_at

GS_BALL = 0x0B


def write(memory, data, symbol, raw, offset=0):
    """Write the bytes ``raw`` at ``symbol`` + ``offset``. High RAM has no bank."""
    bank, address = data.symbols[symbol]
    for index, byte in enumerate(raw):
        if address >= 0xFF80:
            memory[address + offset + index] = byte
        else:
            memory[bank, address + offset + index] = byte


def write_byte(memory, data, name, value, offset=0):
    """Set one byte of ``name``. Returns whether it changed."""
    if Memory(memory, data).byte(name, offset) == value:
        return False
    write(memory, data, name, (value,), offset)
    return True


def _flag(data, name):
    offset, bit = divmod(data.events[name], 8)
    return offset, 1 << bit


def write_flag(memory, data, name, value):
    """Set or clear the event flag ``name`` (a key of ``data.events``). Returns whether it changed."""
    offset, mask = _flag(data, name)
    old = Memory(memory, data).byte('wEventFlags', offset)
    return write_byte(memory, data, 'wEventFlags', old | mask if value else old & ~mask, offset)


def reset_event(memory, data, flags):
    """Apply (event name, bool) pairs together, preserving other bits. Returns the names that changed.

    Every name is checked and conflicting values are refused before any write. Each written byte
    is read back. On a failure every byte already written is restored and the error re-raised.
    """
    requested = {}
    for name, value in flags:
        if name not in data.events or type(value) is not bool:
            raise ValueError('Changes must be pairs of a known event flag and bool')
        if requested.get(name, value) != value:
            raise ValueError('Conflicting values for one flag')
        requested[name] = value
    if not requested:
        raise ValueError('Supply at least one event flag')
    mem = Memory(memory, data)
    before, changed = {}, []
    for name, value in requested.items():
        offset, mask = _flag(data, name)
        current = before.setdefault(offset, mem.byte('wEventFlags', offset))
        if bool(current & mask) != value:
            changed.append(name)
    after = dict(before)
    for name, value in requested.items():
        offset, mask = _flag(data, name)
        after[offset] = after[offset] | mask if value else after[offset] & ~mask
    attempted = []
    try:
        for offset in sorted(after):
            if after[offset] == before[offset]:
                continue
            attempted.append(offset)
            write(memory, data, 'wEventFlags', (after[offset],), offset)
            if mem.byte('wEventFlags', offset) != after[offset]:
                raise RuntimeError('Flag write did not persist')
    except Exception as error:
        for offset in reversed(attempted):
            try:
                write(memory, data, 'wEventFlags', (before[offset],), offset)
                if mem.byte('wEventFlags', offset) != before[offset]:
                    raise RuntimeError('Rollback verification failed')
            except Exception as rollback_error:
                error.add_note(f'Could not restore event flag byte {offset}: {rollback_error}')
        raise
    return tuple(changed)


def box_gift(memory, data, species, seed, box, position, *, nicknames=None, ot='POKESIM'):
    """Put a level 5 ``species`` in PC ``box`` (0 to 13) at ``position``, the next free slot.

    ``seed`` fixes the trainer ID and DVs. Moves are the last four it learns by level 5, with
    full PP and 70 happiness. The nickname is drawn from ``nicknames`` with the same generator,
    or is the species name when ``nicknames`` is None. The Pokédex caught and seen bits are set.
    Raises ValueError unless the box holds exactly ``position`` Pokémon.
    Reads ``data.species`` (``learnset``, ``growth``, ``name``), ``data.moves`` and ``data.charmap``.
    """
    rng = random.Random(seed)
    entry = data.species[species]
    raw = bytearray(32)
    raw[0] = species
    moves = []
    for level, move in entry['learnset']:
        if level <= 5 and move not in moves:
            moves.append(move)
    moves = moves[-4:]
    raw[2:2 + len(moves)] = bytes(moves)
    raw[6:8] = rng.randrange(65536).to_bytes(2, 'big')
    raw[8:11] = experience_at(5, entry['growth']).to_bytes(3, 'big')
    raw[21:23] = bytes((rng.randrange(256), rng.randrange(256)))
    raw[23:23 + len(moves)] = bytes(data.moves[move]['pp'] for move in moves)
    raw[27] = 70
    raw[31] = 5
    alphabet = {value: key for key, value in data.charmap.items() if len(value) == 1}

    def encode(text):
        return bytes([alphabet.get(char, 0x7F) for char in text.upper()[:10]] + [0x50]).ljust(11, b'\x50')
    nickname = encode(rng.choice(nicknames) if nicknames is not None else entry['name'])
    mem = Memory(memory, data)
    name = 'sBox' if box == mem.byte('wCurBox') & 0x7F else f'sBox{box + 1}'
    if mem.byte(name) != position or not 0 <= position < 20:
        raise ValueError('The gift destination changed')
    write(memory, data, name, raw, 22 + position * 32)
    write(memory, data, name, encode(ot), 662 + position * 11)
    write(memory, data, name, nickname, 882 + position * 11)
    write(memory, data, name, bytes((species, 0xFF)), 1 + position)
    write(memory, data, name, bytes((position + 1,)))
    offset, bit = divmod(species - 1, 8)
    for symbol in ('wPokedexCaught', 'wPokedexSeen'):
        write(memory, data, symbol, bytes((mem.byte(symbol, offset) | 1 << bit,)), offset)


def set_gs_ball(memory, data):
    """Turn on Crystal's GS Ball distribution flag, so the Goldenrod Pokémon Center hands it out.

    Raises ValueError on Gold and Silver, which have no GS Ball event.
    """
    if data.game != 'crystal':
        raise ValueError('Only Crystal has the GS Ball event')
    write(memory, data, 'sGSBallFlag', bytes((GS_BALL,)))
