"""Versioned constants generated from the Pokémon Red disassembly."""
from .game_data import load

DATA = load("strategy.json")
MOVES = {int(k): v for k, v in DATA["moves"].items()}
SPECIES = {int(k): v for k, v in DATA["species"].items()}
WORLD = {int(k): v for k, v in DATA["world"].items()}
MAPS = DATA["maps"]
ITEMS = DATA["items"]
EVENTS = DATA["events"]
PRICES = {int(k): v for k, v in DATA["prices"].items()}
MATCHUPS = {(a, b): factor for a, b, factor in DATA["matchups"]}


def normalize_toggle_objects(rows):
    """Keep the unused cartridge entry so every subsequent flag keeps its real bit."""
    rows = [list(row) for row in rows]
    unused = [MAPS['UNUSED_MAP_F4'], 1]
    if unused not in rows:
        index = next(i for i, (m, _) in enumerate(rows) if m == MAPS['POKEMON_MANSION_2F'])
        rows.insert(index, unused)
    return rows


# Older verified bundles omitted the numeric object ID in UNUSED_MAP_F4.
# Normalize in memory so upgrades also fix existing installations without rewriting bundles.
DATA['toggle_objects'] = normalize_toggle_objects(DATA['toggle_objects'])


def event_set(flags: bytes, name: str) -> bool:
    index = EVENTS[name]
    return index // 8 < len(flags) and bool(flags[index // 8] & (1 << (index % 8)))


def object_hidden(snapshot, map_id, object_index):
    index = DATA["toggle_objects"].index([map_id, object_index])
    return (index // 8 < len(snapshot.hidden_objects)
            and bool(snapshot.hidden_objects[index // 8] & (1 << (index % 8))))
