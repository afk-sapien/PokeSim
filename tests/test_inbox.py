"""Each person's inbox: the store in auth.sqlite and the two routes that read and mark it."""
from fastapi.testclient import TestClient
import pytest

from pokesim.app import auth as auth_module
from pokesim.app import inbox
from pokesim.app.auth import AuthStore
from pokesim.app.manager import Manager, create_app

from test_accounts import PASSWORD, library, people  # noqa: F401  (fixtures)
from test_control_lease import game, lease  # noqa: F401  (fixture)
from test_managed_coordinator import setup  # noqa: F401  (fixture)
from test_trade_offers import member, offer_request, offers  # noqa: F401  (fixture)


@pytest.fixture
def store(tmp_path):
    auth = AuthStore(tmp_path)
    yield auth
    auth.close()


def test_the_store_keeps_items_per_user_newest_first(store):
    alice = store.create_user('alice', PASSWORD)
    bob = store.create_user('bob', PASSWORD)
    first = store.notify(alice['id'], 'share.added', 'Bob shared Red with you.', adventure_id='a' * 32, link='/games/a/')
    second = store.notify(alice['id'], 'offer.received', 'An offer.')
    store.notify(bob['id'], 'offer.received', 'Not for Alice.')
    items = store.inbox(alice['id'])
    assert [item['id'] for item in items] == [second, first]
    assert items[1] == {'id': first, 'kind': 'share.added', 'adventure_id': 'a' * 32, 'text': 'Bob shared Red with you.',
                        'link': '/games/a/', 'created_at': items[1]['created_at'], 'read': False}
    assert store.unread_count(alice['id']) == 2
    # Someone else's item numbers change nothing.
    bobs = store.inbox(bob['id'])[0]['id']
    assert store.mark_read(alice['id'], [bobs]) == 0
    assert store.mark_read(alice['id'], [first]) == 1
    assert store.unread_count(alice['id']) == 1 and store.unread_count(bob['id']) == 1
    assert store.mark_read(alice['id']) == 1
    assert store.unread_count(alice['id']) == 0 and store.mark_read(alice['id'], []) == 0


def test_the_store_keeps_only_the_newest_items_and_refuses_odd_ones(store, monkeypatch):
    monkeypatch.setattr(auth_module, 'INBOX_KEEP', 3)
    alice = store.create_user('alice', PASSWORD)
    other = store.create_user('bob', PASSWORD)
    store.notify(other['id'], 'offer.received', 'Kept.')
    for number in range(5):
        store.notify(alice['id'], 'offer.received', f'Offer {number}.')
    assert [item['text'] for item in store.inbox(alice['id'])] == ['Offer 4.', 'Offer 3.', 'Offer 2.']
    assert len(store.inbox(other['id'])) == 1
    for link in ('https://elsewhere.example/', '//elsewhere.example/', 'javascript:alert(1)', '/\\elsewhere'):
        with pytest.raises(ValueError):
            store.notify(alice['id'], 'offer.received', 'Bad link.', link=link)
    with pytest.raises(ValueError):
        store.notify(alice['id'], 'Offer Received', 'Bad kind.')
    with pytest.raises(ValueError):
        store.notify(alice['id'], 'offer.received', '  ')
    with pytest.raises(KeyError):
        store.notify('f' * 32, 'offer.received', 'Nobody.')


def test_a_deleted_user_takes_their_inbox_along(store):
    alice = store.create_user('alice', PASSWORD)
    store.notify(alice['id'], 'offer.received', 'An offer.')
    with store.lock, store.db:
        store.db.execute('DELETE FROM users WHERE id=?', (alice['id'],))
    assert store.db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0] == 0


