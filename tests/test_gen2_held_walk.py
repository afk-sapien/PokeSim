"""Gen II held presses: which straight runs one press walks, and when that press comes up."""
from types import SimpleNamespace

import pytest

import pokesim.gen2.navigation as navigation
from pokecore.gen2.state import Walking
from pokesim.gen2.navigation import HeldWalk
from pokesim.gen2.policy.navigation import NavigationPart
from pokesim.runtime.game_loop import HOLD_CHECK

MAP = 1


class Place:
    """What walking() reads, set by the test between checks."""

    def __init__(self, x=5, y=9):
        self.now = Walking(MAP, x, y, 0, 0, (30, 20), frozenset())

    def set(self, **changes):
        self.now = self.now._replace(**changes)


@pytest.fixture
def place(monkeypatch):
    place = Place()
    monkeypatch.setattr(navigation, 'walking', lambda memory, game: place.now)
    return place


def walk(place, tiles, button='up'):
    nav = SimpleNamespace(visits={}, previous='before')
    return nav, HeldWalk(nav, None, 'gold', 1000, button, tiles)


def checks(stop, place, ys, start=0):
    """Ask the stop once per check with the player at each y in turn. The answers, in order."""
    answers = []
    for k, y in enumerate(ys, 1):
        place.set(y=y)
        answers.append(stop(start + HOLD_CHECK * k))
        if answers[-1]:
            break
    return answers


def test_a_hold_comes_up_at_the_check_after_the_next_to_last_tile_and_counts_each_tile_passed(place):
    nav, stop = walk(place, 3)
    # Up from y 9: the coordinates show y 8 at about frame 25 and y 7 at about frame 41.
    answers = checks(stop, place, [9] * 6 + [8] * 4 + [7, 7])
    assert answers == [False] * 11 + [True]
    assert (stop.reason, stop.moved) == ('done', 2)
    # Tiles 1 and 2 were passed. Tile 3, where it stops, is counted by the next decision.
    assert nav.visits == {(MAP, 5, 8): 1, (MAP, 5, 7): 1}


def test_a_hold_that_already_shows_its_last_tile_comes_up_without_counting_it(place):
    nav, stop = walk(place, 3)
    assert checks(stop, place, [8, 7, 6]) == [False, False, True]
    assert (stop.reason, stop.moved) == ('done', 3)
    assert nav.visits == {(MAP, 5, 8): 1, (MAP, 5, 7): 1}


@pytest.mark.parametrize('change, reason', [
    ({'map': 2}, 'map'),
    ({'battle': 1}, 'battle'),
    ({'hp': (29, 20)}, 'hp'),
    ({'hp': (30,)}, 'hp'),
    ({'x': 6}, 'off line'),
])
def test_a_hold_comes_up_at_once_where_one_tile_presses_would_decide_again(place, change, reason):
    nav, stop = walk(place, 5)
    assert checks(stop, place, [9, 8]) == [False, False]
    place.set(**change)
    assert stop(3 * HOLD_CHECK)
    assert stop.reason == reason
    assert nav.previous == 'before'


def test_a_person_on_the_line_ahead_ends_a_hold_and_one_beside_it_does_not(place):
    nav, stop = walk(place, 4)
    # Up from y 9 for 4 tiles: the line ahead runs to y 5, and y 4 past the last tile is kept clear too.
    place.set(people=frozenset({(4, 6), (6, 5), (5, 3)}))
    assert not stop(HOLD_CHECK)
    place.set(y=8, people=frozenset({(5, 4)}))
    assert stop(2 * HOLD_CHECK) and stop.reason == 'person'


def test_healing_does_not_end_a_hold(place):
    nav, stop = walk(place, 5)
    place.set(hp=(31, 25))
    assert not stop(HOLD_CHECK)


def test_a_script_ends_a_hold_only_once_a_step_is_taken(place):
    # Turning to face the way sets the script byte for a few frames before the first step.
    nav, stop = walk(place, 5)
    place.set(script=1)
    assert not stop(HOLD_CHECK)
    place.set(script=0, y=8)
    assert not stop(2 * HOLD_CHECK)
    place.set(script=1)
    assert stop(3 * HOLD_CHECK) and stop.reason == 'script'


def test_a_hold_that_never_moves_leaves_the_wall_to_the_decision_that_pressed(place):
    nav, stop = walk(place, 4)
    answers = checks(stop, place, [9] * 20)
    assert answers[-1] and stop.reason == 'stuck' and stop.moved == 0
    assert len(answers) * HOLD_CHECK > HeldWalk.STUCK
    assert nav.previous == 'before'


