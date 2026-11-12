"""Shadow-mode progress rows in both generations (docs/design/goal-system.md, section 4)."""
from types import SimpleNamespace

import pytest

from pokesim import progress_events
from pokesim.events import Event
from pokesim.store import Store
from test_behavior_parity import PAIRS, gen1_catches, gen1_checkpoint, gen2_catches, gen2_checkpoint
from test_behavior_parity import gen2_data as gen2_data  # noqa: F401 (a fixture)
from test_collection import sid

SNAPSHOT = SimpleNamespace(map_name='Route 1', playtime=(0, 0, 0), valid=False, started=False)


def rows(store, *kinds):
    marks = ','.join('?' * len(kinds))
    return store.db.execute(f'SELECT kind, frame, goal, tier, species, identity, score, net FROM progress_events '
                            f'WHERE kind IN ({marks}) ORDER BY id', kinds).fetchall()


def test_both_marathons_write_a_net_row_for_a_checkpoint(tmp_path, gen2_data, monkeypatch):  # noqa: F811
    for name, (_, queue) in (('gen1', gen1_checkpoint()), ('gen2', gen2_checkpoint(gen2_data, monkeypatch))):
        store = Store(tmp_path / name)
        store.clock = lambda: 600
        try:
            assert progress_events.drain(store, queue) == []
            [(kind, frame, goal, tier, _, _, score, net)] = rows(store, 'checkpoint')
            assert (kind, frame, tier, score, net) == ('checkpoint', 600, 'RACE', 1, 1) and goal
        finally:
            store.close()


def test_a_drain_keeps_the_journal_entries():
    entry = {'type': 'activity', 'title': 'The Kanto Marathon is on!'}
    store = SimpleNamespace(clock=None)
    assert progress_events.drain(store, [entry]) == [entry]


def test_a_checkpoint_row_comes_only_past_the_starting_line():
    assert progress_events.checkpoints(0, 1, 'race') == []
    assert [row['score'] for row in progress_events.checkpoints(1, 3, 'race')] == [1, 2]


@pytest.mark.parametrize(('gen1', 'gen2'), PAIRS)
def test_both_write_two_catch_rows_with_no_net_for_a_duplicate_catch(tmp_path, gen1, gen2):
    first, second = gen1_catches(tmp_path, gen1), gen2_catches(tmp_path, gen2)
    try:
        for store in (first, second):
            catches = rows(store, 'catch')
            assert [(kind, species, net) for kind, _, _, _, species, _, _, net in catches] == [('catch', 16, 0)] * 2
            # Two copies of one species keep apart by their trainer id or DVs.
            assert len({row[5] for row in catches}) == 2
    finally:
        first.close()
        second.close()


def test_both_count_a_catch_and_a_gift_as_no_net_progress(tmp_path):
    from pokesim import catches
    from pokesim.gen2 import tracking
    first, second = gen1_catches(tmp_path, 'red'), gen2_catches(tmp_path, 'gold')
    try:
        with first.lock, first.db:
            catches.record_gift(first.db, 7, sid(16))
        with second.lock, second.db:
            tracking.record_gift(second.db, 7, 16)
        for store in (first, second):
            found = rows(store, 'catch', 'receive')
            assert [row[0] for row in found].count('receive') == 1
            assert sum(row[-1] for row in found) == 0
    finally:
        first.close()
        second.close()


def test_a_journal_release_and_trade_write_their_rows(tmp_path):
    store = Store(tmp_path)
    store.clock = lambda: 42
    try:
        store.add_event(Event('release', 'Released Pidgey', species=16), SNAPSHOT, None, None)
        store.add_event(Event('trade', 'Traded Pidgey for Abra'), SNAPSHOT, None, None)
        store.add_event(Event('badge', 'Boulder Badge'), SNAPSHOT, None, None)
        assert [(kind, frame, species, net) for kind, frame, _, _, species, _, _, net in
                rows(store, 'release', 'receive', 'badge')] == [('release', 42, 16, 0), ('receive', 42, None, 0)]
    finally:
        store.close()


