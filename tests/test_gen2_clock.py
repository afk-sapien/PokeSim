"""Cartridge clock wiring on Core: ROM-free fakes and ROM-backed round trips."""
import io
import os
import struct
import time
from pathlib import Path

import pytest

from pokecore.gen2 import clock as core
from pokecore.gen2.clock import export_clock, lock_clock, stop_with_clock

from pokesim.capability import CoreCapabilityError


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


def test_capability_error_is_the_backends_so_one_handler_reports_it():
    from pokecore.errors import CoreCapabilityError as BackendError
    assert issubclass(CoreCapabilityError, BackendError)


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


# Game time: live adventures lock the cartridge clock to emulated frames and never let it go back.

class FakeRtc(FakeClock):
    def __init__(self, zero=1000.0, clock=1500.0):
        super().__init__()
        self.state = {'timezero': zero, 'clock': clock, 'locked': False, 'follow_frames': False}

    def rtc_state(self):
        return dict(self.state)

    def lock_clock(self, at, follow_frames=False):
        super().lock_clock(at, follow_frames)
        self.state.update(clock=at, locked=True, follow_frames=follow_frames)


class Store:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def test_remembered_clock_follows_the_live_reading_down():
    # A game write can lower the live reading (a blank cartridge zeroes it, day 140 wraps to 0).
    from pokesim.gen2.emulator import CLOCK_KEY, Emulator
    adventure = Emulator.__new__(Emulator)
    adventure.store = Store({CLOCK_KEY: {'elapsed': 140 * 86_400.0}})
    adventure._remember_clock(12.5)
    assert adventure.store.get(CLOCK_KEY) == {'elapsed': 12.5}


def _adventure(cartridge, store=None):
    """The clock half of a Gen II adventure: a booted cartridge, its store and the emulator's methods."""
    from pokesim.gen2.emulator import Emulator
    adventure = Emulator.__new__(Emulator)
    adventure.store = store or Store()
    adventure.rom = None
    adventure.pb = core.boot(io.BytesIO(cartridge), sound=False)
    core.follow_game_time(adventure.pb)
    adventure._clock_live = False
    return adventure


def _run(emulator, frames):
    for _ in range(frames):
        emulator.tick()


# A cartridge with blank save memory zeroes its clock registers about 80 frames after power-on, and
# PyBoy RS 0.1.2 and later apply each write exactly. Tests that follow the clock across frames
# start after that write.
BLANK_CARTRIDGE_CLOCK_RESET = 120


def test_real_boot_locks_at_the_current_reading_and_follows_frames(cartridge):
    emulator = core.boot(io.BytesIO(cartridge), sound=False)
    try:
        _run(emulator, BLANK_CARTRIDGE_CLOCK_RESET)
        before = core.host_elapsed(emulator)
        locked_at = core.follow_game_time(emulator)
        state = emulator.rtc_state()
        assert state['locked'] and state['follow_frames']
        assert before <= locked_at <= before + 1
        time.sleep(0.2)
        assert core.clock_elapsed(emulator) == pytest.approx(locked_at)  # wall time does not move it
        # Core counts emulated cycles, so a tick with the screen off (the boot logo) can count more
        # than one frame, as a console would. With the screen on, one tick is one frame.
        _run(emulator, 300)
        warm = core.clock_elapsed(emulator)
        assert warm >= locked_at + 300 * core.SECONDS_PER_FRAME
        _run(emulator, 600)
        assert core.clock_elapsed(emulator) == pytest.approx(warm + 600 * core.SECONDS_PER_FRAME, abs=1e-6)
    finally:
        emulator.stop(save=False)


def test_real_restart_resumes_from_the_stored_reading_not_wall_time(cartridge):
    from pokesim.gen2.emulator import CLOCK_KEY
    store = Store({CLOCK_KEY: {'elapsed': 3 * 86_400 + 7_200.0}})
    adventure = _adventure(cartridge, store)
    try:
        assert adventure._sync_clock() == 3 * 86_400 + 7_200.0
        registers = adventure.pb.rtc_registers()
        assert (registers['days'], registers['hours']) == (3, 2)
        _run(adventure.pb, 60)
        adventure._remember_clock(core.clock_elapsed(adventure.pb))
        assert store.get(CLOCK_KEY)['elapsed'] > 3 * 86_400 + 7_200.0
    finally:
        adventure.pb.stop(save=False)


