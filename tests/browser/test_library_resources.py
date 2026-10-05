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


@pytest.mark.parametrize('width', [320, 390, 640, 800, 1000, 1100, 1280, 1600])
def test_library_usage_updates_without_replacing_cards(page, tmp_path, monkeypatch, width):
    usage = {'cpu_percent': 83.4, 'memory_bytes': 244 * 1048576, 'observed_speed': 2.3, 'speed_status': 'ready'}
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
        expect(page.locator('[data-usage="speed"]')).to_have_text('2.3×')
        expect(page.locator('.card-log li')).to_have_count(3)
        page.evaluate('window.originalCard = document.querySelector(".adventure-card")')
        page.get_by_role('button', name='Stop', exact=True).focus()
        for label in ('Stop', 'Download', 'Archive', 'Delete', 'Settings'):
            expect(page.get_by_role('button', name=label, exact=True)).to_be_enabled()
        opening = page.get_by_role('link', name='Open adventure').bounding_box()
        settings = page.get_by_role('button', name='Settings', exact=True).bounding_box()
        assert settings['x'] >= opening['x'] + opening['width']
        assert abs(settings['y'] - opening['y']) < 1
        for button in page.locator('.card-operations button').all():
            assert button.bounding_box()['height'] >= 44
        usage.update(cpu_percent=47.1, memory_bytes=251 * 1048576, observed_speed=18.7)
        expect(page.locator('[data-usage="cpu"]')).to_have_text('47.1%', timeout=10000)
        expect(page.locator('[data-usage="speed"]')).to_have_text('18.7×')
        assert page.evaluate('window.originalCard === document.querySelector(".adventure-card")')
        expect(page.get_by_role('button', name='Stop', exact=True)).to_be_focused()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('.card-screen').bounding_box()['width'] <= page.locator('.adventure-card').bounding_box()['width']
        folder = Path('/tmp/pokesim-library-ui')
        folder.mkdir(exist_ok=True)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(folder / f'library-{width}.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Dark', exact=True).click()
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(folder / f'library-dark-{width}.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Settings', exact=True).click()
        dialog = page.get_by_role('dialog', name='Adventure settings')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label('Custom Mew event', exact=True)).to_be_disabled()
        page.screenshot(path=str(folder / f'settings-{width}.png'), animations='disabled')
        overflow = dialog.evaluate('node => [...node.querySelectorAll("*")].filter(el => el.getBoundingClientRect().right > node.getBoundingClientRect().right).map(el => ({tag: el.tagName, id: el.id, cls: el.className, text: el.textContent.slice(0, 40)}))')
        assert dialog.evaluate('(node) => node.scrollWidth <= node.clientWidth'), overflow


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
        expect(red.get_by_role('button', name='Download')).to_be_disabled()
        with page.expect_download() as downloaded:
            blue.get_by_role('button', name='Download').click()
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
        blue.get_by_role('button', name='Download').click()
        expect(page.locator('#notice')).to_have_text('Wait for the battle to finish.')
        expect(blue.get_by_role('button', name='Download')).to_be_enabled()


@pytest.mark.parametrize('width', [320, 1280])
def test_adventure_speed_changes_independently_and_global_controls_are_removed(page, tmp_path, monkeypatch, width):
    games = []
    managers = []
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        managers.append(manager)
        monkeypatch.setattr(manager, 'start', lambda: None)
        manager.registry.add_rom('fixture', 'sha1', 'blue')
        for name, speed in [('Blue', 0.75 if width == 320 else 4), ('Red', 16)]:
            game = manager.registry.create(name, 'fixture', {'speed': speed}, identifier())
            games.append(game)
            manager.registry.update(game['id'], state='running')
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(url)
        cards = page.locator('.adventure-card')
        expect(cards).to_have_count(2)
        cards.first.get_by_role('button', name='Settings', exact=True).click()
        dialog = page.get_by_role('dialog', name='Adventure settings')
        speed = dialog.get_by_role('combobox', name='Simulation speed', exact=True)
        expect(speed).to_be_enabled()
        expect(speed).to_have_value('0.75' if width == 320 else '4')
        speed.select_option('0')
        assert dialog.evaluate('node => node.scrollWidth <= node.clientWidth')
        page.screenshot(path=f'/tmp/pokesim-per-speed-{width}.png', full_page=True)
        dialog.get_by_role('button', name='Save adventure settings').click()
        expect(dialog).not_to_be_visible()
        assert managers[0].registry.adventure(games[0]['id'])['settings']['speed'] == 0
        assert managers[0].registry.adventure(games[1]['id'])['settings']['speed'] == 16
        page.reload()
        cards.first.get_by_role('button', name='Settings', exact=True).click()
        expect(speed).to_have_value('0')
        page.keyboard.press('Escape')
        page.goto(url + '/settings')
        expect(page.locator('#create-backup')).to_be_visible()
        assert page.locator('#simulation-speed, #max-running, #settings-form').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/pokesim-global-settings-{width}.png', full_page=True)


@pytest.mark.parametrize('action', ['archive', 'delete'])
def test_running_adventure_removal_saves_and_stops_first(page, tmp_path, monkeypatch, action):
    captured = {}
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        manager.registry.add_rom('fixture', 'sha1', 'red')
        row = manager.registry.create('Disposable', 'fixture', {}, identifier())
        manager.registry.update(row['id'], state='running', desired_state='running')
        path = manager.root / 'adventures' / row['id']
        saved = []
        original = manager.supervisor.stop
        def stop(aid, **kwargs):
            assert path.exists()
            assert not manager.registry.adventure(aid)['archived']
            (path / 'save.state').write_bytes(b'latest progress')
            saved.append(aid)
            return original(aid, **kwargs)
        monkeypatch.setattr(manager.supervisor, 'stop', stop)
        captured.update(manager=manager, row=row, path=path, saved=saved)
        return create_app(manager)
    with serve(factory) as url:
        page.goto(url)
        page.get_by_role('button', name=action.title(), exact=True).click()
        if action == 'delete':
            page.locator('#delete-confirmation').fill('Disposable')
            page.get_by_role('button', name='Delete adventure', exact=True).click()
        expect(page.locator('.adventure-card')).to_have_count(0)
        assert captured['saved'] == [captured['row']['id']]
        if action == 'archive':
            assert (captured['path'] / 'save.state').read_bytes() == b'latest progress'
            row = captured['manager'].registry.adventure(captured['row']['id'])
            assert row['archived'] and row['state'] == 'stopped'
        else:
            assert not captured['path'].exists()