def test_a_cable_trade_row_takes_the_receiving_adventures_frame(tmp_path):
    from test_managed_participant import committed
    from pokesim.runtime.participant import _promote
    store = Store(tmp_path)
    try:
        # A restart promotes the commit before the emulator starts, so the saved clock gives the frame.
        store.set('play_clock', {'frames': 9000})
        _promote(store, committed(store))
        # A running adventure's live clock gives it, and a retried commit writes no second row.
        store.clock = lambda: 12000
        record = committed(store)
        _promote(store, record)
        _promote(store, record)
        assert [(kind, frame) for kind, frame, *_ in rows(store, 'receive')] == [('receive', 9000), ('receive', 12000)]
    finally:
        store.close()


def test_a_goal_row_comes_when_the_running_goal_changes(tmp_path):
    store = Store(tmp_path)
    try:
        watch = progress_events.GoalWatch()
        for key, tier in (('race', 'RACE'), ('race', 'RACE'), ('hunt:16', ''), (None, '')):
            watch.observe(store, key, tier)
        assert [(goal, tier) for _, _, goal, tier, *_ in rows(store, 'goal')] == [('race', 'RACE'), ('hunt:16', '')]
    finally:
        store.close()


def test_a_gen2_goal_key_names_the_activity_hunt_or_training():
    from pokesim.gen2.standdown import goal_key, hunt_key
    policy = SimpleNamespace(collection={'target': None})
    assert goal_key(policy) == (None, '')
    policy.collection['target'] = {'species': 16}
    assert goal_key(policy) == (hunt_key(16), '')
    policy.collection['postgame'] = {'activity': {'kind': 'marathon'}}
    assert goal_key(policy) == ('marathon', 'RACE')


def test_both_forget_the_rows_on_a_new_game(tmp_path):
    first, second = gen1_catches(tmp_path, 'red'), gen2_catches(tmp_path, 'gold')
    try:
        first.restart(1, {})
        second.restart(2, {})
        for store in (first, second):
            assert store.db.execute('SELECT COUNT(*) FROM progress_events').fetchone()[0] == 0
    finally:
        first.close()
        second.close()


def watched(tmp_path, at=42):
    """A store with a PlayClock frame and a running goal, as an emulator leaves it."""
    store = Store(tmp_path)
    store.clock = lambda: at
    store.goal_watch = progress_events.GoalWatch()
    return store


def counts(store):
    return [tuple(row) for row in store.db.execute('SELECT goal, hour, encounters, target, met_rule '
                                                   'FROM encounter_counts ORDER BY goal, hour')]


def test_gen1_journal_entries_say_which_progress_they_are():
    from pokesim.events import RunMemory, diff
    from pokesim.ram import PartyMon
    from test_events import snap
    memory = RunMemory(seen_maps={1})
    before = snap(in_battle=1, enemy_species=0x54, enemy_level=3)
    caught = snap(in_battle=1, enemy_species=0x54, enemy_level=3, owned=frozenset({1, 25}), seen=frozenset({1, 25}),
                  party=before.party + (PartyMon(0x54, 10, 10, 3, 'PIKACHU'),))
    [catch] = [event for event in diff(before, caught, memory) if event.type == 'catch']
    assert (catch.progress, catch.species) == ('dex', 25)
    # An evolution into a new species is a new entry. One into a species already owned is not.
    bulbasaur, ivysaur = PartyMon(0x99, 30, 30, 16, 'BULBASAUR'), PartyMon(0x09, 35, 35, 16, 'BULBASAUR')
    [new] = diff(snap(party=(bulbasaur,)), snap(party=(ivysaur,), owned=frozenset({1, 2})), memory)
    [old] = diff(snap(party=(bulbasaur,), owned=frozenset({1, 2})), snap(party=(ivysaur,), owned=frozenset({1, 2})),
                 memory)
    assert (new.type, new.progress, new.species) == ('evolve', 'dex', 2) and (old.type, old.progress) == ('evolve', '')
    [gift] = diff(snap(), snap(owned=frozenset({1, 25})), memory)
    assert (gift.type, gift.progress, gift.species) == ('obtain', 'dex', 25)
    [badge] = diff(snap(), snap(badges=1), memory)
    [area] = diff(snap(), snap(map=2), memory)
    [league] = diff(snap(map=2), snap(map=118), memory)
    [bicycle] = [event for event in diff(snap(), snap(items=((0x06, 1),)), memory) if event.type == 'item']
    assert [(event.type, event.progress) for event in (badge, area, league)] == [
        ('badge', 'badge'), ('map', 'area'), ('champion', 'league')]
    assert (bicycle.progress, bicycle.needed) == ('item', True)


