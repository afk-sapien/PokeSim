"""Core real-time clock control. Every cartridge here is synthetic."""
import io
import struct
import sys
from types import SimpleNamespace

import pytest

from pokecore.emulator import Emulator
from pokecore.errors import CoreCapabilityError

WRAM = 0xC000


def _program():
    code = bytearray(bytes((0x3E, 0x0A, 0xEA, 0x00, 0x00)))  # enable RAM and the clock
    loop = len(code)
    for value in (0, 1):  # latch by writing 0 then 1 to 0x6000
        code += bytes((0x3E, value, 0xEA, 0x00, 0x60))
    for register in range(8, 13):  # copy RTC registers 8..12 to 0xC000..0xC004
        code += bytes((0x3E, register, 0xEA, 0x00, 0x40))
        code += bytes((0xFA, 0x00, 0xA0))
        code += bytes((0xEA, register - 8, WRAM >> 8))
    code += bytes((0x18, (loop - (len(code) + 2)) & 255))
    return bytes(code)


def cartridge(carttype=0x10):
    data = bytearray(32 * 16384)
    data[0x100:0x103] = bytes((0xC3, 0x50, 0x01))
    data[0x150:0x150 + len(_program())] = _program()
    data[0x147] = carttype
    data[0x148] = 4
    data[0x149] = 3
    data[0x14D] = (-sum(data[0x134:0x14D]) - 25) & 255
    return bytes(data)


def rtc_file(timezero, halt=0, carry=0):
    return struct.pack("<d", timezero) + bytes((halt, carry))


def machine(carttype=0x10, **options):
    pytest.importorskip("pyboy_rs")
    return Emulator(io.BytesIO(cartridge(carttype)), **options)


def observed(emulator, frames=3):
    emulator.tick(frames, render=False, sound=False)
    return tuple(emulator.memory[WRAM + offset] for offset in range(5))


@pytest.fixture
def require_rtc():
    backend = pytest.importorskip("pyboy_rs")
    if not hasattr(backend.PyBoy, "lock_clock"):
        pytest.skip("pyboy_rs build without RTC control")


def test_rtc_file_round_trips_and_is_copied(require_rtc):
    data = rtc_file(1_700_000_000.25, 1, 1)
    source = io.BytesIO(data)
    with machine(rtc_file=source) as emulator:
        assert emulator.has_rtc
        assert emulator.export_rtc() == data
        out, ram = io.BytesIO(b"x" * 40), io.BytesIO()
        emulator.stop(ram_file=ram, rtc_file=out)
    assert out.getvalue() == data
    assert source.getvalue() == data and source.tell() == len(data)
    with machine(rtc_file=data) as emulator:
        assert emulator.export_rtc() == data


def test_stop_without_rtc_stream_writes_no_clock(require_rtc):
    source = io.BytesIO(rtc_file(5.0))
    with machine(rtc_file=source) as emulator:
        emulator.stop(save=True, ram_file=io.BytesIO())
    assert source.getvalue() == rtc_file(5.0)


def test_cartridge_without_rtc(require_rtc):
    with machine(0x13, rtc_file=rtc_file(5.0)) as emulator:
        assert not emulator.has_rtc
        out = io.BytesIO()
        emulator.stop(ram_file=io.BytesIO(), rtc_file=out)
        assert out.getvalue() == b""
    with machine(0x13) as emulator:
        assert "rtc_clock" not in emulator.checkpoint()


def test_import_validation_leaves_clock_unchanged(require_rtc):
    with machine(rtc_file=rtc_file(100.0)) as emulator:
        for bad in (b"", bytes(9), rtc_file(float("nan")), rtc_file(1.0, 2, 0), rtc_file(1.0, 0, 2)):
            with pytest.raises(ValueError):
                emulator.import_rtc(bad)
        assert emulator.export_rtc() == rtc_file(100.0)
        emulator.import_rtc(io.BytesIO(rtc_file(7.0, 1, 0) + b"trailing"))
        assert emulator.export_rtc() == rtc_file(7.0, 1, 0)


def test_registers_are_what_the_game_reads(require_rtc):
    with machine() as emulator:
        emulator.lock_clock(at=1_000_000.0)
        emulator.set_rtc_registers(seconds=5, minutes=4, hours=3, days=2)
        assert observed(emulator, 200) == (5, 4, 3, 2, 0)
        assert emulator.rtc_registers()["days"] == 2
        assert emulator.rtc_state()["timezero"] == 1_000_000.0 - (2 * 86400 + 3 * 3600 + 4 * 60 + 5)


def test_locked_clock_is_deterministic_and_advances_only_on_request(require_rtc):
    with machine(rtc_file=rtc_file(999_000.0)) as first, machine(rtc_file=rtc_file(999_000.0)) as second:
        for emulator in (first, second):
            assert not emulator.clock_locked
            emulator.lock_clock(at=1_000_000.0)
            assert emulator.clock_locked
        assert observed(first, 120) == observed(second, 120) == (40, 16, 0, 0, 0)
        first.advance_clock(61)
        assert observed(first, 5) == (41, 17, 0, 0, 0)
        assert observed(second, 600) == (40, 16, 0, 0, 0)
        with pytest.raises(ValueError):
            first.advance_clock(-1)
        first.unlock_clock()
        assert not first.clock_locked
        with pytest.raises((ValueError, RuntimeError)):
            first.advance_clock(1)


