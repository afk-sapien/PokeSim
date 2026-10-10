"""Stopped, failed and starting adventures open an adventure page, not a second library."""
import os
from pathlib import Path

import pytest

from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from conftest import serve

OFFLINE = '<urlopen error [Errno -5] No address associated with hostname>'
SHOTS = Path(os.environ.get('POKESIM_SHOT_DIR', '/tmp/pokesim-stopped-ui'))


def expect(locator):
    from playwright.sync_api import expect as assertion
    return assertion(locator)


def build(tmp_path, monkeypatch, states):
    ids = {}
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        manager.registry.add_rom('fixture', 'sha1', 'silver')
        for name, (state, error, desired) in states.items():
            row = manager.registry.create(name, 'fixture', {}, identifier())
            manager.registry.update(row['id'], state=state, error=error, desired_state=desired,
                                    summary={'setup': 'Preparing Pokémon Silver maps and game data'} if state == 'failed' else {})
            ids[name] = row['id']
        factory.manager = manager
        return create_app(manager)
    return factory, ids


def no_library_chrome(page):
    body = page.locator('body').inner_text()
    for phrase in ('No adventures yet', 'Create an adventure', 'Your adventure library', 'New adventure',
                   'Show archived', 'A world for every adventure'):
        assert phrase not in body, phrase
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [320, 390, 1280])
def test_failed_adventure_page_explains_and_offers_retry(page, tmp_path, monkeypatch, width):
    factory, ids = build(tmp_path, monkeypatch, {'Cozy Escape': ('failed', OFFLINE, 'running')})
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(f'{url}/games/{ids["Cozy Escape"]}/')
        status = page.locator('.adventure-status')
        expect(status.get_by_role('heading', name='Failed to start')).to_be_visible()
        expect(status.locator('.card-error')).to_have_text(
            "Couldn't download the Pokémon Silver game data (no network). Retry.")
        expect(page.get_by_role('heading', name='Cozy Escape', level=1)).to_be_visible()
        retry = status.get_by_role('button', name='Retry', exact=True)
        expect(retry).to_be_enabled()
        assert retry.bounding_box()['height'] >= 44
        expect(page.get_by_role('link', name='Back to the library')).to_be_visible()
        expect(status.get_by_text('Technical details')).to_be_visible()
        no_library_chrome(page)
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f'failed-{width}.png'), full_page=True, animations='disabled')
        started = []
        def fake_start(route):
            started.append(route.request.method)
            route.fulfill(json={'id': ids['Cozy Escape'], 'state': 'starting'})
        page.route('**/api/v1/adventures/*/start', fake_start)
        retry.click()
        page.wait_for_timeout(300)
        assert started == ['POST']


@pytest.mark.parametrize('width', [320, 1280])
def test_stopped_adventure_page_starts_in_one_click(page, tmp_path, monkeypatch, width):
    factory, ids = build(tmp_path, monkeypatch, {'Quiet Cove': ('stopped', None, 'stopped')})
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 900})
        for path in ('', 'pc', 'journal'):
            page.goto(f'{url}/games/{ids["Quiet Cove"]}/{path}')
            expect(page.locator('.adventure-status').get_by_role('heading', name='Stopped')).to_be_visible()
            expect(page.get_by_role('button', name='Start adventure')).to_be_enabled()
            no_library_chrome(page)
        expect(page.locator('[data-nav="library"]')).to_have_attribute('aria-current', 'page')
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f'stopped-{width}.png'), full_page=True, animations='disabled')
        page.get_by_role('link', name='Cable Club trading').click()
        expect(page).to_have_url(f'{url}/games/{ids["Quiet Cove"]}/trading')


def test_library_cards_show_state_and_start_without_a_detour(page, tmp_path, monkeypatch):
    factory, ids = build(tmp_path, monkeypatch, {'Cozy Escape': ('failed', OFFLINE, 'running'),
                                                 'Quiet Cove': ('stopped', None, 'stopped')})
    with serve(factory) as url:
        for width in (320, 1280):
            page.set_viewport_size({'width': width, 'height': 1000})
            page.goto(url)
            failed = page.locator(f'[data-adventure-id="{ids["Cozy Escape"]}"]')
            stopped = page.locator(f'[data-adventure-id="{ids["Quiet Cove"]}"]')
            expect(failed.locator('.state-pill')).to_have_text('Failed')
            expect(stopped.locator('.state-pill')).to_have_text('Stopped')
            expect(failed.locator('.card-error')).to_have_text(
                "Couldn't download the Pokémon Silver game data (no network). Retry.")
            expect(failed.get_by_role('button', name='Retry', exact=True)).to_be_enabled()
            expect(stopped.get_by_role('button', name='Start', exact=True)).to_be_enabled()
            expect(stopped.get_by_role('link', name='Details')).to_have_attribute('href', f'/games/{ids["Quiet Cove"]}/')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f'library-{width}.png'), full_page=True, animations='disabled')
        started = []
        page.route('**/api/v1/adventures/*/start', lambda route: (started.append(route.request.url),
                                                                   route.fulfill(json={'state': 'starting'})))
        stopped.get_by_role('button', name='Start', exact=True).click()
        page.wait_for_timeout(300)
        assert started and ids['Quiet Cove'] in started[0]
        expect(page).to_have_url(url + '/')
