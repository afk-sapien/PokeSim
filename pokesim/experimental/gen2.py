"""Read-only Gen II exploration for three verified English retail ROMs.

These profiles are deliberately separate from the production ROM allowlist.
Addresses come from the pinned pret symbol files recorded in
docs/validation/gen2-symbols.json. Always read WRAM bank 1 explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import zipfile

ROM_SIZE = 2 * 1024 * 1024
PARTY_SIZE = 48


@dataclass(frozen=True)
class Layout:
    player_name: int
    map_group: int
    party_count: int
    party_mons: int
    party_nicknames: int
    caught: int
    seen: int
    badges: int
    battle_mode: int


GOLD_SILVER = Layout(0xD1A3, 0xDA00, 0xDA22, 0xDA2A, 0xDB8C, 0xDBE4, 0xDC04, 0xD57C, 0xD116)
CRYSTAL = Layout(0xD47D, 0xDCB5, 0xDCD7, 0xDCDF, 0xDE41, 0xDE99, 0xDEB9, 0xD857, 0xD22D)


@dataclass(frozen=True)
class Profile:
    game: str
    revision: str
    sha1: str
    layout: Layout
    symbols: str


PROFILES = (
    Profile('gold', 'USA, Europe', 'd8b8a3600a465308c9953dfa04f0081c05bdcb94', GOLD_SILVER, 'pokegold.sym'),
    Profile('silver', 'USA, Europe', '49b163f7e57702bc939d642a18f591de55d92dae', GOLD_SILVER, 'pokesilver.sym'),
    Profile('crystal', 'USA, Europe, Rev 1', 'f2f52230b536214ef7c9924f483392993e226cfb', CRYSTAL, 'pokecrystal11.sym'),
)


def identify(raw: bytes) -> Profile:
    digest = hashlib.sha1(raw).hexdigest()
    for profile in PROFILES:
        if len(raw) == ROM_SIZE and digest == profile.sha1:
            return profile
    raise ValueError(f'Unrecognized experimental Gen II ROM (sha1 {digest})')


def load_rom(path: Path) -> tuple[Profile, bytes]:
    """Read one bounded ROM from a local file or ZIP without extracting paths."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            candidates = [entry for entry in archive.infolist()
                          if not entry.is_dir() and Path(entry.filename).suffix.lower() in {'.gb', '.gbc'}]
            if len(candidates) != 1:
                raise ValueError('Choose a ZIP containing exactly one .gb or .gbc ROM')
            entry = candidates[0]
            if entry.file_size != ROM_SIZE:
                raise ValueError('Expected a 2 MiB Gen II ROM')
            with archive.open(entry) as source:
                raw = source.read(ROM_SIZE + 1)
    else:
        if path.stat().st_size != ROM_SIZE:
            raise ValueError('Expected a 2 MiB Gen II ROM')
        with path.open('rb') as source:
            raw = source.read(ROM_SIZE + 1)
    return identify(raw), raw


def decode_name(raw: bytes) -> str:
    """Decode the English name alphabet, preserving unknown bytes visibly."""
    letters = {**{0x80 + i: chr(65 + i) for i in range(26)},
               **{0xA0 + i: chr(97 + i) for i in range(26)},
               **{0xF6 + i: str(i) for i in range(10)}, 0x7F: ' '}
    result = []
    for value in raw:
        if value == 0x50:
            break
        result.append(letters.get(value, f'<{value:02x}>'))
    return ''.join(result)


def dex_flags(raw: bytes) -> tuple[int, ...]:
    return tuple(dex for dex in range(1, 252) if raw[(dex - 1) // 8] & (1 << ((dex - 1) % 8)))


@dataclass(frozen=True)
class PartyMon:
    species: int
    egg: bool
    nickname: str
    held_item: int
    moves: tuple[int, ...]
    level: int
    hp: int
    max_hp: int
    attack: int
    defense: int
    speed: int
    special_attack: int
    special_defense: int


@dataclass(frozen=True)
class Snapshot:
    game: str
    player_name: str
    map_group: int
    map_number: int
    x: int
    y: int
    johto_badges: int
    kanto_badges: int
    battle_mode: int
    party: tuple[PartyMon, ...]
    caught: tuple[int, ...]
    seen: tuple[int, ...]


def read_snapshot(memory, profile: Profile) -> Snapshot:
    """Observe initialized game state without changing the CPU's WRAM bank.

    This is a small diagnostic schema, not a production policy snapshot.
    No menus, collision, inventory, events, boxes or battle opponents are decoded.
    """
    layout = profile.layout

    def read(address, size):
        if size == 0:
            return b''
        return bytes(memory[1, address:address + size])

    count = read(layout.party_count, 1)[0]
    if count > 6:
        raise ValueError(f'Invalid Gen II party count {count}')
    party = []
    species_list = read(layout.party_count + 1, count)
    for slot in range(count):
        raw = read(layout.party_mons + slot * PARTY_SIZE, PARTY_SIZE)
        species = raw[0]
        if not 1 <= species <= 251:
            raise ValueError(f'Invalid Gen II species {species} in party slot {slot}')
        nick = decode_name(read(layout.party_nicknames + slot * 11, 11))
        stats = [int.from_bytes(raw[offset:offset + 2], 'big') for offset in range(34, 48, 2)]
        party.append(PartyMon(species, species_list[slot] == 0xFD, nick, raw[1], tuple(raw[2:6]), raw[31], *stats))
    group, number, y, x = read(layout.map_group, 4)
    johto, kanto = read(layout.badges, 2)
    return Snapshot(profile.game, decode_name(read(layout.player_name, 11)), group, number, x, y,
                    johto, kanto, read(layout.battle_mode, 1)[0], tuple(party),
                    dex_flags(read(layout.caught, 32)), dex_flags(read(layout.seen, 32)))
