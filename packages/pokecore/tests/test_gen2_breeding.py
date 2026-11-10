"""Day Care helpers keep single source families breeding. The species table here is synthetic."""
import itertools
import random
from types import SimpleNamespace

from pokecore.gen2 import (DITTO, breeding_stock, descendants_wanted, egg_lines, families, free_slots, lines,
                               offspring, single_source)


class Data:
    """Hashable by identity like the real GameData."""
    def __init__(self, **fields):
        self.__dict__.update(fields)


def row(groups, *evolutions):
    return {'egg_groups': list(groups), 'evolutions': [{'species': species, 'method': method}
                                                      for species, method in evolutions]}


SPECIES = {
    # Eevee and every Eeveelution, from Bill's one gift.
    133: row(['GROUND'], (134, 'item'), (135, 'item'), (136, 'item'), (196, 'happiness'), (197, 'happiness')),
    134: row(['GROUND']), 135: row(['GROUND']), 136: row(['GROUND']), 196: row(['GROUND']), 197: row(['GROUND']),
    # Tyrogue cannot breed itself, but its Hitmons can.
    236: row(['NONE'], (106, 'level'), (107, 'level'), (237, 'level')),
    106: row(['HUMANSHAPE']), 107: row(['HUMANSHAPE']), 237: row(['HUMANSHAPE']),
    175: row(['NONE'], (176, 'happiness')), 176: row(['FLYING', 'FAIRY']),
    143: row(['MONSTER']), 131: row(['MONSTER', 'WATER_1']), 132: row(['DITTO']),
    172: row(['NONE'], (25, 'happiness')), 25: row(['GROUND', 'FAIRY'], (26, 'item')), 26: row(['GROUND', 'FAIRY']),
    29: row(['MONSTER', 'GROUND'], (30, 'level')), 30: row(['NONE'], (31, 'item')), 31: row(['NONE']),
    32: row(['MONSTER', 'GROUND'], (33, 'level')), 33: row(['MONSTER', 'GROUND'], (34, 'item')),
    34: row(['MONSTER', 'GROUND']),
    # A legendary has no egg group, and nothing offers it twice.
    249: row(['NONE']),
    # Two species that evolve into the same one: the first in species order is the pre-evolution.
    250: row(['FAIRY'], (252, 'level')), 251: row(['FAIRY'], (252, 'level')), 252: row(['FAIRY']),
}
WILD = [{'species': species} for species in (25, 132, 29, 32, 251)]


def data(order=None):
    species = SPECIES if order is None else {sid: SPECIES[sid] for sid in order}
    return Data(species=species, encounters=WILD)


DATA = data()


def mon(species, gender='Male', *, egg=False, dvs=(10, 10, 10, 10, 10), box=0):
    return SimpleNamespace(species=species, gender=gender, egg=egg, dvs=dvs, box=box)


def snapshot(stored, party=(), boxes=(5,) * 14):
    return SimpleNamespace(party=tuple(party), stored=tuple(stored), box_counts=boxes)


def test_families_join_babies_and_every_branch():
    family = families(DATA)
    assert family[197] == family[133] == frozenset({133, 134, 135, 136, 196, 197})
    assert family[106] == frozenset({236, 106, 107, 237}) and family[26] == frozenset({172, 25, 26})
    assert family[29] != family[32] and family[132] == frozenset({132})


def test_gift_and_static_families_have_no_wild_source():
    single = single_source(DATA)
    assert {133, 134, 135, 136, 196, 197, 236, 106, 107, 237, 175, 176, 143, 131} <= set(single)
    assert single[196] == single[133] and 236 in single[237]
    # Ditto, Pikachu, either Nidoran and a family with one wild member are wild, and a legendary cannot breed.
    assert not {132, 25, 172, 29, 31, 32, 249, 251, 252} & set(single)


def test_lines_name_each_stage_with_its_path_and_methods():
    eevee = {species: (path, methods) for species, path, methods in lines(DATA, 133)}
    assert set(eevee) == {134, 135, 136, 196, 197}
    assert eevee[196] == (frozenset({133, 196}), frozenset({'happiness'}))
    pichu = {species: (path, methods) for species, path, methods in lines(DATA, 172)}
    assert pichu[26] == (frozenset({172, 25, 26}), frozenset({'happiness', 'item'}))
    assert lines(DATA, 143) == []


def test_the_last_parent_of_a_single_source_family_stays_home():
    assert breeding_stock(DATA, [132, 196, 25, 143]) == {132, 196, 143}
    assert breeding_stock(DATA, [132, 132, 133, 196, 25, 143, 143]) == set()


