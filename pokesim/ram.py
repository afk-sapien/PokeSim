"""Pokemon Red WRAM addresses and a typed snapshot reader.

Addresses are from the pret/pokered disassembly (wram.asm), cross-checked
against the community RAM map and verified in-emulator (see tests/).
"""
from __future__ import annotations

from pokesim_core import gen1 as core_gen1
from pokesim_core.gen1 import (
    W_TILEMAP as W_TILEMAP,
    W_ENEMY_SPECIES2 as W_ENEMY_SPECIES2,
    W_ENEMY_MON as W_ENEMY_MON,
    W_ENEMY_LEVEL as W_ENEMY_LEVEL,
    W_TRAINER_CLASS as W_TRAINER_CLASS,
    W_IS_IN_BATTLE as W_IS_IN_BATTLE,
    W_CUR_OPPONENT as W_CUR_OPPONENT,
    W_BATTLE_TYPE as W_BATTLE_TYPE,
    W_PLAYER_NAME as W_PLAYER_NAME,
    W_PARTY_COUNT as W_PARTY_COUNT,
    W_PARTY_SPECIES as W_PARTY_SPECIES,
    W_PARTY_MONS as W_PARTY_MONS,
    W_PARTY_NICKS as W_PARTY_NICKS,
    W_DEX_OWNED as W_DEX_OWNED,
    W_DEX_SEEN as W_DEX_SEEN,
    W_NUM_BAG_ITEMS as W_NUM_BAG_ITEMS,
    W_BAG_ITEMS as W_BAG_ITEMS,
    W_MONEY as W_MONEY,
    W_RIVAL_NAME as W_RIVAL_NAME,
    W_BADGES as W_BADGES,
    W_CUR_MAP as W_CUR_MAP,
    W_Y as W_Y,
    W_X as W_X,
    W_CURRENT_BOX as W_CURRENT_BOX,
    W_BOX_COUNT as W_BOX_COUNT,
    BOX_CAPACITY as BOX_CAPACITY,
    BOX_COUNT as BOX_COUNT,
    BOX_DATA_SIZE as BOX_DATA_SIZE,
    W_TOGGLE_OBJECT_FLAGS as W_TOGGLE_OBJECT_FLAGS,
    W_EVENT_FLAGS as W_EVENT_FLAGS,
    W_STATUS_FLAGS1 as W_STATUS_FLAGS1,
    W_PLAYTIME_H as W_PLAYTIME_H,
    PARTY_STRUCT as PARTY_STRUCT,
    TILE_BOX_TL as TILE_BOX_TL,
    decode_text as decode_text,
    bcd as bcd,
    flag_bits as flag_bits,
    individual_data as individual_data,
)

from .game_data import load
from dataclasses import dataclass, fields
from functools import lru_cache
from pokesim_core.storage import decode_box, memory_bytes

TABLES = load("tables.json")
MAP_NAMES = {int(k): v for k, v in TABLES["maps"].items()}
SPECIES_NAMES = {int(k): v for k, v in TABLES["species"].items()}
DEX_NAMES = {int(k): v for k, v in TABLES["dex"].items()}
ITEM_NAMES = {int(k): v for k, v in TABLES["items"].items()}
TRAINER_NAMES = {int(k): v for k, v in TABLES["trainers"].items()}
MOVES = {int(k): v for k, v in TABLES.get("moves", {}).items()}   # id -> {name, power, type, effect}
BADGES = TABLES["badges"]
LEADERS = TABLES["leaders"]
KEY_ITEM_IDS = set(TABLES["key_item_ids"])
NOTABLE_TRAINERS = set(TABLES["notable_trainers"])
HALL_OF_FAME_MAP = TABLES["hall_of_fame_map"]


