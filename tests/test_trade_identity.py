"""Trade keys tell apart species that share a trainer and DVs, and survive evolution."""
import json
import os
from pathlib import Path

import pytest

from pokecore import identity as individual
from pokesim import store as store_module
from pokesim.store import Store
from pokesim.strategy_data import SPECIES
from pokesim.trade import preferences
from pokesim.web.pokedex import EVOLUTIONS

TRAINER, DVS = 4321, [7, 9, 3, 12, 6]
# Red, Blue and Yellow species indexes.
RATTATA, PIDGEY, PIKACHU, RAICHU, ONIX = 165, 36, 84, 85, 34


def gen1(species, *, trainer=TRAINER, dvs=DVS, **extra):
    return {'species': species, 'name': SPECIES[species]['name'].title(), 'trainer_id': trainer, 'dvs': list(dvs), **extra}


def gen2(dex, name, *, trainer=TRAINER, dvs=DVS, **extra):
    return {'species': dex, 'dex': dex, 'name': name, 'trainer_id': trainer, 'dvs': list(dvs), **extra}


def collection(*mons):
    return {'party': [dict(mon, slot=i + 1) for i, mon in enumerate(mons[:1])],
            'storage': {'pokemon': [dict(mon, box=1, position=i) for i, mon in enumerate(mons[1:])]}}


def rows(payload, saved=None):
    applied = preferences.apply(payload, saved or {})
    return applied['party'] + applied['storage']['pokemon']


def test_different_species_with_the_same_trainer_and_dvs_are_both_tradable():
    listed = rows(collection(gen1(RATTATA), gen1(PIDGEY), gen2(152, 'Chikorita'), gen2(155, 'Cyndaquil')))
    keys = [mon['trade_key'] for mon in listed]
    assert len(set(keys)) == 4
    assert not any(mon['trade_ambiguous'] for mon in listed)
    assert {preferences.blocked(mon) for mon in listed} == {''}
    # The old trainer and DV signature is still the start of every key.
    assert {individual.legacy(key) for key in keys} == {preferences.signature(listed[0])}


def test_key_survives_evolution_in_both_generations_and_the_time_capsule():
    pikachu = preferences.identity(gen1(PIKACHU))
    assert preferences.identity(gen1(RAICHU)) == pikachu
    assert preferences.identity(gen2(172, 'Pichu')) == pikachu
    assert preferences.identity(gen2(25, 'Pikachu')) == pikachu
    assert preferences.identity(gen2(26, 'Raichu')) == pikachu
    # Onix and Steelix, Eevee and Espeon, Tyrogue and each fighter it can become.
    assert preferences.identity(gen1(ONIX)) == preferences.identity(gen2(208, 'Steelix'))
    assert preferences.identity(gen2(133, 'Eevee')) == preferences.identity(gen2(196, 'Espeon'))
    assert len({preferences.identity(gen2(dex, 'Fighter')) for dex in (236, 106, 107, 237)}) == 1
    # A Gold, Silver or Crystal record of a Red Pokémon carries its Pokédex number.
    assert preferences.identity(gen2(19, 'Rattata')) == preferences.identity(gen1(RATTATA))


def test_the_stamp_is_a_pinned_sha256_of_the_stats():
    # Python's hash() changes with each process, so a key built on it would name nothing after a restart.
    mon = {'dex': 19, 'species': 165, 'nick': 'RATS', 'level': 9, 'experience': 729, 'moves': [33, 39],
           'friendship': 70}
    assert preferences.stamp(mon) == 'fe0dcc84c'
    assert preferences.stamp({**mon, 'level': 10}) != 'fe0dcc84c'


