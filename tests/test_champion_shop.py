"""Walking offers and native supply planning share durable purchase guarantees."""
from contextlib import closing
from dataclasses import replace

import pytest

from pokesim import champion_shop as shop
from pokesim.legendary_returns import STEPS
from pokesim.runtime import tm_purchase
from pokesim.store import Store
from pokesim.strategy_data import ITEMS
from test_tm_shop import purchase_fixture, shop_data, shopper, bought
from test_battle_power import live, partner


def test_offers_start_after_champion_and_cap_without_banking(tmp_path):
    with closing(Store(tmp_path)) as store:
        store.set(STEPS, {'total': 4000000, 'available': True})
        shop.observe(store, shopper(hall_of_fame_count=0))
        assert not shop.status(store)['started']
        shop.observe(store, shopper())
        assert not shop.ready(store)
        store.set(STEPS, {'total': 4999999, 'available': True})
        assert not shop.ready(store)
        store.set(STEPS, {'total': 5000000, 'available': True})
        assert shop.ready(store) == set(shop.OFFERS)
        # An arbitrarily long wait still earns only one purchase of each offer.
        store.set(STEPS, {'total': 19000000, 'available': True})
        shop.observe(store, shopper())
        with store.db:
            shop.consume(store.db, ITEMS['MASTER_BALL'])
        assert shop.ready(store) == {ITEMS['RARE_CANDY']}
        with pytest.raises(ValueError, match='not ready'):
            shop.consume(store.db, ITEMS['MASTER_BALL'])
        progress = shop.status(store)['offers'][0]
        assert progress['remaining'] == 1000000 and progress['purchased'] == 1
        # Reading a restored cartridge state cannot rewind the durable offer.
        shop.observe(store, shopper(frame=1))
        assert shop.status(store)['offers'][0] == progress
        store.set(STEPS, {'total': 20000000, 'available': True})
        assert shop.ready(store) == set(shop.OFFERS)


def test_regular_supplies_and_offer_guards():
    s = shopper(money=200000)
    assert shop.choose(s, set())['item'] not in shop.OFFERS
    plan = shop.choose(s, set(shop.OFFERS))
    assert plan['item'] == ITEMS['MASTER_BALL'] and plan['quantity'] == 1
    assert not shop.valid_plan(replace(s, money=119999), plan, set(shop.OFFERS))
    assert not shop.valid_plan(s, plan, set())
    assert not shop.valid_plan(replace(s, hall_of_fame_count=0), plan, set(shop.OFFERS))
    assert not shop.valid_plan(replace(s, items=((ITEMS['MASTER_BALL'], 1),)), plan, set(shop.OFFERS))
    assert not shop.valid_plan(replace(s, items=tuple((i, 1) for i in range(1, 21))), plan, set(shop.OFFERS))
    candies = shop.choose(replace(s, items=((ITEMS['MASTER_BALL'], 1),)), set(shop.OFFERS))
    assert candies['item'] == ITEMS['RARE_CANDY'] and candies['quantity'] == 5
    assert not shop.valid_plan(s, {**candies, 'quantity': 99}, set(shop.OFFERS))
    maxed = replace(s, party=(replace(s.party[0], level=100),))
    assert shop.recipient(maxed, ITEMS['RARE_CANDY']) is None


def test_pp_ups_target_established_useful_moves_below_native_cap():
    mon = replace(live(partner(level=80, moves=[57, 33, 0, 0])), max_pp=(15, 35, 0, 0))
    assert shop.pp_slot(mon) == 0
    assert shop.pp_slot(replace(mon, max_pp=(24, 35, 0, 0))) is None
    assert shop.pp_slot(replace(mon, level=30)) is None
    assert shop.pp_slot(replace(mon, hp=0)) is None
    assert shop.pp_slot(replace(mon, max_pp=())) is None
    assert shop.pp_slot(replace(mon, moves=(89, 153, 0, 0), max_pp=(10, 5, 0, 0))) == 0


def test_supply_purchase_keeps_last_bag_slot_free():
    s = shopper(items=tuple((item, 1) for item in range(201, 219)))
    plan = shop.choose(s, set())
    assert plan and shop.valid_plan(s, plan, set())
    crowded = replace(s, items=s.items + ((219, 1),))
    assert shop.choose(crowded, set(shop.OFFERS)) is None
    assert not shop.valid_plan(crowded, plan, set())