def test_a_boxed_egg_marks_its_whole_family():
    boxed = snapshot((mon(196), mon(132, 'Genderless'), mon(133, egg=True, box=1)))
    assert egg_lines(DATA, boxed) == families(DATA)[133]
    carried = snapshot((), party=(mon(172, egg=True),))
    assert egg_lines(DATA, carried) == frozenset({172, 25, 26})
    assert egg_lines(DATA, snapshot((mon(196),))) == frozenset()
    # A species missing from the table still counts itself.
    assert egg_lines(DATA, snapshot((mon(999, egg=True),))) == frozenset({999})


def test_free_slots_count_every_box():
    assert free_slots(snapshot(())) == 15 * 14
    assert free_slots(snapshot((), boxes=(20,) * 13 + (18,))) == 2
    assert free_slots(snapshot((), boxes=(25, 0))) == 20
    assert free_slots(SimpleNamespace(party=(), stored=())) == 99


def test_cable_demand_for_a_later_stage_breeds_another_baby():
    espeon, ditto = mon(196, dvs=(10, 9, 8, 7, 6)), mon(132, 'Genderless', dvs=(3, 4, 5, 6, 7))
    held = snapshot((espeon, ditto))
    assert descendants_wanted(DATA, held, {196: 1}, 133)
    # Another Eevee in the box can already become the requested Espeon.
    assert not descendants_wanted(DATA, snapshot((espeon, ditto, mon(133))), {196: 1}, 133)
    assert descendants_wanted(DATA, snapshot((espeon, ditto, mon(133))), {196: 2}, 133)
    # Stones are scarce, so a Jolteon request does not breed, and nothing wanted means nothing bred.
    assert not descendants_wanted(DATA, held, {135: 1}, 133)
    assert not descendants_wanted(DATA, held, {}, 133)
    hitmonlee = mon(106)
    assert descendants_wanted(DATA, snapshot((hitmonlee, ditto)), {237: 1}, 236)
    # Pichu has a wild source, so demand for Pikachu is met by catching one.
    assert not descendants_wanted(DATA, snapshot((ditto,)), {25: 1}, 172)


def offspring_0_6_0(data, first, second):
    """Core 0.6.0's offspring, kept verbatim with its linear scan for the pre-evolution."""
    if first.egg or second.egg or first.species == second.species == DITTO:
        return set()
    groups = [set(data.species[mon.species]['egg_groups']) for mon in (first, second)]
    if any('NONE' in group for group in groups):
        return set()
    if first.dvs[2] == second.dvs[2] and first.dvs[4] % 8 == second.dvs[4] % 8:
        return set()
    if first.species == DITTO or second.species == DITTO:
        mother = second if first.species == DITTO else first
    elif groups[0] & groups[1] and {first.gender, second.gender} == {'Male', 'Female'}:
        mother = first if first.gender == 'Female' else second
    else:
        return set()
    species = mother.species
    for _ in range(2):
        species = next((sid for sid, row in data.species.items()
                        if any(evo['species'] == species for evo in row['evolutions'])), species)
    return {29, 32} if species == 29 else {species}


def test_cached_offspring_matches_the_0_6_0_scan_on_every_pair():
    genders = ('Male', 'Female', 'Genderless')
    # Equal Defense and Special mod 8 is the related-DV case, and the last DVs differ in both.
    dvs = ((0, 8, 2, 8, 4), (0, 8, 2, 8, 12), (0, 8, 5, 8, 5))
    pool = [mon(species, gender, egg=egg, dvs=values)
            for species in SPECIES for gender in genders for egg in (False, True) for values in dvs]
    shuffled = list(SPECIES)
    random.Random(2).shuffle(shuffled)
    for table in (data(), data(sorted(SPECIES)), data(shuffled)):
        produced = 0
        for first, second in itertools.product(pool, repeat=2):
            expected = offspring_0_6_0(table, first, second)
            assert offspring(table, first, second) == expected, (first, second)
            produced += bool(expected)
        assert produced
    assert offspring(DATA, mon(132, 'Genderless', dvs=(0, 8, 5, 8, 5)), mon(252, 'Female')) == {250}
    assert offspring(data(sorted(SPECIES, reverse=True)), mon(132, 'Genderless', dvs=(0, 8, 5, 8, 5)),
                     mon(252, 'Female')) == {251}


def test_the_pre_evolution_cache_follows_a_replaced_species_table():
    table = data()
    ditto = mon(132, 'Genderless', dvs=(0, 8, 5, 8, 5))
    assert offspring(table, ditto, mon(252, 'Female')) == {250}
    table.species = {sid: SPECIES[sid] for sid in sorted(SPECIES, reverse=True)}
    assert offspring(table, ditto, mon(252, 'Female')) == {251}
