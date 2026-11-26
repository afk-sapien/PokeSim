"""The training walk heals and leads by the members that can still fight on its map."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData

SITE = 'ROUTE_29'


@pytest.fixture(scope='module', params=['gold', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def mon(data, trainer_id, level, hp=100, held=0):
    tackle = next(mid for mid, entry in data.moves.items() if entry['constant'] == 'TACKLE')
    return SimpleNamespace(egg=False, species=16, level=level, hp=hp, max_hp=100, status=0, moves=(tackle,),
                           pp=(data.moves[tackle]['pp'],), held_item=held, trainer_id=trainer_id,
                           dvs=(trainer_id, 0, 0, 0), stats=(100, 50, 50, 50, 50, 50), name=str(trainer_id))


def walk(data):
    """A policy on the training walk at SITE and that map's top wild level."""
    from pokesim.gen2.policy import Goal, Policy
    from pokesim.gen2.training import wild_levels
    policy = Policy(data, seed=1, starter='cyndaquil')
    policy.goal = Goal('collection_train', 'Train the partner', SITE, 5, 5, 'up')
    return policy, wild_levels(policy)[data.map_ids[SITE]]


def train(policy, party, slot):
    """The training project raises ``party[slot]``, which holds the Exp. Share."""
    from pokesim.gen2.training import identity
    party[slot].held_item = policy.data.items['EXP_SHARE']
    policy.collection['training'] = {'identity': identity(party[slot])}
    return SimpleNamespace(party=tuple(party), stored=(), items=(), map=policy.data.map_ids[SITE], x=5, y=5, frame=0,
                           badges=0, event=lambda name: True, owned=frozenset(), roamers=(), enemy_level=0,
                           enemy_species=16, enemy_hp=100)


def test_a_worn_partner_waits_while_another_member_can_fight(data):
    from pokesim.gen2.ledger import walk_spent
    from pokesim.gen2.training import training_spent
    policy, top = walk(data)
    # A fighter in front, a partner worn below the heal line and a low trainee that has not fought.
    party = [mon(data, 1, top + 10), mon(data, 2, top + 10, hp=30), mon(data, 3, 2)]
    snapshot = train(policy, party, 2)
    assert walk_spent(data, snapshot)
    assert training_spent(policy, snapshot) is False
    goal, _ = policy.heal.offer(policy, snapshot)
    assert goal is None
    # Once the lead is worn too no fighter is left, and the party heals.
    party[0].hp = 30
    assert training_spent(policy, snapshot) is True
    goal, _ = policy.heal.offer(policy, snapshot)
    assert goal is not None and goal.key == 'heal'
    # A fainted trainee gains nothing, so it heals while a fighter is still fresh.
    party[0].hp, party[2].hp = 100, 0
    assert training_spent(policy, snapshot) is True
    # Off the training walk the usual rule decides.
    policy.goal = None
    assert training_spent(policy, snapshot) is None


def test_the_trainee_leads_the_walk_once_it_can_fight_there(data):
    from pokesim.gen2.menus import Lead
    from pokesim.gen2.training import training_lead
    policy, top = walk(data)
    party = [mon(data, 1, top + 6), mon(data, 2, top + 30), mon(data, 3, top + 5)]
    snapshot = train(policy, party, 2)
    assert training_lead(policy, snapshot) == 2
    assert policy.level_lead(snapshot) == Lead(2, (3, (3, 0, 0, 0)))
    # A trainee too low for the map stays back, and a fighting lead keeps its place over a stronger partner.
    party[2].level = top
    assert training_lead(policy, snapshot) == 0
    assert policy.level_lead(snapshot) is None
    # A worn lead gives way to the fighter with the most room.
    party[0].hp = 30
    assert training_lead(policy, snapshot) == 1
    assert policy.level_lead(snapshot) == Lead(1, (2, (2, 0, 0, 0)))


def foe(policy, *effects):
    """The wild foe's moves as the battle reads them: one move of each effect in ``effects``."""
    moves = tuple(next(mid for mid, entry in policy.data.moves.items() if entry.get('effect') == effect)
                  for effect in effects)
    policy.reads = SimpleNamespace(enemy=SimpleNamespace(moves=moves, stats=(100, 50, 50, 50, 50, 50), status=0,
                                                         dvs=(0, 0, 0, 0, 0)))


def test_a_trainee_leading_the_walk_switches_out_of_a_close_battle(data):
    policy, top = walk(data)
    foe(policy)
    party = [mon(data, 3, top + 5), mon(data, 1, top + 20), mon(data, 2, top + 10)]
    snapshot = train(policy, party, 0)
    snapshot.enemy_level = top + 2
    assert policy.trainee_switch(snapshot, 0) == 1
    # Far enough above the foe it fights the battle out.
    snapshot.enemy_level = top
    assert policy.trainee_switch(snapshot, 0) is None
    # Off the training walk a trainee with its Exp. Share is no lead of its own.
    snapshot.enemy_level = top + 2
    policy.goal = None
    assert policy.trainee_switch(snapshot, 0) is None


