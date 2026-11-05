"""The control lease: one account plays an adventure by hand at a time, with roles below the owner."""
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.app import lease as lease_module
from pokesim.app import policy
from pokesim.store import Store
from pokesim.web.app import create_app
from pokesim.web.security import LEASE_HEADER, role_allows

from test_accounts import library, people  # noqa: F401


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def game(library, people, monkeypatch):  # noqa: F811
    """Alice owns Red. Bob can play it, Carol can manage it and Dave can watch it."""
    calls = []

    def request(aid):
        def send(method, path, body=None, timeout=None, headers=None):
            calls.append((aid, path, (body or {}).get('action')))
            return {'ok': True}
        return send
    monkeypatch.setattr(library.manager.supervisor, 'child', lambda aid: SimpleNamespace(
        url='http://127.0.0.1:12345', token='private-worker-token', request=request(aid)))
    clock = Clock()
    library.manager.leases.clock = clock
    carol, dave = library.user('carol'), library.user('dave')
    auth = library.manager.auth
    auth.grant(people.red, people.bob['id'], 'player', people.alice['id'])
    auth.grant(people.red, carol['id'], 'manager', people.alice['id'])
    auth.grant(people.red, dave['id'], 'viewer', people.alice['id'])
    return SimpleNamespace(library=library, red=people.red, calls=calls, clock=clock,
                           alice=library.login('alice'), bob=library.login('bob'), carol=library.login('carol'),
                           dave=library.login('dave'), ids=SimpleNamespace(bob=people.bob['id'], carol=carol['id']))


def lease(client, aid, action=None, **extra):
    if action is None:
        return client.get(f'/games/{aid}/api/lease')
    return client.post(f'/games/{aid}/api/lease', json={'action': action, **extra})


def press(client, aid):
    return client.post(f'/games/{aid}/api/control', json={'action': 'press', 'value': 'a'})


def test_roles_map_to_controls():
    assert policy.game_action('POST', 'api/control', 'press') == 'adventure.play'
    assert policy.game_action('POST', 'api/control', 'pause') == 'adventure.manage'
    assert policy.game_action('POST', 'api/control', 'restart') == 'adventure.own'
    assert policy.game_action('POST', 'api/lease') == 'adventure.play'
    assert policy.game_action('GET', 'api/lease') == 'adventure.watch'
    assert policy.game_action('GET', 'api/states') == 'adventure.manage'
    assert role_allows('player', 'POST', '/api/control')
    assert not role_allows('player', 'POST', '/api/speed')
    assert role_allows('manager', 'POST', '/api/speed')
    assert not role_allows('manager', 'POST', '/api/export-save')


def test_a_press_needs_the_lease_and_the_first_request_wins(game):
    assert press(game.bob, game.red).status_code == 409
    granted = lease(game.bob, game.red, 'request').json()
    assert granted['you_hold'] and granted['role'] == 'player'
    assert (game.red, '/api/control', 'take_control') in game.calls
    assert press(game.bob, game.red).status_code == 200
    # A second person queues and cannot press.
    queued = lease(game.carol, game.red, 'request').json()
    assert not queued['you_hold'] and queued['queued']
    assert press(game.carol, game.red).status_code == 409
    # A watcher sees who plays, but not the queue or the holder's id.
    watched = lease(game.dave, game.red).json()
    assert watched['holder'] == {'name': 'bob'} and watched['queue'] == []
    assert lease(game.dave, game.red, 'request').status_code == 403
    assert press(game.dave, game.red).status_code == 403


def test_the_holder_hands_over_or_refuses(game):
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    status = lease(game.bob, game.red).json()
    assert [entry['id'] for entry in status['queue']] == [game.ids.carol]
    lease(game.bob, game.red, 'refuse', user_id=game.ids.carol)
    assert lease(game.bob, game.red).json()['queue'] == []
    lease(game.carol, game.red, 'request')
    handed = lease(game.bob, game.red, 'handover', user_id=game.ids.carol).json()
    assert not handed['you_hold'] and handed['holder']['name'] == 'carol'
    assert press(game.carol, game.red).status_code == 200
    assert press(game.bob, game.red).status_code == 409


def test_an_owner_or_manager_takes_control_back(game):
    lease(game.bob, game.red, 'request')
    assert lease(game.bob, game.red, 'take').status_code == 403
    taken = lease(game.alice, game.red, 'take').json()
    assert taken['you_hold']
    assert press(game.bob, game.red).status_code == 409


def test_letting_go_passes_control_on_or_applies_the_owners_choice(game):
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    lease(game.bob, game.red, 'release')
    assert lease(game.carol, game.red).json()['you_hold']
    assert lease(game.bob, game.red, 'setting', end='pause').status_code == 403
    assert lease(game.alice, game.red, 'setting', end='pause').json()['end'] == 'pause'
    lease(game.carol, game.red, 'release')
    assert game.calls[-1] == (game.red, '/api/control', 'pause')
    assert lease(game.carol, game.red).json()['holder'] is None