@dataclass(frozen=True)
class PartyMon:
    species: int
    hp: int
    max_hp: int
    level: int
    nick: str
    status: int = 0
    types: tuple[int, ...] = ()
    moves: tuple[int, ...] = ()
    pp: tuple[int, ...] = ()
    attack: int = 1
    defense: int = 1
    speed: int = 1
    special: int = 1
    experience: int = 0
    max_pp: tuple[int, ...] = ()
    dvs: tuple[int, ...] = ()
    stat_exp: tuple[int, ...] = ()
    trainer_id: int | None = None

    @property
    def pending(self) -> bool:
        """A counted slot whose 44-byte struct the cartridge has not filled in yet.

        AddPartyMon raises wPartyCount and writes wPartySpecies before the nickname
        screen, but only copies the struct at wPartyMons afterwards, so a Pokémon
        being named reads as species 0 for as long as the naming screen is up.
        """
        return self.species == 0

    @property
    def name(self) -> str:
        if self.pending:
            return "Joining the team"
        return SPECIES_NAMES.get(self.species, f"#{self.species}")


@dataclass(frozen=True)
class StoredMon:
    box: int
    position: int
    species: int
    level: int
    nick: str
    moves: tuple[int, ...]
    experience: int
    dvs: tuple[int, ...]
    stat_exp: tuple[int, ...]
    trainer_id: int | None = None


_STORED_FIELDS = tuple(field.name for field in fields(StoredMon))


@dataclass(frozen=True)
class Snapshot:
    frame: int
    map: int
    x: int
    y: int
    badges: int
    party: tuple[PartyMon, ...]
    owned: frozenset[int]
    seen: frozenset[int]
    money: int
    items: tuple[tuple[int, int], ...]
    in_battle: int
    battle_type: int
    enemy_species: int
    enemy_level: int
    opponent: int
    player_name: str
    rival_name: str
    playtime: tuple[int, int, int]   # h, m, s
    textbox: bool
    start_menu: bool
    event_flags: bytes = b""
    saffron_open: bool = False
    hidden_objects: bytes = b""
    boxed_pokemon: tuple[tuple[int, int], ...] = ()
    hall_of_fame_count: int = 0
    coins: int = 0
    active_box: int = 0
    stored_pokemon: tuple[tuple[int, int, int, str], ...] = ()
    box_counts: tuple[int, ...] = ()
    stored_details: tuple[StoredMon, ...] = ()

    def storage_entries(self):
        """Expose individual data while preserving legacy compact storage snapshots."""
        if self.stored_details and self.stored_pokemon == tuple(
                (mon.box, mon.species, mon.level, mon.nick) for mon in self.stored_details):
            # All StoredMon fields are immutable. Only the outer rows need copies.
            return [{name: getattr(mon, name) for name in _STORED_FIELDS} for mon in self.stored_details]
        positions, out = {}, []
        for box, species, level, nick in self.stored_pokemon:
            position = positions.get(box, 0)
            positions[box] = position + 1
            row = {'box': box, 'position': position, 'species': species, 'level': level, 'nick': nick}
            out.append(row)
        return out

    @property
    def box_full(self) -> bool:
        return len(self.boxed_pokemon) >= BOX_CAPACITY

    @property
    def can_catch(self) -> bool:
        return len(self.party) < 6 or not self.box_full

    @property
    def next_free_box(self) -> int | None:
        return next((i for i, count in enumerate(self.box_counts)
                     if i != self.active_box and 0 <= count < BOX_CAPACITY), None)

    @property
    def started(self) -> bool:
        """True once the player has control (past the intro / naming screens)."""
        # Not keyed on the player name: some names decode to nothing (empty names are possible in hacks).
        return self.map != 0 or self.playtime_seconds > 0 or len(self.party) > 0

    @property
    def valid(self) -> bool:
        """Sanity check that WRAM still looks like a running game (a glitched/crashed game fills it with junk)."""
        h, m, sec = self.playtime
        if self.map not in MAP_NAMES or self.in_battle not in (0, 1, 2, 0xFF) or m > 59 or sec > 59:
            return False
        if any(p.species not in SPECIES_NAMES or p.level > 100 or p.hp > p.max_hp for p in self.party):
            return False
        if self.in_battle in (1, 2) and not self.party and self.started:
            return False        # a battle with no Pokémon is a softlock
        return True

    @property
    def map_name(self) -> str:
        return MAP_NAMES.get(self.map, f"Map {self.map}")

    @property
    def badge_list(self) -> list[str]:
        return [BADGES[i] for i in range(8) if self.badges & (1 << i)]

    @property
    def trainer_class(self) -> int | None:
        return self.opponent - 200 if self.in_battle == 2 and self.opponent >= 200 else None

    @property
    def playtime_seconds(self) -> int:
        h, m, s = self.playtime
        return h * 3600 + m * 60 + s

    @property
    def all_fainted(self) -> bool:
        # A Pokémon still on the naming screen reads as an empty struct, so counting it
        # would report a blackout for a team that has not fought anything yet.
        decoded = [p for p in self.party if not p.pending]
        return bool(decoded) and all(p.hp == 0 for p in decoded)

    def to_dict(self) -> dict:
        from .pokemon import party_details
        return {
            "frame": self.frame, "map": self.map, "map_name": self.map_name, "x": self.x, "y": self.y,
            "badges": self.badge_list,
            "party": [{"species": p.species, "name": p.name, "nick": p.nick, "level": p.level,
                       "hp": p.hp, "max_hp": p.max_hp, "status": p.status, "pending": p.pending,
                       "types": p.types, "moves": p.moves, "pp": p.pp, **party_details(p)} for p in self.party],
            "hall_of_fame_count": self.hall_of_fame_count, "coins": self.coins,
            "owned": len(self.owned), "seen": len(self.seen), "money": self.money,
            "dex_owned": sorted(self.owned), "dex_seen": sorted(self.seen),
            "items": [{"id": i, "name": ITEM_NAMES.get(i, f"#{i}"), "qty": q} for i, q in self.items],
            "in_battle": self.in_battle, "enemy": SPECIES_NAMES.get(self.enemy_species) if self.in_battle else None,
            "enemy_level": self.enemy_level if self.in_battle else None,
            "opponent": TRAINER_NAMES.get(self.trainer_class) if self.trainer_class is not None else None,
            "player_name": self.player_name, "rival_name": self.rival_name,
            "playtime": "%d:%02d:%02d" % self.playtime, "playtime_seconds": self.playtime_seconds,
            "textbox": self.textbox, "start_menu": self.start_menu,
            "saffron_open": self.saffron_open,
            "storage": {"active_box": self.active_box + 1,
                        "count": len(self.boxed_pokemon), "capacity": BOX_CAPACITY,
                        "box_counts": self.box_counts, "can_catch": self.can_catch,
                        "pokemon": [{**mon, "box": mon['box'] + 1, "position": mon['position'] + 1,
                                     "name": SPECIES_NAMES.get(mon['species'], "Unknown")}
                                    for mon in self.storage_entries()]},
        }


