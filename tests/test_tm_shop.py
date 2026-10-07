"""Champion shop decisions, finite-item protection, and recoverable purchases."""
from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim import tm_shop
from pokesim.activity_ledger import KEY as ACTIVITY, status
from pokesim.policies.progression import Goal
from pokesim.policies.shopping import ShoppingController
from pokesim.policies.strategic import StrategicPolicy
from pokesim.runtime import tm_purchase
from pokesim.runtime.reward_delivery import BARRIER, PENDING, recover_storage
from pokesim.store import Store
from pokesim.strategy_data import ITEMS, MAPS
from test_battle_power import live, partner
from test_collection import state


@pytest.fixture
def shop_data():
    # Starmie and Magikarp deliberately have different compatibility.
    return {213: 58, 224: 85, 229: 94}, {152: {213, 224, 229}, 133: set()}


def shopper(**changes):
    defaults = dict(party=(live(partner(moves=[57, 105, 33, 0])),), hall_of_fame_count=1,
                    money=100000, map=tm_shop.COUNTER[0], x=6, y=5, frame=10000)
    defaults.update(changes)
    return state(**defaults)


def test_catalogue_has_all_38_limited_tms_and_no_renewable_ones():
    assert len(tm_shop.LIMITED) == 38
    assert set(tm_shop.PRICES) == tm_shop.LIMITED
    assert set(tm_shop.PRICES.values()) == {10000, 25000, 50000}
    assert all(200 + number not in tm_shop.PRICES for number in tm_shop.RENEWABLE)


def test_clean_cartridge_data_supports_existing_bundles():
    rom = Path('roms/pokered.gb')
    if not rom.exists():
        pytest.skip('Private Red ROM unavailable')
    moves, compatible = tm_shop.cartridge_data(rom.read_bytes())
    assert len(moves) == 50 and len(compatible) == 151
    assert moves[213] == 58 and moves[224] == 85
    assert 213 in compatible[152] and 224 in compatible[152]
    assert not compatible[133]
    assert tm_shop.cartridge_data(b'unsupported') == ({}, {})


def test_purchase_requires_champion_cash_capacity_and_compatible_recipient(shop_data):
    moves, compatible = shop_data
    s = shopper()
    chosen = tm_shop.choose(s, moves, compatible, owned=False)
    assert chosen and chosen['target'] == 0
    for changed in (replace(s, hall_of_fame_count=0), replace(s, money=69999),
                    replace(s, items=tuple((item, 1) for item in range(1, 21))),
                    replace(s, party=(live(partner('MAGIKARP')),)),
                    replace(s, party=(live(partner(level=5)),))):
        assert tm_shop.choose(changed, moves, compatible, owned=False) is None
    assert tm_shop.choose(replace(s, money=70000), moves, compatible, owned=False)


def test_owned_tm_does_not_require_purchase_budget_or_free_bag_slot(shop_data):
    moves, compatible = shop_data
    s = shopper(money=0, items=((213, 1),))
    assert tm_shop.choose(s, moves, compatible, owned=True)['item'] == 213
    assert tm_shop.choose(s, moves, compatible, owned=False) is None


def test_never_buys_duplicate_stock_or_replaces_hms(shop_data):
    moves, compatible = shop_data
    s = shopper(items=((213, 1), (224, 1), (229, 1)))
    assert tm_shop.choose(s, moves, compatible, owned=False) is None
    hms = live(partner(moves=[15, 19, 57, 70]))
    assert tm_shop.choose(replace(s, party=(hms,)), moves, compatible, owned=True) is None
    known = live(partner(moves=[57, 58, 85, 94]))
    assert tm_shop.choose(replace(s, party=(known,)), moves, compatible, owned=True) is None


def test_plan_cannot_drift_to_another_party_member(shop_data):
    moves, compatible = shop_data
    s = shopper()
    plan = tm_shop.choose(s, moves, compatible, owned=False)
    assert tm_shop.valid_plan(s, plan, moves, compatible)
    other = replace(s.party[0], nick='Different')
    assert not tm_shop.valid_plan(replace(s, party=(other,)), plan, moves, compatible)
    assert not tm_shop.valid_plan(replace(s, money=0), plan, moves, compatible)


