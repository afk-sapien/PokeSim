"""Per-step decision budget on large synthetic states.

The policy decides once per step, so work that grows with the dex, the party, the PC, the map
or the navigation graph has to be cached on the inputs it reads. These states are built in
memory with no cartridge or save: a full dex, a full PC, a navigation graph the size of a long
run and no breeding project. Each step after the first must stay inside the budget, the first
being the one that builds the caches.
"""
import os
import random
import statistics
import time
from dataclasses import replace

import pytest

from pokesim.policies.base import PolicyContext
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import PartyMon, Snapshot, StoredMon
from pokesim.strategy_data import EVENTS, ITEMS, MAPS, SPECIES, WORLD

MEDIAN_MS = 5
MAX_MS = 50
STEPS = 60
# Shared CI runners are slower and noisier than a workstation, so the clock is scaled there.
SCALE = float(os.environ.get('POKESIM_STEP_BUDGET_SCALE', '1'))
# CPU time of this thread, so a runner that deschedules the test mid-step does not count as a slow step.
clock = time.thread_time


def budget(times):
    ms = [t * 1000 for t in times[1:]]
    median, worst = statistics.median(ms), max(ms)
    assert median <= MEDIAN_MS * SCALE, f'median step {median:.2f} ms over {MEDIAN_MS} ms'
    assert worst <= MAX_MS * SCALE, f'slowest step {worst:.1f} ms over {MAX_MS} ms'


def flags(*names):
    data = bytearray(320)
    for name in names:
        bit = EVENTS[name]
        data[bit // 8] |= 1 << (bit % 8)
    return bytes(data)


def gen1_party():
    rows = [(0x99, (22, 3), (75, 22, 34, 73)), (0xB0, (20, 2), (53, 52, 91, 15)),
            (0xB1, (21, 21), (57, 61, 55, 70)), (0x54, (23, 23), (85, 86, 98, 148)),
            (0x0B, (0, 0), (34, 89, 156, 57)), (0x93, (24, 24), (94, 69, 86, 105))]
    return tuple(PartyMon(sid, 180, 180, 55, SPECIES[sid]['name'], types=types, moves=moves, pp=(15,) * 4,
                          attack=120, defense=110, speed=115, special=118, max_pp=(15,) * 4,
                          dvs=(9, 10, 11, 12, 13), stat_exp=(9000,) * 5, trainer_id=4242)
                 for sid, types, moves in rows)


def gen1_storage(rng):
    species = sorted(SPECIES)
    stored = []
    for box in range(12):
        for position in range(20):
            sid = rng.choice(species)
            stored.append(StoredMon(box, position, sid, rng.randint(5, 50), SPECIES[sid]['name'],
                                    (33, 45, 0, 0), 4000, tuple(rng.randint(0, 15) for _ in range(5)),
                                    (0,) * 5, 4242))
    return tuple(stored)


def walked_graph():
    """Every walkable step of every map, as a long run observes them."""
    edges = {}
    steps = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
    for m, world in WORLD.items():
        passable = set(world['passable'])
        tiles = world['tiles']
        for y, row in enumerate(tiles):
            for x, tile in enumerate(row):
                if tile not in passable:
                    continue
                for direction, (dx, dy) in steps.items():
                    nx, ny = x + dx, y + dy
                    if 0 <= ny < len(tiles) and 0 <= nx < len(tiles[ny]) and tiles[ny][nx] in passable:
                        edges.setdefault((m, x, y), {})[direction] = (m, nx, ny)
    return edges


def walk(policy, snapshot, action):
    """Move the player along an observed edge, as the cartridge would for a free step."""
    target = policy.nav.edges.get((snapshot.map, snapshot.x, snapshot.y), {}).get(action.button)
    if target is None:
        return snapshot
    m, x, y = target
    return replace(snapshot, map=m, x=x, y=y)


def test_gen1_step_stays_within_budget_on_a_large_state():
    rng = random.Random(7)
    stored = gen1_storage(rng)
    counts = [0] * 12
    for mon in stored:
        counts[mon.box] += 1
    snapshot = Snapshot(
        frame=100, map=MAPS['VICTORY_ROAD_2F'], x=12, y=8, badges=255, party=gen1_party(),
        owned=frozenset(range(1, 152)), seen=frozenset(range(1, 152)), money=50000,
        items=((ITEMS['POKE_BALL'], 30), (ITEMS['HYPER_POTION'], 10), (ITEMS['REVIVE'], 5), (ITEMS['FULL_HEAL'], 5)),
        in_battle=0, battle_type=0, enemy_species=0, enemy_level=0, opponent=0, player_name='RED',
        rival_name='BLUE', playtime=(40, 0, 0), textbox=False, start_menu=False,
        event_flags=flags('EVENT_GOT_POKEDEX'), stored_details=stored,
        stored_pokemon=tuple((mon.box, mon.species, mon.level, mon.nick) for mon in stored),
        boxed_pokemon=tuple((mon.species, mon.level) for mon in stored if mon.box == 0),
        box_counts=tuple(counts), active_box=0)
    policy = StrategicPolicy(7)
    policy.nav.edges = walked_graph()
    policy.observed_map = snapshot.map
    memory = bytearray(65536)
    times = []
    for step in range(STEPS):
        snapshot = replace(snapshot, frame=100 + step * 16)
        start = clock()
        actions = policy.step(PolicyContext(snapshot, 0, step / 4, memory))
        times.append(clock() - start)
        if actions and actions[0].button:
            snapshot = walk(policy, snapshot, actions[0])
    assert len(policy.nav.edges) > 20000
    budget(times)


class Gen2Memory:
    """Banked memory of zeros, holding only the block map the navigator reads collision from."""

    def __init__(self, data):
        self.data = data
        self.flat = bytearray(0x10000)
        self.banks = {}

    def __getitem__(self, key):
        if isinstance(key, tuple):
            bank, window = key
            return self.banks.setdefault(bank, bytearray(0x10000))[window]
        return self.flat[key]

    def load(self, mid):
        entry = self.data.maps[mid]
        width, height = entry['width'] // 2, entry['height'] // 2
        stride = width + 6
        blocks = bytearray(stride * (height + 6))
        for y in range(height):
            blocks[(y + 3) * stride + 3:(y + 3) * stride + 3 + width] = entry['blocks'][y * width:(y + 1) * width]
        bank, address = self.data.symbols['wOverworldMapBlocks']
        target = self.banks.setdefault(bank, bytearray(0x10000)) if 0x8000 <= address < 0xE000 else self.flat
        target[address:address + len(blocks)] = blocks


def gen2_mon(data, rng, species, level, moves=(33, 45, 52, 55), box=None, position=None):
    from pokesim.gen2.ram import Mon
    return Mon(species, data.species[species]['name'].upper(), level, 150, 150, 0, 0, moves, (20,) * 4, (20,) * 4,
               (150, 100, 100, 100, 100, 100), 100000, tuple(rng.randint(0, 15) for _ in range(4)), (0,) * 5,
               4242, 70, box=box, position=position, data=data)


def gen2_walk(policy, snapshot, memory, button):
    """Take a free step if the square is walkable, then follow any warp underfoot."""
    data = snapshot.data
    entry = data.maps[snapshot.map]
    grid = policy.nav.collision(snapshot, memory)
    dx, dy = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}[button]
    x, y = snapshot.x + dx, snapshot.y + dy
    if 0 <= x < entry['width'] and 0 <= y < entry['height'] and policy.nav.passable(grid[y * entry['width'] + x]):
        snapshot = replace(snapshot, x=x, y=y)
    warp = next((warp for warp in entry['warps'] if (warp['x'], warp['y']) == (snapshot.x, snapshot.y)), None)
    if warp is None:
        return snapshot
    arrival = data.maps[warp['map']]['warps'][warp['warp'] - 1]
    if warp['map'] != snapshot.map:
        memory.load(warp['map'])
    return replace(snapshot, map=warp['map'], x=arrival['x'], y=arrival['y'])


