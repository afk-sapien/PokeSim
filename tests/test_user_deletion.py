"""Running caps, giving an adventure to someone else, and deleting a user without losing their adventures."""
import pytest

from pokesim.app.registry import identifier

from test_accounts import library, people  # noqa: F401  (fixtures)


@pytest.fixture
def quiet(library, monkeypatch):  # noqa: F811
    """Starts and stops change the registry only. No game process is launched."""
    monkeypatch.setattr(library.manager, 'background', lambda function, *args: None)
    return library


def running(library, owner, count):
    rows = []
    for index in range(count):
        aid = library.adventure(f'Busy {index}', owner)
        library.manager.registry.update(aid, desired_state='running')
        rows.append(aid)
    return rows


def offer(library, from_id, to_id, sender=None):
    return library.manager.registry.create_trade_offer(
        {'id': identifier(), 'from_id': from_id, 'from_key': '0', 'to_id': to_id, 'to_key': '1', 'sender_id': sender})


# Running caps --------------------------------------------------------------------------------

def test_the_server_cap_refuses_one_more_start(quiet, people):  # noqa: F811
    admin = quiet.login('admin')
    assert admin.put('/api/v1/running-caps', json={'server': 2, 'member': None}).status_code == 200
    running(quiet, people.admin, 2)
    refused = quiet.login('alice').post(f'/api/v1/adventures/{people.red}/start', json={})
    assert refused.status_code == 409
    assert refused.json()['cap'] is True and '2 of 2 adventures are running' in refused.json()['detail']
    assert quiet.manager.registry.adventure(people.red)['desired_state'] == 'stopped'


def test_the_member_cap_counts_each_owner_and_spares_admins(quiet, people):  # noqa: F811
    admin = quiet.login('admin')
    admin.put('/api/v1/running-caps', json={'server': None, 'member': 1})
    running(quiet, people.alice, 1)
    alice = quiet.login('alice')
    refused = alice.post(f'/api/v1/adventures/{people.red}/start', json={})
    assert refused.status_code == 409 and 'has 1 of 1 adventures running' in refused.json()['detail']
    # Bob has nothing running, so his own start passes.
    assert quiet.login('bob').post(f'/api/v1/adventures/{people.blue}/start', json={}).status_code == 200
    running(quiet, people.admin, 3)
    mine = quiet.adventure('Admin game', people.admin)
    assert admin.post(f'/api/v1/adventures/{mine}/start', json={}).status_code == 200


def test_a_running_adventure_can_start_again_over_the_cap(quiet, people):  # noqa: F811
    quiet.login('admin').put('/api/v1/running-caps', json={'server': 1, 'member': None})
    quiet.manager.registry.update(people.red, desired_state='running')
    assert quiet.login('alice').post(f'/api/v1/adventures/{people.red}/start', json={}).status_code == 200


def test_only_admins_change_caps_and_bad_values_are_refused(quiet, people):  # noqa: F811
    alice = quiet.login('alice')
    shown = alice.get('/api/v1/running-caps').json()
    assert shown['server'] is None and shown['can_change'] is False and shown['suggested_member'] in {2, 4}
    assert alice.put('/api/v1/running-caps', json={'server': 3, 'member': None}).status_code == 403
    admin = quiet.login('admin')
    for bad in ({'server': 0, 'member': None}, {'server': 'many', 'member': None}, {'server': True, 'member': None}):
        assert admin.put('/api/v1/running-caps', json=bad).status_code == 422
    assert admin.put('/api/v1/running-caps', json={'server': 5, 'member': 2}).json()['member'] == 2


# Transfer ------------------------------------------------------------------------------------

