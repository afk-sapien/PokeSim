"""Export verified cartridge saves on a private Generation II emulator.

Core drives the game's own Save menu and verifies the result (``pokesim_core.gen2.save``).
PokeSim adds the checks that belong to a running adventure.
"""
from __future__ import annotations

from pokesim_core.gen2.save import BUTTONS, clock_archive, export, export_with_clock, press, progress, verify

from pokesim_core.gen2.ram import read_snapshot

__all__ = ['BUTTONS', 'capture', 'clock_archive', 'export', 'export_with_clock', 'press', 'progress', 'verify']


def capture(emu):
    """The adventure's current state for an export, refused during a trade or outside the overworld."""
    if emu.store.get('trade_hold'):
        raise ValueError('Wait for the exchange to finish before exporting a save.')
    snapshot = read_snapshot(emu.pb.memory, emu.data)
    if not snapshot.started or not snapshot.party or snapshot.in_battle or '┌' in snapshot.tiles[12]:
        raise ValueError('Export is available while the trainer is walking, outside battles and dialogue.')
    return emu._state_bytes()
