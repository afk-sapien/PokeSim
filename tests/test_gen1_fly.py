"""Gen I Fly: HM02 from the girl in the Route 16 house after the League, taught to a partner it costs no
battle move, or to a stored one the PC brings onto the team."""
from dataclasses import replace

import pytest

from pokesim.policies.progression import Goal, fly_free, fly_goal, fly_learner
from pokesim.policies.storage import StorageController, field_partners
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import StoredMon
from pokesim.runtime.policy import PolicyContext
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_gen1_bicycle import BIKE, walkable_from_door
from test_strategy import flags, mon

PIDGEOT, PIDGEY, DODRIO = 151, 36, 116
AGILITY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND, FLY = 97, 17, 98, 18, 19
DRILL_PECK, TRI_ATTACK, HYPER_BEAM, SKY_ATTACK = 65, 161, 63, 143
BODY_SLAM, EARTHQUAKE, ROCK_SLIDE = 34, 89, 157
HM02 = ((ITEMS['HM02'], 1),)
# The ace, a strong Bulbasaur no other member comes near.
ACE = mon(level=100, attack=250, defense=250, speed=250, special=250, hp=300, max_hp=300, moves=(15, 22, 75, 34))
# The Pidgeot of a deep Red save: two moves that score nothing, so Fly over one of them costs nothing.
CARRIER = mon(species=PIDGEOT, types=(0, 2), level=44, moves=(AGILITY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND),
              pp=(30, 35, 30, 20), attack=96, defense=90, speed=110, special=80, hp=149, max_hp=149)
# Four attacks of four types, each the best into some opponent, so Fly in place of any of them scores lower.
FIGHTER = mon(species=DODRIO, types=(0, 2), level=60, moves=(DRILL_PECK, BODY_SLAM, EARTHQUAKE, ROCK_SLIDE),
              pp=(20, 15, 10, 10), attack=180, defense=120, speed=180, special=110, hp=200, max_hp=200)
PARTY = (ACE, CARRIER)


def stored(species, level, moves, box=0, position=0):
    return StoredMon(box, position, species, level, 'BIRD', moves, 0, (15, 15, 15, 15, 15), (0,) * 5)


def test_fly_goes_only_where_it_costs_no_battle_move():
    """Gen I Fly is a 70 power move over two turns, so it seldom scores higher than what it replaces."""
    assert fly_free(CARRIER)
    assert not fly_free(FIGHTER)
    assert fly_free(replace(FIGHTER, moves=(DRILL_PECK, BODY_SLAM, 0, 0)))
    # Sky Attack adds nothing past Drill Peck, so Fly over it costs nothing either.
    assert fly_free(replace(FIGHTER, moves=(DRILL_PECK, TRI_ATTACK, HYPER_BEAM, SKY_ATTACK)))
    assert not fly_free(ACE)
    assert not fly_free(replace(CARRIER, moves=(FLY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND)))
    assert fly_free(stored(PIDGEOT, 40, (AGILITY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND)))
    assert not fly_free(stored(DODRIO, 60, (DRILL_PECK, BODY_SLAM, EARTHQUAKE, ROCK_SLIDE)))


def test_the_learner_is_the_weakest_free_flier_and_never_the_ace():
    young = replace(CARRIER, level=20, nick='YOUNG')
    assert fly_learner((ACE, CARRIER, young)) == 2
    assert fly_learner((ACE, FIGHTER)) is None
    assert fly_learner((replace(CARRIER, level=100, attack=300, special=300), young)) == 1
    assert fly_learner((replace(CARRIER, level=100, attack=300, special=300),)) is None


def test_hm02_is_fetched_then_taught_and_never_again():
    party = (ACE, CARRIER)
    assert fly_goal(snap(party=party)).key == 'fly'
    assert fly_goal(snap(party=party, items=HM02)).key == 'teach_fly'
    assert fly_goal(snap(party=(ACE, replace(CARRIER, moves=(FLY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND))))) is None
    # HM02 left in the PC never comes back to the bag, so the run goes on without Fly.
    assert fly_goal(snap(party=party, event_flags=flags('EVENT_GOT_HM02'))) is None


