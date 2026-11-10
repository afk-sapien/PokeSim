"""The Gen 2 naming keyboard on a real cartridge. Collected only when POKESIM_CORE_GEN2_ROMS is set."""
import os
from pathlib import Path

import pytest

from pokecore import gen1_save
from pokecore.controls import ControllerPort
from pokecore.gen2.state import memory_reader
from pokecore.naming import enter_name, gen2_naming
from rom_games import tables

pytest.importorskip('pyboy_rs')


@pytest.mark.parametrize('version', ['crystal'])
def test_player_name_entry_types_symbols_and_submits(version):
    from pokecore.gen2.clock import boot, follow_game_time
    from pokecore.gen2.ram import Memory
    rom = Path(os.environ['POKESIM_CORE_GEN2_ROMS']) / f'{version}.gbc'
    if not rom.exists():
        pytest.skip(f'{rom.name} is not in POKESIM_CORE_GEN2_ROMS')
    emulator = boot(rom.read_bytes(), sound=False)
    try:
        follow_game_time(emulator)
        mem = Memory(emulator.memory, tables(version))
        for step in range(600):
            if '▶NEW NAME' in '\n'.join(mem.tiles()):
                gen1_save.press(emulator, 'a')
                break
            gen1_save.press(emulator, 'start' if step < 3 else 'a', 40)
        else:
            pytest.fail('the player name menu never opened')
        for _ in range(20):
            if gen2_naming(emulator.memory, version):
                break
            gen1_save.press(emulator, None, 10)
        view = gen2_naming(emulator.memory, version)
        assert view['subject'] == 'player' and view['limit'] == 7 and view['length'] == 0

        def send(button, hold=6, gap=24):
            gen1_save.press(emulator, button, max(hold + gap, 1))
            return True
        port = ControllerPort(emulator.memory, send, None, lambda: {'kind': 'naming'}, lambda: 0, version=version)
        result = enter_name(port, 'GO-L.D!')
        assert result['completed'], result
        gen1_save.press(emulator, None, 60)
        assert memory_reader(emulator.memory, version).text('wPlayerName') == 'GO-L.D!'
    finally:
        emulator.stop(save=False)
