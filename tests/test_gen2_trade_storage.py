"""A trade that leaves the PC sealed, or older saves behind its barrier, never wedges a Gen II run."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope='module')
def gold():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'gold')


def member(species, level, *, box=None, position=0):
    return SimpleNamespace(species=species, level=level, egg=False, box=box, position=position, moves=(33, 0, 0, 0))


def sealed_snapshot(gold, *, box_counts=(20,) * 14):
    # The live team after a trade sent its Waterfall partner away for a Slugma: nobody left can learn
    # Waterfall, the team is full and every box is full.
    party = tuple(member(species, level, position=slot) for slot, (species, level) in
                  enumerate([(154, 100), (169, 66), (73, 41), (18, 51), (218, 5), (143, 50)]))
    stored = (member(120, 40, box=3, position=19),)
    return SimpleNamespace(party=party, stored=stored, box_counts=box_counts, active_box=11,
                           can_catch=box_counts[11] < 20, map=gold.map_ids['CHERRYGROVE_POKECENTER_1F'], x=9, y=2)


def test_a_sealed_pc_does_not_send_the_run_to_deposit_a_field_move_partner(gold):
    """Regression: with no Waterfall partner left after a trade, a full team, 14 full boxes and nothing
    spare to release, the run stood at the Cherrygrove PC failing to deposit until the watchdog gave up."""
    from pokesim.gen2.policy import Policy
    policy = Policy(gold, seed=1, starter='chikorita')
    policy.release_target = lambda snapshot: None
    snapshot = sealed_snapshot(gold)
    assert not any(127 in gold.species[mon.species]['machines'] for mon in snapshot.party)
    assert policy.no_room(snapshot)
    assert policy.partner_goal(snapshot, 127) is None


def test_a_pc_with_room_still_fetches_the_field_move_partner(gold):
    from pokesim.gen2.policy import Policy
    policy = Policy(gold, seed=1, starter='chikorita')
    policy.release_target = lambda snapshot: None
    goal = policy.partner_goal(sealed_snapshot(gold, box_counts=(20,) * 13 + (19,)), 127)
    assert goal.key == 'storage'


def unstick_emulator(saves, barrier='trade-2'):
    from pokesim.gen2.emulator import Emulator
    loads, stops = [], []

    def load(path):
        if emu._behind_barrier(saves[path]):
            raise ValueError('Checkpoint predates a completed trade or custom reward')
        loads.append(path)

    emu = SimpleNamespace(
        unstick_streak=0, reloads=0, last_reload=0, frame=500000, snapshot=None, history={},
        store=SimpleNamespace(autosaves=lambda: list(saves), checkpoint_metadata=lambda path: saves[path],
                              get=lambda key: barrier if key == 'trade_barrier' else None),
        policy=SimpleNamespace(recoveries=0, menu=None, on_restore=lambda: None, collection={}, goal=None, decisions=0),
        audio=SimpleNamespace(clear=lambda: None), statistics=SimpleNamespace(previous=None), options_applied=True,
        _tick=lambda n: None, _reset_watch=lambda: None, _boot=lambda: SimpleNamespace(),
        pb=SimpleNamespace(stop=lambda save: stops.append(save)), _event=lambda event, snapshot: None,
        _load_state_file=load)
    emu._behind_barrier = lambda metadata: Emulator._behind_barrier(emu, metadata)
    return emu, loads, stops


def test_unstick_skips_saves_from_before_a_completed_trade():
    """Regression: the watchdog picked an autosave from before the trade, the load was refused, and
    every other reload alternated between it and the trade checkpoint until all 12 were spent."""
    from pokesim.gen2.emulator import Emulator
    saves = {Path('auto-old'): {'frame': 300000, 'trade_id': 'trade-1', 'settled': True},
             Path('auto-before'): {'frame': 440000, 'trade_id': 'trade-1', 'settled': True},
             Path('auto-link'): {'frame': 442000, 'trade_id': 'trade-2', 'settled': True},
             Path('auto-after'): {'frame': 499000, 'trade_id': 'trade-2', 'settled': True}}
    emu, loads, stops = unstick_emulator(saves)
    for _ in range(3):
        Emulator._unstick(emu, 495000, 'stuck')
    assert loads == [Path('auto-link')] * 3
    assert emu.reloads == 3 and not stops


def test_unstick_does_not_power_cycle_past_a_trade_when_every_save_predates_it():
    from pokesim.gen2.emulator import Emulator
    saves = {Path('auto-old'): {'frame': 300000, 'trade_id': 'trade-1', 'settled': True}}
    emu, loads, stops = unstick_emulator(saves)
    Emulator._unstick(emu, 495000, 'stuck')
    assert not loads and not stops and emu.reloads == 0
