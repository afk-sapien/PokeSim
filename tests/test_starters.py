import json

import pytest

from pokesim.policies.progression import STARTERS, story_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import flags


@pytest.mark.parametrize('starter,x', [('charmander', 6), ('squirtle', 7), ('bulbasaur', 8)])
def test_each_starter_targets_its_own_pokeball(starter, x):
    s = snap(party=(), event_flags=flags('EVENT_FOLLOWED_OAK_INTO_LAB'))
    goal = story_goal(s, starter)
    assert goal.title == 'Choose ' + starter.title()
    assert (MAPS['OAKS_LAB'], x, 4) in goal.targets
    assert goal.facing_at((MAPS['OAKS_LAB'], x, 4)) == 'up'


def test_random_starters_are_seeded_varied_and_persisted_over_configuration_changes():
    assert {StrategicPolicy(seed, 'random').starter for seed in range(30)} == set(STARTERS)
    first = StrategicPolicy(5, 'random')
    assert first.starter == StrategicPolicy(5, 'random').starter
    saved = json.loads(json.dumps(first.state_dict()))
    restored = StrategicPolicy(999, 'bulbasaur')
    restored.load_state_dict(saved)
    restored.on_restore()
    assert restored.starter == first.starter


def test_legacy_checkpoints_retain_the_old_starter_and_fixed_choice_survives_reset():
    policy = StrategicPolicy(5, 'charmander')
    policy.reset()
    assert policy.starter == 'charmander'
    policy.load_state_dict({'version': 1})
    assert policy.starter == 'bulbasaur'


def test_invalid_starter_setting_fails_before_play():
    with pytest.raises(ValueError, match='starter'):
        StrategicPolicy(1, 'pikachu')


def test_fossil_and_eevee_choices_are_varied_seeded_and_survive_restore():
    policies = [StrategicPolicy(seed) for seed in range(30)]
    assert {p.fossil for p in policies} == {'DOME_FOSSIL', 'HELIX_FOSSIL'}
    assert {p.collection.eevee_choice for p in policies} == {134, 135, 136}
    for p in policies:
        same = StrategicPolicy(p.seed)
        assert (same.fossil, same.collection.eevee_choice) == (p.fossil, p.collection.eevee_choice)
        restored = StrategicPolicy(999)
        restored.load_state_dict(json.loads(json.dumps(p.state_dict())))
        assert (restored.fossil, restored.collection.eevee_choice) == (p.fossil, p.collection.eevee_choice)


def test_both_fossil_choices_target_the_correct_object():
    from pokesim.policies.progression import object_goal
    from test_campaign import ready
    from dataclasses import replace
    state = replace(ready(badges=1), map=MAPS['MT_MOON_B2F'],
                    event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BEAT_MT_MOON_EXIT_SUPER_NERD'))
    for fossil in ('DOME_FOSSIL', 'HELIX_FOSSIL'):
        goal = story_goal(state, fossil=fossil)
        expected = object_goal('fossil', '', '', 'MT_MOON_B2F', fossil)
        assert goal.key == 'fossil'
        assert goal.targets == expected.targets