def test_twins_whose_stats_differ_get_a_stamped_key_each():
    listed = rows(collection(gen1(RATTATA), gen1(RATTATA, level=9), gen1(PIDGEY)))
    keys = [mon['trade_key'] for mon in listed]
    assert not any(mon['trade_ambiguous'] for mon in listed)
    assert {preferences.blocked(mon) for mon in listed} == {''}
    assert keys[0] != keys[1] and preferences.stamped(keys[0]) and preferences.stamped(keys[1])
    assert preferences.tagged(keys[0]) == preferences.tagged(keys[1]) == f'{preferences.identity(listed[0])}~d'
    assert keys[0] == f'{preferences.tagged(keys[0])}~{preferences.stamp(listed[0])}'
    assert [preferences.find(listed, key) for key in keys[:2]] == listed[:2]
    # An evolved copy and a nicknamed pair are stamped the same way.
    evolved = rows(collection(gen1(PIKACHU), gen1(RAICHU, level=30)))
    assert len({mon['trade_key'] for mon in evolved}) == 2 and not any(mon['trade_ambiguous'] for mon in evolved)
    named = rows(collection(gen1(RATTATA, nick='RATS'), gen1(RATTATA, nick='RATS', level=9)))
    assert len({mon['trade_key'] for mon in named}) == 2 and not any(mon['trade_ambiguous'] for mon in named)


def test_twins_whose_stamps_collide_stay_blocked_with_a_plain_reason(monkeypatch):
    monkeypatch.setattr(preferences, 'stamp', lambda mon: 'f00000000')
    listed = rows(collection(gen1(RATTATA), gen1(RATTATA, level=9), gen1(PIDGEY)))
    assert [mon['trade_ambiguous'] for mon in listed] == [True, True, False]
    # Their levels differ, so the reason never claims identical stats.
    assert preferences.blocked(listed[0]) == ("Another Rattata from the same trainer has the same DVs and "
                                              "no nickname, so this one can't be picked out safely")
    evolved = rows(collection(gen1(PIKACHU), gen1(RAICHU, level=30)))
    assert preferences.blocked(evolved[0]) == ("Raichu is from the same trainer, has the same DVs, the same "
                                               "evolution family and no nickname, so this one can't be picked out safely")
    named = rows(collection(gen1(RATTATA, nick='RATS'), gen1(RATTATA, nick='RATS', level=9)))
    assert preferences.blocked(named[0]) == ("Another Rattata from the same trainer has the same DVs and "
                                             "the same nickname, so this one can't be picked out safely")
    assert not any('identical' in preferences.blocked(mon) for mon in listed + evolved + named)


def old_answers(mon, key):
    """answers as releases before stamps had it, which split a twin key in two."""
    if isinstance(key, str) and preferences.TWIN in key:
        root, mark = key.split(preferences.TWIN, 1)
        return preferences.identity(mon) == root and preferences.tag(mon) == mark
    return individual.same(preferences.identity(mon), key)


def old_find(rows, wanted, field='trade_key'):
    """find as releases before stamps had it."""
    exact = [row for row in rows if row.get(field) and row.get(field) == wanted]
    if (len(exact) > 1 and isinstance(wanted, str) and preferences.TWIN in wanted
            and not any(row.get('trade_ambiguous') or row.get('blocked') for row in exact)):
        return exact[0]
    return individual.find(rows, wanted, field)


def test_an_older_reader_given_a_stamped_key_names_nothing():
    listed = rows(collection(gen1(RATTATA), gen1(RATTATA, level=9), gen1(PIDGEY)))
    stamped = [mon['trade_key'] for mon in listed[:2]]
    # An older release lists the same copies under its two part twin keys.
    old = [{**mon, 'trade_key': preferences.tagged(mon['trade_key'])} for mon in listed]
    for key in stamped:
        assert not any(old_answers(mon, key) for mon in old)
        assert old_find(old, key) is None


def test_nicknames_tell_twins_apart():
    listed = rows(collection(gen1(RATTATA, nick='RATS'), gen1(RATTATA, level=9), gen1(RATTATA, nick='FANG')))
    keys = [mon['trade_key'] for mon in listed]
    assert len(set(keys)) == 3
    assert {preferences.base(key) for key in keys} == {preferences.identity(listed[0])}
    assert not any(mon['trade_ambiguous'] for mon in listed)
    # A nickname that only spells the species name is no nickname.
    plain = rows(collection(gen1(RATTATA, nick='RATTATA'), gen1(RATTATA, level=9)))
    assert {preferences.tagged(mon['trade_key']) for mon in plain} == {f'{preferences.identity(plain[0])}~d'}
    # A lone Pokémon keeps its family key, as 0.7.4 stored it.
    alone = rows(collection(gen1(RATTATA, nick='RATS')))
    assert alone[0]['trade_key'] == preferences.identity(alone[0])


