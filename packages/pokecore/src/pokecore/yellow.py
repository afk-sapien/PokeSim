"""Pokémon Yellow on the Red and Blue engine.

Yellow keeps the Red and Blue memory layout except for one byte. pret/pokeyellow
drops wOnCGB at 0xCF1A and adds Pikachu state later in WRAM, so every Red WRAM
address from 0xCF1B up to the end of the box data sits one byte lower. HRAM
moves a few joypad and layout bytes. Cartridge RAM is identical. Event flag
indices used by ``gen1`` and map IDs are unchanged, apart from Yellow's added
Summer Beach House map.

``RedLayoutMemory`` presents raw Yellow memory at Red addresses, so every Red
decoder reads the same fields on a Yellow machine. The Pikachu fields exist
only in Yellow and are given as raw Yellow addresses, from pokeyellow.sym at
pret/pokeyellow revision e89ead154b9968aa50eed9328ff2b38b6c194382.
"""
from __future__ import annotations

import operator

from .cartridges import YELLOW_SHA1 as YELLOW_SHA1

YELLOW_NAME = 'Pokemon Yellow (USA, Europe) (GBC,SGB Enhanced)'
SOURCE_REVISION = 'e89ead154b9968aa50eed9328ff2b38b6c194382'

# Red WRAM [start, stop) whose Yellow address is one lower. 0xDEE2 onward is CPU
# stack space in both games and stays raw.
SHIFT_START, SHIFT_STOP = 0xCF1B, 0xDEE2
# Red HRAM address to Yellow HRAM address.
HRAM = {0xFFF4: 0xFFF9, 0xFFF6: 0xFFFA, 0xFFF7: 0xFFFB, 0xFFF8: 0xFFF5, 0xFFF9: 0xFFF8}
_HRAM_LOW, _HRAM_HIGH = min(HRAM), max(HRAM) + 1

# Raw Yellow addresses of Yellow-only fields.
W_PIKACHU_OVERWORLD_STATE_FLAGS = 0xD42F
W_PIKACHU_SPAWN_STATE = 0xD430
W_PIKACHU_HAPPINESS = 0xD46F
W_PIKACHU_MOOD = 0xD470
W_PIKACHU_SPAWN_STATE_FLAGS = 0xD471
W_PIKACHU_MAP_SCRIPT_FLAGS = 0xD492
W_PIKACHU_EMOTION_MODIFIER = 0xD49B
W_SURFING_MINIGAME_HI_SCORE = 0xD494
# Kept under PokeSim's name.
PIKACHU_HAPPINESS = W_PIKACHU_HAPPINESS

# Raw Yellow addresses of shared fields that ``read_pikachu`` needs.
W_PLAYER_NAME = 0xD157
W_PARTY_COUNT = 0xD162
W_PARTY_SPECIES = 0xD163
W_PARTY_MONS = 0xD16A
W_PARTY_OT = 0xD272
W_PLAYER_ID = 0xD358

# wPikachuSpawnStateFlags bits, from constants/pikachu_emotion_constants.asm.
BIT_PIKACHU_SPAWN_FOLLOWING = 5
BIT_PIKACHU_SPAWN_SURFING = 6
BIT_PIKACHU_SPAWN_STARTER = 7

STARTER_PIKACHU = 0x54      # internal species ID of PIKACHU
EEVEE = 0x66
# wRivalStarter in Yellow holds which way the rival's Eevee will evolve, not a species.
RIVAL_STARTERS = {1: 'jolteon', 2: 'flareon', 3: 'vaporeon'}
PARTY_STRUCT = 44
NAME_LENGTH = 11
NAME_LENGTH_JP = 6


def address(red: int) -> int:
    """Return the Yellow address that holds the Red field at ``red``."""
    if SHIFT_START <= red < SHIFT_STOP:
        return red - 1
    return HRAM.get(red, red)


def _raw_reader(raw):
    reader = getattr(raw, 'read_bytes', None)
    if callable(reader):
        return lambda start, stop: bytes(reader(start, stop))

    def read(start, stop):
        values = raw[start:stop]
        return bytes(values) if not isinstance(values, int) else bytes(
            raw[index] for index in range(start, stop))
    return read


