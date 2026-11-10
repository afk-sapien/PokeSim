"""Gen II cartridge clock and save helpers without a ROM. Cartridge cases are in test_save_roms.py."""
import io
import zipfile

import pytest

from pokecore.errors import CoreCapabilityError
from pokecore.gen2 import clock, save
from pokecore.gen2.clock import export_clock, lock_clock, stop_with_clock


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

    def clock_lock_state(self):
        return {'at': 123.0} if self.clock_locked else None

    def stop(self, ram_file=None, rtc_file=None):
        self.calls.append(('stop', ram_file, rtc_file))
        rtc_file.write(bytes(10))


def test_lock_defaults_to_current_reading_without_rebase():
    emulator = FakeClock()
    lock_clock(emulator)
    assert emulator.calls == [('lock', 123.0, False)]


def test_lock_with_rebase_moves_zero_point_to_the_instant():
    emulator = FakeClock()
    lock_clock(emulator, at=clock.FIXED_CLOCK_EPOCH, follow_frames=True, rebase=True)
    assert emulator.calls == [('lock', clock.FIXED_CLOCK_EPOCH, True), ('zero', clock.FIXED_CLOCK_EPOCH)]


def test_unlock_only_when_locked():
    emulator = FakeClock()
    lock_clock(emulator, False)
    assert emulator.calls == []
    lock_clock(emulator)
    lock_clock(emulator, False)
    assert emulator.calls[-1] == ('unlock',)


def test_stop_with_clock_writes_both_streams():
    emulator, ram, rtc = FakeClock(), io.BytesIO(), io.BytesIO()
    stop_with_clock(emulator, ram, rtc)
    assert rtc.getvalue() == bytes(10)
    assert export_clock(emulator) == bytes(10)


def test_clock_lock_state_is_the_emulators():
    emulator = FakeClock()
    assert clock.clock_lock_state(emulator) is None
    lock_clock(emulator)
    assert clock.clock_lock_state(emulator) == {'at': 123.0}


@pytest.mark.parametrize('operation', [
    lambda e: lock_clock(e),
    lambda e: stop_with_clock(e, io.BytesIO(), io.BytesIO()),
    lambda e: export_clock(e),
    lambda e: clock.clock_elapsed(e),
    lambda e: clock.clock_lock_state(e),
    lambda e: clock.follow_game_time(e),
])
def test_emulator_without_clock_methods_is_a_capability_error(operation):
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


def test_capability_errors_pass_through_unwrapped():
    original = CoreCapabilityError('backend says no')

    class Refusing(FakeClock):
        def export_rtc(self):
            raise original
    with pytest.raises(CoreCapabilityError) as caught:
        export_clock(Refusing())
    assert caught.value is original


def test_unrelated_runtime_errors_pass_through():
    class Broken(FakeClock):
        def export_rtc(self):
            raise RuntimeError('disk on fire')
    with pytest.raises(RuntimeError, match='disk on fire'):
        export_clock(Broken())


def test_boot_with_a_clock_on_an_old_backend_is_a_clear_capability_error(monkeypatch):
    def old_core(rom, **options):
        raise TypeError("__init__() got an unexpected keyword argument 'rtc_file'")
    monkeypatch.setattr(clock, 'CoreEmulator', old_core)
    with pytest.raises(CoreCapabilityError, match='cartridge clock'):
        clock.boot(b'', rtc=bytes(10))


def test_boot_accepts_bytes_and_a_blank_battery(monkeypatch):
    seen = {}

    class Machine:
        def set_emulation_speed(self, speed):
            seen['speed'] = speed

    def factory(rom, **options):
        seen.update(rom=rom.read(), ram=options['ram_file'].read(), options=options)
        return Machine()
    monkeypatch.setattr(clock, 'CoreEmulator', factory)
    clock.boot(b'cart', sound=False)
    assert seen['rom'] == b'cart' and seen['ram'] == bytes(32768) and seen['speed'] == 0
    assert 'rtc_file' not in seen['options'] and seen['options']['sound_emulated'] is False


# Game time: runs can lock the cartridge clock to emulated frames and never let it go back.

class FakeRtc(FakeClock):
    def __init__(self, zero=1000.0, reading=1500.0):
        super().__init__()
        self.state = {'timezero': zero, 'clock': reading, 'locked': False, 'follow_frames': False}

    def rtc_state(self):
        return dict(self.state)

    def lock_clock(self, at, follow_frames=False):
        super().lock_clock(at, follow_frames)
        self.state.update(clock=at, locked=True, follow_frames=follow_frames)

    def set_rtc_timezero(self, value):
        super().set_rtc_timezero(value)
        self.state['timezero'] = value


def test_follow_game_time_locks_at_the_current_reading_with_frames():
    emulator = FakeRtc()
    assert clock.follow_game_time(emulator) == 500.0
    assert emulator.calls == [('lock', 1500.0, True)]
    assert clock.clock_elapsed(emulator) == 500.0


def test_follow_game_time_never_rounds_below_the_target():
    emulator = FakeRtc(zero=1_791_759_621.6996284)
    for target in (0.1, 1234.5678, 86_400 * 3 + 0.3):
        clock.follow_game_time(emulator, target)
        assert clock.clock_elapsed(emulator) >= target


def test_rebase_to_host_keeps_the_reading_and_moves_the_zero_point(monkeypatch):
    emulator = FakeRtc(zero=1000.0, reading=1000.0 + 9 * 86_400)
    monkeypatch.setattr(clock.time, 'time', lambda: 2_000_000_000.0)
    assert clock.rebase_to_host(emulator) == 9 * 86_400
    assert emulator.state['timezero'] == 2_000_000_000.0 - 9 * 86_400
    assert clock.clock_elapsed(emulator) >= 9 * 86_400
    assert clock.host_elapsed(emulator) == 9 * 86_400
    assert emulator.state['follow_frames']


def test_clock_archive_holds_both_files_with_fixed_timestamps():
    archive = save.clock_archive(b'S' * 4, b'R' * 10, name='gold')
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert bundle.namelist() == ['gold.sav', 'gold.rtc']
        assert bundle.read('gold.rtc') == b'R' * 10
        assert {entry.date_time for entry in bundle.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    assert save.clock_archive(b'S', b'R') == save.clock_archive(b'S', b'R')


def test_gen1_save_export_refuses_other_cartridges():
    from pokecore import gen1_save
    with pytest.raises(ValueError, match='Red, Blue, or Yellow'):
        gen1_save.export(b'not a cartridge', b'')