def test_quiet_pages_and_idle_hands_lose_control(game, monkeypatch):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    game.clock.now += lease_module.HEARTBEAT_GRACE_SECONDS - 1
    lease(game.bob, game.red, 'heartbeat')
    game.clock.now += lease_module.HEARTBEAT_GRACE_SECONDS - 1
    leases.sweep()
    assert leases.holder(game.red) == game.ids.bob
    game.clock.now += 2
    leases.sweep()
    assert leases.holder(game.red) is None
    assert game.calls[-1] == (game.red, '/api/control', 'resume')
    # Heartbeats alone do not keep control: buttons must be pressed.
    monkeypatch.setenv('CONTROL_IDLE_SECONDS', '60')
    lease(game.bob, game.red, 'request')
    game.clock.now += 40
    lease(game.bob, game.red, 'heartbeat')
    status = lease(game.bob, game.red).json()
    assert status['idle_warning'] and status['idle_ends_in'] == 20
    game.clock.now += 21
    lease(game.bob, game.red, 'heartbeat')
    leases.sweep()
    assert leases.holder(game.red) is None


def test_losing_can_play_ends_the_lease(game):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    game.alice.post(f'/api/v1/adventures/{game.red}/grants', json={'user_id': game.ids.bob, 'role': 'viewer'})
    assert leases.holder(game.red) == game.ids.carol
    game.alice.delete(f'/api/v1/adventures/{game.red}/grants/{game.ids.carol}')
    assert leases.holder(game.red) is None


def test_losing_can_manage_ends_what_it_allowed(game, monkeypatch):
    from pokesim.app import ownership
    leases = game.library.manager.leases
    unshared = []
    monkeypatch.setattr(ownership, 'unshare', lambda manager, aid, uid, actor=None: unshared.append(uid))
    lease(game.bob, game.red, 'request')
    assert lease(game.carol, game.red, 'take').json()['you_hold']
    # Sharing Red with Bob again as a player changes nothing, so Carol keeps control.
    game.alice.post(f'/api/v1/adventures/{game.red}/grants', json={'user_id': game.ids.bob, 'role': 'player'})
    assert leases.holder(game.red) == game.ids.carol and unshared == []
    game.alice.post(f'/api/v1/adventures/{game.red}/grants', json={'user_id': game.ids.carol, 'role': 'player'})
    assert leases.holder(game.red) != game.ids.carol and unshared == [game.ids.carol]


def test_a_grant_change_ends_the_lease_off_the_event_loop(game, monkeypatch):
    """Ending a lease can wait on a slow worker, which must never stall every other page."""
    import asyncio
    leases, on_loop = game.library.manager.leases, []
    forget = leases.forget

    def watched(aid, uid):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return forget(aid, uid)
    monkeypatch.setattr(leases, 'forget', watched)
    lease(game.carol, game.red, 'take')
    game.alice.post(f'/api/v1/adventures/{game.red}/grants', json={'user_id': game.ids.carol, 'role': 'viewer'})
    assert on_loop == [False]


def test_a_demotion_or_a_disable_ends_what_the_old_role_allowed(game, people):  # noqa: F811
    from pokesim.app.registry import identifier
    manager = game.library.manager
    leases, registry = manager.leases, manager.registry
    game.library.user('second', 'admin')
    second = game.library.login('second')
    admin = game.library.login('admin')
    lease(game.bob, game.red, 'request')
    assert lease(admin, game.red, 'request').json()['queued']
    # The admin sent an offer from Red, which only admins and its managers may do.
    sent = registry.create_trade_offer({'id': identifier(), 'from_id': game.red, 'from_key': '0', 'to_id': people.blue,
                                        'to_key': '1', 'sender_id': people.admin['id']})
    assert second.patch(f"/api/v1/users/{people.admin['id']}", json={'role': 'member'}).status_code == 200
    assert registry.trade_offer(sent['id'])['status'] == 'withdrawn'
    assert [entry['user_id'] for entry in leases.current(game.red).queue] == []
    # Disabling the person in control hands control on.
    lease(game.carol, game.red, 'request')
    assert second.patch(f'/api/v1/users/{game.ids.bob}', json={'disabled': True}).status_code == 200
    assert leases.holder(game.red) == game.ids.carol


def test_a_trade_or_backup_ends_control(game):
    manager = game.library.manager
    lease(game.bob, game.red, 'request')
    assert manager.leases.end_all('backup') == [game.red]
    lease(game.bob, game.red, 'request')
    manager.suspended = True
    try:
        refused = lease(game.carol, game.red, 'take')
    finally:
        manager.suspended = False
    assert refused.status_code == 409 and 'backup' in refused.json()['detail']