def read_box_counts(mem) -> tuple[int, ...]:
    current = mem[W_CURRENT_BOX]
    active = current & 0x7F
    if active >= BOX_COUNT:
        return ()
    counts = [0] * BOX_COUNT
    if current & 0x80:
        try:
            counts = [mem[2 + i // 6, 0xA000 + (i % 6) * BOX_DATA_SIZE]
                      for i in range(BOX_COUNT)]
        except TypeError:
            # Flat test memory cannot expose cartridge RAM banks.
            counts = [BOX_CAPACITY] * BOX_COUNT
    counts[active] = min(mem[W_BOX_COUNT], BOX_CAPACITY)
    return tuple(counts)


def read_stored_pokemon(mem):
    return tuple((mon.box, mon.species, mon.level, mon.nick) for mon in read_stored_details(mem))


@lru_cache(maxsize=128)
def _decode_box(box, structs, names):
    """Cache immutable records by their bytes, never by emulator identity or time."""
    return tuple(StoredMon(box, mon.position, mon.species, mon.level, mon.nick,
                           mon.moves, mon.experience, mon.dvs, mon.stat_exp, mon.trainer_id)
                 for mon in decode_box(structs, names)
                 if mon.species in SPECIES_NAMES and 1 <= mon.level <= 100)


_box_bytes = memory_bytes


def read_stored_details(mem, *, counts=None):
    counts = read_box_counts(mem) if counts is None else counts
    active = mem[W_CURRENT_BOX] & 0x7F
    out = []
    for box, count in enumerate(counts):
        count = min(count, BOX_CAPACITY)
        if not count:
            continue
        base = W_BOX_COUNT if box == active else 0xA000 + (box % 6) * BOX_DATA_SIZE
        bank = None if box == active else 2 + box // 6
        try:
            structs = _box_bytes(mem, bank, base + 22, count * 33)
            names = _box_bytes(mem, bank, base + 902, count * 11)
        except TypeError:
            # Flat memory has no inactive cartridge banks.
            continue
        out.extend(_decode_box(box, structs, names))
    return tuple(out)


def read_snapshot(mem, frame: int) -> Snapshot:
    """mem: anything supporting mem[addr] and mem[a:b] over the GB address space (pyboy.memory)."""
    from .strategy_data import MOVES as MOVE_DATA
    party = tuple(PartyMon(**mon) for mon in core_gen1.read_party(mem, move_data=MOVE_DATA))
    items = core_gen1.read_bag(mem)
    in_battle = mem[W_IS_IN_BATTLE]
    box_counts = read_box_counts(mem)
    stored = read_stored_details(mem, counts=box_counts)
    # Every cartridge path that registers a species also marks it seen, so an owned flag
    # without its seen flag is not Pokédex data at all. Oak's lab leaves other values in
    # this region for a couple of seconds before the Pokédex exists, which otherwise reads
    # as owning four starters at once.
    seen_dex = flag_bits(bytes(mem[W_DEX_SEEN:W_DEX_SEEN + 19]))
    owned_dex = flag_bits(bytes(mem[W_DEX_OWNED:W_DEX_OWNED + 19])) & seen_dex
    return Snapshot(
        frame=frame,
        map=mem[W_CUR_MAP], x=mem[W_X], y=mem[W_Y],
        badges=mem[W_BADGES],
        saffron_open=bool(mem[W_STATUS_FLAGS1] & 64),
        party=party,
        owned=frozenset(owned_dex),
        seen=frozenset(seen_dex),
        money=bcd(bytes(mem[W_MONEY:W_MONEY + 3])),
        items=items,
        in_battle=in_battle,
        battle_type=mem[W_BATTLE_TYPE],
        enemy_species=mem[W_ENEMY_MON] if in_battle else 0,
        enemy_level=mem[W_ENEMY_LEVEL] if in_battle else 0,
        opponent=mem[W_CUR_OPPONENT],
        player_name=decode_text(bytes(mem[W_PLAYER_NAME:W_PLAYER_NAME + 11])),
        rival_name=decode_text(bytes(mem[W_RIVAL_NAME:W_RIVAL_NAME + 11])),
        playtime=(mem[W_PLAYTIME_H], mem[W_PLAYTIME_H + 2], mem[W_PLAYTIME_H + 3]),
        textbox=mem[W_TILEMAP + 12 * 20] == TILE_BOX_TL,
        start_menu=mem[W_TILEMAP + 10] == TILE_BOX_TL and not in_battle,
        boxed_pokemon=tuple((mem[0xDA96 + i * 33], mem[0xDA99 + i * 33]) for i in range(min(mem[0xDA80], 20))),
        active_box=mem[W_CURRENT_BOX] & 0x7F,
        hall_of_fame_count=mem[0xD5A2],
        coins=bcd(bytes(mem[0xD5A4:0xD5A6])),
        box_counts=box_counts,
        stored_pokemon=tuple((mon.box, mon.species, mon.level, mon.nick) for mon in stored),
        stored_details=stored,
        hidden_objects=bytes(mem[W_TOGGLE_OBJECT_FLAGS:W_TOGGLE_OBJECT_FLAGS + 32]),
        event_flags=bytes(mem[W_EVENT_FLAGS:W_EVENT_FLAGS + 0x140]),
    )
