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
                           active_box=0, map=1, x=1, y=1, items=(), pockets={})


def planner(data, demand):
    storage = SimpleNamespace(map_name='GOLDENROD_POKECENTER_1F', x=1, y=1, face='up')
    return SimpleNamespace(data=data, collection={}, demand=demand, storage_goal=lambda snapshot: storage)


def test_gift_and_static_families_have_no_wild_source(real_data):
    from pokecore.gen2.breeding import single_source
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
    from pokecore.gen2.breeding import breeding_stock
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


def egg(species, **extra):
    return mon(species, egg=True, level=5, friendship=20, **extra)


def hatcher(data, party, stored, *, boxes=(5,) * 14, daycare=(None, None), release=None, owned=None):
    # The eggs belong to unregistered species unless a test says otherwise, so each one is worth a trip.
    eggs = {mon.species for mon in tuple(party) + tuple(stored) if mon.egg}
    state = snapshot(stored, boxes=boxes, owned=set(range(1, 252)) - eggs if owned is None else owned)
    state.party, state.daycare = tuple(party), daycare
    policy = planner(data, {})
    policy.decisions = 1000
    policy.release_target = lambda snapshot: release
    policy.person = lambda snapshot, key, label, map_name, script: SimpleNamespace(key=key, map_name=map_name)
    return policy, state


def test_a_boxed_egg_stops_its_line_from_breeding_again(real_data):
    """Gold boxed 54 Sneasel eggs: each training deposit stored the new egg and the project bred another."""
    from pokesim.gen2.breeding import journey, pairings
    from pokesim.gen2.policy import Goal
    eevee, ditto = mon(196, dvs=(10, 9, 8, 7, 6)), mon(132, 'Genderless', dvs=(3, 4, 5, 6, 7))
    policy = planner(real_data, {196: 1})
    assert any(row[0] == 133 for row in pairings(policy, snapshot((eevee, ditto))))
    policy = planner(real_data, {196: 1})
    boxed = snapshot((eevee, ditto, egg(133, box=1, dvs=(2, 2, 2, 2, 2))))
    assert not any(row[0] == 133 for row in pairings(policy, boxed))
    assert journey(policy, boxed, Goal) is None and policy.collection.get('breeding') is None
    # A project already running does not collect the ready egg while one of its line sits in a box.
    policy = planner(real_data, {196: 1})
    policy.collection['breeding'] = {'target': 133, 'parents': [[4321, [10, 9, 8, 7, 6]], [4321, [3, 4, 5, 6, 7]]],
                                     'species': [196, 132], 'duplicate': True, 'existing': []}
    boxed.egg_ready = True
    policy.person = lambda *args: pytest.fail('collected another egg while one was boxed')
    assert journey(policy, boxed, Goal) is None and policy.collection['breeding'] is None


def test_hatching_withdraws_boxed_eggs_into_a_free_party_slot(real_data):
    from pokesim.gen2.breeding import HATCH_BATCH, arrive, hatching, journey
    from pokesim.gen2.menus import ChangeBox, Storage
    from pokesim.gen2.policy import Goal
    eggs = [egg(215, box=2, position=i, dvs=(i,) * 5) for i in range(5)]
    policy, state = hatcher(real_data, [lead()], eggs)
    # Training is walking time, so it asks for the eggs before it plans anything.
    from pokesim.gen2.training import journey as train
    assert train(policy, state, None, Goal).key == 'collection_hatch_pc'
    goal = hatching(policy, state, Goal)
    assert goal.key == 'collection_hatch_pc'
    policy.goal = goal
    assert arrive(policy, state) == 'a' and policy.menu == ChangeBox(2)
    state.active_box = 2
    assert arrive(policy, state) == 'a' and policy.menu == Storage('WITHDRAW', 0, 1)
    # A decision taken while the PC menu still moves the egg does not forget where it came from.
    assert journey(policy, state, Goal) is None
    # The carried egg walks with the other errands instead of the Goldenrod nursery.
    state.party, state.stored = (lead(), eggs[0]), tuple(eggs[1:])
    assert journey(policy, state, Goal) is None
    assert hatching(policy, state, Goal).key == 'collection_hatch_pc'
    state.party = (lead(),) + tuple(eggs[:HATCH_BATCH])
    state.stored = tuple(eggs[HATCH_BATCH:])
    assert hatching(policy, state, Goal) is None
    # Once the batch is out, carrying one egg does not start another trip until all have hatched.
    state.party = (lead(), eggs[0], mon(215, box=None, level=5))
    assert hatching(policy, state, Goal) is None


