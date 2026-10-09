"""A reorder is keyed by the chosen individual, not by its species."""
from pokesim.policies.strategic import StrategicPolicy, individual
from shortcut_fakes import Recorder
from test_events import snap
from test_strategy import mon

HAUNTER = 0x93


def test_a_failed_reorder_of_one_twin_does_not_block_the_other():
    # Two Haunters at a gym door: comparing species once said the job was already finished and
    # the run reopened the menu forever. Each twin is now its own request.
    weak, strong = mon(species=HAUNTER, level=26, max_hp=63, hp=63), mon(species=HAUNTER, level=41, max_hp=106, hp=106)
    policy = StrategicPolicy(7)
    shortcuts = Recorder.on(policy)
    state = snap(party=(mon(level=50), strong, weak))
    assert policy._reorder(state, 1, 'Lead with the best available matchup')
    shortcuts.finish(False, frame=state.frame)
    assert policy._reorder(state, 1, 'Lead with the best available matchup') is None
    assert policy._reorder(state, 2, 'Lead with the best available matchup')
    assert shortcuts.last.first == 2


def test_a_finished_reorder_restarts_partner_development_from_the_lead():
    policy = StrategicPolicy(7)
    shortcuts = Recorder.on(policy)
    policy.development_index = 2
    policy._reorder(snap(party=(mon(), mon(level=9), mon(level=30))), 2, 'Train')
    shortcuts.finish(True)
    assert policy.development_index == 0


def test_individuals_of_one_species_are_distinguished():
    assert individual(mon(level=26)) != individual(mon(level=41))
    assert individual(mon(level=30, nick='A')) != individual(mon(level=30, nick='B'))
