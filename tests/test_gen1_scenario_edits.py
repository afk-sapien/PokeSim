"""Red, Blue and Yellow scenario edits that move the story on or reopen a Pokédex entry, and the
planner marks a scenario can wait for, on synthetic memory."""
from types import SimpleNamespace

import pytest

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


def test_a_scenario_names_the_legendaries_that_came_back(tmp_path, monkeypatch):
    # The returns sit in the adventure's claims ledger, not in the save. A Red trip back to Zapdos
    # replayed without them ended at once and never reached the Fuchsia Mart loop it stalled in.
    import hashlib
    import json
    from pokesim import scenarios
    checkpoint = tmp_path / 'start.state'
    checkpoint.with_suffix('.json').write_text(json.dumps({'rom_sha1': hashlib.sha1(b'red').hexdigest()}))
    (tmp_path / 'red.gb').write_bytes(b'red')
    booted = SimpleNamespace(pb=SimpleNamespace(memory=cartridge()), policy=SimpleNamespace(collection=SimpleNamespace()))
    monkeypatch.setattr(scenarios, 'HeadlessRun', lambda *args, **kwargs: booted)
    scenario = Scenario(folder=tmp_path, name='zapdos', checkpoint=checkpoint, edits={'returned': [144, 145]})
    run, _ = scenarios.open_run(scenario, tmp_path / 'red.gb')
    assert run.policy.collection.returned_legendaries == {144, 145}


def species(dex):
    from pokesim.strategy_data import SPECIES
    return next(sid for sid, row in SPECIES.items() if row.get('dex') == dex)


def held(*party, boxed=()):
    """A snapshot holding these Pokédex numbers in the party and the boxes."""
    return SimpleNamespace(valid=True, started=True, owned=frozenset(), items=(), event_flags=bytes(320),
                           party=[SimpleNamespace(species=species(dex)) for dex in party],
                           stored_pokemon=[(1, species(dex), 5, 'MON') for dex in boxed], boxed_pokemon=[])


def store_watch(events=None, demand=None):
    collection = SimpleNamespace(returned_events=events or {}, demand=lambda: demand or {})
    run = SimpleNamespace(policy=SimpleNamespace(collection=collection), pb=SimpleNamespace(memory=bytearray(0x10000)))
    watch = Gen1Watch(run)
    return lambda snapshot: [(kind, detail) for kind, detail, _ in watch.marks(snapshot)], run.pb.memory


