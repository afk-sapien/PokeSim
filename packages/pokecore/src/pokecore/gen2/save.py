"""Export and verify Gold, Silver and Crystal cartridge saves on a private emulator.

The cartridge writes its own save through the Save menu on a clone of the run, so the file
is exactly what a console would hold. ``data`` is the consumer's game tables, as for
:func:`pokecore.gen2.read_snapshot`. ROMs are paths or bytes. Nothing is written beside them.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .clock import boot, export_clock, stop_with_clock
from .ram import Memory, read_snapshot

BUTTONS = ('up', 'down', 'left', 'right', 'a', 'b', 'start', 'select')


def press(emulator, button=None, wait=40):
    """Hold ``button`` for eight frames, release it and wait. No button only waits."""
    if button:
        emulator.button_press(button)
    emulator.tick(8, render=False)
    if button:
        emulator.button_release(button)
    emulator.tick(wait, render=False)


def progress(snapshot):
    """The fields a save must restore exactly: party, boxes, dex, badges, money, items, names and place."""
    return (snapshot.party, snapshot.stored, snapshot.box_counts, snapshot.active_box,
            snapshot.owned, snapshot.seen, snapshot.badges, snapshot.money, snapshot.items,
            snapshot.player_name, snapshot.rival_name, snapshot.map, snapshot.x, snapshot.y,
            snapshot.event_flags)


def _walking(snapshot):
    return snapshot.started and snapshot.party and not snapshot.in_battle and '┌' not in snapshot.tiles[12]


def _rom_bytes(rom):
    return bytes(rom) if isinstance(rom, (bytes, bytearray, memoryview)) else Path(rom).read_bytes()


def capture(emulator, data):
    """The raw state of a running emulator, refused unless the trainer is walking with a party.

    No input or game memory is changed. Call it between steps on the emulator's own thread.
    """
    snapshot = read_snapshot(emulator.memory, data)
    if not _walking(snapshot):
        raise ValueError('Export is available while the trainer is walking, outside battles and dialogue.')
    return emulator.save()


def export(rom, state, data):
    """The verified 32 KiB cartridge save for a raw state.

    This is the save alone. Use export_with_clock so the clock travels with it.
    """
    return export_with_clock(rom, state, data)[0]


def clock_archive(save, clock, name='game'):
    """A zip holding the save and its clock file side by side, named so an emulator finds both."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for suffix, content in (('sav', save), ('rtc', clock)):
            entry = zipfile.ZipInfo(f'{name}.{suffix}', (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, content)
    return archive.getvalue()


def export_with_clock(rom, state, data):
    """The verified cartridge save and the ten-byte clock file that belongs with it.

    A Gen II save without its clock is read as having lost the time: the cartridge asks for it again.
    The state is opened with an unlocked clock, so it reads host time against its zero point.
    Rebase a game-time run to the host first (``clock.rebase_to_host``).
    """
    rom_bytes = _rom_bytes(rom)
    emulator = boot(rom_bytes, sound=True)
    try:
        emulator.load_state(io.BytesIO(state))
        for button in BUTTONS:
            emulator.button_release(button)
        press(emulator, wait=16)
        snapshot = read_snapshot(emulator.memory, data)
        if not _walking(snapshot):
            raise ValueError('The trainer is busy. Try exporting again while walking.')
        expected = progress(snapshot)
        mem = Memory(emulator.memory, data)
        if 'SAVE' not in snapshot.text:
            press(emulator, 'start')
        for _ in range(12):
            rows = mem.tiles()
            selected = next((row for row in rows if '▶' in row), '')
            if 'SAVE' in selected:
                break
            if not any('SAVE' in row for row in rows):
                raise ValueError('The cartridge cannot open its Save menu here.')
            press(emulator, 'down', 12)
        else:
            raise ValueError('The cartridge Save option was unavailable.')
        press(emulator, 'a')
        for _ in range(100):
            text = '\n'.join(mem.tiles()).upper()
            if 'SAVED' in text and 'GAME' in text:
                break
            rows = mem.tiles()
            selected = next((row for row in rows if '▶' in row), '')
            press(emulator, 'up' if 'NO' in selected else 'a', 30)
        else:
            raise ValueError('The cartridge did not finish saving.')
        if progress(read_snapshot(emulator.memory, data)) != expected:
            raise ValueError('Progress changed during export. No save was produced.')
        output = io.BytesIO()
        clock = io.BytesIO()
        stop_with_clock(emulator, output, clock)
        save = output.getvalue()
    finally:
        emulator.stop(save=False)
    if len(save) != 32768:
        raise ValueError('The cartridge produced an unexpected save size.')
    verify(rom_bytes, save, data, expected, rtc=clock.getvalue())
    return save, clock.getvalue()


def verify(rom, save, data, expected, *, rtc=None):
    """Boot the save from scratch and check that Continue restores ``expected`` (see ``progress``)."""
    emulator = boot(_rom_bytes(rom), ram=save, rtc=rtc, sound=True)
    try:
        continued = False
        for index in range(180):
            snapshot = read_snapshot(emulator.memory, data)
            if (continued and snapshot.started and snapshot.party and '┌' not in snapshot.tiles[12]
                    and 'CONTINUE' not in snapshot.text and 'BADGES' not in snapshot.text):
                if progress(snapshot) != expected:
                    raise ValueError('The exported save did not restore the same progress.')
                return
            if 'CONTINUE' in snapshot.text:
                continued = True
                button = 'a'
            elif 'NEW GAME' in snapshot.text and not continued:
                raise ValueError('The exported save did not offer Continue.')
            else:
                button = 'a' if continued else 'start' if index % 3 == 0 else 'a'
            press(emulator, button)
        raise ValueError('The exported save could not be verified after restarting.')
    finally:
        emulator.stop(save=False)


def checkpoint_clock(rom, state):
    """The ten-byte clock file a raw state reads as, without changing the source."""
    clone = boot(_rom_bytes(rom), sound=False)
    try:
        clone.load_state(io.BytesIO(state))
        return export_clock(clone)
    finally:
        clone.stop(save=False)


def continue_save(rom, save, data, *, rtc=None):
    """Boot a battery save, choose Continue and return the running emulator once the trainer walks.

    The caller owns the returned emulator and stops it. Raises ValueError if the save never
    reaches the overworld. Checks of where the trainer stands stay with the caller.
    """
    emulator = boot(_rom_bytes(rom), ram=save, rtc=rtc, sound=False)
    try:
        emulator.tick(180, True)
        continuing = False
        for step in range(240):
            snapshot = read_snapshot(emulator.memory, data, step * 48)
            if (continuing and snapshot.started and snapshot.party and 'CONTINUE' not in snapshot.text
                    and 'BADGES' not in snapshot.text):
                press(emulator, wait=120)
                return emulator
            if 'CONTINUE' in snapshot.text:
                continuing = True
                selected = next((row for row in snapshot.tiles if '▶' in row), '')
                button = 'a' if 'CONTINUE' in selected else 'up'
            else:
                button = 'start' if step % 3 == 0 else 'a'
            press(emulator, button, 40)
        raise ValueError('The Gen II save did not Continue to the overworld.')
    except BaseException:
        emulator.stop(save=False)
        raise
