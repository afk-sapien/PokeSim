"""A Gen II run waits for the cartridge clock only when nothing else is useful, and says what it waits for."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def mon(species, *, box=0, position=0, level=30, dvs=(10, 10, 10, 10, 10), **extra):
    fields = dict(species=species, name=str(species), gender='Male', egg=False, box=box, position=position, trainer_id=4321,
                  dvs=dvs, moves=(33, 0, 0, 0), pp=(35, 0, 0, 0), level=level, friendship=70, held_item=0,
                  experience=30000, stat_exp=(0,) * 5)
    fields.update(extra)
    return SimpleNamespace(**fields)


def lead():
    return mon(157, box=None, dvs=(1,) * 5, moves=(57, 15, 53, 0), level=100, trainer_id=1)


def ditto():
    """Kept as the universal Day Care partner, so the plan never hunts for one."""
    return mon(132, box=1, position=19, gender='Genderless', dvs=(4, 4, 4, 4, 4))


def snapshot(party, stored=(), *, owned=None):
    return SimpleNamespace(party=tuple(party), stored=tuple(stored) + (ditto(),), daycare=(None, None), egg_ready=False,
                           owned=set(range(1, 252)) if owned is None else owned, money=50000, box_counts=(5,) * 14,
                           active_box=0, map=1, x=1, y=1, items=(), can_catch=True, hall_of_fame_count=3,
                           pockets={'balls': [(5, 20)]}, event=lambda name: True)


def clock(day=1, time=1):
    """Monday by default, which is neither a contest day nor Lapras's Friday."""
    values = {'wCurDay': day, 'wTimeOfDay': time}
    return SimpleNamespace(byte=lambda name: values.get(name, 0), memory=None)


def stub_activities(monkeypatch, **goals):
    """Make every activity of the expedition idle except the ``goals`` given by name."""
    from pokesim.gen2 import (breeding, celebi, collection, contest, gamecorner, npc_trades, quests, ruins, tower,
                              training)
    for module, name in [(contest, 'journey'), (tower, 'journey'), (ruins, 'journey'), (celebi, 'journey'),
                         (quests, 'gifts'), (quests, 'trade_items'), (quests, 'legends'), (quests, 'stones'),
                         (npc_trades, 'journey'), (breeding, 'journey'), (breeding, 'hatching'),
                         (gamecorner, 'journey'), (training, 'journey')]:
        goal = goals.get(f'{module.__name__.rsplit(".", 1)[1]}.{name}')
        monkeypatch.setattr(module, name, lambda *args, goal=goal, **kwargs: goal)
    monkeypatch.setattr(npc_trades, 'requests', lambda *args: set())
    monkeypatch.setattr(quests, 'ultra_shortfall', lambda *args: False)
    patrols = []
    monkeypatch.setattr(collection, 'patrol', lambda policy, snapshot, Goal, label: patrols.append(label) or
                        Goal('collection_idle', label, 'ROUTE_29', 12, 8))
    return patrols


def expedition(data):
    return SimpleNamespace(data=data, collection={}, demand={}, decisions=1000, completed={'tower': 1}, returned=set(),
                           in_league=lambda snapshot: False, no_room=lambda snapshot: False, memory=None)


