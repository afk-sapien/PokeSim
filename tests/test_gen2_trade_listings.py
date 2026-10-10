"""The Gen II trading view lists every Pokémon, so the PC popup can show any trade state."""
from types import SimpleNamespace

import pytest

from pokesim.gen2 import breeding, trading


def boxed(species, position, **extra):
    return {'species': species, 'box': 1, 'position': position, 'trade_key': f'k{position}',
            'trade_preference': 'auto', 'dvs': (8,) * 5, 'stat_exp': (0,) * 5, **extra}


@pytest.fixture
def emu(monkeypatch):
    monkeypatch.setattr(trading, 'available_trade_item', lambda *args: 0)
    monkeypatch.setattr(trading, 'compatible', lambda *args: True)
    monkeypatch.setattr(trading, 'evolved_species', lambda *args: None)
    monkeypatch.setattr(breeding, 'breeding_stock', lambda data, species: {2})
    stored = tuple(SimpleNamespace(box=0, position=i) for i in range(8))
    policy = SimpleNamespace(collection={}, in_league=lambda snapshot: False)
    return SimpleNamespace(snapshot=SimpleNamespace(items=(), stored=stored), policy=policy, data=None)


def payload():
    return {'party': [{'species': 9, 'slot': 1, 'trade_key': 'p1', 'trade_preference': 'auto'}],
            'storage': {'pokemon': [
                boxed(1, 1), boxed(2, 2), boxed(3, 3, shiny=True), boxed(4, 4, dvs=(15,) * 5),
                boxed(5, 5, trade_preference='locked'), boxed(6, 6, stat_exp=(20000, 0, 0, 0, 0)),
                boxed(7, 7, egg=True), boxed(8, 8, trade_preference='offered', stat_exp=(65535,) * 5)]}}


def test_every_party_and_boxed_pokemon_has_a_trade_state(emu):
    rows = {row['trade_key']: row for row in trading.listings(emu, payload())}
    assert len(rows) == 9
    assert [key for key, row in rows.items() if row['listed']] == ['k1', 'k8']
    assert rows['k2']['reason'].startswith('Kept as a Day Care parent') and rows['k2']['can_offer']
    assert rows['k3']['reason'] == 'Shiny partner preserved for the collection' and not rows['k3']['can_offer']
    assert rows['k4']['perfect_dvs'] and not rows['k4']['can_offer']
    assert rows['k5']['locked'] and rows['k5']['editable'] and not rows['k5']['can_offer']
    assert rows['k6']['reason'] == 'Trained partner kept by automatic selection'
    assert not rows['k7']['editable']
    assert rows['k8']['source'] == 'Selected by you'
    assert rows['p1']['box'] == 0 and rows['p1']['reason'] == 'Active party is protected'
    # The coordinator's eligibility list is unchanged.
    assert [row['trade_key'] for row in trading.offers(emu, payload())] == ['k1', 'k8']


@pytest.mark.parametrize('pause', ['snapshot', 'league', 'contest'])
def test_paused_trading_still_lists_everyone_with_the_reason(emu, pause):
    if pause == 'snapshot':
        emu.snapshot = None
    elif pause == 'league':
        emu.policy.in_league = lambda snapshot: True
    else:
        emu.policy.collection['contest'] = True
    assert trading.offers(emu, payload()) == []
    rows = trading.listings(emu, payload())
    assert len(rows) == 9 and not any(row['listed'] for row in rows)
    assert all(row['reason'] for row in rows)


def test_manual_inventory_offers_everyone_and_explains_time_capsule_limits(tmp_path, monkeypatch):
    from pokesim.store import Store

    party = (SimpleNamespace(species=9, egg=False, moves=(33,), held_item=0),
             SimpleNamespace(species=175, egg=False, moves=(33,), held_item=0))
    stored = (SimpleNamespace(species=1, egg=False, moves=(33, 200), held_item=0, box=0, position=0),
              SimpleNamespace(species=2, egg=False, moves=(33,), held_item=9, box=0, position=1),
              SimpleNamespace(species=3, egg=True, moves=(), held_item=0, box=0, position=2))
    snapshot = SimpleNamespace(party=party, stored=stored, items=())
    monkeypatch.setattr(trading, 'live_status', lambda *args: {
        'party': [{'species': 9, 'slot': 1, 'trainer_id': 1, 'dvs': (1,) * 5},
                  {'species': 175, 'slot': 2, 'trainer_id': 2, 'dvs': (2,) * 5}],
        'storage': {'pokemon': [boxed(1, 1, trainer_id=3), boxed(2, 2, trainer_id=4), boxed(3, 3, egg=True, trainer_id=5)]}})
    monkeypatch.setattr(trading, 'unlocked', lambda *args: True)
    monkeypatch.setattr(trading, 'Memory', lambda *args: None)
    monkeypatch.setattr(trading, 'compatible', lambda mon, data: mon.species <= 151 and max(mon.moves) <= 165 and not mon.held_item)
    data = SimpleNamespace(item_names={9: 'FLOWER MAIL'})
    league = {'value': True}
    policy = SimpleNamespace(collection={}, in_league=lambda snap: league['value'])
    store = Store(tmp_path)
    try:
        emu = SimpleNamespace(snapshot=snapshot, policy=policy, data=data, paused=False, manual_mode=False,
                              pb=SimpleNamespace(memory=b''), status=lambda: {'game': {}})
        owner = trading.Participant(SimpleNamespace(store=store, emulator=emu),
                                    SimpleNamespace(adventure_id='gold', generation=2))
        inventory = owner.manual_inventory()
        assert inventory['reason'] == ''    # The League only delays a chosen trade.
        assert inventory['time_capsule_ready'] is True
        assert inventory['cartridge_generation'] == 2
        assert all(row['trade_key'] for row in inventory['pokemon'])
        names = {('party', 1): 'p1', ('party', 2): 'p2', ('box', 1): 'k1', ('box', 2): 'k2', ('box', 3): 'k3'}
        rows = {names[row['location'], row['slot']]: row for row in inventory['pokemon']}
        assert len(rows) == 5
        assert rows['p1']['blocked'] == '' and rows['p1']['time_capsule_compatible'] is True
        assert rows['p2']['time_capsule_reason'] == 'Red, Blue and Yellow only know the first 151 species'
        assert 'move that does not exist' in rows['k1']['time_capsule_reason']
        assert rows['k2']['blocked'] == ''
        assert 'Mail' in rows['k2']['time_capsule_reason']
        assert rows['k3']['blocked'] == 'Eggs cannot be traded'
        league['value'] = False
        policy.collection['contest'] = True
        assert owner.manual_inventory()['reason'] == 'Trading pauses during the current event'
    finally:
        store.close()
