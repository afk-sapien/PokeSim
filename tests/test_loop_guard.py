"""A run that repeats a gift and a release, or one reload, asks for help and stops the repeat."""
import time

from pokesim.events import Event
from pokesim.stalls import LOOP_LIMIT, LoopGuard
from pokesim.store import Store

from test_events import snap


def add(store, kind, title):
    store.add_event(Event(kind, title, ''), snap(), None, None)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_the_same_gift_and_release_repeated_trips_the_guard_until_real_progress(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        guard = LoopGuard(clock=clock)
        for _ in range(LOOP_LIMIT - 1):
            add(store, 'obtain', 'Received Chikorita from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Chikorita')
        assert guard.looping(store) is None
        # Gen I words its gift with the nickname first.
        add(store, 'obtain', 'Received CHIKO (Chikorita) for League reward #9')
        add(store, 'release', 'Said goodbye to a spare Chikorita')
        clock.now += 60
        assert 'received and released Chikorita 6 times' in guard.looping(store)
        add(store, 'badge', 'Earned the Zephyr Badge')
        clock.now += 60
        assert guard.looping(store) is None
    finally:
        store.close()


def test_different_pokemon_released_after_a_gift_are_not_a_loop(tmp_path):
    store = Store(tmp_path)
    try:
        for index in range(LOOP_LIMIT * 2):
            add(store, 'obtain', 'Received Totodile from a custom PokeSim gift')
            add(store, 'release', f'Said goodbye to a spare Rattata{index}')
        assert LoopGuard().looping(store) is None
    finally:
        store.close()


def test_the_same_save_reloaded_again_and_again_trips_the_guard(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        guard = LoopGuard(clock=clock)
        for _ in range(LOOP_LIMIT):
            guard.reloaded('auto-v1-reward-1.state')
        assert 'reloaded auto-v1-reward-1.state 6 times' in guard.looping(store)
        # Real progress clears the count.
        add(store, 'map', 'Reached Route 30')
        clock.now += 60
        assert guard.looping(store) is None
    finally:
        store.close()
