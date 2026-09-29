"""Resource cards, save downloads, and logo navigation on real rendered pages."""
import io
from pathlib import Path

import pytest
from PIL import Image

from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from pokesim.web.pages import render_game_page
from conftest import serve


def expect(locator):
    from playwright.sync_api import expect as assertion
    return assertion(locator)


@pytest.mark.parametrize('width', [320, 390, 1280])
def test_library_usage_updates_without_replacing_cards(page, tmp_path, monkeypatch, width):
    usage = {'cpu_percent': 83.4, 'memory_bytes': 244 * 1048576}
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        monkeypatch.setattr(manager.supervisor, 'resources', lambda aid: usage)
        manager.registry.add_rom('fixture', 'sha1', 'blue')
        row = manager.registry.create('Blue', 'fixture', {}, identifier())
        manager.registry.update(row['id'], state='running', summary={
            'activity': 'Cerulean Cave', 'league_rewards': {'wins': 52},
            'recent_activity': [{'time': 1790700000, 'message': 'Cerulean Cave'},
                                {'time': 1790699940, 'message': 'Cerulean City'},
                                {'time': 1790699880, 'message': 'Route 24'}]})
        return create_app(manager)
    image = io.BytesIO()
    Image.new('RGB', (160, 144), '#99aa77').save(image, 'JPEG')
    page.route('**/frame.jpg', lambda route: route.fulfill(body=image.getvalue(), content_type='image/jpeg'))
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(url)
        expect(page.locator('[data-usage="cpu"]')).to_have_text('83.4%')
        expect(page.locator('[data-usage="memory"]')).to_have_text('244 MiB')
        expect(page.locator('.card-log li')).to_have_count(3)
        page.evaluate('window.originalCard = document.querySelector(".adventure-card")')
        page.get_by_role('button', name='Save and stop', exact=True).focus()
        usage.update(cpu_percent=47.1, memory_bytes=251 * 1048576)
        expect(page.locator('[data-usage="cpu"]')).to_have_text('47.1%', timeout=10000)
        assert page.evaluate('window.originalCard === document.querySelector(".adventure-card")')
        expect(page.get_by_role('button', name='Save and stop', exact=True)).to_be_focused()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('.card-screen').bounding_box()['width'] <= page.locator('.adventure-card').bounding_box()['width']
        folder = Path('/tmp/pokesim-library-ui')
        folder.mkdir(exist_ok=True)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(folder / f'library-{width}.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Dark', exact=True).click()
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(folder / f'library-dark-{width}.png'), full_page=True, animations='disabled')


@pytest.mark.parametrize('width', [320, 390, 1280])
def test_logo_returns_to_library_without_a_separate_button(page, game, width):
    url, _, _, _ = game
    # Use the real managed page renderer with the synthetic worker API behind it.
    html = render_game_page('index.html', base_path='/games/example', adventure_id='example', adventure_name='Blue')
    page.route('**/games/example/**', lambda route: route.continue_(
        url=route.request.url.replace('/games/example/', '/')))
    page.route('**/managed-preview', lambda route: route.fulfill(body=html, content_type='text/html'))
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/managed-preview')
    button = page.get_by_role('link', name='PokeSim library', exact=True)
    expect(page.get_by_role('link', name='Back to Library', exact=True)).to_have_count(0)
    expect(page.locator('#export-save')).to_have_count(0)
    expect(page.get_by_role('combobox', name='Switch adventure')).to_be_visible()
    expect(button).to_be_visible()
    assert button.get_attribute('href') == '/'
    box = button.bounding_box()
    assert box['height'] >= 44 and box['width'] >= 120
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    folder = Path('/tmp/pokesim-library-ui')
    folder.mkdir(exist_ok=True)
    page.screenshot(path=str(folder / f'return-{width}.png'))
    button.click()
    expect(page).to_have_url(url + '/')


@pytest.mark.parametrize('expired', [False, True])
def test_library_downloads_selected_save_and_reports_busy_game(page, tmp_path, monkeypatch, expired):
    games = {}
    requests = []
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        manager.registry.add_rom('fixture', 'sha1', 'blue')
        for name, state in [('Blue', 'running'), ('Red', 'stopped')]:
            row = manager.registry.create(name, 'fixture', {}, identifier())
            manager.registry.update(row['id'], state=state)
            games[name] = row['id']
        return create_app(manager)
    def export(route):
        requests.append(route.request)
        if expired and len(requests) == 1:
            route.fulfill(status=403, json={'code': 'csrf_expired', 'detail': 'Reload this page before making changes'})
        else:
            route.fulfill(body=bytes(32768), content_type='application/octet-stream',
                          headers={'Content-Disposition': 'attachment' + chr(59) + ' filename="Blue.sav"'})
    page.route('**/api/export-save', export)
    with serve(factory) as url:
        page.goto(url)
        blue = page.locator(f'[data-adventure-id="{games["Blue"]}"]')
        red = page.locator(f'[data-adventure-id="{games["Red"]}"]')
        expect(red.get_by_role('button', name='Download Save')).to_be_disabled()
        with page.expect_download() as downloaded:
            blue.get_by_role('button', name='Download Save').click()
        result = downloaded.value
        assert result.suggested_filename == 'Blue.sav'
        result.save_as(tmp_path / 'Blue.sav')
        assert (tmp_path / 'Blue.sav').read_bytes() == bytes(32768)
        assert len(requests) == (2 if expired else 1)
        for request in requests:
            assert request.url == f'{url}/games/{games["Blue"]}/api/export-save'
            assert request.method == 'POST'
            assert request.headers['x-pokesim-csrf']
        expect(page).to_have_url(url + '/')
        expect(page.locator('#notice')).to_contain_text('Save downloaded.')
        page.unroute('**/api/export-save')
        page.route('**/api/export-save', lambda route: route.fulfill(
            status=409, json={'detail': 'Wait for the battle to finish.'}))
        blue.get_by_role('button', name='Download Save').click()
        expect(page.locator('#notice')).to_have_text('Wait for the battle to finish.')
        expect(blue.get_by_role('button', name='Download Save')).to_be_enabled()
