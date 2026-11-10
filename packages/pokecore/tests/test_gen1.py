import pytest

from pokecore import gen1


class ReadOnlyMemory:
    def __init__(self, data):
        self.data = bytes(data)

    def __getitem__(self, item):
        return self.data[item]


@pytest.fixture
def memory():
    raw = bytearray(65536)
    raw[gen1.W_PARTY_COUNT] = 1
    block = bytearray(44)
    block[0] = 84
    block[1:3] = (28).to_bytes(2, "big")
    block[4:6] = bytes((8, 20))
    block[8:12] = bytes((33, 45, 0, 0))
    block[12:14] = (1234).to_bytes(2, "big")
    block[14:17] = (1000).to_bytes(3, "big")
    block[17:19] = (256).to_bytes(2, "big")
    block[27:29] = bytes((0xAB, 0xCD))
    block[29:33] = bytes((0xC5, 12, 0, 0))
    block[33] = 10
    block[34:36] = (35).to_bytes(2, "big")
    block[36:44] = bytes((0, 15, 0, 18, 0, 20, 0, 22))
    raw[gen1.W_PARTY_MONS:gen1.W_PARTY_MONS + 44] = block
    raw[gen1.W_PARTY_NICKS:gen1.W_PARTY_NICKS + 4] = bytes((0x80, 0xA1, 0xEF, 0x50))
    return raw


def test_party_numeric_fields_dvs_and_pp(memory):
    result = gen1.read_party(ReadOnlyMemory(memory), {33: {"pp": 35}, 45: {"pp": 40}})
    assert len(result) == 1
    assert result[0] == {
        "species": 84, "hp": 28, "max_hp": 35, "level": 10, "nick": "Ab♂", "status": 8,
        "types": (20, 0), "moves": (33, 45, 0, 0), "pp": (5, 12, 0, 0),
        "attack": 15, "defense": 18, "speed": 20, "special": 22,
        "experience": 1000, "max_pp": (56, 40, 0, 0), "trainer_id": 1234,
        "dvs": (5, 10, 11, 12, 13), "stat_exp": (256, 0, 0, 0, 0),
    }


def test_pending_party_slots_are_preserved(memory):
    memory[gen1.W_PARTY_COUNT] = 2
    rows = gen1.read_party(memory)
    assert len(rows) == 2
    assert rows[1]["species"] == 0
    assert rows[1]["level"] == 0
    assert rows[0]["max_pp"] == (0, 0, 0, 0)


def test_corrupt_party_and_bag_counts_are_bounded(memory):
    memory[gen1.W_PARTY_COUNT] = 255
    memory[gen1.W_NUM_BAG_ITEMS] = 255
    for index in range(20):
        memory[gen1.W_BAG_ITEMS + index * 2:gen1.W_BAG_ITEMS + index * 2 + 2] = bytes((4, index + 1))
    assert len(gen1.read_party(memory)) == 6
    assert len(gen1.read_bag(memory)) == 20
    assert gen1.read_bag(memory)[-1] == (4, 20)


def test_bag_skips_empty_and_terminator_ids(memory):
    memory[gen1.W_NUM_BAG_ITEMS] = 3
    memory[gen1.W_BAG_ITEMS:gen1.W_BAG_ITEMS + 6] = bytes((0, 5, 255, 2, 4, 9))
    assert gen1.read_bag(ReadOnlyMemory(memory)) == ((4, 9),)


def test_empty_bag_does_not_request_an_empty_pyboy_slice(memory):
    class PyBoyStyleMemory(ReadOnlyMemory):
        def __getitem__(self, item):
            if isinstance(item, slice) and item.start >= item.stop:
                raise ValueError("Start address has to come before end address")
            return super().__getitem__(item)
    memory[gen1.W_NUM_BAG_ITEMS] = 0
    assert gen1.read_bag(PyBoyStyleMemory(memory)) == ()


