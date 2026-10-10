"""Polled routes send each page only what it draws; full records stay with Python callers."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from pokesim.web import app as web
from pokesim.web.app import HOLDER_FIELDS, OFFER_FIELDS, create_app

STATIC = Path(web.__file__).parent / 'static'
BOXED = 280


def mon(position, **extra):
    """A Pokémon record the size of a real one: moves, stats and experience included."""
    return {'species': 245, 'dex': 245, 'name': 'Suicune', 'nick': 'SOCKPILOT', 'level': 40, 'box': 1 + position // 20,
            'position': 1 + position % 20, 'trade_key': f'key-{position}', 'shiny': False, 'perfect_dvs': False,
            'egg': False, 'dv_stars': 1, 'dv_total': 19, 'dvs': [4, 0, 3, 8, 4], 'stat_exp': [0] * 5,
            'moves': [43, 61, 240, 16], 'pp': [30, 20, 5, 35], 'max_pp': [30, 20, 5, 35],
            'move_details': [{'id': move, 'name': 'Leer', 'type': 'Normal', 'pp': 30, 'max_pp': 30, 'power': 0,
                              'accuracy': 100} for move in (43, 61, 240, 16)],
            'experience': {'total': 80000, 'level_start': 80000, 'next_level': 86151, 'remaining': 6151,
                           'max_level': False, 'percent': 0},
            'calculated_stats': {'HP': 133, 'Attack': 65, 'Defense': 99, 'Speed': 79, 'Special Attack': 80,
                                 'Special Defense': 100},
            'stats': {'Attack': 65, 'Defense': 99, 'Speed': 79, 'Special Attack': 80, 'Special Defense': 100},
            'caught': {'level': 40, 'time': 'Day', 'location': 'Tin Tower'}, 'type_names': ['Water'],
            'status_label': 'Healthy', 'hidden_power': {'type': 'Ground', 'power': 36}, **extra}


def game():
    return {'map_name': 'Tin Tower', 'playtime': '1686:50', 'x': 3, 'y': 4,
            'party': [mon(index, box=0, slot=index + 1) for index in range(6)],
            'storage': {'active_box': 3, 'count': BOXED, 'capacity': 400, 'box_counts': [20] * 14,
                        'pokemon': [mon(index) for index in range(BOXED)]}}


def status():
    return {'version': '0.5.0', 'frame': 99, 'paused': True, 'manual_mode': False, 'speed': 2, 'palette': 'original',
            'health': {'ok': True}, 'performance': {'frames': 1}, 'league_rewards': {'wins': 3},
            'progress': {'state': 'stalled'}, 'strategy': {'collection': {'version': 'red'}}, 'game': game()}


def client(tmp_path, monkeypatch, **kwargs):
    store = SimpleNamespace(shots=tmp_path, get=lambda _: None, trade_preferences=lambda: {})
    emu = SimpleNamespace(status=status)
    return TestClient(create_app(emu, store, **kwargs))


def size(response):
    assert response.status_code == 200
    return len(response.content)


def test_live_state_leaves_out_boxed_pokemon_unless_asked(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    full = api.get('/api/state', params={'storage': 1})
    light = api.get('/api/state')
    assert len(full.json()['game']['storage']['pokemon']) == BOXED
    storage = light.json()['game']['storage']
    assert 'pokemon' not in storage
    assert storage['box_counts'] == [20] * 14 and storage['active_box'] == 3
    assert len(light.json()['game']['party']) == 6
    assert size(light) < 20_000 < 300_000 < size(full)
    # The emulator's own status is never trimmed in place.
    assert len(status()['game']['storage']['pokemon']) == BOXED


def test_live_page_never_reads_boxed_pokemon_from_state():
    assert 'storage' not in (STATIC / 'app.js').read_text()


def test_supervisor_summary_carries_playback_and_health_without_game_data(tmp_path, monkeypatch):
    summary = client(tmp_path, monkeypatch).get('/api/summary')
    data = summary.json()
    assert size(summary) < 1_000
    assert data['game'] == {'map_name': 'Tin Tower', 'playtime': '1686:50'}
    assert 'strategy' not in data
    for key, value in {'paused': True, 'manual_mode': False, 'speed': 2, 'palette': 'original', 'frame': 99,
                       'performance': {'frames': 1}, 'league_rewards': {'wins': 3}, 'health': {'ok': True},
                       'progress': {'state': 'stalled'}, 'viewer_only': False}.items():
        assert data[key] == value


def test_supervisor_and_backup_poll_the_summary():
    root = Path(web.__file__).parents[1] / 'app'
    for name in ('supervisor.py', 'backup.py'):
        text = (root / name).read_text()
        assert "'/api/summary'" in text and "'/api/state'" not in text, name


def test_trading_offers_carry_only_what_the_trading_pages_draw(tmp_path, monkeypatch):
    from pokesim.web import trading
    offers = [mon(index, listed=index % 2 == 0, preference='auto', editable=True, locked=False, source='Spare copy',
                  reason='', can_offer=True) for index in range(BOXED)]
    payload = {'version': 'red', 'owned': [], 'seen': [], 'party': [], 'storage': None}
    monkeypatch.setattr(trading, 'unavailable', lambda payload, instance, message: {
        'connected': False, 'instance': instance, 'offers': offers, 'message': message})
    monkeypatch.setattr('pokesim.web.app.live_status', lambda *args, **kwargs: dict(payload))
    monkeypatch.setattr('pokesim.web.app.preferences.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.league_partners.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.milestones.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.catches.status', lambda _: None)
    api = client(tmp_path, monkeypatch, base_path='/games/a', adventure_id='a')
    api.app.state.participant = SimpleNamespace(runtime=SimpleNamespace(call=lambda operation: payload),
                                                inventory=lambda: payload)
    response = api.get('/api/trading')
    rows = response.json()['offers']
    assert len(rows) == BOXED and size(response) < 100_000
    assert rows[0] == {key: offers[0][key] for key in OFFER_FIELDS if key in offers[0]}
    assert 'move_details' not in rows[0] and 'experience' not in rows[0]


def test_offer_fields_cover_every_field_the_trade_controls_read():
    read = set(re.findall(r'\bmon\.(\w+)', (STATIC / 'trade-ui.js').read_text()))
    block = next(line for line in (STATIC / 'trading.js').read_text().splitlines() if "view === 'block'" in line)
    script = (STATIC / 'trading.js').read_text()
    start = script.index(block)
    read |= set(re.findall(r'\bmon\.(\w+)', script[start:script.index("view === 'opportunities'")]))
    read |= {'dex'}  # sprite(mon) draws the portrait from it
    assert read and read <= set(OFFER_FIELDS), read - set(OFFER_FIELDS)


@pytest.fixture
def dex_status(monkeypatch):
    payload = {'version': 'red', 'started': True, 'owned': [1], 'seen': [1], 'generation': 1, 'party': game()['party'],
               'storage': game()['storage'], 'plan': [{'dex': dex, 'sources': [{'detail': 'x' * 200}] * 3}
                                                     for dex in range(1, 152)]}
    monkeypatch.setattr('pokesim.web.app.live_status', lambda *args, **kwargs: json.loads(json.dumps(payload)))
    monkeypatch.setattr('pokesim.web.app.preferences.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.league_partners.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.milestones.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.catches.status', lambda _: {'available': False})
    return payload


def test_pokedex_status_views_trim_for_their_page_and_default_stays_full(tmp_path, monkeypatch, dex_status):
    api = client(tmp_path, monkeypatch)
    full = api.get('/api/pokedex/status')
    pc = api.get('/api/pokedex/status', params={'view': 'pc'})
    dex = api.get('/api/pokedex/status', params={'view': 'dex'})
    # Broker and tools read the default view and need every record in full.
    assert full.json()['storage']['pokemon'][0]['move_details'] and full.json()['plan']
    assert 'plan' not in pc.json()
    assert pc.json()['storage'] == full.json()['storage'] and pc.json()['party'] == full.json()['party']
    assert dex.json()['plan'] == full.json()['plan']
    assert set(dex.json()['storage']['pokemon'][0]) <= set(HOLDER_FIELDS)
    assert set(dex.json()['party'][0]) <= set(HOLDER_FIELDS)
    assert dex.json()['storage']['active_box'] == 3
    assert size(pc) < size(full) - 90_000 and size(dex) < size(full) - 250_000
    assert api.get('/api/pokedex/status', params={'view': 'other'}).status_code == 422


def test_pages_ask_for_their_pokedex_view_and_holder_fields_cover_the_pokedex():
    assert "'/api/pokedex/status?view=pc'" in (STATIC / 'pc.js').read_text()
    script = (STATIC / 'pokedex.js').read_text()
    assert "'/api/pokedex/status?view=dex'" in script
    read = set(re.findall(r'\bmon\.(\w+)', script))
    assert read and read <= set(HOLDER_FIELDS), read - set(HOLDER_FIELDS)


def reads(script, *names):
    """Fields a page script reads from objects it names, such as mon.level or status.plan."""
    text = (STATIC / script).read_text()
    return {name: set(re.findall(rf'\b{name}\.([a-z_]+)', text)) for name in names}


def test_each_page_view_keeps_every_field_its_page_reads(tmp_path, monkeypatch):
    pc, dex = reads('pc.js', 'status', 'mon'), reads('pokedex.js', 'status', 'mon', 'row', 'project')
    assert {'move_details', 'hidden_power', 'experience'} <= pc['mon'] and {'plan', 'owned'} <= dex['status']
    record = {field: 1 for field in pc['mon'] | dex['mon']}
    plan = [{**{field: 1 for field in dex['row'] | dex['project']}, 'dex': 1}]
    payload = {**{field: 1 for field in pc['status'] | dex['status']}, 'party': [dict(record)],
               'storage': {'active_box': 1, 'box_counts': [1], 'pokemon': [dict(record)]}, 'plan': plan}
    monkeypatch.setattr('pokesim.web.app.live_status', lambda *args, **kwargs: json.loads(json.dumps(payload)))
    monkeypatch.setattr('pokesim.web.app.preferences.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.league_partners.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.milestones.apply', lambda data, _: data)
    monkeypatch.setattr('pokesim.catches.status', lambda _: 1)
    api = client(tmp_path, monkeypatch)
    for view, script, fields in (('pc', 'pc.js', pc), ('dex', 'pokedex.js', dex)):
        data = api.get('/api/pokedex/status', params={'view': view}).json()
        assert fields['status'] <= set(data), (script, fields['status'] - set(data))
        for mon in (data['party'][0], data['storage']['pokemon'][0]):
            assert fields['mon'] <= set(mon), (script, fields['mon'] - set(mon))
        if 'plan' in fields['status']:
            assert fields['row'] | fields['project'] <= set(data['plan'][0])


def test_browser_mocks_of_pokedex_status_also_match_its_views():
    """A route glob without the query string silently stops mocking once a page asks for a view."""
    for test in (Path(__file__).parent / 'browser').glob('test_*.py'):
        assert "route('**/api/pokedex/status'" not in test.read_text(), test.name
