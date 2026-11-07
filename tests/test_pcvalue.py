import random

from pokesim import pcvalue
from pokesim.pcvalue import Entry, Inputs, LAST_COPY, ROLE_COPIES, queue, rate

PLAIN = (8, 8, 8, 8, 8)
SHINY = (10, 10, 10, 10, 10)


def mon(dex, slot, level=20, dvs=PLAIN, **fields):
    return Entry(slot, (dex, 0), f'#{dex}', level, dvs=dvs, stat_exp=(0,) * 5, **fields)


def test_a_shiny_waits_while_any_plain_spare_is_left():
    # The perfect Lv 100 copy is the best one, so the shiny is a spare like the others.
    rows = [mon(16, (0, 0), dvs=SHINY), mon(16, (0, 1), level=100, dvs=(15,) * 5), mon(16, (0, 2)),
            mon(19, (1, 0), level=90), mon(19, (1, 1), level=100)]
    line = queue(rate(rows))
    shiny = [row for row in line if row.entry.dvs == SHINY]
    assert shiny and line.index(shiny[0]) == len(line) - 1


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


def test_a_full_pc_deadlocks_only_when_every_slot_is_locked_or_a_last_copy():
    rng = random.Random(7)
    for _ in range(300):
        rows = []
        for index in range(rng.randrange(1, 30)):
            slot = None if rng.random() < 0.1 else (index // 20, index % 20)
            rows.append(mon(rng.choice((1, 4, 7, 25, 133)), slot, rng.randrange(2, 101),
                            tuple(rng.randrange(16) for _ in range(5)), egg=rng.random() < 0.05,
                            locked=rng.random() < 0.2, role=rng.random() < 0.1, stock=rng.random() < 0.2))
        rated = rate(rows, Inputs(demand={rng.choice((1, 4)): rng.randrange(3)}))
        stuck = all(row.reason in ('Keep', 'In the party', 'Egg', 'Only copy', 'Best copy') for row in rated)
        assert pcvalue.deadlocked(rated) == stuck


def test_the_breakdown_names_each_part():
    row = rate([mon(6, None), mon(6, (0, 0), level=100, dvs=SHINY)])[1]
    assert row.describe().startswith('Best copy. Score ')
    assert 'Shiny +300' in row.describe() and 'Lv 100 +100' in row.describe()
