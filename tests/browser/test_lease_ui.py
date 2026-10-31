"""The control lease panel on a game page: people ask for control, the holder decides, and the owner takes it back."""
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
import time

from pokesim import config
from pokesim.app.manager import Manager, create_app as library_app
from pokesim.app.registry import identifier
from pokesim.store import Store
from pokesim.web import trading
from pokesim.web.app import create_app
from conftest import BrowserErrors, SyntheticEmulator, serve

PASSWORD = 'lease fixture password'
HOLDING = 'You have control. The AI plays again when you stop.'


@contextmanager
def adventure(tmp_path, monkeypatch):
    """A library with accounts in front of one real game page. Alice owns Red, and Bob and Carol may play it."""
    for name in ('AUTH', 'OIDC_ISSUER', 'AUTH_PROXY_HEADER', 'DISABLE_PASSWORD_LOGIN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    monkeypatch.setattr(config, 'TRADING_INSTANCE', 'red')
    monkeypatch.setattr(config, 'TRADING_URL', '')
    store = Store(tmp_path / 'game')
    emu = SyntheticEmulator(store)
    monkeypatch.setattr(trading, 'board', emu.board)
    holder = {}

    def factory(url):
        manager = Manager(tmp_path / 'library', url, auth='accounts')
        monkeypatch.setattr(manager, 'start', lambda: None)
        admin = manager.auth.create_user('admin', PASSWORD, role='admin')
        manager.bind_library_owner(admin['id'])
        holder['manager'] = manager
        return library_app(manager)
    try:
        with serve(factory) as url:
            manager = holder['manager']
            manager.registry.add_rom('fixture', 'sha1', 'red')
            auth = manager.auth
            alice, bob, carol = (auth.create_user(name, PASSWORD) for name in ('alice', 'bob', 'carol'))
            aid = manager.registry.create('Red', 'fixture', {}, identifier(), owner=alice['id'])['id']
            manager.registry.update(aid, state='running')
            for person in (bob, carol):
                auth.grant(aid, person['id'], 'player', alice['id'])
            game = create_app(emu, store, base_path=f'/games/{aid}', adventure_id=aid, adventure_name='Red')
            with serve(lambda _: game) as worker, ExitStack() as pages:
                # The lease tells the worker to enter manual mode. This synthetic worker needs no telling.
                monkeypatch.setattr(manager.supervisor, 'child', lambda _: SimpleNamespace(
                    url=worker, token='t', request=lambda *args, **kwargs: {'ok': True}))
                yield SimpleNamespace(url=url, aid=aid, manager=manager, pages=pages)
    finally:
        store.close()


@contextmanager
def checked(page):
    """Close one person's browser, then fail on any browser error it saw."""
    errors = BrowserErrors(page)
    try:
        yield
    finally:
        errors.closing = True
        page.context.close()
    problems = errors.check()
    assert not problems, problems


def open_game(browser, game, name, lease_route=None):
    """A separate browser for each person, logged in on the game page."""
    from playwright.sync_api import expect
    page = browser.new_context().new_page()
    game.pages.enter_context(checked(page))
    if lease_route:
        page.route('**/api/lease', lease_route)
    page.goto(f'{game.url}/login?next=/games/{game.aid}/')
    page.get_by_label('Username').fill(name)
    page.get_by_label('Password', exact=True).fill(PASSWORD)
    page.get_by_role('button', name='Log in').click()
    expect(page).to_have_url(f'{game.url}/games/{game.aid}/')
    return page


def test_ask_refuse_hand_over_and_take_back(browser, tmp_path, monkeypatch):
    from playwright.sync_api import expect
    with adventure(tmp_path, monkeypatch) as game:
        bob, carol = open_game(browser, game, 'bob'), open_game(browser, game, 'carol')
        take = bob.locator('#take-control')
        expect(take).to_have_text('Take control')
        take.click()
        expect(take).to_have_text('Let AI play')
        expect(bob.locator('#lease-holder')).to_have_text(HOLDING)
        expect(bob.locator('#lease-idle')).to_be_hidden()

        ask = carol.locator('#take-control')
        expect(ask).to_have_text('Ask for control')
        expect(carol.locator('.controller [data-b="a"]')).to_be_disabled()
        ask.click()
        expect(ask).to_have_text('Leave the line')
        expect(carol.locator('#lease-holder')).to_have_text('bob has control. You are in line.')

        row = bob.locator('#lease-queue li')
        expect(row).to_contain_text('carol asks for control')
        row.get_by_role('button', name='Refuse').click()
        expect(bob.locator('#lease-queue')).to_be_hidden()
        expect(ask).to_have_text('Ask for control')

        ask.click()
        expect(row).to_contain_text('carol asks for control')
        row.get_by_role('button', name='Hand over').click()
        expect(carol.locator('#lease-holder')).to_have_text(HOLDING)
        expect(carol.locator('.controller [data-b="a"]')).to_be_enabled()
        expect(bob.locator('#lease-holder')).to_have_text('carol has control.')
        expect(bob.locator('.controller [data-b="a"]')).to_be_disabled()

        alice = open_game(browser, game, 'alice')
        back = alice.locator('#take-control')
        expect(back).to_have_text('Take control back')
        back.click()
        expect(alice.locator('#lease-holder')).to_have_text(HOLDING)
        expect(carol.locator('#lease-holder')).to_have_text('alice has control.')
        expect(carol.locator('#take-control')).to_have_text('Ask for control')


def test_idle_hands_are_warned_then_lose_control(browser, tmp_path, monkeypatch):
    from playwright.sync_api import expect
    # The shortest idle limit is 30 s, the same as the warning lead, so the warning shows at once.
    monkeypatch.setenv('CONTROL_IDLE_SECONDS', '30')
    # Hold back the page's lease reads, so Bob presses before the page knows there is a lease.
    held = []

    def hold_reads(route):
        if route.request.method == 'GET':
            held.append(route)
        else:
            route.continue_()
    with adventure(tmp_path, monkeypatch) as game:
        bob = open_game(browser, game, 'bob', lease_route=hold_reads)
        bob.locator('#take-control').click()
        idle = bob.locator('#lease-idle')
        expect(idle).to_contain_text('No buttons pressed for a while. Control ends in')
        # Unrouting sends the held reads on.
        bob.unroute('**/api/lease', hold_reads)
        assert held
        # Move the lease clock past the limit instead of waiting, then sweep as the library does.
        game.manager.leases.clock = lambda: time.monotonic() + 31
        game.manager.leases.sweep()
        expect(bob.locator('#take-control')).to_have_text('Take control')
        expect(idle).to_be_hidden()
        expect(bob.locator('.controller [data-b="a"]')).to_be_disabled()
