"""Summarize a Red, Blue, Yellow, Gold, Silver or Crystal cartridge save without an emulator.

The save's SRAM holds copies of the WRAM the game's other readers use, so each field is the
matching WRAM address minus one fixed distance. A checksum that does not match refuses the file.
The ROM is optional. It names the version and the species and is never needed for anything else.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .cartridges import identify, resembles
from .gen1 import (CHAMPION_FLAG, ELITE_FLAGS, W_BADGES, W_CUR_MAP, W_CURRENT_BOX, W_DEX_OWNED, W_DEX_SEEN,
                   W_EVENT_FLAGS, W_HALL_OF_FAME_COUNT, W_MONEY, W_PLAYER_ID, W_PLAYER_STARTER, W_PLAYTIME_H,
                   W_RIVAL_NAME, W_RIVAL_STARTER, decode_text, event_set)
from .gen2.charmap import charmap
from .gen2.memory_map import CRYSTAL, GOLD_SILVER
from .gen2.ram import BADGES
from .yellow import RIVAL_STARTERS, STARTER_PIKACHU

SAVE_SIZE = 0x8000
BOX_CAPACITY = 20

# wMainData in Red-layout WRAM, as stored in SRAM bank 1. Yellow's file offsets are identical.
GEN1_MAIN = W_DEX_OWNED - 0x25A3
GEN1_PLAYER_NAME = 0x2598
GEN1_PARTY = 0x2F2C
GEN1_ACTIVE_BOX = 0x30C0
GEN1_CHECKSUM = 0x3523
# Boxes 1 to 6 fill bank 2 and 7 to 12 fill bank 3, each followed by that bank's checksum.
GEN1_BOX_SIZE = 0x462
GEN1_BANKS = (0x4000, 0x6000)
GEN1_BANK_CHECKSUM = 0x1A4C
GEN1_BOXES = 12
GEN1_HAS_CHANGED_BOXES = 0x80
GEN1_PARTY_STRUCT, GEN1_LEVEL = 44, 33
# pret map constants: the Elite Four's rooms, then the rest of the way out of the League.
GEN1_LEAGUE_ROOMS = frozenset({0xF5, 0xF6, 0xF7, 0x71, 0x78, 0x76})
GEN1_LEAGUE = GEN1_LEAGUE_ROOMS | {0x6C, 0xC2, 0xC6, 0xAE}

# The checksummed span, wPlayerData to wPokemonDataEnd in WRAM, starts here in SRAM bank 1.
GEN2_DATA = 0x2009
GEN2_CHECK_1, GEN2_CHECK_1_VALUE = 0x2008, 0x63
GEN2_CHECK_2_VALUE = 0x7F
GEN2_LAYOUTS = {'crystal': (CRYSTAL, 0xB472, 0x2B83), None: (GOLD_SILVER, 0xB198, 0x2D69)}
GEN2_BOXES = 14
GEN2_PARTY_STRUCT, GEN2_LEVEL = 48, 31
GEN2_EGG = 0xFD
GEN2_LEAGUE_ROOMS = frozenset(range(16 * 256 + 3, 16 * 256 + 9))
# Event indices, shared by Gold, Silver and Crystal.
EVENT_FAST_SHIP_HAS_ARRIVED = 49
EVENT_RESTORED_POWER_TO_KANTO = 205
EVENTS_ELITE_FOUR = (1464, 1465, 1466, 1467)
# The credits after beating Red set this count, and only that many Elite Four wins also reach it.
HOF_MASTER_COUNT = 200


class SaveError(ValueError):
    """The file is not a save this module can trust."""


@dataclass(frozen=True)
class PartyMon:
    species: int                # the byte the game stores: internal index in Gen I, dex number in Gen II
    level: int
    name: str | None = None     # needs the ROM
    egg: bool = False


@dataclass(frozen=True)
class SaveSummary:
    generation: int
    version: str | None         # None for Red or Blue, and Gold or Silver, without the ROM
    player_name: str
    rival_name: str
    trainer_id: int
    badges: tuple[str, ...]     # every badge held, Johto first in Gen II
    johto_badges: tuple[str, ...]   # empty in Gen I
    kanto_badges: tuple[str, ...]   # empty in Gen I
    dex_owned: int
    dex_seen: int
    hall_of_fame: int           # the game's counter. Gen II sets it to 200 once Red is beaten.
    money: int
    play_time: tuple[int, int, int]     # hours, minutes, seconds
    party: tuple[PartyMon, ...]
    box_counts: tuple[int, ...]
    map_id: int                 # Gen II: group * 256 + number
    kanto_entered: bool         # Gen II only
    red_beaten: bool            # Gen II only
    stage: str

    @property
    def badge_count(self):
        return len(self.badges)

    @property
    def box_total(self):
        return sum(self.box_counts)

    def to_dict(self):
        return {**asdict(self), 'badge_count': self.badge_count, 'box_total': self.box_total}


def _bytes(source):
    return bytes(source) if isinstance(source, (bytes, bytearray, memoryview)) else Path(source).read_bytes()


def _bits(value, names):
    return tuple(name for bit, name in enumerate(names) if value >> bit & 1)


def _count(count):
    """A box count, with a box the game has not initialized yet read as empty."""
    return count if count <= BOX_CAPACITY else 0


def _gen1_valid(raw):
    return raw[GEN1_CHECKSUM] == ~sum(raw[GEN1_PLAYER_NAME:GEN1_CHECKSUM]) & 0xFF


def _gen2_layout(raw):
    """The layout key whose check bytes and checksum hold, or False."""
    if raw[GEN2_CHECK_1] != GEN2_CHECK_1_VALUE:
        return False
    for key, (symbols, _, end) in GEN2_LAYOUTS.items():
        at = symbols['sChecksum'][1] - 0xA000 + 0x2000
        if (raw[at + 2] == GEN2_CHECK_2_VALUE
                and int.from_bytes(raw[at:at + 2], 'little') == sum(raw[GEN2_DATA:end]) & 0xFFFF):
            return key
    return False


def _stage(party, badges, hall_of_fame, in_rooms, in_league, *, generation, kanto_entered=False, red_beaten=False):
    if generation == 2 and red_beaten:
        return 'red beaten'
    if generation == 2 and kanto_entered:
        return 'kanto entered'
    if hall_of_fame:
        return 'champion' if generation == 2 or in_league else 'post-game'
    if in_rooms:
        return 'league entered'
    if not party and not badges:
        return 'new game'
    return f'{badges} badge' if badges == 1 else f'{badges} badges'


def _gen1(raw, version, names):
    def at(address):
        return raw[address - GEN1_MAIN]

    def span(address, size):
        return raw[address - GEN1_MAIN:address - GEN1_MAIN + size]

    flags = span(W_EVENT_FLAGS, 0x140)
    boxes = at(W_CURRENT_BOX)
    active = boxes & 0x7F
    # Other boxes hold noise until the first box change, which also writes their checksums.
    changed = boxes & GEN1_HAS_CHANGED_BOXES
    if changed:
        for start in GEN1_BANKS:
            if raw[start + GEN1_BANK_CHECKSUM] != ~sum(raw[start:start + GEN1_BANK_CHECKSUM]) & 0xFF:
                raise SaveError('The save has a bad checksum in its Pokemon boxes, so it is corrupt.')
    counts = []
    for box in range(GEN1_BOXES):
        at_box = GEN1_BANKS[box // 6] + box % 6 * GEN1_BOX_SIZE
        counts.append(_count(raw[GEN1_ACTIVE_BOX] if box == active else raw[at_box] if changed else 0))
    count = min(raw[GEN1_PARTY], 6)
    party = tuple(_mon(raw[GEN1_PARTY + 8 + index * GEN1_PARTY_STRUCT],
                       raw[GEN1_PARTY + 8 + index * GEN1_PARTY_STRUCT + GEN1_LEVEL], names) for index in range(count))
    if version is None and at(W_PLAYER_STARTER) == STARTER_PIKACHU and at(W_RIVAL_STARTER) in RIVAL_STARTERS:
        version = 'yellow'
    badges = _bits(at(W_BADGES), BADGES[8:])
    hall_of_fame, map_id = at(W_HALL_OF_FAME_COUNT), at(W_CUR_MAP)
    elite = any(event_set(flags, index) for index in ELITE_FLAGS.values()) or event_set(flags, CHAMPION_FLAG)
    money = int(span(W_MONEY, 3).hex())
    return SaveSummary(
        1, version, decode_text(raw[GEN1_PLAYER_NAME:GEN1_PLAYER_NAME + 11]), decode_text(span(W_RIVAL_NAME, 11)),
        int.from_bytes(span(W_PLAYER_ID, 2), 'big'), badges, (), (),
        int.from_bytes(span(W_DEX_OWNED, 19), 'little').bit_count(),
        int.from_bytes(span(W_DEX_SEEN, 19), 'little').bit_count(), hall_of_fame, money,
        (at(W_PLAYTIME_H), at(W_PLAYTIME_H + 2), at(W_PLAYTIME_H + 3)), party, tuple(counts), map_id, False, False,
        _stage(party, len(badges), hall_of_fame, elite or map_id in GEN1_LEAGUE_ROOMS, map_id in GEN1_LEAGUE,
               generation=1))


def _gen2(raw, key, version, names):
    symbols, delta, _ = GEN2_LAYOUTS[key]
    table = charmap(version or 'gold')

    def span(name, size=1):
        at = symbols[name][1] - delta
        return raw[at:at + size]

    def text(name):
        return ''.join(table.get(value, '') for value in span(name, 11).split(b'\x50', 1)[0]).strip()

    def sram(name):
        bank, address = symbols[name]
        return raw[bank * 0x2000 + address - 0xA000]

    flags = span('wEventFlags', 256)
    active = span('wCurBox')[0] & 0x7F
    counts = tuple(_count(sram('sBox' if box == active else f'sBox{box + 1}')) for box in range(GEN2_BOXES))
    species = span('wPartySpecies', 6)
    mons = span('wPartyMons', 6 * GEN2_PARTY_STRUCT)
    party = tuple(_mon(mons[index * GEN2_PARTY_STRUCT], mons[index * GEN2_PARTY_STRUCT + GEN2_LEVEL], names,
                       egg=species[index] == GEN2_EGG) for index in range(min(span('wPartyCount')[0], 6)))
    johto = _bits(span('wJohtoBadges')[0], BADGES[:8])
    kanto = _bits(span('wKantoBadges')[0], BADGES[8:])
    hall_of_fame = span('wHallOfFameCount')[0]
    group, number = span('wMapGroup')[0], span('wMapNumber')[0]
    map_id = group * 256 + number
    red_beaten = hall_of_fame >= HOF_MASTER_COUNT
    kanto_entered = (bool(kanto) or red_beaten or event_set(flags, EVENT_FAST_SHIP_HAS_ARRIVED)
                     or event_set(flags, EVENT_RESTORED_POWER_TO_KANTO))
    elite = any(event_set(flags, index) for index in EVENTS_ELITE_FOUR)
    hours = int.from_bytes(span('wGameTimeHours', 2), 'big')
    return SaveSummary(
        2, version or key, text('wPlayerName'), text('wRivalName'), int.from_bytes(span('wPlayerID', 2), 'big'),
        johto + kanto, johto, kanto, int.from_bytes(span('wPokedexCaught', 32), 'little').bit_count(),
        int.from_bytes(span('wPokedexSeen', 32), 'little').bit_count(), hall_of_fame,
        int.from_bytes(span('wMoney', 3), 'big'), (hours, span('wGameTimeMinutes')[0], span('wGameTimeSeconds')[0]),
        party, counts, map_id, kanto_entered, red_beaten,
        _stage(party, len(johto), hall_of_fame, elite or map_id in GEN2_LEAGUE_ROOMS, map_id in GEN2_LEAGUE_ROOMS,
               generation=2, kanto_entered=kanto_entered, red_beaten=red_beaten))


def _mon(species, level, names, *, egg=False):
    name = 'EGG' if egg and names else names.get(species, {}).get('name') if names else None
    return PartyMon(species, level, name, egg)


def _rom_facts(rom):
    """The version and species table of a ROM, clean or randomized."""
    from . import romdata

    raw = _bytes(rom)
    cartridge = identify(raw) or resembles(raw)
    if cartridge is None:
        raise SaveError('The ROM is not a Pokemon Red, Blue, Yellow, Gold, Silver or Crystal cartridge.')
    return cartridge.version, cartridge.generation, romdata.load(raw, cartridge.version).species


def summarize_save(save, *, rom=None) -> SaveSummary:
    """Read a 32 KiB cartridge save, given as bytes or a path, into a :class:`SaveSummary`.

    Raises :class:`SaveError` for the wrong size, a bad checksum, or a ROM from the other
    generation. A save that fails its main checksum is refused even when a Gen II backup copy
    would still load on a console.
    """
    raw = _bytes(save)
    if len(raw) != SAVE_SIZE:
        raise SaveError(f'A cartridge save is {SAVE_SIZE} bytes. This file has {len(raw)}.')
    version, generation, names = _rom_facts(rom) if rom is not None else (None, None, None)
    key = _gen2_layout(raw)
    found = 2 if key is not False else 1 if _gen1_valid(raw) else None
    if found is None:
        raise SaveError('The save has a bad checksum, so it is corrupt, empty or not from these games.')
    if generation not in (None, found):
        raise SaveError(f'The ROM is a Generation {generation} game, but this save is from Generation {found}.')
    return _gen2(raw, key, version, names) if found == 2 else _gen1(raw, version, names)
