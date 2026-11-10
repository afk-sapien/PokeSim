"""The seeded randomizer, on small synthetic game data."""
import hashlib
import json

import pytest

from pokecore import randomizer
from pokecore.randomizer import Options
from pokecore.romdata import GameData, FIELDS

SURF = 53


def game(version='red', surfers=(3,)):
    """Six species, two wild tables, two trainers. Only ``surfers`` learn Surf."""
    species = {number: {'tmhm': [SURF] if number in surfers else []} for number in range(1, 7)}
    if version == 'gold':
        slots = {'morn': [[3, 1], [4, 2]], 'day': [[3, 2], [4, 1]], 'nite': [[5, 4], [5, 4]]}
        encounters = {'johto_grass:1': {'kind': 'johto_grass', 'map': 1, 'rate': 10, 'slots': slots},
                      'johto_water:1': {'kind': 'johto_water', 'map': 1, 'rate': 5, 'slots': [[20, 5]]}}
    else:
        encounters = {'grass:1': {'kind': 'grass', 'map': 1, 'rate': 10, 'slots': [[3, 1], [4, 2], [5, 4]]},
                      'water:2': {'kind': 'water', 'map': 2, 'rate': 5, 'slots': [[20, 5]]}}
    trainers = {'1:1': {'class': 1, 'index': 1, 'party': [{'level': 5, 'species': 1}]},
                '1:2': {'class': 1, 'index': 2, 'party': [{'level': 7, 'species': 2}, {'level': 8, 'species': 6}]}}
    tables = {'species': species, 'evolutions': {}, 'learnsets': {}, 'tm_moves': [], 'encounters': encounters,
              'fishing': {}, 'fish_groups': {}, 'trainers': trainers, 'starters': [1, 4]}
    assert set(tables) == set(FIELDS)
    return GameData(version, tables)


GATES = ((SURF, ('grass:1',)),)


def digest(overrides):
    return hashlib.sha256(json.dumps(overrides, sort_keys=True).encode()).hexdigest()


def test_same_seed_same_overrides():
    data = game()
    first = randomizer.randomize(data, 7, gates=GATES)
    assert first == randomizer.randomize(data, 7, gates=GATES)
    assert any(randomizer.randomize(data, seed, gates=GATES) != first for seed in range(8, 20))


def test_draws_are_stable_across_python_versions():
    # A change here breaks every published share code.
    assert digest(randomizer.randomize(game(), 7, gates=GATES)) == (
        '6cdb67727e5f7639e1c8ac7ff28ecf2750be9f29af0c0d5b07127009ab717d6f')


def test_one_species_map_keeps_levels():
    data = game()
    overrides = randomizer.randomize(data, 11, Options(trainers=True), gates=GATES)
    effective = data.with_overrides(overrides)
    pairs = {}
    for before, after in [(data.starters, effective.starters)] + [
            ([mon for _, mon in data.encounters[key]['slots']], [mon for _, mon in effective.encounters[key]['slots']])
            for key in data.encounters] + [
            ([mon['species'] for mon in data.trainers[key]['party']],
             [mon['species'] for mon in effective.trainers[key]['party']]) for key in data.trainers]:
        for old, new in zip(before, after):
            assert pairs.setdefault(old, new) == new
    assert len(set(pairs.values())) == len(pairs)
    for key, table in data.encounters.items():
        assert [level for level, _ in effective.encounters[key]['slots']] == [level for level, _ in table['slots']]
    assert [mon['level'] for mon in effective.trainers['1:2']['party']] == [7, 8]


def test_gen2_slots_keep_times_of_day():
    data = game('gold')
    effective = data.with_overrides(randomizer.randomize(data, 3, gates=()))
    slots = effective.encounters['johto_grass:1']['slots']
    assert set(slots) == {'morn', 'day', 'nite'}
    assert slots['nite'][0] == slots['nite'][1] and [level for level, _ in slots['day']] == [3, 4]


def test_trainers_are_opt_in():
    data = game()
    assert set(randomizer.randomize(data, 5, gates=GATES)) == {'encounters', 'starters'}
    assert set(randomizer.randomize(data, 5, Options(wild=False, starters=False, trainers=True))) == {'trainers'}
    with pytest.raises(ValueError, match='at least one'):
        randomizer.randomize(data, 5, Options(wild=False, starters=False))


def test_every_kept_draw_has_a_surfer_before_the_gate():
    data = game()
    for seed in range(50):
        effective = data.with_overrides(randomizer.randomize(data, seed, gates=GATES))
        assert {mon for _, mon in effective.encounters['grass:1']['slots']} & {3}
        assert randomizer.missing_hm_learners(effective, GATES) == []