def test_hatching_swaps_a_spare_for_an_egg_and_never_stores_an_egg(real_data):
    from pokesim.gen2.breeding import arrive, hatching
    from pokesim.gen2.menus import Storage
    from pokesim.gen2.policy import Goal
    surf = mon(72, box=None, moves=(57, 0, 0, 0), level=40)
    trainee = mon(169, box=None, dvs=(2, 10, 8, 13, 8), level=66)
    spare = mon(143, box=None, level=50)
    party = [lead(), egg(215, box=None), surf, trainee, spare, mon(218, box=None, level=5)]
    policy, state = hatcher(real_data, party, [egg(215, box=0, dvs=(3,) * 5)])
    policy.collection['training'] = {'identity': [4321, [2, 10, 8, 13, 8]]}
    # A finished activity can leave its whole team on record. It does not pin the party.
    policy.collection['activity_team'] = ['2d3b3da9cc2c33ad8262fa21', '89b357461d992da1f414fbc0']
    policy.collection['hatch_fill'] = True
    policy.goal = hatching(policy, state, Goal)
    assert policy.goal.key == 'collection_hatch_pc'
    assert arrive(policy, state) == 'a' and policy.menu == Storage('DEPOSIT', 5, 6)
    # With only the egg, a sole Surf user and the trainee left besides the lead, nothing is stored.
    state.party = (lead(), egg(215, box=None), surf, trainee)
    state.party += (egg(215, box=None, dvs=(4,) * 5), egg(215, box=None, dvs=(5,) * 5))
    policy.collection['hatch_fill'] = True
    assert hatching(policy, state, Goal) is None
    policy.menu = None
    policy.collection['hatch_fill'], policy.collection['hatch_ops'] = True, 0
    state.party = (lead(), egg(215, box=None), surf, trainee, egg(215, box=None, dvs=(4,) * 5), spare)
    assert arrive(policy, state) == 'a' and policy.menu == Storage('DEPOSIT', 5, 6)


def test_hatching_waits_for_a_free_box_slot(real_data):
    from pokesim.gen2.breeding import hatching
    from pokesim.gen2.policy import Goal
    party = [lead(), mon(72, box=None, moves=(57, 0, 0, 0)), mon(218, box=None, level=5), mon(143, box=None, level=50)]
    party += [mon(16, box=None, dvs=(1, 2, 3, 4, 5)), mon(17, box=None, dvs=(5, 4, 3, 2, 1))]
    policy, state = hatcher(real_data, party, [egg(215)], boxes=(20,) * 14)
    assert hatching(policy, state, Goal) is None
    policy, state = hatcher(real_data, party, [egg(215)])
    assert hatching(policy, state, Goal).key == 'collection_hatch_pc'


def test_training_sends_an_egg_to_the_pc_last(real_data):
    from pokesim.gen2.menus import Storage
    from pokesim.gen2.training import arrive
    trainee = mon(169, box=3, position=4, dvs=(2, 10, 8, 13, 8), level=66)
    party = (lead(), mon(72, box=None, moves=(57, 0, 0, 0), level=40), egg(215, box=None),
             mon(18, box=None, moves=(19, 0, 0, 0), level=51), mon(143, box=None, level=50), mon(218, box=None, level=12))
    state = snapshot((trainee,))
    state.party = party
    policy = planner(real_data, {})
    policy.collection['training'] = {'identity': [4321, [2, 10, 8, 13, 8]]}
    policy.goal = SimpleNamespace(key='collection_train_pc')
    assert arrive(policy, state) == 'a' and policy.menu == Storage('DEPOSIT', 5, 6)