def test_interchangeable_twins_share_a_key_and_can_be_picked():
    listed = rows(collection(gen1(RATTATA, level=9), gen1(RATTATA, level=9), gen1(PIDGEY)))
    assert listed[0]['trade_key'] == listed[1]['trade_key']
    assert not any(mon['trade_ambiguous'] for mon in listed)
    assert preferences.find(listed, listed[0]['trade_key']) is listed[0]
    assert preferences.interchangeable(listed, listed[0]['trade_key']) == listed[:2]
    assert preferences.sendable(listed, 0, listed[0]['trade_key'])
    differing = rows(collection(gen1(RATTATA, level=9), gen1(RATTATA, level=10)))
    assert preferences.find(differing, differing[0]['trade_key']) is differing[0]
    assert preferences.sendable(differing, 0, differing[0]['trade_key'])
    # The party copy a stamped key picked gains a level on the way, and the slot still answers.
    grown = rows(collection(gen1(RATTATA, level=11), gen1(RATTATA, level=10)))
    assert preferences.sendable(grown, 0, differing[0]['trade_key'])
    # A two part key from before the copies differed names two that are no longer interchangeable.
    assert not preferences.sendable(differing, 0, preferences.tagged(differing[0]['trade_key']))
    # The party Pokémon must answer to the key the trade agreed on.
    named = rows(collection(gen1(RATTATA, nick='RATS'), gen1(RATTATA, nick='FANG')))
    assert not preferences.sendable(named, 0, named[1]['trade_key'])
    assert preferences.sendable(named, 0, named[0]['trade_key'])


def test_unreadable_pokemon_are_blocked():
    listed = rows(collection(gen1(RATTATA, trainer=None)))
    assert listed[0]['trade_key'] is None
    assert preferences.blocked(listed[0]) == preferences.UNREADABLE


def test_old_keys_match_only_when_one_pokemon_answers():
    rattata, pidgey = gen1(RATTATA), gen1(PIDGEY)
    old = preferences.signature(rattata)
    listed = [{'trade_key': preferences.identity(mon)} for mon in (rattata, pidgey)]
    assert individual.find(listed, old) is None
    assert individual.find(listed[:1], old) is listed[0]
    assert individual.find(listed, listed[1]['trade_key']) is listed[1]
    assert individual.same(listed[0]['trade_key'], old)
    assert not individual.same(listed[0]['trade_key'], listed[1]['trade_key'])


def test_saved_settings_move_to_the_new_key_only_when_unambiguous(tmp_path):
    rattata, pidgey, onix = gen1(RATTATA), gen1(PIDGEY), gen1(ONIX, trainer=99)
    store = Store(tmp_path)
    shared, alone = preferences.signature(rattata), preferences.signature(onix)
    store.set_trade_preference(shared, {'state': preferences.KEEP})
    store.set_trade_preference(alone, {'state': preferences.FIRST})
    assert store.trade_preferences().keys() == {shared, alone}
    store.upgrade_trade_preferences(lambda: [rattata, pidgey, onix])
    saved = store.trade_preferences()
    # Onix was the only Pokémon with its trainer and DVs, so its setting follows it.
    assert saved[preferences.identity(onix)]['state'] == preferences.FIRST
    assert alone not in saved
    # Rattata and Pidgey shared the old key, so it is left alone. A lock fails safe, so it keeps both.
    assert saved[shared]['state'] == preferences.KEEP
    applied = rows(collection(rattata, pidgey, onix), saved)
    assert [mon['trade_preference'] for mon in applied] == [preferences.KEEP, preferences.KEEP, preferences.FIRST]
    # The move runs once per process.
    store.upgrade_trade_preferences(lambda: pytest.fail('ran twice'))
    store.close()


