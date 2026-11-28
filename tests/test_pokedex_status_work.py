"""Polled routes build only the boxed records they send, and each record works out its stats once."""
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from pokesim import pokemon
from pokesim.store import Store
from pokesim.strategy_data import SPECIES
from pokesim.web import pokedex
from pokesim.web.app import HOLDER_FIELDS, create_app, pick

BY_DEX = {row['dex']: sid for sid, row in SPECIES.items()}


def boxed(box, position, dex, level, dvs=(9, 8, 7, 6, 5)):
    """A box record as the Gen I snapshot sends it, before the Pokédex adds anything."""
    sid = BY_DEX[dex]
    return {'box': box, 'position': position, 'species': sid, 'level': level, 'nick': SPECIES[sid]['name'][:10],
            'moves': [33, 45], 'experience': level ** 3, 'dvs': list(dvs), 'stat_exp': [900] * 5,
            'trainer_id': 4242, 'hp': 20, 'status': 0, 'pp': [35, 40], 'max_pp': [35, 40], 'types': [0, 0],
            'name': SPECIES[sid]['name'].title()}


def member(slot, dex, level):
    sid = BY_DEX[dex]
    return {'species': sid, 'dex': dex, 'name': SPECIES[sid]['name'].title(), 'nick': SPECIES[sid]['name'][:10],
            'level': level, 'hp': 40, 'max_hp': 40, 'status': 0, 'pending': False, 'types': [0, 0],
            'moves': [33, 45], 'pp': [35, 40], 'max_pp': [35, 40], 'dvs': [15, 15, 15, 15, 15], 'stat_exp': [0] * 5,
            'trainer_id': 4242, 'experience': {'total': level ** 3}, 'status_label': 'Healthy', 'shiny': False,
            'move_details': [], 'slot': slot}


def game():
    rows = [boxed(1, 1, 129, 20), boxed(1, 2, 129, 31, dvs=(15, 15, 15, 15, 15)), boxed(1, 3, 41, 12)]
    return {'party': [member(1, 19, 30), member(2, 129, 15)], 'dex_owned': [19, 41, 129], 'dex_seen': [19, 41, 129],
            'player_name': 'RED', 'playtime': '10:00:00',
            'storage': {'active_box': 1, 'count': len(rows), 'capacity': 20, 'box_counts': [len(rows)],
                        'can_catch': True, 'pokemon': rows}}


@contextmanager
def api(tmp_path, **kwargs):
    store = Store(tmp_path)
    status = {'strategy': {'collection': {'version': 'red'}}, 'game': game()}
    try:
        yield TestClient(create_app(SimpleNamespace(status=lambda: status), store, **kwargs))
    finally:
        store.close()


def test_the_live_popup_and_pokedex_build_no_boxed_record_and_answer_as_before(tmp_path, monkeypatch):
    built, record = [], pokedex.stored_record
    monkeypatch.setattr(pokedex, 'stored_record', lambda mon: built.append(mon) or record(mon))
    with api(tmp_path) as client:
        full = client.get('/api/pokedex/status').json()
        assert len(built) == 3
        built.clear()
        party = client.get('/api/pokedex/status', params={'view': 'party'}).json()
        dex = client.get('/api/pokedex/status', params={'view': 'dex'}).json()
    # The popup sends no boxes and the Pokédex only who holds each species, so neither needs a full record.
    assert built == []
    assert {key: value for key, value in party.items() if key != 'viewer_only'} == {
        key: value for key, value in full.items() if key not in ('plan', 'storage')}
    assert dex['storage'] == {**full['storage'], 'pokemon': [pick(mon, HOLDER_FIELDS)
                                                             for mon in full['storage']['pokemon']]}
    assert dex['party'] == [pick(mon, HOLDER_FIELDS) for mon in full['party']]
    assert {key: value for key, value in dex.items() if key not in ('party', 'storage')} == {
        key: value for key, value in full.items() if key not in ('party', 'storage')}
    assert {mon['dex'] for mon in dex['storage']['pokemon']} == {41, 129}
    assert dex['milestones']['perfect_held'] == 3


def test_managed_trading_reads_only_the_participant_inventory(tmp_path, monkeypatch):
    calls, live = [], pokedex.live_status
    monkeypatch.setattr('pokesim.web.app.live_status', lambda *args, **kwargs: calls.append(1) or live(*args, **kwargs))
    inventory = {'started': True, 'version': 'red', 'owned': [], 'party': [], 'storage': {'pokemon': []}}
    with api(tmp_path, base_path='/games/a', adventure_id='a') as client:
        client.app.state.participant = SimpleNamespace(runtime=SimpleNamespace(call=lambda operation: operation()),
                                                       inventory=lambda: inventory)
        response = client.get('/api/trading')
    assert response.status_code == 200 and response.json()['managed'] is True
    # The route answers from the participant's inventory, so the page's own Pokédex status was thrown away.
    assert calls == []


def test_a_boxed_record_works_out_its_stats_once(monkeypatch):
    calls, strength = [], pokemon.stored_strength
    for module in (pokemon, pokedex):
        monkeypatch.setattr(module, 'stored_strength', lambda mon: calls.append(1) or strength(mon))
    record = pokedex.stored_record(boxed(1, 1, 129, 31))
    assert len(calls) == 1
    assert record['max_hp'] == record['calculated_stats']['HP'] and record['hp'] == 20
    assert record['power'] == strength(boxed(1, 1, 129, 31))['power']
