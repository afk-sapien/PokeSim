"""A run that repeats a gift and a release asks for help and stops the repeat. The reload ladder counts reloads."""
import time

from pokesim.events import Event, release_title
from pokesim.gen2.rewards import gift_title as gen2_gift_title
from pokesim.ram import SPECIES_NAMES
from pokesim.runtime.reward_delivery import gift_title
from pokesim.stalls import LOOP_LIMIT, SCAN_FRAMES, LoopGuard
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
            add(store, 'obtain', gen2_gift_title('Chikorita'))
            add(store, 'release', release_title('Chikorita'))
        assert guard.looping(store) is None
        add(store, 'obtain', gen2_gift_title('Chikorita'))
        add(store, 'release', release_title('Chikorita'))
        clock.now += SCAN_FRAMES
        assert 'received and released Chikorita 6 times' in guard.looping(store)
        add(store, 'badge', 'Earned the Zephyr Badge')
        clock.now += SCAN_FRAMES
        assert guard.looping(store) is None
    finally:
        store.close()


def test_different_pokemon_released_after_a_gift_are_not_a_loop(tmp_path):
    store = Store(tmp_path)
    try:
        for index in range(LOOP_LIMIT * 2):
            add(store, 'obtain', 'Received Totodile from a custom PokeSim gift')
            add(store, 'release', f'Said goodbye to a spare Rattata{index}')
        assert LoopGuard(clock=Clock()).looping(store) is None
    finally:
        store.close()


def test_gen2_help_request_names_why_the_run_loops():
    from types import SimpleNamespace

    from pokesim.gen2.emulator import Emulator
    # The status page reads the last scan's answer and never scans itself.
    guard = SimpleNamespace(reason='It received and released Chikorita 6 times.',
                            looping=lambda store: (_ for _ in ()).throw(AssertionError('status scanned')))
    assert Emulator._looping(SimpleNamespace(loop_guard=guard, store=None)) == 'It received and released Chikorita 6 times.'
    assert Emulator._looping(SimpleNamespace(store=None)) is None


