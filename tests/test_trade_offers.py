"""Trade offers: one adventure asks another, often someone else's, for a trade. Accepting queues a manual trade."""
import threading

import pytest

from pokesim.app import offers as offers_module
from pokesim.app import trade_settings
from pokesim.app.offers import ACCEPTED_EXPIRE, EXPIRE_SECONDS, Changed, LimitReached, OwnerOnly, TradeOffers
from pokesim.app.policy import Actor
from pokesim.app.registry import LIBRARY_OWNER, identifier

from test_accounts import library, people  # noqa: F401  (fixtures)
from test_managed_coordinator import setup  # noqa: F401  (fixture)

CAROL = 'c' * 32


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def member(uid, **grants):
    return Actor({'id': uid, 'role': 'member', 'disabled': False}, grants)


@pytest.fixture
def offers(setup):  # noqa: F811
    setup.manager.coordinator = setup.coordinator
    setup.manager.offers = TradeOffers(setup.manager)
    # These tests answer offers by hand. Offers between two adventures of one owner start at once,
    # which test_an_offer_between_one_owners_adventures_starts_at_once covers.
    setup.manager.offers.auto_accept = False
    # The actor as the accounts hold it now. Tests that revoke a grant meanwhile replace this.
    setup.manager.fresh_actor = lambda actor: actor
    return setup


def offer_request(setup, from_key='0', to_key='1'):
    request = {'from_id': setup.data['left_id'], 'from_key': from_key, 'to_id': setup.data['right_id']}
    return {**request, 'to_key': to_key} if to_key else request


def test_an_offer_can_ask_for_nothing_and_the_receiver_picks_at_accept(offers):
    service, right = offers.manager.offers, offers.data['right_id']
    offer = service.create(offer_request(offers, to_key=None))
    assert offer['status'] == 'pending' and offer['to']['key'] is None
    assert offer['expires_at'] == offer['created_at'] + EXPIRE_SECONDS
    assert [row['id'] for row in service.for_adventure(right)['incoming']] == [offer['id']]
    with pytest.raises(ValueError, match='Choose a Pokémon to give'):
        service.accept(offer['id'])
    accepted = service.accept(offer['id'], to_key='1')
    assert accepted['status'] == 'accepted' and accepted['to']['key'] == '1' and accepted['to']['name'] == 'Ivysaur'
    entry = offers.coordinator.manual_status(accepted['manual_id'])
    assert (entry['left_key'], entry['right_key']) == ('0', '1')
    assert offers.coordinator.drain_manual()['phase'] == 'completed'
    assert service.status(offer['id'])['status'] == 'completed'


def test_decline_and_cancel_answer_only_pending_offers(offers):
    service = offers.manager.offers
    first = service.create(offer_request(offers))
    assert service.decline(first['id'])['status'] == 'declined'
    with pytest.raises(ValueError, match='already declined'):
        service.accept(first['id'])
    second = service.create(offer_request(offers))
    assert service.withdraw(second['id'])['status'] == 'withdrawn'
    with pytest.raises(ValueError, match='already withdrawn'):
        service.decline(second['id'])


def test_open_offers_lock_their_pokemon_away_from_automatic_trading(offers):
    service, c = offers.manager.offers, offers.coordinator
    left, right = offers.data['left_id'], offers.data['right_id']
    offer = service.create(offer_request(offers))
    assert {(left, '0'), (right, '1')} <= c.hand_picked_keys()
    service.withdraw(offer['id'])
    asked_nothing = service.create(offer_request(offers, to_key=None))
    assert c.hand_picked_keys() == {(left, '0')}
    service.decline(asked_nothing['id'])
    assert c.hand_picked_keys() == set()


