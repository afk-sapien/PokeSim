"""The stage ladder: which rung a moment counts for, the stall loop, adopting a save, and fresh saves that replay."""
import gzip
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import stage_ladder
from tools.stage_ladder import GEN1_LORELEI, main, reached

ROOT = Path(__file__).resolve().parents[1]
RED_ROM = Path(os.environ.get('ROM_PATH', ROOT / 'roms' / 'pokered.gb'))
CARTRIDGES = Path(os.environ.get('GEN2_CARTRIDGE_DIR', ROOT / 'roms'))
GEN2_DATA = os.environ.get('GEN2_DATA_DIR')


def gen1(**fields):
    return SimpleNamespace(**{'map': 0, 'badges': 0, 'hall_of_fame_count': 0, **fields})


def gen2(constant='NEW_BARK_TOWN', **fields):
    data = SimpleNamespace(maps={(1, 1): {'constant': constant}})
    return SimpleNamespace(**{'map': (1, 1), 'badges': 0, 'hall_of_fame_count': 0, 'data': data, **fields})


def test_gen1_rungs_follow_badges_the_first_league_room_and_the_hall_of_fame():
    assert reached(1, gen1(), {}) == {'new_game'}
    assert reached(1, gen1(badges=0b111), {}) == {'new_game', 'badges_2'}
    assert reached(1, gen1(badges=0xFF, map=GEN1_LORELEI), {}) >= {'badges_8', 'league_first'}
    # Back in Lorelei's room for a rematch is neither the first League nor post-game.
    assert not reached(1, gen1(badges=0xFF, map=GEN1_LORELEI, hall_of_fame_count=1), {}) & {'league_first', 'post_game'}
    assert 'post_game' in reached(1, gen1(badges=0xFF, map=0, hall_of_fame_count=1), {})


def test_gen2_rungs_count_johto_badges_and_follow_the_story_after_the_league():
    assert reached(2, gen2(badges=0xFF00), {}) == {'new_game'}
    assert 'badges_4' in reached(2, gen2(badges=0x0F), {})
    assert 'league_first' in reached(2, gen2('WILLS_ROOM', badges=0xFF), {})
    assert 'champion_first' not in reached(2, gen2('HALL_OF_FAME', hall_of_fame_count=1), {})
    after = reached(2, gen2('VERMILION_CITY', hall_of_fame_count=1), {'kanto': True})
    assert after >= {'champion_first', 'kanto_entry'} and 'post_game' not in after
    assert 'red' in reached(2, gen2('SILVER_CAVE_OUTSIDE', hall_of_fame_count=1), {'kanto': True})
    done = reached(2, gen2('NEW_BARK_TOWN', hall_of_fame_count=2), {'kanto': True, 'red': True})
    assert 'post_game' in done and not done & {'champion_first', 'kanto_entry', 'red'}


class FakeRun:
    """A Gen I run that never achieves anything, so every quiet window is a stall."""
    generation = 1

    def __init__(self):
        self.frame, self.reloads = 0, []
        self.policy = SimpleNamespace(details=lambda: {'reason': 'Walking in circles'}, goal=None)
        self.pb = SimpleNamespace(tick=lambda frames, render: None)

    def save(self, path, compress=False):
        path.write_bytes(b'state')
        path.with_suffix('.json').write_text(json.dumps({'frame': self.frame}), encoding='utf-8')
        return path

    def step(self, snapshot):
        self.frame += 600

    def reload(self, path):
        self.reloads.append(json.loads(Path(path).with_suffix('.json').read_text(encoding='utf-8'))['frame'])

    def stop(self):
        pass


class QuietWatch:
    loop = None

    def observe(self, snapshot):
        return [], False

    def marks(self, snapshot):
        return []

    def battle_clock(self, snapshot, since, frame):
        return None

    def reset(self):
        pass


