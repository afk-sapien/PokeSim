import random

import pytest

from pokesim import pcvalue
from pokesim.pcvalue import Entry, Inputs, LAST_COPY, ROLE_COPIES, queue, rate

PLAIN = (8, 8, 8, 8, 8)
SHINY = (10, 10, 10, 10, 10)


def mon(dex, slot, level=20, dvs=PLAIN, **fields):
    return Entry(slot, (dex, 0), f'#{dex}', level, dvs=dvs, stat_exp=(0,) * 5, **fields)


def test_a_shiny_waits_while_any_plain_spare_is_left():
    # One shiny is the best copy and the perfect one the rarest, so the second shiny is a spare.
    rows = [mon(16, (0, 0), dvs=SHINY), mon(16, (0, 1), level=100, dvs=(15,) * 5), mon(16, (0, 2)),
            mon(16, (0, 3), dvs=SHINY), mon(16, (0, 4), dvs=(13, 15, 15, 14, 15)),
            mon(19, (1, 0), level=90), mon(19, (1, 1), level=100), mon(19, (1, 2), dvs=(14, 15, 15, 15, 14))]
    line = queue(rate(rows))
    shiny = [row for row in line if row.entry.dvs == SHINY]
    assert len(shiny) == 1 and line.index(shiny[0]) == len(line) - 1


def test_the_best_copy_stays_and_the_last_copy_needs_its_name():
    only = mon(25, (0, 0))
    best, spare = mon(26, (0, 1), level=50), mon(26, (0, 2))
    rated = {row.entry: row for row in rate([only, best, spare])}
    assert rated[only].reason == 'Only copy' and rated[best].reason == 'Best copy'
    assert [row.entry for row in queue(rated.values())] == [spare]
    asked = rate([Entry(**{**vars(only), 'requested': 'release'})])
    assert not queue(asked)
    named = rate([Entry(**{**vars(only), 'requested': LAST_COPY})])
    assert len(queue(named)) == 1


def test_breeding_stock_holds_a_role_for_two_copies_only():
    rows = [mon(133, (0, index), level=10 + index, stock=True) for index in range(6)]
    rated = rate(rows)
    roles = [row for row in rated if any(label == 'Plan role' for label, _ in row.parts)]
    assert len(roles) == ROLE_COPIES
    # The best copy is the floor, so at most two others are kept and the rest stay spares.
    assert sum(row.status == 'spare' for row in rated) >= len(rows) - 1 - ROLE_COPIES


