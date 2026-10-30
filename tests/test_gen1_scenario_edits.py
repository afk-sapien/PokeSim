"""Red, Blue and Yellow scenario edits that move the story on or reopen a Pokédex entry, and the
planner marks a scenario can wait for, on synthetic memory."""
from types import SimpleNamespace

from pokesim.events import RunMemory
from pokesim.planning.monitor import STOOD_DOWN, Monitor
from pokesim.ram import read_snapshot
from pokesim.scenarios import Gen1Watch, Scenario, apply_edits, matches
from pokesim.strategy_data import event_set

from test_scenarios import cartridge


def test_unowned_badges_and_events_reach_the_snapshot_the_policy_reads():
    mem = cartridge()
    apply_edits(mem, {'unowned': [], 'badges': 0})
    assert not read_snapshot(mem, 0).owned and read_snapshot(mem, 0).badges == 0
    from pokesim.ram import W_DEX_OWNED, W_DEX_SEEN
    for flags in (W_DEX_OWNED, W_DEX_SEEN):
        mem[flags:flags + 19] = bytes([0xFF] * 18 + [0x7F])
    apply_edits(mem, {'unowned': [1, 46, 151], 'badges': 2, 'events': ['EVENT_BEAT_CERULEAN_ROCKET_THIEF']})
    snapshot = read_snapshot(mem, 0)
    assert len(snapshot.owned) == 148 and not {1, 46, 151} & snapshot.owned and {2, 45, 47, 150} <= snapshot.owned
    assert snapshot.badges == 0b11
    assert event_set(snapshot.event_flags, 'EVENT_BEAT_CERULEAN_ROCKET_THIEF')
    apply_edits(mem, {'badges': 8})
    assert read_snapshot(mem, 0).badges == 0xFF


def watch_with(table):
    monitor = Monitor({STOOD_DOWN: table})
    run = SimpleNamespace(policy=SimpleNamespace(collection=SimpleNamespace(director=SimpleNamespace(monitor=monitor))))
    return Gen1Watch(run)


def test_a_pokedex_entry_counts_once_it_holds_for_two_snapshots():
    watch = watch_with({})
    seen = lambda owned: watch.marks(SimpleNamespace(valid=True, started=True, owned=frozenset(owned)))
    assert seen({1}) == [] and seen({1, 77}) == []                 # one frame could be half-written RAM
    assert [(kind, detail) for kind, detail, _ in seen({1, 77})] == [('owned', '77')]
    assert seen({1, 77}) == [] and seen({1}) == [] and seen({1, 77}) == []
    assert matches('owned:77', 'owned', '77') and not matches('owned:46', 'owned', '77')


def test_the_same_goal_standing_down_four_times_in_a_row_is_a_loop():
    table = {}
    watch = watch_with(table)
    for when in range(1, 5):
        table['catch_cut'] = when
        assert [(kind, detail) for kind, detail, _ in watch.marks()] == [('stand_down', 'catch_cut')]
        assert (watch.loop is None) == (when <= 3)
    watch = watch_with(table)
    for when, key in enumerate(['catch_cut', 'heal', 'catch_cut', 'heal', 'catch_cut'], start=10):
        table[key] = when
        watch.marks()
    assert watch.loop is None                                      # taking turns is not a retry loop


def test_a_kanto_marathon_checkpoint_restarts_the_quiet_clock():
    collection = SimpleNamespace(project={'method': 'marathon', 'checkpoint': 3})
    watch = Gen1Watch(SimpleNamespace(memory=RunMemory(), policy=SimpleNamespace(collection=collection)))
    snapshot = read_snapshot(cartridge(), 0)
    assert watch.observe(snapshot)[1] is False                      # the first look only sets the mark
    assert watch.observe(snapshot)[1] is False
    collection.project['checkpoint'] = 4
    assert watch.observe(snapshot)[1] is True
    assert watch.observe(snapshot)[1] is False
    collection.project = {'method': 'gift', 'checkpoint': 9}
    assert watch.observe(snapshot)[1] is False                      # only a race has checkpoints


def test_a_scenario_can_require_run_attempts(tmp_path):
    (tmp_path / 'scenario.json').write_text('{"until": "owned:77", "min_flees": 2}', encoding='utf-8')
    scenario = Scenario.load(tmp_path)
    assert (scenario.until, scenario.min_flees) == ('owned:77', 2)
    (tmp_path / 'scenario.json').write_text('{}', encoding='utf-8')
    assert Scenario.load(tmp_path).min_flees == 0
