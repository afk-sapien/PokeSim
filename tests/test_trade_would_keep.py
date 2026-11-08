"""A game says whether its PC would keep an incoming trade, so the coordinator does not send a spare."""
from types import SimpleNamespace

import pytest

from pokesim.pcvalue import Entry, rate
from pokesim.runtime.participant import Participant


def participant(stored):
    policy = SimpleNamespace(pc_rated=lambda snapshot, extra=(): rate([*stored, *extra]))
    return SimpleNamespace(emu=SimpleNamespace(policy=policy, snapshot=object()))


def held(position, dex, level, dvs=()):
    return Entry((0, position), (dex, 0), 'Pidgey', level, dvs=dvs)


def test_a_new_species_is_kept_and_a_plain_third_copy_is_not():
    game = participant([held(0, 16, 30, (1, 15, 15, 15, 15)), held(1, 16, 20, (1, 12, 12, 12, 12))])
    assert Participant.would_keep(game, {'dex': 19, 'level': 5})['keep']
    assert not Participant.would_keep(game, {'dex': 16, 'level': 5, 'dvs': [0, 1, 1, 1, 1]})['keep']


def test_a_game_without_a_rating_keeps_everything():
    game = SimpleNamespace(emu=SimpleNamespace(policy=None, snapshot=None))
    assert Participant.would_keep(game, {'dex': 16, 'level': 5})['keep']


@pytest.mark.parametrize('data', [{'dex': 0}, {'dex': 16, 'level': 101}, {'dex': 16, 'dvs': [1, 2]},
                                  {'dex': '16'}, {'dex': 16, 'stat_exp': [-1, 0, 0, 0, 0]}])
def test_a_malformed_incoming_pokemon_is_refused(data):
    with pytest.raises(ValueError):
        Participant.would_keep(participant([]), data)


def test_gen1_rates_an_extra_row_after_the_pc(monkeypatch):
    from pokesim.policies import team
    monkeypatch.setattr(team, 'entries', lambda *args: [held(0, 16, 30, (1, 15, 15, 15, 15))])
    extra = held(-1, 16, 5)
    rows = team.release_rated(object(), extra=(extra,))
    assert [row.entry for row in rows] == [held(0, 16, 30, (1, 15, 15, 15, 15)), extra]
    assert rows[-1].status == 'spare'
