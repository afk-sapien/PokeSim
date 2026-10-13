"""Automatic trading settings: on or off, Prefer to trade, and hand-picked trades first."""
import asyncio
import threading
import time

import pytest

from pokesim import config
from pokesim.app import trade_settings
from pokesim.app.trade_builder import TradeBuilder, ViewOnlyError
from pokesim.app.registry import identifier
from pokesim.gen2 import trading as gen2_trading

from test_managed_coordinator import Peer, setup  # noqa: F401  (fixture)
from test_view_links import managed  # noqa: F401  (fixture)


def running_loop():
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class Chosen(Exception):
    pass


def capture(coordinator, monkeypatch):
    def propose(data):
        raise Chosen(data)
    monkeypatch.setattr(coordinator, 'propose', propose)


def chosen(coordinator):
    with pytest.raises(Chosen) as picked:
        coordinator.schedule_once()
    data = picked.value.args[0]
    return {data['left_id'], data['right_id']}


class SlowRegistry:
    """Holds the shared value and pauses between reading it and writing it back."""
    def __init__(self):
        self.values = {}

    def setting(self, key, default=None):
        value = self.values.get(key, default)
        time.sleep(0.01)
        return {**value} if isinstance(value, dict) else value

    def set_setting(self, key, value):
        self.values[key] = value