def test_a_stall_keeps_a_bundle_and_goes_back_to_the_save_before_it(tmp_path, monkeypatch):
    run = FakeRun()
    cartridge = SimpleNamespace(version='red', generation=1, sha1='abc')
    snapshot = SimpleNamespace(valid=True, in_battle=0, textbox=False, start_menu=False, map=0x26, badges=0,
                               hall_of_fame_count=0)
    monkeypatch.setattr(stage_ladder, 'prepare', lambda rom, code: (cartridge, ''))
    monkeypatch.setattr(stage_ladder, 'open_fresh', lambda *args: (run, QuietWatch(), lambda: snapshot))
    ladder = tmp_path / 'red'
    assert main(['snapshot', 'red.gb', str(ladder), '--quiet', '30', '--max-stalls', '2', '--game-hours', '3']) == 1
    report = json.loads((ladder / 'snapshot-report.json').read_text(encoding='utf-8'))
    assert [kept['rung'] for kept in report['kept']] == ['new_game']
    assert [stall['reason'] for stall in report['stalls']] == ['nothing achieved for 30 game minutes'] * 2
    assert report['gave_up'] == 'too many stalls' and report['missing'][0] == 'badges_2'
    # The first stall went back to the save taken at the start, the last progress there was.
    assert run.reloads == [0]
    bundle = ladder / report['stalls'][0]['bundle']
    assert {path.name for path in bundle.iterdir()} >= {'before.state', 'before.json', 'noticed.state', 'report.json'}
    assert json.loads((bundle / 'report.json').read_text(encoding='utf-8'))['policy_reason'] == 'Walking in circles'
    assert json.loads((ladder / 'new_game' / 'scenario.json').read_text(encoding='utf-8'))['name'] == 'ladder-red-new_game'
    assert not (ladder / '.work').exists()


def test_a_repeat_stall_in_the_same_minute_keeps_both_bundles(tmp_path):
    run = FakeRun()
    snap = SimpleNamespace(map=0x26)
    first = stage_ladder._bundle(run, snap, tmp_path, None, 'first', ['badges_2'], 90, [])
    second = stage_ladder._bundle(run, snap, tmp_path, None, 'second', ['badges_2'], 90, [])
    assert (first['bundle'], second['bundle']) == ('stalls/stall-00090m', 'stalls/stall-00090m-2')
    assert json.loads((tmp_path / first['bundle'] / 'report.json').read_text(encoding='utf-8'))['reason'] == 'first'


def test_pruning_a_rolling_save_removes_its_manifest_too(tmp_path):
    run = FakeRun()
    rolling = [(frame, run.save(tmp_path / f'rolling-{frame}.state')) for frame in (0, 600, 1200)]
    stage_ladder._prune(rolling, 700)
    assert [frame for frame, _ in rolling] == [600, 1200]
    assert sorted(path.name for path in tmp_path.iterdir()) == ['rolling-1200.json', 'rolling-1200.state',
                                                                'rolling-600.json', 'rolling-600.state']


def test_adopt_keeps_an_existing_save_compressed(tmp_path):
    ladder = tmp_path / 'blue'
    ladder.mkdir()
    (ladder / 'ladder.json').write_text(json.dumps({'game': 'blue', 'generation': 1, 'rom_sha1': 'abc',
                                                    'randomizer': ''}), encoding='utf-8')
    source = tmp_path / 'hall.state'
    source.write_bytes(b'\0' * 1000)
    source.with_suffix('.json').write_text(json.dumps({'rom_sha1': 'abc', 'frame': 9}), encoding='utf-8')
    assert main(['adopt', str(ladder), 'post_game', str(source)]) == 0
    rung = ladder / 'post_game'
    assert gzip.decompress((rung / 'start.state').read_bytes()) == b'\0' * 1000
    assert json.loads(gzip.decompress((rung / 'start.json').read_bytes()))['frame'] == 9
    with pytest.raises(SystemExit, match='exists'):
        main(['adopt', str(ladder), 'post_game', str(source)])
    with pytest.raises(SystemExit, match='no rung'):
        main(['adopt', str(ladder), 'red', str(source)])


def test_ladders_stay_out_of_the_tracked_checkout():
    with pytest.raises(SystemExit, match='private game data'):
        main(['snapshot', str(RED_ROM), str(ROOT / 'tests' / 'ladder')])


@pytest.mark.skipif(not RED_ROM.exists(), reason='no ROM')
def test_a_fresh_red_run_saves_compressed_and_replays(tmp_path):
    from pokesim.headless import HeadlessRun
    from pokesim.ram import read_snapshot
    run = HeadlessRun(RED_ROM)
    try:
        while run.frame < 20000:
            run.step(read_snapshot(run.pb.memory, run.frame))
        path = run.save(tmp_path / 'fresh.state', compress=True)
        frame = run.frame
    finally:
        run.stop()
    assert path.read_bytes()[:2] == b'\x1f\x8b' and (tmp_path / 'fresh.json').read_bytes()[:2] == b'\x1f\x8b'
    again = HeadlessRun(RED_ROM, path)
    try:
        assert again.frame == frame
    finally:
        again.stop()
    from pokecore.save_summary import summarize_save
    from pokesim.checkpoints import open_state
    with open_state(path) as handle:
        image = stage_ladder.rung_save(RED_ROM.read_bytes(), {'generation': 1, 'game': 'red'}, handle.read())
    # By frame 20000 the run may already hold its starter.
    assert summarize_save(image).stage in ('new game', '0 badges')


