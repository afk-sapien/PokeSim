"""The trade builder: the owner picks a Pokémon in two adventures, and only hard limits stop the trade.

In 0.5.0 trading is automatic or built by hand, so trade offers, manual Cable Club
sessions and Ask me first suggestions have no routes and no tab.
"""
import re

import pytest

from pokesim import config
from pokesim.app import trade_requests, trade_settings
from pokesim.app.registry import identifier
from pokesim.app.coordinator import BUSY_NOTE, MANUAL_KEY
from pokesim.app.trade_builder import HardLimit, TradeBuilder, ViewOnlyError
from pokesim.runtime.participant import BUSY
from pokesim.web.pages import render_game_page

from test_managed_coordinator import setup  # noqa: F401  (fixture)
from test_view_links import managed, writes  # noqa: F401  (fixtures)


@pytest.fixture
def built(setup):  # noqa: F811
    setup.manager.coordinator = setup.coordinator
    setup.manager.builder = TradeBuilder(setup.manager)
    for peer in setup.peers.values():
        peer.pokemon[0].update(level=20, power=180, battle_power=95)
    return setup


def test_picker_lists_targets_and_hard_limits(built):
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    targets = service.targets(left)
    assert [row['id'] for row in targets['adventures']] == [right]
    assert targets['adventures'][0]['available'] is True
    built.peers[right].pokemon[1]['blocked'] = 'Eggs cannot be traded'
    limits = service.limits(left, '0', right)
    assert limits['blocked'] == {'party-1': 'Eggs cannot be traded'}
    assert limits['from']['name'] == 'Ivysaur' and limits['from']['blocked'] == ''
    built.registry.update(right, state='stopped', desired_state='stopped')
    assert service.targets(left)['adventures'][0]['reason'] == 'Start this adventure to trade from it'


def make_crystal(peer, *, ready=True, compatible=True):
    peer.generation, peer.capsule_ready = 2, ready
    for mon in peer.pokemon:
        mon.update(cartridge_generation=2, time_capsule_compatible=compatible,
                   time_capsule_reason='' if compatible else 'Togepi did not exist in Gen I')


def test_targets_grey_out_games_that_cannot_take_the_chosen_pokemon(built):
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    row = service.targets(left, '0')['adventures'][0]
    assert row['id'] == right and row['available'] is True and row['reason'] == ''
    # A Gen II-only Pokémon cannot go to a Red game, so Red is greyed out before its PC opens.
    make_crystal(built.peers[left], compatible=False)
    row = service.targets(left, '0')['adventures'][0]
    assert row['available'] is False
    assert 'cannot go to a Red, Blue or Yellow game' in row['reason'] and 'Togepi did not exist in Gen I' in row['reason']
    assert service.targets(left)['adventures'][0]['available'] is True
    make_crystal(built.peers[left], ready=False)
    assert 'Time Capsule yet' in service.targets(left, '0')['adventures'][0]['reason']
    make_crystal(built.peers[left])
    assert service.targets(left, '0')['adventures'][0]['available'] is True
    built.peers[left].pokemon[0]['blocked'] = 'Eggs cannot be traded'
    assert service.targets(left, '0')['adventures'][0]['reason'] == 'Eggs cannot be traded'
    with pytest.raises(ValueError, match='no longer in First Red'):
        service.targets(left, 'missing')


def test_targets_grey_out_a_game_when_every_pair_is_blocked(built):
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    for mon in built.peers[right].pokemon:
        mon['blocked'] = 'Eggs cannot be traded'
    row = service.targets(left, '0')['adventures'][0]
    assert row['available'] is False and row['reason'] == 'Eggs cannot be traded'
    built.peers[right].pokemon[1]['blocked'] = 'This is the last party member that can battle'
    assert service.targets(left, '0')['adventures'][0]['reason'] == 'Nothing in Second Red can be traded for Ivysaur'


