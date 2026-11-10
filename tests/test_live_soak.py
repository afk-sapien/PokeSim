"""tools/live_soak.py holds a candidate to the deployed commit on copies of the live adventures.

The journal titles come from the real producers, so a change to a title breaks these tests and not
only the gate.
"""
import json
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from pokesim.events import release_title
from pokesim.gen2.rewards import gift_title as gen2_gift_title
from pokesim.ram import SPECIES_NAMES
from pokesim.runtime.reward_delivery import gift_title
from pokesim.strategy_data import SPECIES
from tools import live_soak
from tools.stage_ladder import attempt

HOUR = live_soak.FRAMES_PER_HOUR
SQUIRTLE = 177


def result(events=(), receipts=(), catches=(), reloads=None, name='Red', **changes):
    """One adventure's raw results, as the runner writes them, over one game hour."""
    rows = [[index + 1, float(index), kind, title] for index, (kind, title) in enumerate(events)]
    return {'id': name, 'name': name, 'version': 'red', 'failed': None, 'frames': HOUR, 'events': rows,
            'journal_bytes': 0, 'kv_bytes': 0, 'receipts': [list(row) for row in receipts], 'catches': list(catches),
            'held_start': 0, 'held_end': 0, 'reloads': reloads or {}, 'errors': 0, 'help': None,
            'names': live_soak.gen1_names(), **changes}


def gift_loop(times, internal=SQUIRTLE):
    return [entry for index in range(times) for entry in (
        ('obtain', gift_title('SOUPJUDGE', internal, index)), ('release', release_title(SPECIES_NAMES[internal])))]


def catch(dex, improved=False, goal='113:grass:51:', gift=False, at=0.0):
    return {'at': at, 'dex': dex, 'goal': goal, 'improved': improved, 'gift': gift}


def test_a_gen1_gift_released_three_times_without_progress_is_churn():
    dex = SPECIES[SQUIRTLE]['dex']
    assert live_soak.churned_species(result(gift_loop(3))) == {dex: 3}
    assert live_soak.churned_species(result(gift_loop(2))) == {}
    events = gift_loop(3)
    events.insert(2, ('badge', 'Earned the Boulder Badge'))
    assert live_soak.churned_species(result(events)) == {}


def test_every_gen1_spelling_pairs_by_pokedex_number():
    names = live_soak.gen1_names()
    for internal in SPECIES:
        if internal in SPECIES_NAMES and SPECIES[internal].get('dex'):
            assert names[live_soak.species_key(SPECIES_NAMES[internal])] == SPECIES[internal]['dex']
            assert names[live_soak.species_key(SPECIES[internal]['name'])] == SPECIES[internal]['dex']


def test_gen2_gift_and_release_titles_pair():
    events = [entry for _ in range(3) for entry in (('obtain', gen2_gift_title('Chikorita')),
                                                     ('release', release_title('Chikorita')))]
    assert live_soak.churned_species(result(events, names={'chikorita': 152})) == {152: 3}


def test_a_duplicate_catch_counts_from_its_receipt_with_no_journal_entry():
    # Live Gen I catches of a species already registered wrote no obtain entry, only a capture receipt.
    receipts = [(f'catch:{index}', 16, index * 2 + 0.5) for index in range(3)]
    events = [('release', release_title('Pidgey'))] * 3
    rows = result(events, receipts)
    rows['events'] = [[index + 1, index * 2 + 1.0, kind, title] for index, (kind, title) in enumerate(events)]
    assert live_soak.churned_species(rows) == {16: 3}
    measured = live_soak.measure(rows)
    assert (measured['obtains'], measured['releases'], measured['catches']) == (3, 3, 3)


def test_a_goal_that_catches_ten_without_a_better_copy_churns():
    flat = [catch(16) for _ in range(live_soak.CHURN_CATCHES)]
    goals = live_soak.goal_churn(flat)
    assert goals['113:grass:51:'] == {'catches': 10, 'improvements': 0, 'longest_flat': 10,
                                      'catches_per_improvement': None, 'churn': True}
    better = flat[:5] + [catch(16, improved=True)] + flat[:5]
    assert live_soak.goal_churn(better)['113:grass:51:']['churn'] is False
    assert live_soak.goal_churn(better)['113:grass:51:']['catches_per_improvement'] == 11
    # Gifts are not the goal's choice.
    assert live_soak.goal_churn([catch(16, gift=True)] * 20) == {}
    problems = live_soak.invariants(result(catches=flat), result())
    assert any('10 catches in a row under 113:grass:51:' in problem for problem in problems)


def test_a_catch_improves_once_the_poll_after_it_shows_a_better_copy():
    catches = live_soak.Catches()
    catches.poll([], 'pidgey', {16: 50.0})
    catches.poll([('a', 16, 1.0)], 'pidgey', {16: 50.0})
    catches.poll([('b', 16, 2.0), ('c', 19, 2.5)], 'pidgey', {16: 10.0})
    rows = catches.finish({16: 10.0})
    # a brought the better Pidgey, b only repeated it, and c was released before the PC was read.
    assert [(row['dex'], row['improved']) for row in rows] == [(16, True), (16, False), (19, False)]
    fresh = live_soak.Catches()
    fresh.poll([], 'new', {})
    fresh.poll([('d', 25, 1.0)], 'new', {})
    assert fresh.finish({25: 40.0})[0]['improved'] is True


