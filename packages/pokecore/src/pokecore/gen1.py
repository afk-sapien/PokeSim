"""Read-only Generation I memory primitives for English Red, Blue and Yellow.

Derived from PokeSim. Addresses correspond to pret/pokered revision
a1a22aaf84d1675bcdbaeb194592379d586d838e. No game tables are bundled.

Every address here is a Red address. Readers take ``version``: for 'yellow'
they read raw Yellow memory through ``yellow.red_layout``. Passing a view that
is already Red-layout, such as a ``YellowEmulator``'s memory, also works with
the default version.
"""
from .yellow import red_layout

W_TILEMAP = 0xC3A0

W_ENEMY_SPECIES2 = 0xCFD8

W_ENEMY_MON = 0xCFE5

W_ENEMY_LEVEL = 0xCFF3

W_TRAINER_CLASS = 0xD031

W_IS_IN_BATTLE = 0xD057

W_CUR_OPPONENT = 0xD059

W_BATTLE_TYPE = 0xD05A

W_PLAYER_NAME = 0xD158

W_PARTY_COUNT = 0xD163

W_PARTY_SPECIES = 0xD164

W_PARTY_MONS = 0xD16B

W_PARTY_NICKS = 0xD2B5

W_DEX_OWNED = 0xD2F7

W_DEX_SEEN = 0xD30A

W_NUM_BAG_ITEMS = 0xD31D

W_BAG_ITEMS = 0xD31E

W_MONEY = 0xD347

W_RIVAL_NAME = 0xD34A

W_PLAYER_ID = 0xD359

W_PARTY_OT = 0xD273

W_RIVAL_STARTER = 0xD715

W_PLAYER_STARTER = 0xD717

W_BADGES = 0xD356

W_CUR_MAP = 0xD35E

W_Y = 0xD361

W_X = 0xD362

W_CURRENT_BOX = 0xD5A0

W_BOX_COUNT = 0xDA80

BOX_CAPACITY = 20

BOX_COUNT = 12

BOX_DATA_SIZE = 1122

W_TOGGLE_OBJECT_FLAGS = 0xD5A6

W_EVENT_FLAGS = 0xD747

W_STATUS_FLAGS1 = W_EVENT_FLAGS - 31

W_PLAYTIME_H = 0xDA41

# Overworld, menu and battle state, by pret/pokered name. Bits count from 0.
# wSpritePlayerStateData1FacingDirection: a key of FACINGS.
W_FACING = 0xC109
FACINGS = {0: 'down', 4: 'up', 8: 'left', 12: 'right'}
# wSpriteStateData2: 16 sprites of SPRITE_STRUCT bytes, the player first, then map objects.
# The map Y and X bytes count 2x2 blocks from 4. See sprite_tile.
W_SPRITE_STATE_DATA2 = 0xC200
SPRITE_STRUCT = 16
SPRITE_MAP_Y, SPRITE_MAP_X = 4, 5
# wWalkCounter: nonzero while a step animation runs.
W_WALK_COUNTER = 0xCFC5
# wWhichPokemon: the party or box slot the last menu chose, from 0.
W_WHICH_POKEMON = 0xCF92
# wPlayerDisabledMove: the disabled move (1 to 4) in the high nibble, turns left in the low nibble.
W_PLAYER_DISABLED_MOVE = 0xD06D
# wMoveNum: the move the move menus and the move relearner work on.
W_MOVE_NUM = 0xD0E0
# wWalkBikeSurfState: 0 walking, 1 biking, 2 surfing.
W_WALK_BIKE_SURF_STATE = 0xD700
# Bits of W_STATUS_FLAGS1 and wMovementFlags.
BIT_STRENGTH_ACTIVE = 0
BIT_GAVE_SAFFRON_GUARDS_DRINK = 6
W_MOVEMENT_FLAGS = 0xD736
BIT_SPINNING = 7    # riding the arrow tiles in the Rocket Hideout and Viridian Gym

PARTY_STRUCT = 44

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

_SET_BITS = tuple(tuple(bit for bit in range(8) if value & (1 << bit)) for value in range(256))

def flag_bits(b: bytes) -> set[int]:
    """Return 1-based indices of set bits in a little-endian flag array."""
    out = set()
    for i, byte in enumerate(b):
        if byte:
            base = i * 8 + 1
            out.update(base + bit for bit in _SET_BITS[byte])
    return out

def individual_data(struct):
    """Decode shared party/box fields, with stats ordered HP, Attack, Defense, Speed, Special."""
    attack, defense = struct[27] >> 4, struct[27] & 15
    speed, special = struct[28] >> 4, struct[28] & 15
    hp = ((attack & 1) << 3) | ((defense & 1) << 2) | ((speed & 1) << 1) | (special & 1)
    return {'moves': tuple(struct[8:12]), 'trainer_id': int.from_bytes(struct[12:14], 'big'),
            'experience': int.from_bytes(struct[14:17], 'big'),
            'dvs': (hp, attack, defense, speed, special),
            'stat_exp': tuple(int.from_bytes(struct[i:i + 2], 'big') for i in range(17, 27, 2))}

W_HALL_OF_FAME_COUNT = 0xD5A2
W_COINS = 0xD5A4
HALL_OF_FAME_MAP = 118
BADGES = ("Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth")
GYM_FLAGS = (119, 191, 359, 425, 601, 865, 665, 81)
ELITE_FLAGS = {"Lorelei": 2273, "Bruno": 2281, "Agatha": 2289, "Lance": 2297}
STORY_FLAGS = {"starter": 34, "pokedex": 37, "silph_co": 1935, "surf": 2176}
CHAMPION_FLAG = 2305