def red_bytes(read, start: int, stop: int) -> bytes:
    """Assemble Red-layout bytes for [start, stop) from a raw Yellow reader ``read(start, stop)``."""
    out = bytearray()
    cursor = start
    while cursor < stop:
        if cursor < SHIFT_START:
            end = min(stop, SHIFT_START)
            out += read(cursor, end)
        elif cursor < SHIFT_STOP:
            end = min(stop, SHIFT_STOP)
            out += read(cursor - 1, end - 1)
        elif cursor < _HRAM_LOW or cursor >= _HRAM_HIGH:
            end = min(stop, _HRAM_LOW) if cursor < _HRAM_LOW else stop
            out += read(cursor, end)
        else:
            end = cursor + 1
            out += read(address(cursor), address(cursor) + 1)
        cursor = end
    return bytes(out)


class RedLayoutMemory:
    """Red-layout view of raw Yellow memory. Banked keys outside WRAM and HRAM pass through.

    ``raw`` is anything indexable by address: bytes, a list, or emulator memory.
    Writes are forwarded only when the raw object supports them.
    """

    def __init__(self, raw):
        self.raw = raw
        self._read = _raw_reader(raw)

    def _byte(self, key):
        return self.raw[address(operator.index(key))]

    def __getitem__(self, key):
        if isinstance(key, tuple):
            _, inner = key
            if isinstance(inner, slice):
                start = inner.start or 0
                if 0xC000 <= start < 0xE000 or 0xFF80 <= start:
                    return list(self[inner])
                return self.raw[key]
            if 0xC000 <= inner < 0xE000 or inner >= 0xFF80:
                return self[inner]
            return self.raw[key]
        if isinstance(key, slice):
            if key.step not in (None, 1):
                return [self[i] for i in range(*key.indices(65536))]
            start = 0 if key.start is None else operator.index(key.start)
            stop = 65536 if key.stop is None else operator.index(key.stop)
            return list(self.read_bytes(start, stop))
        return self._byte(key)

    def read_bytes(self, start, stop):
        start, stop = operator.index(start), operator.index(stop)
        if not 0 <= start <= stop <= 65536:
            raise ValueError('Invalid memory range')
        return red_bytes(self._read, start, stop)

    def __setitem__(self, key, value):
        if isinstance(key, tuple):
            _, inner = key
            if isinstance(inner, slice) or not (0xC000 <= inner < 0xE000 or inner >= 0xFF80):
                self.raw[key] = value
                return
            key = inner
        if isinstance(key, slice):
            start = 0 if key.start is None else operator.index(key.start)
            values = list(value) if not isinstance(value, int) else [value] * len(range(*key.indices(65536)))
            for offset, byte in enumerate(values):
                self.raw[address(start + offset)] = byte
            return
        self.raw[address(operator.index(key))] = value

    def __iter__(self):
        raise TypeError('Read an explicit memory range')


# PokeSim's name for the same view.
YellowMemory = RedLayoutMemory


def red_layout(memory, version=None):
    """Return ``memory`` unchanged for Red and Blue, or a Red-layout view of raw Yellow memory.

    ``version`` is a cartridge version string or a ``cartridges.Cartridge``. A view
    that is already Red-layout is returned unchanged.
    """
    version = getattr(version, 'version', version)
    if version in (None, 'red', 'blue') or isinstance(memory, RedLayoutMemory):
        return memory
    if version != 'yellow':
        raise ValueError('Generation I decoding supports Red, Blue and Yellow')
    return RedLayoutMemory(memory)


def _bytes(memory, start, size):
    values = memory[start:start + size]
    return bytes(values) if not isinstance(values, int) else bytes(memory[i] for i in range(start, start + size))


def is_starter_pikachu(struct, ot_name, player_id: int, player_name) -> bool:
    """IsThisMonStarterPikachu: species, trainer ID and the first five name bytes match the player."""
    struct, ot_name, player_name = bytes(struct), bytes(ot_name), bytes(player_name)
    return (len(struct) >= 14 and struct[0] == STARTER_PIKACHU
            and int.from_bytes(struct[12:14], 'big') == player_id
            and ot_name[:NAME_LENGTH_JP - 1] == player_name[:NAME_LENGTH_JP - 1])


def starter_pikachu_slot(memory, *, alive=True, layout='yellow') -> int | None:
    """Zero-based party slot of the player's own starter Pikachu, or None.

    With ``alive`` this follows IsStarterPikachuAliveInOurParty, which stops at the
    first matching Pikachu and reports none if it has fainted. ``layout`` is
    'yellow' for raw Yellow memory or 'red' for a Red-layout view.
    """
    raw = _raw(memory, layout)
    player_id = int.from_bytes(_bytes(raw, W_PLAYER_ID, 2), 'big')
    player_name = _bytes(raw, W_PLAYER_NAME, NAME_LENGTH)
    count = min(raw[W_PARTY_COUNT], 6)
    for slot in range(count):
        if raw[W_PARTY_SPECIES + slot] == 0xFF:
            break
        struct = _bytes(raw, W_PARTY_MONS + slot * PARTY_STRUCT, PARTY_STRUCT)
        if is_starter_pikachu(struct, _bytes(raw, W_PARTY_OT + slot * NAME_LENGTH, NAME_LENGTH),
                              player_id, player_name):
            if alive and not int.from_bytes(struct[1:3], 'big'):
                return None
            return slot
    return None


