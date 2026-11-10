"""ROM-read game data and the randomizer override layer, on small synthetic cartridges."""
import pytest

from pokecore import romdata
from pokecore.romdata import Layout, gen1, gen2


class Rom:
    """Bank 1 of a two-bank cartridge, filled front to back. Addresses equal file offsets.
    Bank 0 holds only the header title, which ``romdata.load`` checks."""

    def __init__(self, title):
        self.data = bytearray(0x8000)
        self.data[0x134:0x134 + len(title)] = title.encode()
        self.at = 0x4000

    def put(self, raw):
        offset = self.at
        self.data[offset:offset + len(raw)] = bytes(raw)
        self.at += len(raw)
        return offset

    def words(self, count):
        return self.put(bytes(2 * count))

    def set_word(self, offset, value):
        self.data[offset:offset + 2] = value.to_bytes(2, 'little')


def name(text):
    return bytes(0x80 + ord(letter) - ord('A') for letter in text) + b'\x50'


def gen1_cartridge():
    rom = Rom('POKEMON RED')
    dex_order = rom.put([1, 2] + [0] * (gen1.INDEX_COUNT - 2))
    base_stats = rom.put([1, 45, 49, 49, 45, 65, 22, 3, 45, 64] + [0] * 5 + [33, 45, 0, 0, 3, 0b101] + [0] * 6 + [0]
                         + [2, 60, 62, 63, 60, 80, 22, 3, 45, 141] + [0] * 5 + [33, 45, 73, 0, 3, 0b100] + [0] * 6 + [0])
    names = rom.put(name('ALPHA').ljust(10, b'\x50') + name('BETA').ljust(10, b'\x50'))
    evos_moves = rom.words(gen1.INDEX_COUNT)
    rom.set_word(evos_moves, rom.put([1, 16, 2, 0, 7, 73, 0]))
    rom.set_word(evos_moves + 2, rom.put([0, 22, 75, 0]))
    tm_moves = rom.put(range(1, 56))
    wild = rom.words(4)
    grass = [level for slot in range(gen1.SLOTS) for level in (3 + slot, 1 + slot % 2)]
    rom.set_word(wild, rom.put([25, *grass, 0]))
    rom.set_word(wild + 2, rom.put([0, 5, *[20, 2] * gen1.SLOTS]))
    rom.set_word(wild + 4, rom.put([10, *[9, 2] * gen1.SLOTS, 0]))
    rom.set_word(wild + 6, 0xFFFF)
    trainers = rom.words(3)
    rom.set_word(trainers, rom.put([5, 1, 2, 0, 0xFF, 7, 1, 9, 2, 0]))
    # Class 2 has no parties, so it points at class 3's data.
    shared = rom.put([10, 2, 0])
    rom.set_word(trainers + 2, shared)
    rom.set_word(trainers + 4, shared)
    trainers_end = rom.at
    starter = rom.put([1])
    old_rod = rom.put([2, 5])
    good_rod = rom.put([10, 1, 12, 2])
    # Map 7 lists a second group, which the game never reaches.
    group = rom.put([3, 15, 1, 20, 2, 25, 1])
    other = rom.put([1, 30, 2])
    super_rod = rom.put([7, 0, 0, 7, 0, 0, 0xFF])
    rom.set_word(super_rod + 1, group)
    rom.set_word(super_rod + 4, other)
    found = Layout('red', 1, base_stats=base_stats, species_count=2, names=names, evos_moves=evos_moves,
                   tm_moves=tm_moves, tm_count=55, wild=(('wild', wild),), trainers=trainers, trainer_classes=3,
                   trainers_end=trainers_end, starters=((starter,),), dex_order=dex_order,
                   old_rod=old_rod, good_rod=good_rod, super_rod=super_rod)
    return bytes(rom.data), found


