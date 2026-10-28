from dataclasses import dataclass, field

from pokesim.planning.monitor import CONTINUE, Backoff, Monitor, ProgressEvent
from pokesim.planning.progress import events


def test_budget_is_a_multiple_of_expected_frames():
    monitor = Monitor(backoff=Backoff(100))
    monitor.start('hunt', expected_frames=1000)
    assert monitor.observe('hunt', 2999, now=0) == CONTINUE
    verdict = monitor.observe('hunt', 1, now=50)
    assert verdict.stand_down and verdict.until == 150
    assert monitor.standing_down('hunt', 149)
    assert not monitor.standing_down('hunt', 150)


def test_progress_clears_the_count():
    monitor = Monitor()
    monitor.start('train', budget=100)
    monitor.observe('train', 90)
    assert not monitor.observe('train', 50, [ProgressEvent('level', 1)]).stand_down
    assert monitor.spent('train') == 0
    assert not monitor.observe('train', 90).stand_down


def test_a_goal_without_a_budget_is_only_counted():
    monitor = Monitor()
    monitor.start('walk')
    assert monitor.observe('walk', 10 ** 9, now=0) == CONTINUE
    monitor.observe('rest', 10 ** 9)
    assert monitor.shares() == {'walk': 0.5, 'rest': 0.5}


def test_spent_frames_survive_a_restart():
    state = {}
    first = Monitor(state)
    first.start('hunt', budget=100)
    first.observe('hunt', 60)
    second = Monitor(state)
    second.start('hunt', budget=100)
    assert second.observe('hunt', 40, now=0).stand_down
    assert second.shares() == {'hunt': 1.0}


def test_backoff_doubles_for_stand_downs_in_a_row():
    monitor = Monitor(backoff=Backoff(60000, doublings=3))
    waits = [monitor.stand_down('rematch', 0) for _ in range(6)]
    assert waits == [60000, 120000, 240000, 480000, 480000, 480000]
    assert monitor.stand_down('rematch', 0, progressed=True) == 60000
    assert monitor.stand_down('rematch', 0) == 60000


def test_a_fixed_wait_matches_the_gen2_stand_down():
    state = {'stood_down': {'hunt:223': 900}}
    monitor = Monitor(state, backoff=Backoff(50000))
    assert monitor.standing_down('hunt:223', 50899)
    assert not monitor.standing_down('hunt:223', 50900)
    monitor.stand_down('hunt:223', 1000)
    monitor.stand_down('hunt:223', 2000)
    assert monitor.until('hunt:223') == 52000
    assert state['stood_down'] == {'hunt:223': 2000}
    monitor.clear('hunt:223')
    assert monitor.until('hunt:223') is None


@dataclass
class Mon:
    species: int
    level: int


@dataclass
class Snap:
    owned: frozenset = frozenset()
    items: tuple = ()
    party: tuple = ()
    box_counts: tuple = ()
    badges: int = 0
    hall_of_fame_count: int = 0
    event_flags: bytes = b'\0\0'
    valid: bool = True
    extra: dict = field(default_factory=dict)


def test_events_from_two_snapshots():
    before = Snap(party=(Mon(25, 10),), items=((4, 3),), box_counts=(3, 0))
    assert events(before, before) == []
    after = Snap(owned=frozenset({25}), party=(Mon(25, 12), Mon(16, 3)), items=((4, 2), (5, 1)),
                 box_counts=(3, 0), badges=1, hall_of_fame_count=1, event_flags=b'\1\0')
    kinds = {event.kind: event.detail for event in events(before, after)}
    assert kinds == {'dex': 1, 'catch': None, 'item': (5,), 'level': 2, 'badge': None, 'league': None, 'event': 1}
    assert events(None, after) == [] and events(before, Snap(valid=False)) == []