def test_each_catch_reports_its_rarity_and_the_rarest_copy_held_before_it():
    # Soak red caught two Seel in one poll, and only the first was judged to improve.
    copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    catches = live_soak.Catches()
    for receipts, held in (([], [PLAIN]), ([('a', 86, 1.0), ('b', 86, 1.1)], [PLAIN, RARER, COMMON]), ([], [PLAIN, RARER, COMMON])):
        game = {'party': [], 'storage': {'pokemon': [{'dex': 86, 'dvs': list(dvs)} for dvs in held]}}
        arrivals = copies.poll(game, lambda mon: mon['dex'], 0)
        catches.poll(receipts, 'seel', {86: min(TAILS[dvs] for dvs in held)}, arrivals)
    rows = catches.finish({86: 0.05}, copies.rarest())
    assert [(row['improved'], row['rarity'], row['best_held']) for row in rows] == [(True, 0.05, 0.6), (False, 0.9, 0.6)]
    assert [live_soak.catch_rarity(row) for row in rows] == [
        {'dex': 86, 'goal': 'seel', 'kept': True, 'one_in': 20, 'best_held_one_in': 2, 'times_rarer': 12.0},
        {'dex': 86, 'goal': 'seel', 'kept': False, 'one_in': 1, 'best_held_one_in': 2, 'times_rarer': 0.67}]


def test_each_catch_is_judged_by_its_own_rarity_against_the_copies_held_when_it_arrived():
    # Soak red's second Seel: a 1 in 2 new entry, then a 1 in 4 copy at the next PC visit. The old judge
    # credited the better tail to the first catch and scored the second one not kept.
    copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    catches = live_soak.Catches()
    for receipts, held in (([], []), ([('a', 86, 1.0)], [HALF]), ([('b', 86, 2.0)], [HALF, QUARTER]),
                           ([], [HALF, QUARTER])):
        game = {'party': [], 'storage': {'pokemon': [{'dex': 86, 'dvs': list(dvs)} for dvs in held]}}
        arrivals = copies.poll(game, lambda mon: mon['dex'], 0)
        catches.poll(receipts, 'seel', {86: min(TAILS[dvs] for dvs in held)} if held else {}, arrivals)
    rows = catches.finish({86: 0.25}, copies.rarest())
    assert [(row['improved'], row['kept'], row['rarity'], row['best_held']) for row in rows] == [
        (True, True, 0.5, None), (True, True, 0.25, 0.5)]
    assert [live_soak.catch_rarity(row)['times_rarer'] for row in rows] == [None, 2.0]
    # A copy less than twice as rare is no improvement, as the catch rule would not keep it.
    close = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    judged = live_soak.Catches()
    for receipts, held in (([], [HALF]), ([('c', 86, 3.0)], [HALF, CLOSE]), ([], [HALF, CLOSE])):
        game = {'party': [], 'storage': {'pokemon': [{'dex': 86, 'dvs': list(dvs)} for dvs in held]}}
        judged.poll(receipts, 'seel', {86: min(TAILS[dvs] for dvs in held)}, close.poll(game, lambda mon: mon['dex'], 0))
    assert [row['improved'] for row in judged.finish({86: 0.3}, close.rarest())] == [False]


COMMON, PLAIN, RARE, RARER = (0, 2, 2, 2, 2), (0, 4, 4, 4, 4), (0, 8, 8, 8, 8), (0, 12, 12, 12, 12)
HALF, CLOSE, QUARTER = (0, 6, 6, 6, 6), (0, 7, 7, 7, 7), (0, 10, 10, 10, 10)
TAILS = {COMMON: 0.9, PLAIN: 0.6, RARE: 0.2, RARER: 0.05, HALF: 0.5, CLOSE: 0.3, QUARTER: 0.25}


def visits(*polls):
    """Copies.poll over ``polls`` of (Pidgey DVs held, whether the journal shows a release since the last poll)."""
    copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    for held, released in polls:
        copies.poll({'party': [], 'storage': {'pokemon': [{'dex': 16, 'dvs': list(dvs)} for dvs in held]}},
                    lambda mon: mon['dex'], released)
    return copies


def test_a_catch_released_at_its_first_pc_visit_fails():
    copies = visits(([PLAIN], False), ([PLAIN, COMMON], False), ([PLAIN], True), ([PLAIN], False))
    assert [row['dvs'] for row in copies.first_visit] == [list(COMMON)] and not copies.pushed_out
    # A copy that stayed through one visit may go at the next.
    later = visits(([PLAIN], False), ([PLAIN, COMMON, RARE], False), ([COMMON, RARE], True), ([COMMON, RARE], False),
                   ([RARE], True))
    assert not later.first_visit
    problems = live_soak.invariants(result(first_visit=copies.first_visit, pushed_out=[]), None)
    assert any('1 copies caught after the start were released at their first PC visit, #16' in problem
               for problem in problems)


def test_a_hunt_best_replaced_by_a_rarer_copy_may_go_at_once():
    copies = visits(([PLAIN], False), ([PLAIN, RARE], False), ([PLAIN, RARE, RARER], False), ([PLAIN, RARER], True))
    assert not copies.first_visit and not copies.pushed_out


