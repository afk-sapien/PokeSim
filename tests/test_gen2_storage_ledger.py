"""Full Gen II boxes free a slot through the resource ledger, taking a held item off first when it can."""
from types import SimpleNamespace

import pytest

from pokesim.gen2 import ledger
from pokesim.gen2.menus import ChangeBox, Release, Storage, Take
from pokesim.gen2.release import BOX_CAPACITY

BERRY, EVERSTONE = 83, 112


@pytest.fixture(autouse=True)
def no_breeding_stock(monkeypatch):
    monkeypatch.setattr('pokecore.gen2.breeding.breeding_stock', lambda data, species: set())


def mon(position, *, box=0, dvs=(4, 4, 4, 4, 4), **extra):
    fields = dict(species=16, egg=False, box=box, position=position, trainer_id=4321, dvs=dvs, level=20,
                  held_item=0, experience=8000, stat_exp=(0,) * 5)
    fields.update(extra)
    return SimpleNamespace(**fields)


def snapshot(stored, party=(), *, active_box=0, items=()):
    return SimpleNamespace(party=list(party), stored=list(stored), active_box=active_box, money=0,
                           box_counts=(BOX_CAPACITY,) * 14, pockets={'items': tuple(items)})


class Policy:
    def __init__(self, refused=()):
        self.data = SimpleNamespace(
            items={'EVERSTONE': EVERSTONE, 'BITTER_BERRY': BERRY}, item_names={}, species={},
            item_attributes={BERRY: {'price': 20, 'pocket': 'ITEM'}, EVERSTONE: {'price': 200, 'pocket': 'ITEM'}})
        self.demand, self.collection, self.decisions, self.menu = {}, {}, 0, None
        self.refused = list(refused)

    def trade_preferences(self):
        return {}

    def allowed(self, task, snapshot):
        return task not in self.refused


BEST = mon(0, dvs=(15, 15, 15, 15, 15))
PARTY = [mon(None, box=None, species=1)] * 5


def rows(policy, view):
    return {(unit.detail.position, unit.action): unit.value for unit in ledger.box_units(policy, view)}


def test_spares_are_worth_their_training_and_the_item_they_would_lose():
    plain = mon(1)
    trained = mon(2, stat_exp=(20000, 0, 0, 0, 0))
    berry = mon(3, held_item=BERRY)
    stone = mon(4, held_item=EVERSTONE)
    found = rows(Policy(), snapshot([BEST, plain, trained, berry, stone], PARTY))
    assert found == {
        (1, 'release'): ledger.PLAIN,
        (2, 'release'): ledger.TRAINED,
        # A Bitter Berry no plan wants may go with its holder, but taking it off first costs less.
        (3, 'release'): ledger.HELD + ledger.PLAIN + 20,
        (3, 'unequip'): ledger.HELD + ledger.PLAIN,
        # An Everstone a plan uses never leaves with its holder.
        (4, 'unequip'): ledger.HELD + ledger.PLAIN,
    }
    # The bag already holds Bitter Berries, so losing one costs half its price.
    found = rows(Policy(), snapshot([BEST, berry], PARTY, items=[(BERRY, 3)]))
    assert found[(3, 'release')] == ledger.HELD + ledger.PLAIN + 10


def test_a_spare_standing_down_skips_the_unequip_route():
    from pokesim.gen2.standdown import stand_down
    policy = Policy()
    berry = mon(3, held_item=BERRY)
    stand_down(policy, ledger.unequip_key(berry))
    assert rows(policy, snapshot([BEST, berry], PARTY)) == {(3, 'release'): ledger.HELD + ledger.PLAIN + 20}


def test_the_cheapest_spare_goes_and_unequip_waits_for_a_party_slot():
    policy = Policy()
    berry = mon(3, held_item=BERRY)
    trained = mon(2, stat_exp=(20000, 0, 0, 0, 0))
    unit = ledger.storage_unit(policy, snapshot([BEST, trained, berry], PARTY))
    assert (unit.action, unit.detail) == ('unequip', berry)
    # With six in the party nobody can be withdrawn, so the holder goes with its berry.
    unit = ledger.storage_unit(policy, snapshot([BEST, trained, berry], PARTY + [mon(None, box=None, species=2)]))
    assert (unit.action, unit.detail) == ('release', berry)
    # A plain spare goes before any of them.
    plain = mon(1)
    assert ledger.storage_unit(policy, snapshot([BEST, plain, trained, berry], PARTY)).detail == plain
    # A direct caller only takes spares it can release from the box.
    assert ledger.storage_unit(policy, snapshot([BEST, trained, berry], PARTY), direct=True).action == 'release'


