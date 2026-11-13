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
        self.monitor_tables, self.clock = {}, 0
        self.refused = list(refused)

    def trade_preferences(self):
        return {}

    def allowed(self, task, snapshot):
        return task not in self.refused


BEST = mon(0, dvs=(15, 15, 15, 15, 15))
PARTY = [mon(None, box=None, species=1)] * 5


def rows(policy, view):
    return {(unit.detail.position, unit.action): unit.value for unit in ledger.box_units(policy, view)}


def score(policy, view, position):
    """The PC score (pcvalue.py) of the boxed Pokémon at ``position``."""
    from pokesim.gen2.release import release_rated
    return next(row.score for row in release_rated(policy, view) if row.entry.slot and row.entry.slot[1] == position)


def roomy(view):
    """``view`` with room left in the open box, so no refill is due."""
    from pokesim.planning.ledger import BOX_REFILL
    view.box_counts = (BOX_CAPACITY - BOX_REFILL,) + (BOX_CAPACITY,) * 13
    return view


def worth(policy, view, position):
    """The worth box_units gives the boxed Pokémon at ``position`` before its item and box change: its
    place in the PC visit when a refill takes it, otherwise after the visit by its score."""
    from pokesim.gen2.release import release_rated
    from pokesim.pcvalue import releases, requested
    from pokesim.planning.ledger import box_wanted
    rated = release_rated(policy, view)
    needed = max(box_wanted(ledger.headroom(view), True), len(requested(rated)), 1)
    visit = [row.entry.slot[1] for row in releases(rated, needed, view.active_box)]
    return visit.index(position) if position in visit else len(visit) + score(policy, view, position)


def test_spares_are_worth_their_score_and_the_item_they_would_lose():
    plain = mon(1)
    trained = mon(2, stat_exp=(20000, 0, 0, 0, 0))
    berry = mon(3, held_item=BERRY)
    stone = mon(4, held_item=EVERSTONE)
    view = snapshot([BEST, plain, trained, berry, stone], PARTY)
    value = {position: ledger.PLAIN + worth(Policy(), view, position) for position in range(1, 5)}
    assert value[2] > value[1]
    assert rows(Policy(), view) == {
        (1, 'release'): value[1],
        (2, 'release'): value[2],
        # A Bitter Berry no plan wants may go with its holder, but taking it off first costs less.
        (3, 'release'): ledger.HELD + value[3] + 20,
        (3, 'unequip'): ledger.HELD + value[3],
        # An Everstone a plan uses never leaves with its holder.
        (4, 'unequip'): ledger.HELD + value[4],
    }
    # The bag already holds Bitter Berries, so losing one costs half its price.
    view = snapshot([BEST, berry], PARTY, items=[(BERRY, 3)])
    assert rows(Policy(), view)[(3, 'release')] == ledger.HELD + ledger.PLAIN + worth(Policy(), view, 3) + 10


def test_a_spare_standing_down_skips_the_unequip_route():
    from pokesim.gen2.standdown import stand_down
    policy = Policy()
    berry = mon(3, held_item=BERRY)
    stand_down(policy, ledger.unequip_key(berry))
    view = snapshot([BEST, berry], PARTY)
    assert rows(policy, view) == {(3, 'release'): ledger.HELD + ledger.PLAIN + worth(policy, view, 3) + 20}


def test_the_cheapest_spare_goes_and_unequip_waits_for_a_party_slot():
    policy = Policy()
    berry = mon(3, held_item=BERRY)
    trained = mon(2, stat_exp=(100000, 0, 0, 0, 0))
    # With room left only the cheapest goes in this visit. A refill would take all of them anyway.
    unit = ledger.storage_unit(policy, roomy(snapshot([BEST, trained, berry], PARTY)))
    assert (unit.action, unit.detail) == ('unequip', berry)
    # With six in the party nobody can be withdrawn, so the holder goes with its berry.
    unit = ledger.storage_unit(policy, roomy(snapshot([BEST, trained, berry], PARTY + [mon(None, box=None, species=2)])))
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


# Every Release built in pokesim/gen2, by how it meets the one release rule (release.may_release).
# 'menu': it becomes policy.menu, and Policy.menu_step asks the rule before the first press.
# 'checked': its function asks may_release itself, for a runner that presses outside menu_step.
# 'probe': a key for policy.allowed that never runs.
RELEASE_SITES = {('ledger.py', 'unequip_step'): 'menu', ('ledger.py', 'release_step'): 'menu',
                 ('ledger.py', 'storage_unit'): 'probe', ('policy/storage.py', 'trade_spare'): 'probe',
                 ('preparation.py', 'make_room'): 'checked', ('teams.py', 'arrive'): 'menu',
                 ('training.py', 'arrive'): 'menu'}