def test_a_leading_trainee_leaves_a_foe_that_would_trap_it_in_a_lost_fight(data):
    policy, top = walk(data)
    party = [mon(data, 3, top + 20), mon(data, 1, top + 10, hp=70), mon(data, 2, top + 10)]
    snapshot = train(policy, party, 0)
    snapshot.enemy_level = top
    # Far above an ordinary foe it fights the battle out.
    foe(policy, 'EFFECT_CONFUSE', 'EFFECT_NORMAL_HIT')
    assert policy.trainee_switch(snapshot, 0) is None
    # It beats a foe with Mean Look in fewer turns than the foe needs, so it stays and keeps all the experience.
    foe(policy, 'EFFECT_CONFUSE', 'EFFECT_MEAN_LOOK', 'EFFECT_NORMAL_HIT')
    assert policy.trainee_switch(snapshot, 0) is None
    # Its Tackle cannot touch a Gastly, so the trap would hold it in a fight it loses, and it gives way to the
    # fighter with the most room.
    snapshot.enemy_species = next(sid for sid, entry in data.species.items() if entry['constant'] == 'GASTLY')
    assert policy.trainee_switch(snapshot, 0) == 2
    # Without Mean Look it can still leave once its HP runs low, so it fights on.
    foe(policy, 'EFFECT_CONFUSE', 'EFFECT_NORMAL_HIT')
    assert policy.trainee_switch(snapshot, 0) is None
    # A foe that cannot hurt it never wins, trap or not.
    foe(policy, 'EFFECT_CONFUSE', 'EFFECT_MEAN_LOOK')
    assert policy.trainee_switch(snapshot, 0) is None
    # Off the training walk the usual rule decides.
    foe(policy, 'EFFECT_CONFUSE', 'EFFECT_MEAN_LOOK', 'EFFECT_NORMAL_HIT')
    policy.goal = None
    assert policy.trainee_switch(snapshot, 0) is None


def test_a_trainee_losing_on_the_walk_hands_the_battle_to_the_fighter_with_most_room(data):
    policy, top = walk(data)
    foe(policy)
    # The highest member is worn below the heal line, so the walk would pull it again a turn later.
    party = [mon(data, 3, top + 5), mon(data, 1, top + 30, hp=30), mon(data, 2, top + 10)]
    snapshot = train(policy, party, 0)
    snapshot.enemy_level = top + 2
    assert policy.trainee_switch(snapshot, 0) == 2
    # Healed, it has as much room as the other and takes the battle by its place in the party.
    party[1].hp = 100
    assert policy.trainee_switch(snapshot, 0) == 1


def test_a_spent_member_gives_way_mid_battle_on_the_walk(data):
    policy, top = walk(data)
    foe(policy)
    party = [mon(data, 1, top + 30), mon(data, 2, top + 10), mon(data, 3, 2)]
    snapshot = train(policy, party, 2)
    snapshot.enemy_level = top
    assert policy.trainee_switch(snapshot, 0) is None
    # Its last strong PP went this battle, so the fighter with room takes over before it is left with
    # nothing but a move that knocks itself out.
    party[0].pp = (0,)
    assert policy.trainee_switch(snapshot, 0) == 1
    # Below the heal line it gives way the same way.
    party[0].pp, party[0].hp = (35,), 40
    assert policy.trainee_switch(snapshot, 0) == 1
    # A member no higher than the foe is no fighter here, so it is left as it is.
    party[0].level = top
    assert policy.trainee_switch(snapshot, 0) is None
    # So is any member off the training walk.
    party[0].level = top + 30
    policy.goal = None
    assert policy.trainee_switch(snapshot, 0) is None


@pytest.mark.parametrize('lead', ['roam', 'tower', 'legend', 'static_lead', 'quest', 'release', 'box'])
def test_the_training_walk_keeps_each_deliberate_lead(data, lead):
    from pokesim.gen2.policy import Goal
    policy, top = walk(data)
    # A low sleeper leads, and the trainee in slot 2 could fight on the map, so the walk would lead with it.
    party = [mon(data, 9, 3), mon(data, 1, top + 30), mon(data, 2, top + 6)]
    snapshot = train(policy, party, 2)
    assert policy.level_lead(snapshot) is not None
    sleeper = (party[0].trainer_id, tuple(party[0].dvs))
    if lead == 'roam':
        policy.collection['roam_lead'] = True
        snapshot.roamers = ({'species': 243, 'map': snapshot.map},)
    elif lead == 'tower':
        policy.collection['tower'] = {'preparation_center': True, 'returning': False}
    elif lead == 'legend':
        policy.goal = Goal('legend_suicune', 'Suicune', SITE, 5, 5, 'up')
    elif lead == 'static_lead':
        policy.goal = Goal('collection_static_lead', 'Lead with the sleeper', SITE, 5, 5, 'up')
    elif lead == 'quest':
        policy.static_sleeper = sleeper
        policy.legend_decision = policy.decisions
    else:
        policy.static_sleeper = sleeper
        policy.goal = Goal(f'collection_{lead}', 'Make room in storage', 'CHERRYGROVE_POKECENTER_1F', 3, 1, 'up')
    assert policy.level_lead(snapshot) is None
    # Mid battle the walk never sends the sleeper out either, even worn and facing a foe that traps.
    foe(policy, 'EFFECT_MEAN_LOOK')
    snapshot.enemy_level = top
    party[0].hp = 30
    assert policy.trainee_switch(snapshot, 0) is None
