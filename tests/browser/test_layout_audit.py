"""Machine layout checks: every page at every window size, measured instead of eyeballed.

layout_audit.js walks the visible DOM and reports sideways page scroll, boxes that spill or are
clipped, text that does not fit, overlapping siblings, uneven cards in one row and small tap targets.

Set LAYOUT_AUDIT_REPORT to a folder to collect the whole backlog instead of failing on the first
page. Each test then writes its violations and screenshots there, and report.json plus summary.md
are rebuilt at the end of the module.
"""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import re
import time

from PIL import Image
import pytest

from conftest import SyntheticEmulator, serve
from pokesim import config
from pokesim.activity_ledger import KEY as LEDGER, increment
from pokesim.app.manager import Manager, create_app as create_library
from pokesim.app.registry import identifier
from pokesim.events import Event
from pokesim.ram import PartyMon, StoredMon
from pokesim.statistics import StatisticsTracker
from pokesim.store import Store
from pokesim.web import trading
from pokesim.web.app import create_app
from test_flows import expect
from test_trading_tabs import FROM, Library

HERE = Path(__file__).parent
AUDIT = (HERE / 'layout_audit.js').read_text()
REPORT = os.environ.get('LAYOUT_AUDIT_REPORT')
WIDTHS = [(320, 800), (360, 800), (390, 844), (768, 1024), (1024, 768), (1100, 900), (1280, 900),
          (1440, 900), (1920, 1080), (844, 390)]
# Tap targets are judged on phones, where a finger is the pointer.
TAP_WIDTH = 390

# Each entry is a deliberate design choice, never a way to hide a broken layout.
ALLOW = [
    # The adventure tabs are one row that scrolls inside its own strip on small screens.
    {'types': ['scroller'], 'selector': '.rail nav[aria-label="Main navigation"]',
     'reason': 'Main tabs scroll sideways inside their strip on phones, with the current tab kept in view'},
    # Tables with many number columns scroll inside a labelled, focusable region.
    {'types': ['scroller'], 'selector': '.ledger-scroll',
     'reason': 'The stats ledger has up to nine number columns and scrolls inside its own region'},
    # The Pokédex move table has six columns and scrolls inside a labelled, focusable region on phones.
    {'types': ['scroller'], 'selector': '.move-scroll',
     'reason': 'The six-column move table scrolls inside its own labelled region on phones'},
    # The lamp glow and other absolutely placed marks are skipped by the audit already. The skip link
    # sits off screen until it gets focus.
    {'types': ['spill', 'clipped', 'tap'], 'selector': '.skip-link',
     'reason': 'Skip link waits off screen until keyboard focus moves onto it'},
]

ADVENTURES = [
    ('Weekend Crystal Marathon', 'crystal', 'running'), ('Second Red Living Dex', 'red', 'running'),
    ('Shiny Hunt Blue Forever', 'blue', 'stopped'), ('Pikachu Friendship Yellow', 'yellow', 'running'),
    ('Johto Gold Champion Run', 'gold', 'failed'), ('Silver Rival Rematches', 'silver', 'stopped'),
]
NICKS = ['THUNDERPAW', 'SHELLSHOCK', 'MOONLIGHTS', 'BLAZEWINGS', 'GRASSKNOTS', 'STONEGUARD']
# Internal species numbers: Venusaur, Charizard, Blastoise, Pikachu, Gyarados, Snorlax and more.
SPECIES = [154, 180, 28, 84, 22, 132, 131, 21, 14, 149, 126, 20]


def rich_snapshot(snapshot):
    party = tuple(PartyMon(SPECIES[i], 287 - i * 30, 300, 100 - i * 7, NICKS[i], types=(20, 21), moves=(15, 33, 89, 57),
                           pp=(30, 35, 10, 15), max_pp=(30, 35, 10, 15), attack=250, defense=220, speed=280, special=260,
                           experience=1_000_000, dvs=(15, 14, 13, 12, 15), stat_exp=(65535,) * 5, trainer_id=100)
                  for i in range(6))
    boxed = tuple(StoredMon(box, position, SPECIES[(box + position) % len(SPECIES)], 5 + (position * 4) % 95,
                            NICKS[(box + position) % 6] if position % 3 else f'PARTNER{position:03}',
                            (33, 45, 89, 57), 125_000, (position % 16,) * 5, (0,) * 5, 100)
                  for box, count in enumerate([20, 20, 17, 9, 3, 0, 0, 0, 0, 0, 0, 1]) for position in range(count))
    counts = tuple(sum(1 for mon in boxed if mon.box == box) for box in range(12))
    return replace(snapshot, party=party, stored_details=boxed, money=999_999, badges=255, player_name='ASHKETCH',
                   rival_name='GARYOAK', playtime=(255, 59, 59), owned=frozenset(range(1, 140)),
                   seen=frozenset(range(1, 152)), stored_pokemon=tuple((p.box, p.species, p.level, p.nick) for p in boxed),
                   box_counts=counts)