def test_a_release_that_takes_a_copy_rarer_than_the_newcomer_fails():
    copies = visits(([RARE, PLAIN], False), ([RARE, PLAIN, COMMON], False), ([PLAIN, COMMON], True))
    assert copies.pushed_out == [{'dex': 16, 'dvs': list(RARE), 'tail': 0.2, 'by': 0.9}]
    problems = live_soak.invariants(result(first_visit=[], pushed_out=copies.pushed_out), None)
    assert any('1 releases took a copy rarer than the newer one that pushed it out, #16' in problem
               for problem in problems)
    # The common copy going instead is the rule working.
    fine = visits(([RARE, PLAIN], False), ([RARE, PLAIN, RARER], False), ([RARE, RARER], True))
    assert not fine.pushed_out and not fine.first_visit
    # Results without the copies held, as from an older run, are not judged.
    assert live_soak.measure(result())['released_at_first_visit'] is None


def test_a_release_count_the_deployed_commit_matched_passes():
    copies = visits(([RARE, PLAIN], False), ([RARE, PLAIN, COMMON], False), ([PLAIN, COMMON], True))
    rarer = [*copies.pushed_out, *copies.pushed_out]

    def checks(mine, theirs):
        problems = live_soak.invariants(result(first_visit=[], pushed_out=mine, best_copy=[], only_copy=[]),
                                        result(first_visit=[], pushed_out=theirs, best_copy=[], only_copy=[]))
        return [problem for problem in problems if 'rarer than the newer one' in problem]

    # At or below the deployed count on the same copy, the check passes. Above it, or alone, it fails.
    assert checks(copies.pushed_out, rarer) == [] and checks(copies.pushed_out, copies.pushed_out) == []
    assert checks(rarer, copies.pushed_out)
    assert checks(copies.pushed_out, [])
    problems = live_soak.invariants(result(first_visit=[], pushed_out=copies.pushed_out), None)
    assert any('rarer than the newer one' in problem for problem in problems)


def test_a_newcomer_of_another_species_counts_against_a_rarer_release():
    copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    for held, released in (([(16, RARE), (19, PLAIN)], False), ([(16, RARE), (19, PLAIN), (19, COMMON)], False),
                           ([(19, PLAIN), (19, COMMON)], True)):
        copies.poll({'party': [], 'storage': {'pokemon': [{'dex': dex, 'dvs': list(dvs)} for dex, dvs in held]}},
                    lambda mon: mon['dex'], released)
    assert copies.pushed_out == [{'dex': 16, 'dvs': list(RARE), 'tail': 0.2, 'by': 0.9}]


def test_a_release_is_judged_by_pc_score_when_the_commit_sends_one():
    # A traded common Rattata outlasts a rarer own Pidgey by design. Its trade points outscore the Pidgey.
    def judged(scores):
        copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
        for held, released in (([(16, RARE), (19, PLAIN)], False), ([(16, RARE), (19, PLAIN), (19, COMMON)], False),
                               ([(19, PLAIN), (19, COMMON)], True)):
            copies.poll({'party': [], 'storage': {'pokemon': [{'dex': dex, 'dvs': list(dvs)} for dex, dvs in held]}},
                        lambda mon: mon['dex'], released, scores)
        return copies.pushed_out
    assert not judged({RARE: 50, PLAIN: 37, COMMON: 68})
    assert judged({RARE: 116, PLAIN: 37, COMMON: 8}) == [{'dex': 16, 'dvs': list(RARE), 'tail': 0.2, 'by': 0.9,
                                                          'score': 116, 'by_score': 8}]
    # Without scores, as from an older commit, the tails judge.
    assert judged(None) == [{'dex': 16, 'dvs': list(RARE), 'tail': 0.2, 'by': 0.9}]


def test_pc_scores_are_read_only_when_the_boxes_change():
    class Child:
        asked = 0

        def request(self, method, path):
            assert path == '/api/pokedex/status?view=pc'
            self.asked += 1
            return {'storage': {'pokemon': [{'dvs': list(RARE), 'pc_value': {'score': 116}}, {'dvs': list(COMMON)}]}}
    child, game = Child(), {'storage': {'pokemon': [{'dvs': list(RARE)}, {'dvs': list(COMMON)}]}}
    boxed, scores = live_soak._pc_scores(child, game, None)
    assert scores == {RARE: 116} and child.asked == 1
    assert live_soak._pc_scores(child, game, boxed) == (boxed, {}) and child.asked == 1


def test_a_newcomer_no_release_may_take_does_not_count_against_a_release():
    # Soak Yellow c3b193c1: a gift Mew, the only copy of a new entry, arrived and Grimer [14, 1, 7, 5, 2]
    # went at the next visit. The journal keeps no DVs for the Mew, so these give its soak tail.
    grimer, mew, best, plain = (14, 1, 7, 5, 2), (9, 1, 0, 2, 15), (0, 2, 2, 2, 2), (0, 3, 3, 3, 3)
    tails = {(88, grimer): 0.7048187255859375, (88, best): 0.3, (151, mew): 0.7691802978515625, (151, plain): 0.9}

    def judged(*polls):
        copies = live_soak.Copies(lambda dex, dvs: tails[dex, tuple(dvs)])
        for held, party, released in polls:
            copies.poll({'party': [{'dex': dex, 'dvs': list(dvs)} for dex, dvs in party],
                         'storage': {'pokemon': [{'dex': dex, 'dvs': list(dvs)} for dex, dvs in held]}},
                        lambda mon: mon['dex'], released)
        return copies.pushed_out
    start = [(88, best), (88, grimer)]
    assert not judged((start, [], False), ([*start, (151, mew)], [], False), ([(88, best), (151, mew)], [], True))
    # A party member cannot go either, but a second, commoner Mew boxed beside it could.
    assert not judged((start, [], False), (start, [(151, plain), (151, mew)], False),
                      ([(88, best)], [(151, plain), (151, mew)], True))
    assert judged((start, [], False), ([*start, (151, mew), (151, plain)], [], False),
                  ([(88, best), (151, mew), (151, plain)], [], True)) == [
        {'dex': 88, 'dvs': list(grimer), 'tail': 0.7048187255859375, 'by': 0.9}]