def test_resume_and_pause_end_the_lease(game):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    assert game.bob.post(f'/games/{game.red}/api/control', json={'action': 'pause'}).status_code == 403
    assert game.carol.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 200
    assert leases.holder(game.red) is None


def test_a_resume_the_worker_never_got_keeps_the_lease(game):
    leases, app = game.library.manager.leases, game.library.app
    lease(game.bob, game.red, 'request')

    def unreachable(request):
        raise httpx.ConnectError('the worker is restarting')
    # The library fixture already replaced httpx.AsyncClient, so start from the real class.
    original = httpx._client.AsyncClient
    app.state.children = original(transport=httpx.MockTransport(unreachable))
    assert game.carol.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 503
    assert leases.holder(game.red) == game.ids.bob
    app.state.children = original(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    assert game.carol.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 500
    assert leases.holder(game.red) == game.ids.bob


def test_a_slow_worker_holds_up_only_its_own_adventure(game, monkeypatch):
    manager = game.library.manager
    leases, entered, answer = manager.leases, threading.Event(), threading.Event()

    def child(aid):
        def send(method, path, body=None, timeout=None, headers=None):
            entered.set()
            answer.wait(5)
            return {'ok': True}
        return SimpleNamespace(url='http://127.0.0.1:12345', token='private-worker-token', request=send)
    monkeypatch.setattr(manager.supervisor, 'child', child)
    bob = manager.actor_for(manager.auth.user(game.ids.bob))
    asking = threading.Thread(target=leases.act, args=(game.red, bob, manager.registry.adventure(game.red), 'request'))
    asking.start()
    try:
        assert entered.wait(5)
        # Another page reads and sweeps while Red's worker has not answered.
        assert leases.lock.acquire(timeout=1)
        leases.lock.release()
        assert lease(game.dave, game.red).json()['holder'] is None
    finally:
        answer.set()
        asking.join(5)
    assert leases.holder(game.red) == game.ids.bob


def test_a_refused_hand_on_ends_the_lease_once(game, monkeypatch):
    manager = game.library.manager
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    manager.suspended = True
    try:
        lease(game.bob, game.red, 'release')
    finally:
        manager.suspended = False
    assert manager.leases.holder(game.red) is None
    ends = [row for row in manager.auth.audit_rows() if row['action'] == 'lease.end']
    assert len(ends) == 1 and ends[0]['user_id'] == game.ids.bob


def test_a_quiet_queued_page_leaves_the_line(game):
    leases = game.library.manager.leases

    def wait(seconds):
        # Bob keeps his page open and presses buttons, so only Carol's page is quiet.
        game.clock.now += seconds
        lease(game.bob, game.red, 'heartbeat')
        press(game.bob, game.red)
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    # A hidden tab runs its timers about once a minute, so two minutes of silence keeps her place.
    for _ in range(4):
        wait(30)
    leases.sweep()
    status = lease(game.carol, game.red).json()
    assert status['queued'] and 'left_line' not in status
    # Carol closed her tab. When Bob lets go nobody is waiting, so control is not passed to her.
    wait(lease_module.QUEUE_GRACE_SECONDS - 120 + 1)
    leases.sweep()
    status = lease(game.carol, game.red).json()
    assert not status['queued'] and status['left_line'] == 'quiet'
    # Her page hears it once.
    assert 'left_line' not in lease(game.carol, game.red).json()
    lease(game.bob, game.red, 'release')
    assert leases.holder(game.red) is None


def test_a_refused_page_hears_why(game):
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    lease(game.bob, game.red, 'refuse', user_id=game.ids.carol)
    assert lease(game.carol, game.red).json()['left_line'] == 'refused'
    lease(game.carol, game.red, 'request')
    assert 'left_line' not in lease(game.carol, game.red).json()


def test_a_page_in_line_that_can_no_longer_play_hears_why(game, people):  # noqa: F811
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    # Carol can only watch now, and nothing took her out of the line before Bob let go.
    game.library.manager.auth.grant(game.red, game.ids.carol, 'viewer', people.alice['id'])
    lease(game.bob, game.red, 'release')
    status = lease(game.carol, game.red).json()
    assert status['holder'] is None and not status['queued'] and status['left_line'] == 'no_longer_allowed'


def test_a_backup_during_a_lease_change_does_not_hang(game, monkeypatch):
    """A take asks the registry whether a trade holds the adventure while a backup ends every lease."""
    from pokesim.app import backup
    manager = game.library.manager
    coordinator, inside, go = manager.coordinator, threading.Event(), threading.Event()
    reserved = coordinator.reserved

    def slow_reserved(aid):
        inside.set()
        go.wait(5)
        return reserved(aid)
    lease(game.bob, game.red, 'request')
    monkeypatch.setattr(coordinator, 'reserved', slow_reserved)
    carol = manager.actor_for(manager.auth.user(game.ids.carol))
    asking = threading.Thread(target=manager.leases.act, args=(game.red, carol, manager.registry.adventure(game.red), 'take'),
                              daemon=True)
    asking.start()
    assert inside.wait(5)
    made = []
    backing_up = threading.Thread(target=lambda: made.append(backup.create_backup(manager)), daemon=True)
    backing_up.start()
    for _ in range(100):
        if manager.suspended:
            break
        threading.Event().wait(0.02)
    # Let the backup reach the lease before the grant asks the registry.
    threading.Event().wait(0.2)
    go.set()
    asking.join(10)
    backing_up.join(10)
    assert not asking.is_alive() and not backing_up.is_alive()
    assert made and manager.leases.holder(game.red) is None


def test_no_handover_lands_while_the_worker_resumes(game):
    """A handover asked for during Resume waits for it, so nobody holds control while the autopilot plays."""
    manager, app = game.library.manager, game.library.app
    leases = manager.leases
    lease(game.bob, game.red, 'request')
    carol = manager.actor_for(manager.auth.user(game.ids.carol))
    adventure = manager.registry.adventure(game.red)

    def hand_over():
        leases.end(game.red, 'release', apply=False)
        leases.act(game.red, carol, adventure, 'request')
    handover = threading.Thread(target=hand_over, daemon=True)

    def resumed(request):
        handover.start()
        handover.join(0.3)
        assert handover.is_alive(), 'the handover landed between Resume and the end of the lease'
        return httpx.Response(200, json={'ok': True})
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(resumed))
    assert game.alice.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 200
    handover.join(5)
    # Carol asked after the autopilot took over, so she holds a fresh lease.
    assert not handover.is_alive() and leases.holder(game.red) == game.ids.carol


