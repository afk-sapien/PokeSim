"""Cartridge clock wiring on Core: ROM-free fakes and ROM-backed round trips."""
import io
import os
import struct
import time
from pathlib import Path

import pytest

from pokesim.gen2 import core
from pokesim.gen2.core import CoreCapabilityError, export_clock, lock_clock, stop_with_clock


class FakeClock:
    def __init__(self):
        self.calls = []
        self.clock_locked = False

    def clock_now(self):
        return 123.0

    def lock_clock(self, at, follow_frames=False):
        self.calls.append(('lock', at, follow_frames))
        self.clock_locked = True

    def unlock_clock(self):
        self.calls.append(('unlock',))
        self.clock_locked = False

    def set_rtc_timezero(self, value):
        self.calls.append(('zero', value))

    def export_rtc(self):
        return bytes(10)

    def stop(self, ram_file=None, rtc_file=None):
        self.calls.append(('stop', ram_file, rtc_file))
        rtc_file.write(bytes(10))


def test_lock_defaults_to_current_reading_without_rebase():
    emulator = FakeClock()
    lock_clock(emulator)
    assert emulator.calls == [('lock', 123.0, False)]


def test_lock_with_rebase_moves_zero_point_to_the_instant():
    emulator = FakeClock()
    lock_clock(emulator, at=core.FIXED_CLOCK_EPOCH, follow_frames=True, rebase=True)
    assert emulator.calls == [('lock', core.FIXED_CLOCK_EPOCH, True), ('zero', core.FIXED_CLOCK_EPOCH)]


def test_unlock_only_when_locked():
    emulator = FakeClock()
    lock_clock(emulator, False)
    assert emulator.calls == []
    lock_clock(emulator)
    lock_clock(emulator, False)
    assert emulator.calls[-1] == ('unlock',)


def test_stop_with_clock_writes_both_streams():
    emulator, save, clock = FakeClock(), io.BytesIO(), io.BytesIO()
    stop_with_clock(emulator, save, clock)
    assert clock.getvalue() == bytes(10)
    assert export_clock(emulator) == bytes(10)


@pytest.mark.parametrize('operation', [
    lambda e: lock_clock(e),
    lambda e: stop_with_clock(e, io.BytesIO(), io.BytesIO()),
    lambda e: export_clock(e),
])
def test_core_without_clock_methods_is_a_capability_error(operation):
    with pytest.raises(CoreCapabilityError):
        operation(object())


@pytest.mark.parametrize('error', [
    NotImplementedError('rtc_file is not supported'),
    RuntimeError('this build requires real-time clock control'),
])
def test_backend_refusals_become_capability_errors(error):
    class Refusing(FakeClock):
        def export_rtc(self):
            raise error
    with pytest.raises(CoreCapabilityError):
        export_clock(Refusing())


def test_unrelated_runtime_errors_pass_through():
    class Broken(FakeClock):
        def export_rtc(self):
            raise RuntimeError('disk on fire')
    with pytest.raises(RuntimeError, match='disk on fire'):
        export_clock(Broken())


def test_capability_error_is_the_backends_so_one_handler_reports_it():
    from pokesim_core.errors import CoreCapabilityError as BackendError
    assert issubclass(CoreCapabilityError, BackendError)


def test_boot_with_a_clock_on_an_old_core_is_a_clear_capability_error(monkeypatch):
    def old_core(rom, **options):
        raise TypeError("__init__() got an unexpected keyword argument 'rtc_file'")
    monkeypatch.setattr(core, 'CoreEmulator', old_core)
    with pytest.raises(CoreCapabilityError, match='cartridge clock'):
        core.boot(io.BytesIO(b''), rtc=bytes(10))


GAMES = ['gold', 'silver', 'crystal']


@pytest.fixture(params=GAMES)
def cartridge(request):
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    return (Path(directory) / (request.param + '.gbc')).read_bytes()


def test_real_clock_file_round_trips_through_a_fresh_emulator(cartridge):
    clock = struct.pack('<d', 1_700_000_000.0) + bytes([0, 0])
    emulator = core.boot(io.BytesIO(cartridge), rtc=clock, sound=False)
    try:
        assert export_clock(emulator) == clock
    finally:
        emulator.stop(save=False)


def _elapsed(emulator):
    registers = emulator.rtc_registers()
    return ((registers['days'] * 24 + registers['hours']) * 60 + registers['minutes']) * 60 + registers['seconds']


def test_real_locked_rebased_clock_reads_zero_elapsed(cartridge):
    # Core 0.3.0 with pyboy-rs carrying rtc_export_follows_host exports a locked clock as its
    # host-following equivalent: the file that, read on the host clock now, shows what the locked
    # clock shows now. The fake locked base (FIXED_CLOCK_EPOCH here) is never written out, because
    # a real cartridge or an unlocked emulator would read it as a jump of hundreds of days. So a
    # rebased clock at zero elapsed exports a base of about now, and a fresh emulator still reads zero.
    emulator = core.boot(io.BytesIO(cartridge), sound=False)
    try:
        lock_clock(emulator, at=core.FIXED_CLOCK_EPOCH, rebase=True)
        assert emulator.clock_locked
        assert _elapsed(emulator) == 0
        exported = export_clock(emulator)
        assert abs(struct.unpack('<d', exported[:8])[0] - time.time()) <= 5
        assert emulator.clock_locked and _elapsed(emulator) == 0  # exporting changes nothing
        fresh = core.boot(io.BytesIO(cartridge), rtc=exported, sound=False)
        try:
            assert not fresh.clock_locked
            assert _elapsed(fresh) <= 5
        finally:
            fresh.stop(save=False)
        lock_clock(emulator, False)
        assert not emulator.clock_locked
    finally:
        emulator.stop(save=False)


def test_real_stop_with_clock_emits_ten_byte_file(cartridge):
    emulator = core.boot(io.BytesIO(cartridge), sound=False)
    save, clock = io.BytesIO(), io.BytesIO()
    stop_with_clock(emulator, save, clock)
    assert len(clock.getvalue()) == 10
    assert len(save.getvalue()) == 32768


def test_source_info_never_lets_git_read_the_terminal(tmp_path, monkeypatch):
    import subprocess
    from pokesim import build_info
    (tmp_path / '.git').mkdir()
    seen = []

    def fake(command, **options):
        seen.append(options)
        return 'a' * 40 if 'rev-parse' in command else ''
    monkeypatch.setattr(subprocess, 'check_output', fake)
    assert build_info.source_info(tmp_path)['revision'] == 'a' * 40
    assert len(seen) == 2 and all(options['stdin'] is subprocess.DEVNULL for options in seen)
