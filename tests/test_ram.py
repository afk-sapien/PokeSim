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


def test_a_headless_read_ends_a_damaged_nickname_that_comes_into_the_party():
    from types import SimpleNamespace
    from pokesim.adapter import Gen1Adapter
    from pokesim.ram import W_PARTY_COUNT, W_PARTY_NICKS
    damaged = bytes([0x96, 0x84, 0x93, 0x85, 0x94, 0x8D, 0x83, 0x51, 0x8B, 0x8B, 0x50])
    memory = bytearray(0x10000)
    memory[W_PARTY_COUNT] = 1
    memory[W_PARTY_NICKS:W_PARTY_NICKS + 11] = damaged
    adapter = Gen1Adapter.__new__(Gen1Adapter)
    adapter.last = None
    run = SimpleNamespace(pb=SimpleNamespace(memory=memory), frame=0)
    assert [mon.nick for mon in adapter.read(run).party] == ['WETFUND']
    # A withdraw brings a stored nickname whose terminator rose to a text command into the party.
    memory[W_PARTY_COUNT] = 2
    memory[W_PARTY_NICKS + 11:W_PARTY_NICKS + 22] = damaged
    assert [mon.nick for mon in adapter.read(run).party] == ['WETFUND', 'WETFUND']
    assert memory[W_PARTY_NICKS + 11 + 7] == 0x50


def test_a_headless_read_resets_a_box_level_in_the_enemy_party_slot_when_a_wild_battle_starts():
    from types import SimpleNamespace
    from pokecore.repairs import W_ENEMY_MON_PARTY_POS
    from pokesim.adapter import Gen1Adapter
    from pokesim.ram import W_IS_IN_BATTLE
    memory = bytearray(0x10000)
    adapter = Gen1Adapter.__new__(Gen1Adapter)
    adapter.last = None
    run = SimpleNamespace(pb=SimpleNamespace(memory=memory), frame=0)
    # A catch with a full party sent a level 34 Pokémon to a box.
    memory[W_ENEMY_MON_PARTY_POS] = 0x22
    adapter.read(run)
    assert memory[W_ENEMY_MON_PARTY_POS] == 0x22
    memory[W_IS_IN_BATTLE] = 1
    adapter.read(run)
    assert memory[W_ENEMY_MON_PARTY_POS] == 0
    # Only the first read of the battle writes, so a catch later in it keeps the level it stores.
    memory[W_ENEMY_MON_PARTY_POS] = 0x22
    adapter.read(run)
    assert memory[W_ENEMY_MON_PARTY_POS] == 0x22
    memory[W_IS_IN_BATTLE] = 0
    adapter.read(run)
    memory[W_IS_IN_BATTLE] = 1
    adapter.read(run)
    assert memory[W_ENEMY_MON_PARTY_POS] == 0
    # A save loaded in a wild battle is the start of one.
    memory[W_ENEMY_MON_PARTY_POS] = 0x22
    adapter.after_load(run, {'run_memory': {}}, False)
    adapter.read(run)
    assert memory[W_ENEMY_MON_PARTY_POS] == 0


def test_yellow_resets_the_enemy_party_slot_at_its_shifted_address():
    from types import SimpleNamespace
    from pokecore.yellow import RedLayoutMemory
    from pokesim.adapter import Gen1Adapter
    # The Yellow emulator gives the app this Red-layout view of its memory.
    raw = bytearray(0x10000)
    raw[0xD056] = 1    # wIsInBattle, Red's 0xD057
    raw[0xCFE7] = 0x22
    before = bytes(raw)
    adapter = Gen1Adapter.__new__(Gen1Adapter)
    adapter.last = None
    adapter.read(SimpleNamespace(pb=SimpleNamespace(memory=RedLayoutMemory(raw)), frame=0))
    assert [i for i, (old, new) in enumerate(zip(before, raw)) if old != new] == [0xCFE7]
    assert raw[0xCFE7] == 0