def test_only_spares_the_pc_allows_are_offered():
    berry = mon(3, held_item=BERRY)
    policy = Policy(refused=[Release(0, 3)])
    assert ledger.storage_unit(policy, snapshot([BEST, berry], PARTY)) is None


def test_unequip_walks_the_spare_through_the_party_and_back():
    policy = Policy()
    berry = mon(3, box=2, held_item=BERRY)
    identity = ledger.member(berry)
    policy.collection['unequip'] = identity
    assert ledger.unequip_step(policy, snapshot([berry], PARTY)) == 'a'
    assert policy.menu == ChangeBox(2)
    assert ledger.unequip_step(policy, snapshot([berry], PARTY, active_box=2)) == 'a'
    assert policy.menu == Storage('WITHDRAW', 3, 5)
    party = mon(None, box=None, held_item=BERRY)
    assert ledger.unequip_step(policy, snapshot([], PARTY + [party], active_box=2)) == 'a'
    assert policy.menu == Take(5, identity[1:])
    bare = mon(None, box=None)
    assert ledger.unequip_step(policy, snapshot([], PARTY + [bare], active_box=2)) == 'a'
    assert policy.menu == Storage('DEPOSIT', 5, 6)
    back = mon(7, box=2)
    assert ledger.unequip_step(policy, snapshot([back], PARTY, active_box=2)) == 'a'
    assert policy.menu == Release(2, 7, identity)
    # Once it is gone the route is done.
    policy.menu = None
    assert ledger.unequip_step(policy, snapshot([], PARTY, active_box=2)) is None
    assert 'unequip' not in policy.collection and policy.menu is None


def test_taking_an_item_closes_the_pc_text_left_by_the_withdrawal():
    take = Take(5, ledger.member(mon(3))[1:])
    assert take.approach('dialogue') == 'b'
    assert take.approach('pc') == 'b'


def test_a_refused_step_stands_the_spare_down():
    from pokesim.gen2.standdown import standing_down
    berry = mon(3, held_item=BERRY)
    policy = Policy(refused=[Storage('WITHDRAW', 3, 5)])
    policy.collection['unequip'] = ledger.member(berry)
    assert ledger.unequip_step(policy, snapshot([berry], PARTY)) is None
    assert 'unequip' not in policy.collection
    assert standing_down(policy, ledger.unequip_key(berry))
    # A spare refused once it is in the party goes back to its box before the route ends.
    party = mon(None, box=None, held_item=BERRY)
    policy = Policy(refused=[Take(5, ledger.member(berry)[1:])])
    policy.collection['unequip'] = ledger.member(berry)
    assert ledger.unequip_step(policy, snapshot([], PARTY + [party])) == 'a'
    assert policy.menu == Storage('DEPOSIT', 5, 6)
    assert policy.collection['unequip_return'] and standing_down(policy, ledger.unequip_key(berry))
    # Still refused or not, the return trip keeps depositing until it is boxed.
    assert ledger.unequip_step(policy, snapshot([], PARTY + [party])) == 'a'
    assert policy.menu == Storage('DEPOSIT', 5, 6)
    policy.menu = None
    assert ledger.unequip_step(policy, snapshot([mon(9, held_item=BERRY)], PARTY)) is None
    assert 'unequip' not in policy.collection and 'unequip_return' not in policy.collection
    assert policy.menu is None
    # A full party drops the route without standing the spare down.
    policy = Policy()
    policy.collection['unequip'] = ledger.member(berry)
    assert ledger.unequip_step(policy, snapshot([berry], PARTY + [mon(None, box=None, species=2)])) is None
    assert 'unequip' not in policy.collection and not standing_down(policy, ledger.unequip_key(berry))
