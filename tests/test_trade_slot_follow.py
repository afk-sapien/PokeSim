"""A trade picked by a stamped key follows its copy by party slot once the copy is held."""
from types import SimpleNamespace

import pytest

from pokesim.gen2 import preparation as gen2
from pokesim.runtime import preparation as gen1
from pokesim.strategy_data import SPECIES
from pokesim.trade import preferences

TRAINER, DVS = 4321, [7, 9, 3, 12, 6]
RATTATA = 165


def mon(level, nick=''):
    return {'species': RATTATA, 'name': SPECIES[RATTATA]['name'].title(), 'trainer_id': TRAINER,
            'dvs': list(DVS), 'level': level, 'nick': nick}


def held(*party, boxed=()):
    """The party and boxed rows as the preparation lists them, party first."""
    listed = preferences.apply({'party': [dict(row, slot=i + 1) for i, row in enumerate(party)],
                                'storage': {'pokemon': [dict(row, box=1, position=i + 1)
                                                        for i, row in enumerate(boxed)]}}, {})
    return listed['party'], listed['storage']['pokemon']


@pytest.fixture
def rows(monkeypatch):
    """Set the rows both generations' answering read, as a list holding (party, boxed)."""
    current = []

    def gen1_answering(snapshot, saved, key):
        party, boxed = current[0]
        return ([('party', i, row) for i, row in enumerate(party) if preferences.answers(row, key)]
                + [('box', i, row) for i, row in enumerate(boxed) if preferences.answers(row, key)])

    def gen2_answering(snapshot, saved, key):
        party, boxed = current[0]
        return ([('party', i, SimpleNamespace(egg=False), row) for i, row in enumerate(party)
                 if preferences.answers(row, key)]
                + [('box', i, SimpleNamespace(egg=False), row) for i, row in enumerate(boxed)
                   if preferences.answers(row, key)])

    monkeypatch.setattr(gen1, 'answering', gen1_answering)
    monkeypatch.setattr(gen2, 'answering', gen2_answering)
    return current


def pick(generation, key, copies=None, slot=None):
    if generation is gen1:
        return gen1.selection(None, {}, key, copies, slot)[:2]
    return gen2.selected(None, {}, key, copies, slot)[:2]


@pytest.mark.parametrize('generation', [gen1, gen2])
def test_a_stamped_pick_follows_its_party_slot_as_it_gains_levels(rows, generation):
    rows[:] = [held(mon(9), mon(10))]
    first, second = (row['trade_key'] for row in rows[0][0])
    assert preferences.stamped(first) and preferences.stamped(second)
    assert pick(generation, first) == ('party', 0)
    assert pick(generation, second) == ('party', 1)
    # The copy gains a level on the way, so its stamp moves and only its slot still finds it.
    rows[:] = [held(mon(11), mon(10))]
    with pytest.raises(ValueError):
        pick(generation, first)
    assert pick(generation, first, slot=0) == ('party', 0)
    # A slot now holding a copy with another nickname is refused.
    rows[:] = [held(mon(11, 'RATS'), mon(10))]
    with pytest.raises(ValueError):
        pick(generation, first, slot=0)
    rows[:] = [held(mon(10))]
    with pytest.raises(ValueError):
        pick(generation, first, slot=1)


@pytest.mark.parametrize('generation', [gen1, gen2])
def test_a_twin_key_from_before_the_copies_differed_is_refused(rows, generation):
    rows[:] = [held(mon(9), boxed=[mon(9)])]
    key = rows[0][0][0]['trade_key']
    assert not preferences.stamped(key)
    assert pick(generation, key, copies=2) == ('party', 0)
    # One copy gains a level, so the two the key named are no longer interchangeable.
    rows[:] = [held(mon(10), boxed=[mon(9)])]
    with pytest.raises(ValueError):
        pick(generation, key, copies=2)
    with pytest.raises(ValueError):
        pick(generation, key)


def test_the_gen1_preparation_saves_the_slot_once_the_copy_is_held(rows):
    rows[:] = [held(mon(9), boxed=[mon(10)])]
    boxed_key = rows[0][1][0]['trade_key']
    assert preferences.stamped(boxed_key)
    saves = []
    boxed = SimpleNamespace(state={'trade_key': boxed_key}, _preferences=dict, _save=lambda: saves.append(1))
    assert gen1.Preparation._selection(boxed, None)[0] == 'box'
    assert 'slot' not in boxed.state and not saves
    # Withdrawn into the second party slot, then trained on the way.
    rows[:] = [held(mon(9), mon(10))]
    assert gen1.Preparation._selection(boxed, None)[:2] == ('party', 1)
    assert boxed.state['slot'] == 1 and saves == [1]
    rows[:] = [held(mon(9), mon(12))]
    assert gen1.Preparation._selection(boxed, None)[:2] == ('party', 1)
    assert saves == [1]