def test_resume_refuses_once_control_changed_hands(game, monkeypatch):
    manager, app = game.library.manager, game.library.app
    leases, sent = manager.leases, []
    lease(game.bob, game.red, 'request')
    access = manager.leases.current
    # Control changes hands after the access check read the lease and before the worker hears of it.
    reads = iter([access(game.red), object()])
    monkeypatch.setattr(leases, 'current', lambda aid: next(reads, None) or access(aid))
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200, json={'ok': True})))
    assert game.alice.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 409
    assert not sent


def test_a_press_from_the_old_holder_never_reaches_the_new_one(game, monkeypatch):
    manager, app = game.library.manager, game.library.app
    leases, sent = manager.leases, []
    lease(game.bob, game.red, 'request')
    carol = manager.actor_for(manager.auth.user(game.ids.carol))
    adventure = manager.registry.adventure(game.red)
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200, json={'ok': True})))
    reserved = manager.coordinator.reserved

    def handed_over(aid):
        # Control changes hands after the access check and before the press reaches the worker.
        if leases.holder(game.red) == game.ids.bob:
            leases.end(game.red, 'release', apply=False)
            leases.act(game.red, carol, adventure, 'request')
        return reserved(aid)
    monkeypatch.setattr(manager.coordinator, 'reserved', handed_over)
    assert press(game.bob, game.red).status_code == 409
    assert leases.holder(game.red) == game.ids.carol and not sent
    assert press(game.carol, game.red).status_code == 200 and len(sent) == 1


def test_a_held_key_against_a_slow_worker_holds_no_threads_and_keeps_its_order(game, monkeypatch):
    """A held arrow key sends a press every 140 ms. A slow worker must not use up the request
    threads that every page and sign in share, and the presses must reach it in order."""
    import anyio.to_thread
    monkeypatch.setattr('pokesim.app.manager.PRESS_WAIT_SECONDS', 60)
    app, arrived = game.library.app, []
    lease(game.bob, game.red, 'request')
    buttons = ['down', 'a', 'up', 'b', 'left', 'right', 'start', 'select']

    async def held():
        anyio.to_thread.current_default_thread_limiter().total_tokens = 4
        answer = asyncio.Event()

        async def slow(request):
            arrived.append(json.loads(request.content)['value'])
            await answer.wait()
            return httpx.Response(200, json={'ok': True})
        app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(slow))
        async with httpx._client.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver',
                                             cookies=game.bob.cookies, headers=dict(game.bob.headers)) as page:
            presses = []
            for count, button in enumerate(buttons, 1):
                presses.append(asyncio.create_task(page.post(
                    f'/games/{game.red}/api/control', json={'action': 'press', 'value': button})))
                # Like a key repeat, each press is sent once the one before it is in line.
                for _ in range(100):
                    if presses[-1].done() or getattr(app.state, 'press_lines', {}).get(game.red, [None, 0])[1] >= count:
                        break
                    await asyncio.sleep(0.01)
            try:
                # A full line of presses waits on the worker, and a page still reads who holds control.
                status = await asyncio.wait_for(page.get(f'/games/{game.red}/api/lease'), 3)
                assert status.status_code == 200 and status.json()['holder'] is not None
            finally:
                answer.set()
            return [response.status_code for response in await asyncio.gather(*presses)]
    assert asyncio.run(held()) == [200] * len(buttons)
    assert arrived == buttons


