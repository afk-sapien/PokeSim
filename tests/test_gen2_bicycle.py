"""Gen II Bicycle: the Goldenrod bike shop after Cut, when the walk gets on, how a ride is pressed, and the
SELECT register that makes each mount one press."""
import os
from types import SimpleNamespace

import pytest

import pokesim.gen2.menus as menus
import pokesim.gen2.policy.navigation as navigation
from pokesim.gen2.menus import Register
from pokesim.gen2.policy.navigation import NavigationPart
from pokesim.runtime.policy import Action

MAP, BIKE = 1, 7
WIDTH = HEIGHT = 12
# Twenty steps that stay inside the map.
PACE = ['left', 'right'] * (NavigationPart.MOUNT_STEPS // 2)


def part(environment='ROUTE', collision=None, objects=(), allowed=True):
    collision = list(collision or [0] * (WIDTH * HEIGHT))
    entry = {'width': WIDTH, 'height': HEIGHT, 'collision': collision, 'warps': [], 'objects': list(objects),
             'environment': environment, 'connections': []}
    host = object.__new__(NavigationPart)
    host.data = SimpleNamespace(maps={MAP: entry}, game='gold', items={'BICYCLE': BIKE})
    host.nav = SimpleNamespace(collision=lambda snapshot, memory: collision, blocked={}, issued=lambda *args: None)
    host.allowed = lambda task, snapshot: allowed
    host.menu = host.interaction = None
    return host


def at(items=((BIKE, 1),), x=5, y=5):
    return SimpleNamespace(map=MAP, x=x, y=y, items=list(items), objects=[], frame=0, badges=0, party=[])


def tile(x, y, value):
    collision = [0] * (WIDTH * HEIGHT)
    collision[y * WIDTH + x] = value
    return collision


def register(monkeypatch, item):
    monkeypatch.setattr(navigation, 'registered', lambda memory, data: item)
    monkeypatch.setattr(menus, 'registered', lambda memory, data: item)


@pytest.fixture(autouse=True)
def unregistered(monkeypatch):
    register(monkeypatch, None)


@pytest.mark.parametrize('environment', sorted(NavigationPart.BIKE_ENVIRONMENTS))
def test_a_long_walk_where_the_game_allows_a_ride_registers_the_bicycle_first(environment):
    host = part(environment)
    assert host.mount(at(), None, PACE) == Action(None, 0, 24)
    assert host.menu == Register(BIKE)


def test_a_registered_bicycle_gets_on_with_one_select_press(monkeypatch):
    register(monkeypatch, BIKE)
    host = part()
    assert host.mount(at(), None, PACE) == Action('select', 8, 24) and host.menu is None
    # A press the game refused leaves the player on foot on the same tile, and walks on from there.
    assert host.mount(at(), None, PACE) is None
    assert host.mount(at(x=6), None, PACE) == Action('select', 8, 24)
    register(monkeypatch, 0x3D)
    assert host.mount(at(), None, PACE) == Action(None, 0, 24) and host.menu == Register(BIKE)


@pytest.mark.parametrize('host, snapshot, path', [
    (part('INDOOR'), at(), PACE),
    (part('DUNGEON'), at(), PACE),
    (part(), at(), PACE[:-1]),
    (part(), at(items=()), PACE),
    (part(allowed=False), at(), PACE),
    # The game refuses the Bicycle in grass, and the walk ahead must stay off water.
    (part(collision=tile(5, 5, 0x18)), at(), PACE),
    (part(collision=tile(4, 5, 0x21)), at(), PACE),
    # A run up a short map leaves it before the ride pays.
    (part(), at(), ['up'] * NavigationPart.MOUNT_STEPS),
    (part(objects=[{'sprite': 'SPRITE_BOULDER'}] * 2), at(), PACE),
], ids=['indoors', 'dungeon', 'short_walk', 'no_bicycle', 'refused_before', 'grass_underfoot', 'water_ahead',
        'off_the_map', 'boulder_puzzle'])
def test_the_walk_stays_on_foot(host, snapshot, path):
    assert not host.mount(snapshot, None, path) and host.menu is None


def walk(state, path, facing='left'):
    host = part()
    host.reads = SimpleNamespace(memory=None, ui=SimpleNamespace(movement_state=state, facing=facing))
    return host, host.walk(at(), None, path)


def test_walking_on_foot_starts_the_ride_and_a_rider_presses_half_a_step():
    host, action = walk(0, PACE)
    assert action == Action(None, 0, 24) and host.menu == Register(BIKE)
    host, action = walk(1, PACE)
    assert action == Action('left', 8, 8) and host.menu is None
    host, action = walk(4, PACE)
    assert action == Action('left', 16, 16) and host.menu is None


def test_a_rider_turning_presses_a_full_step():
    """A press in a new direction turns the rider first. On Route 30 an 8-frame press ended in the turn, so the
    walk took the tile ahead for a wall and turned again elsewhere."""
    host, action = walk(1, PACE, facing='up')
    assert action == Action('left', 16, 16) and host.menu is None


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def test_the_bicycle_is_borrowed_after_cut_at_any_depth(real_data):
    from pokesim.gen2.policy import Policy
    from pokesim.story import row
    owner = Policy(real_data, starter='cyndaquil')
    owner.story_step = lambda snapshot, key, title, row=None: SimpleNamespace(key=key)

    # Zephyr and Hive, the two badges before Cut.
    def key(*unset, badges=3, place='GOLDENROD_CITY', party=()):
        state = SimpleNamespace(frame=100, badges=badges, party=list(party), map=real_data.map_ids[place], x=0,
                                y=0, farfetchd_position=None, event=lambda flag: flag not in unset)
        return owner.story(state, None).key

    assert key('EVENT_GOT_HM01_CUT', 'EVENT_GOT_BICYCLE') == 'cut'
    assert key('EVENT_GOT_BICYCLE') == 'bicycle'
    assert key('EVENT_GOT_BICYCLE', badges=255) == 'bicycle'
    # Kanto, the League rooms and Silver Cave have no walk to Goldenrod inside Johto. The gate stood down 4 times
    # in a row in Kanto, and took turns with Red at Silver Cave a thousand times. The story moves on to the step
    # after the Bicycle, here Whitney with three badges.
    for place in ('VERMILION_PORT', 'KARENS_ROOM', 'INDIGO_PLATEAU_POKECENTER_1F', 'SILVER_CAVE_OUTSIDE'):
        assert key('EVENT_GOT_BICYCLE', 'EVENT_MADE_WHITNEY_CRY', place=place) == 'plain'
        assert 'bicycle' not in owner.completed
    # With Surf a walk from Silver Cave reaches Goldenrod, but through Route 28 in Kanto, so the step stays off.
    surfer = SimpleNamespace(moves=[57], species=9, level=50, hp=1, max_hp=1, status=0, egg=False)
    assert key('EVENT_GOT_BICYCLE', badges=255, place='SILVER_CAVE_OUTSIDE', party=[surfer]) != 'bicycle'
    assert key('EVENT_GOT_BICYCLE', badges=255, place='ROUTE_27', party=[surfer]) == 'bicycle'
    assert key() != 'bicycle' and owner.completed['bicycle'] == 100
    found = row(2, real_data.game, 'bicycle')
    assert (found['map'], found['object']) == ('GOLDENROD_BIKE_SHOP', 'GoldenrodBikeShopClerkScript')


def test_a_register_task_rebuilt_after_the_register_ends_without_the_pack(monkeypatch):
    register(monkeypatch, BIKE)
    mem = SimpleNamespace(memory=None, data=SimpleNamespace(game='gold'))
    task = Register(BIKE)
    assert task.step(at(), mem) is None and getattr(task, 'machine', None) is None
