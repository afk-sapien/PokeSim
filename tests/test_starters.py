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
