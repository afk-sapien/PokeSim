"""Automatic trading settings: on or off, a wish list, Prefer to trade, and hand-picked trades first."""
import asyncio
import threading
import time

import pytest

from pokesim import config
from pokesim.app import trade_settings
from pokesim.app.offers import TradeOffers
from pokesim.app.registry import identifier
from pokesim.gen2 import trading as gen2_trading

from test_managed_coordinator import Peer, setup  # noqa: F401  (fixture)
from test_view_links import managed  # noqa: F401  (fixture)
from test_cable_sessions import running_loop


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


def test_settings_default_on_with_an_empty_wish_list(setup):  # noqa: F811
    aid = setup.data['left_id']
    assert trade_settings.get(setup.registry, aid) == {'enabled': True, 'wishlist': []}
    assert trade_settings.update(setup.registry, aid, enabled=False, wishlist=[25, 25, 4]) == {
        'enabled': False, 'wishlist': [25, 4]}
    assert trade_settings.get(setup.registry, aid)['enabled'] is False
    assert trade_settings.get(setup.registry, setup.data['right_id'])['enabled'] is True
    with pytest.raises(ValueError):
        trade_settings.update(setup.registry, aid, wishlist=[200], dex_total=151)
    with pytest.raises(ValueError):
        trade_settings.update(setup.registry, aid, enabled='yes')
    assert trade_settings.wanted({'wishlist': [25, 4]}, {'party': [{'dex': 25}]}) == {4}


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


def test_wish_list_makes_an_otherwise_useless_trade_worth_it(setup, monkeypatch):  # noqa: F811
    c, left = setup.coordinator, setup.data['left_id']
    monkeypatch.setattr(c, '_benefit', lambda inventory, mon: 0)
    assert c.schedule_once() is None
    # Both peers offer an Ivysaur (No. 2). The left game wishes for it and holds none.
    trade_settings.update(setup.registry, left, wishlist=[2])
    assert c.schedule_once()['phase'] == 'completed'


def test_a_held_wish_does_not_count(setup, monkeypatch):  # noqa: F811
    c, left = setup.coordinator, setup.data['left_id']
    monkeypatch.setattr(c, '_benefit', lambda inventory, mon: 0)
    trade_settings.update(setup.registry, left, wishlist=[2])
    peer = setup.peers[left]
    plain = peer.request

    def holding(method, path, data=None, timeout=None):
        result = plain(method, path, data, timeout)
        if path.endswith('/inventory'):
            result['party'] = [{'dex': 2}]
        return result
    monkeypatch.setattr(peer, 'request', holding)
    assert c.schedule_once() is None


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


def test_wish_list_hits_rank_before_trade_first(setup, monkeypatch):  # noqa: F811
    c = setup.coordinator
    third_game(setup)
    capture(c, monkeypatch)
    ids = list(setup.peers)
    setup.peers[ids[0]].offer = {'trade_preference': 'offered'}
    setup.peers[ids[1]].offer = {'dex': 7, 'arrived_dex': 7}
    trade_settings.update(setup.registry, ids[2], wishlist=[7])
    assert chosen(c) == {ids[1], ids[2]}


def test_auto_never_takes_a_pokemon_in_a_pending_hand_picked_trade(setup):  # noqa: F811
    c, left, right = setup.coordinator, setup.data['left_id'], setup.data['right_id']
    offer = setup.registry.create_trade_offer({'id': identifier(), 'from_id': left, 'from_key': '0',
                                               'to_id': right, 'to_key': 'party-1', 'display': {'from': {}, 'to': {}}})
    assert (left, '0') in c.hand_picked_keys()
    assert c.schedule_once() is None
    setup.registry.update_trade_offer(offer['id'], status='declined', reason=None)
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
    setup.manager.offers = TradeOffers(setup.manager)
    return setup


def request(setup):  # noqa: F811
    return {'from_id': setup.data['left_id'], 'from_key': '0', 'to_id': setup.data['right_id'], 'to_key': '1'}


def test_an_offer_to_an_owned_adventure_starts_at_once(owned):
    service, c = owned.manager.offers, owned.coordinator
    offer = service.create(request(owned))
    assert offer['status'] == 'accepted' and offer['manual_id']
    assert c.manual_status(offer['manual_id'])['state'] == 'queued'
    assert c.drain_manual()['phase'] == 'completed'
    assert service.status(offer['id'])['status'] == 'completed'


def test_an_offer_to_a_view_only_adventure_waits_for_an_answer(owned):
    service, right = owned.manager.offers, owned.data['right_id']
    game = owned.registry.adventure(right)
    owned.registry.update(right, settings={**game['settings'], 'viewer_only': True})
    offer = service.create(request(owned))
    assert offer['status'] == 'pending' and offer['manual_id'] is None
    assert owned.coordinator.manual_statuses()['trades'] == []


def test_an_offer_that_cannot_start_yet_stays_pending(owned, monkeypatch):
    service = owned.manager.offers
    monkeypatch.setattr(owned.coordinator, 'enqueue_manual',
                        lambda data: (_ for _ in ()).throw(ValueError('Trading is paused for application maintenance')))
    assert service.create(request(owned))['status'] == 'pending'


def test_trade_tab_lists_their_pokemon_with_hard_limits(owned):
    service, left, right = owned.manager.offers, owned.data['left_id'], owned.data['right_id']
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
    assert data['enabled'] is True and data['wishlist'] == [] and data['viewer_only'] is False
    saved = client.put(path, json={'enabled': False, 'wishlist': [25]}).json()
    assert saved['enabled'] is False and [wish['dex'] for wish in saved['wishes']] == [25]
    assert client.put(path, json={'wishlist': [400]}).status_code == 400
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
