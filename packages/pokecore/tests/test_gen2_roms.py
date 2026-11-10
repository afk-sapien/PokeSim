"""Gen II reads on real cartridges. Collected only when POKESIM_CORE_GEN2_ROMS is set.

The directory holds gold.gbc, silver.gbc and crystal.gbc, each optionally with a battery save
next to it (gold.gbc.ram). Set POKESIM_CORE_GEN2_DATA to a directory of <version>/data.json
game tables to also compare full snapshots. Missing files are reported as skips.
"""
import io
import json
import os
from pathlib import Path

import pytest

from pokecore import gen2
from pokecore.gen2 import state
from pokecore.memory_snapshot import snapshot_emulator

ROMS = Path(os.environ.get('POKESIM_CORE_GEN2_ROMS', '.'))
READERS = (state.read_party_structs, state.read_box_structs, state.read_box_counts, state.read_items,
           state.read_player, state.read_pokedex, state.read_clock, state.read_daycare, state.read_roamers)


def machines(version):
    pytest.importorskip('pyboy_rs')
    from pokecore.emulator import Emulator
    rom = ROMS / f'{version}.gbc'
    if not rom.exists():
        pytest.skip(f'{rom.name} is not in POKESIM_CORE_GEN2_ROMS')
    save = rom.with_name(rom.name + '.ram')
    raw, ram = rom.read_bytes(), save.read_bytes() if save.exists() else bytes(32768)
    assert gen2.version_of(raw) == version
    return [cls(io.BytesIO(raw), ram_file=io.BytesIO(ram), sound_emulated=False)
            for cls in (snapshot_emulator(Emulator), Emulator)], save.exists()


@pytest.mark.parametrize('version', gen2.VERSIONS)
def test_snapshot_reads_match_live_reads_through_the_title_screen(version):
    (fast, live), saved = machines(version)
    tables = None
    directory = os.environ.get('POKESIM_CORE_GEN2_DATA')
    if directory:
        tables = gen2.GameTables(json.loads((Path(directory) / version / 'data.json').read_text()))
    try:
        for step in range(40):
            for machine in (fast, live):
                machine.tick(90, render=False, sound=False)
                button = 'start' if step % 3 == 0 else 'a'
                machine.press(button)
                machine.tick(6, render=False, sound=False)
                machine.release(button)
            for read in READERS:
                assert read(fast.memory, version) == read(live.memory, version), read.__name__
            if tables is not None:
                assert repr(gen2.read_snapshot(fast.memory, tables)) == repr(
                    gen2.read_snapshot(live.memory, tables, cache=False))
        if saved:
            player = state.read_player(fast.memory, version)
            assert player['name'] and len(state.read_party_structs(fast.memory, version)) >= 1
    finally:
        fast.stop()
        live.stop()


def boot(version):
    """One live machine with no save, past the boot code."""
    (_, machine), _ = machines(version)
    machine.tick(200, render=False, sound=False)
    return machine


def put(memory, symbols, name, value):
    bank, address = symbols[name] if isinstance(name, str) else name
    value = bytes([value]) if isinstance(value, int) else value
    for index, byte in enumerate(value):
        memory[bank, address + index] = byte


# Addresses from the pinned pokecrystal 87b0d743 symbol file that Core's memory map does not carry.
SET_CAUGHT_DATA, SET_GIFT_PARTY_MON_CAUGHT_DATA, W_CUR_PARTY_LEVEL, H_ROM_BANK = 0x5B49, 0x5BA3, (1, 0xD143), 0xFF9D
CAUGHT_DATA_BANK, ROUTE_30, LANDMARK_ROUTE_30 = 0x13, (26, 1), 4


