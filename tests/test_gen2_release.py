"""Full Gen II storage frees a slot by releasing a spare duplicate, and waiting on the clock is not a stall."""
from types import SimpleNamespace

from pokesim.gen2.release import BOX_CAPACITY, headroom, plan_partners, spares, target


def mon(species, *, box=0, position=0, dvs=(8, 8, 8, 8, 8), trainer_id=4321, **extra):
    fields = dict(species=species, egg=False, box=box, position=position, trainer_id=trainer_id, dvs=dvs, level=20,
                  held_item=0, experience=8000, stat_exp=(0,) * 5)
    fields.update(extra)
    return SimpleNamespace(**fields)


def snapshot(stored, party=(), *, active_box=0, boxes=None):
    return SimpleNamespace(party=tuple(party), stored=tuple(stored), active_box=active_box,
                           box_counts=boxes if boxes is not None else (BOX_CAPACITY,) * 14)


def test_headroom_counts_free_slots_in_every_box():
    assert headroom(snapshot((), boxes=(20, 18, 15))) == 7


def test_the_best_copy_stays_and_the_most_numerous_species_goes_first():
    best = mon(16, position=0, dvs=(15, 14, 14, 14, 14))
    weak = mon(16, position=1, dvs=(2, 2, 2, 2, 2))
    middle = mon(16, position=2, dvs=(9, 9, 9, 9, 9))
    pair = [mon(19, position=3, dvs=(9, 9, 9, 9, 9)), mon(19, position=4, dvs=(3, 3, 3, 3, 3))]
    single = mon(21, position=5)
    order = spares(snapshot([best, weak, middle, *pair, single]))
    assert order == [weak, middle, pair[1]]


def test_party_copies_count_as_the_kept_copy():
    boxed = mon(16, dvs=(15, 15, 15, 15, 14))
    assert spares(snapshot([boxed], party=[mon(16, box=None, position=None)])) == [boxed]
    assert spares(snapshot([boxed])) == []


def test_plan_demand_and_kept_species_are_never_offered():
    copies = [mon(16, position=index, dvs=(index + 1,) * 5) for index in range(3)]
    assert spares(snapshot(copies), demand={16: 2}) == [copies[0]]
    assert spares(snapshot(copies), keep={16}) == []


def test_rare_trained_held_and_partner_pokemon_are_protected():
    best = mon(16, position=0, dvs=(14, 14, 14, 14, 14))
    protected = [
        mon(16, position=1, dvs=(1, 10, 10, 10, 10)),  # shiny
        mon(16, position=2, held_item=1),
        mon(16, position=3, stat_exp=(10000, 10000, 0, 0, 0)),
        mon(16, position=4, egg=True),
        mon(16, position=5, trainer_id=777, dvs=(5, 5, 5, 5, 5)),
        mon(16, position=6, trainer_id=888, dvs=(6, 6, 6, 6, 6)),
    ]
    plain = mon(16, position=7, dvs=(4, 4, 4, 4, 4))
    collection = {'breeding': {'parents': [[777, [5, 5, 5, 5, 5]]]}}
    from pokesim.trade.preferences import identity
    preferences = {identity({'trainer_id': 888, 'dvs': (6, 6, 6, 6, 6)}): {'state': 'locked'}}
    result = spares(snapshot([best, *protected, plain]), preferences=preferences, partners=plan_partners(collection))
    assert result == [plain]


def test_each_unown_letter_keeps_its_own_copy():
    # Letters come from the attack, defense, speed and special DVs.
    a = mon(201, position=0, dvs=(5, 0, 0, 0, 0))
    a_again = mon(201, position=1, dvs=(0, 0, 0, 0, 0))
    other = mon(201, position=2, dvs=(5, 15, 15, 15, 15))
    assert spares(snapshot([a, a_again, other])) == [a_again]


def test_target_skips_refused_slots():
    copies = [mon(16, position=index, dvs=(index + 1,) * 5) for index in range(3)]
    assert target(snapshot(copies), allowed=lambda found: found.position != 0) is copies[1]