def sprites(store):
    folder = store.dir / 'sprites'
    folder.mkdir(parents=True, exist_ok=True)
    for dex in range(1, 152):
        pack = Image.new('RGBA', (56, 56))
        pack.paste(Image.new('RGBA', (40, 48), (40, 120, 60, 255)), (8, 4))
        pack.save(folder / f'{dex}.png')


def journal(store, snapshot):
    image = io.BytesIO()
    Image.new('RGB', (160, 144), '#96ad84').save(image, 'PNG')
    rows = [('catch', 'Caught a wild THUNDERPAW on Route 24 north of Cerulean City'), ('badge', 'Earned the Volcano Badge'),
            ('evolve', 'SHELLSHOCK evolved into Blastoise'), ('map', 'Entered Cerulean Cave basement floor two'),
            ('trainer', 'Beat Cooltrainer Samantha with a full team of six'), ('champion', 'Entered the Hall of Fame again'),
            ('level', 'MOONLIGHTS grew to level 100'), ('trade', 'Traded PARTNER019 to Second Red Living Dex'),
            ('item', 'Found a Rare Candy hidden in the Power Plant'), ('blackout', 'Blacked out against the Elite Four')]
    ids = [store.add_event(Event(kind, title, f'{title}. The adventure continued with 9,297 hours on the clock.',
                                 priority=5 if i % 3 == 0 else 3), snapshot, image.getvalue() if i % 2 else None, b'checkpoint')
           for i, (kind, title) in enumerate(rows * 3)]
    return ids[0]


def ledger(store):
    store.set(LEDGER, {'started_at': 1700000000, 'available': True})
    with store.db:
        for dex in range(1, 152):
            for key, value in [('wild', 123_456 + dex), ('trainer', 9_876), ('defeated', 133_000), ('caught', 4_321),
                               ('traded_in', 12), ('traded_out', 7)]:
                increment(store.db, key, dex, value)
        for item in range(1, 60):
            increment(store.db, 'bought', item, 999_999)
            increment(store.db, 'used', item, 345_678)


@pytest.fixture
def adventure(tmp_path, monkeypatch):
    """One live adventure with a full party, full boxes, a long journal and big numbers."""
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    monkeypatch.setattr(config, 'TRADING_INSTANCE', 'red')
    monkeypatch.setattr(config, 'TRADING_URL', '')
    store = Store(tmp_path / 'game')
    emu = SyntheticEmulator(store)
    emu.connected = True
    emu.snapshot = rich_snapshot(emu.snapshot)
    plain = emu.status

    def status():
        state = plain()
        game = state['game']
        state['play_clock'] = {'display': '9297:37:12', 'seconds': 9297 * 3600 + 37 * 60 + 12}
        state['game'] = {**game, 'map_name': 'Cerulean Cave Basement Floor Two'}
        state['strategy'] = {**state['strategy'], 'action': 'shortcut_choose_move', 'visited_tiles': 1_234_567,
                             'objective': {'key': 'dex', 'label': 'Catch every missing Pokémon in Kanto',
                                           'reason': 'Twelve Pokédex entries are still missing'}}
        return state
    emu.status = status
    monkeypatch.setattr(trading, 'board', emu.board)
    sprites(store)
    eid = journal(store, emu.snapshot)
    ledger(store)
    tracker = StatisticsTracker(store)
    now = time.time()
    tracker.observe(emu.snapshot, now=now - 7200)
    tracker.observe(replace(emu.snapshot, frame=930, x=6), now=now - 7199)
    tracker.value['counters']['steps'] = 10_000_000_000
    tracker.flush(now=now)
    try:
        with serve(lambda url: create_app(emu, store, base_path=f'/games/{FROM}', adventure_id=FROM,
                                          adventure_name='Weekend Crystal Marathon', browser_origin=url)) as url:
            yield url, eid
    finally:
        store.close()


@pytest.fixture
def library(tmp_path, monkeypatch):
    """The Library with six adventures in every state, with long names and big numbers."""
    usage = {'cpu_percent': 183.4, 'memory_bytes': 1244 * 1048576, 'observed_speed': 16.3, 'speed_status': 'ready'}

    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        monkeypatch.setattr(manager.supervisor, 'resources', lambda aid: usage)
        for name, version, state in ADVENTURES:
            manager.registry.add_rom(version, 'sha1' + version, version)
            row = manager.registry.create(name, version, {}, identifier())
            manager.registry.update(row['id'], state=state, error='The cartridge file changed since it was added' if state == 'failed' else None,
                                    summary={'activity': 'Cerulean Cave Basement Floor Two', 'league_rewards': {'wins': 9_297},
                                             'recent_activity': [{'time': 1790700000 - i * 60, 'message': message} for i, message in
                                                                 enumerate(['Caught a wild THUNDERPAW on Route 24',
                                                                            'Entered the Hall of Fame again',
                                                                            'Beat Cooltrainer Samantha'])]})
        return create_library(manager)
    image = io.BytesIO()
    Image.new('RGB', (160, 144), '#99aa77').save(image, 'JPEG')
    with serve(factory) as url:
        yield url, image.getvalue()