def set_flag(memory, name):
    from pokesim.step_events import flag
    base, index = flag(name)
    memory[base + index // 8] |= 1 << index % 8


def test_a_returned_events_edit_names_the_rows_a_live_run_reads_from_its_ledger():
    from pokesim.scenarios import gen1_returned_events, returned_activities
    rows = gen1_returned_events({'dojo': 107, 'fossil': 'amber', 'eevee': True})
    assert rows['dojo']['dex'] == 107 and rows['dojo']['item'] is None
    assert (rows['fossil']['dex'], rows['fossil']['item']) == (142, 'OLD_AMBER') and rows['eevee']['dex'] == 133
    specs = returned_activities(rows)
    assert (specs['dojo'].dex, specs['fossil'].dex, specs['eevee'].dex) == (107, 142, 133)


@pytest.mark.parametrize('wanted', [{'dojo': 25}, {'dojo': True}, {'dojo': '106'}, {'fossil': 'claw'},
                                    {'eevee': 1}, {'mewtwo': True}])
def test_a_malformed_returned_events_edit_is_refused(wanted):
    from pokesim.scenarios import gen1_returned_events
    with pytest.raises(ValueError, match='returned_events'):
        gen1_returned_events(wanted)


@pytest.mark.parametrize('wanted', [{'0': 1}, {'152': 1}, {'raichu': 1}, {'26': 0}, {'26': True}, {'26': 1.5}])
def test_a_malformed_peer_demand_edit_is_refused(wanted):
    from pokesim.scenarios import gen1_demand
    assert gen1_demand({'26': 2, 143: 1}) == {26: 2, 143: 1}
    with pytest.raises(ValueError, match='peer_demand'):
        gen1_demand(wanted)


def test_a_returned_dojo_visit_counts_only_the_gift_it_offers_once_taken():
    # A dojo return replayed without its ledger row passed on routine play and never showed the visit.
    from pokesim.scenarios import gen1_returned_events
    marks, memory = store_watch(gen1_returned_events({'dojo': 107}))
    assert marks(held(25)) == []                                   # the first look sets the count
    assert marks(held(25, 107)) == [] and marks(held(25, 107)) == []  # no gift flag set yet
    set_flag(memory, 'EVENT_GOT_HITMONCHAN')
    assert marks(held(25, 107)) == []                               # one look could be half-written RAM
    assert marks(held(25, 107)) == [('event_return', 'dojo')]
    assert marks(held(25, 107)) == []
    assert matches('event_return:dojo', 'event_return', 'dojo')
    marks, memory = store_watch(gen1_returned_events({'dojo': 107}))
    set_flag(memory, 'EVENT_GOT_HITMONLEE')
    assert marks(held(25)) == [] and marks(held(25, 106)) == [] and marks(held(25, 106)) == []


def test_one_more_copy_another_adventure_asked_for_counts_once_it_holds():
    marks, _ = store_watch(demand={26: 1})
    assert marks(held(26)) == []
    assert marks(held(26, boxed=(26,))) == [] and marks(held(26)) == []  # a rise for one look is not one
    assert marks(held(26, boxed=(26,))) == []
    assert marks(held(26, boxed=(26,))) == [('demand', '26')]
    assert marks(held(26, boxed=(26,))) == []
    assert store_watch()[0](held(26)) == []                         # nothing asked, nothing marked


def test_a_scenario_hands_the_run_its_returned_events_and_the_demand_for_the_whole_replay(tmp_path, monkeypatch):
    import hashlib
    import json
    import math
    from pokesim import scenarios
    from pokesim.policies.collection import Collection
    checkpoint = tmp_path / 'start.state'
    checkpoint.with_suffix('.json').write_text(json.dumps({'rom_sha1': hashlib.sha1(b'red').hexdigest()}))
    (tmp_path / 'red.gb').write_bytes(b'red')
    booted = SimpleNamespace(pb=SimpleNamespace(memory=cartridge()), policy=SimpleNamespace(collection=Collection()))
    monkeypatch.setattr(scenarios, 'HeadlessRun', lambda *args, **kwargs: booted)
    edits = {'returned_events': {'dojo': 106}, 'peer_demand': {'26': 1}}
    run, _ = scenarios.open_run(Scenario(folder=tmp_path, name='dojo', checkpoint=checkpoint, edits=edits),
                                tmp_path / 'red.gb')
    collection = run.policy.collection
    assert collection.returned_events['dojo']['dex'] == 106
    collection.clock = 10 ** 9
    assert collection.demand() == {26: 1} and collection.demand_until == math.inf

    def boot(*args, **kwargs):
        raise AssertionError('a malformed edit boots nothing')
    monkeypatch.setattr(scenarios, 'HeadlessRun', boot)
    with pytest.raises(ValueError, match='returned_events'):
        scenarios.open_run(Scenario(folder=tmp_path, name='dojo', checkpoint=checkpoint,
                                    edits={'returned_events': {'dojo': 25}}), tmp_path / 'red.gb')


def test_a_scenario_can_require_run_attempts(tmp_path):
    (tmp_path / 'scenario.json').write_text('{"until": "owned:77", "min_flees": 2}', encoding='utf-8')
    scenario = Scenario.load(tmp_path)
    assert (scenario.until, scenario.min_flees) == ('owned:77', 2)
    (tmp_path / 'scenario.json').write_text('{}', encoding='utf-8')
    assert Scenario.load(tmp_path).min_flees == 0
