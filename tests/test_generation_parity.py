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
    'statistics.current.marathons': 'Gen 2 keeps no marathon count, the same race as statistics.marathon.',
    'statistics.history[].marathons': 'Gen 2 keeps no marathon count, the same race as statistics.marathon.',
    'statistics.collection_records.perfect_count_is_minimum': 'Perfect DVs are counted from what is held, '
                                                              'so either generation may send only a minimum.',
    'state.clock': 'Gen 2 only. Gold, Silver and Crystal keep a real-time clock.',
    'activity.captures_since': 'Gen 2 leaves it out when its catch count covers the whole adventure.',
    # Labels a Red, Blue or Yellow payload leaves to the page defaults.
    'state.generation': 'Only Gen 2 names its generation. The pages read a missing one as Gen 1.',
    'activity.generation': 'Only Gen 2 names its generation. The pages read a missing one as Gen 1.',
    'statistics.generation': 'Only Gen 2 names its generation. The Stats page reads a missing one as Gen 1.',
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
    # An hour of play, counted in frames.
    emu.play_clock = PlayClock({'frames': 3600 * 60, 'initialized': True})
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


def test_gen2_sales_contest_catches_and_session_trades_reach_the_pages(tmp_path, gen2_data):
    """A vending machine sale, a kept contest Pokémon and a two-trade cable session, each through its
    own hook, fill Purchased, Caught and both trade counts, and Caught agrees with Total caught."""
    from test_gen2_activity import release_session
    from test_gen2_shiny import Ram
    from pokesim.gen2 import activity
    from pokesim.gen2.tracking import Tracker
    gold, store = gen2_adventure(tmp_path, gen2_data)
    try:
        ram, water = Ram(gen2_data), gen2_data.items['FRESH_WATER']
        pb = SimpleNamespace(memory=ram)
        # giveitem FRESH_WATER / iffalse .NotEnoughSpace / takemoney YOUR_MONEY, 200, at 0x6000.
        ram.raw[0x6000:0x600B] = bytes((0x1F, water, 1, 0x08, 0x34, 0x12, 0x23, 0x00, 0xC8, 0x00, 0x00))
        ram.put('wScriptBank', 0x15)
        ram.put('wScriptPos', b'\x07\x60')
        activity.Ledger(store, gen2_data, fresh=True).completed(('vended', pb))
        ram.put('wContestMonSpecies', 123)
        Tracker(store, gen2_data, fresh=True).contest_kept(pb)
        release_session(store, gen2_data)
        pages = payloads(gold, store)
    finally:
        store.close()
    pokemon = {row['id']: row for row in pages['activity']['pokemon']}
    items = {row['id']: row for row in pages['activity']['items']}
    assert items[water]['bought'] == 1 and pokemon[123]['caught'] == 1
    assert (pokemon[4]['traded_out'], pokemon[7]['traded_out'], pokemon[152]['traded_in'], pokemon[155]['traded_in']) == (1, 1, 1, 1)
    catches = pages['statistics']['collection_records']['catches']
    assert catches['total'] == sum(row['caught'] for row in pokemon.values()) == 1


def sixty_days_of_hours(store):
    import json
    with store.lock, store.db:
        store.db.executemany('INSERT OR REPLACE INTO statistics_history VALUES (?, ?, ?)',
                             [(hour, hour * 3600, json.dumps({'steps': hour})) for hour in range(24 * 60)])


def test_both_generations_compact_old_history(tmp_path, gen2_data):
    """Each keeps hourly rows for 30 days and one a day before that, so history stops growing by the hour."""
    from pokesim.gen2.statistics import Statistics
    from pokesim.statistics import DAY, StatisticsTracker
    red, red_store = gen1_adventure(tmp_path)
    gold, gold_store = gen2_adventure(tmp_path, gen2_data)
    try:
        for store in (red_store, gold_store):
            sixty_days_of_hours(store)
        StatisticsTracker(red_store).flush(now=60 * DAY)
        Statistics(gold_store).flush(gold.snapshot, now=60 * DAY)
        counts = [store.db.execute('SELECT COUNT(*) FROM statistics_history').fetchone()[0]
                  for store in (red_store, gold_store)]
    finally:
        red_store.close()
        gold_store.close()
    # 30 daily rows, 30 days of hourly rows, the new row and the fixture's own flush.
    assert all(24 * 30 <= count <= 30 + 24 * 30 + 2 for count in counts), counts


def test_gen2_collection_waits_for_two_matching_reads_as_gen1_does(tmp_path, gen2_data):
    """A box read in the middle of a PC transfer is not charted until the next read agrees."""
    from pokesim.gen2.statistics import Statistics
    gold, store = gen2_adventure(tmp_path, gen2_data)
    try:
        statistics = Statistics(store)
        assert statistics.gauges['held'] == 1
        statistics.observe(replace(gold.snapshot, party=()))
        assert statistics.gauges['held'] == 1
        statistics.observe(replace(gold.snapshot, frame=3630, party=()))
        assert statistics.gauges['held'] == 0
        history = store.db.execute('SELECT data FROM statistics_history').fetchall()
    finally:
        store.close()
    # Gold, Silver and Crystal have no Kanto Marathon, so history keeps no count for it.
    assert all('"marathons": null' in row[0] for row in history)


