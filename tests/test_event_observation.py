"""Short invalid cartridge writes must not erase a valid withdrawal baseline."""
from dataclasses import replace
import threading
from unittest.mock import Mock

from pokesim.emulator import Emulator
from pokesim.events import RunMemory
from pokesim.ram import PartyMon
from test_events import snap


def observer(monkeypatch):
    emu = Emulator.__new__(Emulator)
    emu.pb = Mock()
    emu.play_clock = Mock()
    emu._enforce_options = Mock()
    emu._handle_events = Mock()
    emu.store = Mock()
    emu.mem = RunMemory()
    emu.prev_snapshot = None
    emu.pending = []
    emu.rom_sha1 = 'unverified-test-rom'
    emu.lock = threading.Lock()
    emu.last_pos = None
    emu.invalid_since = None
    emu.battle_since = None
    def observe(snapshot):
        emu.frame = snapshot.frame
        monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda *args: snapshot)
        emu._observe()
    return emu, observe


def test_invalid_withdrawal_write_does_not_report_a_release(monkeypatch):
    emu, observe = observer(monkeypatch)
    before = snap(frame=100, stored_pokemon=((0, 0x65, 58, 'PIXEL'),))
    partner = PartyMon(0x65, 150, 180, 58, 'PIXEL')
    partial = replace(partner, max_hp=100)
    invalid = replace(before, frame=130, party=before.party + (partial,))
    arrived = replace(before, frame=160, party=before.party + (partner,))
    withdrawn = replace(arrived, frame=190, stored_pokemon=())
    assert not invalid.valid and arrived.valid
    for state in (before, invalid, arrived, withdrawn, replace(withdrawn, frame=220)):
        observe(state)
    releases = [event for call in emu._handle_events.call_args_list
                for event in call.args[0] if event.type == 'release']
    assert releases == []
    assert emu.snapshot.party[-1] == partner
    assert emu.invalid_since is None


def test_invalid_snapshot_still_reaches_health_and_expires_event_baseline(monkeypatch):
    emu, observe = observer(monkeypatch)
    before = snap(frame=100)
    invalid = replace(before, frame=130, party=(PartyMon(0x65, 200, 100, 58, 'PIXEL'),))
    observe(before)
    observe(invalid)
    assert emu.snapshot == invalid and emu.invalid_since is not None
    assert emu.prev_snapshot == before
    expired = replace(invalid, frame=250)
    observe(expired)
    assert emu.prev_snapshot == expired


def test_real_release_after_invalid_write_is_still_recorded(monkeypatch):
    emu, observe = observer(monkeypatch)
    before = snap(frame=100, stored_pokemon=((0, 0x65, 58, 'PIXEL'),))
    invalid = replace(before, frame=130, party=(PartyMon(0x65, 200, 100, 58, 'PIXEL'),))
    released = replace(before, frame=160, stored_pokemon=())
    for state in (before, invalid, released, replace(released, frame=190)):
        observe(state)
    releases = [event for call in emu._handle_events.call_args_list
                for event in call.args[0] if event.type == 'release']
    assert len(releases) == 1