def release_sites():
    import ast
    from pathlib import Path
    import pokesim.gen2
    sites = {}
    root = Path(pokesim.gen2.__file__).parent
    for path in sorted(root.rglob('*.py')):
        for function in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
                if any(getattr(call.func, 'id', None) == 'Release' for call in calls):
                    sites[path.relative_to(root).as_posix(), function.name] = function
    return sites


def test_every_gen2_release_meets_the_release_rule_before_it_presses():
    # A new path that builds a Release fails here until it is listed with how it meets the rule.
    import ast
    sites = release_sites()
    assert set(sites) == set(RELEASE_SITES)
    for site, kind in RELEASE_SITES.items():
        names = {getattr(node, 'id', getattr(node, 'attr', None)) for node in ast.walk(sites[site])}
        if kind == 'menu':
            assert 'menu' in names, site
        elif kind == 'checked':
            assert 'may_release' in names, site
        else:
            assert 'allowed' in names, site


def test_unequip_walks_the_spare_through_the_party_and_back():
    from pokesim.pcvalue import VisitTeam
    policy = Policy()
    policy.visit_team = VisitTeam()
    policy.visit_team.observe(7, set())
    berry = mon(3, box=2, held_item=BERRY)
    identity = ledger.member(berry)
    policy.collection['unequip'] = identity
    assert ledger.unequip_step(policy, snapshot([berry], PARTY)) == 'a'
    assert policy.menu == ChangeBox(2)
    assert ledger.unequip_step(policy, snapshot([berry], PARTY, active_box=2)) == 'a'
    assert policy.menu == Storage('WITHDRAW', 3, 5)
    # Its party stint is an errand, so the visit does not count it as a team member at its release.
    assert policy.visit_team.observe(7, {(16, berry.dvs)}) == frozenset()
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
    view = snapshot([BEST, stone, other], FULL)
    cost = ledger.HELD + ledger.PLAIN + worth(Policy(), view, 3)
    assert rows(Policy(), view) == {(3, 'release'): cost + 200, (3, 'unequip'): cost}
    unit = ledger.storage_unit(Policy(), view)
    assert (unit.action, unit.detail) == ('release', stone)
    bagged = rows(Policy(), snapshot([BEST, stone], FULL, items=[(EVERSTONE, 1)]))
    assert bagged[(3, 'release')] == cost + 100
    # A plain spare still goes first.
    plain = mon(1)
    assert ledger.storage_unit(Policy(), snapshot([BEST, plain, stone, other], FULL)).detail == plain


PEARL = 110


def test_a_shiny_spare_goes_after_a_plain_spare_holding_a_dear_item():
    # The plain spare's Pearl costs more than the shiny's score, and a full party cannot take it off.
    # A shiny with no item still goes only once every plain spare is gone (pcvalue.WEIGHTS).
    from pokesim.gen2.release import release_rated
    policy = Policy()
    policy.data.item_attributes[PEARL] = {'price': 1400, 'pocket': 'ITEM'}
    shiny, other = mon(1, dvs=(0, 14, 10, 10, 10)), mon(4, dvs=(0, 6, 10, 10, 10))
    pearl = mon(2, held_item=PEARL)
    stored = [BEST, shiny, pearl, mon(3, dvs=(8, 15, 10, 10, 10)), other]
    # With room left the visit takes one spare. With every box full it takes all three.
    for view in (roomy(snapshot(stored, FULL)), snapshot(stored, FULL)):
        status = {row.entry.slot: row.status for row in release_rated(policy, view)}
        assert status[0, 1] == status[0, 4] == 'spare'
        units = ledger.box_units(policy, view)
        dearest = max(unit.value for unit in units if unit.detail is pearl)
        assert all(unit.value > dearest for unit in units if unit.detail in (shiny, other))
        unit = ledger.storage_unit(policy, view)
        assert (unit.action, unit.detail) == ('release', pearl)


def test_the_last_wanted_item_stays_and_a_free_slot_keeps_the_unequip_route():
    stone, other = mon(3, held_item=EVERSTONE), mon(4, species=19, held_item=EVERSTONE)
    # The only Everstone never leaves.
    assert ledger.storage_unit(Policy(), snapshot([BEST, stone], FULL)) is None
    # With a free party slot the stone comes off first instead.
    assert [unit.action for unit in ledger.box_units(Policy(), snapshot([BEST, stone, other], PARTY))] == ['unequip']
    # A full party cannot take it off whatever room the boxes have, so the spare may go with its stone.
    room = snapshot([BEST, stone, other], FULL)
    room.box_counts = (BOX_CAPACITY - 1,) + (BOX_CAPACITY,) * 13
    assert [unit.action for unit in ledger.box_units(Policy(), room)] == ['release', 'unequip']