def managed(page, url):
    """The library's routes in front of the game worker, the way a real adventure page is served."""
    shelf = Library(page, url)
    page.route(f'**/games/{FROM}/**', lambda route: route.continue_(url=route.request.url.replace(f'/games/{FROM}/', '/')))
    page.route(re.compile(rf'/games/{FROM}/api/interactions(\?|$)'), shelf.interactions)
    page.route(re.compile(r'/api/v1/adventures(\?|$)'), lambda route: Library.json(route, {'adventures': [
        {'id': FROM if i == 0 else identifier(), 'name': name, 'version': version, 'archived': False}
        for i, (name, version, _) in enumerate(ADVENTURES)]}))
    return shelf


def settle(page):
    # Live pages poll and stream, so the network never goes quiet. Wait for fonts and pictures instead.
    page.evaluate('() => document.fonts.ready')
    page.wait_for_function('[...document.images].every(image => image.complete || image.loading === "lazy")')
    page.wait_for_timeout(300)
    page.evaluate('''() => document.getAnimations().forEach(animation => {
      try { animation.finish() } catch (_) { animation.cancel() } })''')


def audit(page, name, width, root=None):
    settle(page)
    found = page.evaluate(AUDIT, {'allow': [{'types': entry['types'], 'selector': entry['selector']} for entry in ALLOW],
                                  'tapMin': 40, 'checkTaps': width <= TAP_WIDTH, 'root': root})
    for row in found:
        row.update(page=name, width=width)
    if REPORT:
        folder = Path(REPORT)
        (folder / 'shots').mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        page.screenshot(path=str(folder / 'shots' / f'{slug}-{width}.png'), full_page=root is None)
        with open(folder / 'violations.jsonl', 'a') as log:
            for row in found:
                log.write(json.dumps(row) + '\n')
            log.write(json.dumps({'type': 'checked', 'page': name, 'width': width}) + '\n')
    return found


def table(found):
    lines = [f'{len(found)} layout violations:', f'{"type":<11} {"width":>5}  {"page":<22} selector / detail']
    for row in found:
        lines.append(f'{row["type"]:<11} {row["width"]:>5}  {row["page"]:<22} {row["selector"]}')
        lines.append(f'{"":<41} {row["detail"]}')
    return '\n'.join(lines)


def check(found):
    if REPORT:
        return
    assert not found, table(found)


@pytest.fixture(scope='module', autouse=True)
def summary():
    if REPORT:
        log = Path(REPORT) / 'violations.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('')
    yield
    if REPORT:
        write_summary(Path(REPORT))


def write_summary(folder):
    rows = [json.loads(line) for line in (folder / 'violations.jsonl').read_text().splitlines() if line]
    checked = [row for row in rows if row['type'] == 'checked']
    found = [row for row in rows if row['type'] != 'checked']
    (folder / 'report.json').write_text(json.dumps({'checked': checked, 'violations': found}, indent=1))
    by_type, by_page = {}, {}
    for row in found:
        by_type[row['type']] = by_type.get(row['type'], 0) + 1
        by_page.setdefault(row['page'], {}).setdefault(row['type'], 0)
        by_page[row['page']][row['type']] += 1
    types = sorted(by_type)
    lines = ['# Layout audit', '', f'{len(checked)} page states checked, {len(found)} violations.', '',
             '| Type | Count |', '| --- | ---: |', *[f'| {kind} | {by_type[kind]} |' for kind in types], '',
             '| Page | ' + ' | '.join(types) + ' |', '| --- |' + ' ---: |' * len(types),
             *[f'| {name} | ' + ' | '.join(str(counts.get(kind, 0)) for kind in types) + ' |' for name, counts in sorted(by_page.items())],
             '', '## Every violation', '', '| Type | Width | Page | Selector | Detail |', '| --- | ---: | --- | --- | --- |']
    if not found:
        lines = lines[:3]
    for row in sorted(found, key=lambda r: (r['page'], r['type'], r['selector'], r['width'])):
        lines.append(f'| {row["type"]} | {row["width"]} | {row["page"]} | `{row["selector"]}` | {row["detail"]} |')
    (folder / 'summary.md').write_text('\n'.join(lines) + '\n')


