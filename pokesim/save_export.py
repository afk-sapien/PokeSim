"""Export current progress through the cartridge's own Save menu on a private clone."""
import hashlib
import io

from pyboy import PyBoy

from .interactions.cable_metadata import BUILDS
from .interactions.verification import boxed_inventory, party
from .policies.base import BUTTONS
from .ram import read_snapshot
from .screen import Screen


def capture(emu):
    """Called on the live emulator thread. No input or game memory is changed."""
    if emu.store.get('trade_hold'):
        raise ValueError('Wait for the trade to finish before exporting a save.')
    snapshot = read_snapshot(emu.pb.memory, emu.frame)
    if (not snapshot.valid or not snapshot.started or not snapshot.party
            or snapshot.in_battle or Screen(emu.pb.memory).kind(snapshot) not in ('overworld', 'pause')):
        raise ValueError('Export is available outside battles and dialogue. Try again when the trainer is walking.')
    return emu._state_bytes()


def press(pb, button=None, wait=60):
    if button:
        pb.button_press(button)
    pb.tick(8, render=False)
    if button:
        pb.button_release(button)
    pb.tick(wait, render=False)


def progress(pb, symbols):
    snapshot = read_snapshot(pb.memory, 0)
    return (party(pb, symbols), boxed_inventory(pb, symbols), snapshot.owned, snapshot.seen,
            snapshot.badges, snapshot.money, snapshot.items, snapshot.player_name, snapshot.rival_name,
            snapshot.map, snapshot.x, snapshot.y)


def export(rom, state):
    """Return a verified 32 KiB .sav without writing beside the ROM or changing the live run."""
    rom_bytes = rom.read_bytes()
    build = BUILDS.get(hashlib.sha1(rom_bytes).hexdigest())
    if build is None:
        raise ValueError('Save export requires a supported English Red or Blue cartridge.')
    symbols = build['symbols']
    pb = PyBoy(io.BytesIO(rom_bytes), ram_file=io.BytesIO(bytes(32768)), window='null',
               sound_emulated=False, log_level='ERROR')
    pb.set_emulation_speed(0)
    try:
        pb.load_state(io.BytesIO(state))
        for button in BUTTONS:
            pb.button_release(button)
        press(pb, wait=16)
        snapshot = read_snapshot(pb.memory, 0)
        screen = Screen(pb.memory)
        if not snapshot.valid or snapshot.in_battle or screen.kind(snapshot) not in ('overworld', 'pause'):
            raise ValueError('The trainer was changing screens. Try exporting again in a moment.')
        expected = progress(pb, symbols)
        if not screen.pause_menu:
            press(pb, 'start')
        for _ in range(9):
            screen = Screen(pb.memory)
            if not screen.pause_menu or not screen.cursor:
                raise ValueError('The game cannot open its Save menu here. Try again when the trainer is walking.')
            if 'SAVE' in screen.rows[screen.cursor[1]]:
                break
            press(pb, 'down', wait=12)
        else:
            raise ValueError('The cartridge Save option is unavailable here.')
        press(pb, 'a')
        saved = False
        for _ in range(60):
            screen = Screen(pb.memory)
            if (screen.rows[14][1:19].strip().upper().endswith(' SAVED')
                    and 'THE GAME!' in screen.rows[16].upper()):
                saved = True
                break
            # The Save confirmation overlays the trainer card. Text to the
            # right of its border belongs to that card, not the YES/NO labels.
            if (screen.cursor in ((1, 8), (1, 10))
                    and screen.rows[8][2:5] == 'YES' and screen.rows[10][2:4] == 'NO'):
                press(pb, 'up' if screen.cursor[1] == 10 else 'a')
            else:
                press(pb)
        if not saved:
            raise ValueError('The cartridge did not finish saving. Try again outside dialogue.')
        if progress(pb, symbols) != expected:
            raise ValueError('Progress changed while preparing the export. No file was downloaded.')
        output = io.BytesIO()
        pb.stop(ram_file=output)
        save = output.getvalue()
    finally:
        pb.stop(save=False)
    if len(save) != 32768:
        raise ValueError('The cartridge produced an unexpected save size.')
    verify(rom_bytes, save, symbols, expected)
    return save


def verify(rom_bytes, save, symbols, expected):
    """Boot the exported SRAM from scratch and check that Continue restores this collection."""
    pb = PyBoy(io.BytesIO(rom_bytes), ram_file=io.BytesIO(save), window='null',
               sound_emulated=False, log_level='ERROR')
    pb.set_emulation_speed(0)
    try:
        pb.tick(180, render=False)
        continued = False
        for step in range(120):
            screen = Screen(pb.memory)
            snapshot = read_snapshot(pb.memory, 0)
            if 'CONTINUE' in screen.text:
                continued = True
                button = 'up' if screen.menu_index else 'a'
            elif 'NEW GAME' in screen.text:
                raise ValueError('The exported save did not offer Continue.')
            elif continued:
                if (snapshot.valid and snapshot.started and snapshot.party and not snapshot.in_battle
                        and screen.kind(snapshot) == 'overworld' and not snapshot.start_menu):
                    if progress(pb, symbols) != expected:
                        raise ValueError('The exported save did not restore the same progress.')
                    return
                button = None
            else:
                button = 'start' if step % 3 == 0 else 'a'
            press(pb, button)
        raise ValueError('The exported save could not be verified after restarting the cartridge.')
    finally:
        pb.stop(save=False)
