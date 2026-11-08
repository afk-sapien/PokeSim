"""Repairs to Gen I party memory."""


def test_a_party_nickname_with_a_text_command_ends_there():
    from pokesim.ram import W_PARTY_COUNT, W_PARTY_NICKS, repair_party_nicknames
    memory = bytearray(0x10000)
    memory[W_PARTY_COUNT] = 2
    # Live bytes: WETFUND, then the 0x55 text command where the terminator belonged, then LL.
    damaged = bytes([0x96, 0x84, 0x93, 0x85, 0x94, 0x8D, 0x83, 0x55, 0x8B, 0x8B, 0x50])
    clean = bytes([0x91, 0x84, 0x83, 0x50]).ljust(11, b'\x50')
    memory[W_PARTY_NICKS:W_PARTY_NICKS + 11] = clean
    memory[W_PARTY_NICKS + 11:W_PARTY_NICKS + 22] = damaged
    assert repair_party_nicknames(memory) == [1]
    assert memory[W_PARTY_NICKS + 11 + 7] == 0x50
    assert memory[W_PARTY_NICKS:W_PARTY_NICKS + 11] == clean
    assert repair_party_nicknames(memory) == []
