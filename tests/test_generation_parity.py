"""Gold, Silver and Crystal show what Red, Blue and Yellow show.

One adventure of each generation is built from its own emulator status and trackers. The live
state, statistics and activity ledger routes are then walked key by key. A field that one
generation fills and the other leaves out, None or empty fails the test unless the allowlist
below names it with a reason.
"""
from dataclasses import replace
import os
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pokesim.store import Store
from pokesim.web.app import create_app

ROUTES = {'state': '/api/state', 'statistics': '/api/statistics', 'activity': '/api/statistics/activity'}

# A key path, as the failure message prints it, and why one generation leaves it out on purpose.
# An entry covers everything under its path too.
ALLOWED = {
    # Settings and panels one generation has on purpose.
    'state.fair_wild_dvs': 'Gen 1 only. Fair wild DVs patch the Red, Blue and Yellow encounter code.',
    'statistics.collection_records.fair_wild_dvs': 'Gen 1 only, the same setting as state.fair_wild_dvs.',
    'state.palette': 'Gen 1 only. Gold, Silver and Crystal draw their own colors, as Yellow does.',
    'statistics.marathon': 'Gen 2 sends marathon: null on purpose. The Kanto Marathon is a Red, Blue and Yellow race.',
    'statistics.collection_records.perfect_count_is_minimum': 'Perfect DVs are counted from what is held, '
                                                              'so either generation may send only a minimum.',
    'state.clock': 'Gen 2 only. Gold, Silver and Crystal keep a real-time clock.',
    'activity.captures_since': 'Gen 2 leaves it out when its catch count covers the whole adventure.',
    # Labels a Red, Blue or Yellow payload leaves to the page defaults.
    'state.generation': 'Only Gen 2 names its generation. The pages read a missing one as Gen 1.',
    'activity.generation': 'Only Gen 2 names its generation. The pages read a missing one as Gen 1.',
    'state.game.generation': 'Only Gen 2 names its generation. The pages read a missing one as Gen 1.',
    'state.game.version': 'Gen 1 names its cartridge in strategy.collection.version.',
    'state.game.badge_total': 'Gen 2 sends 16. The pages default to 8 for Gen 1.',
    'state.game.dex_total': 'Gen 2 sends 251. The pages default to 151 for Gen 1.',
    # The cartridge snapshot follows each game's own memory.
    'state.game.map_group': 'Gen 2 numbers maps by group and number.',
    'state.game.map_number': 'Gen 2 numbers maps by group and number.',
    'state.game.daycare': 'Gen 2 only. Breeding starts in Gold, Silver and Crystal.',
    'state.game.enemy_level': 'Outside battle Gen 1 sends None and Gen 2 sends 0. The page draws it only in battle.',
    'state.game.saffron_open': 'Gen 1 only. The Saffron gate guards are a Red, Blue and Yellow check.',
    'state.game.textbox': 'Gen 1 only. The Gen 1 planner reads these screen flags from its snapshot.',
    'state.game.start_menu': 'Gen 1 only. The Gen 1 planner reads these screen flags from its snapshot.',
    'state.game.party[].stats': 'Gen 1 has one Special stat. Gen 2 splits it into Special Attack and Defense.',
    'state.game.party[].calculated_stats': 'Gen 1 has one Special stat. Gen 2 splits it into Special Attack and Defense.',
    'state.game.party[].egg': 'Gen 2 only. Eggs start in Gold, Silver and Crystal.',
    'state.game.party[].friendship': 'Gen 2 only. Friendship starts in Gold, Silver and Crystal.',
    'state.game.party[].gender': 'Gen 2 only. Gender starts in Gold, Silver and Crystal.',
    'state.game.party[].held_item': 'Gen 2 only. Held items start in Gold, Silver and Crystal.',
    'state.game.party[].hidden_power': 'Gen 2 only. Hidden Power starts in Gold, Silver and Crystal.',
    'state.game.party[].experience': 'Each generation names its experience fields its own way. The Live page '
                                     'draws only percent and max_level, which both send.',
    'state.game.party[].max_pp': 'The Gen 1 party record keeps PP limits in move_details, which the Live page draws.',
    'state.game.party[].move_details[].id': 'The Live page draws moves by name. The PC popup loads its own record.',
    'state.game.party[].perfect_dvs': 'The Live page does not draw it. The PC popup loads its own record.',
    'state.strategy': 'Each generation has its own planner. The Live page reads both goal shapes, '
                      'id and title or key and label, in objectiveOf.',
    # Three known differences have no field in these payloads, so they need no entry. Celebi (Crystal
    # only) is the celebi_event setting. Shiny sprites (Gen 2 only) are the /sprites/shiny route. An
    # untracked Gen 1 ROM hack sends None counts, and both fixtures here run tracked cartridges.
}