def test_shopping_protects_limited_tms_even_when_raising_funds():
    s = shopper(items=((213, 1), (224, 2), (ITEMS['NUGGET'], 1)))
    assert ShoppingController.sale_index(s) == 2
    assert ShoppingController.fund_index(s) == 2
    limited_only = replace(s, items=s.items[:2])
    assert ShoppingController.sale_index(limited_only) is None
    assert ShoppingController.fund_index(limited_only) is None
    assert ShoppingController.sale_index(replace(s, items=((201, 1),))) == 0


def crowded_bag():
    keys = ('BICYCLE', 'TOWN_MAP', 'HELIX_FOSSIL', 'S_S_TICKET', 'POKE_FLUTE',
            'SILPH_SCOPE', 'COIN_CASE', 'OLD_ROD', 'GOOD_ROD', 'HM01', 'HM02', 'HM03')
    return (tuple((ITEMS[name], 1) for name in keys)
            + tuple((item, 1) for item in (206, 211, 221, 224, 234, 245))
            + ((ITEMS['POKE_BALL'], 15), (ITEMS['SUPER_POTION'], 3)))


def test_full_story_bag_routes_to_sell_one_tm_then_resumes():
    from pokesim.policies.pickups import Pickups
    s = shopper(items=crowded_bag(), hall_of_fame_count=0, map=MAPS['SAFFRON_CITY'])
    goal = Goal('silph', 'Get the Card Key', 'Continue the story')
    shop = ShoppingController()
    def plan(state):
        return shop.plan(state, goal, None, requested_goal=goal.key, healing=False,
                         in_league=False, has_pokedex=True)
    assert not Pickups.has_space(s, ITEMS['CARD_KEY'])
    assert plan(s).goal.key == 'restock'
    index = shop._sale_choice(s)
    item, quantity = s.items[index]
    assert item in tm_shop.LIMITED
    assert tm_shop.PRICES[item] * quantity == min(tm_shop.PRICES[mid] * qty for mid, qty in s.items if mid in tm_shop.LIMITED)
    after = replace(s, items=s.items[:index] + s.items[index + 1:])
    assert shop._sale_choice(after) is None
    assert plan(after).goal.key == 'silph'
    assert Pickups.has_space(after, ITEMS['CARD_KEY'])
    assert all(entry in after.items for entry in s.items if entry[0] not in tm_shop.LIMITED)


@pytest.mark.parametrize('surplus', [ITEMS['NUGGET'], ITEMS['X_ATTACK'], 201])
def test_full_bag_sells_ordinary_surplus_before_limited_tms(surplus):
    bag = crowded_bag()
    s = shopper(items=bag[:12] + ((surplus, 1),) + bag[13:])
    assert ShoppingController.sale_index(s) == 12


def test_champion_tm_purchase_keeps_last_bag_slot_free(shop_data):
    moves, compatible = shop_data
    s = shopper(items=tuple((item, 1) for item in range(1, 19)))
    plan = tm_shop.choose(s, moves, compatible, owned=False)
    assert plan and tm_shop.valid_plan(s, plan, moves, compatible)
    crowded = replace(s, items=s.items + ((ITEMS['SUPER_POTION'], 1),))
    assert tm_shop.choose(crowded, moves, compatible, owned=False) is None
    assert not tm_shop.valid_plan(crowded, plan, moves, compatible)
    owned = replace(crowded, items=crowded.items + ((plan['item'], 1),))
    assert tm_shop.choose(owned, moves, compatible, owned=True)
    assert tm_shop.valid_plan(owned, plan, moves, compatible)


