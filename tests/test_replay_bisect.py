"""The replay tool's search, diverge report, environment keys and old-commit shim, without a cartridge."""
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.replay import __main__ as cli
from pokesim.replay import diverge, envs, search, shim
from pokesim.replay.search import STALL, WASTE, Bisect, Options, Run, first_bad, predicate


# The search over commits.

@pytest.mark.parametrize('jobs', [1, 3, 4])
def test_first_bad_finds_every_first_bad_position(jobs):
    for size in range(1, 26):
        for first in range(size):
            tested = []

            def is_bad(index, first=first):
                tested.append(index)
                return index >= first

            index, results, inversions = first_bad(list(range(size)), is_bad, jobs)
            assert index == first
            assert inversions == []
            assert set(results) == set(tested)
            # The last item is the bad end, already known.
            assert size - 1 not in tested


def test_first_bad_tests_about_log2_items_one_at_a_time():
    tested = []
    first_bad(list(range(139)), lambda index: tested.append(index) or index >= 100)
    assert len(tested) <= 8


def test_first_bad_reports_a_good_result_after_a_bad_one():
    bad = {2, 7}
    index, results, inversions = first_bad(list(range(8)), lambda index: index in bad, jobs=4)
    assert index == 2
    assert results == {1: False, 2: True, 4: False, 5: False}
    assert inversions == [4, 5]


def _run(waste=0.0, stall=None, ok=True):
    shim_report = {'code': 0 if ok else 1, 'attached': True, 'head': 'h'}
    return Run('c', Path('.'), shim_report, {'waste': waste, 'stall': stall} if ok else None)


def test_waste_predicate_uses_the_good_end_and_the_gate_margin():
    is_bad = predicate(WASTE, _run(1.3))
    assert is_bad(_run(3.4))
    assert not is_bad(_run(3.3))
    assert is_bad(_run(ok=False))


def test_stall_predicate_with_and_without_a_key():
    key = 'route:red_gyarados:LAKE_OF_RAGE:18,23'
    loop = {'reason': f'a retry loop: {key} stood down 4 times in a row'}
    other = {'reason': 'no progress for 20 game minutes'}
    keyed = predicate(STALL, _run(), stall_key=key)
    assert keyed(_run(stall=loop))
    assert not keyed(_run(stall=other))
    assert not keyed(_run())
    plain = predicate(STALL, _run())
    assert plain(_run(stall=other))
    assert not predicate(STALL, _run(stall=other))(_run(stall=loop))
    with pytest.raises(ValueError):
        predicate('both', _run())


def _git(root, *args):
    variables = {**os.environ, 'GIT_AUTHOR_NAME': 'test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
                 'GIT_COMMITTER_NAME': 'test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid'}
    done = subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True, env=variables)
    return done.stdout.strip()


@pytest.fixture
def history(tmp_path):
    """A main line: start, #10, a plain commit, #20, a merged side branch with #99 inside, #30, a tip."""
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    shas = {}
    for name in ('start', 'Fix one (#10)', 'Tidy', 'Fix two (#20)'):
        _git(root, 'commit', '-q', '--allow-empty', '-m', name)
        shas[name] = _git(root, 'rev-parse', 'HEAD')
    _git(root, 'checkout', '-q', '-b', 'side')
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'Side work (#99)')
    _git(root, 'checkout', '-q', 'main')
    _git(root, 'merge', '-q', '--no-ff', '-m', 'Merge side', 'side')
    shas['merge'] = _git(root, 'rev-parse', 'HEAD')
    for name in ('Fix three (#30)', 'tip'):
        _git(root, 'commit', '-q', '--allow-empty', '-m', name)
        shas[name] = _git(root, 'rev-parse', 'HEAD')
    return root, shas


def test_suspects_follow_the_first_parent_in_merge_order(history):
    root, shas = history
    found = search.suspects(shas['start'], shas['tip'], [30, 10, 99, 20], root=root)
    assert found == [(10, shas['Fix one (#10)']), (20, shas['Fix two (#20)']), (30, shas['Fix three (#30)'])]
    between = search.first_parent_range(shas['Fix one (#10)'], shas['Fix two (#20)'], root=root)
    assert between == [shas['Tidy'], shas['Fix two (#20)']]