def test_available_work_goes_ahead_of_a_clock_wait_and_names_it(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    walk = Goal('collection_hatch', 'Walk with the eggs and the Day Care partners', 'GOLDENROD_CITY', 20, 10)
    patrols = stub_activities(monkeypatch, **{'breeding.journey': walk})
    state = snapshot([lead()], owned=set(range(1, 252)) - {131})
    # Lapras is wanted but surfaces only on Fridays, and the Day Care has a wanted pair now.
    goal = journey(expedition(data), state, clock(day=1), Goal)
    assert goal.key == 'collection_hatch' and not patrols
    assert goal.label == 'Walk with the eggs and the Day Care partners while Lapras waits for Friday'
    # Without a clock wait the label stays as it was.
    goal = journey(expedition(data), snapshot([lead()]), clock(day=1), Goal)
    assert goal.label == 'Walk with the eggs and the Day Care partners'


def test_hatching_and_training_come_before_the_patrol(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    hatch = Goal('collection_hatch_pc', 'Bring eggs from storage to hatch', 'GOLDENROD_POKECENTER_1F', 3, 3)
    train = Goal('collection_train', 'Train MON toward level 100', 'SILVER_CAVE_ROOM_1', 9, 31)
    state = snapshot([lead()], owned=set(range(1, 252)) - {131})
    patrols = stub_activities(monkeypatch, **{'breeding.hatching': hatch, 'training.journey': train})
    assert journey(expedition(data), state, clock(), Goal).label == 'Bring eggs from storage to hatch while Lapras waits for Friday'
    patrols = stub_activities(monkeypatch, **{'training.journey': train})
    assert journey(expedition(data), state, clock(), Goal).key == 'collection_train' and not patrols
    # With nothing else left the patrol is the last resort, and it says what it waits for.
    patrols = stub_activities(monkeypatch)
    policy = expedition(data)
    goal = journey(policy, state, clock(), Goal)
    assert goal.key == 'collection_idle' and policy.collection['phase'] == 'waiting'
    assert patrols == ['Walk the grass while Lapras waits for Friday']


def test_an_open_clock_window_is_used_while_it_lasts(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    stub_activities(monkeypatch)
    state = snapshot([lead()], owned=set(range(1, 252)) - {131})
    state.badges = 0
    # On Friday the Lapras window is open. It fails here for lack of the Fog Badge, so the plan moves on
    # to the patrol instead of waiting for Lapras, and nothing names a Friday wait any more.
    labels = stub_activities(monkeypatch)
    goal = journey(expedition(data), state, clock(day=5), Goal)
    assert goal.key == 'collection_idle' and 'Friday' not in labels[0]


def test_patrol_labels_say_what_the_walk_does_and_waits_for(data):
    from pokesim.gen2.collection import waiting_label
    policy = expedition(data)
    owned = set(range(1, 252))
    assert (waiting_label(policy, snapshot([lead()], owned=owned), clock(), 'day')
            == 'Walk the grass until a trade or a return brings new collection work')
    eggs = snapshot([lead(), mon(175, box=None, egg=True)], owned=owned - {131})
    assert waiting_label(policy, eggs, clock(), 'day') == 'Walk the eggs to hatching while Lapras waits for Friday'
    # Contest days come first when the Sun Stone is still needed.
    contest = snapshot([lead()], owned=owned - {182, 192})
    label = waiting_label(policy, contest, clock(day=1), 'day')
    assert label == 'Walk the grass while the Bug-Catching Contest waits for Tuesday'
    entered = clock(day=2)
    entered.byte = lambda name: {'wCurDay': 2, 'wDailyFlags1': 2}.get(name, 0)
    assert waiting_label(policy, contest, entered, 'day').endswith("waits for Thursday, as today's was entered")


def test_a_time_of_day_encounter_names_the_species_and_the_time(data):
    from pokesim.gen2.collection import clock_wait
    night = {row['species'] for row in data.encounters if row['time'] == 'night'}
    day = {row['species'] for row in data.encounters if row['time'] != 'night'}
    species = min(night - day)
    owned = set(range(1, 252)) - {species}
    wait = clock_wait(expedition(data), snapshot([lead()], owned=owned), clock(), 'day')
    assert wait == f'{data.species[species]["name"]} waits for night'
    assert clock_wait(expedition(data), snapshot([lead()], owned=owned), clock(), 'night') is None


def test_without_exp_share_a_stuck_levelling_plan_lets_boxed_eggs_hatch(data):
    from pokesim.gen2.breeding import hatching
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import identity, journey
    trainee = mon(94, box=3, level=30)
    eggs = [mon(175, box=2, position=i, egg=True, level=5, dvs=(i,) * 5) for i in range(3)]
    state = snapshot([lead()], [trainee, *eggs])
    storage = SimpleNamespace(map_name='GOLDENROD_POKECENTER_1F', x=1, y=1, face='up')
    policy = SimpleNamespace(data=data, collection={}, demand={}, decisions=1000, storage_goal=lambda snapshot: storage,
                             release_target=lambda snapshot: None, no_room=lambda snapshot: False)
    # A roamer lead plan set this levelling project, but the Exp. Share is gone, so it can never finish.
    policy.collection['training'] = {'identity': identity(trainee), 'target': 94, 'item': None, 'species': 94,
                                     'terminal': True, 'level_goal': 37}
    assert hatching(policy, state, Goal) is None
    assert journey(policy, state, clock(), Goal, terminal=True) is None
    assert policy.collection['training'] is None
    assert hatching(policy, state, Goal).key == 'collection_hatch_pc'


def test_without_exp_share_a_stone_evolution_still_runs(data):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import journey
    eevee = mon(133, box=None, position=1, level=20)
    state = snapshot([lead(), eevee], owned=set(range(1, 252)) - {134})
    state.items = ((data.items['WATER_STONE'], 1),)
    state.map = data.map_ids['GOLDENROD_CITY']
    policy = SimpleNamespace(data=data, collection={}, demand={}, decisions=1000, no_room=lambda snapshot: False)
    goal = journey(policy, state, clock(), Goal)
    assert goal.key == 'collection_evolve_item' and policy.collection['training']['target'] == 134


def test_the_exp_share_holder_is_never_released_or_traded(data):
    from pokesim.gen2.release import EXP_SHARE, spares
    from pokesim.gen2.trading import _kept
    assert data.items['EXP_SHARE'] == EXP_SHARE
    holder = mon(16, box=0, position=0, held_item=EXP_SHARE, dvs=(3, 3, 3, 3, 3))
    other = mon(16, box=0, position=1, held_item=data.items['POTION'], dvs=(2, 2, 2, 2, 2))
    best = mon(16, box=0, position=2, dvs=(12, 12, 12, 12, 12))
    state = snapshot([lead()], [holder, other, best])
    assert spares(state, lenient=True) == [other]
    assert _kept({'species': 16, 'held_item': EXP_SHARE, 'trade_key': 'k', 'dvs': [3] * 5}, set()) == 'Holds the Exp. Share'
