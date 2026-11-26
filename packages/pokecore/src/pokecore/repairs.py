"""Named writes that repair damaged Gen I memory, kept apart from the read-only decoders.

Call only while the emulator is paused or under its exclusive simulation lock.
"""
from .gen1 import W_ENEMY_MON, W_IS_IN_BATTLE, W_PARTY_COUNT, W_PARTY_NICKS
from .yellow import red_layout

NAME_END = 0x50    # the text terminator
NAME_LENGTH = 11
# wEnemyMonPartyPos, which is also wEnemyMonBoxLevel.
W_ENEMY_MON_PARTY_POS = W_ENEMY_MON + 3
WILD_BATTLE = 1
PARTY_LENGTH = 6


def repair_party_nicknames(memory, *, version=None) -> list[int]:
    """End each party nickname at its first text command byte, and return the party slots changed.

    Bytes below 0x60 other than the 0x50 terminator are text commands, which the naming screen can
    never type. A nickname that holds one draws differently from how its bytes decode, so a party
    menu never matches the party. A traded nickname can carry one, since the game copies a received
    name byte for byte. ``version`` is needed only for raw Yellow memory.
    """
    memory = red_layout(memory, version)
    repaired = []
    for index in range(min(memory[W_PARTY_COUNT], 6)):
        start = W_PARTY_NICKS + index * NAME_LENGTH
        for offset in range(NAME_LENGTH):
            value = memory[start + offset]
            if value == NAME_END:
                break
            if value < 0x60:
                memory[start + offset] = NAME_END
                repaired.append(index)
                break
    return repaired


def reset_wild_enemy_party_pos(memory, *, version=None) -> int | None:
    """In a wild battle, set wEnemyMonPartyPos to 0 when it names no party slot, and return what it held.

    The byte is also wEnemyMonBoxLevel. SendNewMonToBox stores the level of a Pokémon it sends to a
    box there, after a catch with a full party or a gift, and only a trainer battle sets it again.
    A wild battle still indexes the enemy party with it: IncrementMovePP, after the enemy's
    Metronome or Mirror Move, adds 1 to a PP byte, and CheckDefrost, after a Fire move thaws the
    enemy, clears a status byte. A level past the sixth slot puts those writes in the current box
    or past it, as on a real cartridge. 0 is the value a new game holds. Returns None when it writes
    nothing. ``version`` is needed only for raw Yellow memory.
    """
    memory = red_layout(memory, version)
    if memory[W_IS_IN_BATTLE] != WILD_BATTLE:
        return None
    stale = memory[W_ENEMY_MON_PARTY_POS]
    if stale < PARTY_LENGTH:
        return None
    memory[W_ENEMY_MON_PARTY_POS] = 0
    return stale