def _search(history, monkeypatch, bad_from):
    """A bisect whose runs are made up: a commit wastes 20% from ``bad_from`` on, else 1%."""
    root, shas = history
    order = [shas[name] for name in ('start', 'Fix one (#10)', 'Tidy', 'Fix two (#20)', 'merge',
                                     'Fix three (#30)', 'tip')]
    played = []

    def record(options, rung, sha, n=1, pyboy=None):
        played.append(sha)
        return Run(sha, Path(sha), {'code': 0, 'attached': True, 'head': sha},
                   {'waste': 20.0 if order.index(sha) >= order.index(shas[bad_from]) else 1.0, 'stall': None})

    monkeypatch.setattr(search, 'record', record)
    monkeypatch.setattr(search.diverge, 'compare', lambda a, b: {'a': str(a), 'b': str(b)})
    options = Options(roms=Path('roms'), root=root)
    bisect = Bisect(options, 'silver/badges_6', shas['start'], shas['tip'], [10, 20, 30], jobs=2)
    try:
        return bisect.search(WASTE), shas, played
    finally:
        bisect.close()


def test_a_bad_suspect_with_a_good_parent_is_the_first_bad(history, monkeypatch):
    found, shas, _ = _search(history, monkeypatch, 'Fix two (#20)')
    assert found['first_bad']['commit'] == shas['Fix two (#20)']
    assert found['first_bad']['pull'] == 20
    assert found['parent'] == {'commit': shas['Tidy'], 'bad': False}
    assert found['diverge'] == {'a': shas['Tidy'], 'b': shas['Fix two (#20)']}
    assert 'between' not in found


def test_a_bad_parent_moves_the_search_to_the_commits_between(history, monkeypatch):
    found, shas, _ = _search(history, monkeypatch, 'Tidy')
    assert found['parent'] == {'commit': shas['Tidy'], 'bad': True}
    assert found['first_bad']['commit'] == shas['Tidy']
    assert found['first_bad']['pull'] is None
    assert found['before']['commit'] == shas['Fix one (#10)']
    text = search.markdown({'rung': 'silver/badges_6', 'good': shas['start'], 'bad': shas['tip'],
                            'pyboy': 'current', 'frames': 1, 'searches': [{**found, 'diverge': None}]})
    assert 'First bad: a commit outside the suspects' in text


def test_a_search_stops_when_the_ends_do_not_disagree(history, monkeypatch):
    found, _, played = _search(history, monkeypatch, 'start')
    assert found['stopped'] == 'the bad end is not bad under this predicate'
    assert len(set(played)) == 2


# The diverge report.

def _records(*items, start=100):
    out = []
    for index, (frame, kind, extra) in enumerate(items, 1):
        out.append({'index': index, 'frame': start + frame, 'kind': kind, 'hash': f'{index}', **extra})
    return out


def _decide(goal, digest='d', map=1, x=2, y=3):
    return {'goal': goal, 'digest': digest, 'map': map, 'x': x, 'y': y}


def test_first_difference_names_the_action_and_the_decide_before_it():
    a = _records((0, 'hook', {'name': 'x'}), (0, 'decide', _decide('boot')), (0, 'press', {'button': 'a'}),
                 (4, 'decide', _decide('route:x')), (4, 'press', {'button': 'up'}), (8, 'tick', {'frames': 4}))
    b = _records((0, 'decide', _decide('boot')), (0, 'press', {'button': 'a'}),
                 (4, 'decide', _decide('route:x')), (4, 'press', {'button': 'down'}), (8, 'tick', {'frames': 4}),
                 start=500)
    found = diverge.first_difference(a, b, diverge.ACTIONS, starts=(100, 500))
    assert found['position'] == 1
    assert found['a']['what'] == 'press up'
    assert found['b']['what'] == 'press down'
    assert found['a']['frame'] == 4
    assert found['a']['decide'] == {'frame': 4, 'goal': 'route:x', 'map': 1, 'x': 2, 'y': 3}
    assert found['a']['next'] == ['press up', 'tick 4']


def test_a_memory_difference_shows_in_records_before_actions():
    a = _records((0, 'decide', _decide('boot', 'one')), (0, 'press', {'button': 'a'}))
    b = _records((0, 'decide', _decide('boot', 'two')), (0, 'press', {'button': 'a'}))
    assert diverge.first_difference(a, b)['position'] == 0
    assert diverge.first_difference(a, b, diverge.ACTIONS) is None


def test_a_shorter_trace_ends_first():
    a = _records((0, 'press', {'button': 'a'}))
    b = _records((0, 'press', {'button': 'a'}), (2, 'release', {'button': 'a'}))
    found = diverge.first_difference(a, b)
    assert found['ended'] == 'a'
    assert found['b']['what'] == 'release a'
    assert 'a' not in found


def test_goal_divergence_compares_goal_changes():
    a = _records((0, 'decide', _decide('boot')), (5, 'decide', _decide('boot')), (9, 'decide', _decide('heal')))
    b = _records((0, 'decide', _decide('boot')), (5, 'decide', _decide('boot')), (12, 'decide', _decide('heal')))
    found = diverge.goal_divergence(a, b, starts=(100, 100))
    assert found['change'] == 1
    assert (found['a']['frame'], found['b']['frame']) == (9, 12)
    assert found['before']['goal'] == 'boot'
    assert diverge.goal_divergence(a, a, starts=(100, 100)) is None


