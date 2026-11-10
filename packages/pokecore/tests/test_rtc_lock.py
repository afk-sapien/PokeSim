"""Locked clocks through Core: exporting, and restoring checkpoints with and without clock data."""
import io
import struct
import time
from copy import deepcopy

import pytest

from test_rtc import machine, observed, rtc_file

DAY = 86400
HOUR = 3600


@pytest.fixture(autouse=True)
def require_new_backend():
    backend = pytest.importorskip("pyboy_rs")
    if not backend.has_feature("rtc_export_follows_host"):
        pytest.fail("pyboy_rs is too old: it lacks rtc_export_follows_host")


def reading(emulator):
    r = emulator.rtc_registers()
    return r["days"] * DAY + r["hours"] * HOUR + r["minutes"] * 60 + r["seconds"]


def locked(elapsed=3 * DAY + 5 * HOUR, at=2_000_000_000.0):
    emulator = machine(rtc_file=rtc_file(at - elapsed))
    emulator.lock_clock(at=at)
    return emulator


def test_export_while_locked_follows_the_host_not_the_fake_time():
    with locked() as emulator:
        before = (emulator.rtc_state(), emulator.clock_lock_state())
        exported = emulator.export_rtc()
        assert (emulator.rtc_state(), emulator.clock_lock_state()) == before
        stored = struct.unpack_from("<d", exported)[0]
        assert abs(stored - (time.time() - (3 * DAY + 5 * HOUR))) <= 3
        with machine(rtc_file=exported) as other:
            assert not other.clock_locked
            assert abs(reading(other) - (3 * DAY + 5 * HOUR)) <= 3  # not +1057 days
        out = io.BytesIO()
        emulator.stop(rtc_file=out)
        assert abs(struct.unpack_from("<d", out.getvalue())[0] - stored) <= 3


def test_checkpoint_without_clock_data_releases_a_lock_deterministically():
    with machine(rtc_file=rtc_file(time.time() - 500)) as live:
        live.tick(5, render=False, sound=False)
        checkpoint = live.checkpoint()
    assert checkpoint["rtc_clock"] is None
    legacy = deepcopy(checkpoint)
    del legacy["rtc_clock"]
    for form in (checkpoint, legacy):
        with locked(elapsed=HOUR, at=1.0e9) as emulator:
            emulator.restore_checkpoint(form)
            assert not emulator.clock_locked and emulator.clock_lock_state() is None
            assert abs(reading(emulator) - 500) <= 5


def test_locked_checkpoint_restores_into_a_differently_locked_emulator():
    with locked() as first, locked(at=7.0e8) as second:
        first.tick(40, render=False, sound=False)
        checkpoint = first.checkpoint()
        second.restore_checkpoint(checkpoint)
        assert second.clock_lock_state() == first.clock_lock_state()
        assert observed(first, 100) == observed(second, 100)


@pytest.mark.parametrize("match", ["version", "state_format"])
def test_checkpoint_from_a_rebuilt_wheel_restores(match):
    with locked() as first, locked() as second:
        first.tick(30, render=False, sound=False)
        checkpoint = first.checkpoint()
        assert checkpoint["format"] == 2
        checkpoint["emulator"] = {**checkpoint["emulator"], "native_sha256": "0" * 64, "binding_sha256": "1" * 64}
        checkpoint["execution"]["build"] = {"version": checkpoint["emulator"]["version"],
                                            "native_sha256": "0" * 64, "binding_sha256": "1" * 64}
        second.restore_checkpoint(checkpoint, match=match)
        assert second.save() == first.save()
        with pytest.raises(ValueError, match="original emulator build"):
            second.restore_checkpoint(checkpoint, match="exact")


def test_a_trace_with_a_locked_clock_verifies_on_an_unlocked_machine(tmp_path):
    from pokecore.trace import HARNESS, OK, Recorder, Segment, Trace, verify
    path = tmp_path / "a.jsonl.gz"
    with locked() as first:
        first.tick(10, render=False, sound=False)
        recorder = Recorder(first, check_every=10)
        recorder.begin(Segment(path, keep_start=True))
        first.tick(20, render=False, sound=False)
        first.advance_clock(HOUR)
        first.tick(5, render=False, sound=False)
        recorder.detach()
    trace = Trace.read(path)
    assert trace.header["clock"] is not None
    assert any(record.get("source") == "clock" for record in trace.records)
    with machine(rtc_file=rtc_file(0)) as second:
        result = verify(trace, second)
        assert result.code == OK, result.message
    with machine(rtc_file=rtc_file(0)) as host:
        recorder = Recorder(host)
        recorder.begin(Segment(tmp_path / "host.jsonl.gz", keep_start=True))
        host.tick(2, render=False, sound=False)
        recorder.detach()
    with machine(rtc_file=rtc_file(0)) as third:
        result = verify(tmp_path / "host.jsonl.gz", third)
        assert result.code == HARNESS and "host clock" in result.message
