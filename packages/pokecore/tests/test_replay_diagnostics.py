from copy import deepcopy

import pytest

from pokecore.emulator import Emulator, ReplayDivergence, demo_rom

pytest.importorskip('pyboy_rs')


def test_first_failed_checkpoint_and_memory_differences():
    with Emulator(demo_rom()) as source, Emulator(demo_rom()) as target:
        for emulator in (source, target):
            def hook(_, emulator=emulator):
                emulator.memory[0xc123] = 19 if emulator is source else 20
            emulator.hook_register(0, 0x100, hook, None)
        source.start_recording(100, diagnostic_interval=10, diagnostic_ranges=[(0xc120, 0xc130)])
        source.tick(90)
        recording = source.stop_recording()
        with pytest.raises(ReplayDivergence) as caught:
            target.replay(recording)
        report = caught.value.details
        assert 0 < report['first_failed_offset'] <= 90
        assert report['resolution_frames'] == 10
        assert target.frame_count == report['first_failed_offset']
        assert {'address': 0xc123, 'expected': 19, 'actual': 20} in report['memory_differences']
        assert report['nearby_inputs']


def test_diagnostic_intervals_and_nonmultiple_final_replay():
    with Emulator(demo_rom()) as source, Emulator(demo_rom()) as target:
        source.start_recording(20, diagnostic_interval=4)
        source.tick(11)
        recording = source.stop_recording()
        assert [x['offset'] for x in recording['backend']['checkpoints']] == [4, 8, 11]
        assert target.replay(recording)['verified']
        assert target.checkpoint() == source.checkpoint()


def test_limits_and_invalid_ranges_before_recording():
    with Emulator(demo_rom()) as emulator:
        for kwargs in ({'diagnostic_interval': -1}, {'diagnostic_interval': 1},
                       {'diagnostic_interval': 4, 'diagnostic_ranges': [(0xff00, 0xff10)]},
                       {'diagnostic_interval': 4, 'diagnostic_ranges': [(0xc000, 0xc010), (0xc001, 0xc020)]}):
            with pytest.raises(ValueError):
                emulator.start_recording(**kwargs)
        emulator.start_recording(10, diagnostic_interval=3)
        emulator.tick(4)
        recording = emulator.stop_recording()
        invalid = deepcopy(recording)
        invalid['backend']['checkpoints'][0]['offset'] = 999
        before = emulator.checkpoint()
        with pytest.raises(ValueError):
            emulator.replay(invalid)
        assert emulator.checkpoint() == before


def test_final_only_recordings_remain_supported():
    with Emulator(demo_rom()) as emulator:
        emulator.start_recording(3)
        emulator.tick(2)
        recording = emulator.stop_recording()
        assert recording['backend']['checkpoints'] == []
        assert emulator.replay(recording)['verified']