def test_limits_cap_open_daily_and_incoming_offers(offers, monkeypatch):
    service, registry = offers.manager.offers, offers.registry
    alice, bob = member('a' * 32, **{offers.data['left_id']: 'manager'}), member('b' * 32)
    monkeypatch.setattr(offers_module, 'MAX_PENDING', 1)
    service.create(offer_request(offers), alice)
    with pytest.raises(LimitReached, match='1 offers open'):
        service.create(offer_request(offers, to_key='party-1'), alice)
    monkeypatch.setattr(offers_module, 'MAX_PENDING', 20)
    monkeypatch.setattr(offers_module, 'DAILY', 2)
    service.create(offer_request(offers, to_key='party-1'), alice)
    with pytest.raises(LimitReached, match='2 offers a day'):
        service.create(offer_request(offers, to_key=None), alice)
    # The receiver's owner has 2 offers waiting, so a third person is turned away too.
    monkeypatch.setattr(offers_module, 'MAX_INCOMING', 2)
    with pytest.raises(LimitReached, match='too many offers waiting'):
        service.create(offer_request(offers, to_key=None), member(CAROL, **{offers.data['left_id']: 'manager'}))
    assert registry.count_trade_offers(sender_id=alice.id) == 2
    assert bob.id not in {row['sender_id'] for row in registry.trade_offers()}


def test_unanswered_offers_expire_after_a_day(offers):
    service = offers.manager.offers
    offer = service.create(offer_request(offers))
    service.clock = Clock(offer['created_at'] + EXPIRE_SECONDS + 1)
    expired = service.status(offer['id'])
    assert expired['status'] == 'expired' and expired['reason'] == 'No answer within 24 hours'
    assert offers.coordinator.hand_picked_keys() == set()


def test_an_accepted_offer_whose_trade_never_starts_expires_and_leaves_the_line(offers):
    service, c = offers.manager.offers, offers.coordinator
    accepted = service.accept(service.create(offer_request(offers))['id'])
    service.clock = Clock(accepted['updated_at'] + ACCEPTED_EXPIRE - 1)
    assert service.status(accepted['id'])['status'] == 'accepted'
    service.clock = Clock(accepted['updated_at'] + ACCEPTED_EXPIRE + 1)
    expired = service.status(accepted['id'])
    assert expired['status'] == 'expired' and 'within 6 hours' in expired['reason']
    assert c.manual_status(accepted['manual_id'])['state'] == 'cancelled'
    assert c.drain_manual() is None


def test_an_offer_that_ends_during_accept_queues_no_trade(offers, monkeypatch):
    service = offers.manager.offers
    offer = service.create(offer_request(offers))
    check = service._check

    def ended_meanwhile(*args, **kwargs):
        found = check(*args, **kwargs)
        # A transfer ends the offer while the accept reads both Pokémon, without the offers guard.
        offers.registry.update_trade_offer(offer['id'], expect=('pending',), status='withdrawn',
                                           reason='The adventure changed hands')
        return found
    monkeypatch.setattr(service, '_check', ended_meanwhile)
    with pytest.raises(ValueError, match='already withdrawn'):
        service.accept(offer['id'])
    assert [entry for entry in offers.coordinator._manual_entries() if entry['state'] == 'queued'] == []
    assert service.status(offer['id'])['status'] == 'withdrawn'


def test_an_offer_from_an_adventure_that_changed_hands_meanwhile_is_refused(offers, monkeypatch):
    service, left = offers.manager.offers, offers.data['left_id']
    sides = service._sides

    def transferred_meanwhile(*args, **kwargs):
        found = sides(*args, **kwargs)
        # The owner gives the adventure away while their offer reads both Pokémon.
        offers.registry.set_owner(left, CAROL)
        return found
    monkeypatch.setattr(service, '_sides', transferred_meanwhile)
    with pytest.raises(PermissionError, match='no longer offer trades'):
        service.create(offer_request(offers), member(LIBRARY_OWNER))
    assert offers.registry.trade_offers(left, statuses=['pending']) == []


