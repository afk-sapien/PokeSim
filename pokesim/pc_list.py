"""Which box slots Bill's PC list can reach when a nickname holds a text command.

A nickname received in a trade can carry a text command from pret/pokered home/text.asm. The PC
list draws each name, and some commands stop it there. This is the safe-code table from pokecore
0.9.5, checked live on Red, Yellow, Gold and Silver and statically on Crystal:

- With the stack pointer, Core picks past all nine commands in every game, so nothing is guarded.
- Gen I without it, 0x00, 0x4C, 0x57 and 0x5F are safe and the five in GEN1_BREAKS stop the list.
  In Red and Blue the slots at or past that name cannot be picked. In Yellow no slot in that box can.
- Gen II without it, Core gave no table, so all nine commands guard every slot in that box.

A refused pick never takes the wrong Pokémon. The guard keeps the run from asking for one again
and again.
"""
TEXT_COMMANDS = frozenset({0x00, 0x49, 0x4B, 0x4C, 0x51, 0x55, 0x57, 0x58, 0x5F})
GEN1_BREAKS = frozenset({0x49, 0x4B, 0x51, 0x55, 0x58})
GEN2_BREAKS = TEXT_COMMANDS
TERMINATOR = 0x50
NAME = 11


def stops(name, breaks):
    """Whether the printed part of one nickname holds a command in ``breaks``."""
    for value in name:
        if value == TERMINATOR:
            return False
        if value in breaks:
            return True
    return False


def first_stop(names, breaks):
    """Index of the first nickname in a box's packed names that stops the list, or None."""
    for index in range(len(names) // NAME):
        if stops(names[index * NAME:(index + 1) * NAME], breaks):
            return index
    return None


def gen1_unlisted(names, count, yellow):
    """Positions in one Gen I box the PC list cannot reach without the stack pointer."""
    stop = first_stop(bytes(names[:count * NAME]), GEN1_BREAKS)
    if stop is None:
        return range(0)
    return range(count) if yellow else range(stop, count)


def gen2_unlisted_boxes(stored):
    """Gen II boxes whose list a nickname stops when Core has no stack pointer."""
    return frozenset(mon.box for mon in stored if stops(getattr(mon, 'nick_bytes', b'') or b'', GEN2_BREAKS))


def guarded(snapshot, sp):
    """The (box, position) slots a Gen I pick must avoid: none when Core reads the stack."""
    if sp is not None:
        return frozenset()
    return frozenset(getattr(snapshot, 'unlisted', ()) or ())
