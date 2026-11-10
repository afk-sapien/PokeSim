"""A Gen II catch under 1 in 10 a throw weakens its target first, with a switch when the battler cannot,
and leaves a target nobody can weaken for later rather than spending its balls on it."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData
from pokesim.planning.throws import THROW_BAR, gen2_throw

TANGELA, CHANSEY, SNORLAX = 114, 113, 143


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def test_a_throw_follows_the_cartridge_formula():
    # Tangela's catch rate is 45. At full HP a Poké Ball meets a third of it, an Ultra Ball twice that.
    assert gen2_throw(45, 1, 60, 60, 0) == 16 / 256 < THROW_BAR
    assert gen2_throw(45, 2, 60, 60, 0) == 31 / 256 > THROW_BAR
    # Past 255 the cartridge quarters both HP values, and only sleep or freeze add 10.
    assert gen2_throw(45, 1, 200, 200, 0) == 16 / 256
    assert gen2_throw(45, 1, 60, 60, 2) == 26 / 256
    assert gen2_throw(45, 1, 60, 60, 64) == 16 / 256
    assert gen2_throw(255, 2, 1, 60, 2) == 1


def member(species, level, moves, stats, hp):
    return SimpleNamespace(species=species, level=level, moves=moves, pp=tuple(30 if move else 0 for move in moves),
                           stats=stats, hp=hp, max_hp=hp, status=0, egg=False)


# A Meganium whose every attack could knock the target out, and a Pidgey whose Tackle cannot.
LEAD = member(154, 57, (34, 15, 0, 0), (191, 110, 110, 100, 100, 100), 191)
HELPER = member(16, 14, (33, 0, 0, 0), (35, 20, 18, 25, 18, 18), 35)


def meeting(real_data, species, party, ball='POKE_BALL', hp=60):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    policy.battle_task = lambda task, snapshot, mem: SimpleNamespace(button=task.key())
    policy.needed_move = lambda snapshot: 0
    policy.move_score = lambda *args: 1
    policy.remedy = lambda *args, **kwargs: False
    snapshot = SimpleNamespace(party=party, stored=(), text='FIGHT', tiles=(), map=real_data.map_ids['ROUTE_36'],
        in_battle=1, enemy_species=species, enemy_hp=hp, enemy_max_hp=60, enemy_level=30, owned=set(),
        can_catch=True, badges=65535, money=10000, items=(), pockets={'balls': [(real_data.items[ball], 20)]})
    mem = SimpleNamespace(byte=lambda name: 1 if name in {'wMenuCursorX', 'wMenuCursorY'} else 0,
                          word=lambda name: 40, read=lambda name, size: bytes(size))
    return policy, snapshot, mem


def test_a_long_shot_switches_to_a_member_that_can_weaken_it(real_data):
    policy, snapshot, mem = meeting(real_data, TANGELA, (LEAD, HELPER))
    assert policy.battle(snapshot, mem).button == ('Send', 1)


def test_a_long_shot_nobody_can_weaken_is_left_for_a_new_move_member_or_ball(real_data):
    from pokesim.gen2.collection import deferred
    policy, snapshot, mem = meeting(real_data, TANGELA, (LEAD,))
    assert policy.battle(snapshot, mem).button == ('Flee',)
    assert deferred(policy, snapshot, TANGELA)
    # An Ultra Ball lifts the throw over 1 in 10, so the deferral ends and the balls go.
    policy, snapshot, mem = meeting(real_data, TANGELA, (LEAD,), ball='ULTRA_BALL')
    policy.collection['deferred'] = {str(TANGELA): 'before the Ultra Balls'}
    assert not deferred(policy, snapshot, TANGELA)
    assert policy.battle(snapshot, mem).button == ('Throw', real_data.items['ULTRA_BALL'])


def test_a_weakened_target_gets_throws_whatever_the_odds(real_data):
    # Chansey at 24 of 60 HP is still under 1 in 10 a Poké Ball, and nobody here can weaken it further.
    assert gen2_throw(30, 1, 24, 60, 0) < THROW_BAR
    policy, snapshot, mem = meeting(real_data, CHANSEY, (LEAD,), hp=24)
    assert policy.battle(snapshot, mem).button == ('Throw', real_data.items['POKE_BALL'])


def test_a_one_time_encounter_always_gets_throws(real_data):
    policy, snapshot, mem = meeting(real_data, SNORLAX, (LEAD,))
    assert policy.battle(snapshot, mem).button == ('Throw', real_data.items['POKE_BALL'])


def test_a_deferred_species_is_not_hunted(real_data):
    from pokesim.gen2.collection import defer, deferred
    policy, snapshot, _ = meeting(real_data, TANGELA, (LEAD,))
    defer(policy, snapshot, TANGELA)
    assert deferred(policy, snapshot, TANGELA)
    # A new member changes what can weaken it, so the species is wanted again.
    assert not deferred(policy, SimpleNamespace(party=(LEAD, HELPER), pockets=snapshot.pockets), TANGELA)
