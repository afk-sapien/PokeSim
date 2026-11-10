"""Checkpoint provenance, clock lock handling, capability errors and the press and tick contract."""
import io
import math
import struct
import sys
from types import SimpleNamespace

import pytest

import pokecore.emulator_state as state
from pokecore.checkpoint_audio import enable_checkpoint_sound
from pokecore.emulator import Emulator, clock_control_supported
from pokecore.errors import CoreCapabilityError

from test_rtc import ClockBackend, NoRtcBackend, machine, rtc_file


def provenance(**changes):
    base = {"backend": "pyboy-rs", "version": "0.1.1", "state_format": state.STATE_FORMAT,
            "native_sha256": "a" * 64, "binding_sha256": "b" * 64}
    return {**base, **changes}


@pytest.fixture
def require_rtc():
    backend = pytest.importorskip("pyboy_rs")
    if not hasattr(backend.PyBoy, "lock_clock"):
        pytest.skip("pyboy_rs build without RTC control")


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(state, "runtime_provenance", lambda: provenance())


# Runtime comparison

def test_default_comparison_ignores_binary_hashes_but_not_version_or_format(runtime):
    rebuilt = {"emulator": provenance(native_sha256="c" * 64, binding_sha256="d" * 64)}
    state.validate_runtime(rebuilt)
    state.validate_runtime(rebuilt, version=True)
    with pytest.raises(ValueError, match="original emulator build"):
        state.validate_runtime(rebuilt, exact=True)
    older = {"emulator": provenance(version="0.1.0")}
    state.validate_runtime(older)
    with pytest.raises(ValueError, match="0.1.0.*0.1.1"):
        state.validate_runtime(older, version=True)
    with pytest.raises(ValueError, match="state format"):
        state.validate_runtime({"emulator": provenance(state_format="other")}, version=True)
    with pytest.raises(ValueError, match="state format"):
        state.validate_runtime({"emulator": provenance(backend="pyboy")}, version=True)


def test_checkpoint_from_a_rebuilt_wheel_restores_by_default(require_rtc):
    with machine() as first, machine() as second:
        first.tick(30, render=False, sound=False)
        checkpoint = first.checkpoint()
        checkpoint["emulator"] = {**checkpoint["emulator"], "native_sha256": "0" * 64, "binding_sha256": "1" * 64}
        second.restore_checkpoint(checkpoint)
        assert second.save() == first.save()
        with pytest.raises(ValueError, match="original emulator build"):
            second.restore_checkpoint(checkpoint, match="exact")
        with pytest.raises(ValueError, match="match must be"):
            second.restore_checkpoint(checkpoint, match="loose")


def test_other_backend_version_needs_explicit_opt_in(require_rtc):
    with machine() as first, machine() as second:
        checkpoint = first.checkpoint()
        checkpoint["emulator"] = {**checkpoint["emulator"], "version": "0.0.9"}
        with pytest.raises(ValueError, match="0.0.9"):
            second.restore_checkpoint(checkpoint)
        second.restore_checkpoint(checkpoint, match="state_format")
        del checkpoint["emulator"]
        with pytest.raises(ValueError, match="provenance"):
            second.restore_checkpoint(checkpoint, match="state_format")


# Clock lock beside the checkpoint

def test_every_checkpoint_of_a_clock_cartridge_stores_the_lock_state(require_rtc):
    with machine(rtc_file=rtc_file(500.0)) as emulator:
        assert emulator.checkpoint()["rtc_clock"] is None
        emulator.lock_clock(at=1000.0)
        for _ in range(2):
            checkpoint = emulator.checkpoint()
            assert checkpoint["rtc_clock"] == emulator.clock_lock_state()
            assert checkpoint["rtc_clock"]["base"] == 1000.0
            emulator.tick(3, render=False, sound=False)
    with machine(0x13) as emulator:
        assert "rtc_clock" not in emulator.checkpoint()


