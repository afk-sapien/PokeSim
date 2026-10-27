"""Export current progress through the cartridge's own Save menu on a private clone.

Core saves and verifies the result (``pokecore.gen1_save``). PokeSim adds the checks that
belong to a running adventure.
"""
from pokecore.gen1_save import export, verify

from .ram import read_snapshot
from .screen import Screen

__all__ = ['capture', 'export', 'verify']


def capture(emu):
    """Called on the live emulator thread. No input or game memory is changed."""
    if emu.store.get('trade_hold'):
        raise ValueError('Wait for the trade to finish before exporting a save.')
    snapshot = read_snapshot(emu.pb.memory, emu.frame)
    if (not snapshot.valid or not snapshot.started or not snapshot.party
            or snapshot.in_battle or Screen(emu.pb.memory).kind(snapshot) not in ('overworld', 'pause')):
        raise ValueError('Export is available outside battles and dialogue. Try again when the trainer is walking.')
    return emu._state_bytes()
