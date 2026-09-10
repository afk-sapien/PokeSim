"""Versioned constants generated from the Pokémon Red disassembly."""
from .game_data import load
from pathlib import Path

DATA = load("strategy.json")
MOVES = {int(k): v for k, v in DATA["moves"].items()}
SPECIES = {int(k): v for k, v in DATA["species"].items()}
WORLD = {int(k): v for k, v in DATA["world"].items()}
MAPS = DATA["maps"]
ITEMS = DATA["items"]
EVENTS = DATA["events"]
PRICES = {int(k): v for k, v in DATA["prices"].items()}
MATCHUPS = {(a, b): factor for a, b, factor in DATA["matchups"]}


def event_set(flags: bytes, name: str) -> bool:
    index = EVENTS[name]
    return index // 8 < len(flags) and bool(flags[index // 8] & (1 << (index % 8)))


def object_hidden(snapshot, map_id, object_index):
    index = DATA["toggle_objects"].index([map_id, object_index])
    return (index // 8 < len(snapshot.hidden_objects)
            and bool(snapshot.hidden_objects[index // 8] & (1 << (index % 8))))