MISSING = object()


def blank(value):
    return value is MISSING or value is None or value == [] or value == {}


def merged(rows):
    """Every key the rows carry, with its first filled value, so a list is walked once."""
    result = {}
    for row in rows:
        for key, value in row.items():
            if blank(result.get(key, MISSING)):
                result[key] = value
    return result


def gaps(gen1, gen2, path):
    if isinstance(gen1, dict) and isinstance(gen2, dict):
        for key in sorted(set(gen1) | set(gen2)):
            yield from gaps(gen1.get(key, MISSING), gen2.get(key, MISSING), f'{path}.{key}')
        return
    if isinstance(gen1, list) and isinstance(gen2, list) and gen1 and gen2:
        if all(isinstance(row, dict) for row in gen1 + gen2):
            yield from gaps(merged(gen1), merged(gen2), f'{path}[]')
        return
    if blank(gen1) != blank(gen2):
        yield path, 'Gen 2' if blank(gen2) else 'Gen 1'


def paths(value, path):
    if isinstance(value, dict):
        for key, item in value.items():
            yield f'{path}.{key}'
            yield from paths(item, f'{path}.{key}')
    elif isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
        yield from paths(merged(value), f'{path}[]')


def allowed(path):
    return any(path == key or path.startswith((f'{key}.', f'{key}[')) for key in ALLOWED)


def test_gaps_name_the_key_path_and_the_generation_that_lacks_it():
    gen1 = {'a': {'b': 1, 'c': [{'d': 2}], 'e': None}, 'f': 0}
    gen2 = {'a': {'b': None, 'c': [{'d': 3}, {'g': [1]}], 'e': None}, 'f': False}
    assert list(gaps(gen1, gen2, 'x')) == [('x.a.b', 'Gen 2'), ('x.a.c[].g', 'Gen 1')]


@pytest.fixture(scope='module', params=['gold', 'crystal'])
def gen2_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def common(emu, store):
    """The run state both emulators keep, as a running adventure has it."""
    from pokesim.play_clock import PlayClock
    now = time.time()
    emu.store, emu.paused, emu.manual_mode, emu.frozen, emu.stopping, emu.speed = store, False, False, False, False, 1
    emu.frame = emu.executed_frames = 3600
    emu.started_at = emu.stuck_since = now - 600
    emu.last_activity, emu.last_reload, emu.fatal_error, emu.reloads = time.monotonic(), 0.0, None, 1
    emu.thread = SimpleNamespace(is_alive=lambda: True)
    emu.stall = SimpleNamespace(stalled=lambda *_: False, quiet=lambda *_: (1.5, 0))
    emu.play_clock = PlayClock({'seconds': 3600})
    emu.last_achievement = {'id': 1, 'title': 'Caught a Pokémon', 'ts': now - 30}
    with store.lock, store.db:
        store.db.execute('INSERT INTO progress(ts, badges, owned, seen, league, level100, perfect) '
                         'VALUES (?,?,?,?,?,?,?)', (now - 60, 1, 2, 3, 0, 0, 0))
    store.set('league_rewards', {'wins': 1})


def gen1_adventure(tmp_path):
    from pokesim import config
    from pokesim.activity_ledger import ActivityLedger
    from pokesim.catches import SUPPORTED, CatchTracker
    from pokesim.emulator import Emulator
    from pokesim.events import RunMemory
    from pokesim.legendary import LegendaryRecovery
    from pokesim.policies import make_policy
    from pokesim.ram import PartyMon
    from pokesim.shiny import ShinyTracker
    from pokesim.statistics import StatisticsTracker
    from test_events import snap
    store = Store(tmp_path / 'red')
    emu = Emulator.__new__(Emulator)
    common(emu, store)
    rom = sorted(SUPPORTED)[0]
    CatchTracker(store, rom, fresh=True)
    ShinyTracker(store, rom)
    ledger = ActivityLedger(store, rom)
    # The hook sites are checked against a real cartridge elsewhere. Here counting just starts.
    ledger.hooks = ()
    ledger.attach(None)
    party = (PartyMon(0x99, 20, 20, 5, 'BULBASAUR', types=(22, 3), moves=(33,), pp=(35,), max_pp=(35,),
                      dvs=(15, 10, 9, 8, 7), stat_exp=(0,) * 5, trainer_id=100),)
    emu.snapshot = snap(party=party, items=((4, 5),), owned=frozenset({1}), seen=frozenset({1, 16}), badges=1,
                        box_counts=(0,) * 12)
    statistics = StatisticsTracker(store)
    for frame, x in ((0, 5), (30, 6)):
        statistics.observe(snap(frame=frame, x=x, party=party), now=100 + frame)
    statistics.flush(now=200)
    emu.policy = make_policy(config.POLICY, 1)
    emu.preparation, emu.palette, emu.rom_note = None, 'original', 'Pokémon Red'
    emu.mem = RunMemory(seen_maps={1, 2})
    emu.invalid_since = None
    emu.legendary_recovery = LegendaryRecovery()
    return emu, store