def test_changes_to_different_adventures_at_once_all_stick():
    registry = SlowRegistry()
    ids = [identifier() for _ in range(8)]
    threads = [threading.Thread(target=trade_settings.update, args=(registry, aid), kwargs={'enabled': False})
               for aid in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(trade_settings.get(registry, aid)['enabled'] is False for aid in ids)


def test_settings_default_on_and_switch_per_adventure(setup):  # noqa: F811
    aid = setup.data['left_id']
    assert trade_settings.get(setup.registry, aid) == {'enabled': True}
    assert trade_settings.update(setup.registry, aid, enabled=False) == {'enabled': False}
    assert trade_settings.get(setup.registry, aid)['enabled'] is False
    assert trade_settings.get(setup.registry, setup.data['right_id'])['enabled'] is True
    with pytest.raises(ValueError):
        trade_settings.update(setup.registry, aid, enabled='yes')


def test_an_old_stored_wish_list_is_ignored_and_kept(setup, monkeypatch):  # noqa: F811
    """The wish list is gone. One saved by an earlier build neither crashes nor changes trades, and stays stored."""
    c, left = setup.coordinator, setup.data['left_id']
    setup.registry.set_setting(trade_settings.KEY, {left: {'enabled': True, 'wishlist': [2, 'bad', 999]}, 'junk': 5})
    assert trade_settings.get(setup.registry, left) == {'enabled': True}
    monkeypatch.setattr(c, '_benefit', lambda inventory, mon: 0)
    # Both peers offer an Ivysaur (No. 2). An old wish for it no longer makes a useless trade worth it.
    assert c.schedule_once() is None
    trade_settings.update(setup.registry, left, enabled=False)
    assert setup.registry.setting(trade_settings.KEY)[left] == {'enabled': False, 'wishlist': [2, 'bad', 999]}


def test_auto_off_stops_automatic_trades_only(setup):  # noqa: F811
    c, left = setup.coordinator, setup.data['left_id']
    trade_settings.update(setup.registry, left, enabled=False)
    assert c.schedule_once() is None
    assert setup.cable_calls == []
    # A hand-picked trade still reaches a game with auto trading off.
    entry = c.enqueue_manual({**setup.data, 'request_id': identifier()})
    assert c.drain_manual()['phase'] == 'completed'
    assert setup.cable_calls == [entry['id']]
    trade_settings.update(setup.registry, left, enabled=True)
    setup.registry.db.execute('UPDATE interactions SET updated_at=0')
    assert c.schedule_once()['phase'] == 'completed'


def third_game(setup):  # noqa: F811
    game = setup.registry.create('Third Red', 'rom', {}, identifier())
    setup.registry.update(game['id'], state='running', desired_state='running')
    setup.peers[game['id']] = Peer(game['id'], '2')
    return game['id']


def test_trade_first_pokemon_are_used_before_anything_else(setup, monkeypatch):  # noqa: F811
    c = setup.coordinator
    third = third_game(setup)
    capture(c, monkeypatch)
    before = chosen(c)
    outsider = next(aid for aid in setup.peers if aid not in before)
    setup.peers[outsider].offer = {'trade_preference': 'offered'}
    assert outsider in chosen(c)
    assert third in setup.peers


def test_stored_trade_offers_are_ignored(setup):  # noqa: F811
    """Offers left from before 0.5.0 stay in the registry but no longer hold any Pokémon back."""
    c, left, right = setup.coordinator, setup.data['left_id'], setup.data['right_id']
    setup.registry.create_trade_offer({'id': identifier(), 'from_id': left, 'from_key': '0',
                                       'to_id': right, 'to_key': 'party-1', 'display': {'from': {}, 'to': {}}})
    assert (left, '0') not in c.hand_picked_keys()
    assert c.schedule_once()['phase'] == 'completed'


def test_hand_picked_trades_queue_ahead_of_auto(setup):  # noqa: F811
    c = setup.coordinator
    entry = c.enqueue_manual({**setup.data, 'request_id': identifier()})
    assert {(setup.data['left_id'], '0'), (setup.data['right_id'], '1')} <= c.hand_picked_keys()
    result = c.schedule_once()
    assert result['id'] == entry['id'] and setup.cable_calls == [entry['id']]


def test_shinies_never_trade_automatically_even_when_set_to_trade_first(setup):  # noqa: F811
    setup.peers[setup.data['left_id']].offer = {'shiny': True, 'trade_preference': 'offered'}
    assert setup.coordinator.schedule_once() is None
    mon = {'trade_key': 'k', 'shiny': True, 'trade_preference': 'offered', 'dvs': [1] * 5, 'species': 25}
    assert gen2_trading._kept(mon, set())
    assert gen2_trading._kept({**mon, 'shiny': False}, set()) == ''


@pytest.fixture
def owned(setup):  # noqa: F811
    setup.manager.coordinator = setup.coordinator
    setup.manager.builder = TradeBuilder(setup.manager)
    return setup


def request(setup):  # noqa: F811
    return {'from_id': setup.data['left_id'], 'from_key': '0', 'to_id': setup.data['right_id'], 'to_key': '1'}


def test_a_built_trade_queues_at_once_and_shows_on_both_adventures(owned):
    service, c, left, right = owned.manager.builder, owned.coordinator, owned.data['left_id'], owned.data['right_id']
    body = {**request(owned), 'request_id': identifier()}
    trade = service.create(body)
    assert trade['state'] == 'queued' and trade['left_id'] == left and trade['right_id'] == right
    # Sending the same request again returns the same trade instead of queueing a second one.
    assert service.create(body)['id'] == trade['id'] and len(c.manual_statuses()['trades']) == 1
    for aid in (left, right):
        queued = c.adventure_status(aid)['queued']
        assert [row['id'] for row in queued] == [trade['id']] and queued[0]['position'] == 1
    assert c.drain_manual()['phase'] == 'completed'
    assert c.manual_status(trade['id'])['phase'] == 'completed'
    assert c.adventure_status(left)['queued'] == []


def test_a_view_only_adventure_cannot_take_a_built_trade(owned):
    service, left, right = owned.manager.builder, owned.data['left_id'], owned.data['right_id']
    game = owned.registry.adventure(right)
    owned.registry.update(right, settings={**game['settings'], 'viewer_only': True})
    row = service.targets(left)['adventures'][0]
    assert row['available'] is False and 'view-only' in row['reason']
    assert service.limits(left, '0', right)['starts_now'] is False
    with pytest.raises(ViewOnlyError):
        service.create(request(owned))
    assert owned.coordinator.manual_statuses()['trades'] == []


def test_a_built_trade_checks_hard_limits_first(owned):
    service, right = owned.manager.builder, owned.data['right_id']
    owned.peers[right].pokemon[1]['blocked'] = 'Eggs cannot be traded'
    with pytest.raises(ValueError, match='Eggs cannot be traded'):
        service.create({**request(owned), 'to_key': 'party-1'})
    with pytest.raises(ValueError, match='Choose a Pokémon'):
        service.create({**request(owned), 'extra': 1})
    assert owned.coordinator.manual_statuses()['trades'] == []


def test_trade_tab_lists_their_pokemon_with_hard_limits(owned):
    service, left, right = owned.manager.builder, owned.data['left_id'], owned.data['right_id']
    owned.peers[right].pokemon[1]['blocked'] = 'Eggs cannot be traded'
    limits = service.limits(left, '0', right)
    rows = {row['key']: row for row in limits['pokemon']}
    assert rows['1']['blocked'] == '' and rows['party-1']['blocked'] == 'Eggs cannot be traded'
    assert limits['starts_now'] is True
    mine = service.pokemon(left)
    assert [row['key'] for row in mine['pokemon']] == ['0', 'party-0'] and mine['reason'] == ''
    owned.registry.update(left, state='stopped', desired_state='stopped')
    assert service.pokemon(left)['reason'] == 'Start this adventure to trade from it'


def test_auto_settings_route_reads_writes_and_respects_view_only(managed, monkeypatch):  # noqa: F811
    client, aid = managed.client, managed.aid
    path = f'/api/v1/interactions/auto-settings?adventure_id={aid}'
    data = client.get(path).json()
    assert data == {'adventure_id': aid, 'enabled': True, 'viewer_only': False}
    saved = client.put(path, json={'enabled': False}).json()
    assert saved == {'adventure_id': aid, 'enabled': False, 'viewer_only': False}
    assert client.put(path, json={'wishlist': [25]}).status_code == 400
    assert client.put(path, json={'other': 1}).status_code == 400
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    assert client.put(path, json={'enabled': True}).status_code == 403
    assert client.get(path).json()['enabled'] is False


def test_saving_auto_settings_reads_the_registry_off_the_event_loop(managed, monkeypatch):  # noqa: F811
    client, aid = managed.client, managed.aid
    registry = managed.manager.registry
    on_loop = []
    real = registry.adventure

    def adventure(*args, **kwargs):
        on_loop.append(running_loop())
        return real(*args, **kwargs)
    monkeypatch.setattr(registry, 'adventure', adventure)
    response = client.put(f'/api/v1/interactions/auto-settings?adventure_id={aid}', json={'enabled': False})
    assert response.status_code == 200 and on_loop and not any(on_loop)