def watch(*polls):
    """Copies.poll over ``polls`` of (party, stored, released, map), each copy a (dex, DVs, locked) row, or
    (dex, DVs, locked, held item) for a Gen II one."""
    copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])

    def rows(group):
        return [{'dex': dex, 'dvs': list(dvs), 'trade_locked': locked, **{'held_item': item for item in held}}
                for dex, dvs, locked, *held in group]
    for party, stored, released, where in polls:
        copies.poll({'map': where, 'party': rows(party), 'storage': {'pokemon': rows(stored)}},
                    lambda mon: mon['dex'], released)
    return copies


def release_problems(copies, version='red'):
    return live_soak.invariants(result(version=version, first_visit=[], pushed_out=[], best_copy=copies.best_copy,
                                       only_copy=copies.only_copy, locked_release=copies.locked,
                                       party_release=copies.from_party), None)


def test_a_catch_that_did_not_improve_the_pc_and_left_at_its_next_visit_is_a_phantom():
    # Red's Lv 30 Tentacool and Yellow's Nidorina were caught over a better copy and released at once.
    gone = [{'dex': 72, 'dvs': [2, 8, 2, 9, 10], 'tail': 0.9}]
    problems = live_soak.invariants(result(catches=[catch(72)], first_visit=gone, pushed_out=[]), None)
    assert any('1 phantom catches, caught with no better copy or new entry and released at their next PC visit, #72'
               in problem for problem in problems)
    for kept in (catch(72, improved=True), catch(72, gift=True), catch(30)):
        assert live_soak.measure(result(catches=[kept], first_visit=gone, pushed_out=[]))['phantom_catches'] == 0
    assert live_soak.measure(result(catches=[catch(72)]))['phantom_catches'] is None


def test_a_copy_missing_at_one_poll_of_a_visit_and_back_at_the_next_never_left():
    # Soak red 80ce734: a poll at the Saffron releases read the gift Eevee in neither the party nor the PC,
    # and the next poll had it back. The journal released no Eevee.
    start = [(16, RARE, False), (16, PLAIN, False)]
    copies = watch(([], [*start, (133, COMMON, False)], False, 1), ([(133, COMMON, False)], start, False, 1),
                   ([], [(16, RARE, False)], True, 1), ([], [(16, RARE, False), (133, COMMON, False)], True, 1),
                   ([], [(16, RARE, False), (133, COMMON, False)], False, 1))
    assert not copies.from_party and not copies.only_copy and not release_problems(copies)
    # A copy that stays gone still counts.
    gone = watch(([], start, False, 1), ([(133, COMMON, False)], start, False, 1), ([], start, True, 1),
                 ([], start, False, 1))
    assert gone.from_party == [{'dex': 133, 'dvs': list(COMMON), 'tail': 0.9}]


def test_a_release_of_a_species_best_copy_fails():
    copies = watch(([], [(16, RARE, False), (16, PLAIN, False)], False, 1), ([], [(16, PLAIN, False)], True, 1))
    assert copies.best_copy == [{'dex': 16, 'dvs': list(RARE), 'tail': 0.2, 'kept': 0.6}]
    assert any("1 releases took a species' best copy, #16" in problem for problem in release_problems(copies))
    fine = watch(([], [(16, RARE, False), (16, PLAIN, False)], False, 1), ([], [(16, RARE, False)], True, 1))
    assert not fine.best_copy and not fine.only_copy and not release_problems(fine)


@pytest.mark.parametrize('version', ['red', 'crystal'])
def test_a_release_of_a_species_only_copy_fails_in_both_gens(version):
    # Soak crystal released its Charizard, Blastoise and Feraligatr with no catch at all.
    held = [(6, COMMON, False), (9, PLAIN, False), (160, RARE, False), (16, RARER, False)]
    copies = watch(([], held, False, 1), ([], held[3:], True, 1))
    assert [row['dex'] for row in copies.only_copy] == [6, 9, 160]
    assert any("3 releases took a species' only copy, #6, #9, #160" in problem
               for problem in release_problems(copies, version))
    # A copy whose species stays in the party is no only copy.
    kept = watch(([(16, PLAIN, False)], [(16, COMMON, False)], False, 1), ([(16, PLAIN, False)], [], True, 1))
    assert not kept.only_copy and not kept.best_copy


def test_a_release_of_a_locked_copy_fails():
    copies = watch(([], [(16, RARE, False), (16, COMMON, True)], False, 1), ([], [(16, RARE, False)], True, 1))
    assert [row['dvs'] for row in copies.locked] == [list(COMMON)]
    assert any('1 releases took a copy the trade preferences lock, #16' in problem for problem in release_problems(copies))


