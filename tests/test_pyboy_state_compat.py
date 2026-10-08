"""A state written by the Rust backend loads into PyBoy 2.7.0, which is what a 0.4.x rollback runs.

Skipped when PyBoy is absent, because 0.5.0 does not depend on it. The CI tests job runs it once on
Python 3.12 with `uv run --with pyboy==2.7.0`. Locally, install pyboy==2.7.0 in a scratch environment.
"""
import io
from importlib.metadata import version

import pytest

pyboy_module = pytest.importorskip('pyboy', reason='PyBoy 2.7.0 is only needed for the rollback check')

from pokesim_core.emulator import Emulator, demo_rom  # noqa: E402

pytestmark = pytest.mark.skipif(
    version('pyboy') != '2.7.0', reason='the rollback target is exactly PyBoy 2.7.0')


def snapshot(emulator):
    return bytes(emulator.memory[0xC000:0xE000]) + bytes(emulator.memory[0xFF80:0xFFFF])


def test_rust_written_state_loads_into_pyboy_270_and_keeps_running():
    rom = demo_rom()
    with Emulator(io.BytesIO(rom.read_bytes()), sound_emulated=False) as rust:
        rust.tick(120)
        state = io.BytesIO()
        rust.save_state(state)
        expected = snapshot(rust)
    legacy = pyboy_module.PyBoy(str(rom), window='null', sound_emulated=False)
    try:
        state.seek(0)
        legacy.load_state(state)
        loaded = bytes(legacy.memory[0xC000:0xE000]) + bytes(legacy.memory[0xFF80:0xFFFF])
        assert loaded == expected
        assert legacy.tick(30, False)
        assert legacy.frame_count > 0
    finally:
        legacy.stop(save=False)