def test_routes_show_and_mark_only_your_own_inbox(library, people):  # noqa: F811
    auth = library.manager.auth
    mine = auth.notify(people.alice['id'], 'share.added', 'Bob shared Blue with you.', link='/games/x/')
    theirs = auth.notify(people.bob['id'], 'share.added', 'For Bob.')
    alice = library.login('alice')
    read = alice.get('/api/v1/inbox').json()
    assert read['unread'] == 1 and [item['id'] for item in read['items']] == [mine]
    # The Library's adventure list carries the unread count, so the badge needs no polling of its own.
    assert alice.get('/api/v1/adventures').json()['inbox'] == {'unread': 1}
    assert alice.post('/api/v1/inbox/read', json={'ids': [theirs]}).json() == {'marked': 0, 'unread': 1}
    assert auth.unread_count(people.bob['id']) == 1
    assert alice.post('/api/v1/inbox/read', json={'ids': [mine]}).json() == {'marked': 1, 'unread': 0}
    auth.notify(people.alice['id'], 'offer.received', 'One more.')
    assert alice.post('/api/v1/inbox/read', json={'all': True}).json() == {'marked': 1, 'unread': 0}
    for bad in ({}, {'all': False}, {'ids': 'all'}, {'ids': ['1']}, {'ids': [1], 'all': True}):
        assert alice.post('/api/v1/inbox/read', json=bad).status_code == 400
    assert alice.get('/api/v1/inbox?limit=0').status_code == 200
    # Nobody logged in has no inbox.
    assert library.browser().get('/api/v1/inbox').status_code == 401