def hold(built, monkeypatch, aid, tid, *, empty=False):
    """Hold one adventure for the exchange tid, as its worker does while it trades."""
    peer = built.peers[aid]
    plain = peer.request
    state = {'holding': True}

    def busy(method, path, data=None, timeout=None):
        result = plain(method, path, data, timeout)
        if path.endswith('/manual-inventory') and state['holding']:
            result.update(holding=True, hold_id=tid, reason=BUSY, **({'pokemon': []} if empty else {}))
        return result
    monkeypatch.setattr(peer, 'request', busy)
    return state


def test_a_game_busy_with_a_trade_can_be_picked_and_shows_its_last_known_pokemon(built, monkeypatch):
    service, c, left, right = built.manager.builder, built.coordinator, built.data['left_id'], built.data['right_id']
    assert service.pokemon(right)['busy'] == ''    # Seen free once, so its Pokémon are known.
    tid = identifier()
    built.registry.create_transaction(tid, {'participants': [right, left]})
    hold(built, monkeypatch, right, tid, empty=True)
    row = service.targets(left, '0')['adventures'][0]
    assert row['available'] is True and row['reason'] == ''
    assert row['busy'] == BUSY_NOTE == 'Busy with a trade. Your trade will wait in line.'
    assert service.targets(left)['adventures'][0]['busy'] == BUSY_NOTE
    theirs = service.pokemon(right)
    assert theirs['reason'] == '' and theirs['busy'] == BUSY_NOTE
    assert [mon['key'] for mon in theirs['pokemon']] == ['1', 'party-1']
    assert service.limits(left, '0', right)['busy'] == BUSY_NOTE
    # A worker that cannot answer while it trades still shows what it had.
    built.peers[right].failures['manual-inventory'] = 1
    assert [mon['key'] for mon in service.pokemon(right)['pokemon']] == ['1', 'party-1']
    assert c.manual_inventory(right)['busy_with'] == 'First Red'


def test_a_trade_with_a_busy_game_is_queued_and_runs_once_the_hold_clears(built, monkeypatch):
    service, c, left, right = built.manager.builder, built.coordinator, built.data['left_id'], built.data['right_id']
    tid = identifier()
    built.registry.create_transaction(tid, {'participants': [right, left]})
    held = hold(built, monkeypatch, right, tid)
    trade = service.create({'from_id': left, 'from_key': '0', 'to_id': right, 'to_key': '1'})
    assert trade['state'] == 'queued' and trade['position'] == 1 and trade['cancellable'] is True
    card = c.adventure_status(left)['queued'][0]
    assert card['busy'] is True and card['cancellable'] is True and card['peer_name'] == 'Second Red'
    # It waits while the other exchange runs, and nothing is prepared for it yet.
    assert c.drain_manual() is None and c.schedule_once() is None
    assert c.manual_status(trade['id'])['state'] == 'queued'
    assert built.cable_calls == [] and all(peer.prepared == [] for peer in built.peers.values())
    # The exchange finished but the worker still holds the game: still in line, not refused.
    built.registry.update_transaction(tid, phase='aborted', decision='ABORT')
    assert c.drain_manual() is None
    assert c.manual_status(trade['id'])['state'] == 'queued'
    held['holding'] = False
    assert c.drain_manual()['phase'] == 'completed'
    assert c.manual_status(trade['id'])['phase'] == 'completed'
    assert built.cable_calls == [trade['id']]


