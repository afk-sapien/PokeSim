"""Trainer ids of the linked PokeSim adventures this one trades with.

A release lets go of the player's own Pokémon and of copies that came down the cable from a linked
adventure, since the sibling game holds the same line and can trade it again. A Pokémon with any other
original trainer came from an in-game trade or a game outside PokeSim and is never released.

Two sources fill the list, and it only grows. A completed exchange records the original trainer of the
Pokémon that arrived. The coordinator also passes every linked adventure's own trainer id with its
collection requests, which covers copies traded before this list existed.
"""
import json

KEY = 'trade_partners'
# A trainer id is two bytes in every game. The cap keeps a bad request from growing the row without end.
LIMIT = 4096


def valid(value):
    return type(value) is int and 0 <= value <= 0xFFFF


def read(db):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    try:
        ids = json.loads(row[0]) if row else []
    except ValueError:
        return frozenset()
    return frozenset(value for value in ids if valid(value)) if isinstance(ids, list) else frozenset()


def add(db, ids):
    """Merge ``ids`` into the stored list, inside the caller's transaction. Returns the merged set."""
    known = read(db)
    merged = known | {value for value in ids if valid(value)}
    if merged != known and len(merged) <= LIMIT:
        db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (KEY, json.dumps(sorted(merged))))
        return frozenset(merged)
    return known


def received(struct, generation=1):
    """The original trainer id of a Pokémon that arrived, from its struct, or None."""
    # Gen I box_struct keeps it at +12 (trade/boxes.py), Gen II at +6 (pret wram.asm box_struct).
    offset = 6 if generation == 2 else 12
    try:
        raw = bytes.fromhex(struct) if isinstance(struct, str) else bytes(struct)
    except (TypeError, ValueError):
        return None
    return int.from_bytes(raw[offset:offset + 2], 'big') if len(raw) >= offset + 2 else None


def owners(player, partners):
    """The original trainers whose Pokémon a release may let go, or None when the player is unknown."""
    return None if player is None else frozenset(partners) | {player}
