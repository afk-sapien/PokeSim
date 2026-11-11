"""The same checkpoint and seed play the same game, so a recorded trace replays.

Two headless runs of 20,000 frames from one checkpoint must give the same trace head, and every
segment they write must verify against the cartridge. One case reloads part way and one receives
a trade demand, the two things outside the policy that change where a run goes.
docs/design/replayable-bugs.md section 4.7.
"""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('pyboy_rs')
from pokecore import trace as core  # noqa: E402

RED = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb'))
CRYSTAL = Path(os.environ.get('GEN2_CARTRIDGE_DIR', 'roms')) / 'crystal.gbc'
FRAMES = 20000
EVENT_FRAME = 8000


def cartridge(generation):
    if generation == 1:
        if not RED.exists():
            pytest.skip('Set ROM_PATH to a Red cartridge')
        return RED
    if not CRYSTAL.exists() or not os.environ.get('GEN2_DATA_DIR'):
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR for a Crystal run')
    return CRYSTAL


def headless(generation, rom, checkpoint=None, trace=None):
    from pokesim.runtime.headless import HeadlessRun
    data_root = os.environ['GEN2_DATA_DIR'] if generation == 2 else None
    run = HeadlessRun(rom, checkpoint, seed=7, trace=trace, data_root=data_root)
    return run, run.read


def demand(generation, run):
    """A coordinator's collection request, delivered as the participant receives it."""
    if generation == 1:
        from pokesim.runtime.participant import Participant
        emu = SimpleNamespace(policy=run.policy, play_clock=SimpleNamespace(frames=run.frame), tracer=run.tracer)
        Participant.collection_demand(SimpleNamespace(emu=emu, store=None), {'requests': {'25': 2}})
    else:
        from pokesim.gen2.trading import Participant
        emu = SimpleNamespace(policy=run.policy, tracer=run.tracer)
        Participant.collection_demand(SimpleNamespace(emu=emu, store=None),
                                      {'requests': {'25': 2}, 'supply': [], 'peers': 1})


@pytest.fixture(scope='module', params=[1, 2], ids=['gen1', 'gen2'])
def start(request, tmp_path_factory):
    """A checkpoint a little way past power-on, written as a headless run saves one."""
    generation = request.param
    rom = cartridge(generation)
    run, read = headless(generation, rom)
    try:
        while run.frame < 2000:
            run.step(read())
        path = tmp_path_factory.mktemp(f'gen{generation}') / 'start.state'
        run.save(path)
    finally:
        run.stop()
    return generation, rom, path


def play(start, folder, event):
    generation, rom, checkpoint = start
    run, read = headless(generation, rom, checkpoint, trace=folder)
    try:
        assert run.tracer.recording
        done = False
        while run.frame < FRAMES:
            if not done and run.frame >= EVENT_FRAME:
                done = True
                if event == 'reload':
                    run.reload(checkpoint)
                elif event == 'demand':
                    demand(generation, run)
            run.step(read())
        return run.tracer.recorder.head
    finally:
        run.stop()


@pytest.mark.parametrize('event', ['none', 'reload', 'demand'])
def test_two_runs_of_one_checkpoint_and_seed_record_the_same_trace(start, tmp_path, event):
    heads = [play(start, tmp_path / name, event) for name in ('first', 'second')]
    assert heads[0] and heads[0] == heads[1]
    rom = start[1]
    segments = sorted(tmp_path.glob('*/*/segment.jsonl.gz'))
    assert len(segments) == 2
    for path in segments:
        assert core.main(['verify', str(path), '--rom', str(rom)]) == 0
        records = core.Trace.read(path).records
        assert not [record for record in records if record.get('unrecorded')]
        if event == 'reload':
            assert any(record['kind'] == 'load' and record.get('reason') == 'reload' for record in records)
        if event == 'demand':
            assert any(record['kind'] == 'input' and record.get('source') == 'trade_demand' for record in records)