def gen2_cartridge():
    rom = Rom('POKEMON_GLDAAUE')
    record = [0, 45, 49, 65, 45, 49, 65, 22, 22, 45, 64, 0, 0, 31, 100, 20, 5] + [0] * 5 + [3, 0x17, 0b11] + [0] * 7
    base_stats = rom.put(record + record)
    names = rom.put(name('ALPHA').ljust(10, b'\x50') + name('BETA').ljust(10, b'\x50'))
    evos_moves = rom.words(2)
    rom.set_word(evos_moves, rom.put([5, 20, 1, 2, 4, 1, 2, 0, 1, 33, 0]))
    rom.set_word(evos_moves + 2, rom.put([0, 0]))
    tm_moves = rom.put(range(1, 61))
    grass = rom.put([1, 2, 10, 10, 10, *[3, 1] * gen2.GRASS_SLOTS, *[4, 2] * gen2.GRASS_SLOTS,
                     *[5, 1] * gen2.GRASS_SLOTS, 0xFF])
    water = rom.put([1, 3, 6, *[20, 2] * gen2.WATER_SLOTS, 0xFF])
    trainers = rom.words(3)
    rom.set_word(trainers, rom.put([*name('AB'), 3, 8, 1, 7, 33, 0, 0, 0, 0xFF, *name('C'), 0, 9, 2, 0xFF]))
    shared = rom.put([*name('D'), 2, 30, 2, 4, 0xFF])
    rom.set_word(trainers + 2, shared)
    rom.set_word(trainers + 4, shared)
    trainers_end = rom.at
    starter = rom.put([2])
    # Fish group 1 bites half the time. Its Super Rod's last slot is time group 1.
    old_rod = rom.put([0xB2, 1, 10, 0xFF, 2, 10])
    good_rod = rom.put([0xFF, 1, 20])
    super_rod = rom.put([0x7F, 2, 40, 0xFF, 0, 1])
    fish_groups = rom.put([0x80, 0, 0, 0, 0, 0, 0])
    for rod, table in enumerate((old_rod, good_rod, super_rod)):
        rom.set_word(fish_groups + 1 + 2 * rod, table)
    time_fish_groups = rom.put([1, 5, 2, 6, 1, 30, 2, 35])
    map_groups = rom.words(2)
    headers = [0] * 8 + [1] + [0] * 9
    rom.set_word(map_groups, rom.put(headers))
    rom.set_word(map_groups + 2, rom.put([0] * 8 + [1]))
    map_groups_end = rom.at
    found = Layout('gold', 2, base_stats=base_stats, species_count=2, names=names, evos_moves=evos_moves,
                   tm_moves=tm_moves, tm_count=60, wild=(('johto_grass', grass), ('johto_water', water)),
                   trainers=trainers, trainer_classes=3, trainers_end=trainers_end, starters=((starter, starter),),
                   fish_groups=fish_groups, fish_group_count=1, time_fish_groups=time_fish_groups,
                   map_groups=map_groups, map_group_count=2, map_groups_end=map_groups_end)
    return bytes(rom.data), found


@pytest.fixture
def red(monkeypatch):
    rom, found = gen1_cartridge()
    monkeypatch.setitem(romdata.LAYOUTS, 'red', found)
    return romdata.load(rom, version='red')


@pytest.fixture
def gold(monkeypatch):
    rom, found = gen2_cartridge()
    monkeypatch.setitem(romdata.LAYOUTS, 'gold', found)
    return romdata.load(rom, version='gold')


def test_gen1_tables(red):
    assert red.generation == 1
    assert red.species[1] == {'name': 'ALPHA', 'dex': 1, 'stats': [45, 49, 49, 45, 65], 'types': [22, 3],
                              'catch_rate': 45, 'base_exp': 64, 'start_moves': [33, 45, 0, 0], 'growth': 3,
                              'tmhm': [1, 3]}
    assert red.species[2]['tmhm'] == [3]
    assert red.evolutions == {1: [{'method': 'level', 'level': 16, 'species': 2}], 2: []}
    assert red.learnsets == {1: [[7, 73]], 2: [[22, 75]]}
    assert red.tm_moves == list(range(1, 56))
    assert sorted(red.encounters) == ['grass:0', 'grass:2', 'water:1']
    assert red.encounters['grass:0']['slots'][:2] == [[3, 1], [4, 2]]
    assert red.encounters['water:1'] == {'kind': 'water', 'map': 1, 'rate': 5, 'slots': [[20, 2]] * gen1.SLOTS}
    assert red.starters == [1]


def test_gen1_trainers_skip_classes_without_parties(red):
    assert red.trainers == {
        '1:1': {'class': 1, 'index': 1, 'party': [{'level': 5, 'species': 1}, {'level': 5, 'species': 2}]},
        '1:2': {'class': 1, 'index': 2, 'party': [{'level': 7, 'species': 1}, {'level': 9, 'species': 2}]},
        '3:1': {'class': 3, 'index': 1, 'party': [{'level': 10, 'species': 2}]},
    }