def line_against_a_stalled_worker(game, requests, between=None):
    """Send control requests to a worker that answers none until the last one is in line. Returns
    the status codes and the actions or buttons in the order the worker heard them."""
    app, arrived = game.library.app, []

    async def run():
        answer = asyncio.Event()

        async def stalled(request):
            sent = json.loads(request.content)
            arrived.append(sent.get('value') or sent['action'])
            await answer.wait()
            return httpx.Response(200, json={'ok': True})
        app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(stalled))
        pages, sent = [], []
        try:
            for count, (client, body) in enumerate(requests, 1):
                pages.append(httpx._client.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver',
                                                       cookies=client.cookies, headers=dict(client.headers)))
                sent.append(asyncio.create_task(pages[-1].post(f'/games/{game.red}/api/control', json=body)))
                # Each request is sent once the one before it is in line, or was turned away.
                for _ in range(100):
                    if sent[-1].done() or app.state.press_lines.get(game.red, [None, 0])[1] >= count:
                        break
                    await asyncio.sleep(0.01)
            if between:
                await between()
            answer.set()
            return [response.status_code for response in await asyncio.gather(*sent)]
        finally:
            answer.set()
            for page in pages:
                await page.aclose()
    return asyncio.run(run()), arrived


def presses(client, *buttons):
    return [(client, {'action': 'press', 'value': button}) for button in buttons]


def test_a_full_press_line_turns_the_next_press_away(game):
    lease(game.bob, game.red, 'request')
    buttons = ['down', 'a', 'up', 'b', 'left', 'right', 'start', 'select']
    codes, arrived = line_against_a_stalled_worker(game, presses(game.bob, *buttons, 'a'))
    # Eight presses wait, the ninth is refused at once, and only the eight reach the game.
    assert codes == [200] * 8 + [429]
    assert arrived == buttons


def test_a_press_that_waited_too_long_is_dropped(game, monkeypatch):
    monkeypatch.setattr('pokesim.app.manager.PRESS_WAIT_SECONDS', 0.2)
    lease(game.bob, game.red, 'request')
    codes, arrived = line_against_a_stalled_worker(game, presses(game.bob, 'down', 'a'),
                                                   between=lambda: asyncio.sleep(0.5))
    assert codes == [200, 409] and arrived == ['down']


def test_a_press_from_a_closed_page_is_dropped(game, monkeypatch):
    from starlette.requests import Request
    lease(game.bob, game.red, 'request')
    closed = []

    async def is_disconnected(self):
        # The second press's page closed while it waited in line.
        return bool(closed)

    async def close_page():
        closed.append(True)
    monkeypatch.setattr(Request, 'is_disconnected', is_disconnected)
    codes, arrived = line_against_a_stalled_worker(game, presses(game.bob, 'down', 'a'), between=close_page)
    assert codes[1] == 409 and arrived == ['down']


def test_resume_waits_behind_the_presses_before_it(game, monkeypatch):
    monkeypatch.setattr(game.library.manager, 'auth_mode', 'none')
    page = game.library.browser()
    page.headers['X-PokeSim-CSRF'] = page.get('/api/v1/session').json()['csrf_token']
    # Without accounts nobody holds a lease, so only the line keeps a press from landing after Resume.
    codes, arrived = line_against_a_stalled_worker(
        game, [*presses(page, 'down', 'a'), (page, {'action': 'resume'})])
    assert codes == [200, 200, 200] and arrived == ['down', 'a', 'resume']


def test_a_refused_take_control_never_turns_the_holders_presses_away(game, monkeypatch):
    manager = game.library.manager
    leases = manager.leases
    bob = manager.actor_for(manager.auth.user(game.ids.bob))
    lease(game.bob, game.red, 'request')
    valid = []

    def refused(aid, action, generation):
        # While the worker is asked, Bob's presses still carry the newest generation.
        valid.append(leases.stamp(aid, bob) == leases.generation(aid))
        return False
    monkeypatch.setattr(leases, 'worker', refused)
    assert lease(game.carol, game.red, 'take').status_code == 409
    assert valid == [True] and leases.holder(game.red) == game.ids.bob
    assert press(game.bob, game.red).status_code == 200


def test_a_refused_resume_never_turns_the_holders_presses_away(game):
    manager, app = game.library.manager, game.library.app
    leases = manager.leases
    bob = manager.actor_for(manager.auth.user(game.ids.bob))
    lease(game.bob, game.red, 'request')
    valid = []

    def busy(request):
        valid.append(leases.stamp(game.red, bob) == leases.generation(game.red))
        return httpx.Response(409, json={'detail': 'A trade holds this adventure'})
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(busy))
    assert game.alice.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 409
    assert valid == [True] and leases.holder(game.red) == game.ids.bob


