"""Rights read again once a request body is in, and again where a slow action changes something."""
import asyncio
import threading

import pytest

from pokesim.app import manager as manager_module, ownership
from pokesim.app.deletion import delete_adventure
from pokesim.app.ownership import NoLongerOwner

from test_accounts import library, meanwhile, people  # noqa: F401  (fixtures)
from test_user_deletion import quiet  # noqa: F401  (fixture)


def waits_for_the_guard(manager, work):
    """Whether `work` waits while another thread holds `offers.guard`."""
    held, release = threading.Event(), threading.Event()

    def hold():
        with manager.offers.guard:
            held.set()
            release.wait(5)
    holder = threading.Thread(target=hold)
    holder.start()
    held.wait(5)
    worker = threading.Thread(target=work)
    worker.start()
    worker.join(0.3)
    waited = worker.is_alive()
    release.set()
    worker.join(5)
    holder.join(5)
    return waited


def test_an_old_owner_cannot_take_the_adventure_back_by_transfer(quiet, people, meanwhile):  # noqa: F811
    manager = quiet.manager
    admin = manager.actor_for(people.admin)
    alice = quiet.login('alice')
    meanwhile(lambda: ownership.transfer(manager, people.red, people.bob['id'], admin))
    moved = alice.post(f'/api/v1/adventures/{people.red}/transfer', json={'user_id': people.alice['id']})
    assert moved.status_code in {403, 404}, moved.text
    assert manager.registry.adventure(people.red)['owner_id'] == people.bob['id']
    # A transfer already under way when the adventure moved checks again under the guard.
    stale = manager.actor_for(people.alice)
    green = quiet.adventure('Green', people.alice)
    ownership.transfer(manager, green, people.bob['id'], admin)
    with pytest.raises(NoLongerOwner):
        ownership.transfer(manager, green, people.alice['id'], stale)
    assert manager.registry.adventure(green)['owner_id'] == people.bob['id']


def test_a_demoted_admin_cannot_promote_themselves_back(quiet, people, meanwhile):  # noqa: F811
    manager = quiet.manager
    carol = quiet.user('carol', 'admin')
    admin = manager.actor_for(people.admin)
    client = quiet.login('carol')
    meanwhile(lambda: ownership.change_user(manager, carol['id'], admin, role='member'))
    again = client.patch(f"/api/v1/users/{carol['id']}", json={'role': 'admin'})
    assert again.status_code in {401, 403}, again.text
    assert manager.auth.user(carol['id'])['role'] == 'member'


def test_an_old_owner_cannot_delete_the_adventure(quiet, people, meanwhile):  # noqa: F811
    manager = quiet.manager
    admin = manager.actor_for(people.admin)
    for aid in (people.red,):
        manager.registry.transition(aid, 'stopped', 'test setup', desired_state='stopped')
    name = manager.registry.adventure(people.red)['name']
    alice = quiet.login('alice')
    meanwhile(lambda: ownership.transfer(manager, people.red, people.bob['id'], admin))
    gone = alice.request('DELETE', f'/api/v1/adventures/{people.red}', json={'confirmation': name})
    assert gone.status_code in {403, 404}, gone.text
    assert manager.registry.adventure(people.red)['owner_id'] == people.bob['id']
    # A deletion that read its rights before a transfer checks again once it holds its locks.
    green = quiet.adventure('Green', people.alice)
    manager.registry.transition(green, 'stopped', 'test setup', desired_state='stopped')
    stale = manager.actor_for(people.alice)
    ownership.transfer(manager, green, people.bob['id'], admin)
    with pytest.raises(NoLongerOwner):
        delete_adventure(manager, green, manager.registry.adventure(green)['name'], stale)
    assert manager.registry.adventure(green)['state'] == 'stopped'