def test_locked_checkpoint_from_another_build_needs_the_same_lock_applied(require_rtc):
    with machine(rtc_file=rtc_file(500.0)) as first, machine(rtc_file=rtc_file(500.0)) as second:
        first.lock_clock(at=1000.0)
        first.advance_clock(7)
        checkpoint = first.checkpoint()
        checkpoint["emulator"] = {**checkpoint["emulator"], "version": "0.0.9"}
        before = second.checkpoint()
        with pytest.raises(ValueError, match="locked clock"):
            second.restore_checkpoint(checkpoint, match="state_format")
        second.lock_clock(at=1000.0)
        with pytest.raises(ValueError, match="locked clock"):
            second.restore_checkpoint(checkpoint, match="state_format")
        second.advance_clock(7)
        second.restore_checkpoint(checkpoint, match="state_format")
        assert second.clock_lock_state() == first.clock_lock_state()
        assert before["rtc_clock"] is None
        # An unlocked checkpoint from another build has no lock to lose.
        unlocked = {**before, "emulator": checkpoint["emulator"]}
        second.restore_checkpoint(unlocked, match="state_format")
        assert not second.clock_locked


def test_locked_checkpoint_on_a_backend_without_clock_control_is_refused(require_rtc, monkeypatch):
    with machine(rtc_file=rtc_file(500.0)) as emulator:
        emulator.lock_clock(at=1000.0)
        checkpoint = emulator.checkpoint()
        before = emulator.checkpoint()
        monkeypatch.setattr("pokecore.emulator.clock_control_supported", lambda backend=None: False)
        with pytest.raises(CoreCapabilityError, match="real-time clock"):
            emulator.restore_checkpoint(checkpoint)
        monkeypatch.undo()
        assert emulator.checkpoint() == before


# Capability detection

ALL_METHODS = ("rtc_export", "rtc_import", "rtc_registers", "set_rtc_registers", "rtc_state", "set_rtc_timezero",
               "clock_now", "lock_clock", "unlock_clock", "advance_clock", "clock_lock_state", "set_clock_lock_state")


def backend_class(*, methods=ALL_METHODS, **attributes):
    return type("PyBoy", (), {**{name: (lambda self, *a, **k: None) for name in methods}, **attributes})


def test_capability_follows_methods_and_the_build_flag(monkeypatch):
    assert clock_control_supported(backend_class())
    assert not clock_control_supported(backend_class(methods=ALL_METHODS[:-1]))
    assert not clock_control_supported(backend_class(has_rtc=False))
    assert clock_control_supported(backend_class(has_rtc=True))
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(has_rtc=lambda: False, PyBoy=backend_class()))
    assert not clock_control_supported()
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(has_rtc=False, PyBoy=backend_class()))
    assert not clock_control_supported(backend_class())
    for flags in (dict(HAS_CLOCK_CONTROL=False), dict(has_feature=lambda name: name != "advance_clock")):
        monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=backend_class(), **flags))
        assert not clock_control_supported()
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=backend_class(), HAS_CLOCK_CONTROL=True,
                                                                  has_feature=lambda name: True))
    assert clock_control_supported()
    monkeypatch.delitem(sys.modules, "pyboy_rs")
    assert not clock_control_supported()


def test_capability_error_is_a_runtime_error_and_not_not_implemented(monkeypatch):
    assert issubclass(CoreCapabilityError, RuntimeError)
    assert not issubclass(CoreCapabilityError, NotImplementedError)
    NoRtcBackend.instances = []
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=NoRtcBackend))
    emulator = Emulator(io.BytesIO(bytes(32768)))
    with pytest.raises(CoreCapabilityError):
        try:
            emulator.lock_clock()
        except NotImplementedError:
            pytest.fail("a broad NotImplementedError handler must not catch it")
    for name in ("start_sequence", "start_profiling"):
        with pytest.raises(CoreCapabilityError):
            getattr(emulator, name)(*(([],) if name == "start_sequence" else ()))
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=ClockBackend))
    assert Emulator(io.BytesIO(bytes(32768))).clock_control_available


# Provenance for a downgrade to applications that still require pyboy_version

