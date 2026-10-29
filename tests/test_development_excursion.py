"""A development excursion ends on its partner's own progress, not on a fixed window."""
from dataclasses import replace

from pokesim.policies.progression import Goal
from pokesim.policies.strategic import DEVELOPMENT_STALL, StrategicPolicy
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
