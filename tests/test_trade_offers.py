"""Trade offers: one adventure asks another for a Pokémon, and accepting queues a manual trade."""
import time

import pytest

from pokesim import config
from pokesim.app.offers import EXPIRE_SECONDS, TradeOffers, ViewOnlyError
from pokesim.app.registry import identifier
from pokesim.runtime.participant import BUSY

from test_managed_coordinator import setup  # noqa: F401  (fixture)
from test_view_links import instance_controls, managed, writes  # noqa: F401  (fixtures)


@pytest.fixture
def offers(setup):  # noqa: F811
    setup.manager.coordinator = setup.coordinator
    setup.manager.offers = TradeOffers(setup.manager)
    for peer in setup.peers.values():
        peer.pokemon[0].update(level=20, power=180, battle_power=95)
    return setup


def offer_request(setup, from_key='0', to_key='1'):
    return {'from_id': setup.data['left_id'], 'from_key': from_key,
            'to_id': setup.data['right_id'], 'to_key': to_key}


def test_offer_lifecycle_lists_incoming_and_outgoing_and_answers(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    offer = service.create(offer_request(offers))
    assert offer['status'] == 'pending'
    assert offer['from']['name'] == 'Ivysaur' and offer['from']['level'] == 20
    assert offer['from']['power'] == 180 and offer['from']['battle_power'] == 95
    assert offer['from']['sprite_url'] == f'/games/{left}/sprites/2.png?v=rom-portraits-1'
    assert offer['to']['adventure_name'] == 'Second Red'
    assert [row['id'] for row in service.for_adventure(left)['outgoing']] == [offer['id']]
    assert service.for_adventure(left)['incoming'] == []
    assert [row['id'] for row in service.for_adventure(right)['incoming']] == [offer['id']]
    with pytest.raises(ValueError, match='already offered'):
        service.create(offer_request(offers))
    assert service.decline(offer['id'])['status'] == 'declined'
    with pytest.raises(ValueError, match='already declined'):
        service.accept(offer['id'])
    with pytest.raises(ValueError, match='already declined'):
        service.withdraw(offer['id'])
    second = service.create(offer_request(offers))
    assert service.withdraw(second['id'])['status'] == 'withdrawn'
    assert {row['status'] for row in service.for_adventure(right)['incoming']} == {'declined', 'withdrawn'}
    assert offers.registry.trade_offer(second['id'])['status'] == 'withdrawn'


def test_offer_creation_checks_hard_limits_and_request_ids(offers):
    service = offers.manager.offers
    with pytest.raises(ValueError, match='another adventure'):
        service.create({**offer_request(offers), 'to_id': offers.data['left_id']})
    offers.peers[offers.data['right_id']].pokemon[0]['blocked'] = 'Eggs cannot be traded'
    with pytest.raises(ValueError, match='Eggs cannot be traded'):
        service.create(offer_request(offers))
    offers.peers[offers.data['right_id']].pokemon[0]['blocked'] = None
    request = {**offer_request(offers), 'request_id': identifier()}
    first = service.create(request)
    assert service.create(request)['id'] == first['id']
    with pytest.raises(ValueError, match='another offer'):
        service.create({**request, 'to_key': 'party-1'})


def test_accepting_enqueues_a_manual_trade_and_completes_the_offer(offers):
    service, c = offers.manager.offers, offers.coordinator
    offer = service.create(offer_request(offers))
    accepted = service.accept(offer['id'])
    assert accepted['status'] == 'accepted'
    entry = c.manual_status(accepted['manual_id'])
    assert entry['state'] == 'queued'
    assert (entry['left_id'], entry['left_key'], entry['right_id'], entry['right_key']) == (
        offers.data['left_id'], '0', offers.data['right_id'], '1')
    assert accepted['trade']['id'] == entry['id']
    with pytest.raises(ValueError, match='already accepted'):
        service.decline(offer['id'])
    assert c.drain_manual()['phase'] == 'completed'
    assert offers.cable_calls == [entry['id']]
    finished = service.for_adventure(offers.data['right_id'])['incoming'][0]
    assert finished['status'] == 'completed'
    assert finished['trade']['phase'] == 'completed'


def test_a_failed_manual_trade_fails_the_offer_with_its_reason(offers):
    service, c = offers.manager.offers, offers.coordinator
    offer = service.accept(service.create(offer_request(offers))['id'])
    offers.peers[offers.data['left_id']].pokemon[0]['blocked'] = 'Eggs cannot be traded'
    c.drain_manual()
    status = service.status(offer['id'])
    assert status['status'] == 'failed'
    assert status['reason'] == 'Ivysaur: Eggs cannot be traded' or 'Eggs cannot be traded' in status['reason']


def test_stale_offers_expire_or_fail_on_accept_and_stopped_games_only_wait(offers):
    service, right = offers.manager.offers, offers.data['right_id']
    gone = service.create(offer_request(offers))
    offers.peers[right].pokemon = offers.peers[right].pokemon[1:]
    result = service.accept(gone['id'])
    assert result['status'] == 'expired'
    assert result['reason'] == 'Ivysaur is no longer in Second Red'
    assert result['manual_id'] is None and offers.coordinator.manual_statuses()['trades'] == []

    blocked = service.create(offer_request(offers, to_key='party-1'))
    offers.peers[right].pokemon[0]['blocked'] = 'The game refuses to trade away the only Pokémon that can battle'
    result = service.accept(blocked['id'])
    assert result['status'] == 'failed'
    assert 'only Pokémon that can battle' in result['reason']

    offers.peers[right].pokemon[0]['blocked'] = None
    waiting = service.create(offer_request(offers, to_key='party-1'))
    offers.registry.update(right, state='stopped', desired_state='stopped')
    with pytest.raises(ValueError, match='Start this adventure'):
        service.accept(waiting['id'])
    assert service.status(waiting['id'])['status'] == 'pending'


def test_time_capsule_limits_fail_an_offer_on_accept(offers):
    service, right = offers.manager.offers, offers.data['right_id']
    offer = service.create(offer_request(offers))
    modern = offers.peers[right]
    modern.generation = 2
    modern.capsule_ready = True
    for mon in modern.pokemon:
        mon.update(cartridge_generation=2, time_capsule_compatible=False, time_capsule_reason='Togepi did not exist in Gen I')
    result = service.accept(offer['id'])
    assert result['status'] == 'failed'
    assert 'Togepi did not exist in Gen I' in result['reason']


def test_unanswered_offers_expire_and_archived_partners_expire(offers):
    service = offers.manager.offers
    old = service.create(offer_request(offers))
    offers.registry.db.execute('UPDATE trade_offers SET created_at=? WHERE id=?', (time.time() - EXPIRE_SECONDS - 1, old['id']))
    archived = service.create(offer_request(offers, to_key='party-1'))
    assert service.status(old['id'])['status'] == 'expired'
    assert 'No answer within 7 days' in service.status(old['id'])['reason']
    assert service.status(archived['id'])['status'] == 'pending'
    offers.registry.update(offers.data['right_id'], archived=True)
    rows = {row['id']: row for row in service.for_adventure(offers.data['left_id'])['outgoing']}
    assert rows[old['id']]['status'] == 'expired' and 'No answer within 7 days' in rows[old['id']]['reason']
    assert rows[archived['id']]['status'] == 'expired' and rows[archived['id']]['reason'] == 'Second Red was archived'


def test_picker_lists_targets_and_hard_limits(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    targets = service.targets(left)
    assert [row['id'] for row in targets['adventures']] == [right]
    assert targets['adventures'][0]['available'] is True
    offers.peers[right].pokemon[1]['blocked'] = 'Eggs cannot be traded'
    limits = service.limits(left, '0', right)
    assert limits['blocked'] == {'party-1': 'Eggs cannot be traded'}
    assert limits['from']['name'] == 'Ivysaur' and limits['from']['blocked'] == ''
    offers.registry.update(right, state='stopped', desired_state='stopped')
    assert service.targets(left)['adventures'][0]['reason'] == 'Start this adventure to trade from it'


def make_crystal(peer, *, ready=True, compatible=True):
    peer.generation, peer.capsule_ready = 2, ready
    for mon in peer.pokemon:
        mon.update(cartridge_generation=2, time_capsule_compatible=compatible,
                   time_capsule_reason='' if compatible else 'Togepi did not exist in Gen I')


def test_targets_grey_out_games_that_cannot_take_the_chosen_pokemon(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    # An ordinary pair stays open.
    row = service.targets(left, '0')['adventures'][0]
    assert row['id'] == right and row['available'] is True and row['reason'] == ''
    # A Gen II-only Pokémon cannot go to a Red game, so Red is greyed out before its PC opens.
    make_crystal(offers.peers[left], compatible=False)
    row = service.targets(left, '0')['adventures'][0]
    assert row['available'] is False
    assert 'cannot go to a Red, Blue or Yellow game' in row['reason'] and 'Togepi did not exist in Gen I' in row['reason']
    # Without a chosen Pokémon only the game itself is checked, as before.
    assert service.targets(left)['adventures'][0]['available'] is True
    # Without the Time Capsule nothing crosses.
    make_crystal(offers.peers[left], ready=False)
    assert 'Time Capsule yet' in service.targets(left, '0')['adventures'][0]['reason']
    make_crystal(offers.peers[left])
    assert service.targets(left, '0')['adventures'][0]['available'] is True
    # An egg or other blocked Pokémon cannot go anywhere.
    offers.peers[left].pokemon[0]['blocked'] = 'Eggs cannot be traded'
    assert service.targets(left, '0')['adventures'][0]['reason'] == 'Eggs cannot be traded'
    with pytest.raises(ValueError, match='no longer in First Red'):
        service.targets(left, 'missing')


def test_targets_grey_out_a_game_when_every_pair_is_blocked(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    for mon in offers.peers[right].pokemon:
        mon['blocked'] = 'Eggs cannot be traded'
    row = service.targets(left, '0')['adventures'][0]
    assert row['available'] is False and row['reason'] == 'Eggs cannot be traded'
    offers.peers[right].pokemon[1]['blocked'] = 'This is the last party member that can battle'
    assert service.targets(left, '0')['adventures'][0]['reason'] == 'Nothing in Second Red can be traded for Ivysaur'


def test_a_game_busy_with_a_trade_is_greyed_out_and_names_its_partner(offers, monkeypatch):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    tid = identifier()
    offers.registry.create_transaction(tid, {'participants': [right, left]})
    peer = offers.peers[right]
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
    assert 'held for another exchange' not in row['reason']
    # When the trade record is gone the reason stays honest without a name.
    offers.registry.db.execute('DELETE FROM interactions WHERE id=?', (tid,))
    assert service.targets(left, '0')['adventures'][0]['reason'] == BUSY


def test_limits_report_a_limit_of_the_offered_pokemon_once(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    make_crystal(offers.peers[left], compatible=False)
    limits = service.limits(left, '0', right)
    assert 'cannot go to a Red, Blue or Yellow game' in limits['from']['blocked']
    assert limits['blocked'] == {}


@pytest.mark.parametrize('instance', [False, True])
def test_view_only_adventures_cannot_write_offers(offers, monkeypatch, instance):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    incoming = service.create(offer_request(offers))
    outgoing = service.create(offer_request(offers, to_key='party-1'))
    if instance:
        monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    else:
        for aid in (left, right):
            game = offers.registry.adventure(aid)
            offers.registry.update(aid, settings={**game['settings'], 'viewer_only': True})
    for action in (lambda: service.create(offer_request(offers, to_key='x')), lambda: service.accept(incoming['id']),
                   lambda: service.decline(incoming['id']), lambda: service.withdraw(outgoing['id'])):
        with pytest.raises(ViewOnlyError):
            action()
    assert service.for_adventure(right)['viewer_only'] is True
    assert {row['status'] for row in service.for_adventure(left)['outgoing']} == {'pending'}


def test_offer_routes_refuse_view_links_and_view_only_adventures(managed, monkeypatch):  # noqa: F811
    registry, client, aid = managed.app.state.manager.registry, managed.client, managed.aid
    routes = writes(managed.app, managed.aid)
    for path in ('', f'/{aid}/accept', f'/{aid}/decline', f'/{aid}/withdraw'):
        assert ('POST', '/api/v1/interactions/trade-offers' + path) in routes
    other = registry.create('Other', 'fixture', {}, identifier())
    registry.update(other['id'], state='running')
    offer = registry.create_trade_offer({'id': identifier(), 'from_id': other['id'], 'from_key': 'a',
                                         'to_id': aid, 'to_key': 'b', 'display': {'from': {}, 'to': {}}})
    registry.update(aid, settings={'viewer_only': True})
    for action in ('accept', 'decline'):
        assert client.post(f'/api/v1/interactions/trade-offers/{offer["id"]}/{action}').status_code == 403
    assert client.post(f'/view/{aid}/api/v1/interactions/trade-offers/{offer["id"]}/withdraw').status_code == 403
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    body = {'from_id': aid, 'from_key': 'b', 'to_id': other['id'], 'to_key': 'a'}
    assert client.post('/api/v1/interactions/trade-offers', json=body).status_code == 403
    assert client.post(f'/api/v1/interactions/trade-offers/{offer["id"]}/withdraw').status_code == 403
    listed = client.get(f'/api/v1/interactions/trade-offers?adventure_id={aid}').json()
    assert listed['viewer_only'] is True and [row['status'] for row in listed['incoming']] == ['pending']


def test_targets_route_passes_the_chosen_pokemon_through(managed, monkeypatch):  # noqa: F811
    manager, client, aid = managed.app.state.manager, managed.client, managed.aid
    seen = []
    monkeypatch.setattr(manager.offers, 'targets', lambda from_id, from_key=None: seen.append((from_id, from_key)) or {})
    assert client.get(f'/api/v1/interactions/trade-offers/targets?from_id={aid}&from_key=box-3').status_code == 200
    assert client.get(f'/api/v1/interactions/trade-offers/targets?from_id={aid}').status_code == 200
    assert seen == [(aid, 'box-3'), (aid, None)]