def test_a_release_of_a_team_member_deposited_at_the_visit_fails():
    # Soak red deposited its Lv 43 Weezing and released it at the same visit.
    weezing, spare = (14, 7, 1, 3, 8), (13, 5, 1, 8, 13)
    TAILS.update({weezing: 0.7, spare: 0.1})
    try:
        copies = watch(([(110, weezing, False)], [(110, spare, False)], False, 7),
                       ([], [(110, spare, False), (110, weezing, False)], False, 7),
                       ([], [(110, spare, False)], True, 7))
        assert [row['dvs'] for row in copies.from_party] == [list(weezing)]
        assert any('1 releases took a party member, the trainee, a League partner or a team member, #110' in problem
                   for problem in release_problems(copies))
        # A copy deposited at an earlier visit, on another map, is a spare by now.
        later = watch(([(110, weezing, False)], [(110, spare, False)], False, 7),
                      ([], [(110, spare, False), (110, weezing, False)], False, 8),
                      ([], [(110, spare, False)], True, 8))
        assert not later.from_party and not release_problems(later)
    finally:
        TAILS.pop(weezing), TAILS.pop(spare)


def test_a_spare_withdrawn_only_to_take_its_item_off_is_no_team_member():
    # Soak crystal withdrew its boxed Kabutops, Kingler and three more to take their items off, then released them.
    kabutops, best = (1, 2, 3, 4, 5), (14, 7, 1, 3, 8)
    TAILS.update({kabutops: 0.7, best: 0.1})
    try:
        copies = watch(([], [(141, best, False, 0), (141, kabutops, False, 83)], False, 7),
                       ([(141, kabutops, False, 83)], [(141, best, False, 0)], False, 7),
                       ([(141, kabutops, False, 0)], [(141, best, False, 0)], False, 7),
                       ([], [(141, best, False, 0)], True, 7))
        assert not copies.from_party and not release_problems(copies)
        # A partner withdrawn for a role keeps its item, so its release is still a team member's.
        partner = watch(([], [(141, best, False, 0), (141, kabutops, False, 83)], False, 7),
                        ([(141, kabutops, False, 83)], [(141, best, False, 0)], False, 7),
                        ([], [(141, best, False, 0), (141, kabutops, False, 83)], False, 7),
                        ([], [(141, best, False, 0)], True, 7))
        assert partner.from_party and any('team member' in problem for problem in release_problems(partner))
    finally:
        TAILS.pop(kabutops), TAILS.pop(best)


def test_kept_improving_catches_do_not_count_toward_the_obtains_limit():
    catches = live_soak.Catches()
    catches.poll([], 'fish', {54: 50.0})
    catches.poll([('a', 54, 1.0), ('b', 79, 1.5)], 'fish', {54: 50.0})
    rows = catches.finish({54: 10.0, 79: 30.0})
    assert [(row['dex'], row['improved'], row['kept']) for row in rows] == [(54, True, True), (79, True, True)]
    # A better copy that was later released is not kept.
    gone = live_soak.Catches()
    gone.poll([], 'fish', {54: 50.0})
    gone.poll([('a', 54, 1.0)], 'fish', {54: 50.0})
    gone.poll([], 'fish', {54: 10.0})
    assert gone.finish({54: 50.0})[0]['kept'] is False
    receipts = [(f'catch:{index}', 54, float(index)) for index in range(12)]
    kept = [dict(catch(54, improved=True), kept=True)] * 8 + [catch(54)] * 4
    measured = live_soak.measure(result(receipts=receipts, catches=kept))
    assert (measured['obtains'], measured['all_obtains'], measured['kept_better']) == (4, 12, 8)
    assert not any('obtains' in problem for problem in live_soak.invariants(result(receipts=receipts, catches=kept),
                                                                            result(receipts=receipts[:4])))
    # Catches that beat nothing still count.
    flat = live_soak.invariants(result(receipts=receipts, catches=[catch(54)] * 12), result(receipts=receipts[:4]))
    assert any('12.0 obtains a game hour, 4.0 on the deployed commit' in problem for problem in flat)


def test_the_judge_rates_a_gen1_copy_with_the_tms_of_its_adventures_cartridge(monkeypatch):
    from pokesim import config, investment
    from pokesim.cartridges import identify
    if not config.ROM_PATH.is_file() or getattr(identify(config.ROM_PATH.read_bytes()), 'version', None) not in ('red', 'blue'):
        pytest.skip('needs a clean Red or Blue cartridge at ROM_PATH')
    # The runner process loads no cartridge, and HMs-only weights rate this Nidoran F three times too rare.
    dvs = [15, 0, 15, 15, 15]
    investment._pool.cache_clear()
    real = investment.dex_rarity(29, dvs)
    monkeypatch.setattr(investment, 'cartridge_machines', lambda: ({}, {}))
    investment._pool.cache_clear()
    hms_only = investment.dex_rarity(29, dvs)
    monkeypatch.undo()
    investment._pool.cache_clear()
    assert hms_only < real / 2
    rarity = live_soak.CartridgeRarity(config.ROM_PATH)
    try:
        assert rarity(29, dvs) == pytest.approx(real)
    finally:
        rarity.close()