def visit(page, width, height, url, ready):
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url)
    expect(page.locator(ready).first).to_be_visible()


def test_audit_catches_known_overlap_overflow_and_clipped_text(page):
    page.set_viewport_size({'width': 390, 'height': 600})
    page.goto((HERE / 'layout_audit_fixture.html').as_uri())
    found = page.evaluate(AUDIT, {'allow': [], 'checkTaps': False})
    kinds = {(row['type'], row['selector']) for row in found}
    assert ('overlap', '#overlap-a') in kinds, found
    assert ('spill', '#overflow-child') in kinds, found
    assert ('text', '#clipped-text') in kinds, found
    # Deliberate truncation, a scroller, an absolutely placed badge and a sticky footer are not violations.
    assert not [row for row in found if 'fine-' in row['selector'] and row['type'] != 'scroller'], found
    assert [row['type'] for row in found if row['selector'] == '#fine-scroller'] == ['scroller']
    allowed = page.evaluate(AUDIT, {'allow': [{'types': ['scroller'], 'selector': '.fine-scroller'}], 'checkTaps': False})
    assert not [row for row in allowed if row['selector'] == '#fine-scroller']
    page.set_content('<a href="#" style="display:inline-block;width:20px;height:20px">x</a>')
    assert [row['type'] for row in page.evaluate(AUDIT, {'checkTaps': True})] == ['tap']


GAME_PAGES = [
    ('live', '/', '#take-control'),
    ('journal', '/journal', '#events'),
    ('stats overview', '/stats', '#statistics-charts .progress-row'),
    ('stats pokemon', '/stats/pokemon', '#ledger-rows tr'),
    ('stats items', '/stats/items', '#ledger-rows tr'),
    ('pokedex', '/pokedex', '.dex-card'),
    ('pc box', '/pc?scope=box&box=1', '#pc-grid .pc-mon'),
    ('pc party', '/pc?scope=party', '#pc-grid .pc-mon'),
    ('pc all', '/pc?scope=all', '#pc-grid .pc-mon'),
    ('trading', '/trading', '#make-trade'),
]


@pytest.mark.parametrize('name,path,ready', GAME_PAGES, ids=[row[0] for row in GAME_PAGES])
def test_adventure_pages_have_clean_layout(page, adventure, name, path, ready):
    url, _ = adventure
    managed(page, url)
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, f'{url}/games/{FROM}{path}', ready)
        found += audit(page, name, width)
    check(found)


def test_event_page_has_clean_layout(page, adventure):
    url, eid = adventure
    managed(page, url)
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, f'{url}/games/{FROM}/events/{eid}', '#rewind')
        found += audit(page, 'event', width)
    check(found)


DIALOGS = [
    ('live party detail', '/', '#party .mon', '#mon-detail'),
    ('pc detail', '/pc?scope=box&box=1', '#pc-grid .pc-mon', '#pc-detail'),
    ('pokedex detail', '/pokedex', '.dex-card[data-dex="6"]', '#detail'),
]


@pytest.mark.parametrize('name,path,opener,dialog', DIALOGS, ids=[row[0] for row in DIALOGS])
def test_adventure_dialogs_have_clean_layout(page, adventure, name, path, opener, dialog):
    url, _ = adventure
    managed(page, url)
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, f'{url}/games/{FROM}{path}', opener)
        page.locator(opener).first.click()
        expect(page.locator(dialog)).to_be_visible()
        found += audit(page, name, width, root=dialog)
    check(found)


LIBRARY_PAGES = [
    ('library', '/', '.adventure-card', None, None),
    ('settings', '/settings', '#cartridge-grid .cartridge-slot', None, None),
    ('notifications', '/notifications', '#notify-add', None, None),
    ('new adventure', '/', '#new-adventure', '#new-adventure', '#create-dialog'),
    ('adventure settings', '/', '.card-settings', '.card-settings', '#adventure-settings'),
    ('card menu', '/', '.card-more-toggle', '.card-more-toggle', None),
    ('nickname pool', '/settings', '#nickname-edit', '#nickname-edit', '#nickname-dialog'),
    ('add integration', '/notifications', '#notify-add', '#notify-add', '#integration-dialog'),
]


@pytest.mark.parametrize('name,path,ready,opener,dialog', LIBRARY_PAGES, ids=[row[0] for row in LIBRARY_PAGES])
def test_library_pages_have_clean_layout(page, library, name, path, ready, opener, dialog):
    url, frame = library
    page.route('**/frame.jpg', lambda route: route.fulfill(body=frame, content_type='image/jpeg'))
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, url + path, ready)
        if opener:
            page.locator(opener).first.click()
            if dialog:
                expect(page.locator(dialog)).to_be_visible()
        found += audit(page, name, width, root=dialog)
    check(found)