def test_a_gen1_ground_pickup_is_an_item_row_that_was_not_needed():
    from dataclasses import replace

    from pokesim.events import RunMemory, diff
    from pokesim.strategy_data import ITEMS, WORLD
    from test_pickups import cave, hidden
    before = cave()
    index = next(i for i, obj in enumerate(WORLD[before.map]['objects']) if obj[4].endswith('FULL_HEAL'))
    after = replace(hidden(before, index), items=before.items + ((ITEMS['FULL_HEAL'], 1),))
    [pickup] = [event for event in diff(before, after, RunMemory(seen_maps={before.map})) if event.type == 'item']
    assert (pickup.progress, pickup.needed) == ('item', False)


def test_gen2_journal_entries_say_which_progress_they_are():
    from pokesim.gen2.emulator import Event as Entry
    from test_gen2_journal import DATA, run, snap
    for dex, before in ((16, snap()), (245, snap(in_battle=1, enemy_level=40))):
        event = journal_catch(DATA, dex, before, Entry)
        assert (event.progress, event.species) == ('dex', dex)
    events = run(snap(), snap(pockets={'key': ((7, 1),), 'machines': ((201, 1),)}))
    assert [(event.progress, event.needed) for event in events] == [('item', True)] * 2


def journal_catch(data, dex, before, event):
    from pokesim.gen2 import journal
    return journal.catch(data, dex, before, before, event)


def test_a_tagged_entry_writes_its_row_under_the_running_goal(tmp_path):
    from pokesim.gen2.emulator import Event as Entry
    store = watched(tmp_path)
    try:
        store.goal_watch.observe(store, 'hunt:16')
        store.add_event(Event('badge', 'Boulder Badge', progress='badge'), SNAPSHOT, None, None)
        store.add_event(Event('item', 'Picked up Potion', progress='item', needed=False), SNAPSHOT, None, None)
        store.add_event(Entry('catch', 'Pidgey joined the Pokédex', progress='dex', species=16), SNAPSHOT, None, None)
        store.add_event(Entry('item', 'Got the HM01', progress='item', needed=True), SNAPSHOT, None, None)
        assert [(kind, frame, goal, species, net) for kind, frame, goal, _, species, _, _, net in
                rows(store, 'badge', 'item', 'dex')] == [
            ('badge', 42, 'hunt:16', None, 1), ('item', 42, 'hunt:16', None, 0), ('dex', 42, 'hunt:16', 16, 1),
            ('item', 42, 'hunt:16', None, 1)]
    finally:
        store.close()


def test_story_flags_write_an_event_row_only_for_a_flag_this_run_has_not_seen(tmp_path):
    store = watched(tmp_path)
    watch = store.goal_watch
    try:
        watch.observe(store, 'marathon', 'RACE')
        # The first reading takes the flags already set, and an empty one is no reading.
        for flags in (b'', b'\x01\x00', b'\x01\x00', b'\x03\x00', b'\x01\x00', b'\x03\x00', b'\x03\x80'):
            watch.story(store, flags)
        assert [(goal, tier, score, net) for _, _, goal, tier, _, _, score, net in rows(store, 'event')] == [
            ('marathon', 'RACE', 2, 1), ('marathon', 'RACE', 3, 1)]
        watch.restart()
        watch.story(store, b'\x07\x80')
        assert len(rows(store, 'event')) == 2
    finally:
        store.close()