def test_an_egg_brought_out_to_hatch_never_goes_back_to_the_pc(real_data):
    """Gold traded one Sneasel egg between hatching and training at the PC for the whole replay."""
    from pokesim.gen2.breeding import egg_key, hatching
    from pokesim.gen2.menus import Storage
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import arrive
    trainee = mon(124, box=3, position=4, dvs=(2, 10, 8, 13, 8), level=48)
    carried = egg(215, box=None, dvs=(13, 5, 7, 10, 3))
    # Besides the lead and the egg, every member is the only holder of a field move.
    party = (lead(), carried, mon(72, box=None, moves=(148, 0, 0, 0), level=40), mon(18, box=None, moves=(19, 0, 0, 0), level=51),
             mon(40, box=None, moves=(70, 0, 0, 0), level=45), mon(54, box=None, moves=(127, 0, 0, 0), level=30))
    policy, state = hatcher(real_data, party, [trainee, egg(215, box=0, dvs=(3,) * 5)])
    policy.collection['training'] = {'identity': [4321, [2, 10, 8, 13, 8]]}
    policy.collection['hatching'] = [egg_key(carried)]
    policy.goal = SimpleNamespace(key='collection_train_pc')
    assert arrive(policy, state) == 'a' and policy.menu == Storage('DEPOSIT', 5, 6)
    # The trainee waiting in the PC keeps the freed slot, so no egg trip fills it first.
    state.party = party[:5]
    policy.collection['hatch_fill'] = True
    assert hatching(policy, state, Goal) is None


def test_fetching_the_exp_share_keeps_the_trainee_beside_a_carried_egg(real_data):
    """Gold then swapped Haunter and the Exp. Share holder Butterfree at the PC for the rest of the replay."""
    from pokesim.gen2.breeding import egg_key
    from pokesim.gen2.menus import Storage
    from pokesim.gen2.training import arrive
    holder = mon(12, box=3, position=4, dvs=(7, 7, 7, 7, 7), level=30)
    trainee = mon(93, box=None, dvs=(2, 10, 8, 13, 8), level=26)
    carried = egg(32, box=None, dvs=(9, 1, 6, 4, 9))
    party = (lead(), carried, trainee, mon(18, box=None, moves=(19, 0, 0, 0), level=51),
             mon(40, box=None, moves=(70, 0, 0, 0), level=45), mon(54, box=None, moves=(127, 0, 0, 0), level=30))
    policy, state = hatcher(real_data, party, [holder])
    policy.collection['training'] = {'identity': [4321, [2, 10, 8, 13, 8]]}
    policy.collection['share_holder'] = [4321, [7, 7, 7, 7, 7]]
    policy.collection['hatching'] = [egg_key(carried)]
    policy.goal = SimpleNamespace(key='collection_train_pc')
    assert arrive(policy, state) == 'a' and policy.menu == Storage('DEPOSIT', 5, 6)


