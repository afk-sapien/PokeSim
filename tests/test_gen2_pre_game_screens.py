"""Core reports the title screen and the main menu by name. A Gen II menu task presses nothing there."""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from pokesim.gen2 import menus


@dataclass
class Probe(menus.CoreTask):
    start = ('mart',)
    leave = True

    def build(self, snapshot):
        raise AssertionError('no machine is built before the game has started')


def game(screen, monkeypatch):
    monkeypatch.setattr(menus, 'current_screen', lambda memory, version: screen)
    data = SimpleNamespace(game='crystal')
    return SimpleNamespace(data=data), SimpleNamespace(memory=None, data=data)


@pytest.mark.parametrize('screen', menus.PRE_GAME)
def test_a_task_ends_on_a_pre_game_screen(screen, monkeypatch):
    snapshot, mem = game(screen, monkeypatch)
    assert Probe().step(snapshot, mem) is None


@pytest.mark.parametrize('screen', menus.PRE_GAME)
def test_leaving_a_menu_stops_on_a_pre_game_screen(screen, monkeypatch):
    snapshot, mem = game(screen, monkeypatch)
    task = Probe(phase='exit')
    assert task.step(snapshot, mem) is None


def test_other_screens_are_still_approached(monkeypatch):
    snapshot, mem = game('overworld', monkeypatch)
    assert Probe().step(snapshot, mem) == 'a'
    snapshot, mem = game('bag', monkeypatch)
    assert Probe(phase='exit').step(snapshot, mem) == 'b'