def test_there_is_no_inbox_without_accounts(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    with TestClient(create_app(manager)) as client:
        client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
        assert client.get('/api/v1/inbox').status_code == 404
        assert client.post('/api/v1/inbox/read', json={'all': True}).status_code == 404
        assert 'inbox' not in client.get('/api/v1/adventures').json()
        owner = manager.auth.create_user('alice', PASSWORD)
        assert inbox.notify(manager, owner['id'], 'share.added', 'Never stored.') is None
        assert manager.auth.inbox(owner['id']) == []


def test_nobody_hears_about_their_own_action(library, people):  # noqa: F811
    manager = library.manager
    assert inbox.notify(manager, people.alice['id'], 'share.added', 'Mine.', actor=people.alice['id']) is None
    assert inbox.notify(manager, inbox.LIBRARY_OWNER, 'share.added', 'Nobody reads this.') is None
    assert inbox.notify(manager, people.alice['id'], 'share.added', 'Yours.', actor=people.bob['id'])


def kinds(auth, uid):
    return [item['kind'] for item in reversed(auth.inbox(uid))]


# What lands in an inbox -------------------------------------------------------------------

def test_a_new_share_reaches_the_person_once(library, people):  # noqa: F811
    auth, alice = library.manager.auth, library.login('alice')
    for role in ('viewer', 'player'):
        assert alice.post(f'/api/v1/adventures/{people.red}/grants',
                          json={'user_id': people.bob['id'], 'role': role}).status_code == 200
    [item] = auth.inbox(people.bob['id'])
    assert item['kind'] == 'share.added' and item['adventure_id'] == people.red
    assert item['text'] == 'alice shared Red with you. You can watch it.'
    assert item['link'] == f'/games/{people.red}/'
    assert auth.inbox(people.alice['id']) == []


def test_control_requests_reach_the_holder_and_the_owner(game):  # noqa: F811
    auth = game.library.manager.auth
    bob, carol = game.ids.bob, game.ids.carol
    alice = game.library.manager.registry.adventure(game.red)['owner_id']
    lease(game.bob, game.red, 'request')
    # Nobody is told about a lease granted at once.
    assert auth.inbox(alice) == [] and auth.inbox(bob) == []
    lease(game.carol, game.red, 'request')
    assert kinds(auth, bob) == ['lease.requested'] and kinds(auth, alice) == ['lease.requested']
    assert auth.inbox(bob)[0]['text'] == 'carol asked for control of Red.'
    assert auth.inbox(carol) == []
    # Asking again changes nothing.
    lease(game.carol, game.red, 'request')
    assert len(auth.inbox(bob)) == 1
    lease(game.alice, game.red, 'take')
    assert kinds(auth, bob) == ['lease.requested', 'lease.taken']
    assert auth.inbox(bob)[0]['text'] == 'alice took control of Red from you.'
    assert kinds(auth, alice) == ['lease.requested']


@pytest.fixture
def owned_offers(offers, tmp_path):  # noqa: F811
    """Alice owns the left adventure and Bob the right one, in a library with accounts."""
    manager = offers.manager
    manager.auth, manager.auth_mode = AuthStore(tmp_path), 'accounts'
    alice, bob = manager.auth.create_user('alice', PASSWORD), manager.auth.create_user('bob', PASSWORD)
    for aid, user in ((offers.data['left_id'], alice), (offers.data['right_id'], bob)):
        offers.registry.db.execute('UPDATE adventures SET owner_id=? WHERE id=?', (user['id'], aid))
    offers.alice, offers.bob = member(alice['id']), member(bob['id'])
    yield offers
    manager.auth.close()


def test_offers_and_answers_reach_the_other_person(owned_offers):
    setup, service = owned_offers, owned_offers.manager.offers
    auth, alice, bob = setup.manager.auth, setup.alice, setup.bob
    offer = service.create(offer_request(setup), alice)
    [received] = auth.inbox(bob.id)
    assert received['kind'] == 'offer.received' and received['adventure_id'] == setup.data['right_id']
    assert received['text'].startswith('alice offered ') and received['text'].endswith(' from First Red to Second Red.')
    assert received['link'] == f"/games/{setup.data['right_id']}/trading#offers"
    assert auth.inbox(alice.id) == []
    service.decline(offer['id'], bob)
    assert kinds(auth, alice.id) == ['offer.declined']
    # Withdrawing tells nobody.
    service.withdraw(service.create(offer_request(setup), alice)['id'])
    assert kinds(auth, alice.id) == ['offer.declined'] and kinds(auth, bob.id) == ['offer.received'] * 2
    accepted = service.accept(service.create(offer_request(setup), alice)['id'], bob)
    assert accepted['status'] == 'accepted'
    assert kinds(auth, alice.id) == ['offer.declined', 'offer.accepted']
    assert setup.coordinator.drain_manual()['phase'] == 'completed'
    assert service.status(accepted['id'])['status'] == 'completed'
    for person, aid in ((alice, setup.data['left_id']), (bob, setup.data['right_id'])):
        [done] = [item for item in auth.inbox(person.id) if item['kind'] == 'trade.completed']
        assert done['adventure_id'] == aid and done['link'] == f'/games/{aid}/trading#history'
        assert ' traded with ' in done['text']


def test_an_offer_nobody_answers_tells_the_sender_once(owned_offers):
    from test_trade_offers import Clock
    from pokesim.app.offers import EXPIRE_SECONDS
    setup, service = owned_offers, owned_offers.manager.offers
    offer = service.create(offer_request(setup), setup.alice)
    service.clock = Clock(offer['created_at'] + EXPIRE_SECONDS + 1)
    service.status(offer['id'])
    service.status(offer['id'])
    [expired] = setup.manager.auth.inbox(setup.alice.id)
    assert expired['kind'] == 'offer.expired' and 'No answer within 24 hours.' in expired['text']


def test_trades_inside_one_library_stay_out_of_inboxes(owned_offers):
    setup, service = owned_offers, owned_offers.manager.offers
    alice = setup.alice
    setup.registry.db.execute('UPDATE adventures SET owner_id=?', (alice.id,))
    accepted = service.accept(service.create(offer_request(setup), alice)['id'], alice)
    assert accepted['status'] == 'accepted'
    assert setup.coordinator.drain_manual()['phase'] == 'completed'
    assert setup.manager.auth.inbox(alice.id) == []


def test_without_accounts_offers_reach_no_inbox(owned_offers):
    setup, service = owned_offers, owned_offers.manager.offers
    setup.manager.auth_mode = 'none'
    service.decline(service.create(offer_request(setup), setup.alice)['id'], setup.bob)
    assert setup.manager.auth.inbox(setup.alice.id) == setup.manager.auth.inbox(setup.bob.id) == []