def _raw(memory, layout):
    if layout == 'yellow':
        return memory.raw if isinstance(memory, RedLayoutMemory) else memory
    if layout == 'red':
        raw = getattr(memory, 'raw', None)
        if raw is None:
            raise ValueError('A Red-layout view must expose its raw Yellow memory as .raw')
        return raw
    raise ValueError("layout must be 'yellow' or 'red'")


def read_pikachu(memory, *, layout='yellow') -> dict:
    """Read Yellow's Pikachu happiness, mood and follower state as raw facts.

    ``happiness`` and ``mood`` are the cartridge bytes (0 to 255, mood centres on
    128). ``following`` and ``surfing`` are wPikachuSpawnStateFlags bits.
    ``starter_slot`` is the party slot of the player's living starter Pikachu.
    """
    raw = _raw(memory, layout)
    flags = raw[W_PIKACHU_SPAWN_STATE_FLAGS]
    return {
        'happiness': raw[W_PIKACHU_HAPPINESS],
        'mood': raw[W_PIKACHU_MOOD],
        'spawn_flags': flags,
        'following': bool(flags & (1 << BIT_PIKACHU_SPAWN_FOLLOWING)),
        'surfing': bool(flags & (1 << BIT_PIKACHU_SPAWN_SURFING)),
        'starter_spawn': bool(flags & (1 << BIT_PIKACHU_SPAWN_STARTER)),
        'overworld_flags': raw[W_PIKACHU_OVERWORLD_STATE_FLAGS],
        'spawn_state': raw[W_PIKACHU_SPAWN_STATE],
        'map_script_flags': raw[W_PIKACHU_MAP_SCRIPT_FLAGS],
        'emotion_modifier': raw[W_PIKACHU_EMOTION_MODIFIER],
        'starter_slot': starter_pikachu_slot(raw),
    }


def happiness_band(happiness: int) -> int:
    """The hundreds digit PikachuHappiness uses to pick a reaction, 0, 1 or 2."""
    if type(happiness) is not int or not 0 <= happiness <= 255:
        raise ValueError('Happiness is a byte')
    return happiness // 100


def is_yellow(rom) -> bool:
    """Whether ``rom`` (bytes or a path) is the clean English Yellow cartridge."""
    import hashlib
    from pathlib import Path
    raw = rom if isinstance(rom, (bytes, bytearray, memoryview)) else Path(rom).read_bytes()
    return hashlib.sha1(raw).hexdigest() == YELLOW_SHA1


def _yellow_emulator_class():
    from .emulator import Emulator

    class YellowEmulator(Emulator):
        """A Core emulator whose ``memory`` uses Red addresses on a Yellow cartridge.

        ``raw_memory`` keeps the untranslated Yellow addresses.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.raw_memory = self.memory
            self.memory = RedLayoutMemory(self.raw_memory)

        def _advance(self, frames, render, sound, read_range=None):
            if read_range is None:
                return super()._advance(frames, render, sound)
            super()._advance(frames, render, sound)
            return self.memory.read_bytes(*read_range)

    return YellowEmulator


def __getattr__(name):
    if name == 'YellowEmulator':
        cls = _yellow_emulator_class()
        globals()['YellowEmulator'] = cls
        return cls
    raise AttributeError(name)


def open_emulator(rom, default=None, **kwargs):
    """Construct the Core emulator that matches the cartridge.

    ``rom`` is a path or a binary stream. Yellow gets ``YellowEmulator``. Other
    cartridges use ``default``, which is the Core ``Emulator`` unless named.
    """
    import io
    from pathlib import Path
    if hasattr(rom, 'read'):
        raw = rom.read()
        rom = io.BytesIO(raw)
    else:
        raw = Path(rom).read_bytes()
    if is_yellow(raw):
        return __getattr__('YellowEmulator')(rom, **kwargs)
    if default is None:
        from .emulator import Emulator as default
    return default(rom, **kwargs)
