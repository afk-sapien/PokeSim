"""Repair excess HP through the nurse instead of replaying the same withdrawal."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.emulator import Emulator
from pokesim.policies.battle import needs_healing
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import PartyMon
from pokesim.runtime.reload import FRAMES_PER_SECOND
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import mon


def withdrawn():
    return snap(map=MAPS['VIRIDIAN_POKECENTER'], x=13, y=4, frame=1000,
                party=(mon(), PartyMon(105, 463, 461, 100, 'MOPWATER',
                                       moves=(44, 56, 98, 55), pp=(25, 5, 30, 25))))


def test_withdrawn_reserve_heals_before_rematch_and_remains_invalid_until_healed():
    state = withdrawn()
    assert not state.valid and state.hp_overflow_only
    assert needs_healing(state.party)
    policy = StrategicPolicy(7)
    policy.goal = Goal('collect_rematch', 'Return for a League rematch', '',
                       ((MAPS['INDIGO_PLATEAU_LOBBY'], 8, 10),))
    policy._overworld(state, bytearray(65536))
    assert policy.heal_latch
    assert policy.nav.target
    assert all(target[0] == state.map for target in policy.nav.target)
    healed = replace(state, party=tuple(replace(p, hp=p.max_hp) for p in state.party))
    assert healed.valid and not healed.hp_overflow_only
    assert not needs_healing(healed.party)
    policy._overworld(healed, bytearray(65536))
    assert not policy.heal_latch


@pytest.mark.parametrize('change', [dict(map=999), dict(playtime=(0, 77, 0)), dict(in_battle=7),
                                    dict(party=(PartyMon(105, 65535, 461, 100, 'BAD'),)),
                                    dict(party=(PartyMon(105, 463, 0, 100, 'BAD'),)),
                                    dict(party=(PartyMon(105, 463, 461, 101, 'BAD'),))])
def test_hp_recovery_does_not_hide_other_invalid_fields(change):
    assert not replace(withdrawn(), **change).hp_overflow_only


START = 100 * FRAMES_PER_SECOND


def guard(snapshot, *, speed=1):
    return SimpleNamespace(snapshot=snapshot, policy=SimpleNamespace(heal_latch=True), speed=speed,
                           frame=START, last_reload_frame=-10 ** 9, invalid_frame=START, stuck_frame=START,
                           battle_frame=None, _unstick=Mock(), _check_stall=Mock())


@pytest.mark.parametrize('speed', [0, 1, 16, 0.5, 0.1])
def test_nurse_has_sixty_game_seconds_to_repair_hp_at_any_speed(speed):
    # The grace counts emulator frames, so the pace the run plays at does not change it.
    emu = guard(withdrawn(), speed=speed)
    emu.frame = START + 60 * FRAMES_PER_SECOND - 1
    Emulator._check_guards(emu)
    emu._unstick.assert_not_called()
    emu.frame = START + 60 * FRAMES_PER_SECOND + 1
    Emulator._check_guards(emu)
    emu._unstick.assert_called_once_with(START, 'game state glitched')


@pytest.mark.parametrize('change', [dict(map=MAPS['VICTORY_ROAD_2F']), dict(in_battle=1), dict(playtime=(0, 77, 0))])
def test_other_invalid_states_keep_the_normal_reload_deadline(change):
    emu = guard(replace(withdrawn(), **change))
    emu.frame = START + 6 * FRAMES_PER_SECOND
    Emulator._check_guards(emu)
    emu._unstick.assert_called_once_with(START, 'game state glitched')


def test_a_reload_gives_the_reloaded_game_a_quiet_minute():
    emu = guard(replace(withdrawn(), in_battle=1))
    emu.last_reload_frame = START
    emu.frame = START + 59 * FRAMES_PER_SECOND
    Emulator._check_guards(emu)
    emu._unstick.assert_not_called()
    emu.frame = START + 61 * FRAMES_PER_SECOND
    Emulator._check_guards(emu)
    emu._unstick.assert_called_once_with(START, 'game state glitched')