def test_a_built_trade_is_not_queued_for_an_adventure_its_owner_lost(quiet, people, monkeypatch):  # noqa: F811
    manager = quiet.manager
    admin = manager.actor_for(people.admin)
    green = quiet.adventure('Green', people.alice)
    stale = manager.actor_for(people.alice)
    ownership.transfer(manager, green, people.bob['id'], admin)
    queued = []
    monkeypatch.setattr(manager.builder, '_writer', lambda aid: None)
    monkeypatch.setattr(manager.builder, '_check', lambda selection: ({}, {}))
    monkeypatch.setattr(manager.coordinator, 'enqueue_manual', queued.append)
    trade = {'from_id': people.red, 'from_key': 'a', 'to_id': green, 'to_key': 'b'}
    with pytest.raises(NoLongerOwner):
        manager.builder.create(trade, stale)
    assert queued == []


def test_a_proposed_trade_is_not_recorded_for_an_adventure_its_owner_lost(quiet, people, monkeypatch):  # noqa: F811
    manager = quiet.manager
    coordinator = manager.coordinator
    admin = manager.actor_for(people.admin)
    green = quiet.adventure('Green', people.alice)
    stale = manager.actor_for(people.alice)
    ownership.transfer(manager, green, people.bob['id'], admin)
    recorded = []
    monkeypatch.setattr(coordinator, '_admit', lambda tid, selection: None)
    monkeypatch.setattr(coordinator, 'manual_inventory', lambda aid: {})
    monkeypatch.setattr(coordinator, '_manual_offer', lambda inventory, key: {})
    monkeypatch.setattr(coordinator, '_mon_display', lambda offer: {})
    monkeypatch.setattr(coordinator, '_offer_for', lambda offer, inventory: {})
    monkeypatch.setattr(coordinator, '_compatible_pair', lambda *sides: True)
    monkeypatch.setattr(manager.registry, 'create_transaction', lambda tid, plan: recorded.append(plan))
    trade = {'left_id': people.red, 'left_key': 'a', 'right_id': green, 'right_key': 'b', 'manual': True}
    with pytest.raises(NoLongerOwner):
        coordinator.propose(trade, stale)
    assert recorded == []


def test_a_press_that_waited_in_line_checks_the_role_again(library, people, monkeypatch):  # noqa: F811
    manager = library.manager
    auth, bob = manager.auth, library.login('bob')
    auth.grant(people.red, people.bob['id'], 'player', people.alice['id'])
    assert bob.post(f'/games/{people.red}/api/lease', json={'action': 'request'}).json()['you_hold']
    holds = manager.leases.holds

    def demoted_while_waiting(aid, actor):
        held = holds(aid, actor)
        auth.grant(people.red, people.bob['id'], 'viewer', people.alice['id'])
        return held
    monkeypatch.setattr(manager.leases, 'holds', demoted_while_waiting)
    pressed = bob.post(f'/games/{people.red}/api/control', json={'action': 'press', 'button': 'a'})
    assert pressed.status_code == 403, pressed.text


def test_offers_end_under_the_guard_after_a_role_change_or_a_deleted_user(library, people):  # noqa: F811
    manager = library.manager
    admin = manager.actor_for(people.admin)
    assert waits_for_the_guard(manager, lambda: ownership.recheck(manager, people.bob['id'], admin))
    carol = library.user('carol')
    assert waits_for_the_guard(manager, lambda: ownership.delete_user(manager, carol['id'], {}, admin))
    assert manager.auth.user(carol['id']) is None


def test_a_body_that_never_finishes_is_refused(library, people, monkeypatch):  # noqa: F811
    from starlette.requests import Request

    async def stalled(self):
        await asyncio.sleep(1)
        yield b'{}'
    alice = library.login('alice')
    monkeypatch.setattr(manager_module, 'BODY_SECONDS', 0.05)
    monkeypatch.setattr(Request, 'stream', stalled)
    slow = alice.patch(f'/api/v1/adventures/{people.red}', json={'name': 'Late'})
    assert slow.status_code == 408, slow.text
