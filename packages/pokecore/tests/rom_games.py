"""New-game drivers for the cartridge tests. No save files are committed, so each test plays
from the title screen to the first overworld and then sets up what it needs in WRAM.
"""
import re

from pokecore import gen1_save
from pokecore.gen1_ui import read_screen
from pokecore.gen2 import GameTables
from pokecore.gen2.clock import boot
from pokecore.gen2.ram import Memory
from pokecore.shortcuts.screens import current_screen

# The player's bedroom, where every Gen II game starts after the clock and the name.
BEDROOM = 24 * 256 + 7
_HOUR = re.compile(r'(MORN|DAY|NITE)\s*(\d+)')
_MINUTE = re.compile(r'(\d+)\s*min')


def tables(version):
    """The smallest game tables a snapshot needs: the bedroom map, so ``started`` holds there."""
    return GameTables({'game': version, 'maps': {str(BEDROOM): {'name': 'Bedroom', 'constant': 'PLAYERS_HOUSE_2F'}}})


def shown_hour(text):
    """The 24-hour value of the clock menu's hour, or None while it is not on screen."""
    match = _HOUR.search(text)
    if not match:
        return None
    period, hour = match.group(1), int(match.group(2)) % 12
    if period == 'DAY' and hour < 10:
        return hour + 12
    if period == 'NITE' and hour >= 6:
        return hour + 12
    return hour


def shown_minute(text):
    """The minute the clock menu shows, or None while it is not on screen."""
    match = _MINUTE.search(text)
    return int(match.group(1)) if match else None


def _set(emulator, mem, read, target, modulus):
    """Move a clock menu value to ``target``. Presses are dropped while text prints, so re-read."""
    for _ in range(200):
        value = read('\n'.join(mem.tiles()[:12]))
        if value == target:
            return
        if value is None:
            gen1_save.press(emulator, None, 20)
            continue
        up = (target - value) % modulus <= modulus // 2
        gen1_save.press(emulator, 'up' if up else 'down', 12)
    raise AssertionError(f'the clock menu never showed {target}')


def new_gen2_game(rom, version, *, hour=10, minute=0):
    """Boot a Gen II cartridge and set the clock through the game's own menus to ``hour``:``minute``.

    Returns the emulator standing in the bedroom with its clock locked to emulated frames.
    """
    from pokecore.gen2.clock import follow_game_time
    emulator = boot(rom, sound=False)
    follow_game_time(emulator)
    mem = Memory(emulator.memory, tables(version))
    stage = 'title'
    for step in range(600):
        text = '\n'.join(mem.tiles())
        if stage == 'title' and 'What time is it?' in text:
            _set(emulator, mem, shown_hour, hour, 24)
            stage = 'hour'
        elif stage == 'hour' and 'How many minutes?' in text:
            _set(emulator, mem, shown_minute, minute, 60)
            stage = 'minute'
        if 'NEW NAME' in text and '▶NEW NAME' in text:
            gen1_save.press(emulator, 'down')
            continue
        if (stage == 'minute' and mem.byte('wMapGroup') * 256 + mem.byte('wMapNumber') == BEDROOM
                and '┌' not in mem.tiles()[12] and not any('▶' in row for row in mem.tiles())):
            gen1_save.press(emulator, None, 60)
            if '┌' not in mem.tiles()[12]:
                return emulator
        gen1_save.press(emulator, 'start' if step < 3 else 'a', 40)
    emulator.stop(save=False)
    raise AssertionError(f'{version} never reached the bedroom (stage {stage})')


def new_gen1_game(rom):
    """Boot a Red, Blue or Yellow cartridge and play to the first overworld with preset names."""
    from pokecore.yellow import open_emulator
    import io
    emulator = open_emulator(io.BytesIO(rom), ram_file=io.BytesIO(bytes(32768)), window='null',
                             sound_emulated=False, log_level='ERROR')
    emulator.set_emulation_speed(0)
    memory = emulator.memory
    version = 'yellow' if b'YELLOW' in rom[0x134:0x144] else 'red'
    for step in range(600):
        screen = read_screen(memory, raw_text=True)
        if 'NEW NAME' in '\n'.join(screen['rows']) and screen['menu_index'] == 0:
            gen1_save.press(emulator, 'down')
            continue
        if (step > 30 and current_screen(memory, version=version) == 'overworld'
                and memory[0xD158] not in (0, 0x50) and memory[0xD34A] not in (0, 0x50)):
            gen1_save.press(emulator, None, 60)
            if current_screen(memory, version=version) == 'overworld':
                return emulator
        gen1_save.press(emulator, 'start' if step < 3 else 'a')
    emulator.stop(save=False)
    raise AssertionError('the cartridge never reached the overworld')


def _write(memory, address, values):
    for offset, value in enumerate(values):
        memory[address + offset] = value


def give_gen2_mon(emulator, version, species=152, level=5):
    """Put one Pokémon in an empty Gen II party, as trusted test setup. Its name text is ``A``."""
    from pokecore.gen2 import symbols
    table = symbols(version)
    struct = bytearray(48)
    struct[0], struct[2], struct[23] = species, 33, 35   # Tackle with full PP
    struct[6:8] = (12345).to_bytes(2, 'big')
    struct[21], struct[22] = 0xAB, 0xCD
    struct[27], struct[31] = 70, level
    struct[34:36] = struct[36:38] = (20).to_bytes(2, 'big')
    for index in range(38, 48, 2):
        struct[index:index + 2] = (10).to_bytes(2, 'big')
    name = bytes([0x80]) + bytes([0x50] * 10)
    memory = emulator.memory
    _write(memory, table['wPartyCount'][1], [1, species, 0xFF])
    _write(memory, table['wPartyMons'][1], struct)
    _write(memory, table['wPartyMonOTs'][1], name)
    _write(memory, table['wPartyMonNicknames'][1], name)


def give_gen1_mon(emulator, species=0x99, level=5):
    """Put one Pokémon (Bulbasaur by default) in an empty Gen I party, as trusted test setup.

    Addresses are Red's. A ``YellowEmulator`` translates them on Yellow.
    """
    from pokecore import gen1
    struct = bytearray(gen1.PARTY_STRUCT)
    struct[0], struct[3], struct[8], struct[29] = species, level, 33, 35   # Tackle with full PP
    struct[1:3] = struct[34:36] = (20).to_bytes(2, 'big')
    struct[12:14] = (12345).to_bytes(2, 'big')
    struct[27], struct[28], struct[33] = 0xAB, 0xCD, level
    for index in range(36, 44, 2):
        struct[index:index + 2] = (10).to_bytes(2, 'big')
    name = bytes([0x80]) + bytes([0x50] * 10)
    memory = emulator.memory
    _write(memory, gen1.W_PARTY_COUNT, [1, species, 0xFF])
    _write(memory, gen1.W_PARTY_MONS, struct)
    _write(memory, gen1.W_PARTY_OT, name)
    _write(memory, gen1.W_PARTY_NICKS, name)