def test_release_task_ends_when_someone_else_sits_in_the_slot():
    from pokesim.gen2.menus import Release
    spare = mon(16, box=2, position=4, dvs=(3, 3, 3, 3, 3))
    task = Release(2, 4, [16, 4321, [3, 3, 3, 3, 3]])
    assert not task.finished(snapshot([spare], active_box=2))
    assert task.finished(snapshot([spare], active_box=1))
    assert task.finished(snapshot([mon(19, box=2, position=4)], active_box=2))


def test_held_counts_follow_a_new_snapshot():
    from pokesim.gen2.collection import held_counts
    first = snapshot([mon(16), mon(16), mon(19, egg=True)])
    assert held_counts(first)[16] == 2 and held_counts(first)[19] == 0
    second = snapshot([mon(16)])
    assert held_counts(second)[16] == 1


def guard_emulator(idle):
    from pokesim.gen2.emulator import Emulator
    reloads, recoveries = [], []
    policy = SimpleNamespace(recoveries=0, take_failure=lambda: None, idle=lambda snapshot: idle,
                             recover=lambda level: recoveries.append(level))
    emu = SimpleNamespace(paused=False, manual_mode=False, preparation=None, store=SimpleNamespace(get=lambda key: None),
                          snapshot=SimpleNamespace(valid=True, started=True), frame=10 ** 6, last_reload_frame=0,
                          policy=policy, failure_streak=0, invalid_frame=None, battle_frame=None, stuck_frame=0,
                          screen_frame=0, progress_frame=0, stuck_ts=0.0, stall=SimpleNamespace(frame=5), waiting=False)
    emu._unstick = lambda since, why: reloads.append((since, why))
    emu._check_stall = lambda: None
    Emulator._check_guards(emu)
    return emu, reloads, recoveries


def test_waiting_for_the_cartridge_clock_is_not_stuck():
    emu, reloads, recoveries = guard_emulator(idle=True)
    assert not reloads and not recoveries and emu.waiting
    assert emu.stuck_frame == emu.progress_frame == emu.screen_frame == emu.frame and emu.stall.frame is None


def test_a_stuck_reload_counts_from_the_game_frame_it_began():
    emu, reloads, _ = guard_emulator(idle=False)
    assert reloads == [(0, 'stuck')] and not emu.waiting


def test_reload_target_uses_the_saved_game_frame_not_file_times(tmp_path):
    from pokesim.gen2.emulator import SCREEN_FRAMES, reload_target
    saves = [tmp_path / f'auto-{index}.state' for index in range(3)]
    frames = {saves[0]: 1000, saves[1]: 50000, saves[2]: 90000}
    store = SimpleNamespace(checkpoint_metadata=lambda path: {'frame': frames[path]})
    assert reload_target(store, saves, 90000 + SCREEN_FRAMES) is saves[1]
    assert reload_target(store, saves, 50000) is saves[0]
    assert reload_target(store, saves, 10) is saves[0]
    assert reload_target(store, [], 10) is None


def test_exhausted_reloads_are_reported_once(caplog):
    from pokesim.gen2.emulator import MAX_RELOADS, Emulator
    emu = SimpleNamespace(unstick_streak=MAX_RELOADS, reloads_exhausted=False, _reset_watch=lambda: None)
    with caplog.at_level('ERROR', logger='pokesim.gen2'):
        for _ in range(3):
            Emulator._unstick(emu, 0, 'stuck')
    assert sum('reloads did not help' in record.getMessage() for record in caplog.records) == 1


def test_policy_is_idle_only_on_the_waiting_tile():
    import os

    import pytest
    if not os.environ.get('GEN2_DATA_DIR'):
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    from pokesim.gen2.policy import Goal, Policy
    data = GameData.load(os.environ['GEN2_DATA_DIR'], 'crystal')
    policy = Policy(data, seed=1, starter='cyndaquil')
    here = SimpleNamespace(map=data.map_ids['ROUTE_29'], x=12, y=8, in_battle=0)
    policy.goal = Goal('collection_idle', 'Waiting for Tuesday', 'ROUTE_29', 12, 8)
    assert policy.idle(here)
    assert not policy.idle(SimpleNamespace(map=here.map, x=11, y=8, in_battle=0))
    assert not policy.idle(SimpleNamespace(map=here.map, x=12, y=8, in_battle=1))
    policy.goal = Goal('collection_hunt', 'Hunting', 'ROUTE_29', 12, 8)
    assert not policy.idle(here)