def test_a_carried_egg_hatches_before_the_next_trainee_swaps_in(real_data, monkeypatch):
    """Gold has one spare beside its field move holders, so the egg takes it and the swap waits."""
    from pokesim.gen2.breeding import egg_key, hatching
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import journey
    party = [lead(), mon(72, box=None, moves=(250, 0, 0, 0)), mon(18, box=None, moves=(19, 0, 0, 0)),
             mon(40, box=None, moves=(70, 0, 0, 0)), mon(54, box=None, moves=(127, 0, 0, 0)), mon(143, box=None, level=50)]
    policy, state = hatcher(real_data, party, [egg(215)])
    assert hatching(policy, state, Goal).key == 'collection_hatch_pc'
    carried = egg(215, box=None)
    trainee = mon(93, box=3, position=4, dvs=(2, 10, 8, 13, 8), level=26)
    policy, state = hatcher(real_data, [*party[:5], carried], [trainee, egg(215, box=0, dvs=(3,) * 5)])
    policy.collection['training'] = {'identity': [4321, [2, 10, 8, 13, 8]], 'target': 93, 'item': None,
                                     'species': 93, 'terminal': True, 'level_goal': 54}
    policy.collection['hatching'] = [egg_key(carried)]
    state.items = ((real_data.items['EXP_SHARE'], 1),)
    clock = SimpleNamespace(byte=lambda name: 1)
    monkeypatch.setattr('pokesim.gen2.collection.encounter_points', lambda *args: [(9, 31, 0)])
    goal = journey(policy, state, clock, Goal)
    assert goal.key == 'collection_train' and goal.label.startswith('Walk to hatch the egg')
    # Once the egg hatches, the new partner is a spare and the trainee swaps in.
    state.party = (*party[:5], mon(215, box=None, level=5))
    assert journey(policy, state, clock, Goal).key == 'collection_train_pc'


def test_eggs_of_a_registered_species_never_hold_up_training(real_data, monkeypatch):
    """Gold boxed 28 Sneasel eggs, and fetching them one by one kept Crobat in the PC for about 110 game hours."""
    from pokesim.gen2.breeding import arrive, egg_key, hatching
    from pokesim.gen2.menus import ChangeBox, Storage
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import journey
    party = [lead(), mon(72, box=None, moves=(250, 0, 0, 0)), mon(18, box=None, moves=(19, 0, 0, 0)),
             mon(40, box=None, moves=(70, 0, 0, 0)), mon(54, box=None, moves=(127, 0, 0, 0)), mon(143, box=None, level=50)]
    sneasel = [egg(215, box=0, position=i, dvs=(i,) * 5) for i in range(5)]
    owned = set(range(1, 252))
    policy, state = hatcher(real_data, party[:5], [mon(215, box=1), *sneasel], owned=owned)
    # Every Sneasel egg would only add another copy of a registered species, so no trip fetches one.
    assert hatching(policy, state, Goal) is None
    # Cable demand for a Sneasel the PC lacks makes one worth hatching again.
    policy.demand = {215: 1}
    assert hatching(policy, state, Goal).key == 'collection_hatch_pc'
    # An egg of an unregistered species is brought ahead of the duplicates, whatever box it is in.
    policy, state = hatcher(real_data, party[:5], [*sneasel, egg(204, box=3, position=0)], owned=owned - {204, 205})
    policy.goal = hatching(policy, state, Goal)
    assert policy.goal.key == 'collection_hatch_pc'
    assert arrive(policy, state) == 'a' and policy.menu == ChangeBox(3)
    state.active_box = 3
    assert arrive(policy, state) == 'a' and policy.menu == Storage('WITHDRAW', 0, 5)
    # A duplicate egg already in a full party walks with no one waiting, but never blocks the trainee swap.
    carried = egg(215, box=None, dvs=(9,) * 5)
    trainee = mon(169, box=3, position=4, dvs=(2, 10, 8, 13, 8), level=40)
    policy, state = hatcher(real_data, [*party[:5], carried], [trainee, *sneasel], owned=owned)
    policy.collection['training'] = {'identity': [4321, [2, 10, 8, 13, 8]], 'target': 169, 'item': None,
                                     'species': 169, 'terminal': True, 'level_goal': 54}
    policy.collection['hatching'] = [egg_key(carried)]
    state.items = ((real_data.items['EXP_SHARE'], 1),)
    clock = SimpleNamespace(byte=lambda name: 1)
    monkeypatch.setattr('pokesim.gen2.collection.encounter_points', lambda *args: [(9, 31, 0)])
    assert journey(policy, state, clock, Goal).key == 'collection_train_pc'