def test_settings_wait_for_a_fully_readable_collection(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(store_module.time, 'monotonic', lambda: clock[0])
    store = Store(tmp_path)
    onix = gen1(ONIX)
    store.set_trade_preference(preferences.signature(onix), {'state': preferences.KEEP})
    store.upgrade_trade_preferences(lambda: [onix, {'species': ONIX, 'box': 1}])
    assert preferences.signature(onix) in store.trade_preferences()
    # Every observed frame offers the move, but it waits before reading the collection again.
    clock[0] += store_module.TRADE_KEY_RETRY_SECONDS - 1
    store.upgrade_trade_preferences(lambda: pytest.fail('retried too soon'))
    clock[0] += 1
    store.upgrade_trade_preferences(lambda: [onix])
    assert store.trade_preferences() == {preferences.identity(onix): {'state': preferences.KEEP}}
    store.close()


def old_release_locked(store, mon):
    """Whether 0.4.20 sees a Pokémon as locked: it reads only the trainer and DV row's state."""
    row = store.db.execute('SELECT v FROM kv WHERE k=?', (preferences.PREFIX + preferences.signature(mon),)).fetchone()
    return bool(row) and json.loads(row[0]).get('state') == 'locked'


def test_moved_lock_still_reads_in_the_older_release_after_a_rollback(tmp_path):
    onix, rattata, pidgey = gen1(ONIX, trainer=99), gen1(RATTATA), gen1(PIDGEY)
    store = Store(tmp_path)
    # 0.4.20 wrote Never trade under the trainer and DV key.
    store.set_trade_preference(preferences.signature(onix), {'state': 'locked', 'name': 'Onix'})
    store.upgrade_trade_preferences(lambda: [onix, rattata, pidgey])
    assert store.trade_preferences() == {preferences.identity(onix): {'state': 'locked', 'name': 'Onix'}}
    assert old_release_locked(store, onix)
    # Unlocking and locking again in this release reaches the older row too.
    store.set_trade_preference(preferences.identity(onix), {'state': preferences.stored('auto')})
    assert not old_release_locked(store, onix)
    store.set_trade_preference(preferences.identity(onix), {'state': preferences.stored('keep')})
    assert old_release_locked(store, onix)
    # A lock set in this release on one of two species sharing a key locks that key for 0.4.x,
    # which cannot tell them apart, but this release still locks only that one.
    store.set_trade_preference(preferences.identity(rattata), {'state': preferences.stored('keep')})
    assert old_release_locked(store, pidgey)
    applied = rows(collection(rattata, pidgey, onix), store.trade_preferences())
    assert [mon['trade_locked'] for mon in applied] == [True, False, True]
    store.close()


def test_a_lock_set_after_a_rollback_wins_when_upgrading_again(tmp_path):
    onix = gen1(ONIX)
    store = Store(tmp_path)
    store.set_trade_preference(preferences.identity(onix), {'state': preferences.stored('first')})
    # The older release overwrites its row with a plain lock, without the copy marker.
    store.set_trade_preference(preferences.signature(onix), {'state': 'locked'})
    store.upgrade_trade_preferences(lambda: [onix])
    assert store.trade_preferences() == {preferences.identity(onix): {'state': preferences.KEEP}}
    assert old_release_locked(store, onix)
    store.close()


def test_gen1_index_table_matches_game_data():
    assert {sid: row['dex'] for sid, row in SPECIES.items()} == individual.GEN1_DEX


def test_families_match_gen1_evolutions():
    for sid, evolutions in EVOLUTIONS.items():
        for evolution in evolutions:
            assert individual.family(SPECIES[sid]['dex']) == individual.family(SPECIES[evolution['species']]['dex'])


def test_families_match_gen2_evolutions():
    root = os.environ.get('GEN2_DATA_DIR')
    path = Path(root or '') / 'gen2' / 'crystal' / 'data.json'
    if not root or not path.exists():
        pytest.skip('Set GEN2_DATA_DIR to check families against Gold, Silver and Crystal data')
    species = json.loads(path.read_text())['species']
    linked = {}
    for dex, row in species.items():
        for evolution in row.get('evolutions', ()):
            assert individual.family(int(dex)) == individual.family(evolution['species'])
            linked[int(dex)] = linked[evolution['species']] = True
    # Every listed family is a real evolution line, and every evolving species is listed.
    assert set(linked) == set(individual.FAMILY_ROOTS)
