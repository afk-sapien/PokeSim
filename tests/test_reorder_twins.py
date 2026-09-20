"""A reorder is finished when the chosen individual leads, not when its species does."""
from pokesim.policies.battle import Decision
from pokesim.policies.strategic import StrategicPolicy, individual
from pokesim.screen import Screen
from test_events import snap
from test_strategy import menu, mon

HAUNTER = 0x93


def party_menu():
    return menu({1: ' HAUNTER', 3: ' HAUNTER', 5: ' VENUSAUR'}, (0, 1), top=(0, 1))


def test_promoting_the_stronger_twin_is_not_mistaken_for_done():
    # Two Haunters at a gym door: the weak one led, the strong one was wanted in front, and
    # comparing species said the job was already finished. The run reopened the menu forever.
    weak, strong = mon(species=HAUNTER, level=26, max_hp=63, hp=63), mon(species=HAUNTER, level=41, max_hp=106, hp=106)
    state = snap(party=(weak, strong, mon(level=50)))
    policy = StrategicPolicy(7)
    policy.order_species, policy.order_signature, policy.order_stage = HAUNTER, individual(strong), 'source'
    policy.intent = Decision('reorder', 1, reason='Lead with the best available matchup')
    memory = party_menu()
    policy._dispatch(state, Screen(memory), 'party', memory)
    assert policy.intent is not None, 'the weaker twin in front does not complete the reorder'
    swapped = snap(party=(strong, weak, mon(level=50)))
    policy._dispatch(swapped, Screen(memory), 'party', memory)
    assert policy.intent is None


def test_individuals_of_one_species_are_distinguished():
    assert individual(mon(level=26)) != individual(mon(level=41))
    assert individual(mon(level=30, nick='A')) != individual(mon(level=30, nick='B'))
