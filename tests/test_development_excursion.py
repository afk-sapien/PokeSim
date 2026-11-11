"""A development excursion ends on its partner's own progress, not on a fixed window, and starts only for
a partner the map's wild battles can raise a level in ten battles or fewer."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim.planning.cost import WildOdds
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import DEVELOPMENT_STALL, StrategicPolicy
from pokesim.pcvalue import TRAINING_BATTLES
from pokesim.policies.team import battles_to_level, development_candidate
from pokesim.strategy_data import MAPS
from test_collection import state
from test_strategy import mon

LEAD = mon(hp=100, max_hp=100, level=40, nick='LEAD', experience=60000)
PARTNER = mon(hp=60, max_hp=60, level=20, nick='PARTNER', experience=8000)


def developing(frame=10000):
    """A policy whose excursion trains ``PARTNER``, already moved to the lead, from ``frame``."""
    policy = StrategicPolicy(3)
    route = MAPS['ROUTE_1']
    goal = Goal('train_partner', 'Train', 'Train', ((route, 10, 10),))
    policy.excursion = (goal, None, 'development')
    policy.development_index = 0
    policy.development = {'partner': (PARTNER.species, PARTNER.nick, PARTNER.dvs), 'level': PARTNER.level,
                          'experience': PARTNER.experience, 'since': frame}
    return policy, state(map=route, x=10, y=12, party=(PARTNER, LEAD), frame=frame)


def test_an_excursion_that_gains_experience_goes_on_past_the_stall_window():
    policy, s = developing()
    for step in range(1, 5):
        gained = replace(PARTNER, experience=PARTNER.experience + 50 * step)
        assert not policy._development_done(replace(s, party=(gained, LEAD), frame=s.frame + step * 2000))
    assert policy.developing


def test_an_excursion_ends_when_its_partner_gains_a_level():
    policy, s = developing()
    grown = replace(PARTNER, level=PARTNER.level + 1, experience=PARTNER.experience + 400)
    assert policy._development_done(replace(s, party=(grown, LEAD), frame=s.frame + 600))


def test_an_excursion_without_experience_still_ends():
    policy, s = developing()
    assert not policy._development_done(replace(s, frame=s.frame + DEVELOPMENT_STALL - 1))
    later = replace(s, frame=s.frame + DEVELOPMENT_STALL)
    assert policy._development_done(later)
    assert policy._purposeful_detour(later, bytearray(65536), Goal('story', 'Story', 'Story')) is None
    assert policy.excursion is None and not policy.developing


def test_an_excursion_ends_when_its_partner_leaves_the_party():
    policy, s = developing()
    assert policy._development_done(replace(s, party=(LEAD,), frame=s.frame + 10))


def grass(level, base_exp=70, map_id=MAPS['ROUTE_1']):
    """Cartridge odds whose grass on ``map_id`` meets one species at ``level`` in every slot."""
    return WildOdds(SimpleNamespace(species={7: {'base_exp': base_exp}},
                                    encounters={f'grass:{map_id}': {'rate': 25, 'slots': [[level, 7]] * 10}}))


def test_a_wild_battle_pays_the_grass_tables_top_level_and_average_base_experience():
    odds = WildOdds(SimpleNamespace(species={1: {'base_exp': 70}, 2: {'base_exp': 140}},
                                    encounters={'grass:22': {'rate': 15, 'slots': [[13, 1]] * 9 + [[15, 2]]}}))
    # The last slot meets 3 battles in 256.
    assert odds.battle_experience(22) == pytest.approx((253 * 70 + 3 * 140) / 256 * 15 / 7)
    assert odds.battle_experience(23) is None
    assert grass(15).battle_experience(MAPS['ROUTE_1']) == 150


# Route 11's grass tops out at level 15. A level 41 partner needs about 34 of its battles for a level.
STRONG = mon(hp=200, max_hp=200, level=55, nick='STRONG', experience=200000)
HIGH = mon(hp=120, max_hp=120, level=41, nick='HIGH', experience=61450)
LOW = mon(hp=50, max_hp=50, level=14, nick='LOW', experience=1612)


def test_a_partner_that_needs_more_than_ten_battles_for_a_level_is_not_trained_here():
    gain = grass(15).battle_experience(MAPS['ROUTE_1'])
    assert battles_to_level(HIGH, gain) > TRAINING_BATTLES >= battles_to_level(LOW, gain)
    assert development_candidate(state(party=(STRONG, HIGH)), 15, gain) is None
    assert development_candidate(state(party=(STRONG, HIGH, LOW)), 15, gain) == 2
    # Without the cartridge's tables the rule is not applied.
    assert development_candidate(state(party=(STRONG, HIGH)), 15) == 1


def starts_an_excursion(party, odds):
    policy = StrategicPolicy(3)
    policy.collection.wild = odds
    policy.rng.random = lambda: 0.0
    s = state(map=MAPS['ROUTE_1'], x=12, y=8, party=party, frame=10000)
    policy._purposeful_detour(s, bytearray(65536), Goal('story', 'Story', 'Story'))
    return policy.development and policy.development['partner'][1]


def test_a_route_whose_battles_cannot_raise_the_partner_starts_no_excursion():
    assert starts_an_excursion((STRONG, HIGH), grass(15)) is None
    assert starts_an_excursion((STRONG, HIGH), grass(40, base_exp=100)) == 'HIGH'
    assert starts_an_excursion((STRONG, HIGH, LOW), grass(15)) == 'LOW'