def test_gen2_tables(gold):
    assert gold.generation == 2
    assert gold.species[1]['name'] == 'ALPHA'
    assert gold.species[1]['stats'] == [45, 49, 65, 45, 49, 65]
    assert gold.species[1]['egg_groups'] == [1, 7]
    assert gold.species[1]['tmhm'] == [1, 2]
    assert gold.evolutions[1] == [{'method': 'stat', 'level': 20, 'stat': 1, 'species': 2},
                                  {'method': 'happiness', 'time': 1, 'species': 2}]
    assert gold.learnsets[1] == [[1, 33]]
    grass = gold.encounters['johto_grass:258']
    assert grass['rates'] == [10, 10, 10]
    assert grass['slots']['morn'][0] == [3, 1]
    assert grass['slots']['day'][0] == [4, 2]
    assert grass['slots']['nite'][0] == [5, 1]
    assert gold.encounters['johto_water:259']['slots'] == [[20, 2]] * 3
    assert gold.trainers['1:1'] == {'class': 1, 'index': 1, 'name': 'AB', 'type': 3,
                                    'party': [{'level': 8, 'species': 1, 'item': 7, 'moves': [33, 0, 0, 0]}]}
    assert gold.trainers['1:2']['party'] == [{'level': 9, 'species': 2}]
    assert '2:1' not in gold.trainers
    assert gold.trainers['3:1']['party'] == [{'level': 30, 'species': 2, 'item': 4}]
    assert gold.starters == [2]


def test_gen1_fishing(red):
    assert red.fishing_slots('old_rod', 3) == {'bite': 1.0, 'slots': [{'level': 5, 'species': 2, 'probability': 1.0}]}
    assert red.fishing_slots('good_rod', 0) == {'bite': 1 / 3, 'slots': [
        {'level': 10, 'species': 1, 'probability': 0.5}, {'level': 12, 'species': 2, 'probability': 0.5}]}
    hooked = red.fishing_slots('super_rod', 7)
    assert hooked['bite'] == 3 / 7
    assert [(slot['level'], slot['species']) for slot in hooked['slots']] == [(15, 1), (20, 2), (25, 1)]
    assert red.fishing_slots('super_rod', 0) is None
    with pytest.raises(ValueError, match='Unknown rod'):
        red.fishing_slots('old', 0)


def test_gen2_fishing(gold):
    assert gold.fish_groups == {257: 1, 513: 1}
    old = gold.fishing_slots('old_rod', 257)
    assert old == {'bite': 0.5, 'slots': [{'level': 10, 'species': 1, 'probability': 179 / 256},
                                          {'level': 10, 'species': 2, 'probability': 77 / 256}]}
    day = gold.fishing_slots('super_rod', 513)['slots']
    assert [(slot['level'], slot['species'], slot['probability']) for slot in day] == [(40, 2, 0.5), (30, 1, 0.5)]
    nite = gold.fishing_slots('super_rod', 513, time='nite')['slots']
    assert (nite[1]['level'], nite[1]['species']) == (35, 2)
    assert gold.fishing_slots('old_rod', 258) is None
    assert gold.fishing_slots('old_rod', 257, swarm='qwilfish') == old
    with pytest.raises(ValueError, match='Unknown time'):
        gold.fishing_slots('old_rod', 257, time='noon')


def test_fishing_survives_overrides(red, gold):
    for data in (red, gold):
        effective = data.with_overrides({'species_map': {1: 2, 2: 1}})
        assert (effective.fishing, effective.fish_groups) == (data.fishing, data.fish_groups)


def test_tables_without_fishing_load():
    data = romdata.GameData('red', {name: {} for name in ('species', 'evolutions', 'learnsets', 'encounters',
                                                            'trainers')} | {'tm_moves': [], 'starters': []})
    assert data.fishing == {} and data.fishing_slots('old_rod', 0) is None


def test_load_cached_reads_each_rom_once(monkeypatch):
    rom, found = gen1_cartridge()
    monkeypatch.setitem(romdata.LAYOUTS, 'red', found)
    first = romdata.load_cached(rom, version='red')
    assert romdata.load_cached(bytearray(rom), version='red') is first
    assert romdata.load_cached(rom[:-1] + b'\x01', version='red') is not first


@pytest.mark.parametrize('game', ['red', 'gold'])
def test_no_overrides_is_byte_identical(game, request):
    data = request.getfixturevalue(game)
    assert data.with_overrides({}).canonical() == data.canonical()
    assert data.with_overrides(None).canonical() == data.canonical()