def test_policy_routes_to_counter_then_uses_owned_tm(shop_data):
    policy = StrategicPolicy(1)
    policy.tm_moves, policy.tm_compatible = shop_data
    goal = Goal('collect_plan', 'Plan', 'Choose a project')
    s = shopper(map=MAPS['CELADON_CITY'])
    new_goal, action = policy._tm_development(s, goal, False)
    assert new_goal.key == 'buy_tm' and new_goal.targets == (tm_shop.COUNTER,) and action is None
    item = policy.tm_plan['item']
    # The plan survives travel while the ordinary collection goal is rebuilt.
    new_goal, _ = policy._tm_development(replace(s, frame=s.frame + 20), goal, False)
    assert new_goal.key == 'buy_tm'
    policy.on_restore()
    goal, action = policy._tm_development(replace(s, items=((item, 1),)), goal, False)
    assert goal.key == 'teach_tm' and action[0].button == 'start'
    assert policy.intent.target == 0 and policy.intent.index == 0


def test_tm_trips_wait_for_healing_league_and_active_projects(shop_data):
    policy = StrategicPolicy(1)
    policy.tm_moves, policy.tm_compatible = shop_data
    goal = Goal('collect_plan', 'Plan', 'Choose a project')
    s = shopper()
    assert policy._tm_development(s, goal, True) == (goal, None)
    policy.heal_latch = True
    assert policy._tm_development(s, goal, False) == (goal, None)
    policy.heal_latch = False
    policy.collection.project = {'method': 'train'}
    assert policy._tm_development(s, goal, False) == (goal, None)
    assert policy.tm_plan is None


@pytest.fixture
def purchase_fixture(tmp_path, monkeypatch, shop_data):
    with closing(Store(tmp_path)) as store:
        store.set(ACTIVITY, {'started_at': 123, 'available': True})
        before = shopper()
        policy = StrategicPolicy(1)
        policy.tm_moves, policy.tm_compatible = shop_data
        policy.tm_plan = tm_shop.choose(before, *shop_data, owned=False)
        policy.goal = Goal('buy_tm', 'Buy a TM', 'Improve coverage')
        item = policy.tm_plan['item']
        memory, clone_memory = bytearray(65536), bytearray(65536)
        from pokesim.ram import W_CUR_MAP, W_X, W_Y
        memory[W_CUR_MAP], memory[W_X], memory[W_Y] = tm_shop.COUNTER
        expected = replace(before, money=before.money - tm_shop.PRICES[item], items=before.items + ((item, 1),))
        monkeypatch.setattr(tm_purchase, 'read_snapshot', lambda mem, frame: before if mem is memory else expected)
        clone = SimpleNamespace(memory=clone_memory, load_state=lambda _: None,
                                save_state=lambda stream: stream.write(b'purchased-state'), stop=lambda **_: None)
        source = store.write_checkpoint(b'source', {'frame': before.frame, 'policy_state': {}, 'run_memory': {}})
        emu = SimpleNamespace(store=store, policy=policy, isolated_ram=True, paused=False, manual_mode=False,
                              pb=SimpleNamespace(memory=memory), frame=before.frame,
                              _autosave=lambda: None, _state_bytes=lambda: b'source', _boot=lambda: clone,
                              _load_state_file=lambda _: None, input_epoch=0)
        yield emu, before, item, clone_memory, source


def bought(store, item):
    return next(row['bought'] for row in status(store)['items'] if row['id'] == item)


def test_purchase_commits_money_bag_journal_and_counter_together(purchase_fixture):
    emu, before, item, memory, _ = purchase_fixture
    result = tm_purchase.purchase(emu)
    assert result['decision'] == 'COMMIT'
    assert bought(emu.store, item) == 1
    assert len(emu.store.events()) == 1
    assert emu.store.get(BARRIER) == result['id']
    assert emu.store.latest_state().read_bytes() == b'purchased-state'
    from pokesim.ram import W_MONEY, W_NUM_BAG_ITEMS, W_BAG_ITEMS, bcd
    assert bcd(memory[W_MONEY:W_MONEY + 3]) == before.money - tm_shop.PRICES[item]
    assert memory[W_NUM_BAG_ITEMS] == len(before.items) + 1
    offset = W_BAG_ITEMS + len(before.items) * 2
    assert memory[offset:offset + 3] == bytes((item, 1, 255))
    assert recover_storage(emu.store) is None
    assert tm_purchase.purchase(emu) is None
    assert bought(emu.store, item) == 1


