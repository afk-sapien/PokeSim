"""Named repairs of damaged Gen I memory."""
from pokecore.gen1 import W_PARTY_COUNT, W_PARTY_NICKS
from pokecore.repairs import NAME_END, repair_party_nicknames
from pokecore.yellow import address

# A traded nickname, WETFUND, then the 0x55 text command where the terminator belonged, then LL.
DAMAGED = bytes([0x96, 0x84, 0x93, 0x85, 0x94, 0x8D, 0x83, 0x55, 0x8B, 0x8B, 0x50])
CLEAN = bytes([0x91, 0x84, 0x83, 0x50]).ljust(11, b'\x50')


def party(locate):
    memory = bytearray(0x10000)
    memory[locate(W_PARTY_COUNT)] = 2
    memory[locate(W_PARTY_NICKS):locate(W_PARTY_NICKS) + 11] = CLEAN
    memory[locate(W_PARTY_NICKS) + 11:locate(W_PARTY_NICKS) + 22] = DAMAGED
    return memory


def test_a_red_nickname_ends_at_its_first_text_command_once():
    memory = party(lambda red: red)
    assert repair_party_nicknames(memory) == [1]
    assert memory[W_PARTY_NICKS + 11:W_PARTY_NICKS + 22] == DAMAGED[:7] + bytes([NAME_END]) + DAMAGED[8:]
    assert memory[W_PARTY_NICKS:W_PARTY_NICKS + 11] == CLEAN
    assert repair_party_nicknames(memory) == []


def test_raw_yellow_memory_is_repaired_at_its_shifted_addresses():
    memory = party(address)
    before = bytes(memory)
    assert repair_party_nicknames(memory, version='yellow') == [1]
    changed = [index for index, (old, new) in enumerate(zip(before, memory)) if old != new]
    assert changed == [address(W_PARTY_NICKS) + 11 + 7]


def test_only_the_party_count_of_nicknames_is_read_and_at_most_six():
    memory = party(lambda red: red)
    memory[W_PARTY_COUNT] = 1
    assert repair_party_nicknames(memory) == []
    # Empty slots hold 0x00, a text command, so a corrupt count repairs them too, but never a seventh.
    memory[W_PARTY_COUNT] = 0xFF
    memory[W_PARTY_NICKS + 6 * 11] = 0x01
    assert repair_party_nicknames(memory) == [1, 2, 3, 4, 5]
    assert memory[W_PARTY_NICKS + 6 * 11] == 0x01
