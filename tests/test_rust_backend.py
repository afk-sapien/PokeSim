"""The Rust emulator backend, exercised with the redistributable demonstration cartridge.

These checks need no private ROM, so CI runs them on every platform that installs pyboy-rs.
"""
import io

from pokesim_core.emulator import Emulator, check_runtime, demo_rom
from pokesim_core.emulator_state import runtime_provenance


def boot():
    return Emulator(io.BytesIO(demo_rom().read_bytes()), sound_emulated=False)


def test_runtime_check_passes():
    check_runtime()


def test_backend_is_pyboy_rs_with_the_legacy_state_format():
    provenance = runtime_provenance()
    assert provenance['backend'] == 'pyboy-rs'
    assert provenance['state_format'] == 'pyboy-format-15'
    assert provenance['version'].startswith('0.1.')


def test_core_checkpoint_carries_the_legacy_tag_and_round_trips():
    """Core 0.2 tags Emulator.checkpoint() with pyboy_version so 0.4.x can still load Gen 1 saves."""
    with boot() as first:
        first.tick(30)
        checkpoint = first.checkpoint()
        assert checkpoint['pyboy_version'] == '2.7.0'
        assert checkpoint['emulator']['backend'] == 'pyboy-rs'
        first.tick(30)
        expected = bytes(first.screen.raw_buffer)
    with boot() as second:
        second.restore_checkpoint(checkpoint)
        second.tick(30)
        assert bytes(second.screen.raw_buffer) == expected


def test_demo_cartridge_reports_no_real_time_clock():
    with boot() as game:
        assert game.clock_control_available
        assert not game.has_rtc
