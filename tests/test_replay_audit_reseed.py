"""Goal reseeding in the replay audit: the same goal on the same save meets the same random numbers."""
import os
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

from tools.replay_audit import DIVIDER, GEN1_RANDOM, VBLANK, GoalSeeds, idle, random_bytes

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'scenarios'
RED_ROM = Path(os.environ.get('ROM_PATH', ROOT / 'roms' / 'pokered.gb'))
CARTRIDGES = Path(os.environ.get('GEN2_CARTRIDGE_DIR', ROOT / 'roms'))
GEN2_DATA = os.environ.get('GEN2_DATA_DIR')


class FakeEmulator:
    def __init__(self, seed):
        self.memory = bytearray(random.Random(seed).randbytes(65536))
        self.hooks = {}
        self.frame_count = seed * 1000

    def hook_register(self, bank, address, callback, context):
        assert (bank, address) not in self.hooks
        self.hooks[bank, address] = lambda: callback(context)

    def vblank(self):
        self.frame_count += 1
        self.hooks[0, VBLANK]()
        return bytes(self.memory[a] for a in GEN1_RANDOM)


def fake_run(seed):
    return SimpleNamespace(generation=1, pb=FakeEmulator(seed), policy=SimpleNamespace(rng=random.Random(seed)))


def test_a_goal_start_writes_the_same_seeds_whatever_came_before():
    first, second = fake_run(1), fake_run(2)
    for run in (first, second):
        run.policy.rng.random()
        GoalSeeds('auto-v1-1.state').start(run, 'collection_hunt')
    assert first.pb.memory[DIVIDER] == second.pb.memory[DIVIDER] == 0
    assert first.policy.rng.random() == second.policy.rng.random()
    frames = [first.pb.vblank() for _ in range(20)]
    assert frames == [second.pb.vblank() for _ in range(20)]
    assert len(set(frames)) > 15


def test_the_seed_follows_the_save_the_goal_and_its_occurrence():
    seeds = GoalSeeds('auto-v1-1.state')
    assert seeds.seed('collection_hunt', 0) != seeds.seed('collection_hunt', 1)
    assert seeds.seed('collection_hunt', 0) != seeds.seed('party_box', 0)
    assert seeds.seed('collection_hunt', 0) != GoalSeeds('auto-v1-2.state').seed('collection_hunt', 0)
    run, again = fake_run(3), fake_run(4)
    seeds.start(run, 'collection_hunt')
    seeds.start(run, 'collection_hunt')
    assert seeds.starts['collection_hunt'] == 2 and len(run.pb.hooks) == 1
    other = GoalSeeds('auto-v1-1.state')
    other.starts['collection_hunt'] = 1
    other.start(again, 'collection_hunt')
    assert run.pb.vblank() == again.pb.vblank()


def rolls(open_run, lead, reseed):
    """The game's random bytes each frame after a goal start, ``lead`` frames after loading."""
    run = open_run()
    try:
        idle(run, lead)
        if reseed:
            GoalSeeds('start.state').start(run, 'collection_hunt')
        add, sub = random_bytes(run)
        seen = []
        for _ in range(240):
            idle(run, 1)
            seen.append((run.pb.memory[add], run.pb.memory[sub]))
        return seen
    finally:
        run.stop()


def differences(first, second):
    return [i for i, (a, b) in enumerate(zip(first, second)) if a != b]


def assert_reseeding_aligns(open_run):
    """The rolls match frame for frame. A frame ends a few cycles apart from run to run, so the divider
    the game adds can read one tick apart on some frames. Those read one higher or lower, which changes
    an encounter only when the roll sits right on its threshold, and the next seed undoes it."""
    base = rolls(open_run, 0, True)
    for lead in (1, 37, 600):
        other = rolls(open_run, lead, True)
        apart = differences(base, other)
        assert len(apart) <= len(base) // 8, (lead, apart)
        for i in apart:
            assert all((a - b) % 256 in (1, 255, 0) for a, b in zip(base[i], other[i])), (lead, i)
    assert len(differences(rolls(open_run, 0, False), rolls(open_run, 37, False))) > len(base) // 2


@pytest.mark.skipif(not RED_ROM.exists(), reason='no ROM')
def test_red_rolls_match_after_a_goal_start_whatever_the_timing_before():
    state = SCENARIOS / 'red-cerulean-cave-hunt-20261008' / 'start.state'
    if not state.exists():
        pytest.skip('no private Red scenario')
    from pokesim.headless import HeadlessRun
    assert_reseeding_aligns(lambda: HeadlessRun(RED_ROM, state))


@pytest.mark.parametrize('game, scenario', [('crystal', 'crystal-tower-restore-20261022'),
                                            ('silver', 'silver-np-gate-corner-20261020')])
def test_gen2_rolls_match_after_a_goal_start_whatever_the_timing_before(game, scenario):
    rom, state = CARTRIDGES / f'{game}.gbc', SCENARIOS / scenario / 'start.state'
    if not GEN2_DATA or not rom.exists() or not state.exists():
        pytest.skip('needs GEN2_DATA_DIR, the cartridge and the private scenario')
    from pokesim.gen2.headless import HeadlessRun
    assert_reseeding_aligns(lambda: HeadlessRun(rom, state, data_root=Path(GEN2_DATA)))
