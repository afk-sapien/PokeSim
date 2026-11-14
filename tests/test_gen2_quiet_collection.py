"""A finished Gold, Silver or Crystal run that hatches, catches a better copy or catches for a linked
adventure is not stalled, in the live stall check and in the replay quiet judge."""
from types import SimpleNamespace

import pytest

PIKACHU, VAPOREON = 25, 134
COMMON, FAIR, RARE = (1, 1, 1, 1, 1), (2, 2, 2, 2, 2), (3, 3, 3, 3, 3)
RARITY = {COMMON: 0.5, FAIR: 0.4, RARE: 0.05}


def rarity(mon):
    return RARITY.get(tuple(mon.dvs), 1.0)


def mon(species, dvs, trainer=1, egg=False):
    return SimpleNamespace(species=species, trainer_id=trainer, dvs=dvs, egg=egg, experience=1000, level=50,
                           nick='MON', friendship=0 if egg else 70)


def look(party=(), stored=(), **fields):
    values = dict(valid=True, started=True, party=tuple(party), stored=tuple(stored))
    return SimpleNamespace(**{**values, **fields})


TEAM = mon(VAPOREON, COMMON, trainer=7)


def collected(previous, snapshot, demand=None):
    from pokesim.stalls import collected
    return collected(previous, snapshot, rarity, demand or {})


def test_a_hatch_counts_once():
    egg = mon(PIKACHU, FAIR, egg=True)
    hatched = mon(PIKACHU, FAIR)
    assert collected(look([TEAM, egg]), look([TEAM, hatched]))
    assert not collected(look([TEAM, hatched]), look([TEAM, hatched]))
    assert not collected(look([TEAM, egg]), look([TEAM, egg]))  # walking an egg is Supervisor.progressed's count


def test_a_better_copy_counts():
    held = look([TEAM], [mon(PIKACHU, COMMON)])
    assert collected(held, look([TEAM, mon(PIKACHU, RARE, trainer=2)], held.stored))


def test_other_catches_are_churn():
    held = look([TEAM], [mon(PIKACHU, COMMON)])
    # Rarer than the held copy, but not RARITY_STEP times rarer.
    assert not collected(held, look([TEAM, mon(PIKACHU, FAIR, trainer=2)], held.stored))
    # As rare as the held copy.
    assert not collected(held, look([TEAM, mon(PIKACHU, COMMON, trainer=2)], held.stored))
    # A first copy beats no copy, and a new Pokédex entry is Supervisor.progressed's count.
    assert not collected(held, look([TEAM, mon(1, RARE)], held.stored))
    # A received egg is not a catch.
    assert not collected(held, look([TEAM, mon(PIKACHU, RARE, egg=True)], held.stored))


def test_a_catch_for_a_linked_adventure_counts_until_each_has_a_copy():
    demand = {PIKACHU: 1}
    one = look([TEAM], [mon(PIKACHU, COMMON)])
    two = look([TEAM], [mon(PIKACHU, COMMON), mon(PIKACHU, COMMON, trainer=2)])
    three = look([TEAM], [*two.stored, mon(PIKACHU, COMMON, trainer=3)])
    assert collected(one, two, demand)
    assert not collected(two, three, demand)
    assert not collected(one, two)


def test_a_box_read_twice_or_a_moved_pokemon_adds_nothing():
    rare = mon(PIKACHU, RARE)
    held = look([TEAM, rare], [mon(PIKACHU, COMMON)])
    assert not collected(held, look([TEAM, rare], [*held.stored, rare]))
    assert not collected(held, look([TEAM], [rare, *held.stored]))


def test_a_reload_or_an_unread_look_counts_nothing():
    egg, hatched = mon(PIKACHU, FAIR, egg=True), mon(PIKACHU, FAIR)
    assert not collected(None, look([TEAM, hatched]))
    assert not collected(look([TEAM, egg]), look([TEAM, hatched], valid=False))
    assert not collected(look([TEAM, egg], started=False), look([TEAM, hatched]))


def gen2_look(party, stored=()):
    return look(party, stored, badges=0xFFFF, event_flags=b'\x01', owned=frozenset({PIKACHU, VAPOREON}),
                map=1, map_name='Route 35', hall_of_fame_count=3)