def test_an_offer_from_a_manager_whose_grant_ended_meanwhile_is_refused(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    # Carol's actor was read with the manager grant. The owner removed it before her offer arrived.
    stale = member(CAROL, **{left: 'manager'})
    offers.manager.fresh_actor = lambda actor: member(actor.id)
    with pytest.raises(PermissionError, match='no longer offer trades'):
        service.create(offer_request(offers), stale)
    assert offers.registry.trade_offers(left, statuses=['pending']) == []
    offers.manager.fresh_actor = lambda actor: None
    with pytest.raises(PermissionError, match='no longer offer trades'):
        service.create(offer_request(offers), stale)
    # The receiver's grant ended the same way while they accepted.
    offers.manager.fresh_actor = lambda actor: actor
    offer = service.create(offer_request(offers))
    offers.manager.fresh_actor = lambda actor: member(actor.id)
    with pytest.raises(PermissionError, match='no longer accept trades'):
        service.accept(offer['id'], member(CAROL, **{right: 'manager'}))
    assert service.status(offer['id'])['status'] == 'pending'
    assert [entry for entry in offers.coordinator._manual_entries() if entry['state'] == 'queued'] == []


def test_a_trade_that_finished_before_accept_never_blocks_it_when_settled_meanwhile(offers, monkeypatch):
    service = offers.manager.offers
    first = service.create(offer_request(offers))
    second = service.create(offer_request(offers, to_key='party-1'))
    service.accept(first['id'])
    # The first trade already ran, but nothing has settled its offer yet.
    assert offers.coordinator.drain_manual()['phase'] == 'completed'
    check = service._check

    def swept(*args, **kwargs):
        found = check(*args, **kwargs)
        # The sweep settles the first offer while the accept reads both games.
        service.refresh()
        return found
    monkeypatch.setattr(service, '_check', swept)
    assert service.accept(second['id'], confirm=True)['status'] == 'accepted'


def test_a_trade_that_finishes_during_accept_keeps_its_pokemon_out_of_another(offers, monkeypatch):
    service = offers.manager.offers
    first = service.create(offer_request(offers))
    second = service.create(offer_request(offers, to_key='party-1'))
    service.accept(first['id'])
    check = service._check

    def finished_meanwhile(*args, **kwargs):
        found = check(*args, **kwargs)
        # The first trade, on the same Pokémon, runs and settles while the accept reads both games.
        assert offers.coordinator.drain_manual()['phase'] == 'completed'
        assert service.status(first['id'])['status'] == 'completed'
        return found
    monkeypatch.setattr(service, '_check', finished_meanwhile)
    with pytest.raises(ValueError, match='another trade'):
        service.accept(second['id'])
    assert [entry for entry in offers.coordinator._manual_entries() if entry['state'] == 'queued'] == []
    assert service.status(second['id'])['status'] == 'pending'


def test_accept_holds_no_guard_while_the_games_answer(offers, monkeypatch):
    service = offers.manager.offers
    offer = service.create(offer_request(offers))
    check, free = service._check, []

    def slow_games(*args, **kwargs):
        # A refresh on another thread takes the guard while both games are still answering.
        taker = threading.Thread(target=lambda: free.append(service.guard.acquire(timeout=1) and service.guard.release() is None))
        taker.start()
        taker.join(5)
        return check(*args, **kwargs)
    monkeypatch.setattr(service, '_check', slow_games)
    assert service.accept(offer['id'])['status'] == 'accepted'
    assert free == [True]


def test_a_changed_pokemon_needs_the_receiver_to_confirm(offers):
    service = offers.manager.offers
    offer = service.create(offer_request(offers))
    offers.peers[offers.data['left_id']].pokemon[0].update(dex=3, name='Venusaur')
    with pytest.raises(Changed, match='Ivysaur is now Venusaur') as raised:
        service.accept(offer['id'])
    assert raised.value.offer['status'] == 'pending'
    accepted = service.accept(offer['id'], confirm=True)
    assert accepted['status'] == 'accepted' and accepted['from']['name'] == 'Venusaur'


def test_a_pokemon_that_left_expires_the_offer_at_accept(offers):
    service, right = offers.manager.offers, offers.data['right_id']
    offer = service.create(offer_request(offers))
    offers.peers[right].pokemon = offers.peers[right].pokemon[1:]
    result = service.accept(offer['id'])
    assert result['status'] == 'expired' and result['reason'] == 'Ivysaur is no longer in Second Red'


def test_only_the_owner_offers_or_gives_a_pokemon_automatic_trading_keeps(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    manager_of_both = member(CAROL, **{left: 'manager', right: 'manager'})
    owner = member(LIBRARY_OWNER)
    # party-0 is not among the Pokémon automatic trading would give away, so it is protected.
    with pytest.raises(OwnerOnly):
        service.create(offer_request(offers, from_key='party-0'), manager_of_both)
    offer = service.create(offer_request(offers, from_key='party-0', to_key=None), owner)
    with pytest.raises(OwnerOnly):
        service.accept(offer['id'], manager_of_both, to_key='party-1')
    # A game that cannot answer keeps every Pokémon to its owner.
    offers.peers[right].failures['inventory'] = 1
    with pytest.raises(OwnerOnly):
        service.accept(offer['id'], manager_of_both, to_key='1')
    assert service.accept(offer['id'], manager_of_both, to_key='1')['status'] == 'accepted'


def test_an_offer_between_one_owners_adventures_starts_at_once(offers):
    service = offers.manager.offers
    service.auto_accept = True
    assert service.create(offer_request(offers))['status'] == 'accepted'
    # Across owners, the receiver always answers.
    offers.registry.db.execute('UPDATE adventures SET owner_id=? WHERE id=?', (CAROL, offers.data['right_id']))
    assert service.create(offer_request(offers, to_key='party-1'))['status'] == 'pending'


def test_an_offer_starts_at_once_only_for_someone_who_manages_the_receiver(offers):
    service, left, right = offers.manager.offers, offers.data['left_id'], offers.data['right_id']
    service.auto_accept = True
    # Carol manages the sender only. Her offer into the same owner's other game waits for an answer.
    waiting = service.create(offer_request(offers), member(CAROL, **{left: 'manager', right: 'viewer'}))
    assert waiting['status'] == 'pending'
    offers.registry.update_trade_offer(waiting['id'], status='withdrawn')
    assert service.create(offer_request(offers), member(CAROL, **{left: 'manager', right: 'manager'}))['status'] == 'accepted'


def test_automatic_trading_across_owners_needs_both_to_opt_in(offers):
    c, registry = offers.coordinator, offers.registry
    left, right = offers.data['left_id'], offers.data['right_id']
    registry.db.execute('UPDATE adventures SET owner_id=? WHERE id=?', (CAROL, right))
    trade_settings.update(registry, left, across_owners=True)
    assert c.schedule_once() is None
    trade_settings.update(registry, right, across_owners=True)
    assert c.schedule_once()['phase'] == 'completed'


def test_the_registry_keeps_finished_offers_per_sender(offers):
    registry = offers.registry
    for sender in ('a' * 32, 'b' * 32):
        for _ in range(3):
            row = registry.create_trade_offer({**offer_request(offers), 'id': identifier(), 'sender_id': sender})
            registry.update_trade_offer(row['id'], status='declined')
    registry.prune_trade_offers(2)
    rows = registry.trade_offers()
    assert sorted(row['sender_id'] for row in rows) == ['a' * 32] * 2 + ['b' * 32] * 2


def test_routes_need_open_to_offers_for_someone_elses_adventure(library, people):  # noqa: F811
    alice = library.login('alice')
    pokemon = f'/api/v1/interactions/trade-offers/pokemon?adventure_id={people.blue}'
    offer = {'from_id': people.red, 'from_key': '0', 'to_id': people.blue}
    assert alice.get(pokemon).status_code == 404
    assert alice.post('/api/v1/interactions/trade-offers', json=offer).status_code == 404
    library.manager.auth.grant(people.blue, people.alice['id'], 'viewer', people.bob['id'])
    assert alice.get(pokemon).status_code == 403
    settings = f'/api/v1/interactions/auto-settings?adventure_id={people.blue}'
    assert alice.put(settings, json={'open_to_offers': True}).status_code == 403
    bob = library.login('bob')
    assert bob.put(settings, json={'open_to_offers': True}).json()['open_to_offers'] is True
    assert alice.get(pokemon).status_code == 200
    targets = alice.get(f'/api/v1/interactions/trade-offers/targets?from_id={people.red}').json()
    assert [(row['id'], row['offer'], row['owner_name']) for row in targets['adventures']] == [(people.blue, True, 'bob')]
    # Offers sent from an adventure need its manager, and its offers list stays private.
    assert bob.get(f'/api/v1/interactions/trade-offers?adventure_id={people.red}').status_code == 404
    assert bob.get(f'/api/v1/interactions/trade-offers/targets?from_id={people.red}').status_code == 404
