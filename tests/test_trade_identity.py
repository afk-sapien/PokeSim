"""Trade keys tell apart species that share a trainer and DVs, and survive evolution."""
import json
import os
from pathlib import Path

import pytest

from pokesim import individual
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


def test_true_twins_stay_blocked_with_a_plain_reason():
    listed = rows(collection(gen1(RATTATA), gen1(RATTATA, level=9), gen1(PIDGEY)))
    assert [mon['trade_ambiguous'] for mon in listed] == [True, True, False]
    assert preferences.blocked(listed[0]) == (
        "Another Rattata from the same trainer has identical stats, so the game can't tell them apart")
    evolved = rows(collection(gen1(PIKACHU), gen1(RAICHU)))
    assert preferences.blocked(evolved[0]) == ("Raichu is from the same trainer, has identical stats and the "
                                               "same evolution family, so the game can't tell them apart")


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
    assert set(linked) == set(individual.ROOT)
