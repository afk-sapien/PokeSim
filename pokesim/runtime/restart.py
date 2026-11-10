"""An owner restart in either generation: the store's one transaction, then the emulator's new game.

docs/design/adventure-state-store.md section 3.4 gives the order.
"""
from ..state.domains import RESTART_PENDING

UNFINISHED = 'A restart did not finish. Relaunch this adventure to start the new game.'


def committed(store):
    """Whether the store already holds the new game. A store that cannot answer counts as yes, so a
    run that cannot tell stops rather than playing the old game over the new one."""
    try:
        return bool(store.get(RESTART_PENDING))
    except Exception:  # noqa: BLE001
        return True


def restart(emu, generation, values, start):
    """Commit ``values`` as the new game's rows, then call ``start`` to boot the new game.

    A failure before the commit raises with the old game whole, and the run plays on. Any failure
    after it sets ``fatal_error``: the store holds the new game, so the old one must neither play on
    nor save. Opening the store again finishes the restart.
    """
    try:
        emu.store.restart(generation, values)
    except BaseException:
        if committed(emu.store):
            emu.fatal_error = UNFINISHED
        raise
    try:
        start()
    except BaseException:
        emu.fatal_error = UNFINISHED
        raise
