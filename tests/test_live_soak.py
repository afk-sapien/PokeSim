"""tools/live_soak.py holds a candidate to the deployed commit on copies of the live adventures.

The journal titles come from the real producers, so a change to a title breaks these tests and not
only the gate.
"""
import json
import sqlite3
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


COMMON, PLAIN, RARE, RARER = (0, 2, 2, 2, 2), (0, 4, 4, 4, 4), (0, 8, 8, 8, 8), (0, 12, 12, 12, 12)
TAILS = {COMMON: 0.9, PLAIN: 0.6, RARE: 0.2, RARER: 0.05}


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


def test_a_newcomer_of_another_species_counts_against_a_rarer_release():
    copies = live_soak.Copies(lambda dex, dvs: TAILS[tuple(dvs)])
    for held, released in (([(16, RARE), (19, PLAIN)], False), ([(16, RARE), (19, PLAIN), (19, COMMON)], False),
                           ([(19, PLAIN), (19, COMMON)], True)):
        copies.poll({'party': [], 'storage': {'pokemon': [{'dex': dex, 'dvs': list(dvs)} for dex, dvs in held]}},
                    lambda mon: mon['dex'], released)
    assert copies.pushed_out == [{'dex': 16, 'dvs': list(RARE), 'tail': 0.2, 'by': 0.9}]


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
    assert ' 2 caught 2 released - first visit releases ' in live_soak.report_line(rows[0])


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


def test_check_needs_a_passing_report_for_that_commit(tmp_path, capsys):
    sha = 'a' * 40
    args = SimpleNamespace(sha=sha, reports=tmp_path)
    assert live_soak.check(args) == 1
    (tmp_path / f'{sha}.json').write_text(json.dumps({'commit': sha, 'passed': False, 'problems': ['x']}))
    assert live_soak.check(args) == 1
    (tmp_path / f'{sha}.json').write_text(json.dumps({'commit': 'b' * 40, 'passed': True}))
    assert live_soak.check(args) == 1
    (tmp_path / f'{sha}.json').write_text(json.dumps({'commit': sha, 'passed': True}))
    assert live_soak.check(args) == 0
    assert 'no report' in capsys.readouterr().err


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
