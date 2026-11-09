"""Capture and storage decisions account for the whole collection."""
from dataclasses import replace

import pytest

from pokesim.policies.battle import choose_battle, useful_capture
from pokesim.policies.strategic import StrategicPolicy
from pokesim import pcvalue
from pokesim.pcvalue import queue
from pokesim.policies.collection import improves
from pokesim.policies.team import release_rated, release_target, team_keys
from pokesim.screen import Screen
from pokesim.strategy_data import ITEMS, SPECIES
from test_duplicates import snapshot, stored
from test_events import snap
from test_strategy import mon, menu


def sid(dex):
    return next(key for key, data in SPECIES.items() if data['dex'] == dex)


def collection(**changes):
    values = dict(party=(mon(level=52), mon(level=100)), owned=frozenset({1, 67}),
                  stored_pokemon=tuple((i // 20, sid(67), 41, '') for i in range(102)),
                  in_battle=1, items=((ITEMS['POKE_BALL'], 10),))
    values.update(changes)
    return snap(**values)


@pytest.mark.parametrize('level', [41, 42, 45])
def test_machoke_pile_does_not_justify_another_capture(level):
    state = collection()
    enemy = mon(species=sid(67), types=(1, 1), level=level, hp=1, moves=(), pp=())
    assert not useful_capture(state, enemy.species, level)
    assert choose_battle(state, state.party[0], enemy, 0, collect_missing=True).kind != 'item'


@pytest.mark.parametrize('level', [10, 55, 100])
def test_an_owned_species_is_caught_only_by_the_pc_catch_rule(level):
    # No level and no type is a reason. Only the PC's catch rule (keeps) is.
    state = collection(party=(mon(level=10), mon(level=100)), stored_pokemon=())
    assert not useful_capture(state, sid(67), level)
    assert not useful_capture(state, sid(67), level, keeps=lambda: False)
    assert useful_capture(state, sid(67), level, keeps=lambda: True)


def test_higher_level_tentacool_with_common_dvs_is_not_caught_over_a_better_copy():
    # Soak red caught a level-30 Tentacool with DVs 2, 8, 2, 9, 10 and released it at the next PC.
    held = stored(0, species=sid(72), level=12, dvs=(15, 15, 15, 15, 15))
    state = replace(snapshot([held], party=(mon(level=35),)), owned=frozenset({1, 72}), in_battle=1)
    assert not improves(state, sid(72), (2, 8, 2, 9, 10))
    assert not useful_capture(state, sid(72), 30, keeps=lambda: improves(state, sid(72), (2, 8, 2, 9, 10)))
    common = replace(state, stored_details=(replace(held, dvs=(8, 8, 8, 8, 8)),))
    assert improves(common, sid(72), (15, 15, 15, 15, 15))


def test_missing_entry_and_explicit_field_move_goal_still_capture():
    state = collection()
    enemy = mon(species=sid(25), level=3, hp=1, moves=(), pp=())
    assert choose_battle(state, state.party[0], enemy, 0, collect_missing=True).kind == 'item'
    assert useful_capture(state, sid(67), 10, required_move=70)


def test_safari_flees_unneeded_duplicate_but_catches_missing_species(monkeypatch):
    monkeypatch.setattr(pcvalue, 'verdict', lambda *args, **kwargs: pcvalue.Worth(False, 'Spare'))
    policy = StrategicPolicy(7)
    state = collection(enemy_species=sid(67), enemy_level=41)
    memory = menu({12: 'BALL', 14: 'ROCK'}, (1, 12), top=(1, 12))
    assert policy._dispatch(state, Screen(memory), 'safari', memory)[0].button == 'right'
    missing = replace(state, owned=frozenset({1}))
    assert policy._dispatch(missing, Screen(memory), 'safari', memory)[0].button == 'a'


def test_cleanup_releases_the_lowest_value_spares_first():
    copies = [stored(i, species=sid(67), level=41 + i) for i in range(4)]
    copies += [stored(4, species=sid(25), level=3), stored(5, species=sid(25), level=4)]
    state = snapshot(copies)
    assert [row.entry.slot for row in queue(release_rated(state))] == [(0, 4), (0, 0), (0, 1), (0, 2)]
    # Stock holds a plan role for its best two copies, so the second best Machoke is a floor.
    rated = {row.entry.slot: row.status for row in release_rated(state, stock={sid(67)})}
    assert rated[0, 2] == 'floor' and rated[0, 1] == 'spare'
    # One PC visit releases them in slot order, skipping slots it cannot reach.
    assert release_target(state) == (0, 0)
    assert release_target(state, reserved={(0, 0)}) == (0, 1)
    assert release_target(state, reserved={(0, 0), (0, 1), (0, 2)}) == (0, 4)


def test_cleanup_preserves_best_copy_and_releases_least_invested_equal_level():
    state = snapshot([stored(0, dvs=(15,) * 5), stored(1, dvs=(0,) * 5),
                      stored(2, stat_exp=(10000,) * 5)])
    assert release_target(state) == (0, 1)


def test_a_team_member_deposited_at_this_visit_is_never_released_at_it():
    # Soak red deposited its Lv 43 Weezing and released it at the same visit, keeping four rarer Lv 5 copies.
    rare = [(10, 9, 14, 11, 12), (10, 13, 12, 9, 10), (3, 14, 8, 9, 11), (13, 5, 1, 8, 13)]
    team = mon(species=sid(110), level=43, dvs=(14, 7, 1, 3, 8))
    copies = [stored(i, species=sid(110), level=5, dvs=dvs) for i, dvs in enumerate(rare)]
    deposited = stored(4, species=sid(110), level=43, dvs=team.dvs)
    visit = pcvalue.VisitTeam()
    visit.observe(7, team_keys((team,)))
    keys = visit.observe(7, team_keys(()))
    state = snapshot([*copies, deposited])
    assert (0, 4) in [row.entry.slot for row in queue(release_rated(state))]
    assert (0, 4) not in [row.entry.slot for row in queue(release_rated(state, team=keys))]
    assert release_target(state, reserved={(0, 1), (0, 2), (0, 3)}) == (0, 4)
    assert release_target(state, reserved={(0, 1), (0, 2), (0, 3)}, team=keys) is None
    rated = {row.entry.slot: row for row in release_rated(state, team=keys)}
    assert rated[0, 4].status == 'floor' and rated[0, 4].reason == 'Team member'
    # A later visit, on another map, may let it go as a spare.
    assert visit.observe(8, team_keys(())) == frozenset()


def test_a_spare_withdrawn_only_to_take_its_item_off_is_no_team_member():
    # Soak crystal withdrew boxed Kabutops and Kingler to take their items off, then released them as Team members.
    lead, kabutops = (157, (15, 12, 10, 9, 8)), (141, (3, 4, 5, 6, 7))
    visit = pcvalue.VisitTeam()
    assert visit.observe(7, {lead}) == {lead}
    visit.errand(kabutops)
    assert visit.observe(7, {lead, kabutops}) == {lead}
    # A member deposited at this visit still counts, and an errand never makes it a spare.
    visit.errand(lead)
    assert visit.observe(7, set()) == {lead}
    # At the next visit a Pokémon in the party is a member again.
    assert visit.observe(8, {kabutops}) == {kabutops}


def test_a_boxed_league_partner_withdrawn_at_a_visit_is_never_released_at_it():
    # A readiness step withdraws a boxed partner. It was seen in a box first, and it is still a team member.
    partner = mon(species=sid(141), level=40, dvs=(3, 4, 5, 6, 7))
    visit = pcvalue.VisitTeam()
    assert visit.observe(7, team_keys(())) == frozenset()
    keys = visit.observe(7, team_keys((partner,)))
    keys = visit.observe(7, team_keys(()))
    rare = [stored(i, species=sid(141), level=5, dvs=(15, 15, 15, 14 - i, 15)) for i in range(4)]
    state = snapshot([*rare, stored(4, species=sid(141), level=40, dvs=partner.dvs)])
    assert (0, 4) not in [row.entry.slot for row in queue(release_rated(state, team=keys))]
    assert release_target(state, reserved={(0, 0), (0, 1), (0, 2), (0, 3)}, team=keys) is None
