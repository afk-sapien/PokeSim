"""Pokemon Red WRAM addresses and a typed snapshot reader.

Addresses are from the pret/pokered disassembly (wram.asm), cross-checked
against the community RAM map and verified in-emulator (see tests/).
"""
from __future__ import annotations

from .game_data import load
from dataclasses import dataclass, field
from pathlib import Path

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

# --- WRAM ---
W_TILEMAP = 0xC3A0          # 20x18 screen tiles
W_ENEMY_SPECIES2 = 0xCFD8
W_ENEMY_MON = 0xCFE5        # enemy battle struct: species at +0
W_ENEMY_LEVEL = 0xCFF3
W_TRAINER_CLASS = 0xD031
W_IS_IN_BATTLE = 0xD057     # 0 none, 1 wild, 2 trainer, 0xFF lost
W_CUR_OPPONENT = 0xD059     # species (wild) or 200 + trainer class
W_BATTLE_TYPE = 0xD05A      # 0 normal, 1 old man, 2 safari
W_PLAYER_NAME = 0xD158      # 11 bytes, 0x50 terminated
W_PARTY_COUNT = 0xD163
W_PARTY_SPECIES = 0xD164    # 6 + 0xFF
W_PARTY_MONS = 0xD16B       # 6 x 44-byte party structs
W_PARTY_NICKS = 0xD2B5      # 6 x 11 bytes
W_DEX_OWNED = 0xD2F7        # 19 bytes flag array
W_DEX_SEEN = 0xD30A         # 19 bytes flag array
W_NUM_BAG_ITEMS = 0xD31D
W_BAG_ITEMS = 0xD31E        # (id, qty) pairs, 0xFF terminated, max 20
W_MONEY = 0xD347            # 3 bytes BCD
W_RIVAL_NAME = 0xD34A
W_BADGES = 0xD356
W_CUR_MAP = 0xD35E
W_Y = 0xD361
W_X = 0xD362
W_CURRENT_BOX = 0xD5A0
W_BOX_COUNT = 0xDA80
BOX_CAPACITY = 20
BOX_COUNT = 12
BOX_DATA_SIZE = 1122
W_TOGGLE_OBJECT_FLAGS = 0xD5A6  # 32 bytes, set bits hide objects
W_EVENT_FLAGS = 0xD747      # .. 0xD886
W_STATUS_FLAGS1 = W_EVENT_FLAGS - 31
W_PLAYTIME_H = 0xDA41       # hours, maxed, minutes, seconds, frames
PARTY_STRUCT = 44

# Text box border tiles (font tileset)
TILE_BOX_TL = 0x79

_CHARS = {0x50: "", 0x7F: " ", 0xBA: "é", 0xE0: "'", 0xE3: "-", 0xE6: "?", 0xE7: "!", 0xE8: ".",
          0xEF: "♂", 0xF4: ",", 0xF5: "♀", 0xF2: ".", 0xF1: "×", 0xE1: "PK", 0xE2: "MN", 0xF0: "$"}


def decode_text(b: bytes) -> str:
    out = []
    for c in b:
        if c == 0x50:
            break
        if 0x80 <= c <= 0x99:
            out.append(chr(ord("A") + c - 0x80))
        elif 0xA0 <= c <= 0xB9:
            out.append(chr(ord("a") + c - 0xA0))
        elif 0xF6 <= c <= 0xFF:
            out.append(chr(ord("0") + c - 0xF6))
        elif c in _CHARS:
            out.append(_CHARS[c])
        elif c == 0:
            break
        elif c >= 0x60:
            out.append("?")     # unmapped glyph (symbols, ROM-hack fonts): keep the length, don't drop the name
    return "".join(out).strip()


def bcd(b: bytes) -> int:
    n = 0
    for c in b:
        n = n * 100 + (c >> 4) * 10 + (c & 0xF)
    return n