def call(machine, bank, address, stub):
    """Run one cartridge routine with interrupts off until it returns into a ``jr @`` loop at ``stub``."""
    memory, registers = machine.memory, machine.register_file
    memory[0xFFFF] = 0
    memory[0xFF70] = 1
    memory[0, stub], memory[0, stub + 1] = 0x18, 0xFE
    memory[H_ROM_BANK] = bank
    memory[0x2000] = bank
    sp = 0xC0F0
    memory[sp - 2], memory[sp - 1] = stub & 0xFF, stub >> 8
    registers.SP, registers.PC = sp - 2, address
    machine.tick(1, render=False, sound=False)
    assert registers.PC == stub


def test_crystal_caught_data_written_by_the_cartridge_decodes():
    machine = boot('crystal')
    symbols = gen2.memory_map.symbols('crystal')
    group, number = ROUTE_30
    data = gen2.GameTables({'game': 'crystal', 'maps': {str(group * 256 + number): {
        'landmark': LANDMARK_ROUTE_30, 'environment': 'ROUTE', 'name': 'Route 30'}}})
    try:
        memory, stub = machine.memory, symbols['wTilemap'][1]
        raw = bytearray(48)
        raw[0], raw[31] = 121, 30
        for name, value in (('wPartyCount', 1), ('wPartySpecies', bytes([121, 0xFF])), ('wPartyMons', bytes(raw)),
                            ('wTimeOfDay', 2), (W_CUR_PARTY_LEVEL, 12), ('wMapGroup', group), ('wMapNumber', number),
                            ('wPlayerGender', 1)):
            put(memory, symbols, name, value)
        # SetCaughtData stamps the last party member the way a wild catch does: night, level 12, a female trainer.
        call(machine, CAUGHT_DATA_BANK, SET_CAUGHT_DATA, stub)
        mon = gen2.read_snapshot(memory, data, cache=False).party[0]
        assert mon.caught == 0xCC84
        assert mon.to_dict()['caught'] == {'level': 12, 'time': 'Night', 'location': 'Route 30'}
        assert state.read_party_structs(memory, 'crystal')[0]['caught'] == {
            'time': 'night', 'level': 12, 'trainer_gender': 'Female', 'location': LANDMARK_ROUTE_30}
        # A gift records no level or time, and its landmark reads as Gift.
        machine.register_file.B = 0
        call(machine, CAUGHT_DATA_BANK, SET_GIFT_PARTY_MON_CAUGHT_DATA, stub)
        assert gen2.read_snapshot(memory, data, cache=False).party[0].to_dict()['caught'] == {
            'level': None, 'time': None, 'location': 'Gift'}
    finally:
        machine.stop()


# BattleCommand_Transform in the pinned symbol files. A wild enemy that transforms stores its own DVs there.
TRANSFORM = {'gold': (0x0D, 0x72D0), 'silver': (0x0D, 0x72D0), 'crystal': (0x0D, 0x71CD)}


@pytest.mark.parametrize('version', gen2.VERSIONS)
def test_transform_backup_dvs_are_where_the_cartridge_writes_them(version):
    machine = boot(version)
    symbols = gen2.memory_map.symbols(version)
    rom = (ROMS / f'{version}.gbc').read_bytes()
    bank, address = TRANSFORM[version]
    routine = rom[bank * 0x4000 + address - 0x4000:][:0x80]
    _, backup = symbols['wEnemyBackupDVs']
    for target in (backup, backup + 1):
        assert b'\xea' + target.to_bytes(2, 'little') in routine
    try:
        memory, data = machine.memory, gen2.GameTables({'game': version})
        for name, value in (('wBattleMode', 1), ('wEnemyMonSpecies', 132), ('wEnemyMonDVs', b'\xff\xff'),
                            ('wEnemyBackupDVs', b'\x2a\xaa'), ('wEnemySubStatus5', 0)):
            put(memory, symbols, name, value)
        assert not gen2.read_snapshot(memory, data, cache=False).enemy_shiny
        put(memory, symbols, 'wEnemySubStatus5', 8)
        assert gen2.read_snapshot(memory, data, cache=False).enemy_shiny
    finally:
        machine.stop()
