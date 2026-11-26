"""Named repairs of damaged Gen I memory."""
import pytest

from pokecore.gen1 import W_IS_IN_BATTLE, W_PARTY_COUNT, W_PARTY_NICKS
from pokecore.repairs import NAME_END, W_ENEMY_MON_PARTY_POS, repair_party_nicknames, reset_wild_enemy_party_pos
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


def battle(locate, in_battle, party_pos):
    memory = bytearray(0x10000)
    memory[locate(W_IS_IN_BATTLE)] = in_battle
    memory[locate(W_ENEMY_MON_PARTY_POS)] = party_pos
    return memory


@pytest.mark.parametrize('version, at', [(None, 0xCFE8), ('red', 0xCFE8), ('blue', 0xCFE8), ('yellow', 0xCFE7)])
def test_a_box_level_left_in_the_enemy_party_slot_is_reset_in_a_wild_battle(version, at):
    locate = address if version == 'yellow' else (lambda red: red)
    # A level 34 Pokémon sent to a box after a catch with a full party.
    memory = battle(locate, 1, 0x22)
    before = bytes(memory)
    assert locate(W_ENEMY_MON_PARTY_POS) == at
    assert reset_wild_enemy_party_pos(memory, version=version) == 0x22
    assert [i for i, (old, new) in enumerate(zip(before, memory)) if old != new] == [at]
    assert memory[at] == 0
    assert reset_wild_enemy_party_pos(memory, version=version) is None


@pytest.mark.parametrize('in_battle, party_pos', [(0, 0x22), (2, 0x22), (0xFF, 0x22), (1, 5), (1, 0)])
def test_the_enemy_party_slot_is_kept_outside_a_wild_battle_or_inside_the_party(in_battle, party_pos):
    # A trainer battle sets the slot itself, and 0 to 5 index the six enemy party slots.
    memory = battle(lambda red: red, in_battle, party_pos)
    before = bytes(memory)
    assert reset_wild_enemy_party_pos(memory) is None
    assert bytes(memory) == before
