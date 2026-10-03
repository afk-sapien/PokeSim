"""Create and edit several independently subscribed notification integrations."""
from pathlib import Path
import re

import pytest

from pokesim.app.manager import Manager, create_app
from pokesim.app import notifications
from pokesim.app.registry import identifier
from conftest import serve


@pytest.mark.parametrize('width', [320, 390, 1079, 1280])
def test_named_integrations_and_filters(page, tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    sent = []
    managers = []
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        monkeypatch.setattr(notifications, 'publish', lambda *args, **kwargs: sent.append(kwargs))
        manager.registry.add_rom('fixture', 'sha1', 'red')
        for name in ('Red', 'Blue'):
            manager.registry.create(name, 'fixture', {}, identifier())
        managers.append(manager)
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(url + '/notifications')
        expect(page.get_by_text('No integrations yet', exact=True)).to_be_visible()
        dialog = page.get_by_role('dialog', name='Add integration')
        for name, provider in [('My phone', 'telegram'), ('Group chat', 'telegram'), ('League channel', 'discord'), ('Travel alerts', 'ntfy')]:
            page.get_by_role('button', name='+ Add integration', exact=True).click()
            expect(dialog).to_be_visible()
            page.locator('#notify-name').fill(name)
            page.locator('#notify-provider').select_option(provider)
            if provider == 'telegram':
                page.locator('#notify-telegram-token').fill('123:' + 'y' * 35)
                page.locator('#notify-telegram-chat').fill('123' if name == 'My phone' else '-456')
            elif provider == 'discord':
                page.locator('#notify-discord-webhook').fill('https://discordapp.com/api/webhooks/123/' + 'x' * 40)
            else:
                page.locator('#notify-token').fill('test_original_token')
                page.locator('#notify-generate').click()
                expect(page.locator('#notify-topic')).to_have_value(re.compile('pokesim-.+'))
            if name == 'My phone':
                dialog.get_by_label('Blue', exact=True).uncheck()
                page.locator('#notify-include-new').uncheck()
                page.locator('[data-notify="categories"][data-key="league"]').uncheck()
            page.get_by_role('button', name='Save integration', exact=True).click()
            expect(dialog).to_be_hidden()
            expect(page.locator('#notice')).to_have_text('Integration saved.')
        page.get_by_label('Send notifications', exact=True).check()
        expect(page.locator('#notify-delivery-state')).to_contain_text('Delivery is on')
        page.reload()
        cards = page.locator('.integration-card')
        expect(cards).to_have_count(4)
        ntfy = cards.filter(has=page.get_by_role('heading', name='Travel alerts', exact=True))
        ntfy.get_by_role('button', name='Edit', exact=True).click()
        page.get_by_role('button', name='Use no access token', exact=True).click()
        page.locator('#notify-token').fill('test_replacement_token')
        page.get_by_role('button', name='Save integration', exact=True).click()
        expect(page.get_by_role('dialog')).to_be_hidden()
        assert managers[0].notifications.settings()['integrations'][3]['token'] == 'test_replacement_token'
        first = cards.filter(has=page.get_by_role('heading', name='My phone', exact=True))
        second = cards.filter(has=page.get_by_role('heading', name='Group chat', exact=True))
        first.get_by_role('button', name='Test', exact=True).click()
        expect(first.locator('.form-result')).to_contain_text('Test accepted')
        assert sent[-1]['chat_id'] == '123'
        second.get_by_role('button', name='Test', exact=True).click()
        expect(second.locator('.form-result')).to_contain_text('Test accepted')
        assert sent[-1]['chat_id'] == '-456'
        first.get_by_role('button', name='Edit', exact=True).click()
        dialog = page.get_by_role('dialog', name='Edit integration')
        expect(dialog).to_be_visible()
        expect(page.locator('#notify-telegram-token')).to_be_hidden()
        expect(page.get_by_role('button', name='Replace token', exact=True)).to_be_visible()
        expect(page.locator('#notify-provider')).to_be_disabled()
        expect(dialog.get_by_label('Red', exact=True)).to_be_checked()
        expect(dialog.get_by_label('Blue', exact=True)).not_to_be_checked()
        expect(page.locator('[data-notify="categories"][data-key="league"]')).not_to_be_checked()
        expect(page.locator('#notify-include-new')).not_to_be_checked()
        page.get_by_role('button', name='Replace token', exact=True).click()
        expect(page.locator('#notify-telegram-token')).to_be_visible()
        page.locator('#notify-telegram-token').fill('123:' + 'z' * 35)
        page.get_by_role('button', name='Save integration', exact=True).click()
        expect(dialog).to_be_hidden()
        assert managers[0].notifications.settings()['integrations'][0]['telegram_token'] == '123:' + 'z' * 35
        second.get_by_role('button', name='Disable', exact=True).click()
        expect(second.get_by_role('button', name='Enable', exact=True)).to_be_visible()
        expect(first.get_by_role('button', name='Disable', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        folder = Path('/tmp/pokesim-integrations-ui')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'list-{width}.png'), full_page=True)
        first.get_by_role('button', name='Edit', exact=True).click()
        expect(dialog).to_be_visible()
        assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
        page.screenshot(path=str(folder / f'editor-{width}.png'))
        page.get_by_role('button', name='Delete…', exact=True).click()
        page.get_by_role('button', name='Keep integration', exact=True).click()
        expect(page.locator('#notify-delete-confirm')).to_be_hidden()
        page.get_by_role('button', name='Delete…', exact=True).click()
        page.get_by_role('button', name='Delete integration', exact=True).click()
        expect(dialog).to_be_hidden()
        expect(cards).to_have_count(3)
        page.reload()
        expect(cards).to_have_count(3)
        expect(cards.filter(has=page.get_by_role('heading', name='My phone', exact=True))).to_have_count(0)
