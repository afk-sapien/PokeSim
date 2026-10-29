"""The battle stance: fight, flee or catch, decided by the goal under way."""
import pytest

from pokesim.planning.ledger import HP, PP, Ledger, Resources
from pokesim.planning.stance import (CATCH, FIGHT, FLEE, FLEE_TRIES, HUNT, STORY, TRAIN, TRAVEL, Encounter,
                                     budget_spent, stance)


def books(hp=50, pp=20):
    ledger = Ledger(lambda snapshot, kinds: Resources({HP: hp, PP: pp}))
    ledger.snapshot(None)
    return ledger


PLAIN = Encounter(wild=True)


@pytest.mark.parametrize('kind,expected', [(STORY, FIGHT), (TRAVEL, FLEE), (TRAIN, FIGHT), (HUNT, FLEE)])
def test_each_kind_meets_a_plain_wild_battle_by_its_default(kind, expected):
    assert stance(kind, PLAIN, books()) is expected


@pytest.mark.parametrize('kind', [STORY, TRAVEL, TRAIN, HUNT])
def test_every_kind_catches_what_it_wants_and_fights_trainers(kind):
    assert stance(kind, Encounter(wild=True, wanted=True), books()) is CATCH
    assert stance(kind, Encounter(wild=False), books()) is FIGHT


@pytest.mark.parametrize('kind', [STORY, TRAVEL, TRAIN, HUNT])
def test_every_kind_runs_from_a_shiny_it_cannot_catch(kind):
    assert stance(kind, Encounter(wild=True, shiny=True), books()) is FLEE


@pytest.mark.parametrize('kind', [TRAVEL, HUNT])
def test_a_battle_that_forbids_running_or_already_refused_it_twice_is_fought(kind):
    assert stance(kind, Encounter(wild=True, escape=False), books()) is FIGHT
    assert stance(kind, Encounter(wild=True, tries=FLEE_TRIES - 1), books()) is FLEE
    assert stance(kind, Encounter(wild=True, tries=FLEE_TRIES), books()) is FIGHT
    assert stance(kind, Encounter(wild=True, shiny=True, tries=FLEE_TRIES), books()) is FIGHT


@pytest.mark.parametrize('hp,pp,spent', [(50, 20, False), (1, 1, False), (0, 20, True), (50, 0, True)])
def test_the_walk_budget_is_spent_when_hp_or_pp_runs_out(hp, pp, spent):
    assert budget_spent(books(hp, pp), 'walk') is spent
    # A story goal with its budget spent runs early, and training keeps fighting.
    assert stance(STORY, PLAIN, books(hp, pp)) is (FLEE if spent else FIGHT)
    assert stance(TRAIN, PLAIN, books(hp, pp)) is FIGHT


def test_resources_are_read_only_when_the_budget_decides():
    reads = []
    ledger = Ledger(lambda snapshot, kinds: Resources({HP: 0, PP: 0}))

    def read():
        reads.append(1)
        return ledger.snapshot(None)
    assert stance(STORY, Encounter(wild=True, wanted=True), ledger, resources=read) is CATCH
    assert stance(TRAVEL, PLAIN, ledger, resources=read) is FLEE
    assert not reads
    assert stance(STORY, PLAIN, ledger, resources=read) is FLEE and reads == [1]
