"""Export Red, Blue and Yellow progress through the cartridge's own Save menu on a private clone.

The cartridge writes the save itself, then a fresh emulator boots it and checks that Continue
restores the same collection. ROMs are paths or bytes. Nothing is written beside them and the
live run is never changed. Yellow runs on ``YellowEmulator``, so every read uses Red addresses.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from .gen1 import (W_BADGES, W_CUR_MAP, W_DEX_OWNED, W_DEX_SEEN, W_IS_IN_BATTLE, W_MONEY, W_PLAYER_NAME,
                   W_RIVAL_NAME, W_X, W_Y, read_bag, read_progress)
from .gen1_link_metadata import BUILDS
from .gen1_ui import read_screen
from .shortcuts.screens import current_screen
from .trade import boxed_inventory, gen1_party
from .yellow import open_emulator

BUTTONS = ('up', 'down', 'left', 'right', 'a', 'b', 'start', 'select')


def press(emulator, button=None, wait=60):
    """Hold ``button`` for eight frames, release it and wait. No button only waits."""
    if button:
        emulator.button_press(button)
    emulator.tick(8, render=False)
    if button:
        emulator.button_release(button)
    emulator.tick(wait, render=False)


def symbols_for(rom):
    """The verified cable symbols of a supported English Red, Blue or Yellow cartridge."""
    build = BUILDS.get(hashlib.sha1(_rom_bytes(rom)).hexdigest())
    if build is None:
        raise ValueError('Save export requires a supported English Red, Blue, or Yellow cartridge.')
    return build['symbols']


def progress(memory, symbols):
    """The fields a save must restore exactly: party, boxes, dex, badges, money, bag, names and place.

    ``memory`` uses Red addresses (a ``YellowEmulator``'s memory on Yellow).
    """
    def raw(start, size):
        return bytes(memory[start:start + size])
    return (gen1_party(memory, symbols), boxed_inventory(memory, symbols), raw(W_DEX_OWNED, 19),
            raw(W_DEX_SEEN, 19), memory[W_BADGES], raw(W_MONEY, 3), read_bag(memory),
            raw(W_PLAYER_NAME, 11), raw(W_RIVAL_NAME, 11), memory[W_CUR_MAP], memory[W_X], memory[W_Y])


def _walking(memory):
    """A sane party outside battle, on the overworld or the pause menu."""
    return (read_progress(memory)['valid'] and not memory[W_IS_IN_BATTLE]
            and current_screen(memory) in ('overworld', 'pause'))


def _rom_bytes(rom):
    return bytes(rom) if isinstance(rom, (bytes, bytearray, memoryview)) else Path(rom).read_bytes()


def _pause_menu(screen):
    text = '\n'.join(screen['rows'])
    return 'EXIT' in text and ('ITEM' in text or 'SAVE' in text or 'OPTION' in text)


def _open(rom_bytes, save):
    emulator = open_emulator(io.BytesIO(rom_bytes), ram_file=io.BytesIO(save), window='null',
                             sound_emulated=False, log_level='ERROR')
    emulator.set_emulation_speed(0)
    return emulator


def capture(emulator):
    """The raw state of a running emulator, refused unless the trainer is walking with a party.

    No input or game memory is changed. Call it between steps on the emulator's own thread.
    """
    if not _walking(emulator.memory):
        raise ValueError('Export is available outside battles and dialogue. Try again when the trainer is walking.')
    return emulator.save()


def export(rom, state):
    """Return a verified 32 KiB .sav for a raw state."""
    rom_bytes = _rom_bytes(rom)
    symbols = symbols_for(rom_bytes)
    emulator = _open(rom_bytes, bytes(32768))
    try:
        emulator.load_state(io.BytesIO(state))
        for button in BUTTONS:
            emulator.button_release(button)
        press(emulator, wait=16)
        memory = emulator.memory
        if not _walking(memory):
            raise ValueError('The trainer was changing screens. Try exporting again in a moment.')
        expected = progress(memory, symbols)
        if not _pause_menu(read_screen(memory, raw_text=True)):
            press(emulator, 'start')
        for _ in range(9):
            screen = read_screen(memory, raw_text=True)
            if not _pause_menu(screen) or not screen['cursor']:
                raise ValueError('The game cannot open its Save menu here. Try again when the trainer is walking.')
            if 'SAVE' in screen['rows'][screen['cursor'][1]]:
                break
            press(emulator, 'down', wait=12)
        else:
            raise ValueError('The cartridge Save option is unavailable here.')
        press(emulator, 'a')
        saved = False
        for _ in range(60):
            screen = read_screen(memory, raw_text=True)
            rows, cursor = screen['rows'], screen['cursor']
            if rows[14][1:19].strip().upper().endswith(' SAVED') and 'THE GAME!' in rows[16].upper():
                saved = True
                break
            # The Save confirmation overlays the trainer card. Text to the
            # right of its border belongs to that card, not the YES/NO labels.
            if cursor in ((1, 8), (1, 10)) and rows[8][2:5] == 'YES' and rows[10][2:4] == 'NO':
                press(emulator, 'up' if cursor[1] == 10 else 'a')
            else:
                press(emulator)
        if not saved:
            raise ValueError('The cartridge did not finish saving. Try again outside dialogue.')
        if progress(memory, symbols) != expected:
            raise ValueError('Progress changed while preparing the export. No save was produced.')
        output = io.BytesIO()
        emulator.stop(ram_file=output)
        save = output.getvalue()
    finally:
        emulator.stop(save=False)
    if len(save) != 32768:
        raise ValueError('The cartridge produced an unexpected save size.')
    verify(rom_bytes, save, symbols, expected)
    return save


def verify(rom, save, symbols, expected):
    """Boot the save from scratch and check that Continue restores ``expected`` (see ``progress``)."""
    emulator = _open(_rom_bytes(rom), save)
    try:
        emulator.tick(180, render=False)
        memory = emulator.memory
        continued = False
        for step in range(120):
            screen = read_screen(memory, raw_text=True)
            text = '\n'.join(screen['rows'])
            if 'CONTINUE' in text:
                continued = True
                button = 'up' if screen['menu_index'] else 'a'
            elif 'NEW GAME' in text:
                raise ValueError('The exported save did not offer Continue.')
            elif continued:
                if _walking(memory) and current_screen(memory) == 'overworld':
                    if progress(memory, symbols) != expected:
                        raise ValueError('The exported save did not restore the same progress.')
                    return
                button = None
            else:
                button = 'start' if step % 3 == 0 else 'a'
            press(emulator, button)
        raise ValueError('The exported save could not be verified after restarting the cartridge.')
    finally:
        emulator.stop(save=False)