def flag_bits(b: bytes) -> set[int]:
    """Return 1-based indices of set bits in a little-endian flag array."""
    out = set()
    for i, byte in enumerate(b):
        for bit in range(8):
            if byte & (1 << bit):
                out.add(i * 8 + bit + 1)
    return out


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

    @property
    def name(self) -> str:
        return SPECIES_NAMES.get(self.species, f"#{self.species}")


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
        return bool(self.party) and all(p.hp == 0 for p in self.party)

    def to_dict(self) -> dict:
        from .pokemon import party_details
        return {
            "frame": self.frame, "map": self.map, "map_name": self.map_name, "x": self.x, "y": self.y,
            "badges": self.badge_list,
            "party": [{"species": p.species, "name": p.name, "nick": p.nick, "level": p.level,
                       "hp": p.hp, "max_hp": p.max_hp, "status": p.status,
                       "types": p.types, "moves": p.moves, "pp": p.pp, **party_details(p)} for p in self.party],
            "hall_of_fame_count": self.hall_of_fame_count, "coins": self.coins,
            "owned": len(self.owned), "seen": len(self.seen), "money": self.money,
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
                        "pokemon": [{"box": box + 1, "species": sid, "level": level, "nick": nick,
                                     "name": SPECIES_NAMES.get(sid, "Unknown")}
                                    for box, sid, level, nick in self.stored_pokemon]},
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
    counts = read_box_counts(mem)
    active = mem[W_CURRENT_BOX] & 0x7F
    out = []
    for box, count in enumerate(counts):
        for i in range(min(count, BOX_CAPACITY)):
            if box == active:
                base = W_BOX_COUNT
                get = lambda address: mem[address]
            else:
                base = 0xA000 + (box % 6) * BOX_DATA_SIZE
                get = lambda address: mem[2 + box // 6, address]
            try:
                sid = get(base + 22 + i * 33)
                level = get(base + 25 + i * 33)
                nick = decode_text(bytes(get(base + 902 + i * 11 + j) for j in range(11)))
            except TypeError:
                break
            if sid in SPECIES_NAMES and 1 <= level <= 100:
                out.append((box, sid, level, nick))
    return tuple(out)


def read_snapshot(mem, frame: int) -> Snapshot:
    """mem: anything supporting mem[addr] and mem[a:b] over the GB address space (pyboy.memory)."""
    count = min(mem[W_PARTY_COUNT], 6)
    party = []
    from .strategy_data import MOVES as MOVE_DATA
    for i in range(count):
        base = W_PARTY_MONS + i * PARTY_STRUCT
        s = bytes(mem[base:base + PARTY_STRUCT])
        nick = decode_text(bytes(mem[W_PARTY_NICKS + i * 11:W_PARTY_NICKS + i * 11 + 11]))
        party.append(PartyMon(species=s[0], hp=(s[1] << 8) | s[2], max_hp=(s[0x22] << 8) | s[0x23],
                              level=s[0x21], nick=nick, status=s[4], types=(s[5], s[6]),
                              moves=tuple(s[8:12]), pp=tuple(v & 0x3F for v in s[29:33]),
                              attack=int.from_bytes(s[36:38], "big"), defense=int.from_bytes(s[38:40], "big"),
                              speed=int.from_bytes(s[40:42], "big"), special=int.from_bytes(s[42:44], "big"),
                              experience=int.from_bytes(s[14:17], "big"),
                              max_pp=tuple(MOVE_DATA.get(mid, {}).get("pp", 0) +
                                           min(7, MOVE_DATA.get(mid, {}).get("pp", 0) // 5) * (s[29 + j] >> 6)
                                           for j, mid in enumerate(s[8:12]))))
    n_items = min(mem[W_NUM_BAG_ITEMS], 20)
    raw = bytes(mem[W_BAG_ITEMS:W_BAG_ITEMS + n_items * 2]) if n_items else b""
    items = tuple((raw[i], raw[i + 1]) for i in range(0, len(raw), 2) if raw[i] not in (0, 0xFF))
    in_battle = mem[W_IS_IN_BATTLE]
    return Snapshot(
        frame=frame,
        map=mem[W_CUR_MAP], x=mem[W_X], y=mem[W_Y],
        badges=mem[W_BADGES],
        saffron_open=bool(mem[W_STATUS_FLAGS1] & 64),
        party=tuple(party),
        owned=frozenset(flag_bits(bytes(mem[W_DEX_OWNED:W_DEX_OWNED + 19]))),
        seen=frozenset(flag_bits(bytes(mem[W_DEX_SEEN:W_DEX_SEEN + 19]))),
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
        box_counts=read_box_counts(mem),
        stored_pokemon=read_stored_pokemon(mem),
        hidden_objects=bytes(mem[W_TOGGLE_OBJECT_FLAGS:W_TOGGLE_OBJECT_FLAGS + 32]),
        event_flags=bytes(mem[W_EVENT_FLAGS:W_EVENT_FLAGS + 0x140]),
    )
