"""Global nickname customization through the real settings page."""
from pathlib import Path

import pytest

from pokesim.app.manager import Manager, create_app
from conftest import serve


@pytest.mark.parametrize('width', [320, 1280])
def test_nickname_settings_save_reload_reset_and_validate(page, tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(url + '/settings')
        prefixes = page.get_by_label('Extra prefixes')
        suffixes = page.get_by_label('Extra suffixes')
        expect(prefixes).to_be_visible()
        prefixes.fill('chaos, spicy')
        suffixes.fill('goose\ngremlin')
        page.get_by_role('button', name='Save nickname settings').click()
        expect(prefixes).to_have_value('CHAOS\nSPICY')
        page.reload()
        expect(suffixes).to_have_value('GOOSE\nGREMLIN')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        folder = Path('/tmp/pokesim-nickname-ui')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'settings-{width}.png'), full_page=True)
        prefixes.fill('bad!')
        page.get_by_role('button', name='Save nickname settings').click()
        expect(page.locator('#notice')).to_contain_text('1 to 7 letters')
        page.reload()
        expect(prefixes).to_have_value('CHAOS\nSPICY')
        page.get_by_role('button', name='Restore defaults').click()
        expect(prefixes).to_have_value('')
        expect(suffixes).to_have_value('')
        page.reload()
        expect(prefixes).to_have_value('')
