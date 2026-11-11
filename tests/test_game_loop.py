"""The one game loop: how an action is played, and when the autosave and the guards run after it."""
from types import SimpleNamespace

import pytest

from pokesim import config
from pokesim.runtime.game_loop import GUARD_FRAMES, IDLE_FRAMES, GameLoop, Gen1, Gen2, gen1_options


def act(button, hold, gap):
    return SimpleNamespace(button=button, hold=hold, gap=gap)


class Pad:
    """An emulator that only records what was pressed."""

    def __init__(self):
        self.log = []
        self.memory = bytearray(0x10000)
        self.register_file = SimpleNamespace(SP=0xDFF0)

    def button_press(self, button):
        self.log.append(('press', button))

    def button_release(self, button):
        self.log.append(('release', button))


class Host:
    def __init__(self, frame=0):
        self.pb, self.policy, self.frame = Pad(), None, frame

    def tick(self, frames):
        self.pb.log.append(('tick', frames))
        self.frame += frames


class Script:
    """A decider that hands out the same actions for every decision."""

    def __init__(self, actions):
        self.actions = actions

    def options(self, pb):
        pb.log.append(('options',))

    def ask(self, policy, snapshot, pb):
        return list(self.actions)


def test_a_step_writes_options_then_presses_holds_releases_and_waits_out_each_action():
    host = Host()
    GameLoop(host, Script([act('a', 2, 3), act(None, 0, 4)]), host.tick).step(None)
    assert host.pb.log == [('options',), ('press', 'a'), ('tick', 2), ('release', 'a'), ('tick', 3),
                           ('tick', 0), ('tick', 4)]
    assert host.frame == 9


def test_a_failing_tick_still_releases_the_button():
    host = Host()

    def tick(frames):
        raise RuntimeError('emulator stopped')

    loop = GameLoop(host, Script([act('b', 8, 2)]), tick)
    with pytest.raises(RuntimeError):
        loop.step(None)
    assert host.pb.log[-2:] == [('press', 'b'), ('release', 'b')]


def test_guards_run_once_a_second_and_again_at_once_after_a_rewind():
    host = Host()
    ran = []
    loop = GameLoop(host, Script([act(None, 0, 20)] * 10), host.tick, guards=lambda: ran.append(host.frame))
    loop.step(None)
    assert ran == [20, 20 + GUARD_FRAMES, 20 + 2 * GUARD_FRAMES, 20 + 3 * GUARD_FRAMES]
    # A reload moves the frame back. The guards watch the restored run from its first action.
    host.frame = 30
    loop.decide(None)
    loop.act()
    assert ran[-1] == 50 and host.guard_frame == 50 + GUARD_FRAMES


def test_the_autosave_waits_until_the_host_is_ready_and_then_follows_game_time(monkeypatch):
    monkeypatch.setattr(config, 'AUTOSAVE_SECONDS', 1)
    host = Host()
    ready, saves = [False, False, True, True, True], []
    loop = GameLoop(host, Script([act(None, 0, 30)] * 5), host.tick,
                    autosave=lambda: saves.append(host.frame), ready=lambda: ready[host.frame // 30 - 1])
    loop.step(None)
    # Due at 60, but the host was busy until 90. The next save waits a full second of game time after it.
    assert saves == [90, 150]


def test_the_autosave_runs_before_the_guards(monkeypatch):
    monkeypatch.setattr(config, 'AUTOSAVE_SECONDS', 1)
    host = Host()
    order = []
    loop = GameLoop(host, Script([act(None, 0, 120)]), host.tick,
                    guards=lambda: order.append('guards'), autosave=lambda: order.append('autosave'))
    loop.step(None)
    assert order == ['autosave', 'guards']


def test_a_gen1_policy_with_nothing_to_do_waits_and_reads_the_play_clock():
    seen = []
    policy = SimpleNamespace(step=lambda ctx: seen.append(ctx) or [])
    actions = Gen1(lambda: 1234).ask(policy, 'snapshot', Pad())
    assert [(a.button, a.hold, a.gap) for a in actions] == [(None, 0, IDLE_FRAMES)]
    assert (seen[0].snapshot, seen[0].clock, seen[0].sp) == ('snapshot', 1234, 0xDFF0)


def test_gen1_options_follow_the_text_and_animation_settings(monkeypatch):
    from pokesim.screen import W_OPTIONS
    monkeypatch.setattr(config, 'FAST_TEXT', True)
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', True)
    assert gen1_options(0b011) == 0b001
    pb = Pad()
    pb.memory[W_OPTIONS] = 0b011
    Gen1(lambda: 0).options(pb)
    assert pb.memory[W_OPTIONS] == 0b001
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', False)
    assert gen1_options(0b011) == 0b1000_0001
    monkeypatch.setattr(config, 'FAST_TEXT', False)
    assert gen1_options(0b011) == 0b1000_0011


def test_gen2_asks_with_the_stack_pointer_and_never_writes_options():
    pb = Pad()
    before = bytes(pb.memory)
    Gen2(lambda: 0).options(pb)
    assert bytes(pb.memory) == before
    calls = []
    policy = SimpleNamespace(step=lambda snapshot, memory, sp, clock: calls.append((snapshot, sp, clock)) or act('a', 6, 24))
    # The policy's waits count the clock the decider was given, the PlayClock in a managed run.
    assert [a.button for a in Gen2(lambda: 7200).ask(policy, 'snapshot', pb)] == ['a']
    assert calls == [('snapshot', 0xDFF0, 7200)]
