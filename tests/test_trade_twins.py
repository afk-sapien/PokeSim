"""Twins share a trainer, DVs and evolution family. Their nicknames tell them apart, and settings stay put."""
import json

from pokesim.broker import inventory
from pokesim.store import Store
from pokesim.trade import pair, preferences
from test_trade_identity import RATTATA, collection as held, gen1 as cartridge, rows


def gen1(species, **extra):
    """A Rattata as live_status lists it, with its Pokédex number."""
    return cartridge(species, **{'dex': 19, 'nick': '', **extra})


def states(payload, saved):
    return [mon['trade_setting'] for mon in rows(payload, saved)]


def raw(store, key):
    row = store.db.execute('SELECT v FROM kv WHERE k=?', (preferences.PREFIX + key,)).fetchone()
    return json.loads(row[0]) if row else None


def test_a_setting_stays_on_its_twin_when_the_order_changes(tmp_path):
    store = Store(tmp_path)
    rats, fang = gen1(RATTATA, nick='RATS'), gen1(RATTATA, nick='FANG', level=9)
    payload = held(rats, fang)
    fang_key = rows(payload)[1]['trade_key']
    preferences.update(store, payload, fang_key, 'keep')
    assert states(payload, store.trade_preferences()) == ['auto', 'keep']
    # A withdraw puts Fang first. The lock follows the nickname, not the place.
    assert states(held(fang, rats), store.trade_preferences()) == ['keep', 'auto']
    # 0.7.4 reads only the family key, so it keeps both after a rollback.
    root = preferences.identity(rats)
    assert raw(store, root)['state'] == preferences.KEEP
    assert root not in store.trade_preferences()
    store.close()


def test_a_074_setting_still_applies_to_twins():
    rats, fang = gen1(RATTATA, nick='RATS'), gen1(RATTATA, nick='FANG', level=9)
    root = preferences.identity(rats)
    # A Never trade saved without a nickname could be either copy, so it keeps both.
    assert states(held(rats, fang), {root: {'state': 'locked'}}) == ['keep', 'keep']
    # A setting saved with a nickname names that copy alone.
    saved = {root: {'state': 'offered', 'nick': 'FANG'}}
    assert states(held(rats, fang), saved) == ['auto', 'first']
    # A copy alone keeps its 0.7.4 setting under the family key.
    assert states(held(rats), {root: {'state': 'offered', 'nick': 'FANG'}}) == ['first']


def test_a_lock_on_a_twin_that_is_not_held_keeps_every_copy():
    rats, fang = gen1(RATTATA, nick='RATS'), gen1(RATTATA, nick='FANG', level=9)
    root = preferences.identity(rats)
    # A third twin, now in the Day-Care or renamed, was set to Never trade.
    gone = f'{root}{preferences.TWIN}{preferences.tag(gen1(RATTATA, nick="BITE"))}'
    assert states(held(rats, fang), {gone: {'state': 'locked'}}) == ['keep', 'keep']


def test_ambiguous_twins_keep_a_lock_and_policies_see_any_twin_lock():
    a, b = gen1(RATTATA, level=8), gen1(RATTATA, level=9)
    root = preferences.identity(a)
    assert states(held(a, b), {root: {'state': 'locked'}}) == ['keep', 'keep']
    twin = rows(held(gen1(RATTATA, nick='RATS'), gen1(RATTATA, nick='FANG')))[1]['trade_key']
    merged = preferences.merged({twin: {'state': 'locked'}, root: {'state': 'offered'}})
    assert merged[root]['state'] == preferences.KEEP and merged[twin]['state'] == 'locked'


def test_a_party_twin_of_an_offer_is_not_offered():
    # Interchangeable twins share a key. One is in the party, so the boxed copy is not offered.
    payload = {**held(gen1(RATTATA, level=9), gen1(RATTATA, level=9)), 'started': True, 'version': 'red'}
    payload['storage']['pokemon'][0].update(box=1, position=1)
    inv = inventory.normalise('red', '', preferences.apply(payload, {}), ())
    assert not inv.tradeable
    # Without the party copy the boxed one is offered.
    alone = {**held(gen1(RATTATA, level=9), gen1(RATTATA, level=9)), 'started': True, 'version': 'red'}
    alone['party'] = []
    alone['storage']['pokemon'][0].update(box=1, position=1)
    assert inventory.normalise('red', '', preferences.apply(alone, {}), ()).tradeable


def test_a_trade_keeps_the_setting_of_the_twins_that_stayed(tmp_path, monkeypatch):
    store = Store(tmp_path / 'pair/red')
    twin, plain = 'abc-1~nfeed', 'abc-2'
    store.set_trade_preferences({twin: {'state': 'offered'}, plain: {'state': 'offered'}})
    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path / 'pair')
    transaction = tmp_path / 'transactions/9'
    transaction.mkdir(parents=True)
    moved = {'instance': 'red', 'sent': {'nick': 'A'},
             'received': {'nick': 'B', 'name': 'Zubat', 'level': 8, 'evolved_from': None}}
    proposal = {'give': {'instance': 'red', 'trade_key': twin}, 'take': {'instance': 'red', 'trade_key': plain}}
    (transaction / 'result.json').write_text(json.dumps({'moved': [moved], 'reason': 'Test', 'proposal': proposal}))
    pair.journal(tmp_path, '9')
    assert set(store.trade_preferences()) == {twin}
    store.close()