def test_species_map_rewrites_placed_pokemon_only(red):
    before = red.canonical()
    effective = red.with_overrides({'species_map': {1: 2, 2: 1}})
    assert red.canonical() == before
    assert effective.starters == [2]
    assert effective.encounters['grass:0']['slots'][:2] == [[3, 2], [4, 1]]
    assert effective.trainers['3:1']['party'] == [{'level': 10, 'species': 1}]
    assert effective.evolutions == red.evolutions
    assert effective.species == red.species


def test_species_map_covers_every_time_of_day(gold):
    effective = gold.with_overrides({'species_map': {1: 2}})
    slots = effective.encounters['johto_grass:258']['slots']
    assert {slot[1] for time in slots.values() for slot in time} == {2}


def test_encounter_swap_and_field_override(red):
    effective = red.with_overrides({'species_map': {2: 1}, 'encounters': {'grass:0': 'grass:2',
                                                                           'water:1': {'rate': 9}}})
    assert effective.encounters['grass:0'] == {'kind': 'grass', 'map': 0, 'rate': 10, 'slots': [[9, 1]] * gen1.SLOTS}
    assert effective.encounters['water:1']['rate'] == 9


def test_explicit_entries_win_over_species_map(red):
    party = [{'level': 50, 'species': 2}]
    effective = red.with_overrides({'species_map': {2: 1}, 'trainers': {'3:1': {'party': party}},
                                    'starters': [2]})
    assert effective.trainers['3:1']['party'] == party
    assert effective.starters == [2]
    assert effective.trainers['1:1']['party'][1]['species'] == 1


def test_base_data_overrides(red):
    effective = red.with_overrides({'species': {1: {'stats': [1, 2, 3, 4, 5]}}, 'learnsets': {2: [[1, 1]]},
                                    'evolutions': {1: []}, 'tm_moves': [0] * 55})
    assert effective.species[1]['stats'] == [1, 2, 3, 4, 5]
    assert effective.learnsets[2] == [[1, 1]]
    assert effective.evolutions[1] == []
    assert effective.tm_moves == [0] * 55
    assert effective.overrides['tm_moves'] == [0] * 55


@pytest.mark.parametrize('overrides, message', [
    ({'moves': {}}, 'Unknown override keys'),
    ({'species_map': {1: 99}}, 'not a species'),
    ({'species': {1: {'colour': 1}}}, 'Unknown species fields'),
    ({'tm_moves': [1]}, 'needs 55 entries'),
    ({'starters': [1, 2]}, 'needs 1 entries'),
    ({'starters': [99]}, 'not a species'),
    ({'encounters': {'grass:0': 'water:1'}}, 'Cannot swap'),
    ({'encounters': {'grass:9': {'rate': 1}}}, 'Unknown encounters key'),
    ({'encounters': {'grass:0': {'map': 3}}}, 'cannot set'),
    ({'encounters': {'grass:0': {'slots': [[5, 99]]}}}, 'not a species'),
    ({'trainers': {'2:1': {'party': []}}}, 'Unknown trainers key'),
    ({'trainers': {'1:1': {'party': [{'level': 5, 'species': 0}]}}}, 'not a species'),
])
def test_invalid_overrides(red, overrides, message):
    with pytest.raises(ValueError, match=message):
        red.with_overrides(overrides)


def test_load_needs_a_known_cartridge_or_version():
    rom, _ = gen1_cartridge()
    with pytest.raises(ValueError, match='Unknown ROM'):
        romdata.load(rom)
    with pytest.raises(ValueError, match='No ROM layout'):
        romdata.load(rom, version='green')


@pytest.mark.parametrize('rom, title', [
    (bytes(0x8000), ''),
    (b'\0' * 0x134 + b'DEMO GAME' + bytes(0x8000), 'DEMO GAME'),
    (bytes(0x100), None),
    (gen1_cartridge()[0], 'POKEMON RED'),
])
def test_load_refuses_other_cartridges_before_reading(rom, title, monkeypatch):
    monkeypatch.setitem(romdata.LAYOUTS, 'gold', gen2_cartridge()[1])
    for version in (None, 'gold'):
        with pytest.raises(romdata.UnsupportedCartridge) as refused:
            romdata.load(rom, version=version)
        assert refused.value.title == title
    assert issubclass(romdata.UnsupportedCartridge, ValueError)