def test_gen2_planner_releases_reach_the_journal_as_gen1_releases_do():
    from pokesim.gen2.emulator import Event
    from pokesim.gen2.journal import Releases
    from pokesim.gen2.menus import Release
    data = SimpleNamespace(species={16: {'name': 'Pidgey'}})
    spare = SimpleNamespace(species=16, trainer_id=100, dvs=(1, 2, 3, 4), level=7, box=0, position=0)
    keep = SimpleNamespace(species=16, trainer_id=100, dvs=(9, 9, 9, 9), level=9, box=0, position=1)
    held = SimpleNamespace(party=(), stored=(spare, keep), map_name='Route 30')
    gone = SimpleNamespace(party=(), stored=(keep,), map_name='Route 30')
    task = Release(0, 0, [16, 100, [1, 2, 3, 4]])
    releases = Releases()
    assert releases.observe(task, held, data, Event) == []
    # One read without the spare could be a box half written, so it waits for a second.
    assert releases.observe(task, gone, data, Event) == []
    [event] = releases.observe(None, gone, data, Event)
    assert (event.type, event.title, event.notable) == ('release', 'Said goodbye to a spare Pidgey', False)
    assert releases.observe(None, gone, data, Event) == []
    # A refused release ends the task with the spare still in its box, and nothing is logged.
    refused = Releases()
    refused.observe(task, held, data, Event)
    assert refused.observe(None, held, data, Event) == [] and refused.member is None


def test_both_generations_keep_the_same_battle_and_moment_tallies(tmp_path, gen2_data):
    """Each generation writes its own journal entries. The Stats page counts them the same way
    and keeps them after the journal is pruned."""
    from pokesim.events import Event as Gen1Event
    from pokesim.gen2.emulator import Event as Gen2Event
    moments = [('faint', 'BULBASAUR fainted', ''), ('blackout', 'Blacked out!', 'fainted fighting a RATTATA.'),
               ('blackout', 'Blacked out!', 'The whole party fainted.'), ('trainer', 'Defeated a Youngster', ''),
               ('evolve', 'BULBASAUR evolved!', ''), ('release', 'Said goodbye to a spare Rattata', '')]
    tallies = []
    for emu, store, event in (gen1_adventure(tmp_path) + (Gen1Event,), gen2_adventure(tmp_path, gen2_data) + (Gen2Event,)):
        try:
            for kind, title, body in moments:
                store.add_event(event(kind, title, body), emu.snapshot, None, None)
            with store.lock, store.db:
                store.db.execute('UPDATE events SET ts = 0')
            store.prune_events(1)
            tallies.append(payloads(emu, store)['statistics']['tallies'])
        finally:
            store.close()
    gen1, gen2 = tallies
    assert gen1 == gen2
    assert (gen1['faints'], gen1['blackouts'], gen1['trainers_defeated'], gen1['trainer_losses']) == (1, 2, 1, 1)
    assert (gen1['evolutions'], gen1['releases'], gen1['trainer_win_rate']) == (1, 1, 50.0)


def test_both_generations_report_catch_pace_and_a_dated_shiny_log(tmp_path, gen2_data):
    """Three catches in an hour of play, 30 wild Pidgey for them and one shiny seen give the same
    rates, per species ratio and shiny log in both generations."""
    from pokesim import shiny
    from pokesim.activity_ledger import increment
    from pokesim.catches import KEY as GEN1_CATCHES
    from pokesim.gen2.tracking import CAPTURES
    found = []
    for generation, (emu, store), key in ((1, gen1_adventure(tmp_path), GEN1_CATCHES),
                                          (2, gen2_adventure(tmp_path, gen2_data), CAPTURES)):
        try:
            store.set(key, {**store.get(key), 'total': 3, 'complete_history': True})
            with store.lock, store.db:
                increment(store.db, 'wild', 16, 30)
                increment(store.db, 'caught', 16, 3)
                shiny.record(store.db, 'seen', 'pidgey', 16, generation=generation)
            pages = payloads(emu, store)
        finally:
            store.close()
        records = pages['statistics']['collection_records']
        pidgey = next(row for row in pages['activity']['pokemon'] if row['id'] == 16)
        log = [(entry['kind'], entry['dex'], entry['name'].upper(), entry['ts'] > 0) for entry in records['shiny']['log']]
        found.append((records['rates'], pidgey['per_catch'], log))
    assert found[0] == found[1]
    assert found[0] == ({'catches_per_hour': 3.0, 'encounters_per_catch': 10.0, 'partial': False}, 10.0,
                        [('seen', 16, 'PIDGEY', True)])