def test_a_transfer_moves_ownership_and_clears_the_old_owners_open_work(quiet, people):  # noqa: F811
    manager = quiet.manager
    manager.auth.grant(people.red, people.bob['id'], 'player', people.alice['id'])
    sent = offer(quiet, people.red, people.blue)
    received = offer(quiet, people.blue, people.red)
    forgotten = []
    real_forget = manager.leases.forget
    manager.leases.forget = lambda aid, uid: (forgotten.append((aid, uid)), real_forget(aid, uid))
    alice = quiet.login('alice')
    moved = alice.post(f'/api/v1/adventures/{people.red}/transfer', json={'user_id': people.bob['id']})
    assert moved.status_code == 200, moved.text
    assert manager.registry.adventure(people.red)['owner_id'] == people.bob['id']
    assert manager.auth.grants_for(people.bob['id']) == {}
    assert manager.registry.trade_offer(sent['id'])['status'] == 'withdrawn'
    assert manager.registry.trade_offer(received['id'])['status'] == 'declined'
    assert (people.red, people.alice['id']) in forgotten
    # Alice no longer sees it, Bob owns it now.
    assert alice.get(f'/api/v1/adventures/{people.red}').status_code in {403, 404}
    assert quiet.login('bob').get(f'/api/v1/adventures/{people.red}').json()['access'] == 'owner'


def test_only_the_owner_transfers_and_only_to_a_real_person(quiet, people):  # noqa: F811
    bob = quiet.login('bob')
    assert bob.post(f'/api/v1/adventures/{people.red}/transfer', json={'user_id': people.bob['id']}).status_code in {403, 404}
    alice = quiet.login('alice')
    assert alice.post(f'/api/v1/adventures/{people.red}/transfer', json={'user_id': 'nobody'}).status_code == 404
    assert alice.post(f'/api/v1/adventures/{people.red}/transfer', json={'user_id': people.alice['id']}).status_code == 409
    assert alice.post(f'/api/v1/adventures/{people.red}/transfer', json={}).status_code == 409


# Deleting a user -----------------------------------------------------------------------------

def test_deleting_a_user_needs_a_choice_for_every_adventure(quiet, people):  # noqa: F811
    admin = quiet.login('admin')
    second = quiet.adventure('Red 2', people.alice)
    partial = admin.request('DELETE', f'/api/v1/users/{people.alice["id"]}', json={'adventures': {people.red: 'archive'}})
    assert partial.status_code == 409
    assert quiet.manager.auth.user(people.alice['id']) is not None
    done = admin.request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                         json={'adventures': {people.red: people.bob['id'], second: 'archive'}})
    assert done.status_code == 200, done.text
    registry = quiet.manager.registry
    assert quiet.manager.auth.user(people.alice['id']) is None
    assert registry.adventure(people.red)['owner_id'] == people.bob['id']
    kept = registry.adventure(second)
    assert kept['archived'] and kept['desired_state'] == 'stopped' and kept['owner_id'] == people.admin['id']


def test_deleting_a_user_ends_their_sessions_grants_and_sent_offers(quiet, people):  # noqa: F811
    manager = quiet.manager
    manager.auth.grant(people.blue, people.alice['id'], 'manager', people.bob['id'])
    # Alice sent this from Bob's adventure to the admin's, so neither archived adventure is in it.
    sent = offer(quiet, people.blue, quiet.adventure('Green', people.admin), sender=people.alice['id'])
    alice = quiet.login('alice')
    admin = quiet.login('admin')
    assert admin.request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                         json={'adventures': {people.red: 'archive'}}).status_code == 200
    assert manager.auth.grants(people.blue) == []
    assert manager.registry.trade_offer(sent['id'])['status'] == 'withdrawn'
    assert alice.get('/api/v1/adventures').status_code == 401


def test_deleting_is_for_admins_and_never_yourself_or_the_last_admin(quiet, people):  # noqa: F811
    alice = quiet.login('alice')
    assert alice.request('DELETE', f'/api/v1/users/{people.bob["id"]}',
                         json={'adventures': {people.blue: 'archive'}}).status_code == 403
    admin = quiet.login('admin')
    assert admin.request('DELETE', f'/api/v1/users/{people.admin["id"]}', json={'adventures': {}}).status_code == 409
    other = quiet.user('second', 'admin')
    second = quiet.login('second')
    assert second.request('DELETE', f'/api/v1/users/{people.admin["id"]}', json={'adventures': {}}).status_code == 200
    # The admin who is left cannot be removed by anyone.
    assert quiet.manager.auth._admins() == 1 and quiet.manager.auth.user(other['id'])