def test_someone_who_cannot_press_never_takes_a_place_in_the_line(game):
    lease(game.bob, game.red, 'request')
    # Dave only watches. His presses are turned away before the line, so Bob's next press still joins it.
    codes, arrived = line_against_a_stalled_worker(
        game, [*presses(game.bob, 'a'), *presses(game.dave, *'abcdefgh'), *presses(game.bob, 'b')])
    assert codes == [200] + [403] * 8 + [200] and arrived == ['a', 'b']


def test_a_full_press_line_still_takes_resume_in_order(game):
    lease(game.bob, game.red, 'request')
    buttons = ['down', 'a', 'up', 'b', 'left', 'right', 'start', 'select']
    codes, arrived = line_against_a_stalled_worker(
        game, [*presses(game.bob, *buttons), (game.alice, {'action': 'resume'})])
    assert codes == [200] * 9 and arrived == [*buttons, 'resume']


def test_a_take_control_that_timed_out_moves_the_holder_to_its_generation(game, monkeypatch):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    asked = []

    def timed_out(aid, action, generation):
        # The worker took control, but its answer never came back.
        asked.append(generation)
        return False
    monkeypatch.setattr(leases, 'worker', timed_out)
    assert lease(game.carol, game.red, 'take').status_code == 409
    assert leases.holder(game.red) == game.ids.bob
    # The worker now refuses anything older than the take_control, so Bob's presses carry it too.
    assert press(game.bob, game.red).status_code == 200
    assert game.library.forwarded[-1].headers[LEASE_HEADER] == str(asked[0])


def test_a_resume_that_timed_out_moves_the_holder_to_its_generation(game):
    app = game.library.app
    lease(game.bob, game.red, 'request')
    asked, sent = [], []

    def timed_out(request):
        asked.append(request.headers[LEASE_HEADER])
        raise httpx.ReadTimeout('no answer', request=request)
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(timed_out))
    assert game.alice.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 503
    assert game.library.manager.leases.holder(game.red) == game.ids.bob
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200, json={'ok': True})))
    assert press(game.bob, game.red).status_code == 200
    assert sent[-1].headers[LEASE_HEADER] == asked[0]


def test_a_resume_without_a_lease_waits_for_a_grant_under_way(game):
    manager, app = game.library.manager, game.library.app
    leases, sent = manager.leases, []
    carol = manager.actor_for(manager.auth.user(game.ids.carol))
    adventure = manager.registry.adventure(game.red)
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200, json={'ok': True})))
    granting = threading.Event()

    def grant():
        # Carol's request has sent take_control and not yet recorded her lease.
        with leases.turn(game.red):
            granting.set()
            threading.Event().wait(0.3)
            leases.act(game.red, carol, adventure, 'request')
    granter = threading.Thread(target=grant)
    granter.start()
    granting.wait(5)
    resumed = game.alice.post(f'/games/{game.red}/api/control', json={'action': 'resume'})
    granter.join(5)
    # The Resume waited for the grant, found Carol in control and never reached the game.
    assert resumed.status_code == 409 and not sent
    assert leases.holder(game.red) == game.ids.carol


def test_a_slow_press_keeps_the_usual_time_limit(game):
    lease(game.bob, game.red, 'request')
    assert press(game.bob, game.red).status_code == 200
    # A press that takes longer than five seconds still works, so the page never shows a 503
    # for a press the game made.
    sent = game.library.forwarded[-1]
    assert sent.url.path == '/api/control' and sent.extensions['timeout']['read'] == 30


def test_a_press_carries_its_lease_generation(game):
    app, sent = game.library.app, []
    lease(game.bob, game.red, 'request')
    first = game.library.manager.leases.generation(game.red)
    app.state.children = httpx._client.AsyncClient(transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200, json={'ok': True})))
    assert press(game.bob, game.red).status_code == 200
    assert sent[-1].headers[LEASE_HEADER] == str(first)
    lease(game.bob, game.red, 'release')
    lease(game.carol, game.red, 'request')
    assert game.library.manager.leases.generation(game.red) > first
    assert press(game.carol, game.red).status_code == 200
    assert int(sent[-1].headers[LEASE_HEADER]) > first


