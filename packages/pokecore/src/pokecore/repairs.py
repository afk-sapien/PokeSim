"""Named writes that repair damaged Gen I memory, kept apart from the read-only decoders.

Call only while the emulator is paused or under its exclusive simulation lock.
"""
from .gen1 import W_PARTY_COUNT, W_PARTY_NICKS
from .yellow import red_layout

NAME_END = 0x50    # the text terminator
NAME_LENGTH = 11


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
