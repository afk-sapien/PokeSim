"""Cartridge clock and Save-menu exports on real cartridges.

Collected only when POKESIM_CORE_GEN2_ROMS (gold.gbc, silver.gbc, crystal.gbc) or
POKESIM_CORE_ROMS (red.gb, blue.gb, yellow.gb) names a folder of ROMs. No saves are
committed, so each case plays a new game from the title screen first.
"""
import io
import os
import struct
import time
from pathlib import Path

import pytest

from pokecore import gen1_save
from pokecore.gen2 import clock, read_clock, read_snapshot, save
from rom_games import give_gen1_mon, give_gen2_mon, new_gen1_game, new_gen2_game, tables

pytest.importorskip('pyboy_rs')


def _rom(variable, name):
    directory = os.environ.get(variable)
    if not directory:
        pytest.skip(f'set {variable} to a folder of cartridges to run')
    path = Path(directory) / name
    if not path.exists():
        pytest.skip(f'{name} is not in {variable}')
    return path.read_bytes()


@pytest.fixture(params=['gold', 'silver', 'crystal'])
def gen2(request):
    return request.param, _rom('POKESIM_CORE_GEN2_ROMS', f'{request.param}.gbc')


@pytest.fixture(params=['red', 'blue', 'yellow'])
def gen1(request):
    return request.param, _rom('POKESIM_CORE_ROMS', f'{request.param}.gb')


def _elapsed(emulator):
    registers = emulator.rtc_registers()
    return ((registers['days'] * 24 + registers['hours']) * 60 + registers['minutes']) * 60 + registers['seconds']


def _minutes_past(reading, hour, minute):
    """Minutes the game clock reads past ``hour``:``minute``, across midnight."""
    return (reading['hours'] * 60 + reading['minutes'] - hour * 60 - minute) % 1440


def test_clock_file_round_trips_through_a_fresh_emulator(gen2):
    _, rom = gen2
    file = struct.pack('<d', 1_700_000_000.0) + bytes([0, 0])
    emulator = clock.boot(rom, rtc=file, sound=False)
    try:
        assert clock.export_clock(emulator) == file
    finally:
        emulator.stop(save=False)


def test_locked_rebased_clock_reads_zero_elapsed_and_exports_host_time(gen2):
    # A locked clock exports as its host-following equivalent, never the fake locked base, which a
    # real cartridge or an unlocked emulator would read as a jump of hundreds of days.
    _, rom = gen2
    emulator = clock.boot(rom, sound=False)
    try:
        clock.lock_clock(emulator, at=clock.FIXED_CLOCK_EPOCH, rebase=True)
        assert emulator.clock_locked and _elapsed(emulator) == 0
        exported = clock.export_clock(emulator)
        assert abs(struct.unpack('<d', exported[:8])[0] - time.time()) <= 5
        assert emulator.clock_locked and _elapsed(emulator) == 0
        fresh = clock.boot(rom, rtc=exported, sound=False)
        try:
            assert not fresh.clock_locked and _elapsed(fresh) <= 5
        finally:
            fresh.stop(save=False)
        clock.lock_clock(emulator, False)
        assert not emulator.clock_locked
    finally:
        emulator.stop(save=False)


def test_stop_with_clock_emits_both_files(gen2):
    _, rom = gen2
    emulator = clock.boot(rom, sound=False)
    ram, rtc = io.BytesIO(), io.BytesIO()
    clock.stop_with_clock(emulator, ram, rtc)
    assert len(rtc.getvalue()) == 10 and len(ram.getvalue()) == 32768


def test_game_time_follows_frames_not_wall_time(gen2):
    _, rom = gen2
    emulator = clock.boot(rom, sound=False)
    try:
        before = clock.host_elapsed(emulator)
        locked_at = clock.follow_game_time(emulator)
        state = emulator.rtc_state()
        assert state['locked'] and state['follow_frames']
        assert before <= locked_at <= before + 1
        time.sleep(0.2)
        assert clock.clock_elapsed(emulator) == pytest.approx(locked_at)
        # Core counts emulated cycles, so ticks before the game turns the screen on do not each
        # count a whole frame. With the screen on, one tick is one frame.
        for _ in range(300):
            emulator.tick(render=False)
        warm = clock.clock_elapsed(emulator)
        assert warm > locked_at
        for _ in range(600):
            emulator.tick(render=False)
        assert clock.clock_elapsed(emulator) == pytest.approx(warm + 600 * clock.SECONDS_PER_FRAME, abs=1e-6)
    finally:
        emulator.stop(save=False)


