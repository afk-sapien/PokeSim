"""Only the most trained copy of a species, and a trained shiny or event Pokémon, is a Trained floor.
Another trained copy goes after every spare, so a PC full of them is not a deadlock. The PC full alert
is journaled once until a slot is free, however often a League reload clears the policy's flag."""
from collections import Counter
from types import SimpleNamespace

from full_red_pc import entries
from pokecore.dvs import is_shiny
from pokesim import pcvalue
from pokesim.investment import dex_rarity
from pokesim.pcvalue import Entry, Inputs, queue, rate
from pokesim.planning.ledger import BOX_REFILL, box_wanted
from pokesim.policies.team import evolutions
from pokesim.store import Store
from test_release_origins import stored
from test_release_origins import snapshot as gen1_snapshot

PLAIN, SHINY, BEST = (8, 8, 8, 8, 8), (10, 10, 10, 10, 10), (15, 15, 15, 15, 15)


def red():
    return Inputs(rarity=dex_rarity, evolutions=evolutions(), owned=frozenset(range(1, 152)))


def trainee(dex, slot, stat_exp, dvs=PLAIN, experience=125000, **fields):
    return Entry(slot, (dex, 0), f'#{dex}', 50, experience, dvs, (stat_exp, 0, 0, 0, 0), **fields)


def trained(row):
    return sum(row.entry.stat_exp) >= pcvalue.TRAINED_STAT_EXP


def test_the_full_red_pc_frees_its_extra_trained_copies():
    # A postgame Red with 240 Pokémon boxed, each a floor, caught nothing for a day.
    rated = rate(entries(), red())
    line = queue(rated)
    assert not pcvalue.deadlocked(rated, 0)
    assert len(line) == 42 and Counter(row.entry.dex for row in line)[141] == 21
    assert all((row.status, row.reason) == ('kept', 'Trained') for row in line)
    assert not any(is_shiny({'dvs': list(row.entry.dvs)}) or row.entry.origin == 'legendary' for row in line)
    # The most trained copy of every species stays, in the party or in a box.
    for dex in {row.entry.dex for row in line}:
        top = max((row for row in rated if row.entry.dex == dex and trained(row)),
                  key=lambda row: (sum(row.entry.stat_exp), row.entry.experience))
        assert top.status == 'floor'
    assert all(row.status == 'floor' for row in rated if row.reason in ('Only copy', 'Best copy', 'Rarest copy'))


def test_a_pc_visit_frees_the_full_red_pc_to_its_refill_mark():
    # The visit Gen I starts with no slot free, as policies/team.py asks for it.
    chosen = pcvalue.releases(rate(entries(), red()), box_wanted(0, True))
    assert len(chosen) == BOX_REFILL and all((row.status, row.reason) == ('kept', 'Trained') for row in chosen)


def test_one_trained_copy_of_a_species_stays_and_the_others_go_after_every_spare():
    best, top, extra = trainee(141, (0, 0), 0, BEST), trainee(141, (0, 1), 300000), trainee(141, (0, 2), 150000)
    # A shiny best copy, a plain trained copy and a trained shiny less trained than it.
    shiny, plain, trained_shiny = (trainee(25, (0, 3), 0, SHINY, 200000), trainee(25, (0, 4), 300000),
                                   trainee(25, (0, 5), 150000, SHINY))
    # Every copy an event Pokémon, so each one's training keeps it.
    event = [trainee(144, (1, index), 300000 - 50000 * index, origin='legendary') for index in range(3)]
    # The party holds the most trained Charizard, so the boxed one is an extra.
    party, boxed = trainee(6, None, 300000), trainee(6, (1, 3), 150000)
    # A gift spare scores above a caught trained copy, yet still goes first.
    gift, spare = trainee(16, (1, 4), 0, BEST, origin='gift'), trainee(16, (1, 5), 0, origin='gift')
    rows = [best, top, extra, shiny, plain, trained_shiny, *event, party, boxed, gift, spare]
    rated = {row.entry: row for row in rate(rows)}
    assert (rated[top].status, rated[top].reason) == ('floor', 'Trained')
    assert (rated[extra].status, rated[extra].reason) == ('kept', 'Trained')
    assert rated[plain].reason == 'Trained' and rated[trained_shiny].status == 'floor'
    assert all(rated[copy].status == 'floor' for copy in event)
    assert (rated[boxed].status, rated[boxed].reason) == ('kept', 'Trained')
    assert rated[spare].score > rated[extra].score
    assert [row.entry for row in queue(rated.values())] == [spare, extra, boxed]


def test_the_full_notice_clears_only_when_a_slot_is_free(tmp_path):
    store = Store(tmp_path)
    assert pcvalue.full_notice(store, True, 0)
    # A League reload restores the policy with its flag clear while the PC is still full.
    assert not pcvalue.full_notice(store, False, 0) and not pcvalue.full_notice(store, True, 0)
    assert not pcvalue.full_notice(store, False, 1)
    assert pcvalue.full_notice(store, True, 0)


def test_a_restored_policy_journals_the_gen1_pc_full_alert_once(tmp_path):
    from pokesim.emulator import Emulator
    policy = SimpleNamespace(pc_deadlock=True, details=lambda: {'objective': {'title': 'Catch Mew'}})
    emulator = SimpleNamespace(policy=policy, store=Store(tmp_path))
    full = gen1_snapshot([stored(0, level=60)], box_counts=(20,) * 12)
    roomy = gen1_snapshot([stored(0, level=60)], box_counts=(19,) + (20,) * 11)
    seen = []
    for flag, snap in ((True, full), (False, full), (True, full), (False, full), (True, roomy), (True, full)):
        policy.pc_deadlock = flag
        events = []
        Emulator._release_journal(emulator, events, snap)
        seen.append([event.type for event in events])
    assert seen == [['pc_full'], [], [], [], [], ['pc_full']]