def test_a_hold_stopped_by_an_unknown_wall_marks_the_tile_it_stopped_on(place):
    nav, stop = walk(place, 6)
    answers = checks(stop, place, [9] * 6 + [8] * 4 + [7] * 20)
    assert answers[-1] and (stop.reason, stop.moved) == ('stuck', 2)
    # As if a one-tile press had been made from y 7 when the walk there ended.
    # y 7 first showed at the eleventh check.
    assert nav.previous == ((MAP, 5, 7), 'up', 1000 + 11 * HOLD_CHECK)
    assert nav.visits == {(MAP, 5, 8): 1}


def test_a_hold_past_its_planned_tiles_ends_off_the_line(place):
    nav, stop = walk(place, 3)
    assert checks(stop, place, [8, 5]) == [False, True]
    assert stop.reason == 'off line'


# held_tiles: which runs are held.

WIDTH = HEIGHT = 12


def part(collision=None, warps=(), environment='ROUTE', blocked=(), objects=()):
    collision = list(collision or [0] * (WIDTH * HEIGHT))
    entry = {'width': WIDTH, 'height': HEIGHT, 'collision': collision, 'warps': list(warps),
             'objects': list(objects), 'environment': environment, 'connections': []}
    host = object.__new__(NavigationPart)
    host.data = SimpleNamespace(maps={MAP: entry}, game='gold')
    host.nav = SimpleNamespace(collision=lambda snapshot, memory: collision, blocked=dict.fromkeys(blocked, 1))
    return host


def at(x=5, y=10, objects=()):
    return SimpleNamespace(map=MAP, x=x, y=y, objects=list(objects), frame=0)


READS = SimpleNamespace(ui=SimpleNamespace(movement_state=0))


def held(host, path, snapshot=None, reads=READS):
    return host.held_tiles(snapshot or at(), None, path, reads)


def set_tile(collision, x, y, value):
    collision[y * WIDTH + x] = value


def test_a_straight_run_is_held_up_to_the_cap():
    assert held(part(), ['up'] * 10) == NavigationPart.HELD_TILES
    assert held(part(), ['up'] * 4 + ['left'] * 3) == 4
    assert held(part(), ['up'] * 3) == 3


def test_a_run_under_the_minimum_is_walked_one_tile_at_a_time():
    assert held(part(), ['up', 'up', 'left', 'left', 'left']) == 0


@pytest.mark.parametrize('environment', ['INDOOR', 'GATE'])
def test_indoor_maps_are_walked_one_tile_at_a_time(environment):
    assert held(part(environment=environment), ['up'] * 6) == 0


@pytest.mark.parametrize('state, tiles', [(1, 6), (4, 0), (8, 0)], ids=['cycling', 'surfing', 'surfing_pikachu'])
def test_a_ride_is_held_and_a_surf_is_walked_one_tile_at_a_time(state, tiles):
    assert held(part(), ['up'] * 6, reads=SimpleNamespace(ui=SimpleNamespace(movement_state=state))) == tiles


def test_an_ice_map_is_walked_one_tile_at_a_time():
    collision = [0] * (WIDTH * HEIGHT)
    set_tile(collision, 0, 0, 0x23)
    assert held(part(collision), ['up'] * 6) == 0


@pytest.mark.parametrize('value', [0x12, 0x1A, 0x21, 0x29, 0x60, 0xA0, 0x07])
def test_a_hold_stops_before_any_tile_that_is_not_floor_or_grass(value):
    collision = [0] * (WIDTH * HEIGHT)
    set_tile(collision, 5, 5, value)
    # From y 10, y 5 is the fifth tile. Tiles 1 to 3 have plain tiles past them.
    assert held(part(collision), ['up'] * 8) == (4 if value < 0xA0 else 3)


def test_grass_is_held_onto():
    collision = [0] * (WIDTH * HEIGHT)
    set_tile(collision, 5, 9, 0x18)
    set_tile(collision, 5, 8, 0x14)
    assert held(part(collision), ['up'] * 5) == 5


def test_a_hold_ends_a_tile_before_a_warp_a_person_a_ledge_or_the_map_edge():
    warp = {'x': 5, 'y': 5, 'map': 2, 'warp': 1}
    assert held(part(warps=[warp]), ['up'] * 8) == 3
    assert held(part(), ['up'] * 8, at(objects=[(1, 5, 5)])) == 3
    collision = [0] * (WIDTH * HEIGHT)
    set_tile(collision, 5, 5, 0xA3)
    assert held(part(collision), ['up'] * 8) == 3
    assert held(part(), ['up'] * 8, at(y=5)) == 4


def test_a_known_wall_ends_a_hold_before_it():
    assert held(part(blocked=[(MAP, 5, 6)]), ['up'] * 8) == 3
    assert held(part(blocked=[(MAP, 5, 8)]), ['up'] * 8) == 0
