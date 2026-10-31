"""Account settings in a real browser: change your password, and share an adventure with a role."""
import pytest

from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from conftest import refused, serve

OLD = 'first fixture password'
NEW = 'second fixture password'


def library(tmp_path, monkeypatch):
    for name in ('AUTH', 'OIDC_ISSUER', 'AUTH_PROXY_HEADER', 'DISABLE_PASSWORD_LOGIN'):
        monkeypatch.delenv(name, raising=False)
    holder = {}

    def factory(url):
        manager = Manager(tmp_path / 'library', url, auth='accounts')
        monkeypatch.setattr(manager, 'start', lambda: None)
        admin = manager.auth.create_user('admin', OLD, role='admin')
        manager.bind_library_owner(admin['id'])
        holder['manager'] = manager
        return create_app(manager)
    return factory, holder


def log_in(page, url, name, password):
    from playwright.sync_api import expect
    page.goto(url + '/login?next=/settings')
    page.get_by_label('Username').fill(name)
    page.get_by_label('Password', exact=True).fill(password)
    page.get_by_role('button', name='Log in').click()
    expect(page).to_have_url(url + '/settings')


# The library refuses the wrong current password the test types.
@pytest.mark.expected_errors(*refused('/api/v1/auth/password', 401))
@pytest.mark.parametrize('width', [390, 1280])
def test_change_password_from_settings(page, tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    factory, _ = library(tmp_path, monkeypatch)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 900})
        log_in(page, url, 'admin', OLD)
        result = page.locator('#password-result')
        page.get_by_label('Current password').fill('not the password')
        page.get_by_label('New password', exact=True).fill(NEW)
        page.get_by_label('New password again').fill(NEW)
        page.get_by_role('button', name='Change password').click()
        expect(result).to_have_text('Your current password is wrong')
        page.get_by_label('New password again').fill(NEW + ' typo')
        page.get_by_label('Current password').fill(OLD)
        page.get_by_role('button', name='Change password').click()
        expect(result).to_have_text('The two new passwords do not match.')
        page.get_by_label('New password again').fill(NEW)
        page.get_by_role('button', name='Change password').click()
        expect(result).to_contain_text('Password changed')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.context.clear_cookies()
        log_in(page, url, 'admin', NEW)


def test_share_an_adventure_with_a_role(page, tmp_path, monkeypatch):
    from playwright.sync_api import expect
    factory, holder = library(tmp_path, monkeypatch)
    with serve(factory) as url:
        manager = holder['manager']
        manager.registry.add_rom('fixture', 'sha1', 'red')
        admin = manager.auth.user_by_name('admin')
        manager.registry.create('Red', 'fixture', {}, identifier(), owner=admin['id'])
        bob = manager.auth.create_user('bob', OLD)
        log_in(page, url, 'admin', OLD)
        page.locator('#share-adventure').select_option(label='Red')
        page.locator('#share-person').select_option(label='bob (bob)')
        page.locator('#share-role').select_option('player')
        page.get_by_role('button', name='Share', exact=True).click()
        expect(page.locator('#share-watchers')).to_contain_text('bob can play.')
        page.get_by_label('What bob can do').select_option('manager')
        expect(page.locator('#share-watchers')).to_contain_text('bob can manage.')
        aid = manager.registry.adventures()[0]['id']
        assert manager.auth.grants_for(bob['id']) == {aid: 'manager'}
