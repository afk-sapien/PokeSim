"""A finished Gen II run keeps playing the way Red, Blue and Yellow do, with a bounded shiny search."""
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


def test_a_better_dv_hunt_ends_after_three_catches(data):
    from pokesim.gen2 import postgame
    policy = expedition(data)
    first = mon(16)
    hunt = {'kind': 'quality', 'species': 16, 'row': row(5), 'started': 1000, 'seen': [postgame.ident(first)], 'caught': 0}
    postgame.state(policy)['activity'] = hunt
    caught = [mon(16, position=i, dvs=(i, i, i, i, i)) for i in range(1, 3)]
    assert not postgame.done(policy, snapshot([lead()], [first] + caught), hunt, 'day')
    caught.append(mon(16, position=3, dvs=(9, 9, 9, 9, 9)))
    assert postgame.done(policy, snapshot([lead()], [first] + caught), hunt, 'day') and hunt['caught'] == 3
    postgame.finish(policy)
    assert postgame.state(policy)['searches'] == {'16': 1} and postgame.state(policy)['activity'] is None


def test_a_shiny_outing_counts_encounters_not_turns_and_keeps_its_count_on_reload(data):
    import json
    from pokesim.gen2 import postgame
    policy = expedition(data)
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'started_frame': 60000, 'shinies': 0}
    postgame.state(policy)['activity'] = session
    view = snapshot([lead()], [mon(16)])
    view.map = 5
    for encounter in range(1, 101):
        view.in_battle = 0
        postgame.observe(policy, view)
        view.in_battle = 1
        for _ in range(10):
            postgame.observe(policy, view)
        assert session['encounters'] == encounter
        assert postgame.done(policy, view, session, 'day') == (encounter == 100)
    # A checkpoint in the final battle cannot count it twice.
    policy.collection = json.loads(json.dumps(policy.collection))
    postgame.observe(policy, view)
    assert postgame.state(policy)['activity']['encounters'] == 100
    postgame.finish(policy)
    assert postgame.state(policy)['shiny_break'] == 2


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


def test_shiny_outings_stop_on_a_catch_or_gameplay_safety_limit(data):
    from pokesim.gen2 import postgame
    policy = expedition(data)
    session = {'kind': 'shiny', 'row': row(5, None), 'started': 1000, 'started_frame': 60000, 'shinies': 0}
    postgame.state(policy)['activity'] = session
    view = snapshot([lead()], [mon(16)])
    policy.decisions += 100000
    assert not postgame.done(policy, view, session, 'day')
    view.stored += (mon(16, position=1, shiny=True),)
    assert postgame.done(policy, view, session, 'day')
    view.stored = ()
    view.frame += postgame.SHINY_MAX_FRAMES - 1
    assert not postgame.done(policy, view, session, 'day')
    view.frame += 1
    assert postgame.done(policy, view, session, 'day')


def test_two_other_activities_take_their_turn_before_another_shiny_outing(data, monkeypatch):
    from pokesim.gen2 import collection, postgame
    from pokesim.gen2.policy import Goal
    policy = expedition(data)
    postgame.state(policy)['activity'] = {'kind': 'shiny'}
    postgame.finish(policy)
    view = snapshot([lead()])
    offered = []
    for kind in ('quality', 'trainee', 'shiny'):
        monkeypatch.setattr(postgame, kind, lambda *args, kind=kind: offered.append(kind))
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: False)
    assert postgame.choose(policy, view, clock(), 'day') is None
    assert sorted(offered) == ['quality', 'trainee']
    # League outings are carried to completion by collection.journey before it calls the director again.
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: True)
    monkeypatch.setattr(collection, 'league_funding', lambda *args, **kwargs: 'league')
    for remaining in (1, 0):
        assert postgame.step(policy, view, clock(), Goal, 'day') == 'league'
        assert postgame.state(policy)['shiny_break'] == remaining
    offered.clear()
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: False)
    postgame.choose(policy, view, clock(), 'day')
    assert 'shiny' in offered



def test_the_rotation_spreads_the_activities_like_gen_one(data, monkeypatch):
    from pokesim.gen2 import collection, postgame
    for kind, name in (('quality', 'quality'), ('train', 'trainee'), ('shiny', 'shiny')):
        monkeypatch.setattr(postgame, name, lambda *args, kind=kind: {'kind': kind})
    monkeypatch.setattr(collection, 'postgame_league', lambda *args: True)
    state = snapshot([lead()])
    picks = []
    for decisions in range(400):
        policy = expedition(data, decisions)
        picks.append(postgame.choose(policy, state, clock(), 'day')['kind'])
    counts = {kind: picks.count(kind) for kind in postgame.WEIGHTS}
    assert counts['quality'] > counts['shiny'] > counts['league'] > 0 and counts['train'] > counts['shiny']
    # Two picks of one kind in a row rule it out for the next pick.
    for decisions in range(100):
        policy = expedition(data, decisions)
        postgame.state(policy)['recent'] = ['train', 'train']
        assert postgame.choose(policy, state, clock(), 'day')['kind'] != 'train'


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
