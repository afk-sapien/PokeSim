"""League wins past the cartridge's 200 Hall of Fame entries still count."""
from dataclasses import dataclass
from types import SimpleNamespace

from pokesim.gen2.emulator import HOF_MASTER_COUNT, count_league

DATA = SimpleNamespace(map_ids={'LANCES_ROOM': 1, 'HALL_OF_FAME': 2, 'ROUTE': 3})


@dataclass(frozen=True)
class Snap:
    map: int
    hall_of_fame_count: int
    valid: bool = True
    started: bool = True


def visit(history, *maps, count=HOF_MASTER_COUNT):
    return [count_league(history, DATA, Snap(map, count)).hall_of_fame_count for map in maps]


def test_a_win_at_the_cap_counts_once():
    history = {'league': HOF_MASTER_COUNT}
    assert visit(history, 3, 1, 1, 2, 2, 3) == [200, 200, 200, 201, 201, 201]
    assert visit(history, 1, 2) == [201, 202]
    assert history['capped_wins'] == 2


def test_wins_below_the_cap_are_the_cartridge_s_own():
    history = {'league': 10}
    assert visit(history, 1, 2, count=10) == [10, 10]
    assert 'capped_wins' not in history
    # The 200th win itself is counted by the cartridge, so it adds nothing extra.
    assert visit(history, 1, 2, count=199) == [199, 199]
    assert 'capped_wins' not in history


def test_a_hall_of_fame_without_lance_is_not_a_win():
    history = {}
    assert visit(history, 2, 3, 2) == [200, 200, 200]
    assert 'capped_wins' not in history


def test_other_reads_only_add_recorded_wins():
    history = {'capped_wins': 2, 'league_attempt': True}
    assert count_league(history, DATA, Snap(2, HOF_MASTER_COUNT), observe=False).hall_of_fame_count == 202
    assert history == {'capped_wins': 2, 'league_attempt': True}


def test_invalid_snapshots_change_nothing():
    history = {'league_attempt': True}
    snap = Snap(2, HOF_MASTER_COUNT, valid=False)
    assert count_league(history, DATA, snap) is snap
    assert history == {'league_attempt': True}


def test_a_league_win_is_progress_for_a_finished_run():
    from pokesim.gen2.emulator import Emulator
    from pokesim.stalls import StallWatch
    emu = Emulator.__new__(Emulator)
    emu.frame, emu.history = 1000, {'maps': [1, 2, 3], 'league': 200}
    snapshot = SimpleNamespace(badges=0xFFFF, event_flags=b'\xff', owned=set(range(1, 252)), party=())
    emu.best_progress = (16, 8, 251, 3, 0, 200)
    emu.stall = StallWatch()
    emu.stall.progress(0, 0.0)
    emu._note_progress(snapshot, 10.0)
    assert emu.stall.frame == 0
    emu.history['league'] = 201
    emu._note_progress(snapshot, 20.0)
    assert emu.stall.frame == 1000 and emu.best_progress[-1] == 201