def test_a_full_party_lets_a_held_spare_go_before_a_copy_kept_for_trade():
    # A linked adventure misses Pidgey, so the second Pidgey is kept for trade. The spare Rattata holds
    # an Everstone a plan wants, and the best Rattata holds another. Six in the party cannot withdraw
    # the spare to take its stone off, so it goes with the stone while the boxes still have room. The
    # Pidgey went instead, and the Pokédex hunt caught it again.
    from pokesim.gen2.release import release_rated
    from pokesim.planning.ledger import BOX_REFILL
    policy = Policy()
    policy.demand = {16: 1}
    kept = mon(1)
    stone = mon(3, species=19, held_item=EVERSTONE)
    other = mon(4, species=19, dvs=(15, 15, 15, 15, 15), held_item=EVERSTONE)
    # One slot short of the refill mark, so the visit takes only the spare.
    view = snapshot([BEST, kept, stone, other], FULL)
    view.box_counts = (BOX_CAPACITY - BOX_REFILL + 1,) + (BOX_CAPACITY,) * 13
    status = {row.entry.slot: (row.status, row.reason) for row in release_rated(policy, view)}
    assert status[0, 1] == ('kept', 'For trade') and status[0, 3][0] == 'spare'
    for direct in (False, True):
        unit = ledger.storage_unit(policy, view, direct=direct)
        assert (unit.action, unit.detail) == ('release', stone)
    # With a party slot free the stone comes off first, and the Pidgey still stays.
    view.party = list(PARTY)
    unit = ledger.storage_unit(policy, view)
    assert (unit.action, unit.detail) == ('unequip', stone)


def test_a_spare_in_another_box_costs_a_box_change():
    best = mon(0, box=1, dvs=(15, 15, 15, 15, 15))
    here, away = mon(1, box=0), mon(2, box=1, dvs=(3, 3, 3, 3, 3))
    view = snapshot([best, here, away], PARTY)
    assert rows(Policy(), view) == {(1, 'release'): ledger.PLAIN + worth(Policy(), view, 1),
                                    (2, 'release'): ledger.PLAIN + worth(Policy(), view, 2) + ledger.BOX_CHANGE}
    # The weaker copy waits in box 1, but the one in the open box goes first.
    assert ledger.storage_unit(Policy(), snapshot([best, here, away], PARTY)).detail == here


class Owned(Policy):
    def __init__(self, partners):
        super().__init__()
        self.partners = partners

    def release_owners(self):
        from pokesim.trade.partners import owners
        return owners(4321, self.partners)


def test_a_copy_from_an_unknown_trainer_is_worth_more_than_one_from_a_linked_adventure():
    from pokesim.pcvalue import WEIGHTS
    traded = mon(1, trainer_id=13132)
    # A plainer spare is the one this visit takes, so the traded copy is worth its score.
    view = roomy(snapshot([BEST, traded, mon(2, dvs=(0, 2, 2, 2, 2))], PARTY))
    linked = rows(Owned(frozenset({13132})), view)[(1, 'release')]
    assert linked == ledger.PLAIN + worth(Owned(frozenset({13132})), view, 1)
    assert rows(Owned(frozenset()), view)[(1, 'release')] == linked + WEIGHTS['traded']


def test_release_owners_reads_the_player_and_the_linked_adventures():
    from pokesim.gen2.policy import Policy as Gen2Policy
    fake = SimpleNamespace(memory=None, data=None, trade_partners=lambda: frozenset({13132}))
    assert Gen2Policy.release_owners(fake) is None
    from pokesim.trade import partners
    assert partners.owners(47325, frozenset({13132})) == {47325, 13132}


def visit(party_size, room):
    from pokesim.gen2.policy import Goal, Policy as Gen2Policy
    view = SimpleNamespace(party=[mon(None, box=None)] * party_size, stored=[], map=1, bug_contest=False,
                           box_counts=(BOX_CAPACITY - room,) + (BOX_CAPACITY,) * 13)
    fake = SimpleNamespace(collection={}, monitor_tables={}, clock=0, in_league=lambda view: False, in_transmitter_room=lambda view: False,
                           data=SimpleNamespace(map_ids={'POKECENTER_2F': 2}), storage_target=lambda view: object(),
                           storage_goal=lambda view: Goal('storage', 'PC', 'GOLDENROD_POKECENTER_1F', 1, 1))
    memory = SimpleNamespace(byte=lambda name: 0)
    return Gen2Policy.release_goal(fake, view, memory)


def test_a_free_party_slot_counts_as_room_before_a_release_visit_starts():
    from pokesim.planning.ledger import BOX_RESERVE
    assert visit(6, BOX_RESERVE - 1).key == 'collection_release'
    # A PC errand that deposits one partner before withdrawing another leaves the party a slot short.
    assert visit(5, BOX_RESERVE - 1) is None