@pytest.mark.parametrize("data,expected", [
    (bytes((0x80, 0x99, 0x7F, 0xA0, 0xB9, 0xF6, 0xFF, 0x50, 0x80)), "AZ az09"),
    (bytes((0xBA, 0xEF, 0xF5, 0xE0, 0xE3)), "é♂♀'-"),
    (bytes((0x80, 0, 0x81)), "A"),
    (bytes((0x80, 0x70, 0x01, 0x81)), "A?B"),
    (bytes((0xE1, 0xE2, 0xF0, 0xF1)), "PKMN$×"),
])
def test_cartridge_text(data, expected):
    assert gen1.decode_text(data) == expected


def test_bcd_and_flag_index_conventions():
    assert gen1.bcd(bytes((0x12, 0x34, 0x56))) == 123456
    assert gen1.flag_bits(bytes((0x81, 0x02))) == {1, 8, 10}
    assert gen1.event_set(bytes((0x81, 0x02)), 0)
    assert gen1.event_set(bytes((0x81, 0x02)), 9)
    assert not gen1.event_set(bytes((0x81, 0x02)), 8)


@pytest.mark.parametrize("index", [-1, 16, True, 1.5])
def test_event_index_bounds(index):
    with pytest.raises(ValueError):
        gen1.event_set(bytes(2), index)


def test_progress_reads_flags_without_awarding_points(memory):
    memory[gen1.W_BADGES] = 1
    memory[gen1.W_CUR_MAP] = 118
    memory[gen1.W_HALL_OF_FAME_COUNT] = 1
    for index in (119, 2273, 2305, 34):
        memory[gen1.W_EVENT_FLAGS + index // 8] |= 1 << (index % 8)
    original = bytes(memory)
    result = gen1.read_progress(ReadOnlyMemory(memory))
    assert result["valid"]
    assert result["gym_flags"] == [True] + [False] * 7
    assert result["elite"]["Lorelei"]
    assert result["champion"]
    assert result["story"]["starter"]
    assert "score" not in result
    assert "complete" not in result
    assert bytes(memory) == original


def test_progress_does_not_accept_empty_or_incomplete_party(memory):
    memory[gen1.W_PARTY_COUNT] = 0
    assert not gen1.read_progress(memory)["valid"]
    memory[gen1.W_PARTY_COUNT] = 1
    memory[gen1.W_PARTY_MONS] = 0
    assert not gen1.read_progress(memory)["valid"]


def test_named_addresses_match_pret_pokered():
    assert (gen1.W_FACING, gen1.W_WALK_COUNTER, gen1.W_WHICH_POKEMON, gen1.W_MOVE_NUM) == (0xC109, 0xCFC5, 0xCF92, 0xD0E0)
    assert (gen1.W_PLAYER_DISABLED_MOVE, gen1.W_WALK_BIKE_SURF_STATE) == (0xD06D, 0xD700)
    assert (gen1.W_STATUS_FLAGS1, gen1.W_MOVEMENT_FLAGS) == (0xD728, 0xD736)
    assert gen1.W_SPRITE_STATE_DATA2 + gen1.SPRITE_STRUCT + gen1.SPRITE_MAP_Y == 0xC214
    assert gen1.FACINGS[4] == 'up'


def test_sprite_tile_reads_the_map_block_position():
    raw = bytearray(65536)
    raw[0xC214], raw[0xC215] = 9, 14
    raw[0xC204], raw[0xC205] = 4, 5
    assert gen1.sprite_tile(raw, 1) == (10, 5)
    assert gen1.sprite_tile(raw, 0) == (1, 0)
    # Sprite data sits below the Yellow shift, so the raw Yellow bytes are the same.
    assert gen1.sprite_tile(raw, 1, version='yellow') == (10, 5)


def test_named_addresses_read_yellow_through_the_red_layout():
    from pokecore.yellow import red_layout
    raw = bytearray(65536)
    raw[0xCFC4], raw[0xD6FF], raw[0xD735] = 3, 2, 0x80
    view = red_layout(raw, 'yellow')
    assert view[gen1.W_WALK_COUNTER] == 3 and view[gen1.W_WALK_BIKE_SURF_STATE] == 2
    assert view[gen1.W_MOVEMENT_FLAGS] & 1 << gen1.BIT_SPINNING