def gen2_adventure(tmp_path, data):
    from pokecore.gen2.ram import Mon, Snapshot
    from pokesim import config
    from pokesim.gen2 import activity
    from pokesim.gen2.emulator import Emulator
    from pokesim.gen2.legendary import Recovery
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.statistics import Statistics
    from pokesim.gen2.tracking import Tracker
    store = Store(tmp_path / data.game)
    emu = Emulator.__new__(Emulator)
    common(emu, store)
    Tracker(store, data, fresh=True)
    activity.start(store, True)
    party = (Mon(1, 'BULBASAUR', 5, 20, 20, 0, 0, (33, 0, 0, 0), (35, 0, 0, 0), (35, 0, 0, 0),
                 (20, 10, 10, 10, 10, 10), 135, (15, 10, 9, 8, 7), (0,) * 5, 100, 70, data=data),)
    start = next(iter(data.maps))
    emu.snapshot = Snapshot(
        frame=3600, map=start, x=5, y=5, player_name='GOLD', rival_name='SILVER', party=party, stored=(),
        box_counts=(0,) * 14, active_box=0, owned=frozenset({1}), seen=frozenset({1, 16}), badges=1,
        items=((18, 5),), pockets={}, money=3000, coins=0, in_battle=0, enemy_species=0, enemy_level=0,
        enemy_hp=0, enemy_max_hp=0, trainer_class=0, battle_type=0, playtime=(1, 0, 0), hall_of_fame_count=0,
        event_flags=bytes(256), tiles=(), objects=(), valid=True, data=data)
    statistics = Statistics(store, clock=emu.play_clock.status)
    for frame in (3570, 3600):
        statistics.observe(replace(emu.snapshot, frame=frame))
    statistics.flush(emu.snapshot)
    emu.data, emu.policy = data, Policy(data, seed=1, starter=config.STARTER)
    emu.rom_note = f'Pokémon {data.game.title()} (revision 0)'
    emu.progress_frame, emu.waiting, emu.unstick_streak, emu.invalid_frame = 3500, False, 0, None
    emu.game_clock = {'weekday': 'Monday', 'hour': 10, 'minute': 0, 'period': 'Day'}
    emu.history = {'maps': [start], 'owned': [1], 'badges': 1, 'league': 0}
    emu.legendary_recovery = Recovery()
    return emu, store


def payloads(emu, store):
    client = TestClient(create_app(emu, store))
    result = {}
    for name, route in ROUTES.items():
        response = client.get(route)
        assert response.status_code == 200, (route, response.text)
        result[name] = response.json()
    return result


def test_both_generations_fill_the_same_user_visible_fields(tmp_path, gen2_data):
    red, red_store = gen1_adventure(tmp_path)
    gold, gold_store = gen2_adventure(tmp_path, gen2_data)
    try:
        gen1, gen2 = payloads(red, red_store), payloads(gold, gold_store)
    finally:
        red_store.close()
        gold_store.close()
    # An entry for a field neither payload sends any more is stale.
    present = {path.lstrip('.') for payload in (gen1, gen2) for path in paths(payload, '')}
    assert not set(ALLOWED) - present, sorted(set(ALLOWED) - present)
    found = [(path, lacking) for path, lacking in gaps(gen1, gen2, '') if not allowed(path.lstrip('.'))]
    assert not found,'Fields one generation fills and the other leaves out:\n' + '\n'.join(
        f'  {path.lstrip(".")}: missing on {lacking}' for path, lacking in found)
