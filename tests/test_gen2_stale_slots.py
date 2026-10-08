"""Party slot menus must survive a party that changed under them."""
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from pokesim.gen2.menus import DayCare, FieldMove, Fly, Forget, Give, Lead, Remedy, ShowPartner, Take, Teach

EXP_SHARE = 57


def mon(trainer_id, dvs, held_item=0, moves=(33,)):
    return SimpleNamespace(trainer_id=trainer_id, dvs=dvs, held_item=held_item, moves=moves)


def screen(party, text=''):
    rows = (' ',) * 18
    return SimpleNamespace(party=tuple(party), tiles=rows, text=text, items=(), in_battle=False,
                           daycare=(None, None), event=lambda name: False, map=0)


def test_restored_give_with_a_slot_past_the_party_end_backs_out():
    # The live Silver checkpoint: Give(Exp. Share, slot 5) was saved mid-exit, then trade
    # preparation deposited two Pokémon and the party shrank to four.
    state = {'item': EXP_SHARE, 'slot': 5, 'phase': 'exit', 'steps': 29, 'exit_steps': 5}
    menu = Give(**state)
    party = [mon(1, (1, 2, 3, 4, 5)), mon(2, (1, 1, 1, 1, 1)), mon(3, (9, 9, 9, 9, 9), EXP_SHARE), mon(4, (0, 0, 0, 0, 0))]
    buttons = [menu.step(screen(party), None) for _ in range(12)]
    assert buttons[0] == 'b'
    assert None in buttons


@pytest.mark.parametrize('make', [
    lambda: Give(EXP_SHARE, 3),
    lambda: Take(3),
    lambda: Forget(3, 33),
    lambda: Teach(94, 3),
    lambda: Remedy(EXP_SHARE, 3, 0),
    lambda: FieldMove(3, 'CUT'),
    lambda: Fly(3, 1, 0, 1),
    lambda: ShowPartner(3, 'EVENT'),
    lambda: DayCare(0, 3),
])
def test_slot_menus_end_when_the_slot_is_gone(make):
    menu = make()
    party = [mon(1, (1, 1, 1, 1, 1))]
    for _ in range(20):
        button = menu.step(screen(party), SimpleNamespace(byte=lambda name: 0))
        if button is None:
            break
        assert button == 'b'
    assert button is None


def test_give_stops_when_another_pokemon_takes_its_slot():
    first, second = mon(1, (1, 1, 1, 1, 1)), mon(2, (2, 2, 2, 2, 2))
    menu = Give(EXP_SHARE, 1)
    assert menu.step(screen([first, second]), None) == 'start'
    # A trade or deposit puts someone else in slot 1. The item must not go to them.
    assert menu.step(screen([second, mon(3, (3, 3, 3, 3, 3))]), None) == 'b'
    assert menu.phase == 'exit'


def test_slot_target_survives_a_checkpoint_round_trip():
    first, second = mon(1, (1, 1, 1, 1, 1)), mon(2, (2, 2, 2, 2, 2))
    menu = Take(1)
    menu.step(screen([first, mon(2, (2, 2, 2, 2, 2), EXP_SHARE)]), None)
    restored = Take(**{key: value for key, value in asdict(menu).items()})
    restored.member = [restored.member[0], list(restored.member[1])]
    assert restored.step(screen([second, first]), None) == 'b'
    assert restored.phase == 'exit'


def test_lead_follows_its_pokemon_after_the_party_shifts():
    lead = mon(7, (7, 7, 7, 7, 7))
    menu = Lead(4, (7, [7, 7, 7, 7, 7]), phase='party')
    rows = ['  '] * 18
    rows[2] = '▶ MON'
    snapshot = screen([mon(1, (1, 1, 1, 1, 1)), mon(2, (2, 2, 2, 2, 2)), lead], text='CANCEL /')
    snapshot.tiles = rows
    assert menu.step(snapshot, SimpleNamespace(byte=lambda name: 1)) == 'down'
    assert menu.slot == 2
    gone = Lead(4, (7, [7, 7, 7, 7, 7]), phase='party')
    assert gone.step(screen([mon(1, (1, 1, 1, 1, 1))]), None) == 'b'


def test_trade_preparation_drops_a_half_finished_policy_menu(monkeypatch):
    from pokesim.gen2 import preparation
    policy = SimpleNamespace(menu=Give(EXP_SHARE, 5, phase='exit'))
    emu = SimpleNamespace(policy=policy)
    prep = preparation.Preparation(emu, {})
    seen = []
    monkeypatch.setattr(prep, 'advance', lambda snapshot: seen.append(policy.menu) or 'ok')
    assert prep.step(None) == 'ok'
    assert seen == [None]
    # Menus the preparation's own battles start later are left alone.
    policy.menu = 'battle menu'
    prep.step(None)
    assert seen[-1] == 'battle menu'