def test_a_full_pc_deadlocks_only_when_every_slot_is_locked_or_a_kept_best():
    rng = random.Random(7)
    for _ in range(300):
        rows = []
        for index in range(rng.randrange(1, 30)):
            slot = None if rng.random() < 0.1 else (index // 20, index % 20)
            rows.append(mon(rng.choice((1, 4, 7, 25, 133)), slot, rng.randrange(2, 101),
                            tuple(rng.randrange(16) for _ in range(5)), egg=rng.random() < 0.05,
                            locked=rng.random() < 0.2, role=rng.random() < 0.1, stock=rng.random() < 0.2))
        rated = rate(rows, Inputs(demand={rng.choice((1, 4)): rng.randrange(3)}))
        stuck = all(row.reason in ('Keep', 'In the party', 'Egg', 'Only copy', 'Best copy', 'Rarest copy',
                                   'Trained', 'Plan role')
                    for row in rated)
        assert pcvalue.deadlocked(rated, 0) == stuck
        # A PC with room is never full, however little may go.
        assert not pcvalue.deadlocked(rated, 1)


def test_a_new_game_with_room_is_not_full():
    rated = rate([mon(1, None), mon(4, (0, 0)), mon(7, (0, 1))])
    assert not queue(rated) and not pcvalue.deadlocked(rated, 18)
    assert pcvalue.deadlocked(rated, 0)


def test_a_plan_role_is_a_floor_that_only_a_request_takes():
    plain, trainee, stock, spare = (mon(133, (0, 0), level=60), mon(133, (0, 1), role=True),
                                    mon(133, (0, 2), level=30, stock=True), mon(133, (0, 3), level=40, dvs=(2,) * 5))
    rated = {row.entry: row for row in rate([plain, trainee, stock, spare])}
    # Both roles outrank the plain copy, so one is the best copy and the other a plan's.
    assert rated[trainee].status == rated[stock].status == 'floor'
    assert {rated[trainee].reason, rated[stock].reason} == {'Best copy', 'Plan role'}
    assert [row.entry for row in queue(rated.values())] == [spare, plain]
    asked = rate([plain, mon(133, (0, 4), level=30, role=True), Entry(**{**vars(trainee), 'requested': 'release'})])
    assert [row.entry.slot for row in queue(asked)][0] == (0, 1)


def test_stock_above_the_cap_stays_a_spare():
    rows = [mon(133, (0, index), level=10 + index, stock=True) for index in range(6)]
    rated = rate(rows)
    floors = [row for row in rated if row.status == 'floor']
    assert len(floors) == ROLE_COPIES and len(queue(rated)) == len(rows) - ROLE_COPIES


def test_requests_lead_the_visit_order():
    rows = [mon(16, (0, 0), level=90), *(mon(16, (1, index)) for index in range(4)),
            mon(19, (2, 0), level=90), Entry(**{**vars(mon(19, (2, 1), level=80)), 'requested': 'release'})]
    chosen = pcvalue.releases(rate(rows), 3, active_box=1)
    assert chosen[0].entry.slot == (2, 1)


def test_linked_demand_counts_as_wishes():
    rows = [mon(16, (0, 0), level=90), mon(16, (0, 1))]
    plain = rate(rows)[1].score
    wished = rate(rows, Inputs(wishes={16: 3}))[1]
    assert wished.score == plain + pcvalue.WEIGHTS['demand_cap'] and 'Wanted in trade' in wished.describe()


def test_the_last_copy_confirm_ignores_spelling_marks():
    for name, typed in (('Mr. Mime', 'mr mime'), ('Nidoran♀', 'Nidoran F'), ("Farfetch'd", 'FARFETCHD'),
                        ('Mr.Mime', 'Mr. Mime')):
        row = rate([Entry((0, 0), (122, 0), name, 20)])[0]
        assert pcvalue.request_value(row, typed) == LAST_COPY


def test_the_breakdown_names_each_part():
    row = rate([mon(6, None), mon(6, (0, 0), level=100, dvs=SHINY)])[1]
    assert row.describe().startswith('Best copy. Score ')
    assert 'Shiny +900' in row.describe() and 'Rarity 1 in 2 +61' in row.describe()
    # Level is not part of the value.
    assert 'Lv' not in row.describe()


def internal(dex):
    from pokesim.investment import _internal
    return _internal()[dex]


def test_a_special_attacker_scores_without_attack():
    from pokesim.investment import dex_rarity, families, potential_power
    from pokesim.rarity import attack_weight
    assert families().forms(internal(65))[0][1] == 0
    assert attack_weight((24,), [(90, 100, 24)]) == 0 and attack_weight((0,), [(85, 100, 0)]) == 1
    assert attack_weight((0, 24), [(90, 100, 24), (85, 100, 0)]) == 0.5
    # An Attack DV of 15 sets 8 in the HP DV, so the Attack 0 copy needs a little more elsewhere to win.
    low, high = (7, 0, 15, 15, 15), (8, 15, 14, 14, 14)
    alakazam = internal(65)
    assert potential_power({'species': alakazam, 'dvs': low}) > potential_power({'species': alakazam, 'dvs': high})
    assert dex_rarity(65, low) < dex_rarity(65, high)
    rows = rate([mon(65, (0, 0), dvs=high), mon(65, (0, 1), dvs=low)], Inputs(rarity=dex_rarity))
    assert rows[1].reason == 'Best copy' and rows[0].status == 'spare'


def test_the_attack_weight_follows_the_side_that_wins_by_a_quarter():
    from pokesim.rarity import attack_weight
    # Gengar: Dream Eater 100 against a same-type Lick of 30, Ghost being physical.
    assert attack_weight((8, 3), [(20, 100, 8), (100, 100, 24)]) == 0
    assert attack_weight((3,), [(100, 100, 0), (80, 100, 20)]) == 1
    assert attack_weight((3,), [(99, 100, 0), (80, 100, 20)]) == 0.5
    assert attack_weight((3,), [(80, 100, 0), (80, 100, 20)]) == 0.5
    assert attack_weight((3,), [(80, 100, 0), (100, 100, 20)]) == 0
    # A form with no damaging move is judged by its types.
    assert attack_weight((0, 0), []) == 1 and attack_weight((24, 24), []) == 0


def test_the_move_pool_adds_only_the_machines_the_bot_teaches():
    import os
    import pytest
    import pokesim.policies  # noqa: F401  (tm_shop imports through the policies package)
    from pokesim.investment import families, taught_machines
    from pokesim.strategy_data import MOVES
    from pokesim.tm_shop import LIMITED, RENEWABLE
    if not os.path.isfile(os.environ.get('ROM_PATH', '')):
        pytest.skip('Set ROM_PATH to a Red or Blue cartridge')
    taught = {MOVES[move]['name'] for moves in taught_machines().values() for move in moves}
    # One-time TMs and Cut, Surf and Strength, never a renewable mart TM such as Hyper Beam.
    assert {'THUNDERBOLT', 'SURF', 'STRENGTH'} <= taught and 'HYPER_BEAM' not in taught
    assert len(LIMITED) == 50 - len(RENEWABLE)
    # Voltorb learns no Electric move by level, so Electrode's Attack counts only with Thunderbolt.
    assert families().forms(internal(101))[0][1] == 0


@pytest.fixture
def cartridge(monkeypatch, tmp_path):
    """Point ROM_PATH at a path, or unset it with None, and build the move pools again from it."""
    from pokesim import config, investment

    def point(path):
        if path is None:
            monkeypatch.delenv('ROM_PATH', raising=False)
            path = tmp_path / 'absent' / 'pokered.gb'
        else:
            monkeypatch.setenv('ROM_PATH', str(path))
        monkeypatch.setattr(config, 'ROM_PATH', path)
        investment._pool.cache_clear()
    yield point
    investment._pool.cache_clear()


def test_a_run_without_a_cartridge_counts_only_the_hms(cartridge):
    from pokesim.investment import TAUGHT_HMS, dex_rarity, families, rating_problem, taught_machines
    cartridge(None)
    taught = taught_machines()
    assert set().union(*taught.values()) == TAUGHT_HMS
    assert families() is not None and rating_problem() is None
    assert dex_rarity(16, (0, 4, 4, 4, 4)) is not None


@pytest.mark.parametrize('failure', ['missing', 'unverified'])
def test_a_configured_cartridge_that_cannot_be_read_rates_and_releases_nothing(cartridge, tmp_path, monkeypatch,
                                                                               caplog, failure):
    import hashlib
    import logging
    from pokesim import catches, investment, policies  # noqa: F401  (tm_shop imports through the policies package)
    from pokesim import tm_shop
    from pokesim.rarity import RatingUnavailable
    rom = tmp_path / 'pokered.gb'
    if failure == 'unverified':
        rom.write_bytes(b'a tracked cartridge whose TM table does not verify')
        monkeypatch.setattr(catches, 'TRACKED', catches.TRACKED | {hashlib.sha1(rom.read_bytes()).hexdigest()})

        def unverified(data):
            raise ValueError('The cartridge TM move table could not be verified')
        monkeypatch.setattr(tm_shop, 'cartridge_data', unverified)
    cartridge(rom)
    with caplog.at_level(logging.ERROR, logger='pokesim.investment'):
        with pytest.raises(RatingUnavailable):
            investment.families()
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1 and 'will not rate or release' in errors[0].getMessage()
    assert investment.rating_problem() == ('The cartridge TM move table could not be verified.'
                                           if failure == 'unverified' else
                                           'The cartridge at ROM_PATH could not be read (No such file or directory).')
    # No HMs-only pool stands in: nothing is scored, and the PC releases nothing and keeps no new spare.
    copy = {'species': internal(16), 'dvs': (0, 4, 4, 4, 4)}
    assert investment.potential_power(copy) is None and investment.rarity(copy) is None
    table = Inputs(rarity=investment.dex_rarity)
    held = [mon(16, (0, 0), dvs=(0, 4, 4, 4, 4)), mon(16, (0, 1), dvs=(0, 2, 2, 2, 2)), mon(17, (0, 2))]
    rows = rate(held, table)
    assert [row.reason for row in rows] == ['Not rated', 'Not rated', 'Only copy']
    assert queue(rows) == [] and pcvalue.releases(rows, 3) == []
    assert not pcvalue.worth(mon(16, (0, 3), dvs=(0, 12, 12, 12, 12)), held, table).keep
    assert pcvalue.worth(mon(18, (0, 3)), held, table, missing=True).keep
    # The owner may still release a copy, and the only copy still needs its name.
    asked = rate([Entry(**{**vars(held[1]), 'requested': 'release'}), held[0],
                  Entry(**{**vars(held[2]), 'requested': 'release'})], table)
    assert [row.entry.slot for row in queue(asked)] == [(0, 1)]
    assert investment.automatic_trade_protected({'species': internal(16), 'dvs': [0, 2, 2, 2, 2], 'level': 5}, [])
    # The failure is found once, not read again on every rating.
    assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1


def test_a_copy_scores_as_its_best_final_form():
    from pokesim.investment import potential_power
    dvs = (9, 12, 7, 14, 3)
    assert potential_power({'species': internal(92), 'dvs': dvs}) == potential_power({'species': internal(94), 'dvs': dvs})
    branches = [potential_power({'species': internal(dex), 'dvs': dvs}) for dex in (134, 135, 136)]
    assert potential_power({'species': internal(133), 'dvs': dvs}) == max(branches)


# A rarity table for the worth tests: the held copy, one 1.5 times rarer and one twice as rare.
HELD, RARER, RAREST = (0, 4, 4, 4, 4), (0, 6, 6, 6, 6), (0, 8, 8, 8, 8)
TAILS = {HELD: 0.3, RARER: 0.2, RAREST: 0.15, (0, 2, 2, 2, 2): 0.9}
TABLE = Inputs(rarity=lambda dex, dvs: TAILS.get(tuple(dvs)))


def test_a_new_copy_is_kept_only_when_twice_as_rare():
    held = [mon(16, (0, 0), dvs=HELD)]
    assert not pcvalue.worth(mon(16, (0, 1), dvs=RARER), held, TABLE).keep
    found = pcvalue.worth(mon(16, (0, 1), dvs=RAREST), held, TABLE)
    assert found.keep and found.rarity == 0.15 and found.best == 0.3
    # A held copy without DVs is not counted, and a gift whose DVs are not known is not kept.
    assert pcvalue.worth(mon(16, (0, 1), dvs=RARER), [mon(16, (0, 0), dvs=())], TABLE).keep
    assert not pcvalue.worth(mon(16, (0, 1), dvs=()), held, TABLE).keep


def test_a_missing_entry_and_a_shiny_are_always_kept():
    held = [mon(16, (0, 0), dvs=(15,) * 5)]
    assert pcvalue.worth(mon(16, (0, 1), dvs=(0, 2, 2, 2, 2)), held, missing=True).keep
    assert pcvalue.worth(mon(16, (0, 1), dvs=(0, 2, 10, 10, 10)), held).keep
    assert not pcvalue.worth(mon(16, (0, 1), dvs=(0, 2, 2, 2, 2)), held).keep


def test_a_fresh_rare_copy_stays_and_the_common_one_goes():
    old, older = mon(16, (0, 0), level=50, dvs=HELD), mon(16, (0, 1), level=40, dvs=(0, 2, 2, 2, 2))
    fresh = mon(16, (0, 2), level=5, dvs=RAREST)
    assert pcvalue.worth(fresh, [old, older], TABLE).keep
    rated = {row.entry: row for row in rate([old, older, fresh], TABLE)}
    assert rated[fresh].reason == 'Best copy'
    assert [row.entry for row in queue(rated.values())] == [older, old]
    assert [row.entry for row in pcvalue.releases(list(rated.values()), 1)] == [older]


def test_a_release_never_takes_a_copy_rarer_than_the_catch_that_pushed_it_out():
    # Of any species, with the visit the release path makes once the catch is boxed.
    rng = random.Random(11)
    caught = pushed = 0
    for _ in range(600):
        rows = [mon(rng.choice((16, 19, 25)), (index // 20, index % 20), rng.randrange(2, 101),
                    tuple(rng.randrange(16) for _ in range(5)), origin=rng.choice(('caught', 'gift', 'traded')))
                for index in range(rng.randrange(1, 25))]
        candidate = mon(rng.choice((16, 19, 25)), (9, 0), 5, tuple(rng.randrange(16) for _ in range(5)))
        needed, active = rng.randrange(1, 11), rng.choice((0, 1, None))
        found = pcvalue.worth(candidate, rows, needed=needed, active_box=active)
        if not found.keep or found.reason != 'Rarer':
            continue
        caught += 1
        rated = rate([*rows, candidate])
        chosen = pcvalue.releases(rated, needed, active)
        assert rated[-1] not in chosen
        for row in chosen:
            pushed += 1
            assert row.rarity >= found.rarity
    assert caught > 20 and pushed > 20


@pytest.mark.parametrize('rare, common', [
    ((88, (14, 1, 7, 5, 2), 0.7048), (19, (5, 5, 5, 5, 5), 0.7895)),
    ((69, (5, 0, 7, 4, 11), 0.6410), (1, (6, 6, 6, 6, 6), 0.7146)),
])
def test_the_most_common_spare_goes_first_across_species_and_boxes(rare, common):
    # The soak pairs: Grimer against a copy at 0.789, and Bellsprout against a spare Bulbasaur at 0.715.
    # Both sit in one old visit band, so the open box used to send the rarer copy.
    tails = {dvs: tail for _, dvs, tail in (rare, common)}
    inputs = Inputs(rarity=lambda dex, dvs: tails.get(tuple(dvs), 0.05))
    rows = [mon(rare[0], (0, 0), level=50, dvs=(15,) * 5), mon(rare[0], (0, 1), dvs=rare[1]),
            mon(common[0], (1, 0), level=50, dvs=(15,) * 5), mon(common[0], (1, 1), dvs=common[1])]
    rated = rate(rows, inputs)
    for active in (0, 1, None):
        assert [row.entry.dvs for row in pcvalue.releases(rated, 1, active)] == [common[1]]
    # Only copies exactly as common choose by box.
    tails[rare[1]] = common[2]
    tied = rate(rows, inputs)
    assert [row.entry.slot for row in pcvalue.releases(tied, 1, 0)] == [(0, 1)]
    assert [row.entry.slot for row in pcvalue.releases(tied, 1, 1)] == [(1, 1)]


def test_a_traded_common_copy_outlasts_a_rarer_own_spare():
    # A stranger's trade cannot be traded back, so its points keep it over a copy rare enough to score less.
    tails = {(1, 1, 1, 1, 1): 0.9, (2, 2, 2, 2, 2): 0.5}
    inputs = Inputs(rarity=lambda dex, dvs: tails.get(tuple(dvs), 0.05))
    traded = mon(19, (0, 1), dvs=(1, 1, 1, 1, 1), origin='traded')
    own = mon(16, (1, 1), dvs=(2, 2, 2, 2, 2))
    rated = rate([mon(16, (1, 0), dvs=(15,) * 5), own, mon(19, (0, 0), dvs=(15,) * 5), traded], inputs)
    assert [row.entry for row in pcvalue.releases(rated, 1, 0)] == [own]


def test_a_catch_is_refused_when_its_visit_would_release_it_or_a_rarer_copy():
    rare, common = (0, 14, 14, 14, 14), (0, 2, 2, 2, 2)
    better = mon(19, (9, 0), 5, dvs=(0, 12, 12, 12, 12))
    # The old Rattata goes for the better one.
    alone = [mon(19, (0, 0), dvs=common)]
    assert pcvalue.worth(better, alone, needed=1).keep
    # A rarer Pidgey is the only spare a visit for two can take beside the old Rattata.
    pidgeys = [mon(16, (0, 0), dvs=(0, 15, 15, 15, 15)), mon(16, (0, 1), dvs=rare)]
    held = [*pidgeys, mon(19, (0, 2), dvs=common)]
    assert pcvalue.worth(better, held, needed=1).keep
    refused = pcvalue.worth(better, held, needed=2)
    assert not refused.keep and refused.reason == 'Pushes out a rarer copy'
    # With room left no visit comes, so the catch is judged as before.
    assert pcvalue.worth(better, held).keep


def test_a_catch_visit_comes_only_once_the_reserve_is_spent():
    from pokesim.planning.ledger import BOX_REFILL, BOX_RESERVE
    assert pcvalue.catch_visit(BOX_RESERVE + 1) == 0
    assert pcvalue.catch_visit(BOX_RESERVE) == BOX_REFILL - BOX_RESERVE + 1
    assert pcvalue.catch_visit(1) == BOX_REFILL
    assert pcvalue.catch_visit(BOX_RESERVE + 1, requests=3) == 0
    assert pcvalue.catch_visit(1, requests=BOX_REFILL + 2) == BOX_REFILL + 2


# A PC like Silver's: every boxed Pokémon the only copy of its species, so nothing may go.
ONLY_COPIES = [mon(16, (0, 0), dvs=HELD), *(mon(dex, (0, dex)) for dex in range(20, 38))]


def test_the_last_slot_takes_an_upgrade_even_when_every_boxed_copy_is_the_only_one():
    reserve = pcvalue.UPGRADE_RESERVE
    rows = rate([*ONLY_COPIES, mon(16, (-1, 0), dvs=RAREST)], TABLE)
    assert pcvalue.deadlocked(rate(ONLY_COPIES, TABLE), 0) and pcvalue.upgrade(rows)
    assert pcvalue.keeps_new(rows, headroom=reserve, room=reserve)
    # The copy it replaces is the one spare, so the visit after the catch releases it first.
    assert [row.entry for row in pcvalue.releases(rows, 1)] == [ONLY_COPIES[0]]
    # A copy not rare enough is no upgrade, and a trained copy it would replace cannot go.
    assert not pcvalue.keeps_new(rate([*ONLY_COPIES, mon(16, (-1, 0), dvs=RARER)], TABLE), room=reserve)
    trained = Entry(**{**vars(ONLY_COPIES[0]), 'stat_exp': (30000,) * 5})
    assert not pcvalue.keeps_new(rate([trained, *ONLY_COPIES[1:], mon(16, (-1, 0), dvs=RAREST)], TABLE), room=reserve)


def test_only_an_upgrade_may_take_the_reserved_slot():
    # A copy a plan's demand keeps is no upgrade, so it waits for room.
    needed = Inputs(demand={16: 2}, rarity=TABLE.rarity)
    rows = rate([*ONLY_COPIES, mon(16, (-1, 0), dvs=(0, 2, 2, 2, 2))], needed)
    assert pcvalue.keeps_new(rows) and pcvalue.keeps_new(rows, room=pcvalue.UPGRADE_RESERVE + 1)
    assert not pcvalue.keeps_new(rows, room=pcvalue.UPGRADE_RESERVE)


def test_a_missing_entry_takes_the_reserved_slot_only_when_a_release_can_follow():
    reserve = pcvalue.UPGRADE_RESERVE
    rows = rate([*ONLY_COPIES, mon(99, (-1, 0))], TABLE)
    assert not pcvalue.reserve_allows(rows, reserve, missing=True)
    assert pcvalue.reserve_allows(rows, reserve + 1, missing=True)
    assert pcvalue.boxes_full(True, reserve) and not pcvalue.boxes_full(True, reserve + 1)
    spare = rate([*ONLY_COPIES, mon(16, (0, 40), dvs=(0, 2, 2, 2, 2)), mon(99, (-1, 0))], TABLE)
    assert pcvalue.reserve_allows(spare, reserve, missing=True)
