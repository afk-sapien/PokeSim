from dataclasses import replace

from pokesim.policies.awareness import ActionWatch
from pokesim.policies.battle import choose_battle, replacement_slot
from pokesim.policies.progression import teaching_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.team import development_candidate, readiness, reserve_to_deposit
from pokesim.strategy_data import ITEMS, MAPS, SPECIES
from test_events import snap
from test_strategy import flags, mon


def species(name):
    return next(sid for sid, data in SPECIES.items() if data.get('name') == name)


def test_cut_without_bulbasaur_seeks_local_habitats_not_lapras():
    s = snap(party=(mon(species=species('WARTORTLE'), level=30),), badges=3,
             map=MAPS['ROUTE_6'], event_flags=flags('EVENT_GOT_POKEDEX'))
    goal = teaching_goal('teach_cut', 'Teach Cut', 'Open the route', s)
    assert goal.key == 'catch_cut'
    assert any(m == MAPS['ROUTE_6'] for m, x, y in goal.targets)
    assert all(m != MAPS['SILPH_CO_7F'] for m, x, y in goal.targets)


def test_full_party_without_compatible_boxed_mon_still_seeks_a_catch():
    s = snap(party=(mon(species=species('PIDGEY')),)*6, boxed_pokemon=())
    assert teaching_goal('teach_cut', 'Cut', 'Open route', s).key == 'catch_cut'
    s = replace(s, boxed_pokemon=((species('ODDISH'), 12),))
    assert teaching_goal('teach_cut', 'Cut', 'Open route', s).key == 'party_cut'


def test_lapras_gift_requires_access_and_cannot_solve_cut():
    s = snap(party=(mon(species=species('PIDGEY')),), badges=63)
    assert teaching_goal('teach_surf', 'Surf', 'Cross water', s).key == 'catch_surf'
    s = replace(s, event_flags=flags('EVENT_BEAT_SILPH_CO_GIOVANNI'))
    assert teaching_goal('teach_surf', 'Surf', 'Cross water', s).key == 'lapras'
    assert teaching_goal('teach_cut', 'Cut', 'Open route', s).key == 'catch_cut'


def test_required_partner_is_caught_even_if_every_attack_would_knock_it_out():
    me = mon(level=60, hp=150, max_hp=150, attack=150, special=150)
    enemy = mon(species=species('ODDISH'), hp=10, max_hp=10, level=12)
    s = snap(party=(me,), in_battle=1, items=((ITEMS['POKE_BALL'], 5),))
    assert choose_battle(s, me, enemy, 0, required_move=15).kind == 'item'


def test_cycle_detection_ignores_training_and_recognizes_movement_without_progress():
    watch = ActionWatch()
    s = snap()
    failure = None
    for i in range(8):
        failure = watch.observe(replace(s, x=i % 2, frame=i * 30), 'overworld', None, 0) or failure
    assert failure and 'cycle' in failure
    watch = ActionWatch()
    assert all(watch.observe(replace(s, x=i % 2, frame=i * 30), 'overworld', None, 0, training=True) is None for i in range(20))


def test_action_deadline_survives_retries_but_battles_are_not_failed_walking():
    watch = ActionWatch()
    s = snap(frame=0)
    pos = (s.map, s.x, s.y)
    watch.begin('move', 'Leave the doorway', s, pos)
    watch.begin('move', 'Leave the doorway', replace(s, frame=400), pos)
    assert watch.observe(replace(s, frame=500), 'overworld', None, 0)
    watch.begin('move', 'Walk', s, pos)
    assert watch.observe(replace(s, frame=1000, in_battle=1), 'dialogue', None, 0) is None


def test_readiness_uses_matchups_and_available_pp():
    strong = mon(level=25, hp=80, max_hp=80, attack=55, special=65, defense=50)
    s = snap(party=(strong,), badges=1)
    assert readiness(s)['score'] > readiness(replace(s, party=(replace(strong, pp=(0, 0, 0, 0)),)))['score']
    assert readiness(s)['opponent'] == 'Misty'


def test_development_requires_safe_encounter_levels_and_deposits_protect_lead_hms():
    s = snap(party=(mon(level=30), mon(level=15), mon(level=3), mon(level=5, moves=(15,))))
    assert development_candidate(s, 14) == 1
    assert development_candidate(s, 25) is None
    assert reserve_to_deposit(s) == 2


def test_move_replacement_preserves_critical_attack_and_hm():
    p = mon(level=40, moves=(15, 75, 73, 22))
    slot = replacement_slot(p, 76)
    assert slot not in (0, 1)


def test_recovery_history_and_personality_survive_restore():
    policy = StrategicPolicy(4)
    s = snap()
    policy.last_action = ((s.map, s.x, s.y), 'left')
    policy._remember_failure(s, 'Door did not open')
    restored = StrategicPolicy(99)
    restored.load_state_dict(policy.state_dict())
    assert restored.history[-1]['message'] == 'Door did not open'
    assert restored.personality == policy.personality
    assert restored.failures