def test_a_league_win_a_reload_took_back_is_no_event_after_the_worker_starts_again(tmp_path):
    """A Gold League run restarted from its entry save, and the worker started again before the
    replay. The Elite Four flags it set again wrote net rows each time. Only a flag never seen counts."""
    store = watched(tmp_path)
    try:
        watch = store.goal_watch
        watch.observe(store, 'funds_will', 'UPKEEP')
        watch.story(store, b'\x01\x00')
        watch.story(store, b'\x07\x00')     # Will and Koga beaten
        assert len(rows(store, 'event')) == 1
        # The reload clears the two wins and a new worker reads the store again.
        watch = store.goal_watch = progress_events.GoalWatch()
        watch.observe(store, 'funds_will', 'UPKEEP')
        for flags in (b'\x01\x00', b'\x03\x00', b'\x07\x00'):
            watch.story(store, flags)
        assert len(rows(store, 'event')) == 1
        watch.story(store, b'\x0f\x00')     # Bruno, never beaten before
        assert [score for *_, score, net in rows(store, 'event')] == [3, 4]
        # A new game starts with no flags seen, and its rows start empty.
        store.restart(2, {})
        assert progress_events.stored_flags(store) == b''
        watch.restart()
        watch.story(store, b'\x01\x00')
        watch.story(store, b'\x03\x00')
        assert [score for *_, score, net in rows(store, 'event')] == [2]
    finally:
        store.close()


def test_wild_encounters_count_per_goal_and_game_hour(tmp_path, caplog):
    at = [10]
    store = Store(tmp_path)
    store.clock = lambda: at[0]
    watch = store.goal_watch = progress_events.GoalWatch()
    try:
        progress_events.encounter(store, 16, b'\x00\x00')
        watch.observe(store, 'hunt:16', hunt=(16, lambda raw: raw[0] > 0))
        for species, raw in ((16, b'\x10\x00'), (16, b'\x00\x00'), (19, b'\x10\x00')):
            progress_events.encounter(store, species, raw)
        at[0] = progress_events.HOUR + 5
        progress_events.encounter(store, 16, b'\x10\x00')
        watch.observe(store, 'hunt:16', hunt=(16, lambda raw: 1 / 0))
        # A rule that fails counts the encounter as not met and the game goes on.
        with caplog.at_level('ERROR', logger='pokesim.progress_events'):
            progress_events.encounter(store, 16, b'\x10\x00')
            watch.observe(store, 'shiny', hunt=(None, None))
        progress_events.encounter(store, 19, b'\x00\x00')
        watch.flush(store)
        assert counts(store) == [('', 0, 1, 0, 0), ('hunt:16', 0, 3, 2, 1), ('hunt:16', 1, 2, 2, 1),
                                 ('shiny', 1, 1, 1, 1)]
        assert any('hunt rule failed' in record.getMessage() for record in caplog.records)
        # Without a PlayClock, as for a page or a trade worker, nothing is counted.
        store.clock = None
        progress_events.encounter(store, 16, b'\x10\x00')
        assert watch.pending == []
    finally:
        store.close()


def test_the_gen1_wild_battle_hook_counts_every_wild_encounter(tmp_path):
    from pokesim.shiny import ShinyTracker
    store = watched(tmp_path)
    try:
        tracker = ShinyTracker(store, 'ea9bcae617fdf159b045185467ae58b2e4a48b9a')
        memory = bytearray(65536)
        memory[0xcfe5], memory[0xcff1:0xcff3], memory[0xd057] = 0x99, b'\x22\x22', 2
        tracker.encounter(SimpleNamespace(memory=memory))
        memory[0xd057] = 1
        tracker.encounter(SimpleNamespace(memory=memory))
        assert [(species, dvs) for *_, species, dvs in store.goal_watch.pending] == [(1, b'\x22\x22')]
    finally:
        store.close()


def test_a_reload_writes_a_plan_row_that_names_its_reason(tmp_path):
    store = watched(tmp_path, at=7)
    try:
        store.goal_watch.observe(store, 'hunt:16')
        progress_events.reload(store, 'battle cannot end')
        assert [tuple(row) for row in rows(store, 'plan')] == [
            ('plan', 7, 'hunt:16', '', None, 'reload:battle cannot end', None, 0)]
    finally:
        store.close()
    # A store that cannot write costs the run nothing.
    progress_events.reload(SimpleNamespace(), 'stuck')


