"""The trade builder: the owner picks a Pokémon in two adventures, and only hard limits stop the trade.

In 0.5.0 trading is automatic or built by hand, so trade offers and manual Cable Club
sessions have no routes and no tab.
"""
import re

import pytest

from pokesim import config
from pokesim.app.registry import identifier
from pokesim.app.trade_builder import TradeBuilder, ViewOnlyError
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


def test_a_game_busy_with_a_trade_is_greyed_out_and_names_its_partner(built, monkeypatch):
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    tid = identifier()
    built.registry.create_transaction(tid, {'participants': [right, left]})
    peer = built.peers[right]
    plain = peer.request

    def busy(method, path, data=None, timeout=None):
        result = plain(method, path, data, timeout)
        if path.endswith('/manual-inventory'):
            result.update(holding=True, hold_id=tid, reason=BUSY)
        return result
    monkeypatch.setattr(peer, 'request', busy)
    row = service.targets(left, '0')['adventures'][0]
    assert row['available'] is False
    assert row['reason'] == 'Busy finishing a trade with First Red — available again once it finishes'
    built.registry.db.execute('DELETE FROM interactions WHERE id=?', (tid,))
    assert service.targets(left, '0')['adventures'][0]['reason'] == BUSY


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
    for gone in ('tab-offers', 'panel-offers', 'offers-count', 'tab-cable', 'panel-cable', 'cable-games', 'Send offer'):
        assert gone not in html