def test_real_reload_of_an_older_state_never_goes_back(cartridge):
    from pokesim.gen2.emulator import CLOCK_KEY
    adventure = _adventure(cartridge)
    try:
        _run(adventure.pb, BLANK_CARTRIDGE_CLOCK_RESET)
        adventure._sync_clock(running=86_400.0)
        old = adventure._state_bytes()
        old_reading = core.clock_elapsed(adventure.pb)
        _run(adventure.pb, 3_000)
        running = adventure._clock_reading()
        assert running > old_reading
        adventure._remember_clock(running)
        adventure.pb.load_state(io.BytesIO(old))
        adventure._sync_clock({'rtc_elapsed': old_reading}, running)
        assert core.clock_elapsed(adventure.pb) >= running
        assert adventure.store.get(CLOCK_KEY)['elapsed'] >= running
    finally:
        adventure.pb.stop(save=False)


def test_real_game_clock_write_is_remembered_even_when_lower(cartridge):
    # The game's own clock writes are its time: a blank cartridge zeroes the clock, and every
    # cartridge takes 140 days off when the day counter reaches 140. A restart must resume from the
    # written reading, not from the larger reading before the write.
    from pokesim.gen2.emulator import CLOCK_KEY
    adventure = _adventure(cartridge)
    try:
        adventure._sync_clock(running=86_400.0)
        assert adventure.store.get(CLOCK_KEY)['elapsed'] == pytest.approx(86_400.0)
        _run(adventure.pb, BLANK_CARTRIDGE_CLOCK_RESET)
        written = adventure._clock_reading()
        assert written < 60
        adventure._remember_clock(written)
        assert adventure.store.get(CLOCK_KEY)['elapsed'] == pytest.approx(written)
        assert adventure._sync_clock() == pytest.approx(written)
    finally:
        adventure.pb.stop(save=False)


def test_real_cable_copy_of_a_saved_state_reads_at_least_game_time(cartridge):
    # Cable sides, exports and verifiers open a raw state with an unlocked clock. Game time can be
    # far ahead of the host clock after a fast run, and the copy must still not read less.
    adventure = _adventure(cartridge)
    try:
        ahead = 9 * 86_400 + 1_234.5
        adventure._sync_clock(running=ahead)
        state = adventure._state_bytes()
        assert core.clock_elapsed(adventure.pb) == pytest.approx(ahead)  # saving keeps the reading
        side = core.boot(io.BytesIO(cartridge), sound=False)
        try:
            side.load_state(io.BytesIO(state))
            assert not side.clock_locked
            assert ahead <= core.host_elapsed(side) <= ahead + 5
            registers = side.rtc_registers()
            assert registers['days'] == 9
        finally:
            side.stop(save=False)
    finally:
        adventure.pb.stop(save=False)


def test_real_trade_result_keeps_its_own_later_reading(cartridge):
    # A trade result was made on unlocked copies, so its host reading is the game time at the start
    # of the session plus the session's length. Both sides keep their own clocks this way.
    adventure = _adventure(cartridge)
    try:
        adventure._sync_clock(running=50_000.0)
        state = adventure._state_bytes()
        adventure.pb.load_state(io.BytesIO(state))
        time.sleep(0.3)
        assert adventure._sync_clock({'rtc_elapsed': 50_000.0}, 50_000.0, fresh=True) >= 50_000.3
    finally:
        adventure.pb.stop(save=False)


def test_real_existing_save_migrates_from_its_current_reading(cartridge):
    # A save from before game time has no stored reading and no rtc_elapsed in its manifest. It
    # starts from what it shows on the host clock, and from then on moves only with frames.
    from pokesim.gen2.emulator import CLOCK_KEY
    adventure = _adventure(cartridge)
    try:
        adventure.pb.set_rtc_timezero(time.time() - 40 * 86_400)
        adventure._sync_clock({'frame': 10})
        reading = core.clock_elapsed(adventure.pb)
        assert 40 * 86_400 <= reading <= 40 * 86_400 + 5
        assert adventure.store.get(CLOCK_KEY)['elapsed'] == pytest.approx(reading)
        time.sleep(0.2)
        assert core.clock_elapsed(adventure.pb) == pytest.approx(reading)
    finally:
        adventure.pb.stop(save=False)