def test_a_scan_falls_on_game_frames_and_a_rewound_clock_scans_at_once(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        guard = LoopGuard(clock=clock)
        assert guard.looping(store) is None
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', gen2_gift_title('Chikorita'))
            add(store, 'release', release_title('Chikorita'))
        # Inside one scan window the answer is the last scan's, however much real time passed.
        clock.now += SCAN_FRAMES - 1
        assert guard.looping(store) is None
        # A clock that went back past the last scan, as on a new game, scans again straight away.
        clock.now = 500.0
        assert 'received and released Chikorita 6 times' in guard.looping(store)
        assert guard.reason is not None
    finally:
        store.close()


def test_catching_a_returning_legendary_ends_the_loop(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        guard = LoopGuard(clock=clock)
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', 'Received Cyndaquil from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Cyndaquil')
        assert guard.looping(store)
        add(store, 'event_return', 'Caught the returning Sudowoodo')
        clock.now += SCAN_FRAMES
        # It counts once it has stayed in the PC for a check.
        assert guard.looping(store)
        clock.now += SCAN_FRAMES
        assert guard.looping(store) is None
    finally:
        store.close()


def test_a_return_released_straight_away_is_not_progress(tmp_path):
    # Gold caught the returning Sudowoodo and released it 11 seconds later, and the Eevee gift every 20 hours.
    store, clock = Store(tmp_path), Clock()
    try:
        guard = LoopGuard(clock=clock)
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', 'Received Cyndaquil from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Cyndaquil')
        assert guard.looping(store)
        add(store, 'event_return', 'Caught the returning Sudowoodo')
        add(store, 'event_return', 'Completed the Eevee gift')
        add(store, 'event_return', 'Sudowoodo has returned!')
        clock.now += SCAN_FRAMES
        assert guard.looping(store)
        add(store, 'release', 'Said goodbye to a spare Sudowoodo Lv 20')
        add(store, 'release', 'Said goodbye to a spare Eevee')
        for _ in range(3):
            clock.now += SCAN_FRAMES
            assert 'received and released Cyndaquil' in guard.looping(store)
    finally:
        store.close()


def test_gen1_gifts_and_releases_pair_by_species_across_spellings(tmp_path):
    # The real Gen I titles: the gift names the species as strategy data does, the release as RAM does.
    store = Store(tmp_path)
    try:
        for index in range(LOOP_LIMIT):
            add(store, 'obtain', gift_title('SOUPJUDGE', 177, index))
            add(store, 'release', release_title(SPECIES_NAMES[177]))
            add(store, 'obtain', gift_title('MIMIC', 42, index))
            add(store, 'release', release_title(SPECIES_NAMES[42]) + ' Lv 5')
        reason = LoopGuard(clock=Clock()).looping(store)
        assert 'received and released Squirtle 6 times' in reason or 'Mr. Mime 6 times' in reason
    finally:
        store.close()


def test_every_gen1_gift_title_pairs_with_its_release_title():
    """The producers spell MR_MIME and NIDORAN_F one way in a gift and Mr. Mime and Nidoran♀ in a release."""
    from pokesim.stalls import _RECEIVED, _RELEASED, species_key
    from pokesim.strategy_data import SPECIES
    for species in SPECIES:
        if species not in SPECIES_NAMES:
            continue
        gift = species_key(_RECEIVED.match(gift_title('NICK', species, 1)).group(1))
        release = species_key(_RELEASED.match(release_title(SPECIES_NAMES[species])).group(1))
        assert gift == release, SPECIES[species]['name']


def test_a_reload_replaying_the_same_journal_is_not_progress(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        add(store, 'map', 'Reached Route 30')
        add(store, 'level', 'CHIKO grew to level 9')
        # The reload ladder says whether the run has reloaded since its last new high.
        replaying = [True]
        guard = LoopGuard(clock=clock, replaying=lambda: replaying[0])
        assert guard.looping(store) is None
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', gen2_gift_title('Chikorita'))
            add(store, 'release', release_title('Chikorita'))
            # The reload rewinds the run, and the replay journals the same map and level again.
            add(store, 'map', 'Reached Route 30')
            add(store, 'level', 'CHIKO grew to level 9')
            clock.now += SCAN_FRAMES
            guard.looping(store)
        assert 'received and released Chikorita 6 times' in guard.looping(store)
        # Once a new high ends the replay, the same entry is progress again.
        replaying[0] = False
        add(store, 'map', 'Reached Route 30')
        clock.now += SCAN_FRAMES
        assert guard.looping(store) is None
    finally:
        store.close()


def test_the_web_thread_and_the_emulator_thread_share_one_guard(tmp_path):
    import threading
    store = Store(tmp_path)
    try:
        guard = LoopGuard(clock=Clock(), every=0)
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', 'Received Totodile from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Totodile')
        reasons = []
        threads = [threading.Thread(target=lambda: reasons.extend(guard.looping(store) for _ in range(50)))
                   for _ in range(4)]
        threads.append(threading.Thread(target=lambda: [guard.take_trip() for _ in range(200)]))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(reasons) == 200 and all('Totodile 6 times' in reason for reason in reasons)
    finally:
        store.close()


def test_a_waiting_run_is_not_shown_stalled_even_while_it_loops():
    from pokesim.runtime.supervision import STALL_RELOADS, Supervisor
    loop = 'It received and released Totodile 6 times without other progress'
    calm, stuck = Supervisor(), Supervisor()
    stuck.reloads = STALL_RELOADS
    assert calm.stuck(None, 0, loop=loop) and not calm.stuck(None, 0, waiting=True, loop=loop)
    assert not stuck.stuck(None, 0, waiting=True) and not stuck.stuck(None, 0, held=True, loop=loop)
    assert stuck.stuck(None, 0) and not calm.stuck(None, 0)
