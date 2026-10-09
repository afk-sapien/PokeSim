from dataclasses import asdict, replace

from pokesim.battle_power import battle_power, battler, moveset_score
from pokesim.pokemon import stored_strength
from pokesim.policies.battle import replacement_slot
from pokesim.policies.collection import Collection, EVOS
from pokesim.policies.move_development import evolution_wait, hm_upgrade
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import ITEMS, MAPS, SPECIES
from pokesim.web.pokedex import live_status
from test_collection import state
from shortcut_fakes import Recorder


def partner(name='STARMIE', **changes):
    species = next(sid for sid, data in SPECIES.items() if data['name'] == name)
    return {'species': species, 'level': 90, 'dvs': [11, 13, 14, 9, 15],
            'stat_exp': [65535] * 5, 'moves': [33, 0, 0, 0], **changes}


def live(mon):
    return replace(battler(mon), dvs=tuple(mon['dvs']), stat_exp=tuple(mon['stat_exp']),
                   pp=tuple(35 if mid else 0 for mid in mon['moves']))


def test_surf_improves_actual_starmie_but_does_not_change_stat_power():
    tackle = partner()
    surf = {**tackle, 'moves': [33, 57, 0, 0]}
    assert battle_power(surf) > battle_power(tackle) * 2
    assert stored_strength(tackle) == stored_strength(surf)
    assert live_status({'storage': {'pokemon': [tackle]}})['storage']['pokemon'][0]['battle_power'] == battle_power(tackle)


def test_move_score_uses_the_attacking_stat_for_the_move_type():
    base = battler(partner())
    physical = replace(base, attack=300, special=100)
    special = replace(base, attack=100, special=300)
    assert moveset_score(physical, (33,)) > moveset_score(special, (33,))
    assert moveset_score(special, (57,)) > moveset_score(physical, (57,))


def test_power_is_stable_when_hurt_or_out_of_pp_and_unknown_is_unavailable():
    base = partner(moves=[57, 94, 105, 0])
    assert battle_power(base) == battle_power({**base, 'hp': 0, 'status': 64, 'pp': [0] * 4})
    assert battle_power({**base, 'moves': None}) is None
    assert battle_power({**base, 'moves': [999]}) is None
    assert battle_power({**base, 'dvs': []}) is None
    assert battle_power({**base, 'moves': [0] * 4}) == 0


def test_coverage_and_recovery_help_but_duplicate_moves_do_not_stack():
    mon = battler(partner())
    assert moveset_score(mon, (57, 85)) > moveset_score(mon, (57,))
    assert moveset_score(mon, (57, 105)) > moveset_score(mon, (57,))
    assert moveset_score(mon, (57, 57)) == moveset_score(mon, (57,))
    assert moveset_score(mon, (105, 106)) == 0
    assert moveset_score(mon, (90,)) == 0
    assert moveset_score(mon, (153,)) < moveset_score(mon, (57,))


def test_move_learning_considers_special_stat_and_keeps_hms():
    mon = replace(battler(partner()), moves=(57, 33, 70, 105))
    assert replacement_slot(mon, 94) == 1
    assert replacement_slot(replace(mon, moves=(15, 19, 57, 70)), 94) is None


def test_staryu_waits_for_water_gun_and_recover_before_stone_evolution():
    mon = partner('STARYU', level=15)
    evo = EVOS[mon['species']][0]
    assert evolution_wait(mon, evo) == (17, 55)
    assert evolution_wait({**mon, 'moves': [33, 57, 0, 0]}, evo) == (27, 105)
    collection = Collection()
    collection.project = {'method': 'evolve', 'parent': mon['species'],
                          'species': evo['species'], 'evolution': evo}
    s = state(party=(live(mon),), items=((ITEMS['WATER_STONE'], 1),))
    goal = collection.goal(s)
    assert goal.key == 'collect_train'
    assert 'Water Gun' in goal.title
    assert goal.targets
    ready = partner('STARYU', level=50, moves=[57, 105, 129, 113])
    assert collection.goal(replace(s, party=(live(ready),))).key == 'collect_evolve'


def test_non_stone_evolution_and_finished_learnsets_are_not_delayed():
    mon = partner('BULBASAUR', level=15)
    assert evolution_wait(mon, EVOS[mon['species']][0]) is None
    old = partner('STARYU', level=100)
    assert evolution_wait(old, EVOS[old['species']][0]) is None


def test_existing_surf_user_does_not_prevent_teaching_starmie():
    weak = live(partner())
    other = live(partner('LAPRAS', moves=[57, 58, 34, 47]))
    s = state(party=(weak, other), items=((ITEMS['HM03'], 1),))
    _, target, item, move = hm_upgrade(s)
    assert (target, item, move) == (0, ITEMS['HM03'], 57)
    taught = replace(weak, moves=(33, 57, 0, 0))
    assert hm_upgrade(replace(s, party=(taught, other))) is None
    assert hm_upgrade(replace(s, items=())) is None
    assert hm_upgrade(replace(s, party=(replace(weak, moves=(33, 55, 106, 129)),))) is None


def test_policy_opens_hm_menu_for_specific_partner_and_bounds_retries():
    s = state(party=(live(partner()),), items=((ITEMS['HM03'], 1),),
              map=MAPS['PALLET_TOWN'], frame=10000)
    policy = StrategicPolicy(1)
    shortcuts = Recorder.on(policy)
    policy.goal = Goal('collect_plan', 'Plan', 'Plan')
    policy._overworld(s, bytearray(65536))
    assert policy.goal.key == 'teach_battle'
    assert (shortcuts.last.kind, shortcuts.last.item, shortcuts.last.target) == ('use_item', ITEMS['HM03'], 0)
    assert policy.move_teaching_after > s.frame
