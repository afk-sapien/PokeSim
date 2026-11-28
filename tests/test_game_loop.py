"""The one game loop: how an action is played, and when the autosave and the guards run after it."""
from types import SimpleNamespace

import pytest

from pokesim import config
from pokesim.runtime.game_loop import (GEN1_WAIT, GEN2_WAIT, GUARD_FRAMES, HOLD_CHECK, IDLE_FRAMES, Decider,
                                       GameLoop, gen1_options, play, write_gen1_options)
from pokesim.runtime.policy import Action, Hold


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
    """A decider that writes the options and hands out the same actions for every decision."""
    wait = GEN1_WAIT

    def __init__(self, actions):
        self.actions = actions

    def ask(self, policy, snapshot, pb):
        pb.log.append(('options',))
        return list(self.actions)


def test_a_step_writes_options_then_presses_holds_releases_and_waits_out_each_action():
    host = Host()
    GameLoop(host, Script([act('a', 2, 3), act(None, 0, 4)]), host.tick).step(None)
    assert host.pb.log == [('options',), ('press', 'a'), ('tick', 2), ('release', 'a'), ('tick', 3),
                           ('tick', 0), ('tick', 4)]
    assert host.frame == 9


def test_a_held_press_comes_up_at_the_first_check_its_stop_allows():
    host = Host()
    asked = []

    def stop(held):
        asked.append(held)
        return held >= 10

    play(host.pb, Hold('up', 40, 16, stop=stop), host.tick, GEN2_WAIT)
    assert asked == [HOLD_CHECK, 2 * HOLD_CHECK, 3 * HOLD_CHECK]
    assert host.pb.log == [('press', 'up'), ('tick', 4), ('tick', 4), ('tick', 4), ('release', 'up'), ('tick', 16)]


def test_a_held_press_whose_stop_never_says_so_lasts_its_whole_hold():
    host = Host()
    play(host.pb, Hold('up', 10, 16, stop=lambda held: False), host.tick, GEN2_WAIT)
    assert host.pb.log == [('press', 'up'), ('tick', 4), ('tick', 4), ('tick', 2), ('release', 'up'), ('tick', 16)]
    assert host.frame == Hold('up', 10, 16).frames(GEN2_WAIT)


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


def test_a_policy_with_nothing_to_do_waits_and_reads_the_play_clock():
    seen = []
    policy = SimpleNamespace(step=lambda ctx: seen.append(ctx) or [])
    actions = Decider(lambda: 1234, write_gen1_options).ask(policy, 'snapshot', Pad())
    assert [(a.button, a.hold, a.gap) for a in actions] == [(None, 0, IDLE_FRAMES)]
    assert (seen[0].snapshot, seen[0].clock, seen[0].sp) == ('snapshot', 1234, 0xDFF0)


def test_an_action_with_no_gap_waits_the_generation_wait():
    for wait in (GEN1_WAIT, GEN2_WAIT):
        pb, ticks = Pad(), []
        play(pb, Action('a'), ticks.append, wait)
        play(pb, Action('a', 6, 24), ticks.append, wait)
        assert ticks == [8, wait, 6, 24]


def test_gen1_options_follow_the_text_and_animation_settings(monkeypatch):
    from pokesim.screen import W_OPTIONS
    monkeypatch.setattr(config, 'FAST_TEXT', True)
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', True)
    assert gen1_options(0b011) == 0b001
    pb = Pad()
    pb.memory[W_OPTIONS] = 0b011
    Decider(lambda: 0, write_gen1_options).ask(SimpleNamespace(step=lambda ctx: []), 'snapshot', pb)
    assert pb.memory[W_OPTIONS] == 0b001
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', False)
    assert gen1_options(0b011) == 0b1000_0001
    Decider(lambda: 0, write_gen1_options).ask(SimpleNamespace(step=lambda ctx: []), 'snapshot', pb)
    assert pb.memory[W_OPTIONS] == 0b1000_0001
    monkeypatch.setattr(config, 'FAST_TEXT', False)
    assert gen1_options(0b011) == 0b1000_0011
    # Turning animations back on while the game runs clears the bit at the next decision.
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', True)
    assert gen1_options(0b1000_0011) == 0b011
    Decider(lambda: 0, write_gen1_options).ask(SimpleNamespace(step=lambda ctx: []), 'snapshot', pb)
    assert pb.memory[W_OPTIONS] == 0b001