@pytest.fixture
def red_rom(monkeypatch):
    rom, found = gen1_cartridge()
    monkeypatch.setitem(romdata.LAYOUTS, 'red', found)
    return rom


@pytest.fixture
def gold_rom(monkeypatch):
    rom, found = gen2_cartridge()
    monkeypatch.setitem(romdata.LAYOUTS, 'gold', found)
    return rom


@pytest.mark.parametrize('game', ['red', 'gold'])
def test_patch_without_overrides_returns_the_rom(game, request):
    rom = request.getfixturevalue(f'{game}_rom')
    assert romdata.patch_rom(rom, version=game) == rom
    assert romdata.patch_rom(rom, {}, version=game) == rom


@pytest.mark.parametrize('game, overrides', [
    ('red', {'species_map': {1: 2, 2: 1}}),
    ('red', {'encounters': {'grass:0': 'grass:2', 'water:1': {'rate': 9}}, 'starters': [2],
             'trainers': {'1:2': {'party': [{'level': 40, 'species': 2}, {'level': 41, 'species': 2}]}}}),
    ('gold', {'species_map': {1: 2, 2: 1}, 'tm_moves': list(range(60, 0, -1))}),
    ('gold', {'encounters': {'johto_grass:258': {'rates': [5, 6, 7]}},
              'trainers': {'1:1': {'party': [{'level': 9, 'species': 2, 'item': 1, 'moves': [1, 2, 3, 4]}]}}}),
])
def test_patch_reads_back_as_the_effective_data(game, overrides, request):
    rom = request.getfixturevalue(f'{game}_rom')
    patched = romdata.patch_rom(rom, overrides, version=game)
    assert patched != rom
    assert len(patched) == len(rom)
    expected = romdata.effective_data(rom, overrides, version=game)
    assert romdata.load(patched, version=game).canonical() == expected.canonical()
    assert int.from_bytes(patched[0x14E:0x150], 'big') == (sum(patched) - patched[0x14E] - patched[0x14F]) & 0xFFFF


def test_patch_leaves_the_input_unchanged(red_rom):
    rom = bytearray(red_rom)
    romdata.patch_rom(rom, {'starters': [2]}, version='red')
    assert bytes(rom) == red_rom


@pytest.mark.parametrize('game, overrides, message', [
    ('red', {'trainers': {'1:1': {'party': [{'level': 5, 'species': 1}]}}}, 'is 3 bytes, the ROM holds 4'),
    ('red', {'trainers': {'3:1': {'party': [{'level': 11, 'species': 2}]}}}, 'levels cannot change'),
    ('red', {'learnsets': {1: []}}, 'cannot write learnsets'),
    ('gold', {'trainers': {'1:2': {'name': 'Z'}}}, 'cannot change a trainer name'),
    ('gold', {'trainers': {'3:1': {'party': [{'level': 30, 'species': 2}]}}}, 'need exactly'),
    ('gold', {'encounters': {'johto_water:259': {'slots': [[1, 1]]}}}, 'needs 3 slots'),
])
def test_patch_refuses_changes_that_do_not_fit(game, overrides, message, request):
    rom = request.getfixturevalue(f'{game}_rom')
    with pytest.raises(ValueError, match=message):
        romdata.patch_rom(rom, overrides, version=game)


def test_maps_sharing_a_table_must_agree(red_rom):
    rom = bytearray(red_rom)
    found = romdata.LAYOUTS['red']
    wild = found.wild[0][1]
    rom[wild + 4:wild + 6] = rom[wild:wild + 2]
    data = romdata.load(rom, version='red')
    assert data.encounters['grass:2']['slots'] == data.encounters['grass:0']['slots']
    patched = romdata.patch_rom(rom, {'species_map': {1: 2}}, version='red')
    assert romdata.load(patched, version='red').encounters['grass:2']['slots'][0] == [3, 2]
    with pytest.raises(ValueError, match='shares its ROM table'):
        romdata.patch_rom(rom, {'encounters': {'grass:2': {'rate': 1}}}, version='red')


def test_layouts_cover_every_supported_version():
    assert sorted(romdata.LAYOUTS) == ['blue', 'crystal', 'gold', 'red', 'silver', 'yellow']
    assert romdata.rom_offset(0x0E, 0x43DE) == 0x383DE
    assert romdata.rom_offset(0, 0x0150) == 0x0150
