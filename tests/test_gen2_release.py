"""Full Gen II storage frees a slot by releasing the lowest-value Pokémon, and waiting on the clock is not a stall."""
from types import SimpleNamespace

import pytest

from pokesim.gen2.release import BOX_CAPACITY, headroom, plan_partners, spares, target


def mon(species, *, box=0, position=0, dvs=(8, 8, 8, 8, 8), trainer_id=4321, **extra):
    fields = dict(species=species, egg=False, box=box, position=position, trainer_id=trainer_id, dvs=dvs, level=20,
                  held_item=0, experience=8000, stat_exp=(0,) * 5)
    fields.update(extra)
    return SimpleNamespace(**fields)


def strong(species, position=0, **extra):
    """A perfect, trained Lv 100 copy that outscores any spare, so it is the best copy."""
    return mon(species, position=position, dvs=(15,) * 5, level=100, stat_exp=(30000,) * 5, **extra)


def snapshot(stored, party=(), *, active_box=0, boxes=None):
    return SimpleNamespace(party=tuple(party), stored=tuple(stored), active_box=active_box,
                           box_counts=boxes if boxes is not None else (BOX_CAPACITY,) * 14)


def test_headroom_counts_free_slots_in_every_box():
    assert headroom(snapshot((), boxes=(20, 18, 15))) == 7


def test_the_best_copy_stays_and_the_lowest_value_goes_first():
    best = mon(16, position=0, dvs=(15, 14, 14, 14, 14))
    weak = mon(16, position=1, dvs=(2, 2, 2, 2, 2))
    middle = mon(16, position=2, dvs=(9, 9, 9, 9, 9))
    pair = [mon(19, position=3, dvs=(9, 9, 9, 9, 9)), mon(19, position=4, dvs=(3, 3, 3, 3, 3))]
    single = mon(21, position=5)
    assert spares(snapshot([best, weak, middle, *pair, single])) == [weak, pair[1], middle]


def test_a_party_member_stays_and_a_boxed_upgrade_is_the_best_copy():
    boxed = mon(16, dvs=(0, 2, 2, 2, 2))
    assert spares(snapshot([boxed], party=[mon(16, box=None, position=None)])) == [boxed]
    assert spares(snapshot([boxed])) == []
    upgrade = mon(16, dvs=(0, 10, 10, 10, 8))
    party = mon(16, box=None, position=None, dvs=(0, 8, 8, 8, 8))
    spare = mon(16, position=1, dvs=(0, 2, 2, 2, 2))
    assert spares(snapshot([upgrade, spare], party=[party])) == [spare]


def test_copies_a_plan_needs_go_after_every_spare():
    copies = [mon(16, position=index, dvs=(index + 1,) * 5) for index in range(3)]
    other = [mon(19, position=3, dvs=(9,) * 5), mon(19, position=4, dvs=(10,) * 5)]
    # Two linked adventures miss the species, so it keeps two copies and its spare is wanted in trade.
    assert spares(snapshot([*copies, *other]), demand={16: 2}) == [other[0], copies[0], copies[1]]


def test_breeding_stock_holds_a_role_for_two_copies_only():
    copies = [mon(16, position=index, dvs=(index + 1,) * 5) for index in range(6)]
    # The two best hold the role and stay, the best of them as the best copy, and the rest are spares.
    assert spares(snapshot(copies), keep={16}) == [copies[0], copies[1], copies[2], copies[3]]


def test_valuable_copies_go_last_and_eggs_keep_and_partners_stay():
    from pokesim.trade.preferences import identity
    best = strong(16)
    shiny = mon(16, position=1, dvs=(1, 10, 10, 10, 10))
    trained = mon(16, position=2, stat_exp=(30000,) * 5)
    egg = mon(16, position=3, egg=True)
    partner = mon(16, position=4, trainer_id=777, dvs=(5, 5, 5, 5, 5))
    locked = mon(16, position=5, trainer_id=888, dvs=(6, 6, 6, 6, 6))
    plain = mon(16, position=6, dvs=(4, 4, 4, 4, 4))
    collection = {'breeding': {'parents': [[777, [5, 5, 5, 5, 5]]]}}
    preferences = {identity({'trainer_id': 888, 'dvs': (6, 6, 6, 6, 6), 'dex': 16}): {'state': 'locked'}}
    order = spares(snapshot([best, shiny, trained, egg, partner, locked, plain]), preferences=preferences,
                   partners=plan_partners(collection))
    assert order == [plain, trained, shiny]


def test_perfect_and_rare_dv_copies_go_after_plain_ones():
    perfect = [mon(16, position=index, dvs=(15, 15, 15, 15, 15)) for index in range(2)]
    rare = mon(16, position=2, dvs=(13, 15, 15, 14, 15))
    plain = mon(16, position=3, dvs=(4, 4, 4, 4, 4))
    assert spares(snapshot([*perfect, rare, plain])) == [plain, rare, perfect[1]]


def test_the_exp_share_holder_is_not_protected_because_its_item_comes_off_first():
    from pokesim.gen2.release import EXP_SHARE
    best = mon(16, position=0, dvs=(14, 14, 14, 14, 14))
    holder = mon(16, position=1, held_item=EXP_SHARE)
    assert spares(snapshot([best, holder])) == [holder]