def test_copy_of_a_rebased_state_reads_at_least_game_time(gen2):
    # Exports and verifiers open a raw state with an unlocked clock. Game time can be far ahead of
    # the host clock after a fast run, and the copy must still not read less.
    _, rom = gen2
    emulator = clock.boot(rom, sound=False)
    try:
        ahead = 9 * 86_400 + 1_234.5
        clock.follow_game_time(emulator, ahead)
        assert clock.rebase_to_host(emulator) == pytest.approx(ahead)
        state = emulator.save()
        assert clock.clock_elapsed(emulator) == pytest.approx(ahead)
        assert clock.clock_lock_state(emulator) is not None
        side = clock.boot(rom, sound=False)
        try:
            side.load(state)
            assert not side.clock_locked
            assert ahead <= clock.host_elapsed(side) <= ahead + 5
            assert side.rtc_registers()['days'] == 9
        finally:
            side.stop(save=False)
        exported = save.checkpoint_clock(rom, state)
        assert len(exported) == 10
        assert abs(time.time() - struct.unpack('<d', exported[:8])[0] - ahead) <= 5
    finally:
        emulator.stop(save=False)


@pytest.mark.parametrize('hour,minute', [(15, 37), (23, 5), (7, 59)])
def test_menus_set_the_clock_and_a_restart_keeps_it(gen2, hour, minute):
    version, rom = gen2
    emulator = new_gen2_game(rom, version, hour=hour, minute=minute)
    try:
        assert 0 <= _minutes_past(read_clock(emulator.memory, version), hour, minute) <= 3
        give_gen2_mon(emulator, version)
        clock.rebase_to_host(emulator)
        data = tables(version)
        battery, rtc = save.export_with_clock(rom, save.capture(emulator, data), data)
    finally:
        emulator.stop(save=False)
    assert len(battery) == 32768 and len(rtc) == 10
    resumed = save.continue_save(rom, battery, data, rtc=rtc)
    try:
        assert 0 <= _minutes_past(read_clock(resumed.memory, version), hour, minute) <= 5
        snapshot = read_snapshot(resumed.memory, data)
        assert [(mon.species, mon.level, mon.nick) for mon in snapshot.party] == [(152, 5, 'A')]
    finally:
        resumed.stop(save=False)


def test_gen2_verify_rejects_different_progress(gen2):
    version, rom = gen2
    data = tables(version)
    emulator = new_gen2_game(rom, version)
    try:
        give_gen2_mon(emulator, version)
        clock.rebase_to_host(emulator)
        battery, rtc = save.export_with_clock(rom, save.capture(emulator, data), data)
        expected = list(save.progress(read_snapshot(emulator.memory, data)))
    finally:
        emulator.stop(save=False)
    expected[7] += 1
    with pytest.raises(ValueError, match='same progress'):
        save.verify(rom, battery, data, tuple(expected), rtc=rtc)


def test_gen2_capture_refuses_without_a_party(gen2):
    version, rom = gen2
    emulator = new_gen2_game(rom, version)
    try:
        with pytest.raises(ValueError, match='walking'):
            save.capture(emulator, tables(version))
    finally:
        emulator.stop(save=False)


def test_gen1_save_menu_export_restores_the_party(gen1):
    _, rom = gen1
    emulator = new_gen1_game(rom)
    try:
        with pytest.raises(ValueError, match='walking'):
            gen1_save.capture(emulator)
        give_gen1_mon(emulator)
        state = gen1_save.capture(emulator)
        symbols = gen1_save.symbols_for(rom)
        expected = gen1_save.progress(emulator.memory, symbols)
    finally:
        emulator.stop(save=False)
    battery = gen1_save.export(rom, state)
    assert len(battery) == 32768
    gen1_save.verify(rom, battery, symbols, expected)
    changed = list(expected)
    changed[4] ^= 1
    with pytest.raises(ValueError, match='same progress'):
        gen1_save.verify(rom, battery, symbols, tuple(changed))
