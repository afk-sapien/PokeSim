"""The optional artwork control works on phones and desktops without automatic downloads."""
import io
import threading

from PIL import Image
import pytest

from conftest import serve
from pokesim.app.manager import Manager, create_app
from pokesim.app import portrait_packs


@pytest.mark.parametrize('width,theme', [(320, 'light'), (1280, 'light'), (1280, 'dark')])
def test_optional_pack_download_progress_preview_and_restore(page, tmp_path, monkeypatch, width, theme):
    from playwright.sync_api import expect
    calls = []
    gate = threading.Event()
    started = threading.Event()
    image = io.BytesIO()
    Image.new('RGBA', (96, 96), (80, 140, 60, 255)).save(image, 'PNG')
    def download(client, url, limit):
        calls.append(url)
        if url.endswith('/LICENCE.txt'):
            return b'Synthetic notice'
        started.set()
        assert gate.wait(15)
        return image.getvalue()
    monkeypatch.setattr(portrait_packs, 'download', download)
    captured = {}
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        captured['manager'] = manager
        return create_app(manager)
    with serve(factory) as url:
        try:
            page.set_viewport_size({'width': width, 'height': 1000})
            page.goto(url + '/settings')
            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            install = page.get_by_role('button', name='Install community sprite pack', exact=True)
            expect(install).to_be_enabled()
            expect(page.locator('#portrait-preview')).not_to_be_visible()
            assert calls == []
            install.click()
            assert started.wait(5)
            expect(page.locator('#portrait-progress')).to_be_visible()
            expect(page.locator('#portrait-install')).to_be_disabled()
            expect(page.locator('#portrait-state')).to_contain_text('Downloading')
            gate.set()
            expect(page.locator('#portrait-state')).to_have_text('Community sprites active', timeout=15000)
            expect(page.locator('#portrait-progress')).not_to_be_visible()
            expect(page.locator('#portrait-preview img')).to_have_count(3)
            page.wait_for_function("() => Array.from(document.querySelectorAll('#portrait-preview img')).every(image => image.complete && image.naturalWidth === 96)")
            assert len(calls) == 152
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=f'/tmp/pokesim-community-settings-{width}-{theme}.png', full_page=True)
            page.get_by_role('button', name='Restore default sprites').click()
            expect(page.locator('#portrait-state')).to_have_text('Default sprites active')
            page.get_by_role('button', name='Use community sprites', exact=True).click()
            expect(page.locator('#portrait-state')).to_have_text('Community sprites active')
            assert len(calls) == 152
            page.reload()
            expect(page.locator('#portrait-state')).to_have_text('Community sprites active')
            assert captured['manager'].assets.portraits.status()['active'] == 'community'
        finally:
            gate.set()


def test_failed_download_is_explained_and_can_be_retried(page, tmp_path, monkeypatch):
    from playwright.sync_api import expect
    def unavailable(*args):
        raise OSError('Synthetic upstream outage')
    monkeypatch.setattr(portrait_packs, 'download', unavailable)
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        return create_app(manager)
    with serve(factory) as url:
        page.goto(url + '/settings')
        page.get_by_role('button', name='Install community sprite pack', exact=True).click()
        expect(page.locator('#portrait-feedback')).to_contain_text('Your current artwork is unchanged', timeout=10000)
        expect(page.locator('#portrait-install')).to_be_enabled()
        expect(page.locator('#portrait-state')).to_have_text('Default sprites active')
        expect(page.locator('#portrait-preview')).not_to_be_visible()
