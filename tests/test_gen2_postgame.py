"""A finished Gen II run keeps playing the way Red, Blue and Yellow do, with a shiny search as filler."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData

ORDINARY = (0, 8, 8, 8, 8)
PERFECT = (15,) * 5


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def mon(species, *, box=0, position=0, level=30, dvs=ORDINARY, **extra):
    fields = dict(species=species, name=str(species), gender='Male', egg=False, box=box, position=position, trainer_id=4321,
                  dvs=dvs, moves=(33, 0, 0, 0), pp=(35, 0, 0, 0), level=level, friendship=70, held_item=0,
                  experience=30000, stat_exp=(0,) * 5, shiny=False)
    fields.update(extra)
    return SimpleNamespace(**fields)


def lead():
    return mon(157, box=None, dvs=PERFECT, moves=(57, 15, 53, 0), level=100, trainer_id=1)


def snapshot(party, stored=()):
    return SimpleNamespace(frame=60000, party=tuple(party), stored=tuple(stored), daycare=(None, None), owned=set(range(1, 252)),
                           box_counts=(5,) * 14, active_box=0, map=1, x=1, y=1, items=(), can_catch=True,
                           hall_of_fame_count=3, pockets={'balls': [(5, 20)]}, event=lambda name: True)


def clock():
    return SimpleNamespace(byte=lambda name: {'wTimeOfDay': 1}.get(name, 0), memory=None)


def expedition(data, decisions=1000):
    return SimpleNamespace(data=data, collection={}, demand={}, decisions=decisions, completed={'champion': 1},
                           returned=set(), no_room=lambda snapshot: False, memory=None, goal=None)


def row(mid, species=16, method='grass'):
    return {'map': mid, 'method': method, 'species': species, 'time': 'any', 'chance': 30}


def test_training_takes_the_best_copy_ten_levels_at_a_time(data, monkeypatch):
    from pokesim.gen2 import postgame
    monkeypatch.setattr(postgame, 'huntable', lambda *args: {16: [row(5)]})
    policy = expedition(data)
    best = mon(16, position=0, level=34, dvs=PERFECT)
    state = snapshot([lead()], [best, mon(16, position=1, level=50)])
    assert postgame.trainee(policy, state) == {'kind': 'train', 'identity': [4321, list(PERFECT)], 'species': 16,
                                               'level_goal': 40}
    # A level 100 copy about as strong leaves nothing to gain from training this species.
    done = mon(16, position=2, level=100, dvs=PERFECT, trainer_id=99)
    assert postgame.trainee(policy, snapshot([lead()], [best, done])) is None


def test_ordinary_copies_wait_for_their_better_dv_hunts(data, monkeypatch):
    from pokesim.gen2 import postgame
    monkeypatch.setattr(postgame, 'huntable', lambda *args: {16: [row(5)]})
    policy = expedition(data)
    state = snapshot([lead()], [mon(16, level=50)])
    assert postgame.trainee(policy, state) is None
    # Once the hunts for it are spent, the best copy found is trained.
    postgame.state(policy)['searches']['16'] = postgame.SEARCH_BUDGET
    assert postgame.trainee(policy, state)['level_goal'] == 60


def test_a_better_dv_hunt_picks_the_most_ordinary_best_copy(data, monkeypatch):
    from pokesim.gen2 import postgame
    monkeypatch.setattr(postgame, 'huntable', lambda *args: {16: [row(5)], 19: [row(6, 19)]})
    monkeypatch.setattr(postgame, 'reachable', lambda policy, snapshot, rows: rows[0])
    policy = expedition(data)
    state = snapshot([lead()], [mon(16), mon(19, position=1, dvs=PERFECT)])
    hunt = postgame.quality(policy, state, 'day')
    assert hunt['kind'] == 'quality' and hunt['species'] == 16 and hunt['row']['map'] == 5
    # A species still missing from the Pokédex is collection work, never a postgame hunt.
    state.owned = state.owned - {16}
    assert postgame.quality(policy, state, 'day') is None


def test_a_rare_species_is_hunted_only_while_its_next_catch_pays(data, monkeypatch):
    from pokesim.gen2 import postgame
    rare, common = dict(row(5, 16), chance=5), dict(row(6, 19), chance=30)
    monkeypatch.setattr(postgame, 'huntable', lambda *args: {16: [rare], 19: [common]})
    monkeypatch.setattr(postgame, 'reachable', lambda policy, snapshot, rows: rows[0])
    policy = expedition(data)
    good = (0, 12, 12, 12, 12)
    assert 0.1 < postgame.tail(mon(16, dvs=good)) < 0.2
    # Equally good copies: the common species pays for its next catch and the rare one does not.
    state = snapshot([lead()], [mon(16, dvs=good), mon(19, position=1, dvs=good)])
    assert postgame.quality(policy, state, 'day')['species'] == 19
    monkeypatch.setattr(postgame, 'huntable', lambda *args: {16: [rare]})
    assert postgame.quality(policy, state, 'day') is None
    # With an ordinary best copy the rare species is still worth it, and the hunt ends at a good catch.
    first = mon(16)
    hunt = postgame.quality(policy, snapshot([lead()], [first]), 'day')
    assert hunt['species'] == 16
    postgame.state(policy)['activity'] = hunt
    worse = mon(16, position=1, trainer_id=99)
    # Each catch took as long as the table rate says.
    each = postgame.search_expected(5)
    policy.decisions = hunt['started'] + each
    assert not postgame.done(policy, snapshot([lead()], [first, worse]), hunt, 'day')
    policy.decisions += each
    assert postgame.done(policy, snapshot([lead()], [first, worse, mon(16, position=2, dvs=good)]), hunt, 'day')
    assert hunt['caught'] == 2
    # Training no longer waits for a hunt that would not pay.
    assert postgame.trainee(policy, snapshot([lead()], [mon(16, level=50, dvs=good)]))['species'] == 16


def test_a_hunt_running_dry_ends_before_its_stand_down_budget_and_is_not_picked_again(data, monkeypatch):
    from pokesim.gen2 import postgame
    from pokesim.gen2.standdown import search_expected
    common = dict(row(5, 16), chance=30)
    monkeypatch.setattr(postgame, 'huntable', lambda *args: {16: [common]})
    monkeypatch.setattr(postgame, 'reachable', lambda policy, snapshot, rows: rows[0])
    policy = expedition(data)
    policy.decisions = 1000
    first = mon(16, dvs=(0, 12, 12, 12, 12))
    state = snapshot([lead()], [first])
    hunt = postgame.quality(policy, state, 'day')
    assert hunt['species'] == 16
    postgame.state(policy)['activity'] = hunt
    # The table rate is one catch already seen, so the hunt pays until a dry run stretches it past WORTH.
    dry = postgame.catch_value(postgame.tail(first)) / postgame.WORTH - search_expected(30)
    assert 0 < dry < 3 * hunt['expected']
    policy.decisions = 1000 + int(dry) - 10
    assert not postgame.done(policy, state, hunt, 'day')
    policy.decisions = 1000 + int(dry) + 10
    assert postgame.done(policy, state, hunt, 'day') and hunt['caught'] == 0
    postgame.finish(policy)
    assert postgame.state(policy)['effort']['16'][1] == 0
    assert postgame.quality(policy, state, 'day') is None


def test_a_better_dv_hunt_ends_at_its_first_better_copy(data):
    from pokesim.gen2 import postgame
    policy = expedition(data)
    first = mon(16)
    # An older save's hunt kept no starting tail, so it beats the best copy held when it is next checked.
    hunt = {'kind': 'quality', 'species': 16, 'row': row(5), 'started': 1000, 'seen': [postgame.ident(first)], 'caught': 0}
    postgame.state(policy)['activity'] = hunt
    caught = [mon(16, position=1, trainer_id=99)]
    assert not postgame.done(policy, snapshot([lead()], [first] + caught), hunt, 'day')
    assert hunt['tail'] == postgame.tail(first) and hunt['caught'] == 1
    caught.append(mon(16, position=2, dvs=(0, 12, 12, 12, 12)))
    assert postgame.done(policy, snapshot([lead()], [first] + caught), hunt, 'day') and hunt['caught'] == 2
    postgame.finish(policy)
    assert postgame.state(policy)['searches'] == {'16': 1} and postgame.state(policy)['activity'] is None


def test_a_shiny_search_counts_encounters_without_a_cap_and_keeps_its_count_on_reload(data):
    import json
    from pokesim.gen2 import postgame
    policy = expedition(data)
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'shinies': 0}
    postgame.state(policy)['activity'] = session
    view = snapshot([lead()], [mon(16)])
    view.map = 5
    for encounter in range(1, 151):
        view.in_battle = 0
        postgame.observe(policy, view)
        view.in_battle = 1
        for _ in range(10):
            postgame.observe(policy, view)
        assert session['encounters'] == encounter
        assert not postgame.done(policy, view, session, 'day')
    # A checkpoint in the final battle cannot count it twice.
    policy.collection = json.loads(json.dumps(policy.collection))
    postgame.observe(policy, view)
    assert postgame.state(policy)['activity']['encounters'] == 150
    postgame.finish(policy)
    assert postgame.state(policy)['finished'] == 1 and 'shiny_break' not in postgame.state(policy)


def test_older_saves_drop_the_rotation_state(data):
    from pokesim.gen2 import postgame
    policy = expedition(data)
    policy.collection['postgame'] = {'activity': None, 'recent': ['train', 'shiny'], 'searches': {}, 'shiny_break': 2,
                                     'shiny_maps': []}
    data_ = postgame.state(policy)
    assert data_['finished'] == 2 and 'recent' not in data_ and 'shiny_break' not in data_


def test_each_shiny_search_battle_counts_as_progress_and_a_dry_map_stands_down(data):
    from pokesim.gen2 import collection, postgame
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import monitor, standing_down
    policy = expedition(data)
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'shinies': 0, 'maps': 0}
    postgame.state(policy)['activity'] = session
    policy.goal = Goal('collection_hunt', 'Search for a shiny in Route 29', 'ROUTE_29', 1, 1)
    view = snapshot([lead()])
    view.map, view.in_battle = 5, 0
    for _ in range(200):
        collection.observe_search(policy, view)
    session['encounters'] = 1
    collection.observe_search(policy, view)
    assert monitor(policy).spent('shiny:5') == 0
    # With no battle met for three times the decisions one is expected to take, the map stands down.
    calls = 0
    while not standing_down(policy, 'shiny:5') and calls < 1000:
        collection.observe_search(policy, view)
        calls += 1
    assert calls == round(3 * postgame.search_expected(100))


def test_shiny_searches_stop_on_a_shiny_and_have_no_time_limit(data):
    from pokesim.gen2 import postgame
    policy = expedition(data)
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'shinies': 0}
    postgame.state(policy)['activity'] = session
    view = snapshot([lead()], [mon(16)])
    policy.decisions += 100000
    view.frame += 10 * 60 * 60 * 60
    assert not postgame.done(policy, view, session, 'day')
    view.stored += (mon(16, position=1, shiny=True),)
    assert postgame.done(policy, view, session, 'day')


def test_shiny_outings_ignore_trainers_and_unrelated_wild_battles(data):
    from pokesim.gen2 import postgame
    policy = expedition(data)
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'shinies': 0}
    postgame.state(policy)['activity'] = session
    view = snapshot([lead()])
    for map_id, battle, target in [(5, 2, None), (6, 1, None), (5, 0, None), (5, 1, row(5))]:
        view.map, view.in_battle = map_id, battle
        policy.collection['target'] = target
        postgame.observe(policy, view)
    assert session.get('encounters', 0) == 0


def offer(monkeypatch, quality=None, train=None, shiny=None, race=False):
    from pokesim.gen2 import collection, marathon, postgame
    monkeypatch.setattr(postgame, 'quality', lambda *args: quality)
    monkeypatch.setattr(postgame, 'trainee', lambda *args: train)
    monkeypatch.setattr(postgame, 'shiny', lambda *args: shiny)
    monkeypatch.setattr(marathon, 'eligible', lambda *args: race)
    monkeypatch.setattr(marathon, 'candidate', lambda snapshot: {'kind': 'marathon'})
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: True)


def test_the_arbiter_ranks_the_postgame_by_tier_then_value_per_decision(data, monkeypatch):
    from pokesim.gen2 import postgame
    from pokesim.planning.arbiter import Tier
    policy = expedition(data)
    trainee = mon(19, position=1, level=50, dvs=PERFECT)
    state = snapshot([lead()], [mon(16), trainee])
    hunt = {'kind': 'quality', 'species': 16, 'row': row(5), 'expected': postgame.search_expected(30)}
    train = {'kind': 'train', 'identity': postgame.ident(trainee), 'species': 19, 'level_goal': 60}
    search = {'kind': 'shiny', 'row': row(7, None), 'shinies': 0}
    offer(monkeypatch, hunt, train, search)
    by_kind = {kind: postgame.candidate(policy, state, activity) for kind, activity in
               (('quality', hunt), ('train', train), ('shiny', search))}
    # Training outranks better copies, which sit in Gen I's hunt tier with the shiny search.
    from pokesim.policies.collection import HUNT_TIER
    assert by_kind['train'].tier == Tier.UPGRADE < by_kind['quality'].tier == HUNT_TIER == by_kind['shiny'].tier
    assert by_kind['quality'].score > by_kind['shiny'].score
    assert postgame.choose(policy, state, clock(), 'day') is train
    offer(monkeypatch, hunt, shiny=search)
    assert postgame.choose(policy, state, clock(), 'day') is hunt
    # A due race outranks both, and its own cooldown keeps it rare.
    offer(monkeypatch, hunt, train, search, race=True)
    assert postgame.choose(policy, state, clock(), 'day') == {'kind': 'marathon'}
    # With nothing else on offer the shiny search runs, ahead of the League, and its map counts as searched.
    offer(monkeypatch, shiny=search)
    assert postgame.choose(policy, state, clock(), 'day') is search and postgame.state(policy)['shiny_maps'] == [7]
    offer(monkeypatch)
    assert postgame.choose(policy, state, clock(), 'day') == {'kind': 'league'}


def test_a_shiny_search_asks_the_arbiter_again_after_each_battle(data, monkeypatch):
    from pokesim.gen2 import postgame
    from pokesim.gen2.policy import Goal
    policy = expedition(data)
    view = snapshot([lead()], [mon(16)])
    view.map, view.in_battle = 5, 0
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'shinies': 0, 'encounters': 0, 'in_battle': False}
    postgame.state(policy)['activity'] = session
    asked = []
    offer(monkeypatch)
    monkeypatch.setattr(postgame, 'offers', lambda *args, **kwargs: asked.append(1) or {})
    # Nothing is asked before the first battle, or while one is on.
    assert not postgame.outranked(policy, view, session, 'day') and not asked
    session['encounters'], view.in_battle = 1, 1
    assert not postgame.outranked(policy, view, session, 'day') and not asked
    view.in_battle = 0
    assert not postgame.outranked(policy, view, session, 'day') and len(asked) == 1
    # Each battle is asked about once.
    assert not postgame.outranked(policy, view, session, 'day') and len(asked) == 1
    # A race that came due takes over once the next battle is over.
    session['encounters'] = 2
    monkeypatch.setattr(postgame, 'offers', lambda *args, **kwargs: {'marathon': {'kind': 'marathon'}})
    assert postgame.outranked(policy, view, session, 'day')
    session['encounters'] = 3
    monkeypatch.setattr(postgame, 'choose', lambda *args: None)
    assert postgame.step(policy, view, clock(), Goal, 'day') is None
    assert postgame.state(policy)['activity'] is None and postgame.state(policy)['finished'] == 1


def test_a_league_run_is_the_fallback_once_nothing_else_is_left(data, monkeypatch):
    from pokesim.gen2 import collection, postgame
    offered = []
    for kind in ('quality', 'trainee', 'shiny'):
        monkeypatch.setattr(postgame, kind, lambda *args, kind=kind: offered.append(kind))
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: True)
    policy = expedition(data)
    assert postgame.choose(policy, snapshot([lead()]), clock(), 'day') == {'kind': 'league'}
    assert sorted(offered) == ['quality', 'shiny', 'trainee']
    # A team not ready for the League has nothing to do here, as before.
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: False)
    assert postgame.choose(policy, snapshot([lead()]), clock(), 'day') is None


def test_postgame_work_steps_aside_for_a_pokedex_hunt(data, monkeypatch):
    from pokesim.gen2 import breeding, postgame, training
    from pokesim.gen2.policy import Goal
    policy = expedition(data)
    postgame.state(policy)['activity'] = {'kind': 'shiny', 'row': row(1, None), 'started': 1000, 'shinies': 0}
    state = snapshot([lead()], [mon(16)])
    assert postgame.shiny_session(policy, state)
    policy.collection['target'] = row(7, 251)
    assert not postgame.shiny_session(policy, state) and postgame.quality_species(policy) is None
    # A postgame trainee waits behind collection work instead of pulling the run to Mt. Silver.
    monkeypatch.setattr(breeding, 'hatching', lambda *args: None)
    project = {'identity': postgame.ident(state.stored[0]), 'target': 16, 'item': None, 'species': 16,
               'terminal': True, 'level_goal': 40, 'postgame': True}
    policy.collection['training'] = project
    assert training.journey(policy, state, clock(), Goal) is None and policy.collection['training'] is project


def test_a_higher_priority_errand_suspends_hunt_battle_rules(data):
    from pokesim.gen2 import postgame
    from pokesim.gen2.policy import Policy
    policy = Policy(data)
    view = snapshot([lead()])
    view.map = data.map_ids['POKECENTER_2F']
    for kind in ('quality', 'shiny'):
        activity = {'kind': kind, 'species': 16, 'row': row(view.map), 'started': 0, 'shinies': 0}
        postgame.state(policy)['activity'] = activity
        assert postgame.quality_species(policy) == 16 if kind == 'quality' else postgame.shiny_session(policy, view)
        assert policy.journey(view, clock()).key == 'return_from_cable'
        assert postgame.quality_species(policy) is None
        assert not postgame.shiny_session(policy, view)


def test_a_stalled_search_stands_down_across_a_reload(data):
    from pokesim.gen2 import postgame
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import carry_over, stalled_objectives, standing_down
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'shinies': 0}
    policy = expedition(data)
    postgame.state(policy)['activity'] = dict(session)
    policy.goal = Goal('collection_hunt', 'Search for a shiny in Route 29', 'ROUTE_29', 1, 1)
    stalled = stalled_objectives(policy)
    assert stalled['keys'] == ['shiny:5']
    restored = expedition(data)
    postgame.state(restored)['activity'] = dict(session)
    carry_over(restored, stalled)
    assert postgame.state(restored)['activity'] is None and standing_down(restored, 'shiny:5')


def test_unloaded_encounter_tiles_get_a_bounded_retry(data, monkeypatch):
    from pokesim.gen2 import collection, postgame
    from pokesim.gen2.policy import Goal
    policy = expedition(data)
    view = snapshot([lead()])
    view.map, view.x, view.y = data.map_ids['ROUTE_29'], 2, 3
    activity = {'kind': 'shiny', 'row': row(view.map, None), 'started': 0, 'shinies': 0}
    postgame.state(policy)['activity'] = activity
    monkeypatch.setattr(collection, 'encounter_points', lambda *args, **kwargs: [])
    for _ in range(20):
        assert collection.hunt(policy, view, Goal, target=activity['row']).key == 'collection_wait'
        assert postgame.state(policy)['activity'] is activity
    assert collection.hunt(policy, view, Goal, target=activity['row']) is None
    assert postgame.state(policy)['activity'] is None