def read_party(memory, move_data=None, *, version=None) -> list[dict]:
    """Decode all counted party slots, including pending zero-species slots.

    Returns numerical fields without species or move name tables. move_data may
    map integer move IDs to mappings containing base pp for maximum PP decoding.
    No field is dropped because of invalid or half-written game data. Consumers
    choose their own validation and observation filtering.
    """
    memory = red_layout(memory, version)
    move_data = move_data or {}
    party = []
    for index in range(min(memory[W_PARTY_COUNT], 6)):
        base = W_PARTY_MONS + index * PARTY_STRUCT
        block = bytes(memory[base:base + PARTY_STRUCT])
        nick_start = W_PARTY_NICKS + index * 11
        party.append({
            "species": block[0], "hp": int.from_bytes(block[1:3], "big"),
            "max_hp": int.from_bytes(block[34:36], "big"), "level": block[33],
            "nick": decode_text(memory[nick_start:nick_start + 11]), "status": block[4],
            "types": (block[5], block[6]), "pp": tuple(value & 63 for value in block[29:33]),
            "attack": int.from_bytes(block[36:38], "big"), "defense": int.from_bytes(block[38:40], "big"),
            "speed": int.from_bytes(block[40:42], "big"), "special": int.from_bytes(block[42:44], "big"),
            **individual_data(block),
            "max_pp": tuple(move_data.get(move, {}).get("pp", 0)
                            + min(7, move_data.get(move, {}).get("pp", 0) // 5) * (block[29 + i] >> 6)
                            for i, move in enumerate(block[8:12])),
        })
    return party


def read_bag(memory, *, version=None) -> tuple[tuple[int, int], ...]:
    """Decode bag entries, limiting reads to the cartridge's twenty slots."""
    memory = red_layout(memory, version)
    count = min(memory[W_NUM_BAG_ITEMS], 20)
    raw = bytes(memory[W_BAG_ITEMS:W_BAG_ITEMS + count * 2]) if count else b""
    return tuple((raw[index], raw[index + 1]) for index in range(0, len(raw), 2)
                 if raw[index] not in (0, 255))


def sprite_tile(memory, sprite: int, *, version=None) -> tuple[int, int]:
    """(x, y) map tile of sprite slot ``sprite``: 0 is the player, 1 to 15 the map's objects in order."""
    memory = red_layout(memory, version)
    base = W_SPRITE_STATE_DATA2 + sprite * SPRITE_STRUCT
    return memory[base + SPRITE_MAP_X] - 4, memory[base + SPRITE_MAP_Y] - 4


def event_set(flags, index: int) -> bool:
    """Read a zero-based event index, distinct from the one-based flag_bits helper."""
    if type(index) is not int or index < 0 or index >= len(flags) * 8:
        raise ValueError("Event index is outside the supplied flag array")
    return bool(flags[index // 8] & (1 << (index % 8)))


def read_progress(memory, *, version=None) -> dict:
    """Read progress facts without scoring or deciding game completion.

    The valid field is a lightweight party sanity check, not a proof that the
    entire machine state is valid. Callers must confirm transitions over time.
    Yellow uses the same event indices as Red and Blue.
    """
    memory = red_layout(memory, version)
    flags = bytes(memory[W_EVENT_FLAGS:W_EVENT_FLAGS + 0x140])
    count = memory[W_PARTY_COUNT]
    valid = 1 <= count <= 6 and all(
        1 <= memory[W_PARTY_MONS + index * PARTY_STRUCT] <= 190
        and 1 <= memory[W_PARTY_MONS + index * PARTY_STRUCT + 33] <= 100
        for index in range(min(count, 6))
    )
    return {
        "valid": valid,
        "badges": memory[W_BADGES],
        "gym_flags": [event_set(flags, index) for index in GYM_FLAGS],
        "elite": {name: event_set(flags, index) for name, index in ELITE_FLAGS.items()},
        "champion": event_set(flags, CHAMPION_FLAG),
        "hall_of_fame": memory[W_HALL_OF_FAME_COUNT],
        "map_id": memory[W_CUR_MAP],
        "story": {name: event_set(flags, index) for name, index in STORY_FLAGS.items()},
    }


# Yellow stores which way the rival's Eevee evolves, not a species.
YELLOW_RIVAL_EVOLUTIONS = {1: "jolteon", 2: "flareon", 3: "vaporeon"}


def read_starters(memory, *, version=None) -> dict:
    """Read the starter bytes the cartridge keeps for later rival battles.

    ``player`` and, in Red and Blue, ``rival`` are internal species IDs. Yellow's
    ``rival`` byte is 1, 2 or 3 and ``rival_evolution`` names the Eevee evolution
    it selects. Bytes are raw and are zero before Oak's lab.
    """
    yellow = getattr(version, "version", version) == "yellow"
    memory = red_layout(memory, version)
    rival = memory[W_RIVAL_STARTER]
    return {"player": memory[W_PLAYER_STARTER], "rival": rival,
            "rival_evolution": YELLOW_RIVAL_EVOLUTIONS.get(rival) if yellow else None,
            "player_id": int.from_bytes(bytes(memory[W_PLAYER_ID:W_PLAYER_ID + 2]), "big")}


def read_trainers(memory, *, version=None) -> dict:
    """Player name, rival name and player trainer ID."""
    memory = red_layout(memory, version)
    return {"player": decode_text(bytes(memory[W_PLAYER_NAME:W_PLAYER_NAME + 11])),
            "rival": decode_text(bytes(memory[W_RIVAL_NAME:W_RIVAL_NAME + 11])),
            "trainer_id": int.from_bytes(bytes(memory[W_PLAYER_ID:W_PLAYER_ID + 2]), "big")}