def test_stand_down_loops_and_the_decide_that_began_them():
    key = 'route:red_gyarados:LAKE_OF_RAGE:18,23'
    run_file = {'frames': 1000, 'wasted': {'a': 300, 'b': 100},
                'stand_downs': [{'key': key, 'goal': f'{key} (row)', 'frame': 5000 + frame}
                                for frame in (200, 500, 800)]}
    downs = diverge.stand_downs(run_file, run_frame=5000)
    assert [entry['offset'] for entry in downs] == [200, 500, 800]
    assert diverge.loops(downs) == {key: {'count': 3, 'first': 5200, 'periods': [300, 300]}}
    changes = [{'frame': 10, 'goal': 'boot'}, {'frame': 150, 'goal': key}, {'frame': 400, 'goal': key}]
    assert diverge.loop_start(changes, downs) == changes[1]
    assert diverge.wasted_rows(run_file) == [{'row': 'a', 'frames': 300, 'share': 30.0},
                                             {'row': 'b', 'frames': 100, 'share': 10.0}]


def test_two_commits_with_the_same_records_say_so():
    info = {'commit': 'c' * 40, 'pyboy': '0.1.5', 'frames': 10, 'waste': 0.0, 'stall': None, 'records': 3,
            'wasted_rows': [], 'loops': {}, 'loop_start': None}
    report = {'a': info, 'b': info, 'same_head': False, 'same_records': True, 'first_record': None,
              'first_action': None, 'first_goal': None}
    assert 'only the headers differ' in diverge.markdown(report)


def _clock(call, at, follow=True):
    return {'source': 'clock', 'payload': {'call': call, 'args': [], 'kwargs': {'at': at, 'follow_frames': follow}}}


def test_wall_clock_readings_differ_without_parting_the_play():
    a = _records((0, 'decide', _decide('boot')), (0, 'input', _clock('lock_clock', 1.5)), (2, 'press', {'button': 'a'}))
    b = _records((0, 'decide', _decide('boot')), (0, 'input', _clock('lock_clock', 9.25)), (2, 'press', {'button': 'a'}))
    assert diverge.first_difference(a, b)['position'] == 1
    assert diverge.first_difference(a, b, clock_values=False) is None
    assert diverge.clock_readings(a, b) == 1
    # Another call or another flag still parts the play.
    for other in (_clock('advance_clock', 1.5), _clock('lock_clock', 1.5, follow=False)):
        c = _records((0, 'decide', _decide('boot')), (0, 'input', other), (2, 'press', {'button': 'a'}))
        assert diverge.first_difference(a, c, clock_values=False)['position'] == 1


def test_the_self_check_passes_two_runs_whose_clock_readings_alone_differ(monkeypatch):
    one, two = _run(), _run()
    two.shim = {**two.shim, 'head': 'other'}
    monkeypatch.setattr(search.diverge, 'compare', lambda a, b: {'clock_only': True, 'clock_readings': 2})
    check = search.twice(one, two)
    assert (check['same_head'], check['same'], check['reason']) == (False, True, 'only wall-clock readings differ')
    monkeypatch.setattr(search.diverge, 'compare', lambda a, b: {'clock_only': False, 'clock_readings': 0})
    assert search.twice(one, two)['same'] is False
    assert search.twice(one, one) == {'same_head': True, 'same': True, 'reason': 'same head'}
    assert search.twice(one, _run(ok=False))['reason'] == 'a run failed'


# Environments.

def test_env_key_covers_the_lock_the_core_tree_and_the_pyboy_choice():
    key = envs.env_key(b'lock', 'tree', 'current')
    assert key == envs.env_key(b'lock', 'tree', 'current')
    assert len({key, envs.env_key(b'lock2', 'tree', 'current'), envs.env_key(b'lock', None, 'current'),
                envs.env_key(b'lock', 'tree', 'own')}) == 4


