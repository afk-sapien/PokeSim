"""Backup selection and copy loading through the rendered Settings page."""
from contextlib import closing
import hashlib
from pathlib import Path

import pytest

from conftest import serve
from pokesim import desktop_setup
from pokesim.app.backup import create_backup
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from pokesim.store import Store


@pytest.mark.parametrize('width', [320, 1280])
def test_load_backup_file_and_open_copy(page, tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    captured = {}
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        raw = b'browser-backup-cartridge'
        monkeypatch.setitem(desktop_setup.ROM_NAMES, hashlib.sha1(raw).hexdigest(), 'Pokémon Red')
        asset = manager.assets.install_rom(raw)
        row = manager.registry.create('Red adventure', asset['id'], {'speed': 4}, identifier())
        with closing(Store(manager.root / 'adventures' / row['id'])) as store:
            store.set('fixture', 'saved')
        captured['manager'] = manager
        captured['backup'] = create_backup(manager)
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(url + '/settings')
        page.locator('#backups').get_by_role('button', name='Load', exact=True).click()
        dialog = page.locator('#backup-dialog')
        expect(dialog).to_be_visible()
        expect(page.get_by_label('Name for restored copy')).to_have_value('Red adventure (restored)')
        page.get_by_label('Name for restored copy').fill('Recovered adventure')
        assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth')
        folder = Path('/tmp/pokesim-nickname-ui')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'backup-{width}.png'), full_page=True)
        page.get_by_role('button', name='Load adventure copy', exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(page.locator('#notice')).to_contain_text('stopped copy')
        rows = captured['manager'].registry.adventures()
        assert len(rows) == 2
        assert rows[1]['name'] == 'Recovered adventure'
        assert rows[1]['provenance']['trading_blocked']
        page.locator('#backup-file').set_input_files(captured['backup']['path'])
        expect(dialog).to_be_visible()
        expect(page.get_by_label('Name for restored copy')).to_have_value('Red adventure (restored)')
        dialog.get_by_role('button', name='Close', exact=True).click()
        assert page.locator('#backups .backup-row').count() == 2
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(folder / f'backups-settings-{width}.png'), full_page=True)


@pytest.mark.parametrize('width,theme', [(320, 'light'), (1024, 'light'), (1280, 'light'), (1280, 'dark')])
def test_delete_backups_confirmation_and_pagination(page, tmp_path, monkeypatch, width, theme):
    from playwright.sync_api import expect
    import os
    paths = []
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        directory = manager.root / 'backups'
        directory.mkdir(exist_ok=True)
        for index in range(6):
            path = directory / (identifier() + '.zip')
            path.write_bytes(b'test backup')
            os.utime(path, (1700000000 + index, 1700000000 + index))
            paths.append(path)
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.emulate_media(color_scheme=theme)
        page.goto(url + '/settings')
        expect(page.locator('#backups .backup-row')).to_have_count(5)
        expect(page.locator('#backup-summary')).to_contain_text('6 backups')
        expect(page.locator('#backup-page-label')).to_have_text('1–5 of 6')
        page.locator('#backup-next').click()
        expect(page.locator('#backups .backup-row')).to_have_count(1)
        expect(page.locator('#backup-page-label')).to_have_text('6–6 of 6')
        page.locator('[data-delete-backup]').click()
        dialog = page.locator('#backup-delete-dialog')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role('button', name='Keep backup')).to_be_focused()
        dialog.get_by_role('button', name='Keep backup').click()
        expect(dialog).not_to_be_visible()
        assert all(path.exists() for path in paths)
        page.locator('[data-delete-backup]').click()
        folder = Path('/tmp/pokesim-backup-delete-ui')
        folder.mkdir(exist_ok=True)
        assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth')
        page.screenshot(path=str(folder / f'confirm-{width}-{theme}.png'), full_page=True)
        page.route('**/api/v1/backups/*', lambda route: route.fulfill(
            status=409, content_type='application/json', body='{"detail":"Backup is busy"}')
            if route.request.method == 'DELETE' else route.continue_())
        dialog.get_by_role('button', name='Delete backup', exact=True).click()
        expect(dialog.locator('.dialog-feedback')).to_have_text('Backup is busy')
        assert all(path.exists() for path in paths)
        page.unroute('**/api/v1/backups/*')
        dialog.get_by_role('button', name='Delete backup', exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(page.locator('#backup-summary')).to_contain_text('5 backups')
        expect(page.locator('#backup-pagination')).not_to_be_visible()
        expect(page.locator('#backups .backup-row')).to_have_count(5)
        assert not paths[0].exists()
        assert all(path.exists() for path in paths[1:])
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(folder / f'list-{width}-{theme}.png'), full_page=True)
        for _ in range(5):
            page.locator('[data-delete-backup]').first.click()
            dialog.get_by_role('button', name='Delete backup', exact=True).click()
            expect(dialog).not_to_be_visible()
        expect(page.locator('#backups')).to_contain_text('No backups yet')
        assert not any(path.exists() for path in paths)