def test_checkpoint_metadata_keeps_the_pyboy_tag_when_states_are_format_15(runtime):
    metadata = state.checkpoint_metadata()
    assert metadata["pyboy_version"] == "2.7.0" and metadata["emulator"]["backend"] == "pyboy-rs"
    state.validate_runtime(metadata, version=True)
    assert "pyboy_version" not in state.checkpoint_metadata(rtc_clock={"base": 1.0, "offset": 0.0,
                                                                         "frames": 0, "follow_frames": False})
    assert state.checkpoint_metadata(rtc_clock=None)["pyboy_version"] == "2.7.0"


def test_retag_keeps_the_pyboy_tag_only_when_truthful(runtime, monkeypatch):
    output = state.retag_checkpoint({"pyboy_version": "2.7.0", "frame": 5})
    assert output["pyboy_version"] == "2.7.0" and output["emulator"] == provenance()
    assert output["emulator_migration"]["from"] == {"backend": "pyboy", "version": "2.7.0"}
    assert state.same_runtime_or_recorded_migration({"pyboy_version": "2.7.0", "frame": 5}, output)
    again = state.retag_checkpoint(output)
    assert again["pyboy_version"] == "2.7.0" and again["emulator"] == provenance()
    assert "emulator_migration" in output and "emulator_migration" in again
    # Another PyBoy release, an unknown backend, a locked clock or another state format are not tagged.
    assert "pyboy_version" not in state.retag_checkpoint({"pyboy_version": "2.6.0"})
    assert "pyboy_version" not in state.retag_checkpoint({"emulator": {"backend": "other", "version": "1"}})
    locked = {"emulator": provenance(), "rtc_clock": {"base": 1.0, "offset": 0.0, "frames": 0, "follow_frames": False}}
    assert "pyboy_version" not in state.retag_checkpoint(locked)
    monkeypatch.setattr(state, "runtime_provenance", lambda: provenance(state_format="pyboy-format-16"))
    assert "pyboy_version" not in state.retag_checkpoint({"pyboy_version": "2.7.0"})


# Copies of how PokeSim 0.4.19 judges a checkpoint manifest. PokeSim v0.4.19 runs PyBoy 2.7.0.
# Each helper replicates the version check of one call site and returns normally on acceptance.

INSTALLED_PYBOY = "2.7.0"


def pokesim_0419_autosave_check(metadata):
    """pokesim/emulator.py _load_state_file: a mismatch makes the autosave unusable."""
    if metadata.get("pyboy_version") != INSTALLED_PYBOY:
        raise ValueError("Checkpoint requires a different PyBoy version")


def pokesim_0419_headless_check(metadata):
    """pokesim/headless.py _load: indexes the key, so an untagged manifest is a KeyError."""
    if metadata["pyboy_version"] != INSTALLED_PYBOY:
        raise ValueError("ROM or emulator version does not match the checkpoint")


def pokesim_0419_trade_check(metadata):
    """pokesim/trade/pair.py inspect."""
    if metadata.get("pyboy_version") != INSTALLED_PYBOY:
        raise ValueError("Checkpoint runtime is incompatible with the trade worker")


POKESIM_0419_CHECKS = (pokesim_0419_autosave_check, pokesim_0419_headless_check, pokesim_0419_trade_check)


def test_rust_checkpoint_is_accepted_by_the_pokesim_0419_validations(require_rtc):
    with machine() as emulator:
        emulator.tick(10, render=False, sound=False)
        checkpoint = emulator.checkpoint()
        assert checkpoint["pyboy_version"] == "2.7.0" and checkpoint["emulator"]["backend"] == "pyboy-rs"
        for check in POKESIM_0419_CHECKS:
            check(checkpoint)
        emulator.restore_checkpoint(checkpoint)
    with machine(rtc_file=rtc_file(500.0)) as emulator:
        for check in POKESIM_0419_CHECKS:  # following the host clock, no lock to lose
            check(emulator.checkpoint())


