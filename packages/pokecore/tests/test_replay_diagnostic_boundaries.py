import pytest

from pokecore.emulator import Emulator, ReplayDivergence, demo_rom

pytest.importorskip('pyboy_rs')


@pytest.mark.parametrize('ranges,differences', [
    ([], 0), ([(0xc400, 0xc440), (0xc440, 0xc480)], 128), ([(0xc800, 0xc810)], 0),
])
def test_hash_divergence_with_empty_or_partial_windows_and_bounded_byte_report(ranges, differences):
    with Emulator(demo_rom()) as source, Emulator(demo_rom()) as target:
        for value, emulator in enumerate((source, target), 1):
            def hook(_, value=value, emulator=emulator):
                emulator.memory[0xc400:0xc480] = [value] * 128
            emulator.hook_register(0, 0x100, hook, None)
        source.start_recording(90, diagnostic_interval=7, diagnostic_ranges=ranges)
        source.tick(90)
        recording = source.stop_recording()
        with pytest.raises(ReplayDivergence) as caught:
            target.replay(recording)
        details = caught.value.details
        assert details['expected_state_sha256'] != details['actual_state_sha256']
        assert details['memory_difference_count'] == differences
        assert len(details['memory_differences']) == min(64, differences)
        assert details['memory_differences_truncated'] == (differences > 64)
        assert details['last_verified_offset'] == 63
        assert details['first_failed_offset'] == 70
        assert target.frame_count == 70
        assert [item['offset'] for item in details['nearby_inputs']] == list(range(67, 74))
        details['nearby_inputs'][0]['events'].append(1)
        assert recording['backend']['frames'][66]['events'] == []