def test_both_reloads_write_the_reload_row(tmp_path, monkeypatch):
    from pokesim import emulator
    from pokesim.checkpoints import CheckpointStore
    from pokesim.gen2.emulator import Emulator as Gen2
    from pokesim.play_clock import PlayClock
    from pokesim.runtime.supervision import Supervisor
    reasons = []
    monkeypatch.setattr(progress_events, 'reload', lambda store, why: reasons.append(why))
    store = CheckpointStore(tmp_path)
    store.write_checkpoint(b'recent', {'policy_state': {}, 'run_memory': {}})
    game = SimpleNamespace(store=SimpleNamespace(autosaves=store.autosaves, state_path=store.state_path,
                                                 checkpoint_metadata=store.checkpoint_metadata),
                           snapshot=SimpleNamespace(map=emulator.MAPS['ROUTE_1']), reloads=0, frame=10 ** 6,
                           play_clock=PlayClock(), adventure_seed=7, supervisor=Supervisor(),
                           _restore_first_valid=lambda paths: None, _tick=lambda n: None,
                           _behind_barrier=lambda metadata: False)
    emulator.Emulator._unstick(game, game.frame, 'battle cannot end')
    gen2 = SimpleNamespace(supervisor=Supervisor(), snapshot=SimpleNamespace(valid=True, started=True, map_name='Route 29'),
                           store=SimpleNamespace(autosaves=lambda: []), play_clock=PlayClock(), adventure_seed=7,
                           policy=SimpleNamespace(recoveries=4, menu=None, on_restore=lambda: None, collection={},
                                                  goal=None, decisions=0, in_league=lambda snapshot: False),
                           reloads=0, last_reload=0, audio=SimpleNamespace(clear=lambda: None),
                           statistics=SimpleNamespace(previous=None), options_applied=True, _tick=lambda n: None,
                           _reset_watch=lambda: None, _boot=lambda **_: SimpleNamespace(), _sync_clock=lambda: None,
                           pb=SimpleNamespace(stop=lambda save: None), _event=lambda event, snapshot: None)
    Gen2._unstick(gen2, 0.0, 'stuck')
    assert reasons == ['battle cannot end', 'stuck']


def test_the_hunt_helpers_name_the_target_and_rule():
    from pokesim.gen2.standdown import hunt
    from pokesim.policies.collection import Collection
    from test_duplicates import snapshot, stored
    policy = SimpleNamespace(collection={'target': None})
    assert hunt(policy, None) is None
    policy.collection['target'] = {'species': 16}
    assert hunt(policy, None) == (16, None)
    policy.collection['postgame'] = {'activity': {'kind': 'shiny'}}
    species, rule = hunt(policy, None)
    assert species is None and rule(b'\x2a\xaa') and not rule(b'\x22\x22')
    policy.collection['postgame'] = {'activity': {'kind': 'marathon'}}
    assert hunt(policy, None) is None
    collection = Collection()
    assert collection.hunt(None) is None
    collection.project = {'method': 'gift', 'species': sid(133)}
    assert collection.hunt(None) is None
    collection.project = {'method': 'grass', 'species': sid(16)}
    assert collection.hunt(None) == (16, None)
    # A DV hunt's rule is the catch rule: a shiny is kept, a copy as plain as the one held is not.
    collection.project = {'method': 'grass', 'species': 0x99, 'dv_hunt': True}
    species, rule = collection.hunt(snapshot([stored(0, dvs=(0, 8, 8, 8, 8))]))
    assert species == 1 and rule(b'\x2a\xaa') and not rule(b'\x22\x22')


