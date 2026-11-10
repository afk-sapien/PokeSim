"""The inbox in a real browser: the badge counts unread items, the panel lists them, and reading clears it."""
import pytest

from pokesim.app import inbox
from pokesim.app.policy import Actor
from pokesim.app.registry import identifier
from conftest import serve
from test_accounts_ui import OLD, library


def log_in(page, url, name):
    from playwright.sync_api import expect
    page.goto(url + '/login?next=/')
    page.get_by_label('Username').fill(name)
    page.get_by_label('Password', exact=True).fill(OLD)
    page.get_by_role('button', name='Log in').click()
    expect(page).to_have_url(url + '/')


@pytest.mark.parametrize('width', [320, 390, 1280])
def test_the_inbox_badge_panel_and_mark_read(page, tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    factory, holder = library(tmp_path, monkeypatch)
    with serve(factory) as url:
        manager = holder['manager']
        manager.registry.add_rom('fixture', 'sha1', 'red')
        admin = manager.auth.user_by_name('admin')
        aid = manager.registry.create('Red', 'fixture', {}, identifier(), owner=admin['id'])['id']
        bob = manager.auth.create_user('bob', OLD)
        manager.auth.grant(aid, bob['id'], 'player', admin['id'])
        inbox.shared(manager, aid, bob['id'], 'player', Actor(admin, {}))
        manager.auth.notify(bob['id'], 'offer.received', 'An offer waits for you in Settings.', link='/settings')
        page.set_viewport_size({'width': width, 'height': 800})
        log_in(page, url, 'bob')
        toggle = page.locator('#inbox-open')
        expect(toggle).to_have_attribute('aria-label', 'Inbox, 2 unread')
        expect(page.locator('#inbox-count')).to_have_text('2')
        toggle.click()
        panel = page.locator('#inbox-panel')
        expect(panel).to_be_visible()
        expect(toggle).to_have_attribute('aria-expanded', 'true')
        expect(panel.locator('.inbox-item.is-unread')).to_have_count(2)
        expect(panel).to_contain_text('admin shared Red with you. You can play it.')
        box = panel.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.keyboard.press('Escape')
        expect(panel).to_be_hidden()
        expect(toggle).to_be_focused()
        # Following an item marks it read.
        toggle.click()
        panel.get_by_role('link', name='An offer waits for you in Settings.').click()
        expect(page).to_have_url(url + '/settings')
        expect(page.locator('#inbox-count')).to_have_text('1')
        assert manager.auth.unread_count(bob['id']) == 1
        page.locator('#inbox-open').click()
        page.get_by_role('button', name='Mark all read').click()
        expect(page.locator('#inbox-count')).to_be_hidden()
        expect(page.locator('#inbox-open')).to_have_attribute('aria-label', 'Inbox')
        expect(panel.locator('.inbox-item.is-unread')).to_have_count(0)
        assert manager.auth.unread_count(bob['id']) == 0
        # A click outside closes it.
        page.mouse.click(2, 790)
        expect(panel).to_be_hidden()


def test_the_inbox_stays_hidden_without_accounts(page, tmp_path, monkeypatch):
    from playwright.sync_api import expect
    from pokesim.app.manager import Manager, create_app
    for name in ('AUTH', 'OIDC_ISSUER', 'AUTH_PROXY_HEADER', 'DISABLE_PASSWORD_LOGIN'):
        monkeypatch.delenv(name, raising=False)

    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        return create_app(manager)
    with serve(factory) as url:
        page.goto(url + '/')
        expect(page.locator('#status')).not_to_have_text('Connecting')
        expect(page.locator('#inbox-open')).to_be_hidden()