def test_the_worker_drops_a_press_from_before_control_changed_hands(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    emu = Mock()
    with TestClient(create_app(emu, Store(tmp_path))) as worker:
        def control(action, generation, value=None):
            return worker.post('/api/control', json={'action': action, 'value': value},
                               headers={LEASE_HEADER: str(generation)})
        assert control('take_control', 3).status_code == 200
        assert control('press', 3, 'a').status_code == 200
        assert control('take_control', 5).status_code == 200
        # Bob's press left the library just before Carol took over, and reaches the game after.
        assert control('press', 3, 'down').status_code == 409
        assert control('press', 5, 'down').status_code == 200
    assert [call.args for call in emu.press.call_args_list] == [('a',), ('down',)]


def test_a_page_in_line_hears_that_control_ended(game):
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    assert game.alice.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 200
    status = lease(game.carol, game.red).json()
    assert not status['queued'] and status['left_line'] == 'ended'
    assert 'left_line' not in lease(game.carol, game.red).json()


def test_an_adventure_without_a_lease_keeps_no_turn_lock(game):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    assert game.red in leases.turns
    lease(game.bob, game.red, 'release')
    assert leases.holder(game.red) is None and game.red not in leases.turns


def test_the_worker_hears_the_role(game):
    game.library.forwarded.clear()
    game.bob.get(f'/games/{game.red}/api/state')
    game.carol.get(f'/games/{game.red}/api/state')
    game.alice.get(f'/games/{game.red}/api/state')
    roles = [request.headers.get('X-PokeSim-Role') for request in game.library.forwarded]
    assert roles == ['player', 'manager', None]


def test_an_open_stream_closes_when_watching_is_revoked(game, monkeypatch):
    import httpx
    monkeypatch.setattr('pokesim.app.manager.STREAM_RECHECK_SECONDS', 0)
    auth = game.library.manager.auth
    dave_id = auth.user_by_name('dave')['id']

    async def frames():
        yield b'--frame\r\n1'
        auth.revoke_grant(game.red, dave_id)
        for _ in range(5):
            yield b'--frame\r\n2'

    # The library fixture already replaced httpx.AsyncClient, so start from the real class.
    original = httpx._client.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=frames())), **kwargs))
    with game.dave.stream('GET', f'/games/{game.red}/stream') as response:
        body = b''.join(response.iter_bytes())
    assert body.count(b'--frame') == 1


def test_the_game_page_learns_there_is_a_lease(game, monkeypatch):
    import httpx
    from pokesim.web.pages import LEASE_META, SPRITE_META, SPRITE_VERSION
    page = f'<head>{SPRITE_META % SPRITE_VERSION}</head>'
    original = httpx._client.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, html=page)), **kwargs))
    assert LEASE_META in game.bob.get(f'/games/{game.red}/').text
    monkeypatch.setattr(lease_module.Leases, 'enforced', property(lambda self: False))
    assert LEASE_META not in game.bob.get(f'/games/{game.red}/').text


def test_watchers_never_learn_the_other_side_of_a_trade(game, monkeypatch):
    coordinator = game.library.manager.coordinator
    row = {'id': 't', 'peer_id': 'peer-xyz', 'peer_name': 'Secret adventure', 'failure_reason': 'Their box was full'}
    monkeypatch.setattr(coordinator, '_adventure_status', lambda aid: {
        'adventure': {}, 'active': [row], 'queued': [], 'recent_failures': [row], 'history': [row],
        'attention': {'message': 'Trade with Secret adventure failed', 'reason': 'box'}, 'auto_enabled': False})
    assert coordinator.adventure_status(game.red)['history'][0]['peer_name'] == 'Secret adventure'
    hidden = coordinator.adventure_status(game.red, watcher=True)
    assert 'Secret' not in repr(hidden) and 'peer-xyz' not in repr(hidden) and 'box' not in repr(hidden)


def test_an_old_view_link_becomes_a_share_link(library):  # noqa: F811
    from pokesim.app.registry import identifier
    row = library.manager.registry.create('Old', 'fixture', {}, identifier())
    admin = library.user('admin', 'admin')
    library.manager.bind_library_owner(admin['id'])
    client = library.login('admin')
    sharing = client.get(f"/api/v1/adventures/{row['id']}/sharing").json()
    assert sharing['legacy'] == {'path': f"/view/{row['id']}/"}
    made = client.post(f"/api/v1/adventures/{row['id']}/shares", json={'legacy': True})
    assert made.status_code == 200 and '/s/' in made.json()['url']
    assert client.get(f"/api/v1/adventures/{row['id']}/sharing").json()['legacy'] is None
    fresh = library.adventure('New', admin)
    assert client.get(f'/api/v1/adventures/{fresh}/sharing').json()['legacy'] is None


def test_without_accounts_take_control_needs_no_lease(tmp_path):
    from pokesim.app.manager import Manager
    manager = Manager(tmp_path, 'http://testserver', auth='none')
    try:
        assert not manager.leases.enforced
        with pytest.raises(lease_module.LeaseRefused):
            manager.leases.act('x', policy.Actor(None, {}), {}, 'request')
    finally:
        manager.close()