def test_the_judge_fails_the_run_when_it_cannot_rate_with_the_cartridge(tmp_path):
    junk = tmp_path / 'junk.gb'
    junk.write_bytes(b'not a cartridge')
    with pytest.raises(live_soak.RatingFailed, match='not one PokeSim knows'):
        live_soak.CartridgeRarity(junk)
    with pytest.raises(live_soak.RatingFailed, match='could not be read'):
        live_soak.CartridgeRarity(tmp_path / 'missing.gb')
    # A known cartridge whose TMs the helper cannot read fails too, never rating with the HMs only.
    rarity = live_soak.CartridgeRarity.__new__(live_soak.CartridgeRarity)
    rarity.process = SimpleNamespace(stdin=SimpleNamespace(write=lambda text: None, flush=lambda: None),
                                     stdout=SimpleNamespace(readline=lambda: json.dumps(
                                         {'error': 'its cartridge cannot rate copies, The cartridge gave no TMs'}) + '\n'))
    with pytest.raises(live_soak.RatingFailed, match='gave no TMs'):
        rarity(29, [15, 0, 15, 15, 15])


def test_a_judge_that_cannot_rate_fails_the_adventure(monkeypatch):
    def refuse(manager, adventure):
        raise live_soak.RatingFailed('its cartridge is not one PokeSim knows')
    monkeypatch.setattr(live_soak, '_rarity', refuse)
    monkeypatch.setattr(live_soak, '_names', lambda manager, adventure: {})
    monkeypatch.setattr(live_soak, '_readonly', lambda path: _events_db())
    monkeypatch.setattr(live_soak, '_kv_bytes', lambda db: 0)
    adventure = {'name': 'Red', 'version': 'red', 'settings': {}}
    registry = SimpleNamespace(adventure=lambda aid: adventure, update=lambda aid, **changes: None, root=live_soak.ROOT)
    outcome = live_soak.play_one(SimpleNamespace(registry=registry), 'red', HOUR, lambda line: None)
    assert outcome['failed'] == 'the judge cannot rate copies as the adventure does, its cartridge is not one PokeSim knows'
    assert live_soak.invariants(result(failed=outcome['failed']), None)


def _events_db():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE events (id INTEGER)')
    return db


def test_the_first_pc_visit_wave_is_reported_but_never_fails():
    copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    game = {'party': [], 'storage': {'pokemon': [{'dex': 16, 'dvs': list(PLAIN)}]}}
    # Three releases over two polls make the first visit, and a later visit does not add to it.
    for released in (0, 2, 1, 0, 0, 4, 0):
        copies.poll(game, lambda mon: mon['dex'], released)
    assert copies.first_wave == 3
    quiet = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    quiet.poll(game, lambda mon: mon['dex'], 0)
    assert quiet.first_wave is None
    candidate, deployed = result(first_wave=3, first_visit=[], pushed_out=[]), result()
    assert live_soak.measure(candidate)['first_wave_releases'] == 3
    assert live_soak.measure(deployed)['first_wave_releases'] is None
    assert live_soak.invariants(candidate, deployed) == []
    problems, rows = live_soak.judge([candidate], [deployed])
    assert problems == [] and rows[0]['candidate']['first_wave_releases'] == 3
    assert live_soak.report_line(rows[0]).endswith(' 3 first visit releases (- deployed)')


def test_the_window_catches_and_releases_are_reported_as_counts():
    releases = [('release', release_title('Pidgey')), ('release', release_title('Rattata'))]
    receipts = [('capture:1', 16, 0.0), ('capture:2', 19, 1.0), ('gift-event:1', 7, 2.0)]
    candidate = result(releases, receipts)
    measured = live_soak.measure(candidate)
    assert (measured['catches'], measured['window_releases']) == (2, 2)
    _, rows = live_soak.judge([candidate], [candidate])
    assert ' 2 caught 0 kept better 2 released - first visit releases ' in live_soak.report_line(rows[0])


def test_rates_hold_the_candidate_to_the_deployed_commit():
    deployed = result(gift_loop(1) + [('badge', 'Earned the Boulder Badge')] * 10)
    assert live_soak.invariants(deployed, deployed) == []
    many = result([('release', release_title(f'Spare{index}')) for index in range(12)])
    assert any('12.0 releases a game hour' in problem for problem in live_soak.invariants(many, deployed))
    assert any('real progress' in problem for problem in live_soak.invariants(result(), deployed))
    reloads = result(reloads={'auto-v1-1.state': 3})
    assert any('reloaded auto-v1-1.state 3 times' in problem for problem in live_soak.invariants(reloads, None))
    grown = result(journal_bytes=5 * live_soak.BYTES_FLOOR)
    assert any('grew' in problem for problem in live_soak.invariants(grown, result()))
    assert live_soak.invariants(result(journal_bytes=live_soak.BYTES_FLOOR), result()) == []


def test_a_title_sequence_repeated_five_times_fails():
    loop = [('trainer', 'Defeated Lance'), ('map', 'Reached Indigo Plateau')] * 5
    assert live_soak.repeated_sequence([title for _, title in loop]) == ['Defeated Lance', 'Reached Indigo Plateau']
    assert live_soak.repeated_sequence([title for _, title in loop[:-2]]) is None
    assert any('repeated' in problem for problem in live_soak.invariants(result(loop), result(loop)))


def test_a_failed_run_fails_the_gate():
    assert live_soak.invariants(result(failed='the worker failed'), result()) == ['Red: the run failed, the worker failed']