@pytest.mark.parametrize('game', ['silver', 'crystal'])
def test_gen2_step_stays_within_budget_on_a_large_state(game):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.ram import Snapshot as Gen2Snapshot
    data = GameData.load(directory, game)
    rng = random.Random(7)
    # A finished team that knows every field move, so the walk to the League is all that is left.
    party = tuple(gen2_mon(data, rng, species, 50, moves) for species, moves in (
        (157, (53, 15, 70, 98)), (160, (57, 127, 250, 70)), (154, (75, 148, 115, 34)),
        (181, (84, 86, 9, 113)), (149, (19, 57, 63, 85)), (248, (242, 89, 157, 46))))
    species = sorted(data.species)
    stored = tuple(gen2_mon(data, rng, rng.choice(species), rng.randint(5, 50), box=box, position=position)
                   for box in range(14) for position in range(20))
    balls = ((data.items['ULTRA_BALL'], 50),)
    mid = data.map_ids['VICTORY_ROAD']
    memory = Gen2Memory(data)
    memory.load(mid)
    snapshot = Gen2Snapshot(
        frame=100, map=mid, x=9, y=67, player_name='GOLD', rival_name='SILVER', party=party, stored=stored,
        box_counts=(20,) * 14, active_box=0, owned=frozenset(range(1, 252)), seen=frozenset(range(1, 252)),
        badges=0xFFFF, items=balls + ((data.items['FULL_RESTORE'], 20),),
        pockets={'items': (), 'balls': balls, 'key': (), 'machines': ()}, money=500000, coins=0, in_battle=0,
        enemy_species=0, enemy_level=0, enemy_hp=0, enemy_max_hp=0, trainer_class=0, battle_type=0,
        playtime=(100, 0, 0), hall_of_fame_count=0, event_flags=bytes([255] * 256), tiles=(' ' * 20,) * 18,
        objects=(), valid=True, data=data)
    policy = Policy(data, starter='totodile', seed=7)
    times, maps = [], {mid}
    for step in range(120):
        snapshot = replace(snapshot, frame=100 + step * 16)
        start = clock()
        action = policy.step(snapshot, memory)
        times.append(clock() - start)
        if action.button in {'up', 'down', 'left', 'right'}:
            snapshot = gen2_walk(policy, snapshot, memory, action.button)
            maps.add(snapshot.map)
    assert len(maps) >= 3, 'the walk should cross Victory Road into the maps beyond it'
    budget(times)