def test_failed_commit_leaves_source_and_statistics_untouched(purchase_fixture):
    import sqlite3
    emu, _, item, _, source = purchase_fixture
    emu.store.db.execute("CREATE TRIGGER reject_purchase BEFORE INSERT ON events "
                         "BEGIN SELECT RAISE(ABORT, 'journal failed')" + chr(59) + ' END')
    with pytest.raises(sqlite3.IntegrityError, match='journal failed'):
        tm_purchase.purchase(emu)
    assert emu.store.get(BARRIER) is None
    assert emu.store.get(PENDING)['decision'] is None
    assert emu.store.latest_state() == source
    assert bought(emu.store, item) == 0
    assert recover_storage(emu.store) is None


def test_interrupted_publication_recovers_without_another_charge(purchase_fixture, monkeypatch):
    emu, _, item, _, _ = purchase_fixture
    original = tm_purchase.recover_storage
    monkeypatch.setattr(tm_purchase, 'recover_storage', lambda _: (_ for _ in ()).throw(OSError('disk failure')))
    with pytest.raises(OSError, match='disk failure'):
        tm_purchase.purchase(emu)
    assert emu.stopping and emu.fatal_error
    assert emu.store.get(PENDING)['phase'] == 'committed'
    assert bought(emu.store, item) == 1
    monkeypatch.setattr(tm_purchase, 'recover_storage', original)
    path = recover_storage(emu.store)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == emu.store.get(PENDING)['sha256']
    assert recover_storage(emu.store) is None
    assert bought(emu.store, item) == 1
    assert len(emu.store.events()) == 1


@pytest.mark.parametrize('change', ['manual', 'paused', 'trade', 'preparation', 'wrong_counter', 'battle', 'menu', 'moving', 'cash', 'recipient'])
def test_purchase_rechecks_safe_point_and_current_recipient(purchase_fixture, monkeypatch, change):
    emu, before, item, _, source = purchase_fixture
    if change == 'manual':
        emu.manual_mode = True
    elif change == 'paused':
        emu.paused = True
    elif change == 'trade':
        emu.store.set('trade_hold', 'transaction')
    elif change == 'preparation':
        emu.store.set('interaction_preparation', {'phase': 'travelling'})
    elif change == 'moving':
        emu.pb.memory[0xcfc5] = 1
    else:
        changes = {'wrong_counter': {'x': 5}, 'battle': {'in_battle': 1}, 'menu': {'textbox': True},
                   'cash': {'money': 0}, 'recipient': {'party': (replace(before.party[0], nick='Other'),)}}
        monkeypatch.setattr(tm_purchase, 'read_snapshot', lambda *_: replace(before, **changes[change]))
    assert tm_purchase.purchase(emu) is None
    assert emu.store.latest_state() == source
    assert bought(emu.store, item) == 0


def test_future_natural_move_is_saved_and_trip_survives_local_recovery(shop_data):
    pikachu = live(partner('PIKACHU', level=35, moves=[84, 0, 0, 0]))
    assert tm_shop.improvement(pikachu, 225, {225: 87}, {pikachu.species: {225}}) is None
    policy = StrategicPolicy(1)
    policy.tm_moves, policy.tm_compatible = shop_data
    s = shopper()
    goal = Goal('collect_plan', 'Plan', 'Choose a project')
    policy._tm_development(s, goal, False)
    planned = policy.tm_plan.copy()
    policy._recover(s)
    assert policy.tm_plan == planned
    policy._tm_development(replace(s, frame=policy.tm_deadline + 1), goal, False)
    assert policy.tm_plan is None


