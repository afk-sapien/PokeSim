"""A cartridge that restarted to its opening, and a goal that keeps failing for want of a route.

A live Crystal run reset during a Battle Tower challenge. The main menu had read the save, so the
party and the Battle Tower 1F place looked like a started run, but no map was loaded. The policy
found no route out of the blank map, failed every few seconds for hours, and was never reloaded.
"""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


class Cartridge:
    """Zeroed RAM with chosen bytes, read through the same symbols as the real cartridge."""

    def __init__(self, data, **values):
        self.values = {tuple(data.symbols[name]): value for name, value in values.items()}

    def __getitem__(self, key):
        bank, window = key if isinstance(key, tuple) else (0, key)
        return [self.values.get((bank, address), 0) for address in range(window.start, window.stop)]


def memory(**values):
    return SimpleNamespace(byte=lambda name: values.get(name, 0))


def snapshot_at(data, constant):
    return SimpleNamespace(started=True, valid=True, in_battle=0, hall_of_fame_count=0, map=data.map_ids[constant],
                           x=7, y=7, party=(), stored=(), items=(), badges=0, owned=frozenset(), step_count=0,
                           breeding_compatible=False, event_flags=bytes(256))


def test_policy_continues_the_save_instead_of_walking_an_unloaded_map(data, monkeypatch):
    from pokesim.gen2 import contest, policy as module, ruins, tower
    from pokesim.gen2.policy import Policy
    monkeypatch.setattr(module, 'update_world', lambda *args: None)
    for part in (ruins, contest, tower):
        monkeypatch.setattr(part, 'control', lambda *args: None)
    policy = Policy(data, seed=1, starter='cyndaquil')
    policy.naming.step = lambda snapshot, mem: None
    snapshot = snapshot_at(data, 'BATTLE_TOWER_1F' if data.game == 'crystal' else 'OLIVINE_CITY')
    action = policy.step(snapshot, Cartridge(data))
    assert policy.mode == 'opening'
    assert action.button in {'start', 'a'}
    assert not policy.unloaded(snapshot, memory(wMapWidth=8))


def test_a_policy_recovery_does_not_make_the_same_tile_look_like_progress(data):
    """Each recovery starts a fresh navigator. The failure streak must still reach its limit."""
    from pokesim.gen2.emulator import Emulator
    from pokesim.gen2.policy import Policy
    policy = Policy(data, seed=1, starter='cyndaquil')
    snapshot = snapshot_at(data, 'ROUTE_29')
    emu = SimpleNamespace(policy=policy, history={'maps': [snapshot.map]}, explored=set(), progress_key=None,
                          progress_frame=0, stuck_frame=0, stuck_ts=0.0, frame=100, failure_streak=0)
    Emulator._watch_progress(emu, snapshot, 0.0)
    for frame in (200, 300, 400):
        policy.nav.visits[(snapshot.map, snapshot.x, snapshot.y)] = 1
        policy.fail('no route to a goal')
        emu.failure_streak += 1
        emu.frame = frame
        Emulator._watch_progress(emu, snapshot, 0.0)
    assert emu.failure_streak == 3
    assert emu.progress_frame == 100