def test_missing_hm_learners():
    assert randomizer.missing_hm_learners(game(surfers=(5,)), GATES) == [SURF]
    assert randomizer.missing_hm_learners(game(surfers=(1,)), GATES) == []
    # A table the cartridge lacks is skipped, and starters never count.
    assert randomizer.missing_hm_learners(game(surfers=(4, 1)), ((SURF, ('grass:9', 'water:2')),)) == [SURF]


def learnable(data, mon):
    """True when every move ``mon`` knows is in its species' learnset at or below its level."""
    known = {move for level, move in data.learnsets.get(mon['species'], []) if level <= mon['level']}
    return all(move == 0 or move in known for move in mon['moves'])


def test_default_moves_fill_like_the_cartridge():
    learnset = [[1, 33], [1, 45], [4, 39], [7, 33], [9, 52], [12, 98], [15, 44], [50, 1]]
    assert randomizer.default_moves(learnset, 1) == [33, 45, 0, 0]
    assert randomizer.default_moves(learnset, 9) == [33, 45, 39, 52]
    assert randomizer.default_moves(learnset, 15) == [39, 52, 98, 44]
    assert randomizer.default_moves([], 30) == [0, 0, 0, 0]


def test_gen2_trainer_moves_follow_the_new_species():
    data = game('gold')
    tables = data.as_dict()
    tables['learnsets'] = {number: [[1, number * 10], [5, number * 10 + 1], [9, number * 10 + 2]]
                           for number in range(1, 7)}
    tables['trainers']['2:1'] = {'class': 2, 'index': 1, 'party': [
        {'level': 6, 'species': 1, 'item': 0, 'moves': [10, 11, 0, 0]},
        {'level': 9, 'species': 3, 'item': 0, 'moves': [30, 31, 32, 0]}]}
    data = GameData('gold', tables)
    for seed in range(30):
        effective = data.with_overrides(randomizer.randomize(data, seed, Options(trainers=True), gates=()))
        for trainer in effective.trainers.values():
            for mon in trainer['party']:
                if 'moves' in mon:
                    assert len(mon['moves']) == 4 and learnable(effective, mon)
                    assert mon['moves'] == randomizer.default_moves(effective.learnsets[mon['species']], mon['level'])


def test_gen1_parties_have_no_explicit_moves():
    data = game()
    overrides = randomizer.randomize(data, 4, Options(trainers=True), gates=GATES)
    assert all(set(mon) == {'level', 'species'} for trainer in overrides['trainers'].values()
               for mon in trainer['party'])


def test_impossible_gates_raise():
    with pytest.raises(RuntimeError, match='No draw'):
        randomizer.randomize(game(surfers=()), 1, gates=GATES)


def test_real_gates_cover_each_version():
    for version in randomizer.GAMES:
        gates = randomizer.hm_gates(version)
        assert [hm for hm, _ in gates] == ([51, 53, 54] if version in ('red', 'blue', 'yellow') else [51, 53, 54, 57])
        for (_, earlier), (_, later) in zip(gates, gates[1:]):
            assert set(earlier) < set(later)
    assert randomizer.hm_gates('gold') == randomizer.hm_gates('silver') != randomizer.hm_gates('crystal')


@pytest.mark.parametrize('version, seed, options, code', [
    ('red', 0, Options(), 'PSR1-RED-WS-0'),
    ('crystal', 42, Options(trainers=True), 'PSR1-CRYSTAL-WST-42'),
    ('yellow', 2 ** 64 - 1, Options(wild=False, starters=False, trainers=True), 'PSR1-YELLOW-T-18446744073709551615'),
])
def test_share_code_round_trip(version, seed, options, code):
    assert randomizer.encode_share_code(version, seed, options) == code
    assert randomizer.decode_share_code(code) == (version, seed, options)
    assert randomizer.decode_share_code(f' {code.lower()} ') == (version, seed, options)


@pytest.mark.parametrize('code', ['PSR2-RED-WS-1', 'PSR1-EMERALD-WS-1', 'PSR1-RED--1', 'PSR1-RED-SW-1',
                                  'PSR1-RED-WWS-1', 'PSR1-RED-WX-1', 'PSR1-RED-WS--1', 'PSR1-RED-WS-01',
                                  'PSR1-RED-WS-18446744073709551616', 'PSR1-RED-WS', 'PSR1-RED-WS-1-2'])
def test_bad_share_codes(code):
    with pytest.raises(ValueError):
        randomizer.decode_share_code(code)


@pytest.mark.parametrize('seed', [-1, 2 ** 64, 1.5, '3', True])
def test_bad_seeds(seed):
    with pytest.raises(ValueError, match='seed'):
        randomizer.randomize(game(), seed, gates=GATES)
