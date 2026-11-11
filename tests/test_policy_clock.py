"""Policies read time only from the context clock in PlayClock frames, never from the wall."""
import pytest

from pokesim.runtime.policy import PolicyContext, Stillness
from pokesim.policies.collection import DEMAND_FRAMES, Collection
from pokesim.policies.guided_random import STUCK_FRAMES as GUIDED_FRAMES, GuidedRandomPolicy
from pokesim.policies.smart_random import STUCK_FRAMES as SMART_FRAMES, SmartRandomPolicy
from test_events import snap

INTRO = dict(map=0, playtime=(0, 0, 0), party=())


def ctx(clock, mem=None, **changes):
    return PolicyContext(snap(**changes), clock, mem)


def test_the_old_positional_form_fails_loudly():
    with pytest.raises(TypeError, match='stuck_seconds'):
        PolicyContext(snap(), 0, 12.5, bytearray(65536))
    with pytest.raises(TypeError, match='stuck_seconds'):
        PolicyContext(snap(), 0, 0, bytearray(65536))
    assert PolicyContext(snap()).clock == 0


def test_stillness_counts_frames_on_one_tile_and_restarts_after_a_move():
    still = Stillness()
    assert still.frames(ctx(100)) == 0
    assert still.frames(ctx(700)) == 600
    assert still.frames(ctx(800, x=6)) == 0
    assert still.frames(ctx(900, x=6)) == 100
    # A headless clock that rewinds on a reload starts the count again.
    assert still.frames(ctx(300, x=6)) == 0
    assert still.frames(ctx(400, x=6)) == 100


def test_stillness_ignores_battles_and_the_intro():
    still = Stillness()
    still.frames(ctx(0))
    assert still.frames(ctx(5000, in_battle=1)) == 0
    assert still.frames(ctx(5100)) == 100
    intro = Stillness()
    intro.frames(ctx(0, **INTRO))
    assert intro.frames(ctx(9000, **INTRO)) == 0


def test_peer_demand_lasts_its_frames_on_the_play_clock():
    c = Collection()
    c.set_demand({25: 1}, 1000)
    assert c.demand() == {25: 1}
    c.clock = 1000 + DEMAND_FRAMES - 1
    assert c.demand() == {25: 1}
    c.clock = 1000 + DEMAND_FRAMES
    assert c.demand() == {}


def test_a_request_with_an_older_reading_keeps_the_newer_clock():
    c = Collection()
    c.clock = 50_000
    c.set_demand({25: 1}, 10)
    assert c.clock == 50_000
    assert c.demand_until == 50_000 + DEMAND_FRAMES
    c.set_demand({4: 2})
    assert c.demand() == {4: 2}
    assert c.demand_until == 50_000 + DEMAND_FRAMES


def test_guided_random_unsticks_after_its_frames_on_one_tile():
    p = GuidedRandomPolicy(3)
    p.step(ctx(0))
    p.step(ctx(GUIDED_FRAMES))
    assert p.mode != 'unstick'
    p.step(ctx(GUIDED_FRAMES + 1))
    assert p.still == GUIDED_FRAMES + 1
    assert p.mode == 'unstick'
    p.step(ctx(GUIDED_FRAMES + 2, x=6))
    assert p.still == 0 and p.mode != 'unstick'


def test_smart_random_measures_stillness_on_the_clock():
    p = SmartRandomPolicy(3)
    mem = bytearray(65536)
    p.step(ctx(0, mem))
    p.step(ctx(SMART_FRAMES + 1, mem))
    assert p.still == SMART_FRAMES + 1
    p.step(ctx(SMART_FRAMES + 2, mem, x=6))
    assert p.still == 0
