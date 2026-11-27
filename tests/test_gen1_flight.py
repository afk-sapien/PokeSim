"""Kanto's Fly shortcut: after the first Hall of Fame, fly to a visited town when the walk on from its landing
beats the walk from here by more than a flight costs. The comparison is the one Gen II's Fly uses."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim.events import RunMemory
from pokesim.gen2 import flight as johto
from pokesim.policies import flight
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.scenarios import Gen1Watch, matches
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import mon

PALLET, VIRIDIAN, INDIGO = MAPS['PALLET_TOWN'], MAPS['VIRIDIAN_CITY'], MAPS['INDIGO_PLATEAU']
FLIER = mon(level=50, moves=(flight.FLY, 33, 0, 0))
# Postgame in Pallet with every badge, Pallet, Viridian and Indigo Plateau visited.
HOME = snap(map=PALLET, x=5, y=6, badges=0xff, hall_of_fame_count=1, party=(FLIER,),
            towns_visited=1 << PALLET | 1 << VIRIDIAN | 1 << INDIGO)
# The north end of Viridian, far up Route 1 from Pallet and near Viridian's landing.
NORTH_VIRIDIAN = ((VIRIDIAN, 32, 10),)


def navigator(s):
    nav = Navigator()
    nav.update_story(s)
    return nav


def unread():
    raise AssertionError('the landings were read for a walk too short to fly')
    yield


def test_a_landing_counts_only_when_it_saves_more_than_the_flight():
    assert flight.pick(10, [(5, 'a')], 6, 4) == 'a'
    assert flight.pick(10, [(6, 'a')], 6, 4) is None
    # The cheapest landing wins, the first on a tie, and a landing with no way on never counts.
    assert flight.pick(40, [(20, 'a'), (9, 'b'), (9, 'c'), (None, 'd')], 6, 4) == 'b'
    # With no walking route any landing with a way on beats walking.
    assert flight.pick(None, [(None, 'a'), (90, 'b')], 6, 4) == 'b'
    assert flight.pick(None, [(None, 'a')], 6, 4) is None


def test_a_walk_under_the_minimum_never_reads_the_landings():
    assert flight.pick(5, unread(), 6, 4) is None


def test_johto_keeps_its_hop_rule_through_the_shared_comparison():
    """Gen II flew from a route of six hops or more to a point whose remainder plus four hops beats it."""
    assert (johto.MINIMUM_HOPS, johto.FLIGHT_HOPS) == (6, 4)
    assert flight.pick(5, unread(), johto.MINIMUM_HOPS, johto.FLIGHT_HOPS) is None
    assert flight.pick(6, [(1, 'near')], johto.MINIMUM_HOPS, johto.FLIGHT_HOPS) == 'near'
    assert flight.pick(6, [(2, 'near')], johto.MINIMUM_HOPS, johto.FLIGHT_HOPS) is None


def test_one_search_from_every_start_finds_the_nearest_and_the_first_on_a_tie():
    nav = navigator(HOME)
    pallet, viridian = (PALLET, 5, 6), (VIRIDIAN, 23, 26)
    steps, start = nav.nearest_start([pallet, viridian], NORTH_VIRIDIAN, 0)
    assert start == viridian
    nav.route(viridian, frozenset(NORTH_VIRIDIAN), 0)
    assert steps == len(nav.path)
    assert nav.nearest_start([pallet, pallet], [pallet], 0) == (0, pallet)
    assert nav.nearest_start([pallet], [(PALLET, -5, -5)], 0) is None


def test_a_long_walk_up_route_1_flies_to_viridian_and_a_short_one_walks():
    nav = navigator(HOME)
    assert flight.destination(nav, HOME, NORTH_VIRIDIAN) == VIRIDIAN
    assert flight.destination(nav, HOME, ((PALLET, 10, 8),)) is None
    assert flight.destination(nav, HOME, ((PALLET, 5, 6),)) is None


@pytest.mark.parametrize('change', [
    {'hall_of_fame_count': 0}, {'badges': 0xff & ~flight.THUNDER_BADGE}, {'party': (mon(level=50),)},
    {'map': MAPS['REDS_HOUSE_1F'], 'x': 3, 'y': 7}, {'towns_visited': 0}])
def test_no_flight_before_the_league_without_the_badge_a_flier_the_outdoors_or_a_town(change):
    s = replace(HOME, **change)
    assert flight.destination(navigator(s), s, NORTH_VIRIDIAN) is None


def test_the_landing_search_is_kept_while_only_the_position_changes():
    nav, searched = navigator(HOME), []
    nearest = nav.nearest_start
    nav.nearest_start = lambda *args: searched.append(args) or nearest(*args)
    assert flight.destination(nav, HOME, NORTH_VIRIDIAN) == VIRIDIAN
    assert flight.destination(nav, replace(HOME, x=6), NORTH_VIRIDIAN) == VIRIDIAN
    assert len(searched) == 1
    flight.destination(nav, replace(HOME, towns_visited=HOME.towns_visited | 1 << MAPS['PEWTER_CITY']), NORTH_VIRIDIAN)
    assert len(searched) == 2


def fly_policy(monkeypatch, project=None):
    policy, started = StrategicPolicy(7), []
    policy.nav.update_story(HOME)
    policy.collection.project = project
    monkeypatch.setattr(policy, '_start_shortcut', lambda s, machine, key, purpose, done:
                        started.append((machine, key, purpose, done)) or ['press'])
    return policy, started


def test_the_flight_starts_from_the_walk_and_counts_its_landing(monkeypatch):
    policy, started = fly_policy(monkeypatch, {'method': 'static', 'species': 75})
    goal = Goal('collect_static', 'Collect', '', NORTH_VIRIDIAN)
    assert policy._fly(HOME, goal) == ['press']
    machine, key, purpose, done = started[0]
    assert key == ('field', 'FLY', 'VIRIDIAN_CITY', (PALLET, 5, 6)) and purpose == 'Fly to Viridian City, nearer the goal'
    done(SimpleNamespace(completed=False), machine)
    assert policy.flights == 0
    done(SimpleNamespace(completed=True), machine)
    assert (policy.flights, policy.flown) == (1, 'VIRIDIAN_CITY')


def test_a_marathon_under_way_is_run_on_foot(monkeypatch):
    goal = Goal('marathon', 'Marathon', '', NORTH_VIRIDIAN)
    policy, started = fly_policy(monkeypatch, {'method': 'marathon', 'checkpoint': 1})
    assert policy._fly(HOME, goal) is None and started == []
    policy, started = fly_policy(monkeypatch, {'method': 'marathon'})
    assert policy._fly(HOME, goal) == ['press']


def test_the_watch_marks_each_landing_once():
    policy = SimpleNamespace(collection={}, flights=0, flown=None)
    watch = Gen1Watch(SimpleNamespace(memory=RunMemory(), policy=policy))
    assert watch.fly_marks() == []
    policy.flights, policy.flown = 1, 'INDIGO_PLATEAU'
    assert watch.fly_marks() == [('fly', 'INDIGO_PLATEAU', 'Flew to INDIGO_PLATEAU')]
    assert watch.fly_marks() == []
    assert matches('fly:INDIGO_PLATEAU', 'fly', 'INDIGO_PLATEAU')