def test_a_queued_trade_whose_pokemon_left_is_cancelled_at_its_turn(built, monkeypatch):
    service, c, left, right = built.manager.builder, built.coordinator, built.data['left_id'], built.data['right_id']
    tid = identifier()
    built.registry.create_transaction(tid, {'participants': [right, left]})
    held = hold(built, monkeypatch, right, tid)
    trade = service.create({'from_id': left, 'from_key': 'party-0', 'to_id': right, 'to_key': '1'})
    assert c.manual_status(trade['id'])['state'] == 'queued'
    built.registry.update_transaction(tid, phase='completed', decision='COMMIT')
    held['holding'] = False
    built.peers[left].pokemon = [mon for mon in built.peers[left].pokemon if mon['trade_key'] != 'party-0']
    assert c.drain_manual() is None
    status = c.manual_status(trade['id'])
    assert status['state'] == 'rejected'
    assert status['error'] == 'Cancelled: Pikachu is no longer in First Red’s party or boxes'
    # Neither save was touched: no exchange was recorded and no worker prepared anything.
    assert [row['id'] for row in built.registry.transactions()] == [tid]
    assert built.cable_calls == [] and all(peer.prepared == [] for peer in built.peers.values())


def test_hard_limits_still_refuse_a_trade_with_a_busy_game(built, monkeypatch):
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    tid = identifier()
    built.registry.create_transaction(tid, {'participants': [right, left]})
    hold(built, monkeypatch, right, tid)
    built.peers[right].pokemon[0]['blocked'] = 'Eggs cannot be traded'
    with pytest.raises(HardLimit, match='Eggs cannot be traded'):
        service.create({'from_id': left, 'from_key': '0', 'to_id': right, 'to_key': '1'})
    built.registry.update(right, state='stopped', desired_state='stopped')
    with pytest.raises(ValueError, match='Start this adventure'):
        service.create({'from_id': left, 'from_key': '0', 'to_id': right, 'to_key': 'party-1'})
    assert built.coordinator.manual_statuses()['trades'] == []


def test_only_a_trade_still_in_line_can_be_cancelled(built):
    service, c = built.manager.builder, built.coordinator
    left, right = built.data['left_id'], built.data['right_id']
    first = service.create({'from_id': left, 'from_key': '0', 'to_id': right, 'to_key': '1'})
    second = service.create({'from_id': left, 'from_key': 'party-0', 'to_id': right, 'to_key': 'party-1'})
    assert c.manual_status(second['id'])['position'] == 2
    status = service.cancel(second['id'])
    assert status['state'] == 'cancelled' and status['cancellable'] is False
    assert c.adventure_status(left)['queued'] == [c.adventure_status(left)['queued'][0]]
    c._manual_update(first['id'], state='starting')
    with pytest.raises(ValueError, match='already started'):
        service.cancel(first['id'])
    c._manual_update(first['id'], state='queued')
    assert c.drain_manual()['phase'] == 'completed'
    with pytest.raises(ValueError, match='already started'):
        service.cancel(first['id'])
    assert built.cable_calls == [first['id']]
    with pytest.raises(KeyError):
        service.cancel(identifier())
    game = built.registry.adventure(left)
    third = service.create({'from_id': left, 'from_key': '0', 'to_id': right, 'to_key': '1'})
    built.registry.update(left, settings={**game['settings'], 'viewer_only': True})
    with pytest.raises(ViewOnlyError):
        service.cancel(third['id'])
    assert c.manual_status(third['id'])['state'] == 'queued'


def test_the_library_lists_every_trade_waiting_in_line(built):
    service, c = built.manager.builder, built.coordinator
    left, right = built.data['left_id'], built.data['right_id']
    assert c.status()['queued'] == []
    first = service.create({'from_id': left, 'from_key': '0', 'to_id': right, 'to_key': '1'})
    second = service.create({'from_id': left, 'from_key': 'party-0', 'to_id': right, 'to_key': 'party-1'})
    c._manual_update(first['id'], state='starting')
    queued = c.status()['queued']
    assert [(row['id'], row['position'], row['state'], row['cancellable']) for row in queued] == [
        (first['id'], 1, 'starting', False), (second['id'], 2, 'queued', True)]
    assert {row['left_id'] for row in queued} == {left} and {row['right_id'] for row in queued} == {right}
    assert all(set(row['names']) == {'left', 'right'} for row in queued)
    service.cancel(second['id'])
    assert [row['id'] for row in c.status()['queued']] == [first['id']]


