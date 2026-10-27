from dataclasses import replace
import re


def expect(locator):
    from playwright.sync_api import expect as assertion
    return assertion(locator)


def until(page, check, message, timeout=15000):
    # The presses land in the test's emulator, which the page cannot see, so poll it from here.
    for _ in range(timeout // 50):
        if check():
            return
        page.wait_for_timeout(50)
    raise AssertionError(message())


def test_mobile_hold_stops_on_release_and_blur(page, game):
    url, _, emu, _ = game
    emu.press = lambda button: emu.commands.append(('press', button))
    sending = set()
    page.on('request', lambda request: '/api/control' in request.url and sending.add(request))
    page.on('requestfinished', lambda request: sending.discard(request))
    page.on('requestfailed', lambda request: sending.discard(request))
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(url + '/')
    page.locator('#manual-controls').evaluate('(element) => element.open = true')
    button = page.locator('.controller [data-b="right"]')
    expect(button).to_be_visible()

    def stopped():
        # Once the hold is released and the last press has landed, nothing may follow.
        expect(button).not_to_have_class(re.compile(r'\bis-held\b'))
        until(page, lambda: not sending, lambda: f'{len(sending)} presses still sending')
        count = len(emu.commands)
        page.wait_for_timeout(350)
        assert len(emu.commands) == count, emu.commands

    button.hover()
    page.mouse.down()
    until(page, lambda: len(emu.commands) >= 3, lambda: f'the hold repeated only {len(emu.commands)} times')
    page.mouse.up()
    stopped()
    count = len(emu.commands)
    page.mouse.down()
    until(page, lambda: len(emu.commands) > count, lambda: 'the second hold sent nothing')
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    stopped()
    assert button.evaluate("e => getComputedStyle(e).touchAction") == 'none'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_shiny_badges_filters_and_counts(page, game):
    url, _, emu, _ = game
    emu.snapshot = replace(emu.snapshot, party=(replace(emu.snapshot.party[0], dvs=(0,2,10,10,10)),))
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(url + '/')
    expect(page.locator('#party .shiny-badge')).to_have_text('★ Shiny')
    page.goto(url + '/pc?scope=all&rating=shiny')
    expect(page.locator('.pc-mon')).to_have_count(1)
    expect(page.locator('.pc-mon .shiny-badge')).to_have_text('★ Shiny')
    page.locator('.pc-mon').click()
    expect(page.locator('#pc-detail-body .shiny-badge')).to_be_visible()
    page.goto(url + '/pokedex')
    expect(page.locator('#sum-shiny')).to_have_text('1/151')
    page.locator('#status-filter').select_option('shiny')
    expect(page.locator('.dex-card')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path='/tmp/pokesim-shiny-mobile.png', full_page=True)


def test_shiny_summary_fits_small_phone(page, game):
    page.set_viewport_size({'width': 320, 'height': 844})
    page.goto(game[0] + '/pokedex')
    expect(page.locator('#sum-shiny')).to_have_text('0/151')
    assert page.locator('.shiny-collection').count() == 0
    page.screenshot(path='/tmp/pokesim-shiny-320.png', full_page=False)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.locator('main *').evaluate_all('''elements => elements.filter(e => e.getBoundingClientRect().right > innerWidth).map(e => [e.tagName, e.className, e.id, e.getBoundingClientRect().right])''')


def test_adventure_palette_and_permanent_deletion(page, tmp_path, monkeypatch):
    from conftest import serve
    from pokesim.app.manager import Manager, create_app
    from pokesim.app.registry import identifier
    captured = {}
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        manager.registry.add_rom('fixture', 'sha1', 'red')
        row = manager.registry.create('Disposable adventure', 'fixture', {}, identifier())
        path = manager.root / 'adventures' / row['id']
        (path / 'private.state').write_bytes(b'save fixture')
        captured.update(manager=manager, row=row, path=path)
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(url)
        page.locator('[data-action="settings"]').click()
        page.locator('#settings-palette').select_option('blue')
        page.get_by_role('button', name='Save adventure settings', exact=True).click()
        expect(page.locator('#adventure-settings')).not_to_be_visible()
        assert captured['manager'].registry.adventure(captured['row']['id'])['settings']['palette'] == 'blue'
        page.locator('.card-more-toggle').click()
        page.locator('[data-action="delete"]').click()
        dialog = page.locator('#adventure-delete-dialog')
        expect(dialog).to_be_visible()
        assert dialog.evaluate('(element) => element.scrollWidth <= element.clientWidth')
        page.locator('#delete-confirmation').fill('Wrong name')
        dialog.locator('button[type="submit"]').click()
        expect(dialog.locator('.dialog-feedback')).to_contain_text('Type the adventure name')
        assert captured['path'].exists()
        page.locator('#delete-confirmation').fill('Disposable adventure')
        page.screenshot(path='/tmp/pokesim-delete-mobile.png', full_page=True)
        dialog.locator('button[type="submit"]').click()
        expect(dialog).not_to_be_visible()
        expect(page.locator('.adventure-card')).to_have_count(0)
        assert not captured['path'].exists()


def test_touch_hold_and_cancel_and_single_start(page, game):
    url, _, emu, _ = game
    emu.press = lambda button: emu.commands.append(('press', button))
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(url + '/')
    page.locator('#manual-controls').evaluate('(element) => element.open = true')
    touch = page.context.new_cdp_session(page)
    for name in ('down', 'start'):
        emu.commands.clear()
        button = page.locator(f'.controller [data-b="{name}"]')
        button.scroll_into_view_if_needed()
        box = button.bounding_box()
        touch.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [
            {'x': box['x'] + box['width']/2, 'y': box['y'] + box['height']/2}]})
        page.wait_for_timeout(600)
        assert len(emu.commands) >= 3 if name == 'down' else len(emu.commands) == 1
        touch.send('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
        page.wait_for_timeout(200)
        count = len(emu.commands)
        page.wait_for_timeout(300)
        assert len(emu.commands) == count
