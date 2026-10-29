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


def test_a_release_visit_ends_at_the_refill_mark():
    from pokesim.planning.ledger import BOX_REFILL
    policy = Policy()
    berry = mon(3, held_item=BERRY)
    policy.storage_target = lambda view: ledger.storage_unit(policy, view)
    full = snapshot([BEST, berry], PARTY)
    assert ledger.release_step(policy, full) == 'a'
    assert policy.collection['unequip'] == ledger.member(berry)
    # With the refill mark reached, the spare under way still finishes but no new one starts.
    roomy = snapshot([BEST, berry], PARTY)
    roomy.box_counts = (BOX_CAPACITY - BOX_REFILL,) + (BOX_CAPACITY,) * 13
    policy.menu = None
    assert ledger.release_step(policy, roomy) == 'a' and policy.menu is not None
    policy.collection.clear()
    policy.menu = None
    assert ledger.release_step(policy, roomy) == 'wait'
    assert policy.menu is None and 'unequip' not in policy.collection


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


def test_a_wanted_item_never_leaves_with_its_holder():
    # The Everstone is a breeding item and this is the only one, so its holder is offered only with the
    # item taken off first.
    stone = mon(3, held_item=EVERSTONE)
    for party in (PARTY, PARTY + [mon(None, box=None, species=2)]):
        units = ledger.box_units(Policy(), snapshot([BEST, stone], party))
        assert [unit.action for unit in units] == ['unequip']
        unit = ledger.storage_unit(Policy(), snapshot([BEST, stone], party))
        assert unit is None or unit.action == 'unequip'


FULL = PARTY + [mon(None, box=None, species=2)]


def test_a_full_party_and_full_boxes_let_a_wanted_item_go_while_a_copy_stays():
    # The holder can never be withdrawn, so its Everstone cannot come off. A second Everstone held by
    # another Pokémon, or one in the bag, keeps the item, so the spare may go with its stone.
    stone, other = mon(3, held_item=EVERSTONE), mon(4, species=19, held_item=EVERSTONE)
    found = rows(Policy(), snapshot([BEST, stone, other], FULL))
    assert found == {(3, 'release'): ledger.HELD + ledger.PLAIN + 200, (3, 'unequip'): ledger.HELD + ledger.PLAIN}
    unit = ledger.storage_unit(Policy(), snapshot([BEST, stone, other], FULL))
    assert (unit.action, unit.detail) == ('release', stone)
    bagged = rows(Policy(), snapshot([BEST, stone], FULL, items=[(EVERSTONE, 1)]))
    assert bagged[(3, 'release')] == ledger.HELD + ledger.PLAIN + 100
    # A plain spare still goes first.
    plain = mon(1)
    assert ledger.storage_unit(Policy(), snapshot([BEST, plain, stone, other], FULL)).detail == plain


def test_the_last_wanted_item_stays_and_a_free_slot_keeps_the_unequip_route():
    stone, other = mon(3, held_item=EVERSTONE), mon(4, species=19, held_item=EVERSTONE)
    # The only Everstone never leaves.
    assert ledger.storage_unit(Policy(), snapshot([BEST, stone], FULL)) is None
    # With a free party slot the stone comes off first instead.
    assert [unit.action for unit in ledger.box_units(Policy(), snapshot([BEST, stone, other], PARTY))] == ['unequip']
    # A free box slot also means no release is needed to take the item off later.
    room = snapshot([BEST, stone, other], FULL)
    room.box_counts = (BOX_CAPACITY - 1,) + (BOX_CAPACITY,) * 13
    assert [unit.action for unit in ledger.box_units(Policy(), room)] == ['unequip']


def test_a_spare_in_another_box_costs_a_box_change():
    best = mon(0, box=1, dvs=(15, 15, 15, 15, 15))
    here, away = mon(1, box=0), mon(2, box=1, dvs=(3, 3, 3, 3, 3))
    found = rows(Policy(), snapshot([best, here, away], PARTY))
    assert found == {(1, 'release'): ledger.PLAIN, (2, 'release'): ledger.PLAIN + ledger.BOX_CHANGE}
    # The weaker copy waits in box 1, but the one in the open box goes first.
    assert ledger.storage_unit(Policy(), snapshot([best, here, away], PARTY)).detail == here


class Owned(Policy):
    def __init__(self, partners):
        super().__init__()
        self.partners = partners

    def release_owners(self):
        from pokesim.trade.partners import owners
        return owners(4321, self.partners)


def test_a_copy_from_an_unknown_trainer_is_never_released():
    traded = mon(1, trainer_id=13132)
    assert rows(Owned(frozenset()), snapshot([BEST, traded], PARTY)) == {}
    assert rows(Owned(frozenset({13132})), snapshot([BEST, traded], PARTY)) == {(1, 'release'): ledger.PLAIN}


def test_release_owners_reads_the_player_and_the_linked_adventures():
    from pokesim.gen2.policy import Policy as Gen2Policy
    fake = SimpleNamespace(memory=None, data=None, trade_partners=lambda: frozenset({13132}))
    assert Gen2Policy.release_owners(fake) is None
    from pokesim.trade import partners
    assert partners.owners(47325, frozenset({13132})) == {47325, 13132}


def visit(party_size, room):
    from pokesim.gen2.policy import Goal, Policy as Gen2Policy
    view = SimpleNamespace(party=[mon(None, box=None)] * party_size, stored=[], map=1,
                           box_counts=(BOX_CAPACITY - room,) + (BOX_CAPACITY,) * 13)
    fake = SimpleNamespace(collection={}, in_league=lambda view: False, in_transmitter_room=lambda view: False,
                           data=SimpleNamespace(map_ids={'POKECENTER_2F': 2}), storage_target=lambda view: object(),
                           storage_goal=lambda view: Goal('storage', 'PC', 'GOLDENROD_POKECENTER_1F', 1, 1))
    memory = SimpleNamespace(byte=lambda name: 0)
    return Gen2Policy.release_goal(fake, view, memory)


def test_a_free_party_slot_counts_as_room_before_a_release_visit_starts():
    from pokesim.planning.ledger import BOX_RESERVE
    assert visit(6, BOX_RESERVE - 1).key == 'collection_release'
    # A PC errand that deposits one partner before withdrawing another leaves the party a slot short.
    assert visit(5, BOX_RESERVE - 1) is None
