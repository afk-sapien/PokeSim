"""Gen I Flash: Oak's aide gives HM05 on the way to Rock Tunnel, a partner learns it, and it lights the
cave once per map entered. A run without it walks the cave dark."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim.policies.progression import AIDE_REQUIREMENT, FLASH, flash_learner, story_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.team import reserve_to_deposit
from pokesim.ram import W_MAP_PAL_OFFSET, W_TOWN_VISITED, read_snapshot
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_gen1_scenario_edits import watch_with
from test_strategy import flags, mon

PIKACHU, ABRA, CLEFAIRY = 0x54, 0x94, 0x04
TUNNEL, TUNNEL_B1F = MAPS['ROCK_TUNNEL_1F'], MAPS['ROCK_TUNNEL_B1F']


def road(**changes):
    """Three badges and short of Rock Tunnel, ten species owned, and an Abra that can learn Flash
    behind a Bulbasaur ace that cannot."""
    base = dict(badges=0b111, map=MAPS['VERMILION_CITY'], owned=frozenset(range(1, AIDE_REQUIREMENT + 1)),
                event_flags=flags('EVENT_GOT_POKEDEX'),
                party=(mon(level=40, moves=(15, 33, 22, 45)), mon(species=ABRA, level=20, moves=(100, 0, 0, 0))))
    base.update(changes)
    return snap(**base)


def test_the_snapshot_reads_the_dark_palette_and_the_towns_entered():
    memory = bytearray(65536)
    assert not read_snapshot(memory, 0).dark
    memory[W_MAP_PAL_OFFSET] = 6
    memory[W_TOWN_VISITED] = 1 << MAPS['LAVENDER_TOWN']
    memory[W_TOWN_VISITED + 1] = 1 << MAPS['SAFFRON_CITY'] - 8
    s = read_snapshot(memory, 1)
    assert s.dark and s.towns_visited == 1 << MAPS['LAVENDER_TOWN'] | 1 << MAPS['SAFFRON_CITY']


def test_the_aide_gives_flash_on_the_way_to_rock_tunnel():
    goal = story_goal(road())
    assert goal.key == 'flash'
    assert {target[0] for target in goal.targets} == {MAPS['ROUTE_2_GATE']}
    assert story_goal(road(items=((ITEMS['HM05'], 1),))).key == 'teach_flash'


@pytest.mark.parametrize('changes', [
    {'towns_visited': 1 << MAPS['LAVENDER_TOWN']},     # Already through the tunnel.
    {'map': MAPS['ROUTE_10']},                          # Already on the road into it.
    {'map': TUNNEL},
    {'owned': frozenset(range(1, AIDE_REQUIREMENT))},  # The aide wants one more species.
    {'party': (mon(level=40), mon(species=ABRA, level=20, moves=(100, FLASH, 0, 0)))},
    {'party': (mon(species=PIKACHU, level=40, moves=(84, 33, 0, 0)), mon(level=20)),   # Only the ace can learn it.
     'items': ((ITEMS['HM05'], 1),)},
    {'party': (mon(species=PIKACHU, level=40, moves=(84, 33, 0, 0)), mon(level=20))},  # No trip for nothing.
], ids=['past_lavender', 'route_10', 'in_the_tunnel', 'nine_owned', 'knows_flash', 'only_the_ace_learns',
        'no_learner_no_trip'])
def test_a_run_past_the_pickup_walks_the_cave_dark(changes):
    assert story_goal(road(**changes)).key not in ('flash', 'teach_flash')


def test_flash_goes_to_the_strongest_partner_never_the_ace():
    party = (mon(species=PIKACHU, level=40, moves=(84, 33, 0, 0)), mon(species=ABRA, level=12, moves=(100, 0, 0, 0)),
             mon(species=CLEFAIRY, level=18, moves=(1, 45, 0, 0)), mon(level=30))
    assert flash_learner(party) == 2
    assert flash_learner(party[:1] + party[3:]) is None


def flash_policy(monkeypatch):
    policy, used = StrategicPolicy(7), []
    monkeypatch.setattr(policy, '_field', lambda s, move, slot, purpose: used.append((s.map, move, slot)) or ['press'])
    return policy, used


def test_flash_lights_a_dark_map_once_per_map_entered(monkeypatch):
    policy, used = flash_policy(monkeypatch)
    dark = road(map=TUNNEL, dark=True, party=(mon(level=40), mon(species=ABRA, level=20, moves=(100, FLASH, 0, 0))))
    assert policy._flash(dark) == ['press'] and used == [(TUNNEL, 'FLASH', 1)]
    # A refusal or a menu that closed early is not retried on the same map, so the walk goes on dark.
    assert policy._flash(dark) is None
    assert policy._flash(replace(dark, map=TUNNEL_B1F)) == ['press']
    # Walking out clears the dark, and walking back in offers Flash again.
    assert policy._flash(replace(dark, map=MAPS['ROUTE_10'], dark=False)) is None
    assert policy._flash(dark) == ['press'] and len(used) == 3


def test_flash_waits_for_the_boulder_badge_and_a_holder(monkeypatch):
    policy, used = flash_policy(monkeypatch)
    dark = road(map=TUNNEL, dark=True, party=(mon(level=40), mon(species=ABRA, level=20, moves=(100, FLASH, 0, 0))))
    assert policy._flash(replace(dark, badges=0b110)) is None
    assert policy._flash(replace(dark, party=dark.party[:1])) is None
    assert policy._flash(replace(dark, dark=False)) is None and used == []


def test_the_watch_marks_flash_lighting_the_map_it_was_dark_on():
    watch = watch_with({})
    look = lambda map_id, dark: watch.flash_marks(SimpleNamespace(
        valid=True, started=True, map=map_id, map_name=f'Map {map_id}', dark=dark))
    assert look(TUNNEL, True) == []
    assert look(TUNNEL, False) == [('flash', f'Map {TUNNEL}', f'Lit Map {TUNNEL} with Flash')]
    # Walking out turns the dark off on another map, which is no mark.
    assert look(TUNNEL_B1F, True) == []
    assert look(MAPS['ROUTE_10'], False) == []


def test_a_sole_flash_holder_stays_until_lavender_and_is_an_ordinary_reserve_after():
    party = (mon(level=60),) + tuple(mon(level=30, moves=(move, 33, 0, 0)) for move in (15, 19, 57, 70)) + (
        mon(level=35, moves=(FLASH, 33, 0, 0)),)
    assert reserve_to_deposit(snap(party=party)) is None
    assert reserve_to_deposit(snap(party=party, towns_visited=1 << MAPS['LAVENDER_TOWN'])) == 5


def test_the_pokemon_center_swap_keeps_the_flash_user_before_rock_tunnel():
    """A Clefairy taught Flash was swapped for a stronger boxed Diglett at a Pokémon Center, so the
    run walked Rock Tunnel dark. The weakest reserve without a field move goes instead."""
    party = (mon(level=31), mon(level=18), mon(level=11), mon(species=CLEFAIRY, level=11, moves=(FLASH, 1, 0, 0)))
    assert reserve_to_deposit(snap(party=party)) == 2
    assert reserve_to_deposit(snap(party=party[:1] + party[3:])) is None