def test_the_last_copy_and_party_members_are_never_offered():
    lone = mon(16, position=0)
    party = mon(19, box=None, position=None)
    assert spares(snapshot([lone], party=[party])) == []


@pytest.mark.parametrize('species', [144, 145, 146, 150, 151, 243, 244, 245, 249, 250, 251])
def test_a_duplicate_legendary_goes_after_a_trained_lv_100_spare(species):
    copies = [mon(species, position=index, dvs=(index + 1,) * 5, level=50) for index in range(2)]
    veteran = [strong(16, position=2), mon(16, position=3, level=100, stat_exp=(30000,) * 5)]
    assert spares(snapshot([*copies, *veteran])) == [veteran[1], copies[0]]


@pytest.mark.parametrize('landmark', [0x7E, 0x7F])
def test_a_crystal_gift_or_event_copy_goes_after_a_caught_one(landmark):
    best = strong(16)
    # The high byte holds the catch time and level, the low byte the OT gender bit and the landmark.
    marked = mon(16, position=1, caught=0x4A00 | 0x80 | landmark)
    caught = mon(16, position=2, caught=0x4A00 | 0x80 | 0x12)
    assert spares(snapshot([best, marked, caught])) == [caught, marked]


def test_a_pokemon_from_an_unlinked_trainer_goes_after_the_players_own():
    from pokesim.trade.partners import owners
    best = strong(16)
    own = mon(16, position=1, dvs=(3, 3, 3, 3, 3), trainer_id=4321)
    partner = mon(16, position=2, dvs=(4, 4, 4, 4, 4), trainer_id=13132)
    foreign = mon(16, position=3, dvs=(2, 2, 2, 2, 2), trainer_id=20897)
    view = snapshot([best, own, partner, foreign])
    assert spares(view, owners=owners(4321, frozenset({13132}))) == [own, partner, foreign]
    assert spares(view, owners=owners(4321, frozenset())) == [own, foreign, partner]
    # Without a known player id nothing is judged by its trainer.
    assert owners(None, frozenset({13132})) is None
    assert spares(view, owners=None) == [foreign, own, partner]


def test_a_league_reward_scores_as_a_catch_not_a_trade():
    from pokesim.rewards import mark
    from pokesim.trade.partners import owners
    best = strong(155)
    reward = mon(155, position=1, dvs=(3, 3, 3, 3, 3), trainer_id=999)
    traded = mon(155, position=2, dvs=(2, 2, 2, 2, 2), trainer_id=998)
    marks = frozenset({mark(999, reward.dvs)})
    assert spares(snapshot([best, reward, traded]), owners=owners(4321, frozenset()), rewards=marks) == [reward, traded]


def test_an_owner_request_goes_first_but_never_takes_a_last_copy_unless_named():
    from pokesim.pcvalue import LAST_COPY
    from pokesim.trade.preferences import identity
    best = mon(16, position=0, dvs=(14, 14, 14, 14, 14))
    weak = mon(16, position=1, dvs=(2, 2, 2, 2, 2))
    lone = mon(19, position=2)
    key = lambda row: identity({'trainer_id': row.trainer_id, 'dvs': row.dvs, 'dex': row.species})  # noqa: E731
    view = snapshot([best, weak, lone])
    assert spares(view, requested={key(best): 'release'}) == [best, weak]
    assert spares(view, requested={key(lone): 'release'}) == [weak]
    assert spares(view, requested={key(lone): LAST_COPY}) == [lone, weak]


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
                             waiting=lambda snapshot: idle, recover=lambda level: recoveries.append(level))
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


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_policy_is_idle_only_on_the_waiting_tile(version):
    import os
    if not os.environ.get('GEN2_DATA_DIR'):
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    from pokesim.gen2.policy import Goal, Policy
    data = GameData.load(os.environ['GEN2_DATA_DIR'], version)
    policy = Policy(data, seed=1, starter='cyndaquil')
    here = SimpleNamespace(map=data.map_ids['ROUTE_29'], x=12, y=8, in_battle=0)
    policy.goal = Goal('collection_idle', 'Waiting for Tuesday', 'ROUTE_29', 12, 8)
    assert policy.idle(here)
    assert not policy.idle(SimpleNamespace(map=here.map, x=11, y=8, in_battle=0))
    assert not policy.idle(SimpleNamespace(map=here.map, x=12, y=8, in_battle=1))
    policy.goal = Goal('collection_hunt', 'Hunting', 'ROUTE_29', 12, 8)
    assert not policy.idle(here)


def test_a_return_the_pc_would_release_is_not_kept(monkeypatch):
    from pokesim.gen2.release import keeps_another
    monkeypatch.setattr('pokecore.gen2.breeding.breeding_stock', lambda data, species: set())
    policy = SimpleNamespace(data=SimpleNamespace(species={185: {'name': 'Sudowoodo'}}, game='gold'), demand={},
                             collection={}, trade_preferences=lambda: {})
    # Gold received the returning Sudowoodo while it held one, and released it 11 seconds later.
    assert not keeps_another(policy, snapshot([mon(185, dvs=(3,) * 5)]), 185)
    assert keeps_another(policy, snapshot([mon(16)]), 185)
    # A plan that needs two copies keeps the second.
    policy.demand = {185: 2}
    assert keeps_another(policy, snapshot([mon(185, dvs=(3,) * 5)]), 185)
