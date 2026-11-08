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
        # Gen I words its gift with the nickname first and the species in capitals.
        add(store, 'obtain', 'Received CHIKO (CHIKORITA) for League reward #9')
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


def test_gen2_help_request_names_why_the_run_loops():
    from types import SimpleNamespace

    from pokesim.gen2.emulator import Emulator
    guard = SimpleNamespace(looping=lambda store: 'It received and released Chikorita 6 times.')
    assert Emulator._looping(SimpleNamespace(loop_guard=guard, store=None)) == 'It received and released Chikorita 6 times.'
    assert Emulator._looping(SimpleNamespace(store=None)) is None


def test_catching_a_returning_legendary_ends_the_loop(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        guard = LoopGuard(clock=clock)
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', 'Received Cyndaquil from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Cyndaquil')
        assert guard.looping(store)
        add(store, 'event_return', 'Caught the returning Sudowoodo')
        clock.now += 60
        # It counts once it has stayed in the PC for a check.
        assert guard.looping(store)
        clock.now += 60
        assert guard.looping(store) is None
    finally:
        store.close()


def test_a_return_released_straight_away_is_not_progress(tmp_path):
    # Gold caught the returning Sudowoodo and released it 11 seconds later, and the Eevee gift every 20 hours.
    store, clock = Store(tmp_path), Clock()
    try:
        guard = LoopGuard(clock=clock)
        for _ in range(LOOP_LIMIT):
            guard.reloaded('auto-v1-1.state')
        assert guard.looping(store)
        add(store, 'event_return', 'Caught the returning Sudowoodo')
        add(store, 'event_return', 'Completed the Eevee gift')
        add(store, 'event_return', 'Sudowoodo has returned!')
        clock.now += 60
        assert guard.looping(store)
        add(store, 'release', 'Said goodbye to a spare Sudowoodo Lv 20')
        add(store, 'release', 'Said goodbye to a spare Eevee')
        for _ in range(3):
            clock.now += 60
            assert 'reloaded auto-v1-1.state' in guard.looping(store)
    finally:
        store.close()


def test_gen1_gifts_and_releases_pair_by_species_across_spellings(tmp_path):
    # The real Gen I titles: the gift names the species as strategy data does, the release as RAM does.
    store = Store(tmp_path)
    try:
        for index in range(LOOP_LIMIT):
            add(store, 'obtain', f'Received SOUPJUDGE (SQUIRTLE) for League reward #{index}')
            add(store, 'release', 'Said goodbye to a spare Squirtle')
            add(store, 'obtain', f'Received MIMIC (MR.MIME) for League reward #{index}')
            add(store, 'release', 'Said goodbye to a spare Mr. Mime Lv 5')
        reason = LoopGuard().looping(store)
        assert 'received and released Squirtle 6 times' in reason or 'Mr. Mime 6 times' in reason
    finally:
        store.close()


def test_a_reload_replaying_the_same_journal_is_not_progress(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        add(store, 'map', 'Reached Route 30')
        add(store, 'level', 'CHIKO grew to level 9')
        guard = LoopGuard(clock=clock)
        assert guard.looping(store) is None
        for _ in range(LOOP_LIMIT):
            guard.reloaded('auto-v1-1.state')
            # The reload rewinds the run, and the replay journals the same map and level again.
            add(store, 'map', 'Reached Route 30')
            add(store, 'level', 'CHIKO grew to level 9')
            clock.now += 60
            guard.looping(store)
        assert 'reloaded auto-v1-1.state 6 times' in guard.looping(store)
        add(store, 'level', 'CHIKO grew to level 10')
        clock.now += 60
        assert guard.looping(store) is None
    finally:
        store.close()


def test_the_web_thread_and_the_emulator_thread_share_one_guard(tmp_path):
    import threading
    store = Store(tmp_path)
    try:
        guard = LoopGuard(every=0)
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', 'Received Totodile from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Totodile')
        reasons = []
        threads = [threading.Thread(target=lambda: reasons.extend(guard.looping(store) for _ in range(50)))
                   for _ in range(4)]
        threads.append(threading.Thread(target=lambda: [guard.reloaded('a.state') for _ in range(200)]))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(reasons) == 200 and all('Totodile 6 times' in reason for reason in reasons)
    finally:
        store.close()


def test_a_waiting_run_is_not_shown_stalled_even_while_it_loops():
    from pokesim.stalls import stalled_state
    assert stalled_state(True, False, False, 'It reloaded a.state 6 times without progress')
    assert not stalled_state(True, True, False, 'It reloaded a.state 6 times without progress')
    assert not stalled_state(True, True, True, None) and not stalled_state(False, False, True, 'loop')
    assert stalled_state(True, False, True, None)