def emulator(demand):
    from test_supervision import ladder
    restarts = []
    emu = SimpleNamespace(supervisor=ladder(3), play_clock=SimpleNamespace(frames=1000), history={'maps': [1]},
                          stall=SimpleNamespace(progress=lambda frame, now: restarts.append(now)), previous=None,
                          data=None, policy=SimpleNamespace(demand=demand))
    return emu, restarts


@pytest.mark.parametrize('caught, demand', [(mon(PIKACHU, RARE, trainer=2), {}),
                                            (mon(PIKACHU, COMMON, trainer=2), {PIKACHU: 1})])
def test_the_live_check_restarts_the_stall_clock_and_leaves_the_ladder(monkeypatch, caught, demand):
    from pokesim.gen2.emulator import Emulator
    monkeypatch.setattr('pokesim.gen2.postgame.tail', lambda data, mon: rarity(mon))
    emu, restarts = emulator(demand)
    held = [mon(PIKACHU, COMMON)]
    # The catch goes to the PC, so the party's experience stays as it was.
    looks = [gen2_look([TEAM], held), gen2_look([TEAM], held), gen2_look([TEAM], [*held, caught]),
             gen2_look([TEAM], [*held, caught])]
    for now, snapshot in enumerate(looks):
        emu.supervisor.reloads = 3
        Emulator._note_progress(emu, snapshot, float(now))
        emu.previous = snapshot
        # Only the first look, the run's first best, starts the ladder again.
        assert emu.supervisor.reloads == (0 if now == 0 else 3)
    assert restarts == [0.0, 2.0]


def test_the_replay_judge_counts_a_hatch_a_better_copy_and_a_catch_for_a_linked_adventure(monkeypatch):
    from pokesim.scenarios import Gen2Watch
    monkeypatch.setattr('pokesim.gen2.postgame.tail', lambda data, mon: rarity(mon))
    data = SimpleNamespace(species={PIKACHU: {'name': 'Pikachu'}, VAPOREON: {'name': 'Vaporeon'}})
    policy = SimpleNamespace(collection={}, demand={})
    run = SimpleNamespace(data=data, history={'maps': [1], 'owned': [PIKACHU, VAPOREON], 'badges': 0xFFFF,
                                              'league': 3}, policy=policy)
    watch = Gen2Watch(run)
    egg, hatched = mon(PIKACHU, FAIR, egg=True), mon(PIKACHU, FAIR)
    held = [mon(PIKACHU, COMMON)]
    assert watch.observe(gen2_look([TEAM, egg], held)) == ([], False)
    assert watch.observe(gen2_look([TEAM, hatched], held)) == ([], True)
    assert watch.observe(gen2_look([TEAM, hatched], held)) == ([], False)
    rare = mon(PIKACHU, RARE, trainer=2)
    assert watch.observe(gen2_look([TEAM, hatched, rare], held)) == ([], True)
    churn = mon(PIKACHU, COMMON, trainer=3)
    assert watch.observe(gen2_look([TEAM, hatched, rare, churn], held)) == ([], False)
    policy.demand = {PIKACHU: 4}
    wanted = mon(PIKACHU, COMMON, trainer=4)
    assert watch.observe(gen2_look([TEAM, hatched, rare, churn], [*held, wanted])) == ([], True)


def test_the_replay_judge_counts_each_egg_cycle_once(monkeypatch):
    from pokesim.scenarios import Gen2Watch
    monkeypatch.setattr('pokesim.gen2.postgame.tail', lambda data, mon: rarity(mon))
    data = SimpleNamespace(species={PIKACHU: {'name': 'Pikachu'}, VAPOREON: {'name': 'Vaporeon'}})
    run = SimpleNamespace(data=data, history={'maps': [1], 'owned': [PIKACHU, VAPOREON], 'badges': 0xFFFF,
                                              'league': 3}, policy=SimpleNamespace(collection={}, demand={}))
    watch = Gen2Watch(run)
    held = [mon(PIKACHU, COMMON)]

    def walked(cycles):
        return gen2_look([TEAM, SimpleNamespace(**{**vars(mon(PIKACHU, FAIR, egg=True)), 'friendship': cycles})],
                         held)

    assert watch.observe(walked(20)) == ([], False)
    assert watch.observe(walked(20)) == ([], False)
    assert watch.observe(walked(19)) == ([], True)
    # A reload back to a fuller egg replays a cycle that already counted.
    watch.reset()
    assert watch.observe(walked(20)) == ([], False)
    assert watch.observe(walked(19)) == ([], False)
    assert watch.observe(walked(18)) == ([], True)
