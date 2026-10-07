"""Export verified cartridge saves on a private Generation II emulator."""
from __future__ import annotations

import io

from .core import boot, stop_with_clock

from .ram import Memory, read_snapshot

BUTTONS = ('up', 'down', 'left', 'right', 'a', 'b', 'start', 'select')


def press(pb, button=None, wait=40):
    if button:
        pb.button_press(button)
    pb.tick(8, render=False)
    if button:
        pb.button_release(button)
    pb.tick(wait, render=False)


def progress(snapshot):
    return (snapshot.party, snapshot.stored, snapshot.box_counts, snapshot.active_box,
            snapshot.owned, snapshot.seen, snapshot.badges, snapshot.money, snapshot.items,
            snapshot.player_name, snapshot.rival_name, snapshot.map, snapshot.x, snapshot.y,
            snapshot.event_flags)


def capture(emu):
    if emu.store.get('trade_hold'):
        raise ValueError('Wait for the exchange to finish before exporting a save.')
    snapshot = read_snapshot(emu.pb.memory, emu.data)
    if not snapshot.started or not snapshot.party or snapshot.in_battle or '┌' in snapshot.tiles[12]:
        raise ValueError('Export is available while the trainer is walking, outside battles and dialogue.')
    return emu._state_bytes()


def export(rom, state, data):
    """The verified 32 KiB cartridge save for a checkpoint."""
    return export_with_clock(rom, state, data)[0]


def export_with_clock(rom, state, data):
    """The verified cartridge save and the ten-byte clock file that belongs with it.

    A Gen II save without its clock is read as having lost the time: the cartridge asks for it again.
    """
    rom_bytes = rom.read_bytes()
    pb = boot(io.BytesIO(rom_bytes), sound=True)
    try:
        pb.load_state(io.BytesIO(state))
        for button in BUTTONS:
            pb.button_release(button)
        press(pb, wait=16)
        snapshot = read_snapshot(pb.memory, data)
        if not snapshot.started or not snapshot.party or snapshot.in_battle or '┌' in snapshot.tiles[12]:
            raise ValueError('The trainer is busy. Try exporting again while walking.')
        expected = progress(snapshot)
        mem = Memory(pb.memory, data)
        if 'SAVE' not in snapshot.text:
            press(pb, 'start')
        for _ in range(12):
            rows = mem.tiles()
            selected = next((row for row in rows if '▶' in row), '')
            if 'SAVE' in selected:
                break
            if not any('SAVE' in row for row in rows):
                raise ValueError('The cartridge cannot open its Save menu here.')
            press(pb, 'down', 12)
        else:
            raise ValueError('The cartridge Save option was unavailable.')
        press(pb, 'a')
        for _ in range(100):
            text = '\n'.join(mem.tiles()).upper()
            if 'SAVED' in text and 'GAME' in text:
                break
            rows = mem.tiles()
            selected = next((row for row in rows if '▶' in row), '')
            press(pb, 'up' if 'NO' in selected else 'a', 30)
        else:
            raise ValueError('The cartridge did not finish saving.')
        if progress(read_snapshot(pb.memory, data)) != expected:
            raise ValueError('Progress changed during export. No save was downloaded.')
        output = io.BytesIO()
        clock = io.BytesIO()
        stop_with_clock(pb, output, clock)
        save = output.getvalue()
    finally:
        pb.stop(save=False)
    if len(save) != 32768:
        raise ValueError('The cartridge produced an unexpected save size.')
    verify(rom_bytes, save, data, expected, rtc=clock.getvalue())
    return save, clock.getvalue()


def verify(rom, save, data, expected, *, rtc=None):
    pb = boot(io.BytesIO(rom), ram=io.BytesIO(save), rtc=rtc, sound=True)
    try:
        continued = False
        for index in range(180):
            snapshot = read_snapshot(pb.memory, data)
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
            press(pb, button)
        raise ValueError('The exported save could not be verified after restarting.')
    finally:
        pb.stop(save=False)