@pytest.mark.parametrize(('gen1', 'gen2'), PAIRS)
def test_both_write_one_improve_row_for_a_copy_the_worth_oracle_kept_better(tmp_path, gen1, gen2, monkeypatch):
    """A catch the worth oracle kept for an improve reason writes one net ``improve`` row under the goal
    that asked, and a plain catch or a new entry writes none (its dex row is the progress)."""
    from pokesim.catches import CatchTracker
    from pokesim.gen2 import activity
    from pokecore.gen2.ram import Memory
    from pokesim.gen2.postgame import wild_dvs as gen2_dvs
    from pokesim.gen2.tracking import Tracker
    from pokesim.pcvalue import FAMILY, Worth
    from pokesim.policies.collection import wild_dvs as gen1_dvs
    from test_behavior_parity import GEN1_ROMS, replace_game
    from test_gen2_activity import Emulator, fake_data

    def watching(store):
        store.clock = lambda: 7
        store.goal_watch = progress_events.GoalWatch()
        store.goal_watch.key, store.goal_watch.tier = 'hunt:16', 'PROGRESS'
        return store

    first = watching(Store(tmp_path / 'gen1'))
    tracker = CatchTracker(first, GEN1_ROMS[gen1], fresh=True)
    raw = (0x9a, 0xbc)
    first.goal_watch.expect(16, gen1_dvs(raw), Worth(True, 'Rarer'))
    first.goal_watch.expect(19, gen1_dvs(raw), Worth(True, 'New entry'))
    for trainer, species in ((1, 16), (2, 16), (3, 19)):
        memory = bytearray(0x10000)
        memory[0xd11c], memory[0xd057] = sid(species), 1
        memory[0xd359:0xd35b] = trainer.to_bytes(2, 'big')
        memory[0xcff1:0xcff3] = bytes(raw)
        tracker.completed(SimpleNamespace(memory=memory))

    second = watching(Store(tmp_path / 'gen2'))
    data = replace_game(fake_data(), gen2)
    activity.start(second, fresh=True)
    gen2_tracker = Tracker(second, data, fresh=True)
    # A repeat of the exact same capture is not counted twice, so each catch differs in its DVs.
    for dvs, noted in (((0x9a, 0xbc), True), ((0x9a, 0xbd), False), ((0x22, 0x22), False)):
        pb = Emulator()
        for name, value in (('wWildMon', 16), ('wBattleMode', 1), ('wBattleType', 0)):
            pb.memory.put(name, value)
        pb.memory.put('wEnemyMonDVs', *dvs)
        if noted:
            # Both rules key a copy by the two DV bytes the cartridge holds, from the five DVs worth reads.
            second.goal_watch.expect(16, gen2_dvs(Memory(pb.memory, data).read('wEnemyMonDVs', 2)), Worth(True, FAMILY))
        gen2_tracker.captured(pb)
    try:
        for store in (first, second):
            assert [(kind, frame, goal, tier, species, net) for kind, frame, goal, tier, species, _, _, net
                    in rows(store, 'improve')] == [('improve', 7, 'hunt:16', 'PROGRESS', 16, 1)]
            assert len(rows(store, 'catch')) == 3 and store.goal_watch.expected == {}
    finally:
        first.close()
        second.close()


MON = progress_events.identity(4321, bytes((0x9a, 0xbc)), 157)


def gain(store, level, mon=MON):
    """A level gain's journal entry, as both emulators write it, and the row it left."""
    store.add_event(Event('level', f'TYPHLOSION grew to level {level}', species=157, identity=mon, score=level),
                    SNAPSHOT, None, None)
    return tuple(rows(store, 'level', 'improve')[-1])


def test_a_level_gain_toward_the_readiness_target_is_an_improve_row(tmp_path, caplog):
    store = watched(tmp_path)
    store.goal_watch.readiness = lambda snapshot: 23
    try:
        assert gain(store, 12) == ('improve', 42, '', '', 157, MON, 12, 1)
        # A level counts once for each Pokémon, so a reload that gains it again writes a plain level row.
        assert [gain(store, level)[0] for level in (12, 13)] == ['level', 'improve']
        assert gain(store, 12, progress_events.identity(4321, bytes((0x11, 0x11)), 157))[0] == 'improve'
        # Past the target, or under the best level the Pokémon already reached, a gain is no progress.
        assert [gain(store, level)[0] for level in (24, 23)] == ['level', 'level']
        # With no next boss, or a hook that fails, the gain still writes its entry and a level row.
        store.goal_watch.readiness = lambda snapshot: None
        assert gain(store, 25)[0] == 'level'
        store.goal_watch.readiness = lambda snapshot: 1 / 0
        assert gain(store, 26)[0] == 'level' and 'Cannot read the readiness target' in caplog.text
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE type = 'level'").fetchone()[0] == 8
    finally:
        store.close()


def test_a_gen1_level_gain_names_the_pokemon_and_its_new_level():
    from dataclasses import replace
    from pokesim.events import RunMemory, diff
    from pokesim.ram import PartyMon
    from test_events import snap
    before = PartyMon(0x99, 20, 20, 5, 'BULBASAUR', dvs=(10, 9, 10, 11, 12), trainer_id=4321)
    grew = [event for event in diff(snap(party=(before,)), snap(party=(replace(before, level=6),)),
                                    RunMemory(seen_maps={1})) if event.type == 'level']
    assert [(event.species, event.identity, event.score) for event in grew] == [
        (1, progress_events.identity(4321, bytes((0x9a, 0xbc)), 1), 6)]


