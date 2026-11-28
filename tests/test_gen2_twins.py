"""Two Pokémon alike in trainer ID and DVs are told apart by species and evolution family (#705)."""
from types import SimpleNamespace

from pokecore.identity import pokemon_identity

from pokesim.gen2 import collection, training
from pokesim.gen2.teams import assembled, changes, key
from pokesim.gen2.tower import over_cap
from pokesim.gen2.training import trainee_index

VOLTORB, ELECTRODE, RHYDON = 100, 101, 112
DVS = (8, 15, 10, 10, 10)
IDENTITY = [7, list(DVS)]


def twin(species, level=30, box=None):
    return SimpleNamespace(trainer_id=7, dvs=DVS, species=species, level=level, egg=False, box=box, position=0)


def trainer(species):
    return SimpleNamespace(collection={'training': {'identity': IDENTITY, 'species': species}})


def test_find_picks_the_species_then_its_family_and_never_another_family():
    find = training.find
    rhydon, voltorb, electrode = twin(RHYDON), twin(VOLTORB), twin(ELECTRODE)
    assert find([rhydon, electrode], IDENTITY, ELECTRODE) is electrode
    assert find([rhydon, voltorb, electrode], IDENTITY, ELECTRODE) is electrode
    assert find([rhydon, electrode], IDENTITY, VOLTORB) is electrode  # the trainee evolved
    assert find([rhydon], IDENTITY, ELECTRODE) is None
    assert find([rhydon, electrode], IDENTITY) is rhydon


def test_the_trainee_slot_skips_a_twin_already_in_front():
    party = (twin(RHYDON), twin(16), twin(ELECTRODE))
    assert trainee_index(trainer(ELECTRODE), SimpleNamespace(party=party)) == 2
    assert trainee_index(trainer(VOLTORB), SimpleNamespace(party=party)) == 2


def test_a_league_trainee_is_judged_by_its_own_level_not_its_twins(monkeypatch):
    monkeypatch.setattr(collection, 'league_run', lambda policy, snapshot: (SimpleNamespace(low=50), None))
    electrode = twin(ELECTRODE, level=30, box=0)
    snapshot = SimpleNamespace(party=(twin(RHYDON, level=80),), stored=(electrode,))
    assert collection.league_trainees(trainer(ELECTRODE), snapshot) == [(electrode, IDENTITY)]


def test_a_team_is_assembled_only_with_its_own_member_not_a_twin():
    rhydon, electrode, other = twin(RHYDON), twin(ELECTRODE, box=0), twin(16)
    assert not assembled(SimpleNamespace(party=(rhydon,)), [key(electrode)])
    extra, missing = changes(SimpleNamespace(party=(other, rhydon), stored=(twin(RHYDON, box=0), electrode)),
                             [key(other), key(electrode)])
    assert (extra, missing) == (1, electrode)


def test_a_team_saved_before_the_family_joined_the_key_still_assembles():
    rhydon = twin(RHYDON)
    assert assembled(SimpleNamespace(party=(rhydon,)), [pokemon_identity(7, DVS)])


def test_a_twin_past_the_tower_level_does_not_count_as_a_member_over_it():
    party = (twin(RHYDON, level=60), twin(ELECTRODE, level=40))
    assert not over_cap(SimpleNamespace(party=party), {'team': [key(party[1])], 'cap': 50})
    assert over_cap(SimpleNamespace(party=party), {'team': [key(party[0])], 'cap': 50})
