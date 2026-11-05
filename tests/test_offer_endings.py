"""Offers ended by a transfer, a revoked share, a deleted user or a deleted adventure reach both sides' inboxes."""
from test_accounts import library, people  # noqa: F401  (fixtures)
from test_user_deletion import offer, quiet  # noqa: F401  (fixture)


def ended(manager, uid):
    return [item for item in manager.auth.inbox(uid) if item['kind'] == 'offer.ended']


def test_a_transfer_tells_both_sides_of_each_ended_offer(quiet, people):  # noqa: F811
    manager = quiet.manager
    sent = offer(quiet, people.red, people.blue, sender=people.alice['id'])
    green = quiet.adventure('Green', people.admin)
    # The admin gives Bob's game away, so Alice's offer to it ends and both Alice and Bob hear.
    moved = quiet.login('admin').post(f'/api/v1/adventures/{people.blue}/transfer', json={'user_id': people.admin['id']})
    assert moved.status_code == 200, moved.text
    assert manager.registry.trade_offer(sent['id'])['status'] == 'declined'
    [alice] = ended(manager, people.alice['id'])
    [bob] = ended(manager, people.bob['id'])
    assert alice['text'] == bob['text'] == 'The offer of a Pokémon from Red to Blue ended because Blue changed hands.'
    assert alice['link'] == f'/games/{people.red}/trading#offers'
    assert bob['link'] == f'/games/{people.blue}/trading#offers'
    # The person who acted hears nothing about their own action, and an offer ends only once.
    assert ended(manager, people.admin['id']) == []
    assert green and len(ended(manager, people.alice['id'])) == 1


def test_a_new_owner_starts_with_the_trading_switches_at_their_defaults(quiet, people):  # noqa: F811
    from pokesim.app import trade_settings
    registry = quiet.manager.registry
    defaults = {'enabled': True, 'open_to_offers': False, 'across_owners': False}
    for aid in (people.red, people.blue):
        trade_settings.update(registry, aid, enabled=False, open_to_offers=True, across_owners=True)
    # Bob gives Blue to Alice, who never chose to trade it with other people.
    moved = quiet.login('bob').post(f'/api/v1/adventures/{people.blue}/transfer', json={'user_id': people.alice['id']})
    assert moved.status_code == 200, moved.text
    assert trade_settings.get(registry, people.blue) == defaults
    # A deletion that hands Red on, and archives Blue under the admin, does the same.
    trade_settings.update(registry, people.blue, open_to_offers=True, across_owners=True)
    deleted = quiet.login('admin').request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                                           json={'adventures': {people.red: people.bob['id'], people.blue: 'archive'}})
    assert deleted.status_code == 200, deleted.text
    assert trade_settings.get(registry, people.red) == trade_settings.get(registry, people.blue) == defaults
    # Switches the owner sets after a transfer stay.
    trade_settings.update(registry, people.red, open_to_offers=True)
    assert trade_settings.get(registry, people.red)['open_to_offers'] is True


def test_a_revoked_share_ends_offers_the_person_sent_from_it(quiet, people):  # noqa: F811
    manager = quiet.manager
    green = quiet.adventure('Green', people.admin)
    manager.auth.grant(people.red, people.bob['id'], 'manager', people.alice['id'])
    sent = offer(quiet, people.red, green, sender=people.bob['id'])
    others = offer(quiet, people.red, green, sender=people.alice['id'])
    # Bob also asked Red for a trade from his own Blue. Losing his share of Red does not take that back.
    own = offer(quiet, people.blue, people.red, sender=people.bob['id'])
    alice = quiet.login('alice')
    assert alice.request('DELETE', f'/api/v1/adventures/{people.red}/grants/{people.bob["id"]}').status_code == 200
    assert manager.registry.trade_offer(sent['id'])['status'] == 'withdrawn'
    assert manager.registry.trade_offer(others['id'])['status'] == 'pending'
    assert manager.registry.trade_offer(own['id'])['status'] == 'pending'
    [bob] = ended(manager, people.bob['id'])
    [admin] = ended(manager, people.admin['id'])
    assert bob['text'] == admin['text'] == 'The offer of a Pokémon from Red to Green ended because sharing of an adventure ended.'
    assert ended(manager, people.alice['id']) == []


