"""The precondition check: conditions, their enablers and ``feasible``, built from past stuck runs."""
from dataclasses import dataclass, field

from pokesim.planning.conditions import (FEASIBLE, AnyOf, Badge, Event, Feasibility, Item, Reach, Requirements,
                                         feasible, missing, requirements)
from pokesim.planning.ledger import BOX, Ledger, Need, Resources


@dataclass
class World:
    items: set = field(default_factory=set)
    badges: set = field(default_factory=set)
    events: set = field(default_factory=set)
    places: set = field(default_factory=set)

    def has_item(self, item):
        return item in self.items

    def has_badge(self, badge):
        return badge in self.badges

    def event(self, flag):
        return flag in self.events

    def reachable(self, place):
        return place in self.places


@dataclass(frozen=True)
class Goal:
    key: str
    found: Requirements = Requirements()

    def requires(self, world):
        return self.found


def books(free):
    resources = Resources(free, 0, ())
    ledger = Ledger(lambda snapshot, kinds: resources)
    ledger.snapshot(None)
    return ledger


def test_each_condition_reads_its_own_question():
    world = World(items={'BICYCLE'}, badges={2}, events={'EVENT_CINNABAR_GYM_GATE1_UNLOCKED'}, places={'ROUTE_17'})
    assert Item('BICYCLE').holds(world) and not Item('SODA_POP').holds(world)
    assert Badge(2).holds(world) and not Badge(4).holds(world)
    assert Event('EVENT_CINNABAR_GYM_GATE1_UNLOCKED').holds(world)
    assert not Event('EVENT_CINNABAR_GYM_GATE2_UNLOCKED').holds(world)
    assert Reach('ROUTE_17').holds(world) and not Reach('ROUTE_18').holds(world)


def test_conditions_compare_by_value_whatever_their_enabler():
    assert Item('BICYCLE', enable=lambda world: 'shop') == Item('BICYCLE')
    assert len({Badge(8), Badge(8, enable=lambda world: 'gym'), Badge(16)}) == 2


def test_a_cycling_road_gate_without_a_bicycle_is_closed_and_names_the_errand():
    # #153: a run with no Bicycle paced the Route 18 gate until the explore project timed out.
    bike = Item('BICYCLE', enable=lambda world: 'get_bicycle')
    gate = Goal('route_18_gate', Requirements((bike,)))
    answer = feasible(gate, World())
    assert not answer and answer.missing == (bike,) and answer.enablers == ('get_bicycle',)
    assert feasible(gate, World(items={'BICYCLE'})) is FEASIBLE


def test_any_drink_opens_the_saffron_gates():
    drink = AnyOf((Event('saffron_open'), Item('FRESH_WATER'), Item('SODA_POP'), Item('LEMONADE', enable=lambda world: 'buy_drink')))
    assert not drink.holds(World())
    assert drink.enabler(World()) == 'buy_drink'
    assert drink.holds(World(items={'SODA_POP'})) and drink.holds(World(events={'saffron_open'}))
    # Its own enabler goes before those of its options.
    assert AnyOf((Item('LEMONADE', enable=lambda world: 'buy_drink'),), enable=lambda world: 'vending').enabler(World()) == 'vending'


def test_route_23_lists_every_missing_badge_in_order():
    # A run with six badges argued with the Volcano Badge guard. Each guard checks one badge.
    guards = tuple(Badge(bit, enable=lambda world, bit=bit: f'gym_{bit}') for bit in (2, 4, 8, 16, 32, 64, 128))
    world = World(badges={2, 4, 8, 16, 32, 128})
    answer = feasible(Requirements(guards), world)
    assert answer.missing == (Badge(64),) and answer.enablers == ('gym_64',)
    assert missing(guards, World(badges={2})) == guards[1:]


def test_a_catch_wait_with_full_boxes_falls_short_on_the_ledger():
    # #147: a Lapras wait with 14 full boxes and nothing to release held back the League.
    lapras = Goal('wait:LAPRAS', Requirements((), Need(box_slots=1)))
    ledger = books({BOX: 0})
    answer = feasible(lapras, World(), ledger)
    assert not answer.ok and answer.missing == () and dict(answer.shortfall.missing) == {BOX: 1}
    assert 'wait:LAPRAS' not in ledger.reservations
    # With room the slot is held for the goal under its key, so the next catch sees one fewer.
    ledger = books({BOX: 1})
    assert feasible(lapras, World(), ledger).ok and ledger.reservations['wait:LAPRAS'] == Need(box_slots=1)
    assert not feasible(Goal('catch:DRATINI', Requirements((), Need(box_slots=1))), World(), ledger).ok


def test_a_legendary_needs_its_balls_and_a_ball_slot_together():
    # #148: Red skipped the three legendary birds with no bag slot for Ultra Balls.
    ultra = Item('ULTRA_BALL', enable=lambda world: 'buy_ultra_balls')
    bird = Goal('legendary:ZAPDOS', Requirements((ultra, Reach('POWER_PLANT')), Need(pocket_slots={'items': 1})))
    answer = feasible(bird, World(), books({'items': 0}))
    assert answer.missing == (ultra, Reach('POWER_PLANT')) and answer.enablers == ('buy_ultra_balls',)
    assert dict(answer.shortfall.missing) == {'items': 1}
    assert feasible(bird, World(items={'ULTRA_BALL'}, places={'POWER_PLANT'}), books({'items': 2})).ok


def test_enablers_are_listed_once():
    shop = lambda world: 'buy_drink'
    answer = feasible(Requirements((Item('SODA_POP', enable=shop), Item('LEMONADE', enable=shop))), World())
    assert answer.enablers == ('buy_drink',)


def test_requirements_come_from_a_method_a_list_or_nothing():
    world = World()
    assert requirements(None, world) == Requirements()
    assert requirements(object(), world) == Requirements()
    assert requirements(Goal('plain'), world) == Requirements()

    class Listing:
        key = 'listing'

        def requires(self, world):
            return [Badge(2)]

    assert requirements(Listing(), world) == Requirements((Badge(2),))
    assert feasible(Listing(), World(badges={2})).ok
    # Without a ledger a need is not checked, as for a goal planned before the ledger is read.
    assert feasible(Goal('room', Requirements((), Need(box_slots=1))), world).ok


def test_a_feasibility_is_truthy_only_when_ok():
    assert FEASIBLE and FEASIBLE.ok
    assert not Feasibility(missing=(Badge(2),))
    assert not Feasibility(shortfall=object())
