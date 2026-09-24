"""Offers persist by individual and withdrawals reach the automatic selector."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.broker import inventory, routine
from pokesim.store import Store
from pokesim.trade import preferences
from pokesim.trade import pair
from pokesim.web import trading
from pokesim.web.app import create_app
from test_broker import status, MAGIKARP, ZUBAT


def payload(version='red', dex=MAGIKARP):
    data = status({dex}, stored=[(dex, 5), (dex, 20)], version=version)
    for i, mon in enumerate(data['storage']['pokemon']):
        mon.update(trainer_id=100, dvs=[i + 1] * 5, stat_exp=[0] * 5, position=i + 1)
    return data


def normal(data, choices=None, protected=()):
    return inventory.normalise(data['version'], '', preferences.apply(data, choices or {}), protected)


@pytest.mark.parametrize('state', ['withdrawn', 'locked'])
def test_choice_follows_box_moves_training_and_evolution_after_restart(tmp_path, state):
    data = payload()
    mon = data['storage']['pokemon'][0]
    key = preferences.identity(mon)
    store = Store(tmp_path)
    store.set_trade_preference(key, {'state': state})
    store.close()
    moved = deepcopy(data)
    moved['storage']['pokemon'][0].update(box=5, position=9, level=55, nick='NEW NAME', species=22, stat_exp=[999] * 5)
    store = Store(tmp_path)
    rows = preferences.apply(moved, store.trade_preferences())['storage']['pokemon']
    assert rows[0]['trade_key'] == key
    assert rows[0]['trade_preference'] == state
    assert rows[0]['trade_locked'] == (state == 'locked')
    assert rows[1]['trade_preference'] == 'auto'
    assert 'trade_key' not in mon
    store.close()


def test_withdrawal_excludes_automatic_and_last_copy_offers():
    data = payload()
    key = preferences.identity(data['storage']['pokemon'][0])
    red = normal(data, {key: {'state': 'withdrawn'}})
    blue = normal(payload('blue', ZUBAT))
    assert not routine.proposals([red, blue], allow_last_copies=True)
    row = routine.listings(red)[0]
    assert not row['listed'] and row['reason'] == 'Withdrawn by you'
    data['storage']['pokemon'] = data['storage']['pokemon'][:1]
    assert not routine.offers(normal(data, {key: {'state': 'withdrawn'}}), True)


def test_manual_duplicate_expands_offers_and_is_selected_automatically():
    data = payload()
    key = preferences.identity(data['storage']['pokemon'][1])
    red = normal(data, {key: {'state': 'offered'}})
    blue = normal(payload('blue', ZUBAT))
    assert len(routine.offers(red, False)) == 2
    deal, = routine.proposals([red, blue])
    assert deal['give']['trade_key'] == key
    assert deal['spends']['give'] == 'best copy'


def test_manual_offer_does_not_bypass_project_or_last_copy_protection():
    data = payload()
    mon = data['storage']['pokemon'][1]
    key = preferences.identity(mon)
    choice = {key: {'state': 'offered'}}
    protected = normal(data, choice, [mon['species']])
    assert not routine.offers(protected, True)
    data['storage']['pokemon'] = [mon]
    assert not routine.offers(normal(data, choice), False)


def test_ambiguous_individuals_are_never_spent():
    data = payload()
    a, b = data['storage']['pokemon']
    b['dvs'] = a['dvs'][:]
    key = preferences.identity(a)
    red = normal(data, {key: {'state': 'offered'}})
    assert not routine.offers(red, True)
    assert all(not row['editable'] for row in routine.listings(red))


def test_hold_blocks_preference_changes_atomically(tmp_path):
    store = Store(tmp_path)
    store.set('trade_hold', {'id': '123', 'phase': 'prepared'})
    with pytest.raises(ValueError, match='in progress'):
        store.set_trade_preference('example', {'state': 'withdrawn'})
    assert store.trade_preferences() == {}
    store.close()


@pytest.fixture
def game(tmp_path, monkeypatch):
    store = Store(tmp_path)
    data = payload()
    emu = Mock()
    emu.status.return_value = {'game': {'party': [], 'storage': data['storage']},
                               'strategy': {'collection': {'version': 'red'}}}
    from pokesim.web.pokedex import live_status
    emu.set_trade_preference.side_effect = lambda key, state: preferences.update(
        store, live_status(emu.status()['game']), key, state)
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    monkeypatch.setattr(config, 'TRADING_INSTANCE', 'red')
    monkeypatch.setattr(config, 'TRADING_URL', '')
    with TestClient(create_app(emu, store)) as client:
        yield client, store, emu
    store.close()


def test_local_preference_endpoint_validates_individual_and_view_only(game, monkeypatch):
    client, store, emu = game
    key = client.get('/api/pokedex/status').json()['storage']['pokemon'][0]['trade_key']
    assert client.post('/api/trading/preferences', json={'key': key, 'state': 'offered'}).status_code == 200
    assert store.trade_preferences()[key]['state'] == 'offered'
    assert client.post('/api/trading/preferences', json={'key': 'stale', 'state': 'withdrawn'}).status_code == 409
    assert client.post('/api/trading/preferences', json={'key': key, 'state': 'execute'}).status_code == 422
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    assert client.post('/api/trading/preferences', json={'key': key, 'state': 'withdrawn'}).status_code == 403
    emu.trade.assert_not_called()
    emu.command.assert_not_called()


def test_local_trade_page_navigation_and_disconnected_state(game):
    client, _, _ = game
    page = client.get('/trading')
    assert page.status_code == 200
    assert '/static/panel-trading.css' in page.text and '/static/trading.js' in page.text
    assert 'Trade broker' not in page.text
    for path in ('/', '/pc', '/pokedex', '/journal'):
        assert 'href="/trading"' in client.get(path).text
    data = client.get('/api/trading').json()
    assert data['connected'] is False
    assert data['opportunities'] == []
    assert 'not connected' in data['message']


def test_each_game_sees_its_own_send_receive_and_history():
    red, blue = normal(payload()), normal(payload('blue', ZUBAT))
    deal, = routine.proposals([red, blue])
    moved = [{'instance': 'red', 'sent': deal['give'], 'received': deal['take']},
             {'instance': 'blue', 'sent': deal['take'], 'received': deal['give']}]
    board = {'instances': [{**inv.summary(), 'offers': routine.listings(inv)} for inv in (red, blue)],
             'routine_proposals': [deal], 'trading': {'enabled': True,
             'history': [{'id': '1', 'ts': 10, 'reason': deal['reason'], 'moved': moved}]}}
    for name, send in [('red', MAGIKARP), ('blue', ZUBAT)]:
        result = trading.perspective(payload(name), board, name)
        assert result['opportunities'][0]['send']['dex'] == send
        assert result['history'][0]['sent']['dex'] == send
        assert result['history'][0]['received']['dex'] != send
        assert result['trading']['enabled']


def test_new_adventure_clears_only_offer_preferences(tmp_path):
    store = Store(tmp_path)
    store.set('other_setting', 12)
    store.set_trade_preference('example', {'state': 'offered'})
    store.clear_trade_preferences()
    assert store.trade_preferences() == {}
    assert store.get('other_setting') == 12
    store.close()


@pytest.mark.parametrize('state', ['withdrawn', 'locked'])
def test_checkpoint_staging_rechecks_saved_withdrawals(tmp_path, monkeypatch, state):
    root = tmp_path / 'coordinator'
    root.mkdir()
    (root / 'policy.json').write_text(json.dumps({'allow_last_copies': True}))
    pair_root = tmp_path / 'pair'
    monkeypatch.setattr(pair, 'PAIR_ROOT', pair_root)
    snapshots = {}
    for name, dex in [('red', MAGIKARP), ('blue', ZUBAT)]:
        data = payload(name, dex)
        store = Store(pair_root / name)
        if name == 'red':
            for mon in data['storage']['pokemon']:
                store.set_trade_preference(preferences.identity(mon), {'state': state})
        (store.states / 'auto-test.state').write_bytes(b'test checkpoint')
        (store.states / 'auto-test.json').write_text('{}')
        snapshot = Mock()
        snapshot.to_dict.return_value = {'party': [], 'storage': data['storage'], 'dex_owned': [dex]}
        snapshots[name] = snapshot
        store.close()
    monkeypatch.setattr(pair, 'inspect', lambda rom, state: (snapshots[state.parent.parent.name],
                        {'policy_state': {'collection': {}}}, {}))
    perform = Mock()
    monkeypatch.setattr(pair, 'perform', perform)
    pair.stage(root, '123')
    result = json.loads((root / 'transactions/123/result.json').read_text())
    assert result['status'] == 'no_opportunity'
    perform.assert_not_called()


def test_completed_trade_clears_preference_once_with_its_journal(tmp_path, monkeypatch):
    store = Store(tmp_path / 'pair/red')
    key = 'selected-partner'
    store.set_trade_preference(key, {'state': 'offered'})
    monkeypatch.setattr(pair, 'PAIR_ROOT', tmp_path / 'pair')
    transaction = tmp_path / 'transactions/123'
    transaction.mkdir(parents=True)
    moved = {'instance': 'red', 'sent': {'nick': 'OLD'},
             'received': {'nick': 'NEW', 'name': 'Zubat', 'level': 8, 'evolved_from': None}}
    (transaction / 'result.json').write_text(json.dumps({'moved': [moved], 'reason': 'Useful exchange',
        'proposal': {'give': {'instance': 'red', 'trade_key': key}}}))
    pair.journal(tmp_path, '123')
    pair.journal(tmp_path, '123')
    assert store.trade_preferences() == {}
    assert len(store.events(types=['trade'])) == 1
    store.close()


def test_lock_overrides_offer_and_requires_explicit_unlock(game):
    client, store, _ = game
    key = client.get('/api/pokedex/status').json()['storage']['pokemon'][1]['trade_key']
    def change(state):
        return client.post('/api/trading/preferences', json={'key': key, 'state': state})
    assert change('offered').status_code == 200
    assert change('locked').status_code == 200
    for state in ('offered', 'withdrawn', 'auto'):
        assert change(state).status_code == 409
        assert store.trade_preferences()[key]['state'] == 'locked'
    row = next(mon for mon in client.get('/api/trading').json()['offers'] if mon['trade_key'] == key)
    assert row['locked'] and not row['listed'] and not row['can_offer']
    assert 'Locked' in row['reason']
    assert change('unlocked').status_code == 200
    assert store.trade_preferences()[key]['state'] == 'auto'
    row = next(mon for mon in client.get('/api/trading').json()['offers'] if mon['trade_key'] == key)
    assert not row['locked'] and not row['listed']
    assert change('unlocked').status_code == 409


def test_locked_partner_cannot_join_any_trade_planner():
    from pokesim.broker import negotiation
    data = payload()
    key = preferences.identity(data['storage']['pokemon'][0])
    red = normal(data, {key: {'state': 'locked'}})
    blue = normal(payload('blue', ZUBAT))
    assert key not in {mon.trade_key for mon in red.tradeable}
    assert not routine.proposals([red, blue], allow_last_copies=True)
    assert all(side.get('trade_key') != key or side['instance'] != 'red' for deal in negotiation.proposals([red, blue])
               for side in (deal['give'], deal['take']))


@pytest.mark.parametrize('state', ['locked', 'unlocked'])
def test_lock_mutations_respect_view_only_and_exchange_holds(game, monkeypatch, state):
    client, store, _ = game
    key = client.get('/api/pokedex/status').json()['storage']['pokemon'][0]['trade_key']
    store.set_trade_preference(key, {'state': 'locked'})
    body = {'key': key, 'state': state}
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    assert client.post('/api/trading/preferences', json=body).status_code == 403
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    store.set('trade_hold', {'id': '123', 'phase': 'prepared'})
    assert client.post('/api/trading/preferences', json=body).status_code == 409
    assert store.trade_preferences()[key]['state'] == 'locked'