def test_tm_trip_is_not_overridden_by_collection_or_ground_pickups(shop_data, monkeypatch):
    policy = StrategicPolicy(1)
    policy.tm_moves, policy.tm_compatible = shop_data
    policy.goal = Goal('collect_plan', 'Plan', 'Choose a project')
    s = shopper(items=((ITEMS['POKE_BALL'], 20), (ITEMS['FULL_RESTORE'], 10)),
                party=(live(partner(moves=[57, 105, 33, 0])),))
    def unexpected(*args, **kwargs):
        raise AssertionError('A TM trip should keep its own destination')
    monkeypatch.setattr(policy.collection, 'choose', unexpected)
    monkeypatch.setattr(policy.pickups, 'choose', unexpected)
    action = policy._overworld(s, bytearray(65536))
    assert policy.goal.key == 'buy_tm'
    assert action[0].button is None


def test_reset_keeps_verified_cartridge_capability_but_discards_shopping_plan(shop_data):
    policy = StrategicPolicy(1)
    policy.tm_moves, policy.tm_compatible = shop_data
    policy.tm_plan = {'item': 213}
    policy.reset()
    assert (policy.tm_moves, policy.tm_compatible) == shop_data
    assert policy.tm_plan is None


def test_greedy_projection_can_prefer_level_50_over_level_100():
    low = live(partner('STARMIE', level=50))
    high = live(partner('BUTTERFREE', level=100))
    moves, compatible = {229: 94}, {low.species: {229}, high.species: {229}}
    # The previous current-level weighting picked Butterfree here.
    assert (tm_shop.improvement(high, 229, moves, compatible)
            > tm_shop.improvement(low, 229, moves, compatible) * 0.5)
    s = shopper(party=(high, low), items=((229, 1),))
    assert tm_shop.choose(s, moves, compatible, owned=True)['target'] == 1
    assert tm_shop.choose(replace(s, items=()), moves, compatible, owned=False)['target'] == 1


def test_projection_normalizes_level_and_training_but_keeps_actual_dvs():
    moves, compatible = {229: 94}, {152: {229}}
    unfinished = live(partner(level=50, stat_exp=[0] * 5))
    mature = live(partner(level=100))
    early = tm_shop.projected_upgrade(unfinished, 229, moves, compatible)
    late = tm_shop.projected_upgrade(mature, 229, moves, compatible)
    assert early and late
    assert (early['before'], early['after']) == (late['before'], late['after'])
    weak_special = live(partner(level=100, dvs=[11, 13, 14, 9, 0]))
    weaker = tm_shop.projected_upgrade(weak_special, 229, moves, compatible)
    assert weaker['gain'] < late['gain']
    assert tm_shop.choose(shopper(party=(weak_special, unfinished), items=((229, 1),)),
                          moves, compatible, owned=True)['target'] == 1


def test_mature_ranking_still_refuses_low_levels_unknown_dvs_and_natural_moves():
    moves, compatible = {229: 94}, {152: {229}}
    s = shopper(party=(live(partner(level=49)),), items=((229, 1),))
    assert tm_shop.choose(s, moves, compatible, owned=True) is None
    assert tm_shop.choose(replace(s, party=(live(partner(level=50)),)), moves, compatible, owned=True)
    assert tm_shop.choose(replace(s, party=(replace(s.party[0], level=100, dvs=()),)),
                          moves, compatible, owned=True) is None
    slowbro = live(partner('SLOWBRO', level=50))
    assert tm_shop.projected_upgrade(slowbro, 229, moves, {slowbro.species: {229}}) is None


def test_greedy_choice_reassesses_after_one_tm_is_taught():
    first = live(partner('STARMIE', level=50))
    second = live(partner('BUTTERFREE', level=100))
    moves, compatible = {229: 94}, {first.species: {229}, second.species: {229}}
    s = shopper(party=(first, second), items=((229, 2),))
    assert tm_shop.choose(s, moves, compatible, owned=True)['target'] == 0
    taught = replace(first, moves=(33, 94, 0, 0))
    after = replace(s, party=(taught, second), items=((229, 1),))
    assert tm_shop.choose(after, moves, compatible, owned=True)['target'] == 1