def test_a_randomized_run_boots_the_patched_cartridge(monkeypatch):
    if not RED_ROM.exists():
        pytest.skip('no ROM')
    import pokesim.randomized
    booted = []
    real = pokesim.randomized.rom_stream
    monkeypatch.setattr(pokesim.randomized, 'rom_stream', lambda rom: booted.append(rom) or real(rom))
    from pokesim.headless import HeadlessRun
    HeadlessRun(RED_ROM).stop()
    assert booted == [RED_ROM]


@pytest.mark.skipif(not GEN2_DATA or not (CARTRIDGES / 'gold.gbc').exists(), reason='needs GEN2_DATA_DIR and Gold')
def test_a_fresh_gold_ladder_keeps_a_new_game_rung_the_scenarios_replay(tmp_path):
    from pokesim.scenarios import Scenario, open_run
    ladder = tmp_path / 'gold'
    main(['snapshot', str(CARTRIDGES / 'gold.gbc'), str(ladder), '--game-hours', '0.05'])
    scenario = Scenario.load(ladder / 'new_game')
    assert scenario.name == 'ladder-gold-new_game'
    run, _ = open_run(scenario, CARTRIDGES / 'gold.gbc')
    try:
        assert run.frame > 0 and run.read().started
    finally:
        run.stop()
    assert main(['check', str(CARTRIDGES), str(tmp_path)]) == 0


def test_each_rung_names_the_stage_its_save_should_read_as():
    assert stage_ladder.expected_stage(1, 'badges_6') == '6 badges'
    assert stage_ladder.expected_stage(1, 'post_game') == 'post-game'
    # Gen II's red rung stands outside Mt. Silver before the fight, and only the credits mean beaten.
    assert stage_ladder.expected_stage(2, 'red') == 'kanto entered'
    assert stage_ladder.expected_stage(2, 'post_game') == 'red beaten'
    for generation in (1, 2):
        assert all(stage_ladder.expected_stage(generation, rung) for rung in stage_ladder.rungs_for(generation, False))


def test_check_fails_on_a_rung_whose_save_reads_as_another_stage(tmp_path, monkeypatch, capsys):
    import hashlib
    import pokecore.save_summary
    roms = tmp_path / 'roms'
    roms.mkdir()
    (roms / 'any-name.gb').write_bytes(b'cartridge')
    ladder = tmp_path / 'ladders' / 'red'
    for rung in ('new_game', 'badges_2'):
        (ladder / rung).mkdir(parents=True)
        (ladder / rung / 'start.state').write_bytes(gzip.compress(rung.encode()))
    (ladder / 'ladder.json').write_text(json.dumps({'game': 'red', 'generation': 1, 'randomizer': '',
                                                    'rom_sha1': hashlib.sha1(b'cartridge').hexdigest()}))
    stages = {'new_game': 'new game', 'badges_2': '2 badges'}
    monkeypatch.setattr(stage_ladder, 'rung_save', lambda rom, info, state: state.decode())
    monkeypatch.setattr(pokecore.save_summary, 'summarize_save', lambda save: SimpleNamespace(stage=stages[save]))
    assert main(['check', str(roms), str(tmp_path / 'ladders')]) == 0
    stages['badges_2'] = '3 badges'
    assert main(['check', str(roms), str(tmp_path / 'ladders')]) == 1
    assert 'red/badges_2: the save reads as 3 badges, not 2 badges' in capsys.readouterr().out
    (roms / 'any-name.gb').unlink()
    assert main(['check', str(roms), str(tmp_path / 'ladders')]) == 1


def _result(rung, waste=10.0, errors=0, stall=None, ladder='gold'):
    return {'ladder': ladder, 'rung': rung, 'waste': waste, 'errors': errors,
            'stall': stall and {'reason': stall, 'bundle': 'stalls/stall-00010m'}}


