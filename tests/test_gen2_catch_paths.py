"""Gen 2 catch paths: Unown letters, contest-only species and the roaming beasts' movement rule."""
from types import SimpleNamespace

from pokesim.gen2 import collection, contest, quests

SYMBOLS = {'wUnlockedUnowns': (1, 0xD000), 'wUnownDex': (1, 0xD010), 'wRoamMons_LastMapGroup': (1, 0xD040),
           'wRoamMons_LastMapNumber': (1, 0xD041), 'wCurDay': (1, 0xD050), 'wDailyFlags1': (1, 0xD051)}


class RAM:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def __getitem__(self, key):
        _, window = key
        return [self.values.get(address, 0) for address in range(window.start, window.stop)]


def letter_dvs(letter):
    """Smallest DV bytes that give an Unown letter, built by inverting GetUnownLetter."""
    value = (letter - 1) * 10
    first = ((value >> 1) & 0x60) | ((value >> 3) & 0x06)
    second = ((value << 3) & 0x60) | ((value << 1) & 0x06)
    return first, second


def test_unown_letters_follow_the_cartridge_formula():
    assert collection.unown_letter((0, 0)) == 1
    assert collection.unown_letter((0xFF, 0xFF)) == 26
    assert [collection.unown_letter(letter_dvs(letter)) for letter in range(1, 27)] == list(range(1, 27))


def test_unown_is_wanted_while_an_unlocked_letter_is_missing():
    values = {0xD000: 0b0001, 0xD010: 1, 0xD011: 2}  # A to K unlocked, A and B caught
    policy = SimpleNamespace(memory=RAM(values), data=SimpleNamespace(symbols=SYMBOLS), collection={}, demand={})
    snapshot = SimpleNamespace(party=[], stored=[], owned={201})
    assert collection.unown_missing(policy, snapshot) == set(range(3, 12))
    assert collection.wanted(policy, snapshot, 201)
    policy.memory = RAM({0xD000: 0b0001, **{0xD010 + i: i + 1 for i in range(11)}})
    assert not collection.wanted(policy, snapshot, 201)


def test_contest_targets_only_species_with_no_wild_table():
    data = SimpleNamespace(encounters=[{'species': 10}, {'species': 48}])
    policy = SimpleNamespace(data=data, collection={'prerequisites': ()}, demand={}, memory=None)
    snapshot = SimpleNamespace(party=[], stored=[], owned={11, 46})
    assert contest.targets(policy, snapshot) == {12, 13, 14, 15, 123, 127}


def test_contest_keeps_a_target_over_a_stronger_ordinary_catch(monkeypatch):
    data = SimpleNamespace(encounters=[], items={'SUN_STONE': 1})
    policy = SimpleNamespace(data=data, collection={'contest': {'entered': True}, 'prerequisites': ()}, demand={}, memory=None)
    snapshot = SimpleNamespace(party=[], stored=[], owned=set(contest.CONTEST_SPECIES) - {123}, in_battle=1,
                               text='Switch POKéMON? YES NO', tiles=[' ' * 20] * 18, items=[(1, 2)])
    bytes_ = {'wStatusFlags2': 4, 'wEnemyMonSpecies': 123, 'wContestMonSpecies': 48}
    mem = SimpleNamespace(byte=lambda name: bytes_.get(name, 0))
    keep = []
    monkeypatch.setattr(contest, 'choose', lambda tiles, label, exact=False: keep.append(label) or 'a')
    contest.control(policy, snapshot, mem)
    assert keep == ['YES']
    bytes_.update(wEnemyMonSpecies=48, wContestMonSpecies=123)
    keep.clear()
    contest.control(policy, snapshot, mem)
    assert keep == ['NO']


def test_roamer_neighbours_follow_the_roam_map_table():
    ids = {f'ROUTE_{route}': route for route in quests.ROAM_MAPS}
    data = SimpleNamespace(maps={route: {'constant': f'ROUTE_{route}'} for route in quests.ROAM_MAPS}, map_ids=ids)
    assert quests.roam_neighbours(data, 36) == (35, 31, 32, 37)
    assert quests.roam_neighbours(data, 39) == (38,)
    assert all(origin in quests.ROAM_MAPS[target] for origin, targets in quests.ROAM_MAPS.items() for target in targets)
