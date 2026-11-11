"""A Red, Blue or Yellow catch under 1 in 10 a throw weakens its target first, with a switch when the
battler cannot, and leaves a target nobody can weaken for later rather than spending its balls on it."""
import pytest

from pokesim.planning.throws import THROW_BAR, gen1_throw
from pokesim.policies.battle import choose_battle
from pokesim.policies.collection import Collection
from pokesim.strategy_data import ITEMS, MAPS
from test_capture_diversity import sid
from test_events import snap
from test_strategy import mon


def test_a_throw_follows_the_cartridge_formula():
    # Tangela's catch rate is 45. At full HP a Poké Ball meets 46 of its 256 first numbers, and the HP
    # check passes 86 of 256 second numbers. A Great Ball draws under 201 and halves the HP divisor.
    assert gen1_throw(45, 'POKE_BALL', 60, 60, 0) == 46 / 256 * 86 / 256 < THROW_BAR
    great = gen1_throw(45, 'GREAT_BALL', 60, 60, 0)
    assert great == pytest.approx(46 / 201 * 128 / 256) and great > THROW_BAR
    # Sleep catches outright under 25 and any other status under 12, and a target under 4 HP always
    # passes the HP check.
    assert gen1_throw(45, 'POKE_BALL', 60, 60, 1) == (25 + 46 * 86 / 256) / 256
    assert gen1_throw(45, 'POKE_BALL', 60, 60, 8) == (12 + 46 * 86 / 256) / 256
    assert gen1_throw(45, 'POKE_BALL', 1, 60, 0) == 46 / 256


# An Ivysaur whose Razor Leaf could knock the target out, and a Pidgey whose Tackle cannot.
LEAD = mon(species=sid(2), hp=120, max_hp=120, level=45, moves=(75, 45, 0, 0), pp=(20, 30, 0, 0),
           attack=90, defense=80, speed=70, special=90)
HELPER = mon(species=sid(16), hp=40, max_hp=40, level=14, types=(0, 2), moves=(33, 0, 0, 0), pp=(30, 0, 0, 0),
             attack=20, defense=18, speed=25, special=18)


def meeting(dex, party, ball='POKE_BALL', hp=60, where=MAPS['ROUTE_21'], **changes):
    enemy = mon(species=sid(dex), hp=hp, max_hp=60, level=22, types=(22, 22), moves=(132, 20, 0, 0),
                pp=(30, 20, 0, 0), attack=30, defense=60, speed=30, special=60)
    state = snap(party=party, in_battle=1, map=where, items=((ITEMS[ball], 10),), enemy_species=enemy.species,
                 enemy_level=enemy.level, **changes)
    return state, enemy


def decide(state, enemy, **changes):
    return choose_battle(state, state.party[0], enemy, 0, collect_missing=True, **changes)


def test_a_long_shot_switches_to_a_member_that_can_weaken_it():
    state, enemy = meeting(114, (LEAD, HELPER))
    decision = decide(state, enemy)
    assert (decision.kind, decision.index, decision.defer) == ('switch', 1, False)
    # Out in front, the Pidgey weakens it.
    assert choose_battle(state, HELPER, enemy, 1, collect_missing=True).kind == 'fight'


def test_a_long_shot_nobody_can_weaken_runs_and_waits_for_a_new_move_member_or_ball():
    state, enemy = meeting(114, (LEAD,))
    decision = decide(state, enemy)
    assert (decision.kind, decision.defer) == ('run', True)
    collection = Collection()
    collection.defer(state, enemy.species)
    assert collection.deferred(state, enemy.species)
    restored = Collection()
    restored.load(collection.state_dict())
    assert restored.deferred(state, enemy.species)
    taught = meeting(114, (mon(**{**LEAD.__dict__, 'moves': (75, 33, 0, 0)}),))[0]
    joined = meeting(114, (LEAD, HELPER))[0]
    stocked = meeting(114, (LEAD,), ball='GREAT_BALL')[0]
    assert not any(collection.deferred(changed, enemy.species) for changed in (taught, joined, stocked))


@pytest.mark.parametrize('case', ['weakened', 'great ball', 'trapped', 'snorlax', 'power plant', 'legendary',
                                  'shiny'])
def test_these_long_shots_get_throws(case):
    dex = {'snorlax': 143, 'power plant': 101, 'legendary': 145}.get(case, 114)
    state, enemy = meeting(dex, (LEAD,), ball='GREAT_BALL' if case == 'great ball' else 'POKE_BALL',
                           hp=40 if case == 'weakened' else 60,
                           where=MAPS['POWER_PLANT'] if case == 'power plant' else MAPS['ROUTE_21'],
                           enemy_shiny=case == 'shiny')
    decision = decide(state, enemy, can_switch=case != 'trapped')
    assert (decision.kind, decision.defer) == ('item', False)