def test_locked_clock_checkpoint_is_refused_by_the_pokesim_0419_validations(require_rtc):
    with machine(rtc_file=rtc_file(500.0)) as emulator:
        emulator.lock_clock(at=1000.0)
        checkpoint = emulator.checkpoint()
        assert checkpoint["rtc_clock"] is not None and "pyboy_version" not in checkpoint
        with pytest.raises(ValueError, match="different PyBoy"):
            pokesim_0419_autosave_check(checkpoint)
        with pytest.raises(KeyError):
            pokesim_0419_headless_check(checkpoint)
        with pytest.raises(ValueError, match="trade worker"):
            pokesim_0419_trade_check(checkpoint)
        emulator.restore_checkpoint(checkpoint)  # Core itself still restores it


def test_checkpoint_is_untagged_for_another_state_format(require_rtc, monkeypatch):
    with machine() as emulator:
        assert emulator.checkpoint()["pyboy_version"] == "2.7.0"
        monkeypatch.setattr(state, "runtime_provenance", lambda: provenance(state_format="pyboy-format-16"))
        assert "pyboy_version" not in emulator.checkpoint()


# Checkpoint audio patch

def disabled_apu_state():
    """Smallest byte string the format-15 audio adapter accepts, following the pinned layout."""
    apu = 5 + 26 + 8192 + 160 + 11 + 144 * 5 + 5 + 24 + 1
    clocks = apu + 24 + 1602 + 1
    raw = bytearray(clocks + 67)
    raw[0], raw[4] = 15, 0
    struct.pack_into("<QQd", raw, apu, 0, 800, 70224 / 800)
    struct.pack_into("<ddQ", raw, clocks, float(1 << 31), float(1 << 31), 1 << 31)
    struct.pack_into("<Q", raw, clocks + 24, 1000)
    return bytes(raw), clocks


def test_checkpoint_sound_patch_enables_the_disabled_clocks_on_a_copy():
    raw, clocks = disabled_apu_state()
    patched = enable_checkpoint_sound(raw)
    assert patched is not raw and len(patched) == len(raw) and raw == disabled_apu_state()[0]
    period = 70224 / 800
    assert struct.unpack_from("<ddQ", patched, clocks) == (1000 + period, 1000 + 8192, math.ceil(1000 + period))
    assert patched[clocks + 56] == 0x80 and patched[clocks + 66] == 0x77
    assert patched[clocks + 58:clocks + 66] == bytes((128, 64, 32, 16, 8, 4, 2, 1))
    assert enable_checkpoint_sound(patched) == patched  # Already enabled states pass through.


@pytest.mark.parametrize("damage", ["short", "version", "color", "samples", "clock"])
def test_checkpoint_sound_patch_leaves_unknown_states_untouched(damage):
    raw, clocks = disabled_apu_state()
    data = bytearray(raw)
    if damage == "short":
        data = data[:clocks + 10]
    elif damage == "version":
        data[0] = 14
    elif damage == "color":
        data[4] = 1
    elif damage == "samples":
        struct.pack_into("<Q", data, clocks - 1602 - 1 - 24 + 8, 801)
    else:
        struct.pack_into("<d", data, clocks, 5.0)
    assert enable_checkpoint_sound(bytes(data)) == bytes(data)


# press and tick

class RecordingBackend:
    def __init__(self, rom, **options):
        self.frame_count = 0
        self.events = []

    def set_emulation_speed(self, speed):
        pass

    def button_press(self, button):
        self.events.append(("press", button))

    def button_release(self, button):
        self.events.append(("release", button))

    def tick(self, frames, render=True, sound=True):
        self.events.append(("tick", frames))
        self.frame_count += frames

    def save_state(self, stream):
        stream.write(bytes(self.events.__len__().to_bytes(2, "little")))


def test_press_waits_for_the_next_tick_and_checkpoint_carries_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=RecordingBackend))
    emulator = Emulator(io.BytesIO(bytes(32768)))
    backend = emulator._backend
    emulator.press("a")
    assert backend.events == [] and emulator.pending_inputs == (("a", True),)
    assert emulator.save() == b"\x00\x00"  # A raw save between press and tick misses the press.
    monkeypatch.setattr(state, "runtime_provenance", lambda: provenance())
    assert emulator.checkpoint()["pending_inputs"] == (("a", True),)
    emulator.tick(2)
    assert backend.events == [("press", "a"), ("tick", 2)] and emulator.pending_inputs == ()