def test_follow_frames_counts_completed_frames(require_rtc):
    with machine(rtc_file=rtc_file(0.0)) as emulator:
        emulator.lock_clock(at=1000.0, follow_frames=True)
        before = emulator.clock_now()
        emulator.tick(600, render=False, sound=False)
        assert emulator.clock_now() - before == 600 * 4389 / 262144


def test_checkpoint_carries_the_lock_for_exact_resume(require_rtc):
    with machine(rtc_file=rtc_file(500.0)) as first, machine(rtc_file=rtc_file(500.0)) as second:
        first.lock_clock(at=1000.0, follow_frames=True)
        first.tick(90, render=False, sound=False)
        first.advance_clock(30.5)
        checkpoint = first.checkpoint()
        assert checkpoint["rtc_clock"] == {"base": 1000.0, "offset": 30.5, "frames": 90, "follow_frames": True}
        second.lock_clock(at=5.0)
        second.restore_checkpoint(checkpoint)
        assert second.clock_now() == first.clock_now()
        for count in (1, 200, 1000):
            assert observed(first, count) == observed(second, count)
            assert first.save() == second.save()
        assert first.checkpoint()["rtc_clock"] == second.checkpoint()["rtc_clock"]


def test_checkpoint_without_lock_state_and_invalid_lock(require_rtc):
    with machine(rtc_file=rtc_file(500.0)) as emulator:
        unlocked = emulator.checkpoint()
        assert unlocked["rtc_clock"] is None
        emulator.lock_clock(at=1000.0)
        legacy = {key: value for key, value in unlocked.items() if key != "rtc_clock"}
        emulator.restore_checkpoint(legacy)
        assert not emulator.clock_locked  # no clock data releases the lock
        emulator.lock_clock(at=1000.0)
        before = emulator.checkpoint()
        for bad in ({}, {"base": 1.0}, [1, 2, 3, 4]):
            with pytest.raises(ValueError, match="clock lock"):
                emulator.restore_checkpoint({**before, "rtc_clock": bad})
        assert emulator.checkpoint() == before
        emulator.restore_checkpoint(unlocked)
        assert not emulator.clock_locked


class NoRtcBackend:
    instances = []

    def __init__(self, rom, **options):
        self.options = options
        self.frame_count = 0
        self.stops = []
        self.instances.append(self)

    def set_emulation_speed(self, speed):
        pass

    def stop(self, save=True, ram_file=None, **options):
        self.stops.append((save, options))


def test_old_backend_gets_a_clear_error_and_no_new_arguments(monkeypatch):
    NoRtcBackend.instances = []
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=NoRtcBackend))
    emulator = Emulator(io.BytesIO(bytes(32768)))
    assert "rtc_file" not in NoRtcBackend.instances[0].options
    assert not emulator.clock_control_available
    for call in (lambda: emulator.has_rtc, lambda: emulator.lock_clock(), lambda: emulator.export_rtc(),
                 lambda: emulator.clock_lock_state(), lambda: emulator.stop(rtc_file=io.BytesIO())):
        with pytest.raises(CoreCapabilityError, match="real-time clock"):
            call()
    emulator.stop()
    assert NoRtcBackend.instances[0].stops == [(False, {})]


class ClockBackend(NoRtcBackend):
    instances = []
    pass


for _name in ("rtc_export", "rtc_import", "rtc_registers", "set_rtc_registers", "rtc_state", "set_rtc_timezero",
              "clock_now", "lock_clock", "unlock_clock", "advance_clock", "clock_lock_state", "set_clock_lock_state"):
    setattr(ClockBackend, _name, lambda self, *args, **kwargs: None)


def test_rtc_file_is_forwarded_as_a_private_copy(monkeypatch):
    ClockBackend.instances = []
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=ClockBackend))
    source = io.BytesIO(b"0123456789")
    Emulator(io.BytesIO(bytes(32768)), rtc_file=source)
    forwarded = ClockBackend.instances[0].options["rtc_file"]
    assert forwarded is not source and forwarded.getvalue() == b"0123456789"
    Emulator(io.BytesIO(bytes(32768)), rtc_file=b"abc")
    assert ClockBackend.instances[1].options["rtc_file"].getvalue() == b"abc"


def test_rtc_file_on_a_backend_without_clock_control_is_refused_before_construction(monkeypatch):
    NoRtcBackend.instances = []
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=NoRtcBackend))
    with pytest.raises(CoreCapabilityError, match="real-time clock"):
        Emulator(io.BytesIO(bytes(32768)), rtc_file=b"0123456789")
    assert NoRtcBackend.instances == []