def test_the_cancel_route_takes_a_waiting_trade_out_of_line(managed):  # noqa: F811
    manager, client, aid = managed.app.state.manager, managed.client, managed.aid
    assert ('POST', f'/api/v1/interactions/trade-builder/{aid}/cancel') in writes(managed.app, aid)
    other = manager.registry.create('Other', 'fixture', {}, identifier())
    waiting, started = identifier(), identifier()
    base = {'left_id': aid, 'right_id': other['id'], 'left_key': 'a', 'right_key': 'b', 'error': None,
            'cancel_requested': False, 'created_at': 1, 'updated_at': 1}
    manager.registry.set_setting(MANUAL_KEY, [{**base, 'id': waiting, 'state': 'queued'},
                                              {**base, 'id': started, 'state': 'starting'}])
    response = client.post(f'/api/v1/interactions/trade-builder/{waiting}/cancel')
    assert response.status_code == 200 and response.json()['state'] == 'cancelled'
    response = client.post(f'/api/v1/interactions/trade-builder/{started}/cancel')
    assert response.status_code == 409 and 'already started' in response.json()['detail']
    assert client.post(f'/api/v1/interactions/trade-builder/{identifier()}/cancel').status_code == 404
    assert client.post(f'/view/{aid}/api/v1/interactions/trade-builder/{waiting}/cancel').status_code in {403, 404}


def test_limits_report_a_limit_of_the_chosen_pokemon_once(built):
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    make_crystal(built.peers[left], compatible=False)
    limits = service.limits(left, '0', right)
    assert 'cannot go to a Red, Blue or Yellow game' in limits['from']['blocked']
    assert limits['blocked'] == {}


@pytest.mark.parametrize('instance', [False, True])
def test_view_only_adventures_cannot_build_a_trade(built, monkeypatch, instance):
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    if instance:
        monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    else:
        game = built.registry.adventure(left)
        built.registry.update(left, settings={**game['settings'], 'viewer_only': True})
    with pytest.raises(ViewOnlyError):
        service.create({'from_id': left, 'from_key': '0', 'to_id': right, 'to_key': '1'})
    assert service.pokemon(left)['viewer_only'] is True
    assert built.coordinator.manual_statuses()['trades'] == []


def test_builder_routes_pass_through_and_refuse_view_only(managed, monkeypatch):  # noqa: F811
    manager, client, aid = managed.app.state.manager, managed.client, managed.aid
    assert ('POST', '/api/v1/interactions/trade-builder') in writes(managed.app, aid)
    seen = []
    monkeypatch.setattr(manager.builder, 'targets', lambda from_id, from_key=None: seen.append((from_id, from_key)) or {})
    assert client.get(f'/api/v1/interactions/trade-builder/targets?from_id={aid}&from_key=box-3').status_code == 200
    assert client.get(f'/api/v1/interactions/trade-builder/targets?from_id={aid}').status_code == 200
    assert seen == [(aid, 'box-3'), (aid, None)]
    other = manager.registry.create('Other', 'fixture', {}, identifier())
    manager.registry.update(other['id'], state='running')
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    body = {'from_id': aid, 'from_key': 'b', 'to_id': other['id'], 'to_key': 'a'}
    assert client.post('/api/v1/interactions/trade-builder', json=body).status_code == 403
    assert client.post(f'/view/{aid}/api/v1/interactions/trade-builder', json=body).status_code in {403, 404}