def test_wheel_for_machine_picks_this_platform(monkeypatch):
    base = 'https://example.invalid/pyboy_rs-0.1.5-cp311-abi3-'
    lock = {'package': [{'name': 'pyboy-rs', 'version': '0.1.5', 'wheels': [
        {'url': base + 'macosx_11_0_arm64.whl', 'hash': 'sha256:aa'},
        {'url': base + 'manylinux_2_17_aarch64.whl', 'hash': 'sha256:bb'},
        {'url': base + 'manylinux_2_17_x86_64.whl', 'hash': 'sha256:cc'},
        {'url': base + 'win_amd64.whl', 'hash': 'sha256:dd'}]}]}
    monkeypatch.setattr(envs.sys, 'platform', 'linux')
    monkeypatch.setattr(envs.platform, 'machine', lambda: 'x86_64')
    assert envs.wheel_for_machine(lock) == ('0.1.5', base + 'manylinux_2_17_x86_64.whl#sha256=cc')
    monkeypatch.setattr(envs.sys, 'platform', 'win32')
    monkeypatch.setattr(envs.platform, 'machine', lambda: 'AMD64')
    assert envs.wheel_for_machine(lock)[1].endswith('win_amd64.whl#sha256=dd')
    monkeypatch.setattr(envs.sys, 'platform', 'darwin')
    monkeypatch.setattr(envs.platform, 'machine', lambda: 'arm64')
    assert envs.wheel_for_machine(lock)[1].endswith('arm64.whl#sha256=aa')
    with pytest.raises(LookupError):
        envs.wheel_for_machine({'package': []})


def test_this_checkout_names_a_pyboy_wheel():
    if sys.platform not in ('linux', 'darwin', 'win32'):
        pytest.skip('no wheel for this platform')
    version, url = envs.current_pyboy()
    assert version and '#sha256=' in url


# The shim that records an old commit.

class _Recorder:
    def __init__(self, emulator):
        self.emulator, self.detached, self.begun, self.events = emulator, False, None, []

    def detach(self):
        self.detached = True

    def begin(self, segment, **fields):
        self.begun = (segment, fields)

    def decide(self, goal, map, x, y):
        self.events.append(('decide', goal, map, x, y))

    def input(self, source, payload):
        self.events.append(('input', source, payload))


@pytest.fixture
def state(tmp_path, monkeypatch):
    trace = SimpleNamespace(Recorder=_Recorder, Segment=lambda path, keep_start: ('segment', path, keep_start))
    monkeypatch.setattr(shim, 'STATE', shim.State(trace, tmp_path, {'commit': 'abc'}))
    return shim.STATE


def test_the_shim_records_the_run_emulator_and_logs_decides_before_presses(state):
    class Emulator:
        pass

    class Policy:
        goal = SimpleNamespace(key='route:x')

        def step(self, context):
            return ['a']

    class HeadlessRun:
        def __init__(self):
            self.scratch = Emulator()
            self.pb = Emulator()
            self.policy = Policy()
            self.frame = 789

        def step(self, snapshot):
            actions = self.policy.step(SimpleNamespace(snapshot=snapshot))
            state.recorder.events.append(('press', *actions))

    shim.wrap_emulator(Emulator)
    module = types.ModuleType('pokesim.headless')
    module.HeadlessRun = HeadlessRun
    shim.wrap_run(module)
    shim.wrap_run(module)
    run = HeadlessRun()
    run.step(SimpleNamespace(map=3, x=4, y=5))
    run.step(SimpleNamespace(map=3, x=4, y=6))
    assert state.recorder.emulator is run.pb
    assert state.recorder.begun[1] == {'commit': 'abc', 'run_frame': 789}
    assert state.recorder.begun[0][2] is True
    assert state.recorder.events == [('decide', 'route:x', 3, 4, 5), ('press', 'a'),
                                     ('decide', 'route:x', 3, 4, 6), ('press', 'a')]
    assert state.runs == 1 and state.decides == 2


def test_the_shim_logs_each_goal_reseed_with_its_digest(state):
    emulator = object()
    state.recorder = _Recorder(emulator)
    module = types.ModuleType('pokesim.replay.rung')

    class GoalSeeds:
        def __init__(self):
            self.starts = {'route:x': 2}

        def seed(self, key, occurrence):
            return bytes([occurrence])

        def start(self, run, key):
            return 'started'

    GoalSeeds.__module__ = module.__name__
    module.GoalSeeds = GoalSeeds
    shim.wrap_seeds(module)
    assert GoalSeeds().start(SimpleNamespace(pb=emulator), 'route:x') == 'started'
    GoalSeeds().start(SimpleNamespace(pb=object()), 'route:x')
    assert state.recorder.events == [('input', 'goal_seed', {'key': 'route:x', 'occurrence': 2, 'digest': '02'})]


# The command line.

def test_the_command_line_takes_its_folders_from_the_data_folder(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.delenv('GEN2_DATA_DIR', raising=False)
    args = cli.parse(['bisect', '--rung', 'silver/badges_6', '--roms', 'roms', '--good', 'a', '--bad', 'b',
                      '--suspects', '#344,346', '--predicate', 'both'])
    options = cli._options(args)
    assert options.ladders == tmp_path / 'ladder'
    assert options.out == tmp_path / 'ladder' / 'replay'
    assert options.data_dir == tmp_path
    assert options.data_root is None
    assert args.jobs == 4 and args.pyboy == 'current'
