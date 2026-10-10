"""Day Care breeding keeps gift and static families coming once their one copy is in hand."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def mon(species, gender='Male', *, box=0, dvs=(10, 10, 10, 10, 10), level=30, **extra):
    fields = dict(species=species, name=str(species), gender=gender, egg=False, box=box, position=0, trainer_id=4321, dvs=dvs,
                  moves=(33, 0, 0, 0), level=level, friendship=70, held_item=0, experience=30000, stat_exp=(0,) * 5)
    fields.update(extra)
    return SimpleNamespace(**fields)


def lead():
    return mon(157, box=None, dvs=(1,) * 5, moves=(57, 15, 53, 0), level=100, trainer_id=1)


def snapshot(stored, *, owned=None, boxes=(5,) * 14):
    return SimpleNamespace(party=(lead(),), stored=tuple(stored), daycare=(None, None), egg_ready=False,
                           owned=set(range(1, 252)) if owned is None else owned, money=50000, box_counts=boxes,
                           active_box=0, map=1, x=1, y=1, items=())


def planner(data, demand):
    storage = SimpleNamespace(map_name='GOLDENROD_POKECENTER_1F', x=1, y=1, face='up')
    return SimpleNamespace(data=data, collection={}, demand=demand, storage_goal=lambda snapshot: storage)


def test_gift_and_static_families_have_no_wild_source(real_data):
    from pokesim.gen2.breeding import single_source
    single = single_source(real_data)
    # Eevee and every Eeveelution, Tyrogue and the Hitmons, Togepi, Sudowoodo, Snorlax and Lapras.
    assert {133, 134, 135, 136, 196, 197, 236, 106, 107, 237, 175, 176, 185, 143, 131} <= set(single)
    assert single[196] == single[133] and 236 in single[237]
    # Ditto, Pikachu and the Odd Egg babies are wild, and legendaries cannot breed at all.
    assert not {132, 25, 172, 173, 174, 238, 239, 240, 147, 213, 249, 250, 243} & set(single)


def test_cable_demand_for_espeon_breeds_another_eevee(real_data):
    from pokesim.gen2.breeding import journey
    from pokesim.gen2.policy import Goal
    espeon, ditto = mon(196, dvs=(10, 9, 8, 7, 6)), mon(132, 'Genderless', dvs=(3, 4, 5, 6, 7))
    policy = planner(real_data, {196: 1})
    goal = journey(policy, snapshot((espeon, ditto)), Goal)
    project = policy.collection['breeding']
    assert project['target'] == 133 and project['duplicate'] and sorted(project['species']) == [132, 196]
    assert goal.key == 'collection_breed_pc'
    # Another Eevee in the box can already become the requested Espeon.
    policy = planner(real_data, {196: 1})
    assert journey(policy, snapshot((espeon, ditto, mon(133, dvs=(1, 2, 3, 4, 5)))), Goal) is None
    assert policy.collection.get('breeding') is None


def test_cable_demand_for_a_hitmon_breeds_tyrogue_and_waits_for_box_space(real_data):
    from pokesim.gen2.breeding import journey
    from pokesim.gen2.policy import Goal
    hitmonlee, ditto = mon(106, dvs=(10, 9, 8, 7, 6)), mon(132, 'Genderless', dvs=(3, 4, 5, 6, 7))
    policy = planner(real_data, {237: 1})
    journey(policy, snapshot((hitmonlee, ditto)), Goal)
    assert policy.collection['breeding']['target'] == 236
    policy = planner(real_data, {237: 1})
    assert journey(policy, snapshot((hitmonlee, ditto), boxes=(20,) * 13 + (18,)), Goal) is None
    # Without a request, a family that is complete and owned does not breed again.
    policy = planner(real_data, {})
    assert journey(policy, snapshot((hitmonlee, ditto)), Goal) is None


def test_the_last_parent_of_a_single_source_family_stays_home(real_data):
    from pokesim.gen2.breeding import breeding_stock
    assert breeding_stock(real_data, [132, 196, 25, 143]) == {132, 196, 143}
    assert breeding_stock(real_data, [132, 132, 133, 196, 25, 143, 143]) == set()


def test_collection_keeps_a_ditto_after_the_pokedex_is_complete(real_data):
    from pokesim.gen2.collection import prerequisites
    assert 132 in prerequisites(real_data, snapshot((mon(133),)))
    assert 132 not in prerequisites(real_data, snapshot((mon(132, 'Genderless'),)))


def test_happiness_levels_follow_the_cartridge_tiers():
    from pokesim.gen2.training import happiness_levels
    assert happiness_levels(220) == 0
    assert happiness_levels(219) == 1
    assert happiness_levels(120) == 37
    assert happiness_levels(70) == 49


def test_cable_demand_evolves_a_spare_eevee_and_tyrogue(real_data):
    from pokesim.gen2.training import projects
    eevee = mon(133, level=20, experience=8000, friendship=220)
    state = snapshot((eevee,))
    assert not projects(real_data, state, 'night')
    assert {row[4] for row in projects(real_data, state, 'night', {197: 1})} == {197}
    assert not projects(real_data, state, 'day', {197: 1})
    # Attack above Defense at level 20 makes Hitmonlee, so only a Hitmonlee request trains this one.
    tyrogue = mon(236, level=19, experience=6000, dvs=(10, 15, 0, 10, 10))
    state = snapshot((tyrogue,))
    assert {row[4] for row in projects(real_data, state, 'day', {106: 1, 107: 1})} == {106}


def test_eevee_waits_without_exp_share_for_the_time_of_day(real_data):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import identity, journey
    share = real_data.items['EXP_SHARE']
    eevee = mon(133, box=None, level=40, friendship=218, held_item=share)
    state = snapshot(())
    state.party = (lead(), eevee)
    state.owned -= {197}
    state.map = real_data.map_ids['GOLDENROD_CITY']
    policy = planner(real_data, {})
    policy.collection['training'] = {'identity': identity(eevee), 'target': 197, 'item': None, 'species': 133,
                                     'terminal': False}
    day = SimpleNamespace(byte=lambda name: 1)
    goal = journey(policy, state, day, Goal)
    assert goal.key == 'collection_take' and policy.collection['take_slot'] == 1
    eevee.held_item = 0
    state.items = ((share, 1),)
    assert journey(policy, state, day, Goal) is None
    assert policy.collection['training'] is None
    # At night the same Eevee is chosen again, and Umbreon is its project.
    journey(policy, state, SimpleNamespace(byte=lambda name: 2), Goal)
    assert policy.collection['training']['target'] == 197
