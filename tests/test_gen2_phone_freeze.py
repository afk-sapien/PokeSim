"""A phone call that rings while the player walks holds the pad, so the presses it ignores mark no walls."""
from types import SimpleNamespace

import pytest
from pokecore.gen2.memory_map import symbols
from pokecore.gen2.state import script_running

from pokesim.gen2.navigation import Navigator

ROOM = 1


def data():
    maps = {ROOM: dict(constant='TEST_FIELD', width=8, height=8, collision=[0] * 64, objects=[],
                       connections=[], warps=[])}
    return SimpleNamespace(maps=maps, permissions=[0] * 256, events={}, items={}, map_ids={'TEST_FIELD': ROOM})


def look(frame):
    return SimpleNamespace(map=ROOM, x=3, y=4, badges=0, party=[], objects=(), frame=frame,
                           in_battle=False, event=lambda name: False)


def test_presses_during_a_ringing_call_mark_no_walls():
    nav = Navigator(data())
    nav.observe(look(0))
    for step, button in enumerate(('left', 'down', 'right', 'up'), 1):
        nav.issued(look(step * 32 - 32), button)
        nav.observe(look(step * 32), interrupted=True)
    assert nav.blocked == {}
    assert nav.local(look(128), [(1, 4)]) == ['left', 'left']


def test_a_press_into_a_wall_still_marks_it_once_the_call_ends():
    nav = Navigator(data())
    nav.observe(look(0))
    nav.issued(look(0), 'left')
    nav.observe(look(40))
    assert (ROOM, 2, 4) in nav.blocked


class Banked:
    """Banked memory holding one byte, read as ``memory[bank, start:stop]``."""

    def __init__(self, bank, address, value):
        self.bank, self.address, self.value = bank, address, value

    def __getitem__(self, key):
        bank, span = key
        return [self.value if (bank, address) == (self.bank, self.address) else 0
                for address in range(span.start, span.stop)]


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_script_running_reads_the_engine_bit(version):
    bank, address = symbols(version)['wScriptFlags']
    assert not script_running(Banked(bank, address, 0), version)
    assert script_running(Banked(bank, address, 4), version)
    assert not script_running(Banked(bank, address, 3), version)
