"""What a goal is expected to cost, for both generations.

A search costs the walk to its map and then the encounters it takes to meet what it wants, each
counted with the walking that finds it. The cost is what the arbiter divides a goal's value by, and
three times it is the budget the progress monitor gives the goal.

The encounter odds come from core's tables read from the adventure's own cartridge, with a randomized
run's overrides applied, never from a committed table. Each host loads them once per adventure.
"""
from pathlib import Path

# What a search is expected to cost, in decisions. A wild battle takes about 75 with the walking that
# finds it, and crossing one map on the way takes about 150.
DECISIONS_PER_BATTLE = 75
DECISIONS_PER_MAP = 150
# Estimates in frames for both generations: one walking step, one wild battle with its catch attempt or
# its escape, and one cast of a rod with the wait for a bite.
FRAMES_PER_TILE = 16
FRAMES_PER_BATTLE = 1500
FRAMES_PER_CAST = 240
# What each catch costs on top of meeting the Pokémon: the throws, the box and the heal and restock
# trips the catches bring. Measured on three Red and three Yellow postgame saves, quality hunts took
# 30000 to 60000 frames per catch beyond the encounters themselves.
FRAMES_PER_CATCH = 30000
# Gen I picks one of ten wild slots with these chances out of 256, in grass and in water alike.
GEN1_SLOTS = (51, 51, 39, 25, 25, 25, 13, 13, 11, 3)
# Gen II grass has seven slots for each time of day and water has three.
GEN2_GRASS = (30, 30, 20, 10, 5, 4, 1)
GEN2_WATER = (60, 30, 10)
GEN2_TIMES = {'morn': 'morning', 'day': 'day', 'nite': 'night'}
# A search the cartridge's tables cannot price, such as one under a unit test with no cartridge or on an
# unverified dump, meets its target in this percent of encounters, with this many steps between them.
UNPRICED_CHANCE = 10
UNPRICED_STEPS = 10


def search_expected(chance, maps=0, odds=1.0, needed=1.0, per_map=DECISIONS_PER_MAP, per_battle=DECISIONS_PER_BATTLE):
    """What a search is expected to take: the maps on the way, then the wild battles it takes to meet
    ``needed`` Pokémon found in ``chance`` percent of them, of which ``odds`` hold what the search is for.

    The cost is in decisions unless ``per_map`` and ``per_battle`` are given in another unit, such as frames.
    """
    battles = needed / (min(100, max(1, chance)) / 100 * odds)
    return maps * per_map + battles * per_battle


def slot_chance(slots, species, chances):
    """The percent of encounters that meet ``species``, from (level, species) slots and each slot's
    share of ``chances``, such as ``GEN1_SLOTS``."""
    total = sum(chances)
    return 100 * sum(chance for (_, name), chance in zip(slots, chances) if name == species) / total


def game_data(rom_path, version):
    """Core's tables for the cartridge at ``rom_path``, with a randomized run's overrides applied, or None
    when the file cannot be read as ``version``."""
    from pokecore import romdata
    from .. import randomized
    try:
        run = randomized.current(rom_path)
        if run is not None and run.version == version:
            return run.effective
        return romdata.load_cached(Path(rom_path).read_bytes(), version)
    except (OSError, ValueError, KeyError):
        return None


class WildOdds:
    """Gen I encounter odds from core's tables: what a step in grass or water and a cast of a rod meet."""

    def __init__(self, data):
        self.data = data

    def encounter(self, method, map_id, species):
        """The percent of encounters on ``map_id`` that meet ``species``, and the steps between encounters.
        ``method`` is 'grass', 'safari' or 'surf'. A map with no such table gives (0, None)."""
        table = self.data.encounters.get(f'{"water" if method == "surf" else "grass"}:{map_id}')
        if not table or not table.get('rate'):
            return 0, None
        return slot_chance(table['slots'], species, GEN1_SLOTS), 256 / table['rate']

    def cast(self, rod, map_id, species):
        """The percent of casts of ``rod``, such as 'SUPER_ROD', that hook ``species`` on ``map_id``, and
        the share of casts that hook anything."""
        found = self.data.fishing_slots(rod.lower(), map_id)
        if not found:
            return 0, 0
        share = sum(slot['probability'] for slot in found['slots'] if slot['species'] == species)
        return 100 * found['bite'] * share, found['bite']


def wild_odds(rom_path, version):
    """The Gen I odds for an adventure's cartridge, or None when it cannot be read."""
    data = game_data(rom_path, version)
    return WildOdds(data) if data is not None and data.generation == 1 else None


def catch_frames(odds, method, map_id, species, needed=1, rod=None):
    """Frames to meet ``needed`` of ``species`` on ``map_id`` once there, from ``odds`` (a WildOdds) or
    the unpriced estimate when ``odds`` is None.

    A step search pays one battle and the steps that find it per encounter. A rod pays one cast per try
    and a battle for each bite, whatever bites. Each catch adds ``FRAMES_PER_CATCH``.
    """
    if method == 'fish':
        chance, bite = odds.cast(rod, map_id, species) if odds is not None else (UNPRICED_CHANCE, 1)
        search = search_expected(chance, needed=needed, per_battle=FRAMES_PER_CAST + bite * FRAMES_PER_BATTLE)
    else:
        chance, steps = (odds.encounter(method, map_id, species) if odds is not None
                         else (UNPRICED_CHANCE, UNPRICED_STEPS))
        search = search_expected(chance, needed=needed,
                                 per_battle=FRAMES_PER_BATTLE + (steps or UNPRICED_STEPS) * FRAMES_PER_TILE)
    return search + needed * FRAMES_PER_CATCH


def gen2_rows(data, rows):
    """Gen II encounter rows with every grass and surf row read from core's tables in ``data``.

    Other methods, such as rods, trees and Rock Smash, keep their rows and follow the cartridge's. Swarms
    replace a route's table for a day, and the planner never counted on them. On a clean cartridge the
    rows are the ones the game data bundle holds, in the same order.
    """
    result = []
    for table in data.encounters.values():
        if table['kind'].startswith('swarm'):
            continue
        if table['kind'].endswith('grass'):
            for time, slots in table['slots'].items():
                for (level, species), chance in zip(slots, GEN2_GRASS):
                    result.append({'map': table['map'], 'species': species, 'level': level, 'method': 'grass',
                                   'time': GEN2_TIMES[time], 'chance': chance})
        else:
            for (level, species), chance in zip(table['slots'], GEN2_WATER):
                result.append({'map': table['map'], 'species': species, 'level': level, 'method': 'surf',
                               'time': 'any', 'chance': chance})
    return result + [row for row in rows if row['method'] not in ('grass', 'surf')]


def gen2_cartridge_rows(rom_path, version, rows):
    """``rows`` with grass and surf read from the cartridge at ``rom_path``, shuffled when the run is
    randomized. A cartridge core cannot read keeps the bundle's rows."""
    data = game_data(rom_path, version)
    return rows if data is None or data.generation != 2 else gen2_rows(data, rows)