def test_offer_and_cable_session_routes_are_gone(managed):  # noqa: F811
    client, aid, oid = managed.client, managed.aid, identifier()
    routes = {path for _, path in writes(managed.app, aid)}
    assert not any('trade-offers' in path or 'cable-sessions' in path for path in routes)
    for method, path in [
            ('GET', f'/api/v1/interactions/trade-offers?adventure_id={aid}'),
            ('GET', f'/api/v1/interactions/trade-offers/targets?from_id={aid}'),
            ('GET', f'/api/v1/interactions/trade-offers/limits?from_id={aid}&from_key=a&to_id={aid}'),
            ('GET', f'/api/v1/interactions/trade-offers/pokemon?adventure_id={aid}'),
            ('GET', f'/api/v1/interactions/trade-offers/{oid}'),
            ('POST', '/api/v1/interactions/trade-offers'),
            ('POST', f'/api/v1/interactions/trade-offers/{oid}/accept'),
            ('POST', f'/api/v1/interactions/trade-offers/{oid}/decline'),
            ('POST', f'/api/v1/interactions/trade-offers/{oid}/withdraw'),
            ('GET', f'/api/v1/interactions/cable-sessions/partners?adventure_id={aid}'),
            ('GET', f'/api/v1/interactions/cable-sessions/{oid}'),
            ('POST', '/api/v1/interactions/cable-sessions'),
            ('POST', f'/api/v1/interactions/cable-sessions/{oid}/input'),
            ('POST', f'/api/v1/interactions/cable-sessions/{oid}/finish'),
            ('GET', f'/games/{aid}/cable'),
            ('GET', f'/games/{aid}/api/cable'),
            ('GET', f'/view/{aid}/cable'),
            ('GET', f'/view/{aid}/api/cable'),
            ('GET', '/static/cable-club.html')]:
        response = client.request(method, path, json={} if method == 'POST' else None)
        assert response.status_code == 404, (method, path, response.status_code)


@pytest.mark.parametrize('viewer', [False, True])
def test_trading_page_has_no_offers_or_cable_club_tab(viewer):
    html = render_game_page('adventure-trading.html', base_path=f'/{"view" if viewer else "games"}/{"a" * 32}',
                            adventure_id='a' * 32, adventure_name='Gold', viewer=viewer)
    tabs = re.findall(r'role="tab" id="tab-([a-z]+)"', html)
    assert tabs == ['trade', 'auto', 'history']
    for gone in ('tab-offers', 'panel-offers', 'offers-count', 'tab-cable', 'panel-cable', 'cable-games', 'Send offer',
                 'ask-switch', 'trade-requests', 'Ask me first', 'Suggested trades'):
        assert gone not in html


def test_automatic_trades_start_on_their_own_whatever_ask_me_first_said(setup):  # noqa: F811
    # A library from rc44 may have Ask me first on and suggestions waiting. Both are ignored.
    trade_settings.set_ask_first(setup.registry, True)
    setup.registry.set_setting(trade_requests.KEY, {'requests': [
        {'id': identifier(), 'status': 'pending', 'left_id': setup.data['left_id'], 'left_key': '0',
         'right_id': setup.data['right_id'], 'right_key': '1', 'created_at': 1, 'updated_at': 1}], 'dismissed': {}})
    c = setup.coordinator
    assert not hasattr(c, 'requests')
    assert 'ask_first' not in c.adventure_status(setup.data['left_id'])
    assert c.schedule_once()['phase'] == 'completed'
    assert len(setup.cable_calls) == 1


def test_trade_request_routes_are_gone(managed):  # noqa: F811
    client, rid = managed.client, identifier()
    assert not any('trade-requests' in path for _, path in writes(managed.app, managed.aid))
    for method, path in [
            ('GET', f'/api/v1/interactions/trade-requests?adventure_id={managed.aid}'),
            ('PUT', '/api/v1/interactions/trade-requests/settings'),
            ('POST', f'/api/v1/interactions/trade-requests/{rid}/accept'),
            ('POST', f'/api/v1/interactions/trade-requests/{rid}/dismiss')]:
        response = client.request(method, path, json={'ask_first': False} if method == 'PUT' else None)
        assert response.status_code == 404, (method, path, response.status_code)