def oidc_login(library, provider, groups):  # noqa: F811
    import time
    from urllib.parse import parse_qs, urlsplit
    browser = library.browser()
    query = parse_qs(urlsplit(browser.get('/auth/oidc/login', follow_redirects=False).headers['location']).query)
    now = int(time.time())
    provider.claims = {'iss': provider.issuer, 'sub': 'u-erin', 'aud': 'pokesim', 'exp': now + 300, 'iat': now,
                       'nonce': query['nonce'][0], 'preferred_username': 'erin', 'groups': groups}
    done = browser.get(f'/auth/oidc/callback?state={query["state"][0]}&code=abc', follow_redirects=False)
    assert done.status_code == 200, done.text
    browser.headers['X-PokeSim-CSRF'] = browser.get('/api/v1/session').json()['csrf_token']
    return browser


def sent_from(manager, aid, to_id, uid):
    from pokesim.app.registry import identifier
    return manager.registry.create_trade_offer({'id': identifier(), 'from_id': aid, 'from_key': '0', 'to_id': to_id,
                                                'to_key': '1', 'sender_id': uid})


def test_a_provider_that_lowers_a_role_ends_what_the_old_role_allowed(game, people):  # noqa: F811
    from pokesim.app.providers import OIDC
    from test_accounts import Provider
    manager = game.library.manager
    provider = Provider()
    manager.oidc = OIDC(provider.issuer, 'pokesim', 'secret', 'http://testserver/auth/oidc/callback',
                        transport=httpx.MockTransport(provider.handle))
    erin = oidc_login(game.library, provider, ['pokesim-admins'])
    uid = manager.auth.identity_user('oidc', provider.issuer, 'u-erin')['id']
    lease(game.bob, game.red, 'request')
    assert lease(erin, game.red, 'request').json()['queued']
    sent = sent_from(manager, game.red, people.blue, uid)
    oidc_login(game.library, provider, ['pokesim'])
    assert manager.auth.user(uid)['role'] == 'member'
    assert manager.registry.trade_offer(sent['id'])['status'] == 'withdrawn'
    assert manager.leases.current(game.red).queue == []


def test_a_proxy_that_lowers_a_role_ends_what_the_old_role_allowed(game, people, monkeypatch):  # noqa: F811
    import time
    from pokesim.app import ownership
    manager = game.library.manager
    named = ['admin']
    monkeypatch.setattr(manager, 'proxy', SimpleNamespace(
        identify=lambda request: ('frank', named[0]) if request.headers.get('X-Test-Proxy') else None))
    checks = []
    recheck = ownership.recheck
    monkeypatch.setattr(ownership, 'recheck', lambda manager, uid, actor=None: checks.append(uid) or recheck(manager, uid, actor))
    frank = game.library.browser()
    frank.headers['X-Test-Proxy'] = '1'
    lease(game.bob, game.red, 'request')
    assert lease(frank, game.red, 'request').json()['queued']
    uid = manager.auth.identity_user('proxy', 'header', 'frank')['id']
    sent = sent_from(manager, game.red, people.blue, uid)
    # The same role on every request rechecks nothing.
    lease(frank, game.red)
    assert checks == []
    named[0] = 'member'
    frank.get('/api/v1/session')
    # The recheck runs in the background, so wait for its last step.
    deadline = time.monotonic() + 5
    while manager.leases.current(game.red).queue and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.registry.trade_offer(sent['id'])['status'] == 'withdrawn'
    assert manager.leases.current(game.red).queue == []
    frank.get('/api/v1/session')
    assert checks == [uid]


def lease_ends(manager, aid):
    return [row['target'] for row in manager.auth.audit_rows() if row['action'] == 'lease.end' and row['adventure_id'] == aid]


def test_a_role_change_after_an_adventure_went_ends_its_lease_cleanly(game):
    manager = game.library.manager
    leases, registry = manager.leases, manager.registry
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    # Gone between two sweeps, so its lease is still in memory.
    with registry.lock, registry.db:
        registry.db.execute('DELETE FROM adventures WHERE id=?', (game.red,))
    admin = game.library.login('admin')
    assert admin.patch(f'/api/v1/users/{game.ids.bob}', json={'disabled': True}).status_code == 200
    assert leases.holder(game.red) is None
    assert leases.dropped[game.red, game.ids.carol] == 'ended'
    assert lease_ends(manager, game.red) == ['deleted']


def test_deleting_an_adventure_ends_its_lease_and_tells_its_line(game, people):  # noqa: F811
    from pokesim.app.deletion import delete_adventure
    manager = game.library.manager
    leases = manager.leases
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    # Stopped, inside the sweep's window, so the lease is still there.
    manager.registry.update(game.red, state='stopped', desired_state='stopped')
    delete_adventure(manager, game.red, 'Red', manager.actor_for(manager.auth.user(people.alice['id'])))
    assert leases.holder(game.red) is None
    assert leases.dropped[game.red, game.ids.carol] == 'ended'
    assert lease_ends(manager, game.red) == ['deleted']
