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
