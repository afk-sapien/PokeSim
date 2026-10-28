"""The resource ledger holds reservations and answers a shortfall with the units worth least."""
import logging
from types import SimpleNamespace

from pokesim.planning.ledger import BOX, MONEY, PARTY, PRICELESS, Ledger, Need, Resources, Shortfall, Unit


def books(free, units=(), money=0):
    resources = Resources(free, money, tuple(units))
    ledger = Ledger(lambda snapshot, kinds: resources)
    ledger.snapshot(None)
    return ledger


def test_a_need_that_fits_is_reserved_and_counts_against_the_next_goal():
    ledger = books({BOX: 3, 'items': 1}, money=1000)
    assert ledger.reserve('catch', Need(box_slots=2, money=600)).ok
    short = ledger.reserve('gift', Need(box_slots=2, money=600))
    assert not short.ok and dict(short.missing) == {BOX: 1, MONEY: 200}
    # A goal reserving again replaces its own hold instead of adding to it.
    assert ledger.reserve('catch', Need(box_slots=3)).ok
    ledger.release('catch')
    assert ledger.reserve('gift', Need(box_slots=3, money=1000)).ok


def test_make_room_gives_up_the_units_worth_least_and_never_priceless_or_kept_ones():
    units = [Unit('potion', 'items', 300, 'deposit'), Unit('berry', 'items', 20, 'deposit'),
             Unit('share', 'items', PRICELESS, 'deposit'), Unit('nugget', 'items', 10 ** 7, 'deposit')]
    ledger = books({'items': 0}, units)
    short = ledger.reserve('tidy', Need(pocket_slots={'items': 2}))
    assert [unit.key for unit in ledger.make_room(short)] == ['berry', 'potion']
    assert [unit.key for unit in ledger.make_room(short, keep={'berry'})] == ['potion', 'nugget']
    ledger.reservations['tower'] = Need(keep=frozenset({'potion', 'nugget'}))
    # Only the Berry is left to give, which does not cover two entries.
    assert ledger.make_room(short) == []


def test_a_unit_that_needs_room_of_its_own_brings_that_room_first():
    # Releasing a duplicate takes its Leftovers off first, so the release needs a free bag entry.
    held = Unit('marill', BOX, 1, 'release', needs=Need(pocket_slots={'items': 1}))
    plain = Unit('rattata', BOX, 5, 'release')
    berry = Unit('berry', 'items', 20, 'deposit')
    ledger = books({BOX: 0, 'items': 0}, [held, plain, berry])
    plan = ledger.make_room(Shortfall('catch', {BOX: 1}))
    assert [unit.key for unit in plan] == ['berry', 'marill']
    # Without anything to put away the held one cannot go, so the plain one does.
    ledger = books({BOX: 0, 'items': 0}, [held, plain])
    assert [unit.key for unit in ledger.make_room(Shortfall('catch', {BOX: 1}))] == ['rattata']


def test_money_units_rank_by_worth_per_coin():
    nugget = Unit('nugget', MONEY, 5000, 'sell', amount=5000)
    candy = Unit('candy', MONEY, 2 * 2400, 'sell', amount=2400)
    ledger = books({}, [candy, nugget], money=0)
    assert [unit.key for unit in ledger.make_room(Shortfall('fee', {MONEY: 500}))] == ['nugget']
    assert [unit.key for unit in ledger.make_room(Shortfall('fee', {MONEY: 6000}))] == ['nugget', 'candy']


def test_compare_logs_only_a_different_choice(caplog):
    ledger = books({'items': 0}, [Unit('berry', 'items', 20, 'deposit', detail=173)])
    with caplog.at_level(logging.DEBUG, logger='pokesim.ledger'):
        assert ledger.compare('tidy', 'items', 173) == [173]
        assert not caplog.records
        ledger.compare('tidy', 'items', None)
    assert 'existing check picks None' in caplog.text


def gen2_data():
    from tests.test_gen2_bag_room import data
    d = data()
    for item in range(200, 220):
        d.item_attributes[item] = {'price': 99999, 'pocket': 'ITEM'}
    return d


def gen2_view(rows, filler=True):
    from tests.test_gen2_bag_room import bag
    pockets = bag(*rows, filler=filler)
    pockets['balls'] = ((5, 3),)
    return SimpleNamespace(pockets=pockets, items=pockets['items'], party=(1, 2), stored=(), money=4000,
                           box_counts=(20,) * 13 + (17,))


def test_the_gen2_ledger_reads_every_kind_and_frees_an_entry_only_when_the_item_does_not_stack():
    from pokesim.gen2 import ledger
    d = gen2_data()
    view = gen2_view([(18, 5), (151, 1), (22, 1), (173, 16), (30, 1), (15, 1)])
    resources = ledger.ledger(d).snapshot(view)
    assert resources.available('items') == 0 and resources.available('balls') == 11
    assert resources.available(BOX) == 3 and resources.available(PARTY) == 4 and resources.available(MONEY) == 4000
    assert ledger.needs(d, view, 173) == Need()
    assert ledger.needs(d, view, 110) == Need(pocket_slots={'items': 1})
    # The Berry stacks, so it fits. A Pearl needs the Lucky Punch put away.
    assert ledger.fits(d, view, 173)
    assert [unit.detail for unit in ledger.room(d, view, 'tidy', 110)] == [30]
    full = gen2_view([(57, 1), (18, 5), (151, 1), (22, 1)] * 5, filler=False)
    assert ledger.room(d, full, 'tidy', 30) is None


def test_the_gen1_ledger_sells_in_the_order_the_shop_raises_funds():
    from pokesim.policies import ledger
    from pokesim.policies.shopping import ShoppingController
    from pokesim.strategy_data import ITEMS
    rows = ((ITEMS['POTION'], 3), (ITEMS['NUGGET'], 1), (ITEMS['RARE_CANDY'], 1), (ITEMS['POKE_BALL'], 9))
    for items in (rows, rows[2:], rows[3:], rows[:1] + rows[2:]):
        view = SimpleNamespace(items=items, party=(1,), box_counts=(20,) * 12, money=120)
        books = ledger.ledger()
        books.snapshot(view)
        index = ShoppingController.fund_index(view)
        assert books.compare('fund', MONEY, index) == [index]
