"""Trade keys tell apart species that share a trainer and DVs, and survive evolution.

Ported from PokeSim's tests/test_trade_identity.py and tests/test_sprites.py fixtures. The species
tables are checked against the cartridges in test_sprites_roms.py.
"""
from pokecore import formulas, identity
from pokecore.gen2 import ram
from pokecore.identity import dex_of, family, family_key, find, legacy, pokemon_identity, same

TRAINER, DVS = 4321, [7, 9, 3, 12, 6]
# Red, Blue and Yellow species indexes.
RATTATA, PIDGEY, PIKACHU, RAICHU, ONIX = 165, 36, 84, 85, 34


def gen1(species, *, trainer=TRAINER, dvs=DVS):
    return {'species': species, 'trainer_id': trainer, 'dvs': list(dvs)}


def gen2(dex, *, trainer=TRAINER, dvs=DVS):
    return {'species': dex, 'dex': dex, 'trainer_id': trainer, 'dvs': list(dvs)}


def key(mon):
    return family_key(mon.get('trainer_id'), mon.get('dvs', ()), dex_of(mon))


def test_different_species_with_the_same_trainer_and_dvs_get_different_keys():
    keys = [key(mon) for mon in (gen1(RATTATA), gen1(PIDGEY), gen2(152), gen2(155))]
    assert len(set(keys)) == 4
    # The trainer and DV signature is still the start of every key.
    assert {legacy(value) for value in keys} == {pokemon_identity(TRAINER, DVS)}


def test_key_survives_evolution_in_both_generations_and_the_time_capsule():
    pikachu = key(gen1(PIKACHU))
    assert key(gen1(RAICHU)) == key(gen2(172)) == key(gen2(25)) == key(gen2(26)) == pikachu
    assert pikachu.endswith('-25')
    # Onix and Steelix, Eevee and Espeon, Tyrogue and each fighter it can become.
    assert key(gen1(ONIX)) == key(gen2(208))
    assert key(gen2(133)) == key(gen2(196))
    assert len({key(gen2(dex)) for dex in (236, 106, 107, 237)}) == 1
    # A Gold, Silver or Crystal record of a Red Pokémon carries its Pokédex number.
    assert key(gen2(19)) == key(gen1(RATTATA))


def test_unreadable_pokemon_have_no_key():
    assert key(gen1(RATTATA, trainer=None)) is None
    assert key({'species': 0, 'trainer_id': 1, 'dvs': DVS}) is None
    assert key({'species': 'Rattata', 'trainer_id': 1, 'dvs': DVS}) is None
    assert family_key(1, (1, 2), 25) is None


def test_families_can_be_supplied():
    assert family(172) == 25 and family(250) == 250
    assert family(172, {}) == 172
    assert family_key(1, DVS, 26, {26: 999}).endswith('-999')


def test_old_keys_match_only_when_one_pokemon_answers():
    rattata, pidgey = gen1(RATTATA), gen1(PIDGEY)
    old = pokemon_identity(TRAINER, DVS)
    listed = [{'trade_key': key(mon)} for mon in (rattata, pidgey)]
    assert find(listed, old) is None
    assert find(listed[:1], old) is listed[0]
    assert find(listed, listed[1]['trade_key']) is listed[1]
    assert find(listed + [dict(listed[1])], listed[1]['trade_key']) is None
    assert same(listed[0]['trade_key'], old) and same(old, listed[0]['trade_key'])
    assert not same(listed[0]['trade_key'], listed[1]['trade_key'])
    assert not same(None, old) and not same(old, '')
    assert legacy(None) is None and identity.is_legacy(old) and not identity.is_legacy(listed[0]['trade_key'])


def test_gen1_index_tables_are_inverse():
    assert len(identity.GEN1_DEX) == 151 and set(identity.GEN1_DEX.values()) == set(range(1, 152))
    assert all(identity.GEN1_DEX[index] == dex for dex, index in identity.GEN1_INDEX.items())
    assert identity.GEN1_INDEX[151] == 0x15 and identity.GEN1_INDEX[25] == PIKACHU


def test_family_roots_are_the_lowest_member():
    for members in identity.FAMILIES:
        assert {identity.FAMILY_ROOTS[dex] for dex in members} == {min(members)}
    assert sum(len(members) for members in identity.FAMILIES) == len(identity.FAMILY_ROOTS)


def test_experience_curves_are_shared_by_both_generations():
    assert ram.experience_at is formulas.experience_at and ram.experience_progress is formulas.experience_progress
    assert [formulas.experience_at(50, growth) for growth in ('FAST', 'MEDIUM_FAST', 'MEDIUM_SLOW', 'SLOW')] == [
        100000, 125000, 117360, 156250]
    assert formulas.experience_at(1, 'MEDIUM_SLOW') == 0 and formulas.experience_at(0, None) == 1
    assert formulas.experience_at(101, 'SLOW') == formulas.experience_at(100, 'SLOW') == 1250000
    progress = formulas.experience_progress(130, 5, 'MEDIUM_FAST')
    assert progress == {'total': 130, 'level_start': 125, 'next_level': 216, 'remaining': 86,
                        'max_level': False, 'percent': 5.5}
    assert formulas.experience_progress(10 ** 6, 100, 'MEDIUM_FAST')['percent'] == 100