def test_check_needs_a_passing_smoke_for_that_commit(tmp_path, capsys):
    sha = 'a' * 40
    args = SimpleNamespace(sha=sha, reports=tmp_path)
    smokes = tmp_path / 'smoke'
    smokes.mkdir()
    assert live_soak.check(args) == 1
    (smokes / f'{sha}.json').write_text(json.dumps({'commit': sha, 'passed': False, 'problems': ['x']}))
    assert live_soak.check(args) == 1
    (smokes / f'{sha}.json').write_text(json.dumps({'commit': 'b' * 40, 'passed': True}))
    assert live_soak.check(args) == 1
    (smokes / f'{sha}.json').write_text(json.dumps({'commit': sha, 'passed': True}))
    assert live_soak.check(args) == 0
    assert 'no smoke report' in capsys.readouterr().err


def test_the_behaviour_comparison_is_printed_and_never_decides(tmp_path, capsys):
    sha = 'a' * 40
    args = SimpleNamespace(sha=sha, reports=tmp_path)
    (tmp_path / 'smoke').mkdir()
    (tmp_path / f'{sha}.json').write_text(json.dumps({'commit': sha, 'passed': True}))
    assert live_soak.check(args) == 1
    assert 'behaviour soak, advisory: aaaaaaa passed' in capsys.readouterr().err
    (tmp_path / 'smoke' / f'{sha}.json').write_text(json.dumps({'commit': sha, 'passed': True}))
    (tmp_path / f'{sha}.json').write_text(json.dumps({'commit': sha, 'passed': False, 'problems': ['x', 'y']}))
    assert live_soak.check(args) == 0
    assert 'found 2 problems' in capsys.readouterr().err


class SmokeWorkers:
    """A Manager with one adventure that plays 10000 frames a poll, saves its frame when stopped and loads
    its newest save on start. `save`, `reload_from` and `log` change what the worker does."""

    def __init__(self, root, save=True, reload_from=None, log='', stop_error=None):
        from pokesim.checkpoints import CheckpointStore
        self.root, self.save, self.reload_from, self.log, self.stop_error = root, save, reload_from, log, stop_error
        self.folder = root / 'adventures' / 'aid'
        self.states = CheckpointStore(self.folder / 'states')
        self.write(1000)
        self.frame, self.running, self.starts = None, False, 0
        self.registry = SimpleNamespace(
            root=root, adventure=lambda aid: {'name': 'Red', 'version': 'red', 'settings': {}, 'state': 'running'},
            update=lambda aid, **changes: None, request_lifecycle=lambda aid, kind, who: None)
        self.supervisor = SimpleNamespace(child=self.child, stop=self.stop)

    def write(self, frame):
        self.states.write_checkpoint(b'state', {'frame': frame, 'policy_state': {}, 'run_memory': {}})

    def start_adventure(self, aid):
        self.starts += 1
        newest = self.states.latest_state()
        self.frame = self.states.checkpoint_metadata(newest)['frame']
        if self.starts == 2 and self.reload_from is not None:
            self.frame = self.reload_from
        self.running = True
        logs = self.folder / 'logs'
        logs.mkdir(exist_ok=True)
        if (logs / 'worker.log').exists():
            (logs / 'worker.log').replace(logs / 'worker.previous.log')
        (logs / 'worker.log').write_text(f'12:00:00 INFO worker resumed\n{self.log if self.starts == 1 else ""}')

    def child(self, aid):
        if not self.running:
            raise RuntimeError('not running')
        frame, self.frame = self.frame, self.frame + 10000
        return SimpleNamespace(request=lambda method, path: {'frame': frame, 'game': {'party': []}})

    def stop(self, aid):
        if not self.running:
            return
        self.running = False
        if self.stop_error:
            raise RuntimeError(self.stop_error)
        if self.save:
            self.write(self.frame)


def smoke_once(tmp_path, monkeypatch, **changes):
    monkeypatch.setattr(live_soak, 'POLL_SECONDS', 0)
    return live_soak.smoke_one(SmokeWorkers(tmp_path, **changes), 'aid', live_soak.SMOKE_FRAMES, lambda line: None)


def test_the_smoke_passes_an_adventure_that_plays_saves_and_reloads(tmp_path, monkeypatch):
    outcome = smoke_once(tmp_path, monkeypatch)
    assert outcome['failed'] is None
    assert outcome['played'] - outcome['loaded'] >= live_soak.SMOKE_FRAMES
    assert outcome['saved'] >= outcome['played'] and outcome['reloaded'] == outcome['saved']


def test_the_smoke_fails_a_stop_that_writes_no_save(tmp_path, monkeypatch):
    assert 'the newest save is from frame 1000' in smoke_once(tmp_path, monkeypatch, save=False)['failed']


def test_the_smoke_fails_a_failed_stop(tmp_path, monkeypatch):
    outcome = smoke_once(tmp_path, monkeypatch, stop_error='The final save failed')
    assert outcome['failed'] == 'the save on stop failed, The final save failed'


def test_the_smoke_fails_a_reload_of_an_older_save(tmp_path, monkeypatch):
    assert 'older than its save' in smoke_once(tmp_path, monkeypatch, reload_from=1000)['failed']


@pytest.mark.parametrize('line', ['12:00:01 ERROR worker step failed', 'Traceback (most recent call last):',
                                  '12:00:01 WARNING pokesim.emulator cannot restore auto-v1-1.state: bad'])
def test_the_smoke_fails_an_error_or_a_refused_save_in_the_worker_log(tmp_path, monkeypatch, line):
    outcome = smoke_once(tmp_path, monkeypatch, log=line + '\n')
    assert outcome['failed'] == f'1 error line in its worker log, the first {line}'


