"""Global nickname customization through the real settings page."""
from pathlib import Path

import pytest

from pokesim.app.manager import Manager, create_app
from conftest import serve


@pytest.mark.parametrize('width', [320, 780, 1280])
def test_nickname_settings_save_reload_reset_and_validate(page, tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(url + '/settings')
        edit = page.get_by_role('button', name='Edit nickname pool')
        edit.click()
        prefixes = page.get_by_label('Extra prefixes', exact=True)
        suffixes = page.get_by_label('Extra suffixes', exact=True)
        full_names = page.get_by_label('Extra full names', exact=True)
        folder = Path('/tmp/pokesim-nickname-ui')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'editor-top-{width}.png'), full_page=True)
        prefixes.fill('chaos, spicy')
        suffixes.fill('goose\ngremlin')
        full_names.fill('velcro, sirbeans')
        page.locator('#nickname-dialog summary').filter(has_text='Built-in prefixes').click()
        page.get_by_label('MEAT', exact=True).uncheck()
        page.locator('#nickname-dialog summary').filter(has_text='Built-in full names').click()
        page.get_by_label('TAXFRAUD', exact=True).uncheck()
        folder = Path('/tmp/pokesim-nickname-ui')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'editor-{width}.png'), full_page=True)
        assert page.locator('#nickname-form .sheet-foot button').evaluate_all('''buttons => buttons.every(button => {
            const bounds = button.getBoundingClientRect()
            const dialog = button.closest('dialog').getBoundingClientRect()
            return bounds.left >= dialog.left && bounds.right <= dialog.right
        })''')
        page.get_by_role('button', name='Save nickname settings').click()
        expect(page.locator('#nickname-dialog')).not_to_be_visible()
        page.reload()
        edit.click()
        expect(prefixes).to_have_value('CHAOS\nSPICY')
        expect(suffixes).to_have_value('GOOSE\nGREMLIN')
        expect(full_names).to_have_value('VELCRO\nSIRBEANS')
        page.locator('#nickname-dialog summary').filter(has_text='Built-in prefixes').click()
        expect(page.get_by_label('MEAT', exact=True)).not_to_be_checked()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#nickname-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
        prefixes.fill('bad!')
        page.get_by_role('button', name='Save nickname settings').click()
        expect(page.locator('#nickname-dialog .dialog-feedback')).to_contain_text('1 to 7 letters')
        page.get_by_role('button', name='Reset editor to defaults').click()
        expect(prefixes).to_have_value('')
        expect(full_names).to_have_value('')
        expect(page.get_by_label('MEAT', exact=True)).to_be_checked()
        page.get_by_role('button', name='Save nickname settings').click()
        page.reload()
        page.screenshot(path=str(folder / f'settings-{width}.png'), full_page=True)
        edit.click()
        expect(prefixes).to_have_value('')
        expect(full_names).to_have_value('')