def test_a_full_party_hatches_its_eggs_before_fetching_a_boxed_parent(real_data):
    """Gold stood at a Cherrygrove PC pressing B: four field move holders and two carried eggs left no slot."""
    from pokesim.gen2.breeding import egg_key, journey
    from pokesim.gen2.policy import Goal
    ditto, porygon2 = mon(132, 'Genderless', box=0, position=19, dvs=(1, 2, 6, 4, 1)), mon(233, 'Genderless', box=3, dvs=(2, 2, 0, 1, 14))
    carried = [egg(133, box=None, dvs=(9, 15, 6, 2, 1)), egg(204, box=None, dvs=(0, 4, 2, 6, 0))]
    holders = [mon(72, box=None, moves=(148, 0, 0, 0)), mon(18, box=None, moves=(19, 0, 0, 0)), mon(40, box=None, moves=(70, 0, 0, 0))]
    policy, state = hatcher(real_data, [lead(), *holders, *carried], [ditto, porygon2])
    policy.collection['hatching'] = [egg_key(mon) for mon in carried]
    policy.collection['breeding'] = {'target': 137, 'parents': [[4321, [1, 2, 6, 4, 1]], [4321, [2, 2, 0, 1, 14]]],
                                     'species': [132, 233], 'duplicate': True, 'existing': []}
    assert journey(policy, state, Goal).key == 'collection_hatch'
    # Once an egg hatches the new partner is a spare, so the PC can trade it for the parent.
    state.party = (lead(), *holders, mon(133, box=None, level=5), carried[1])
    assert journey(policy, state, Goal).key == 'collection_breed_pc'


def test_the_day_care_man_returns_his_partner_after_the_waiting_egg(real_data):
    """Gold then talked to the Day Care man's empty spot: with an egg waiting he stands outside on Route 34."""
    from pokesim.gen2.breeding import journey
    from pokesim.gen2.policy import Goal
    ditto, porygon2 = mon(132, 'Genderless', box=None, dvs=(1, 2, 6, 4, 1)), mon(233, 'Genderless', box=None, dvs=(2, 2, 0, 1, 14))
    policy, state = hatcher(real_data, [lead(), egg(137, box=None)], [], daycare=(ditto, porygon2))
    policy.collection['breeding'] = {'target': 137, 'parents': [[4321, [1, 2, 6, 4, 1]], [4321, [2, 2, 0, 1, 14]]],
                                     'species': [132, 233], 'duplicate': True, 'existing': []}
    state.egg_ready = True
    assert journey(policy, state, Goal).key == 'collection_breed_egg'
    state.egg_ready = False
    assert journey(policy, state, Goal).key == 'collection_breed_take_0'


@pytest.mark.parametrize('spare', [False, True])
def test_a_party_the_pc_cannot_take_from_stands_breeding_down(real_data, spare):
    """With no egg to hatch and nothing the PC may take, or every box full, the run pressed B at the PC forever."""
    from pokesim.gen2.breeding import BREED_KEY, journey
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import standing_down
    ditto, porygon2 = mon(132, 'Genderless', box=0, position=19, dvs=(1, 2, 6, 4, 1)), mon(233, 'Genderless', box=3, dvs=(2, 2, 0, 1, 14))
    holders = [mon(18, box=None, moves=(19, 0, 0, 0)), mon(40, box=None, moves=(70, 0, 0, 0)),
               mon(72, box=None, moves=(148, 0, 0, 0)), mon(130, box=None, moves=(250, 0, 0, 0)),
               mon(19 if spare else 119, box=None, moves=(33, 0, 0, 0) if spare else (127, 0, 0, 0))]
    policy, state = hatcher(real_data, [lead(), *holders], [ditto, porygon2], boxes=(20,) * 14 if spare else (5,) * 14)
    policy.collection['breeding'] = {'target': 137, 'parents': [[4321, [1, 2, 6, 4, 1]], [4321, [2, 2, 0, 1, 14]]],
                                     'species': [132, 233], 'duplicate': True, 'existing': []}
    assert journey(policy, state, Goal) is None
    assert policy.collection['breeding'] is None and standing_down(policy, BREED_KEY)
    # Standing down, the run does not plan the same pairing straight away.
    assert journey(policy, state, Goal) is None and policy.collection['breeding'] is None