def test_check_takes_a_passing_report_for_a_commit_with_the_same_tree(tmp_path, monkeypatch, capsys):
    # A merge commit identical to its soaked head once needed a second 10 minute soak to deploy.
    repo, reports = tmp_path / 'repo', tmp_path / 'reports'
    repo.mkdir()
    reports.mkdir()
    def git(*command):
        return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *command], cwd=repo,
                              capture_output=True, text=True, check=True).stdout.strip()
    git('init', '-q')
    (repo / 'a.txt').write_text('one')
    git('add', 'a.txt')
    git('commit', '-q', '-m', 'soaked')
    soaked = git('rev-parse', 'HEAD')
    git('commit', '-q', '--allow-empty', '-m', 'merge with no change')
    twin = git('rev-parse', 'HEAD')
    (repo / 'a.txt').write_text('two')
    git('commit', '-q', '-am', 'changed')
    changed = git('rev-parse', 'HEAD')
    monkeypatch.setattr(live_soak, 'ROOT', repo)
    smokes = reports / 'smoke'
    smokes.mkdir()
    (smokes / f'{soaked}.json').write_text(json.dumps({'commit': soaked, 'passed': True}))
    assert live_soak.check(SimpleNamespace(sha=twin, reports=reports)) == 0
    assert f'tree of {soaked[:7]}' in capsys.readouterr().err
    assert live_soak.check(SimpleNamespace(sha=changed, reports=reports)) == 1
    (smokes / f'{soaked}.json').write_text(json.dumps({'commit': soaked, 'passed': False}))
    assert live_soak.check(SimpleNamespace(sha=twin, reports=reports)) == 1


def test_the_copy_keeps_running_adventures_and_drops_private_files():
    keep = lambda name: live_soak._keep(SimpleNamespace(name=name), {'aid'})  # noqa: E731
    assert keep('./app/app.sqlite') and keep('app/assets/roms/x.gb') and keep('app/adventures/aid/pokesim.sqlite')
    assert keep('app/adventures/aid/states/auto-v1-1.state')
    for name in ('app/adventures/other/pokesim.sqlite', 'app/adventures/aid/logs/worker.log', 'app/.env',
                 'app/auth.sqlite', 'app/cli.token', 'app/adventures/aid/states/event-3.state',
                 'app/adventures/aid/shots/a.png'):
        assert not keep(name), name


def test_the_copied_registry_loses_notifications_trades_and_stopped_adventures(tmp_path):
    path = tmp_path / 'app.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE settings (key TEXT, value TEXT)')
        db.execute('CREATE TABLE adventures (id TEXT)')
        db.execute('CREATE TABLE interactions (id TEXT)')
        db.execute('CREATE TABLE trade_offers (id TEXT)')
        db.executemany('INSERT INTO settings VALUES (?, ?)', [('notifications', '{}'), ('max_running', '6')])
        db.executemany('INSERT INTO adventures VALUES (?)', [('aid',), ('stopped',)])
        db.execute("INSERT INTO trade_offers VALUES ('t')")
    db.close()
    live_soak.scrub_registry(path, ['aid'])
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT key FROM settings').fetchall() == [('max_running',)]
        assert db.execute('SELECT id FROM adventures').fetchall() == [('aid',)]
        assert db.execute('SELECT COUNT(*) FROM trade_offers').fetchone() == (0,)
    db.close()


def test_a_gate_report_counts_its_attempt(tmp_path):
    assert attempt(tmp_path, 'abc') == 1
    for index, commit in enumerate(('abc', 'def', 'abc')):
        (tmp_path / str(index)).mkdir()
        (tmp_path / str(index) / 'gate-report.json').write_text(json.dumps({'commit': commit}))
    assert attempt(tmp_path, 'abc') == 3


@pytest.mark.parametrize('schema,refused', [(1, True), (2, False), (3, False)])
def test_a_commit_older_than_the_data_schema_is_refused(tmp_path, schema, refused):
    (tmp_path / 'pokesim' / 'app').mkdir(parents=True)
    (tmp_path / 'pokesim' / 'app' / 'registry.py').write_text(f'SCHEMA = {schema}\n')
    assert (live_soak.schema_of(tmp_path) < 2) is refused


GITHUB_504 = ('error: Failed to fetch: `https://github.com/example/pokecore-0.11.0-py3-none-any.whl`\n'
              '  Caused by: HTTP status server error (504 Gateway Timeout)\n')


@pytest.mark.parametrize('first,offline,tries', [
    (GITHUB_504, 0, 2),  # a network failure is tried once more offline, from the cache
    ('error: The lockfile needs to be updated\n', None, 1),  # any other failure is not
])
def test_an_environment_build_retries_offline_only_after_a_network_error(monkeypatch, tmp_path, first, offline, tries):
    calls, lines = [], []

    def run(command, env, **kwargs):
        calls.append(env.get('UV_OFFLINE'))
        code = 1 if len(calls) == 1 else offline
        return SimpleNamespace(returncode=code, stdout='', stderr=first if code else '')
    monkeypatch.setattr(live_soak.subprocess, 'run', run)
    if offline is None:
        with pytest.raises(live_soak.subprocess.CalledProcessError):
            live_soak.sync_environment(tmp_path, {}, lines.append)
    else:
        live_soak.sync_environment(tmp_path, {}, lines.append)
    assert calls == [None, '1'][:tries]
    assert bool(lines) is (tries == 2)
    if lines:
        assert 'retrying offline' in lines[0] and 'Failed to fetch' in lines[0]