def test_moon_stones_replenish_for_held_evolution_candidates():
    mon = live(partner('CLEFAIRY', level=40))
    s = shopper(party=(mon,), owned=frozenset())
    assert shop.recipient(s, ITEMS['MOON_STONE']) == 0
    assert shop.recipient(replace(s, owned=frozenset({36})), ITEMS['MOON_STONE']) == 0
    assert shop.recipient(shopper(), ITEMS['MOON_STONE']) is None


@pytest.mark.parametrize('failure', [None, 'commit', 'publication'])
def test_candy_bundle_and_offer_are_one_recoverable_purchase(purchase_fixture, monkeypatch, failure):
    import sqlite3
    from pokesim.runtime.reward_delivery import BARRIER, recover_storage
    from pokesim.ram import W_BAG_ITEMS
    emu, before, _, memory, source = purchase_fixture
    item = ITEMS['RARE_CANDY']
    emu.store.set(STEPS, {'total': 0, 'available': True})
    shop.observe(emu.store, before)
    emu.store.set(STEPS, {'total': 1000000, 'available': True})
    plan = {'item': item, 'target': 0, 'signature': shop.signature(before.party[0]), 'supply': True, 'quantity': 5}
    emu.policy.tm_plan = plan
    expected = replace(before, money=before.money - shop.PRICES[item], items=before.items + ((item, 5),))
    monkeypatch.setattr(tm_purchase, 'read_snapshot', lambda mem, frame: before if mem is emu.pb.memory else expected)
    if failure == 'commit':
        emu.store.db.execute("CREATE TRIGGER reject_purchase BEFORE INSERT ON events "
                             "BEGIN SELECT RAISE(ABORT, 'journal failed')" + chr(59) + ' END')
        with pytest.raises(sqlite3.IntegrityError):
            tm_purchase.purchase(emu)
        assert bought(emu.store, item) == 0
        assert item in shop.ready(emu.store)
        assert emu.store.get(BARRIER) is None
        assert emu.store.latest_state() == source
        return
    if failure == 'publication':
        monkeypatch.setattr(tm_purchase, 'recover_storage', lambda _: (_ for _ in ()).throw(OSError('disk failure')))
        with pytest.raises(OSError):
            tm_purchase.purchase(emu)
        assert recover_storage(emu.store)
    else:
        tm_purchase.purchase(emu)
    assert bought(emu.store, item) == 5
    assert item not in shop.ready(emu.store)
    assert shop.status(emu.store)['offers'][1]['remaining'] == 1000000
    offset = W_BAG_ITEMS + len(before.items) * 2
    assert memory[offset:offset + 3] == bytes((item, 5, 255))
    assert len(emu.store.events()) == 1
    assert recover_storage(emu.store) is None


def test_pp_up_menu_is_distinct_from_battle_and_move_replacement():
    from pokesim.screen import Screen
    from test_strategy import menu
    s = shopper(textbox=True)
    memory = menu({8: '      SURF', 9: '      PSYCHIC', 14: ' Raise PP of which', 16: ' technique'},
                  (5, 8), top=(5, 7))
    assert Screen(memory).kind(s) == 'item_moves'
    learning = menu({8: '      SURF', 14: ' Which move should', 16: ' be forgotten'},
                    (5, 8), top=(5, 7))
    assert Screen(learning).kind(s) == 'learn_move'


def test_policy_routes_supply_and_uses_owned_pp_up(shop_data):
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.policies.progression import Goal
    policy = StrategicPolicy(1)
    policy.tm_moves, policy.tm_compatible = shop_data
    mon = replace(live(partner(level=90, moves=[57, 58, 85, 94])), max_pp=(15, 10, 15, 10))
    s = shopper(party=(mon,))
    goal = Goal('collect_plan', 'Plan', 'Choose a project')
    result, action = policy._tm_development(s, goal, False)
    assert result.key == 'buy_tm' and action is None
    assert policy.tm_plan['item'] == ITEMS['PP_UP']
    policy.on_restore()
    result, action = policy._tm_development(replace(s, items=((ITEMS['PP_UP'], 1),)), goal, False)
    assert result.key == 'teach_supply' and action[0].button == 'start'
    assert policy.intent.target == 0


def test_box_list_with_pp_in_a_nickname_is_not_the_pp_up_menu():
    """A storage list showing DAMPPILOT must stay a list, or the PC release loops forever."""
    from pokesim.screen import Screen
    from test_strategy import menu
    s = shopper(textbox=True)
    memory = menu({4: '    TUBAJURY', 6: '    OATKNIGHT', 8: '    NACHODEPT', 10: '    DAMPPILOT', 12: '    CANCEL'},
                  (5, 8), top=(5, 4))
    assert Screen(memory).kind(s) == 'list'