def test_gen2_options_are_written_after_a_load_and_after_a_live_change(monkeypatch):
    """Gen II writes its options once after each load, so traces keep their steps, and again when a play
    setting changes while it runs, so the switch reaches the game without a restart."""
    from pokesim.gen2.emulator import Emulator
    writes = []

    class Memory(dict):
        def __setitem__(self, key, value):
            writes.append(value)
            super().__setitem__(key, value)
    game = SimpleNamespace(pb=SimpleNamespace(memory=Memory({(1, 0xD199): 0b011})), manual_mode=False,
                           data=SimpleNamespace(symbols={'wOptions': (1, 0xD199)}), options_written=None)
    monkeypatch.setattr(config, 'FAST_TEXT', True)
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', True)
    Emulator._sync_options(game)
    Emulator._sync_options(game)
    assert writes == [0b001]
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', False)
    Emulator._sync_options(game)
    Emulator._sync_options(game)
    assert writes == [0b001, 0b1000_0001]
    monkeypatch.setattr(config, 'BATTLE_ANIMATIONS', True)
    Emulator._sync_options(game)
    assert writes == [0b001, 0b1000_0001, 0b001]
    # A load forgets what was written, and hands-on play leaves the byte to the player.
    game.options_written = None
    game.manual_mode = True
    Emulator._sync_options(game)
    assert len(writes) == 3


def test_gen2_asks_with_the_stack_pointer_and_never_writes_options():
    pb = Pad()
    before = bytes(pb.memory)
    calls = []
    policy = SimpleNamespace(step=lambda ctx: calls.append((ctx.snapshot, ctx.sp, ctx.clock)) or [act('a', 6, 24)])
    # The policy's waits count the clock the decider was given, the PlayClock in a managed run.
    assert [a.button for a in Decider(lambda: 7200, wait=GEN2_WAIT).ask(policy, 'snapshot', pb)] == ['a']
    assert calls == [('snapshot', 0xDFF0, 7200)]
    assert bytes(pb.memory) == before


def test_a_press_with_a_ready_check_ends_its_gap_at_the_first_frame_the_game_waits():
    pb, ticks = Pad(), []
    frames = iter([False, False, True])
    play(pb, act('a', 8, 28), ticks.append, GEN2_WAIT, ready=lambda: next(frames))
    assert pb.log == [('press', 'a'), ('release', 'a')] and ticks == [8, 1, 1, 1]
    # A game that never waits again keeps the whole gap, one frame at a time.
    ticks.clear()
    play(pb, act('a', 8, 28), ticks.append, GEN2_WAIT, ready=lambda: False)
    assert ticks == [8] + [1] * 28


def test_a_wait_with_no_press_that_begins_with_the_game_waiting_keeps_its_whole_gap():
    # A shortcut counts its waits, so a wait the game is already ready for still lasts its length.
    ticks = []
    play(Pad(), act(None, 0, 24), ticks.append, GEN2_WAIT, ready=lambda: True)
    assert ticks == [0, 24]


def test_a_wait_with_no_press_that_begins_busy_ends_once_the_game_waits():
    ticks = []
    frames = iter([False, False, False, True])
    play(Pad(), act(None, 0, 24), ticks.append, GEN2_WAIT, ready=lambda: next(frames))
    assert ticks == [0, 1, 1, 1]


class Battle:
    """A decider whose snapshot says whether a battle is on, with the same actions every decision."""
    wait = GEN1_WAIT

    def __init__(self, actions):
        self.actions = actions

    def ask(self, policy, snapshot, pb):
        return list(self.actions)


def test_only_a_battle_ends_a_press_gap_once_the_game_waits_for_a_button():
    for in_battle, ticks in ((True, [8, 1, 1]), (False, [8, 30])):
        host = Host()
        loop = GameLoop(host, Battle([act('a', 8, 30)]), host.tick)
        waits = iter([False, True])
        loop.input_wait = lambda memory, sp: next(waits)
        loop.step(SimpleNamespace(in_battle=in_battle))
        assert [entry[1] for entry in host.pb.log if entry[0] == 'tick'] == ticks, in_battle


def test_the_battle_ready_check_reads_the_live_stack_through_core():
    host = Host()
    loop = GameLoop(host, Battle([act('a', 8, 30)]), host.tick)
    seen = []
    loop.input_wait = lambda memory, sp: seen.append((memory is host.pb.memory, sp)) or True
    loop.step(SimpleNamespace(in_battle=True))
    assert seen == [(True, 0xDFF0)] and host.frame == 9