# Silver's League loop from the a7a83b0 soak, by play time: the rooms entered for the first time, the
# ace's level gains and the blackouts, with the room each happened in. The live StallWatch raised it at
# the blackout at 25:15:14, 133 game minutes after the first one.
LANCE_LOOP = (
    ('22:54:46', 'map', "Karen's Room", None), ('22:56:33', 'level', "Karen's Room", 66),
    ('22:58:42', 'map', "Lance's Room", None), ('23:02:12', 'blackout', "Lance's Room", None),
    ('23:07:40', 'level', "Koga's Room", 67), ('23:14:43', 'level', "Karen's Room", 68),
    ('23:21:50', 'blackout', "Lance's Room", None), ('23:25:33', 'level', "Will's Room", 69),
    ('23:35:14', 'blackout', "Bruno's Room", None), ('23:37:17', 'level', "Will's Room", 70),
    ('23:45:24', 'level', "Bruno's Room", 71), ('23:55:12', 'blackout', "Lance's Room", None),
    ('23:57:51', 'level', "Will's Room", 72), ('24:06:00', 'level', "Bruno's Room", 73),
    ('24:14:01', 'blackout', "Lance's Room", None), ('24:19:26', 'level', "Koga's Room", 74),
    ('24:27:43', 'level', "Karen's Room", 75), ('24:38:08', 'blackout', "Lance's Room", None),
    ('24:56:53', 'level', "Will's Room", 76), ('25:06:12', 'level', "Karen's Room", 77),
    ('25:15:14', 'blackout', "Lance's Room", None), ('25:19:52', 'level', "Koga's Room", 78),
    ('25:28:55', 'level', "Karen's Room", 79), ('25:38:40', 'blackout', "Lance's Room", None))


def lance_loop(tmp_path, aim):
    """The new model's flags on the loop with the writer's rows when the readiness target is ``aim``,
    as game minutes after the first blackout."""
    from pokesim.replay.progress import Adventure, Axis, Entry, Row, replay
    from pokesim.stalls import FRAMES_PER_GAME_MINUTE
    store = watched(tmp_path / str(aim))
    store.goal_watch.readiness = lambda snapshot: aim
    start, entries, found = 1_700_000_000, [], []
    try:
        for i, (played, kind, room, level) in enumerate(LANCE_LOOP, 1):
            hours, minutes, seconds = map(int, played.split(':'))
            at = (hours * 60 + minutes) * 60 + seconds
            ts, frame = start + at, at * 60
            title = {'map': f'Arrived at {room}', 'level': f'TYPHLOSION grew to level {level}',
                     'blackout': 'Blacked out!'}[kind]
            entries.append(Entry(i, ts, kind, title, '', room, played))
            if kind == 'map':
                found.append(Row(ts, frame, 'area', 1))
            elif kind == 'level':
                store.clock = lambda frame=frame: frame
                row = gain(store, level)
                found.append(Row(ts, frame, row[0], row[-1]))
    finally:
        store.close()
    axis = Axis([(entry.ts, (entry.ts - start) * 60) for entry in entries], 'playtime')
    _, flags, _ = replay(Adventure('silver', 'silver', entries, [], [], [], [], []), axis, found,
                         entries[0].ts, entries[-1].ts)
    first = axis(next(entry.ts for entry in entries if entry.type == 'blackout'))
    return [(flag.check, round((flag.frame - first) / FRAMES_PER_GAME_MINUTE, 1)) for flag in flags]


def test_a_loop_of_league_losses_is_still_caught_with_level_gains_counted(tmp_path):
    # Every gain is over Lance's Lv 50 ace, the League's target, so none counts and the loop is caught
    # as before: the watchdog an hour after the last new room and StallWatch two game hours after
    # Lance's room, both before the live StallWatch at 133 minutes.
    assert lance_loop(tmp_path, 50) == [('watchdog', 93.6), ('stallwatch', 116.6)]
    # A target over every gain would hide the loop. The rule caps a loop at the levels left to the
    # target, so with a target of 70 the loop goes quiet after Lv 70 and is caught two game hours on.
    assert lance_loop(tmp_path, 99) == []
    assert lance_loop(tmp_path, 70) == [('watchdog', 145.6), ('stallwatch', 155.6)]
