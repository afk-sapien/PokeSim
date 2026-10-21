"""Yellow memory exposes Red addresses so one snapshot reader serves every Gen 1 cartridge."""
import pytest

from pokesim import yellow


class Raw:
    def __init__(self):
        self.data = bytearray(65536)

    def __getitem__(self, key):
        if isinstance(key, tuple):
            return ('raw', key)
        return self.data[key]

    def __setitem__(self, key, value):
        if isinstance(key, tuple):
            self.banked = (key, value)
            return
        self.data[key] = value

    def read_bytes(self, start, stop):
        return bytes(self.data[start:stop])


class Owner:
    def __init__(self):
        self.raw_memory = Raw()


def machine(red):
    """A Yellow emulator stand-in whose raw RAM holds the Red-layout bytes `red` at Yellow addresses."""
    from types import SimpleNamespace
    owner = Owner()
    owner.raw_memory.data[:] = red
    for a in [*range(0xC000, 0xE000), *yellow._HRAM]:
        owner.raw_memory.data[yellow.address(a)] = red[a]
    return SimpleNamespace(memory=yellow.YellowMemory(owner), raw_memory=owner.raw_memory)


@pytest.fixture
def memory():
    return yellow.YellowMemory(Owner())


def test_shifted_wram_reads_one_byte_lower(memory):
    memory.raw.data[0xD162] = 3   # Yellow wPartyCount
    memory.raw.data[0xD35D] = 0x26   # Yellow wCurMap
    assert memory[0xD163] == 3
    assert memory[0xD35E] == 0x26
    assert yellow.address(0xCF1A) == 0xCF1A
    assert yellow.address(0xCF1B) == 0xCF1A
    assert yellow.address(0xDEE1) == 0xDEE0


def test_stack_and_low_wram_stay_raw(memory):
    memory.raw.data[0xC109] = 4
    memory.raw.data[0xDF00] = 9
    assert memory[0xC109] == 4
    assert memory[0xDF00] == 9


def test_hram_fields_move(memory):
    for red, raw in {0xFFF4: 0xFFF9, 0xFFF6: 0xFFFA, 0xFFF7: 0xFFFB, 0xFFF8: 0xFFF5, 0xFFF9: 0xFFF8}.items():
        memory.raw.data[raw] = red & 0xFF
        assert memory[red] == red & 0xFF
    assert memory[0xFF80] == 0


def test_ranges_match_single_reads(memory):
    for offset in range(0xCF00, 0xCF40):
        memory.raw.data[offset] = offset & 0xFF
    for offset in range(0xFFF0, 0x10000):
        memory.raw.data[offset] = offset & 0x7F
    span = memory[0xCF10:0xCF30]
    assert span == [memory[i] for i in range(0xCF10, 0xCF30)]
    assert span[0xCF1B - 0xCF10] == 0x1A
    assert memory.read_bytes(0xFFF0, 0x10000) == bytes(memory[i] for i in range(0xFFF0, 0x10000))


def test_writes_land_on_yellow_addresses(memory):
    memory[0xD163] = 2
    assert memory.raw.data[0xD162] == 2
    memory[0xD16B:0xD16D] = [7, 8]
    assert memory.raw.data[0xD16A:0xD16C] == bytearray([7, 8])
    memory[0xFFF8] = 5
    assert memory.raw.data[0xFFF5] == 5


def test_banked_rom_and_cartridge_ram_pass_through(memory):
    assert memory[0, 0x3FF0] == ('raw', (0, 0x3FF0))
    assert memory[1, 0xA598] == ('raw', (1, 0xA598))
    memory.raw.data[0xD162] = 6
    assert memory[0, 0xD163] == 6
    memory[1, 0xA000] = 1
    assert memory.raw.banked == ((1, 0xA000), 1)


def test_snapshot_reads_pikachu_happiness(memory):
    from pokesim.ram import read_snapshot
    memory.raw.data[yellow.PIKACHU_HAPPINESS] = 147
    assert read_snapshot(memory, 0).pikachu_happiness == 147