def test_watching_only_ends_offers_too(quiet, people):  # noqa: F811
    manager = quiet.manager
    green = quiet.adventure('Green', people.admin)
    manager.auth.grant(people.red, people.bob['id'], 'manager', people.alice['id'])
    sent = offer(quiet, people.red, green, sender=people.bob['id'])
    changed = quiet.login('alice').post(f'/api/v1/adventures/{people.red}/grants',
                                        json={'user_id': people.bob['id'], 'role': 'viewer'})
    assert changed.status_code == 200
    assert manager.registry.trade_offer(sent['id'])['status'] == 'withdrawn'
    assert len(ended(manager, people.admin['id'])) == 1


def test_a_deleted_user_s_offers_tell_whoever_is_left(quiet, people):  # noqa: F811
    manager = quiet.manager
    manager.auth.grant(people.blue, people.alice['id'], 'manager', people.bob['id'])
    green = quiet.adventure('Green', people.admin)
    offer(quiet, people.blue, green, sender=people.alice['id'])
    received = offer(quiet, people.blue, people.red, sender=people.bob['id'])
    admin = quiet.login('admin')
    assert admin.request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                         json={'adventures': {people.red: people.admin['id']}}).status_code == 200
    # Bob's offer to Red ended when Red changed hands, and Bob heard. The admin acted, so heard nothing.
    assert manager.registry.trade_offer(received['id'])['status'] == 'declined'
    assert [item['text'] for item in ended(manager, people.bob['id'])] == [
        'The offer of a Pokémon from Blue to Red ended because Red changed hands.']
    assert ended(manager, people.admin['id']) == []


def test_deleting_a_user_hands_each_adventure_on_in_one_hold_of_the_offers_guard(quiet, people, monkeypatch):  # noqa: F811
    import threading

    from pokesim.app import ownership
    guard, give, free = quiet.manager.offers.guard, ownership.give, []

    def watched(*args):
        # An offer made from another thread would get the guard here, after the trades ended and
        # before the new owner is recorded.
        def take():
            got = guard.acquire(timeout=0.2)
            free.append(got)
            if got:
                guard.release()
        taker = threading.Thread(target=take)
        taker.start()
        taker.join(5)
        return give(*args)
    monkeypatch.setattr(ownership, 'give', watched)
    admin = quiet.login('admin')
    assert admin.request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                         json={'adventures': {people.red: people.admin['id']}}).status_code == 200
    assert free == [False]
    assert quiet.manager.registry.adventure(people.red)['owner_id'] == people.admin['id']


def test_deleting_an_adventure_ends_its_offers_and_unlinks_its_inbox_items(quiet, people):  # noqa: F811
    manager = quiet.manager
    manager.registry.update(people.red, state='stopped', desired_state='stopped')
    sent = offer(quiet, people.blue, people.red, sender=people.bob['id'])
    manager.auth.notify(people.alice['id'], 'share.added', 'Older news about Red.', adventure_id=people.red,
                        link=f'/games/{people.red}/')
    alice = quiet.login('alice')
    deleted = alice.request('DELETE', f'/api/v1/adventures/{people.red}', json={'confirmation': 'Red'})
    assert deleted.status_code == 200, deleted.text
    assert manager.registry.trade_offer(sent['id'])['status'] == 'declined'
    [bob] = ended(manager, people.bob['id'])
    assert bob['text'] == 'The offer of a Pokémon from Blue to Red ended because Red was deleted.'
    assert bob['adventure_id'] == people.blue and bob['link'] == f'/games/{people.blue}/trading#offers'
    # Alice deleted it herself, so she hears nothing new, and her older item about Red no longer links anywhere.
    [older] = manager.auth.inbox(people.alice['id'])
    assert older['text'] == 'Older news about Red.' and older['adventure_id'] is None and older['link'] is None
