"""A pushed boulder or a Strength question is not a wall, and repeated reloads without progress are reported."""
from types import SimpleNamespace

from pokesim.gen2.navigation import Navigator

ROOM = 1
OBJECTS = [dict(sprite='SPRITE_PERSON', event='EVENT_NONE', x=6, y=1),
           dict(sprite='SPRITE_BOULDER', event='EVENT_BOULDER', x=3, y=3)]


def data():
    permissions = [0] * 256
    maps = {ROOM: dict(constant='TEST_GYM', width=8, height=8, collision=[0] * 64, objects=OBJECTS,
                       connections=[], warps=[])}
    return SimpleNamespace(maps=maps, permissions=permissions, events={}, items={}, map_ids={'TEST_GYM': ROOM})


def look(x, y, frame, objects):
    return SimpleNamespace(map=ROOM, x=x, y=y, badges=0, party=[], objects=tuple(objects), frame=frame,
                           in_battle=False, event=lambda name: False)


def press_up_twice(boulder_after):
    """Walk up into the boulder twice, the way a Strength push looks from the outside."""
    nav = Navigator(data())
    nav.observe(look(3, 4, 0, [(2, 3, 3)]))
    nav.issued(look(3, 4, 0, [(2, 3, 3)]), 'up')
    nav.observe(look(3, 4, 40, [(2, 3, 3)]))
    nav.issued(look(3, 4, 40, [(2, 3, 3)]), 'up')
    nav.observe(look(3, 4, 80, boulder_after))
    nav.issued(look(3, 4, 80, boulder_after), 'up')
    nav.observe(look(3, 4, 120, boulder_after))
    return nav


def test_strength_question_does_not_block_the_boulder_tile():
    nav = Navigator(data())
    nav.observe(look(3, 4, 0, [(2, 3, 3)]))
    nav.issued(look(3, 4, 0, [(2, 3, 3)]), 'up')
    nav.observe(look(3, 4, 40, [(2, 3, 3)]))
    assert nav.blocked == {}


def test_a_push_leaves_the_stand_tile_walkable():
    # The player stays on (3, 4) and the boulder moves from (3, 3) to (3, 2), duplicated under index 255.
    nav = press_up_twice([(2, 3, 2), (255, 3, 2)])
    assert nav.blocked == {}
    assert nav.objects[ROOM] == {2: (3, 2)}
    path = nav.local(look(3, 4, 120, [(2, 3, 2)]), [(3, 3)])
    assert path == ['up']


def test_a_real_wall_is_still_remembered():
    nav = Navigator(data())
    nav.observe(look(1, 4, 0, [(2, 3, 3)]))
    nav.issued(look(1, 4, 0, [(2, 3, 3)]), 'left')
    nav.observe(look(1, 4, 40, [(2, 3, 3)]))
    assert (ROOM, 0, 4) in nav.blocked


def test_blocked_tile_is_cleared_when_its_boulder_moves():
    nav = Navigator(data())
    nav.observe(look(3, 5, 0, [(2, 3, 3)]))
    nav.blocked[(ROOM, 3, 3)] = 500
    nav.observe(look(3, 5, 10, [(2, 3, 2)]))
    assert (ROOM, 3, 3) not in nav.blocked


def emulator(streak, frame=1000):
    from pokesim.gen2.emulator import Emulator
    events = []
    emu = SimpleNamespace(unstick_streak=streak, best_progress=(0,) * 5, frame=frame, history={'maps': []},
                          stall=SimpleNamespace(progress=lambda frame, now: None))
    emu._note_progress = lambda snapshot, now: Emulator._note_progress(emu, snapshot, now)
    return emu, events


def seen(badges=0, flags=b'\x00', owned=(), exp=0):
    return SimpleNamespace(badges=badges, event_flags=flags, owned=owned, party=[SimpleNamespace(experience=exp)])


def test_progress_must_beat_the_best_seen_to_end_a_run_of_reloads():
    emu, _ = emulator(3)
    emu._note_progress(seen(flags=b'\x07', exp=50), 0.0)
    assert emu.unstick_streak == 0
    emu.unstick_streak = 3
    emu._note_progress(seen(flags=b'\x03', exp=50), 1.0)  # an older save has less than the best
    assert emu.unstick_streak == 3
    emu._note_progress(seen(flags=b'\x0f', exp=50), 2.0)
    assert emu.unstick_streak == 0


def test_reloading_stops_after_the_cap():
    from pokesim.gen2 import emulator as module
    reloaded = []
    emu = SimpleNamespace(unstick_streak=module.MAX_RELOADS, store=SimpleNamespace(autosaves=lambda: reloaded.append(1) or []),
                          _reset_watch=lambda: reloaded.append('reset'))
    module.Emulator._unstick(emu, 0.0, 'stuck')
    assert reloaded == ['reset']
    assert module.STALL_RELOADS <= module.MAX_RELOADS