def test_open_emulator_keeps_core_class_for_other_cartridges(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(yellow, 'YellowEmulator', lambda rom, **kw: seen.append('yellow'))
    rom = tmp_path / 'other.gb'
    rom.write_bytes(b'\0' * 32)
    yellow.open_emulator(rom, default=lambda rom, **kw: seen.append('core'), window='null')
    assert seen == ['core']
    assert not yellow.is_yellow(rom)


# (Core constant, Red address, Yellow address) from the pret pokered and pokeyellow symbol files.
CORE_FIELDS = [
    ('W_TILEMAP', 0xC3A0, 0xC3A0),
    ('W_FACING', 0xC109, 0xC109),
    ('W_SPRITE_STATE_DATA2', 0xC200, 0xC200),
    ('W_WHICH_POKEMON', 0xCF92, 0xCF91),
    ('W_WALK_COUNTER', 0xCFC5, 0xCFC4),
    ('W_ENEMY_SPECIES2', 0xCFD8, 0xCFD7),
    ('W_ENEMY_MON', 0xCFE5, 0xCFE4),
    ('W_ENEMY_LEVEL', 0xCFF3, 0xCFF2),
    ('W_TRAINER_CLASS', 0xD031, 0xD030),
    ('W_IS_IN_BATTLE', 0xD057, 0xD056),
    ('W_CUR_OPPONENT', 0xD059, 0xD058),
    ('W_BATTLE_TYPE', 0xD05A, 0xD059),
    ('W_PLAYER_DISABLED_MOVE', 0xD06D, 0xD06C),
    ('W_MOVE_NUM', 0xD0E0, 0xD0DF),
    ('W_PLAYER_NAME', 0xD158, 0xD157),
    ('W_PARTY_COUNT', 0xD163, 0xD162),
    ('W_PARTY_SPECIES', 0xD164, 0xD163),
    ('W_PARTY_MONS', 0xD16B, 0xD16A),
    ('W_PARTY_OT', 0xD273, 0xD272),
    ('W_PARTY_NICKS', 0xD2B5, 0xD2B4),
    ('W_DEX_OWNED', 0xD2F7, 0xD2F6),
    ('W_DEX_SEEN', 0xD30A, 0xD309),
    ('W_NUM_BAG_ITEMS', 0xD31D, 0xD31C),
    ('W_BAG_ITEMS', 0xD31E, 0xD31D),
    ('W_MONEY', 0xD347, 0xD346),
    ('W_RIVAL_NAME', 0xD34A, 0xD349),
    ('W_BADGES', 0xD356, 0xD355),
    ('W_PLAYER_ID', 0xD359, 0xD358),
    ('W_CUR_MAP', 0xD35E, 0xD35D),
    ('W_Y', 0xD361, 0xD360),
    ('W_X', 0xD362, 0xD361),
    ('W_CURRENT_BOX', 0xD5A0, 0xD59F),
    ('W_TOGGLE_OBJECT_FLAGS', 0xD5A6, 0xD5A5),
    ('W_WALK_BIKE_SURF_STATE', 0xD700, 0xD6FF),
    ('W_RIVAL_STARTER', 0xD715, 0xD714),
    ('W_PLAYER_STARTER', 0xD717, 0xD716),
    ('W_STATUS_FLAGS1', 0xD728, 0xD727),
    ('W_MOVEMENT_FLAGS', 0xD736, 0xD735),
    ('W_EVENT_FLAGS', 0xD747, 0xD746),
    ('W_PLAYTIME_H', 0xDA41, 0xDA40),
    ('W_BOX_COUNT', 0xDA80, 0xDA7F),
]

# Literal addresses modules read without a Core name.
LITERAL_FIELDS = [
    ('wCurItem', 0xCF91, 0xCF90),
    ('wItemQuantity', 0xCF96, 0xCF95),
    ('wEnemyMonHP', 0xCFE6, 0xCFE5),
    ('wEnemyMonDVs', 0xCFF1, 0xCFF0),
    ('wEnemyMonMaxHP', 0xCFF4, 0xCFF3),
    ('wCriticalHitOrOHKO', 0xD05E, 0xD05D),
    ('wEnemyBattleStatus3', 0xD069, 0xD068),
    ('wCapturedMonSpecies', 0xD11C, 0xD11B),
    ('wLinkState', 0xD12B, 0xD12A),
    ('wOptions', 0xD355, 0xD354),
    ('wMapMusicSoundID', 0xD35B, 0xD35A),
    ('wNumHoFTeams', 0xD5A2, 0xD5A1),
    ('wPlayerCoins', 0xD5A4, 0xD5A3),
    ('wCompletedInGameTradeFlags', 0xD737, 0xD736),
]

# Outside the window: OAM buffers, the tile map, menu state and the stack.
UNCHANGED = [0xC000, 0xC214, 0xC215, 0xCC24, 0xCC25, 0xCC26, 0xCC28, 0xCC2F, 0xCC36,
             0xCD0F, 0xCD12, 0xCF18, 0xCF1A, 0xDEE2, 0xDF00, 0xDFFF]


@pytest.mark.parametrize('name, red, raw', CORE_FIELDS, ids=[row[0] for row in CORE_FIELDS])
def test_every_core_address_maps_to_its_yellow_symbol(name, red, raw):
    from pokesim_core import gen1
    assert getattr(gen1, name) == red
    assert yellow.address(red) == raw


@pytest.mark.parametrize('name, red, raw', LITERAL_FIELDS, ids=[row[0] for row in LITERAL_FIELDS])
def test_literal_addresses_map_to_their_yellow_symbol(name, red, raw):
    assert yellow.address(red) == raw


@pytest.mark.parametrize('red', UNCHANGED, ids=hex)
def test_addresses_outside_the_window_are_unchanged(red):
    assert yellow.address(red) == red


def test_window_edges_are_exact():
    assert [yellow.address(a) for a in (0xCF1A, 0xCF1B, 0xDEE1, 0xDEE2)] == [0xCF1A, 0xCF1A, 0xDEE0, 0xDEE2]
    shifted = [a for a in range(0xC000, 0xE000) if yellow.address(a) != a]
    assert shifted == list(range(0xCF1B, 0xDEE2))
    assert all(yellow.address(a) == a - 1 for a in shifted)


def test_ram_module_reads_the_core_addresses():
    from pokesim import ram
    for name, red, _ in CORE_FIELDS:
        if hasattr(ram, name):
            assert getattr(ram, name) == red, name


def red_and_yellow_games():
    """One save laid out as Red, and the same bytes in Yellow's shifted layout."""
    from test_trade_save import ABRA, MACHOKE, Memory, entry, populate
    from pokesim import ram
    from pokesim.trade import boxes

    class YellowRaw(Memory):
        def read_bytes(self, start, stop):
            return bytes(self.flat[start:stop])

    red = populate(Memory(), active=2, contents=((1, ABRA, 30), (2, MACHOKE, 41), (7, ABRA, 12)))
    slot = entry(0x99, 20)
    red[ram.W_PARTY_COUNT] = 1
    red[ram.W_PARTY_SPECIES:ram.W_PARTY_SPECIES + 2] = [0x99, 0xFF]
    red[ram.W_PARTY_MONS:ram.W_PARTY_MONS + 33] = slot.struct
    red[ram.W_PARTY_MONS + 33] = 20
    red[0xD273:0xD273 + 11] = slot.ot_name
    red[ram.W_PARTY_NICKS:ram.W_PARTY_NICKS + 11] = slot.nickname
    red[ram.W_PLAYER_NAME:ram.W_PLAYER_NAME + 11] = boxes.encode_text('SKYE')
    red[ram.W_RIVAL_NAME:ram.W_RIVAL_NAME + 11] = boxes.encode_text('GARY')
    red[ram.W_NUM_BAG_ITEMS] = 2
    red[ram.W_BAG_ITEMS:ram.W_BAG_ITEMS + 5] = [0x04, 5, 0x14, 3, 0xFF]
    red[ram.W_MONEY:ram.W_MONEY + 3] = [0x01, 0x23, 0x45]
    red[ram.W_BADGES] = 0b00010111
    red[ram.W_CUR_MAP] = 0x26
    red[ram.W_Y], red[ram.W_X] = 6, 9
    red[ram.W_DEX_OWNED] = red[ram.W_DEX_SEEN] = 0b101
    red[ram.W_DEX_SEEN + 4] = 0x80
    red[ram.W_PLAYER_ID:ram.W_PLAYER_ID + 2] = [0x12, 0x34]
    red[0xD5A2] = 3
    red[0xD5A4:0xD5A6] = [0x09, 0x99]
    red[ram.W_PLAYTIME_H], red[ram.W_PLAYTIME_H + 2], red[ram.W_PLAYTIME_H + 3] = 12, 34, 56
    red[ram.W_TOGGLE_OBJECT_FLAGS + 3] = 0x40
    red[ram.W_EVENT_FLAGS + 0x120] = 0x02
    red[ram.W_EVENT_FLAGS + 0x13F] = 0x81
    raw = YellowRaw()
    raw.flat[:] = red.flat
    for a in range(0xC000, 0xE000):
        raw.flat[yellow.address(a)] = red.flat[a]
    raw.banks = {bank: bytearray(data) for bank, data in red.banks.items()}

    class Owner:
        raw_memory = raw

    return red, yellow.YellowMemory(Owner())


def test_snapshot_of_a_shifted_save_matches_red():
    from dataclasses import replace
    from pokesim.ram import read_snapshot
    red, memory = red_and_yellow_games()
    expected, actual = read_snapshot(red, 7), read_snapshot(memory, 7)
    assert len(actual.party) == 1 and actual.party[0].species == 0x99
    assert (actual.money, actual.coins, actual.badges) == (12345, 999, 0b00010111)
    assert (actual.map, actual.x, actual.y, actual.hall_of_fame_count) == (0x26, 9, 6, 3)
    assert (actual.player_name, actual.rival_name, actual.playtime) == ('SKYE', 'GARY', (12, 34, 56))
    assert actual.player_id == 0x1234 and actual.active_box == 1 and len(actual.items) == 2
    assert actual.event_flags[0x120] == 0x02 and actual.hidden_objects[3] == 0x40
    assert actual.box_counts[:7] == (1, 1, 0, 0, 0, 0, 1)
    assert replace(actual, pikachu_happiness=expected.pikachu_happiness) == expected


def test_box_and_party_writes_through_yellow_memory_land_on_yellow_addresses():
    from test_trade_save import MACHOKE, entry
    from pokesim.trade import boxes
    _, memory = red_and_yellow_games()
    boxes.write_slot(memory, 2, 2, entry(MACHOKE, 44))
    assert memory.raw.flat[0xDA7F] == 2
    assert memory.raw.flat[0xDA7F + 2] == MACHOKE
    assert memory.raw.flat[0xDA80 + 2] == 0xFF
    assert boxes.read_slot(memory, 2, 2).level == 44
    boxes.write_slot(memory, 7, 2, entry(MACHOKE, 45))
    assert boxes.read_slot(memory, 7, 2).level == 45
    assert memory.raw.banks[3][0x0001 + 1] == MACHOKE   # box 7 is the first box in bank 3
