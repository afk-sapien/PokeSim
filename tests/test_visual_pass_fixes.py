"""Per-game pages and Gold, Silver and Crystal statistics from the 0.5.0 visual pass."""
import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

from pokesim import adventure_records, build_info
from pokesim.activity_ledger import gen2_status
from pokesim.store import Store
from pokesim.web import pages
from pokesim.web.app import create_app


def gen2_emulator(game=None, **status):
    species = {sid: {'name': f'Species {sid}', 'dex': sid} for sid in range(1, 252)}
    data = SimpleNamespace(game='gold', species=species, item_names={1: 'Master Ball', 18: 'Potion'})
    current = {'game': game or {}, **status}
    return SimpleNamespace(generation=2, data=data, status=lambda: current, current_frame=lambda timeout=1: b'live')


def mon(dex, **fields):
    return {'dex': dex, 'name': f'Species {dex}', 'egg': False, 'shiny': False, 'dv_total': 40, **fields}


def test_gen2_statistics_report_overview_recent_and_sixteen_badge_milestones(tmp_path):
    game = {'party': [mon(155, shiny=True), mon(215, egg=True, shiny=True)], 'storage': {'pokemon': [mon(4)]}}
    client = TestClient(create_app(gen2_emulator(game, play_clock={'seconds': 60}, areas_discovered=12), Store(tmp_path)))
    result = client.get('/api/statistics').json()
    assert result['overview']['held'] == 2
    assert result['overview']['areas'] == 12
    assert 'day' in result['recent']
    labels = [row['label'] for row in result['milestone_records']['milestones']]
    assert 'All sixteen badges' in labels and 'All 251 registered' in labels
    assert result['collection_records']['shiny']['held'] == 1
    assert result['marathon'] is None


def test_gen2_records_need_all_sixteen_badges_and_ignore_shiny_eggs(tmp_path):
    tracker = adventure_records.RecordTracker(Store(tmp_path), generation=2)
    egg = SimpleNamespace(egg=True, shiny=True)
    snapshot = SimpleNamespace(badges=0xFF, hall_of_fame_count=0, owned=frozenset(range(1, 252)),
                               party=(egg,), stored=())
    first, eight, _, dex, _, shiny, _ = tracker.conditions(snapshot)
    assert first and not eight and dex and not shiny
    assert tracker.conditions(SimpleNamespace(**{**vars(snapshot), 'badges': 0xFFFF}))[1]


def test_pages_print_the_cartridge_dex_size_region_and_marathon(tmp_path):
    gold = TestClient(create_app(gen2_emulator(), Store(tmp_path / 'gold')))
    red = TestClient(create_app(SimpleNamespace(status=lambda: {}), Store(tmp_path / 'red')))
    assert '/251</span>' in gold.get('/').text and 'Somewhere in Johto and Kanto' in gold.get('/').text
    assert 'Species register · Johto and Kanto · 251 entries' in gold.get('/pokedex').text
    stats = gold.get('/stats').text
    assert '<meta name="pokesim-dex-total" content="251">' in stats
    assert 'aria-labelledby="marathon-heading" hidden>' in stats
    assert '/151</span>' in red.get('/').text and 'Somewhere in Kanto' in red.get('/').text
    assert 'aria-labelledby="marathon-heading">' in red.get('/stats').text


def test_version_label_names_the_short_commit(monkeypatch):
    assert build_info.version_label({'version': '0.5.0', 'revision': '95f4a11' + '0' * 33}) == 'v0.5.0 · 95f4a11'
    assert build_info.version_label({'version': '0.5.0', 'revision': None}) == 'v0.5.0'
    monkeypatch.setattr(pages, 'version_label', lambda: 'v9.9.9 · abcdef1')
    assert 'v9.9.9 · abcdef1' in pages.render_game_page('index.html')


def test_gen2_activity_lists_all_251_species_and_skips_eggs():
    game = {'party': [mon(251), mon(175, egg=True)], 'items': [{'id': 18, 'qty': 3}]}
    result = gen2_status(gen2_emulator().data, game)
    assert len(result['pokemon']) == 251 and result['generation'] == 2
    held = {row['id']: row['held'] for row in result['pokemon']}
    assert held[251] == 1 and held[175] == 0
    assert result['pokemon'][0]['wild'] is None
    assert result['items'] == [{'id': 18, 'name': 'Potion', 'bought': None, 'used': None, 'bag': 3}]


def test_gen2_activity_route_uses_the_gen2_ledger(tmp_path):
    client = TestClient(create_app(gen2_emulator({'party': [mon(200)]}), Store(tmp_path)))
    result = client.get('/api/statistics/activity').json()
    assert len(result['pokemon']) == 251 and result['champion_shop'] is None


def test_frame_endpoint_prefers_the_last_picture(tmp_path):
    emu = gen2_emulator()
    emu.still_frame = lambda: b'picture'
    client = TestClient(create_app(emu, Store(tmp_path)))
    assert client.get('/frame.jpg').content == b'picture'


def test_gen2_thumbnail_skips_blank_transition_frames():
    from pokesim.gen2.emulator import Emulator, solid
    white = Image.new('RGB', (160, 144), 'white')
    picture = white.copy()
    picture.putpixel((3, 3), (0, 0, 0))
    assert solid(white) and not solid(picture)
    emu = Emulator.__new__(Emulator)
    emu.pb = SimpleNamespace(screen=SimpleNamespace(image=picture))
    emu._shot_png()
    emu.pb.screen.image = white
    emu.frame_image = emu._shot_png()
    emu.current_frame = lambda timeout=1: emu.frame_image
    assert Image.open(io.BytesIO(emu.still_frame())).getpixel((3, 3)) == (0, 0, 0)


def test_gen2_game_clock_reads_weekday_time_and_period():
    from pokesim.gen2.emulator import game_clock
    symbols = {'wCurDay': (0, 0xD000), 'wTimeOfDay': (0, 0xD001), 'hHours': (0, 0xFF90), 'hMinutes': (0, 0xFF91)}
    memory = bytearray(0x10000)
    memory[0xD000], memory[0xD001], memory[0xFF90], memory[0xFF91] = 9, 0, 8, 5

    class Banked:
        def __getitem__(self, key):
            if isinstance(key, tuple):
                return memory[key[1]]
            return memory[key]

    clock = game_clock(Banked(), SimpleNamespace(symbols=symbols))
    assert clock == {'weekday': 'Tuesday', 'hours': 8, 'minutes': 5, 'time_of_day': 'Morning'}
    memory[0xFF90] = 30
    assert game_clock(Banked(), SimpleNamespace(symbols=symbols)) is None


def test_red_plan_names_maps_the_way_the_game_does():
    from pokesim.policies.collection import place
    from pokesim.strategy_data import WORLD
    seafoam = next(mid for mid, world in WORLD.items() if world['name'] == 'SeafoamIslandsB3F')
    assert place(seafoam) == 'Seafoam Islands B3F'