def test_the_gate_fails_on_a_new_stall_more_errors_or_waste_up_more_than_two_points():
    baseline = {'gold/badges_2': {'stall': None, 'errors': 0, 'waste': 10.0},
                'gold/red': {'stall': 'a retry loop', 'errors': 1, 'waste': 50.0}}
    assert stage_ladder.compare([_result('badges_2', waste=11.9), _result('red', waste=48.0, errors=1, stall='quiet'),
                                 _result('post_game', waste=90.0, stall='quiet')], baseline) == []
    problems = stage_ladder.compare([_result('badges_2', waste=12.5, errors=2, stall='nothing achieved'),
                                     {'ladder': 'gold', 'rung': 'red', 'failed': 'exit 1'}], baseline)
    assert problems == ['gold/badges_2: a new stall, nothing achieved', 'gold/badges_2: 2 errors, 0 before',
                        'gold/badges_2: 12.5% wasted, 10.0% before', 'gold/red: the run failed, exit 1']


def _ladder(root, name, generation, randomizer, rungs):
    folder = root / name
    for rung in rungs:
        (folder / rung).mkdir(parents=True)
        (folder / rung / 'start.state').write_bytes(b'state')
    (folder / 'ladder.json').write_text(json.dumps({'game': name, 'generation': generation, 'rom_sha1': 'aa',
                                                    'randomizer': randomizer}), encoding='utf-8')


def test_the_gate_takes_the_heavy_lock_and_plays_every_rung_niced_in_its_own_process(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'ladders'
    _ladder(root, 'red', 1, '', ['new_game', 'badges_2'])
    _ladder(root, 'red-randomized', 1, 'PSR1-RED-WS-1', ['badges_4'])
    calls = []

    def fake(command, env, **_):
        calls.append((command, env))
        if 'gate-rung' in command:
            ladder, rung, out = Path(command[command.index('gate-rung') + 1]), *command[command.index('gate-rung') + 2:][:2]
            waste = 30.0 if rung == 'badges_4' else 10.0
            Path(out, 'summary.json').write_text(json.dumps(_result(rung, waste, ladder=ladder.name)), encoding='utf-8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stage_ladder.subprocess, 'run', fake)
    monkeypatch.delenv(stage_ladder.GATE_HELD, raising=False)
    monkeypatch.setenv('POKESIM_GEN1_VARIANT', 'yellow')
    args = ['gate', str(tmp_path / 'roms'), str(root), '--out', str(tmp_path / 'out')]
    assert main(args) == 0
    command, env = calls.pop()
    assert command[:3] == ['sh', str(stage_ladder.ROOT / 'tools' / 'load_gate.sh'), 'heavy'] and command[-len(args):] == args
    assert env[stage_ladder.GATE_HELD] == '1'
    monkeypatch.setenv(stage_ladder.GATE_HELD, '1')
    assert main(args + ['--write-baseline']) == 0
    assert len(calls) == 3 and all(command[:3] == ['nice', '-n', '10'] for command, _ in calls)
    assert all('POKESIM_GEN1_VARIANT' not in env for _, env in calls)
    stored = json.loads((root / 'gate-baseline.json').read_text(encoding='utf-8'))
    assert stored['frames'] == stage_ladder.GATE_FRAMES and set(stored['rungs']) == \
        {'red/new_game', 'red/badges_2', 'red-randomized/badges_4'}
    assert main(args) == 0
    stored['rungs']['red-randomized/badges_4']['waste'] = 20.0
    (root / 'gate-baseline.json').write_text(json.dumps(stored), encoding='utf-8')
    capsys.readouterr()
    assert main(args) == 1
    assert 'red-randomized/badges_4: 30.0% wasted, 20.0% before' in capsys.readouterr().out
    with pytest.raises(SystemExit, match='108000'):
        main(args + ['--frames', '36000'])


@pytest.mark.skipif(shutil.which('flock') is None, reason='needs flock')
def test_a_load_gate_inside_a_heavy_run_runs_at_once(tmp_path, monkeypatch):
    # A gate run under the heavy lock once waited 14 hours on the lock its own parent held.
    monkeypatch.setenv('POKESIM_LOAD_GATE', str(tmp_path))
    monkeypatch.delenv('POKESIM_LOAD_GATE_HEAVY', raising=False)
    gate = str(stage_ladder.ROOT / 'tools' / 'load_gate.sh')
    nested = ['sh', gate, 'heavy', 'sh', gate, 'heavy', 'sh', gate, 'pytest', 'echo', 'ran']
    done = subprocess.run(nested, capture_output=True, text=True, timeout=30, check=True)
    assert done.stdout == 'ran\n'