def test_hm02_waits_for_room_in_the_bag():
    """Deep Red saves carry twenty kinds, story key items among them, which the ledger never sells."""
    fill = tuple((ITEMS['POTION'] + k, 1) for k in range(20))
    assert fly_goal(snap(party=(ACE, CARRIER), items=fill[:19])).key == 'fly'
    assert fly_goal(snap(party=(ACE, CARRIER), items=fill)) is None


def test_with_no_free_flier_in_the_party_a_stored_one_is_withdrawn():
    """A League battler's move is never spent on Fly, and with nothing free to teach the run skips HM02."""
    assert fly_goal(snap(party=(ACE, FIGHTER))) is None
    boxed = (stored(DODRIO, 60, (DRILL_PECK, BODY_SLAM, EARTHQUAKE, ROCK_SLIDE), box=0, position=0),
             stored(PIDGEY, 12, (AGILITY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND), box=0, position=1),
             stored(PIDGEOT, 40, (AGILITY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND), box=2, position=3),
             stored(PIDGEOT, 30, (AGILITY, WING_ATTACK, QUICK_ATTACK, WHIRLWIND), box=0, position=2))
    s = snap(party=(ACE, FIGHTER), stored_details=boxed, active_box=0)
    assert fly_goal(s).key == 'fly'
    assert fly_goal(replace(s, items=HM02)).key == 'party_fly'
    # The strongest free flier is withdrawn, from the open box first. The Dodrio would lose an attack.
    assert sorted(field_partners(s, 'party_fly')) == [(0, 1, 12), (0, 2, 30), (2, 3, 40)]
    pc = StorageController()
    assert pc.field_move_box(s, 'party_fly') == 0
    assert pc.target(s, 'party_fly', None, {}) == 2
    assert pc.field_move_box(replace(s, stored_details=boxed[2:3]), 'party_fly') == 2


def test_the_house_goal_stands_where_the_door_leads():
    goal = fly_goal(snap(party=(ACE, CARRIER)))
    assert any((x, y) in walkable_from_door(m) for m, x, y in goal.targets)
    assert {m for m, _, _ in goal.targets} == {MAPS['ROUTE_16_FLY_HOUSE']}


def test_a_run_past_the_league_fetches_hm02_after_the_bicycle_and_only_between_projects():
    policy = StrategicPolicy(7)
    hunt = Goal('collect_hunt', 'Hunt', 'Find grass', ((255, 1, 1), (255, 2, 1)))
    policy.collection.completed_champion = True
    policy.collection.project = {'key': 'grass:1', 'method': 'hunt'}
    policy.collection.remaining = 10 ** 6
    policy.collection.goal = lambda *_, **__: hunt
    policy.nav.guided = lambda *args, **kwargs: 'up'
    for frame in (0, 60):
        policy.step(PolicyContext(snap(frame=frame, party=PARTY, items=BIKE), frame, bytearray(65536)))
    assert policy.goal.key == 'collect_hunt'
    policy.collection.project = None
    policy.step(PolicyContext(snap(frame=120, party=PARTY), 120, bytearray(65536)))
    assert policy.goal.key == 'bike_voucher'
    policy.step(PolicyContext(snap(frame=180, party=PARTY, items=BIKE), 180, bytearray(65536)))
    assert policy.goal.key == 'fly'


@pytest.mark.parametrize('items, key', [(BIKE, 'fly'), (BIKE + HM02, 'teach_fly')])
def test_the_fetch_and_the_teach_draw_no_project(items, key):
    policy = StrategicPolicy(7)
    collection = policy.collection
    collection.completed_champion = True
    drawn = []
    collection.offers = lambda *args, **kwargs: drawn.append(args) or Goal('collect_hunt', 'Hunt', 'Find grass')
    state = snap(party=PARTY, items=items, event_flags=flags('EVENT_GOT_POKEDEX'))
    goal = fly_goal(state)
    assert goal.key == key
    assert collection.pick(state, policy.nav, policy.rng, goal) is None
    assert not drawn
