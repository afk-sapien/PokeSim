"""Pokédex reference data assembled from the generated game tables.

Presentation only: no HTTP, emulator, or storage access. The web layer pairs
this reference with live Pokédex flags, the party, and the storage boxes.
"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from ..game_data import load
from ..pokemon import TYPES
from ..ram import DEX_NAMES, MAP_NAMES, MOVES as MOVE_TABLE
from ..strategy_data import MOVES as MOVE_DETAILS, SPECIES

COLLECTION = load("collection.json")
EVOLUTIONS = {int(sid): rows for sid, rows in COLLECTION["evolutions"].items()}
VERSIONS = tuple(COLLECTION["versions"])
DEFAULT_VERSION = "red" if "red" in VERSIONS else VERSIONS[0]
STAT_NAMES = ("HP", "Attack", "Defense", "Speed", "Special")
GROWTH_LABELS = {"FAST": "Fast", "MEDIUM_FAST": "Medium fast", "MEDIUM_SLOW": "Medium slow", "SLOW": "Slow"}
METHOD_LABELS = {"grass": "Tall grass", "surf": "Surfing", "fish": "Fishing", "safari": "Safari Zone",
                 "static": "Standing encounter", "gift": "Gift", "trade": "In-game trade",
                 "fossil": "Fossil revival", "prize": "Game Corner prize"}
METHOD_ORDER = ("grass", "surf", "fish", "safari", "static", "gift", "trade", "fossil", "prize")


def title(raw: str) -> str:
    """Turn a disassembly constant such as MOON_STONE into readable text."""
    return str(raw).replace("_", " ").title()


def species_name(sid: int) -> str:
    """Display name for an internal species id, preferring the Pokédex spelling."""
    mon = SPECIES.get(sid)
    return DEX_NAMES.get(mon["dex"], title(mon["name"])) if mon else "Unknown"


def move_entry(move_id: int, level: int | None) -> dict:
    table = MOVE_TABLE.get(move_id, {})
    details = MOVE_DETAILS.get(move_id, {})
    # The disassembly spells the psychic type PSYCHIC_TYPE so it cannot collide with the move.
    type_name = (table.get("type") or TYPES.get(details.get("type"), "Normal")).removesuffix(" Type")
    return {"level": level, "name": table.get("name") or title(details.get("name", f"Move {move_id}")),
            "type": type_name,
            "power": table.get("power", details.get("power", 0)),
            "accuracy": details.get("accuracy"), "pp": details.get("pp")}


def evolution_step(sid: int, step: dict) -> dict:
    method, requirement = step["method"], step.get("requirement")
    label = (f"Level {requirement}" if method == "level"
             else title(requirement) if method == "item"
             else "Link trade" if method == "trade" else title(method))
    return {"dex": SPECIES.get(sid, {}).get("dex"), "name": species_name(sid),
            "method": method, "requirement": requirement, "label": label}


def links(name: str, dex: int) -> dict:
    """Outside references for players who want more than the cartridge knows."""
    return {"bulbapedia": f"https://bulbapedia.bulbagarden.net/wiki/{quote(name)}_(Pok%C3%A9mon)",
            "serebii": f"https://www.serebii.net/pokedex/{dex:03d}.shtml",
            "wikipedia": f"https://en.wikipedia.org/wiki/Special:Search?search={quote(name + ' Pokémon')}"}


def locations(rows: list[dict]) -> list[dict]:
    """Group raw encounter rows into one line per place, method, and fishing rod."""
    grouped: dict[tuple, dict] = {}
    for row in rows:
        key = (row["map"], row["method"], row.get("rod"))
        place = grouped.setdefault(key, {
            "map": row["map"], "map_name": MAP_NAMES.get(row["map"], f"Map {row['map']}"),
            "method": row["method"], "method_label": METHOD_LABELS.get(row["method"], title(row["method"])),
            "rod": title(row["rod"]) if row.get("rod") else None, "levels": [],
            "gives": species_name(row["give"]) if row.get("give") else None,
            "item": title(row["item"]) if row.get("item") else None})
        if row.get("level"):
            place["levels"].append(row["level"])
    places = []
    for place in grouped.values():
        levels = sorted(place.pop("levels"))
        place["level_range"] = (f"Lv. {levels[0]}" if levels[0] == levels[-1] else f"Lv. {levels[0]}–{levels[-1]}") if levels else None
        places.append(place)
    places.sort(key=lambda place: (METHOD_ORDER.index(place["method"]) if place["method"] in METHOD_ORDER else len(METHOD_ORDER),
                                   place["map_name"]))
    return places


@lru_cache(maxsize=len(VERSIONS) or 1)
def reference(version: str = DEFAULT_VERSION) -> dict:
    """Every Pokédex entry for one game version, ordered by Pokédex number."""
    if version not in VERSIONS:
        raise ValueError(f"Unknown game version: {version}")
    sources = {int(sid): rows for sid, rows in COLLECTION["versions"][version].items()}
    entries = []
    for sid, mon in sorted(SPECIES.items(), key=lambda pair: pair[1]["dex"]):
        stats = dict(zip(STAT_NAMES, mon["stats"]))
        # A starting move that also appears in the learnset is listed once, as a starting move.
        moves = [move_entry(mid, None) for mid in mon["initial_moves"]]
        moves += [move_entry(mid, level) for level, mid in mon["learnset"] if mid not in mon["initial_moves"]]
        name = species_name(sid)
        entries.append({
            "dex": mon["dex"], "species": sid, "name": name,
            "types": list(dict.fromkeys(TYPES.get(t, "Unknown") for t in mon["types"])),
            "stats": stats, "total": sum(stats.values()),
            "catch_rate": mon["catch_rate"], "growth": GROWTH_LABELS.get(mon["growth"], title(mon["growth"])),
            "moves": moves, "hms": [MOVE_TABLE.get(mid, {}).get("name", title(str(mid))) for mid in mon["hms"]],
            "evolves_from": [evolution_step(parent, step) for parent, steps in EVOLUTIONS.items()
                             for step in steps if step["species"] == sid],
            "evolves_to": [evolution_step(step["species"], step) for step in EVOLUTIONS.get(sid, [])],
            "locations": locations(sources.get(sid, [])),
            "links": links(name, mon["dex"]),
        })
    return {"version": version, "count": len(entries), "entries": entries}


def live_status(game: dict | None, collection: dict | None = None) -> dict:
    """The parts of a snapshot a Pokédex reader needs, without the rest of the state payload."""
    # Only the fields the page reads: the planner's entries repeat on every poll.
    plan = {"plan": [{"dex": row.get("dex"), "species": row.get("species"),
                      "status": row.get("status"), "reason": row.get("reason")}
                     for row in (collection or {}).get("entries", [])],
            "phase": (collection or {}).get("phase", ""),
            "version": (collection or {}).get("version", DEFAULT_VERSION),
            "hunting": ((collection or {}).get("hunt") or {}).get("species")}
    if not game:
        return {"started": False, "owned": [], "seen": [], "party": [], "storage": None, **plan}
    dex_of = {sid: mon["dex"] for sid, mon in SPECIES.items()}
    storage = game.get("storage") or {}
    return {
        "started": True,
        "owned": game.get("dex_owned", []), "seen": game.get("dex_seen", []),
        "player_name": game.get("player_name", ""), "playtime": game.get("playtime", ""),
        "party": [{"dex": mon.get("dex"), "species": mon["species"], "name": mon["name"], "nick": mon["nick"],
                   "level": mon["level"], "hp": mon["hp"], "max_hp": mon["max_hp"],
                   "moves": mon.get("moves", ()), "dvs": mon.get("dvs", ()),
                   "stat_exp": mon.get("stat_exp", ()),
                   "experience": (mon.get("experience") or {}).get("total", 0),
                   "status_label": mon.get("status_label"), "slot": slot + 1}
                  for slot, mon in enumerate(game.get("party", []))],
        "storage": {**storage,
                    "pokemon": [{**mon, "dex": dex_of.get(mon["species"])} for mon in storage.get("pokemon", [])]}
        if storage else None,
        **plan,
    }
