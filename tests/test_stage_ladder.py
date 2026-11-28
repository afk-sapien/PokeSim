"""The stage ladder: which rung a moment counts for, the stall loop, adopting a save, and fresh saves that replay."""
import contextlib
import gzip
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.replay.rung import shares
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

    def state(self):
        return b'state'

    def manifest(self):
        return {'frame': self.frame}

    def save(self, path, compress=False):
        path.write_bytes(self.state())
        path.with_suffix('.json').write_text(json.dumps(self.manifest()), encoding='utf-8')
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


@pytest.mark.parametrize('game, generation', [('red', 1), ('crystal', 2)])
def test_adopt_with_an_adventure_carries_the_rows_a_headless_run_observes(tmp_path, game, generation):
    from pokesim.legendary_returns import STEPS
    from pokesim.state import claims
    from pokesim.store import Store
    ladder = tmp_path / f'{game}-deep'
    ladder.mkdir()
    (ladder / 'ladder.json').write_text(json.dumps({'game': game, 'generation': generation, 'rom_sha1': 'abc',
                                                    'randomizer': ''}), encoding='utf-8')
    source = tmp_path / 'auto.state'
    source.write_bytes(b'\0' * 1000)
    source.with_suffix('.json').write_text(json.dumps({'rom_sha1': 'abc', 'frame': 9}), encoding='utf-8')
    adventure = Store(tmp_path / 'adventure')
    adventure.set(STEPS, {'total': 4321, 'available': True})
    adventure.set('boss_losses', {'brock': 2})
    with adventure.transaction() as db:
        claims.put(db, 'legendary', '144', claims.DELIVERED, frame=60, species=144)
        claims.put(db, 'league', 'won-1', claims.DELIVERED, frame=30)
    adventure.close()
    assert main(['adopt', str(ladder), 'post_game', str(source), '--adventure', str(tmp_path / 'adventure')]) == 0
    carried = json.loads(gzip.decompress((ladder / 'post_game' / 'start.json').read_bytes()))['store_rows']
    assert carried['kv'] == {STEPS: {'total': 4321, 'available': True}}
    assert [(row['source'], row['key']) for row in carried['claims']] == [('legendary', '144')]


def test_ladders_stay_out_of_the_tracked_checkout():
    with pytest.raises(SystemExit, match='private game data'):
        main(['snapshot', str(RED_ROM), str(ROOT / 'tests' / 'ladder')])


@pytest.mark.skipif(not RED_ROM.exists(), reason='no ROM')
def test_a_fresh_red_run_saves_compressed_and_replays(tmp_path):
    from pokesim.runtime.headless import HeadlessRun
    run = HeadlessRun(RED_ROM)
    try:
        while run.frame < 20000:
            run.step(run.read())
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
    from pokesim.runtime.headless import HeadlessRun
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


def _result(rung, waste=10.0, errors=0, stall=None, ladder='gold', story=None, restock=5.0):
    result = {'ladder': ladder, 'rung': rung, 'waste': waste, 'restock': restock, 'heal': 2.0, 'pc': 1.0,
              'errors': errors, 'stall': stall and {'reason': stall, 'bundle': 'stalls/stall-00010m'}}
    if story is not None:
        result['story'] = list(story)
    return result


GOLD_BASE = {'gold/badges_6': {'stall': None, 'errors': 0, 'waste': 10.0, 'story': ['fog', 'storm']}}


def test_a_rung_past_its_baseline_goal_passes_with_a_flag_up_to_ten_points_more_waste():
    # Further along the story is better play, so up to ten more points of waste pass and the flag asks
    # for a reviewed rewrite of the baseline.
    further = _result('badges_6', waste=17.0, story=['fog', 'storm', 'mineral'])
    assert stage_ladder.compare([further], GOLD_BASE) == []
    assert stage_ladder.past_baseline([further], GOLD_BASE) == [
        'gold/badges_6: earned mineral past the baseline, at 17.0% wasted, 10.0% before. '
        'Rewrite its baseline in a reviewed change.']
    assert stage_ladder.compare([_result('badges_6', waste=21.0, story=['fog', 'storm', 'mineral'])], GOLD_BASE) == [
        'gold/badges_6: 21.0% wasted, 10.0% before, more than 10 points up past the baseline to mineral']


def test_a_rung_short_of_its_baseline_goal_fails_and_names_the_goal_it_stopped_before():
    assert stage_ladder.compare([_result('badges_6', waste=5.0, story=['fog'])], GOLD_BASE) == [
        'gold/badges_6: stopped before storm, which the baseline reached']
    assert stage_ladder.past_baseline([_result('badges_6', waste=5.0, story=['fog'])], GOLD_BASE) == []


def test_a_rung_level_with_its_baseline_keeps_the_two_point_rule_and_a_stall_fails_past_it():
    assert stage_ladder.compare([_result('badges_6', waste=12.5, story=['storm', 'fog'])], GOLD_BASE) == [
        'gold/badges_6: 12.5% wasted, 10.0% before']
    stalled = _result('badges_6', waste=11.0, stall='quiet', story=['fog', 'storm', 'mineral'])
    assert stage_ladder.compare([stalled], GOLD_BASE) == ['gold/badges_6: a new stall, quiet']
    assert stage_ladder.past_baseline([stalled], GOLD_BASE) == []
    # A baseline taken before the gate counted milestones ranks every run level with it.
    old = {'gold/badges_6': {'stall': None, 'errors': 0, 'waste': 10.0}}
    assert stage_ladder.compare([_result('badges_6', waste=17.0, story=['fog', 'storm', 'mineral'])], old) == [
        'gold/badges_6: 17.0% wasted, 10.0% before']


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
            summary = dict(_result(rung, waste, ladder=ladder.name), frames=stage_ladder.GATE_FRAMES)
            Path(out, 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stage_ladder.subprocess, 'run', fake)
    monkeypatch.setattr(stage_ladder, 'GATE_BASELINE', root / 'gate-baseline.json')
    # The paired stage has its own test. With no room for it, a rung up on waste alone fails on the screen.
    monkeypatch.setattr(stage_ladder, 'GATE_PAIRED_RUNGS', 0)
    monkeypatch.delenv(stage_ladder.GATE_HELD, raising=False)
    monkeypatch.setenv('POKESIM_GEN1_VARIANT', 'yellow')
    args = ['gate', str(tmp_path / 'roms'), str(root), '--out', str(tmp_path / 'out')]
    assert main(args) == 0
    command, env = calls.pop()
    assert command[:3] == ['sh', str(stage_ladder.ROOT / 'tools' / 'load_gate.sh'), 'heavy'] and command[-len(args):] == args
    assert env[stage_ladder.GATE_HELD] == '1'
    monkeypatch.setenv(stage_ladder.GATE_HELD, '1')
    assert main(args + ['--write-baseline']) == 0
    # Three rungs on three seeds each.
    assert len(calls) == 9 and all(command[:3] == ['nice', '-n', '10'] for command, _ in calls)
    assert sorted(command[command.index('--seed') + 1] for command, _ in calls) == ['7'] * 3 + ['8'] * 3 + ['9'] * 3
    assert all('POKESIM_GEN1_VARIANT' not in env for _, env in calls)
    stored = json.loads((root / 'gate-baseline.json').read_text(encoding='utf-8'))
    assert stored['frames'] == stage_ladder.GATE_FRAMES and stored['seeds'] == [7, 8, 9] and set(stored['rungs']) == \
        {'red/new_game', 'red/badges_2', 'red-randomized/badges_4'}
    assert stored['rungs']['red/new_game'] == {'stall': None, 'stalls': 0, 'errors': 0, 'waste': 10.0,
                                               'restock': 5.0, 'milestones': 0, 'story': []}
    assert main(args) == 0
    stored['rungs']['red-randomized/badges_4']['waste'] = 20.0
    (root / 'gate-baseline.json').write_text(json.dumps(stored), encoding='utf-8')
    capsys.readouterr()
    assert main(args) == 1
    assert 'red-randomized/badges_4: 30.0% wasted, 20.0% before' in capsys.readouterr().out
    with pytest.raises(SystemExit, match='108000'):
        main(args + ['--frames', '36000'])
    with pytest.raises(SystemExit, match='taken on seeds 7, 8, 9, not 7'):
        main(args + ['--seeds', '7'])
    # A baseline from before the gate played several seeds stands for seed 7 alone.
    del stored['seeds']
    (root / 'gate-baseline.json').write_text(json.dumps(stored), encoding='utf-8')
    with pytest.raises(SystemExit, match='taken on seeds 7, not 7, 8, 9'):
        main(args)


def test_the_gate_fails_and_names_a_baseline_rung_whose_save_is_missing(tmp_path, monkeypatch, capsys):
    # A lost save must not pass the gate by playing fewer rungs, and a whole lost ladder counts too.
    root = tmp_path / 'ladders'
    _ladder(root, 'red', 1, '', ['badges_2'])
    rung = {'stall': None, 'stalls': 0, 'errors': 0, 'waste': 10.0, 'restock': 5.0, 'milestones': 0, 'story': []}
    (root / 'gate-baseline.json').write_text(json.dumps({
        'frames': stage_ladder.GATE_FRAMES, 'seeds': [7, 8, 9],
        'rungs': {'red/badges_2': rung, 'red/badges_4': rung, 'blue/badges_2': rung}}), encoding='utf-8')

    def fake(command, env, **_):
        at = command.index('gate-rung')
        summary = dict(_result(command[at + 2], ladder='red'), frames=stage_ladder.GATE_FRAMES)
        Path(command[at + 3], 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stage_ladder.subprocess, 'run', fake)
    monkeypatch.setattr(stage_ladder, 'GATE_BASELINE', root / 'gate-baseline.json')
    monkeypatch.setenv(stage_ladder.GATE_HELD, '1')
    args = ['gate', str(tmp_path / 'roms'), str(root), '--out', str(tmp_path / 'out')]
    assert main(args) == 1
    out = capsys.readouterr().out
    assert f'red/badges_4: in the baseline, but {root / "red" / "badges_4" / "start.state"} is missing' in out
    assert f'blue/badges_2: in the baseline, but {root / "blue" / "badges_2" / "start.state"} is missing' in out
    # A ladder left out with --ladder is not missing.
    (root / 'red' / 'badges_4').mkdir()
    (root / 'red' / 'badges_4' / 'start.state').write_bytes(b'state')
    assert main(args + ['--ladder', 'red']) == 0


def test_the_paired_judgment_passes_a_mean_rise_of_at_most_one_point():
    # The battle goal fix on blue/badges_4 moved the mean by +0.56 on 23 pairs, the first Mt. Moon
    # version red/badges_6 by +1.65. These pairs give the same means.
    harmless = [(seed, 20.0, 20.56) for seed in range(7, 30)]
    verdict = stage_ladder.paired(harmless)
    assert verdict['passed'] and verdict['mean'] == 0.56 and verdict['error'] == 0.0 and len(verdict['pairs']) == 23
    costly = [(seed, 10.0, 13.45 if seed < 18 else 10.0) for seed in range(7, 30)]
    verdict = stage_ladder.paired(costly)
    assert not verdict['passed'] and verdict['mean'] == 1.65 and verdict['median'] == 0.0
    assert verdict['error'] == 0.37
    # A mean of exactly a point passes, as it prints.
    assert stage_ladder.paired([(7, 10.0, 10.3), (8, 10.0, 11.7)])['passed']
    assert not stage_ladder.paired([(7, 10.0, 10.3), (8, 10.0, 11.72)])['passed']


def test_only_a_rung_up_on_waste_alone_goes_to_the_paired_stage():
    baseline = {'gold/badges_2': {'stall': None, 'errors': 0, 'waste': 10.0, 'story': ['fog']},
                'gold/badges_4': {'stall': None, 'errors': 0, 'waste': 10.0, 'story': ['fog']},
                'gold/badges_6': {'stall': None, 'errors': 0, 'waste': 10.0, 'story': ['fog']},
                'gold/badges_8': {'stall': None, 'errors': 0, 'waste': 10.0, 'story': ['fog']}}
    results = [_result('badges_2', waste=12.5, story=['fog']), _result('badges_4', waste=12.5, errors=1, story=['fog']),
               _result('badges_6', waste=11.0, story=['fog']), _result('badges_8', waste=25.0, story=['fog', 'storm'])]
    # More errors fail as before, and a rung past its baseline keeps its own ten point limit.
    assert [result['rung'] for result in stage_ladder.waste_only(results, baseline)] == ['badges_2']


def test_a_restock_rise_shows_on_the_gate_line_and_fails_nothing():
    # Restock moves more from seed to seed than the paired limit, so the reviewer sees it and nothing judges it.
    base = {'gold/badges_6': {'stall': None, 'errors': 0, 'waste': 10.0, 'restock': 5.0, 'story': ['fog']}}
    risen = _result('badges_6', restock=45.0, story=['fog'])
    assert stage_ladder.compare([risen], base) == [] and stage_ladder.waste_only([risen], base) == []
    assert stage_ladder._gate_line(risen, base['gold/badges_6']).startswith(
        'gold/badges_6                   10.0% wasted ( +0.0), 45.0% restock (+40.0), 0 errors')
    # A baseline from before the restock share shows the share alone.
    older = {'stall': None, 'errors': 0, 'waste': 10.0, 'story': ['fog']}
    assert ', 45.0% restock, 0 errors' in stage_ladder._gate_line(risen, older)


def test_the_shares_of_a_run_count_restock_heal_and_pc_goals_by_their_key():
    frames = {'restock Buy 5 Poke Balls': 300, 'buy_balls Restock adventure supplies': 100,
              'sell_supplies Sell spare items': 50, 'heal Pokemon Center': 200, 'party_box Box a spare': 40,
              'collection_hatch_pc Take an egg': 10, 'collection_hunt quality PIKACHU': 300}
    result = {'frames': 1000, 'wasted': {'collection_hunt quality PIKACHU': 125}, 'frames_by_goal': frames}
    assert shares(result) == {'waste': 12.5, 'restock': 45.0, 'heal': 20.0, 'pc': 5.0}
    assert shares({'frames': 0, 'wasted': {}, 'frames_by_goal': {}}) == {'waste': 0.0, 'restock': 0.0, 'heal': 0.0,
                                                                          'pc': 0.0}


def _paired_gate(tmp_path, monkeypatch, base_waste, base='b' * 40, head_only=None):
    """A gate over red/badges_2 and red/badges_4 that plays no game. The head wastes 10% on badges_2 and
    13% on badges_4 on every seed, the merge base ``base`` ``base_waste`` on badges_4, and both baselines
    are 10%. ``head_only`` adds its stall or errors to the head's run on seed 12 alone."""
    root = tmp_path / 'ladders'
    _ladder(root, 'red', 1, '', ['badges_2', 'badges_4'])
    rung = {'stall': None, 'stalls': 0, 'errors': 0, 'waste': 10.0, 'restock': 5.0, 'milestones': 0, 'story': []}
    (root / 'gate-baseline.json').write_text(json.dumps({
        'frames': stage_ladder.GATE_FRAMES, 'seeds': [7, 8, 9],
        'rungs': {'red/badges_2': rung, 'red/badges_4': rung}}), encoding='utf-8')
    calls = []

    def fake(command, env, **_):
        at = command.index('gate-rung')
        rung, out, seed = command[at + 2], Path(command[at + 3]), int(command[command.index('--seed') + 1])
        tree = 'base' if command[3] == 'base-python' else 'head'
        calls.append((tree, rung, seed))
        waste = 10.0 if rung == 'badges_2' else base_waste if tree == 'base' else 13.0
        worse = (head_only or {}) if tree == 'head' and seed == 12 else {}
        summary = dict(_result(rung, waste, ladder='red', story=[], **worse), frames=stage_ladder.GATE_FRAMES)
        (out / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        frames = {'collection_hunt partner PIKACHU': 100, 'collection_hunt quality PIKACHU': 20,
                  'collection_restock': 50 if tree == 'base' else 80}
        (out / 'run.json').write_text(json.dumps({'frames_by_goal': frames}), encoding='utf-8')
        return SimpleNamespace(returncode=0)

    @contextlib.contextmanager
    def merge_base(commit):
        assert commit == base
        yield 'base-python', 'base-script'

    monkeypatch.setattr(stage_ladder.subprocess, 'run', fake)
    monkeypatch.setattr(stage_ladder, '_merge_base', lambda: base)
    monkeypatch.setattr(stage_ladder, 'merge_base', merge_base)
    monkeypatch.setattr(stage_ladder, 'GATE_BASELINE', root / 'gate-baseline.json')
    monkeypatch.setenv(stage_ladder.GATE_HELD, '1')
    out = tmp_path / 'out'
    code = main(['gate', str(tmp_path / 'roms'), str(root), '--out', str(out)])
    return code, calls, json.loads((out / 'gate-report.json').read_text(encoding='utf-8'))


def test_a_rung_up_on_waste_alone_passes_on_paired_seeds_when_the_merge_base_wastes_nearly_as_much(
        tmp_path, monkeypatch, capsys):
    code, calls, report = _paired_gate(tmp_path, monkeypatch, base_waste=12.5)
    assert code == 0 and report['problems'] == []
    # The merge base plays all 23 seeds, the head the 20 its screen did not.
    paired = [(tree, seed) for tree, rung, seed in calls if seed > 9 or tree == 'base']
    assert sorted(seed for tree, seed in paired if tree == 'base') == list(range(7, 30))
    assert sorted(seed for tree, seed in paired if tree == 'head') == list(range(10, 30))
    assert all(rung == 'badges_4' for tree, rung, seed in calls if tree == 'base' or seed > 9)
    verdict = report['paired']['red/badges_4']
    assert verdict['passed'] and verdict['mean'] == 0.5 and verdict['base'] == 'b' * 40 and len(verdict['pairs']) == 23
    assert set(report['paired']) == {'red/badges_4'}
    out = capsys.readouterr().out
    assert ('red/badges_4: +0.50 points wasted on the mean of 23 paired seeds against the merge base bbbbbbbb, '
            'standard error 0.00, median +0.50, within the 1.0 point limit') in out
    assert 'frames under each goal' not in out


@pytest.mark.parametrize('head_only, problem', [
    ({'stall': 'quiet'}, 'red/badges_4: a new stall, quiet, 1 of 23 seeds, 0 before'),
    ({'errors': 1}, 'red/badges_4: 0.04 errors, 0 before')])
def test_a_stall_or_error_the_head_alone_has_on_the_paired_seeds_fails_the_gate(tmp_path, monkeypatch, head_only,
                                                                                 problem):
    # The merge base wastes nearly as much, so the waste passes, and seed 12 on the head alone goes worse.
    code, _, report = _paired_gate(tmp_path, monkeypatch, base_waste=12.5, head_only=head_only)
    assert report['paired']['red/badges_4']['mean'] == 0.5
    assert code == 1 and report['problems'] == [f'{problem} on the merge base bbbbbbbb']


def test_a_paired_failure_prints_the_pairs_and_the_frames_under_each_goal(tmp_path, monkeypatch, capsys):
    code, _, report = _paired_gate(tmp_path, monkeypatch, base_waste=11.5)
    line = ('red/badges_4: +1.50 points wasted on the mean of 23 paired seeds against the merge base bbbbbbbb, '
            'standard error 0.00, median +1.50, over the 1.0 point limit')
    assert code == 1 and report['problems'] == [line]
    assert report['paired']['red/badges_4']['goals'] == {
        'base': {'collection_hunt': 2760, 'collection_restock': 1150},
        'head': {'collection_hunt': 2760, 'collection_restock': 1840}}
    out = capsys.readouterr().out
    assert '     7  11.50  13.00       +1.50' in out and '    29  11.50  13.00       +1.50' in out
    # The goal the head spent most more on comes first.
    goals = out[out.index('frames under each goal over the 23 seeds'):]
    assert goals.index('collection_restock') < goals.index('collection_hunt')
    assert '  collection_restock                1150      1840       +690' in goals


def test_on_main_a_rung_up_on_waste_alone_fails_on_the_screen(tmp_path, monkeypatch, capsys):
    # The merge base of main with origin/main is main itself, and a tree paired with itself always passes.
    code, calls, report = _paired_gate(tmp_path, monkeypatch, base_waste=13.0, base=None)
    assert code == 1 and report['problems'] == ['red/badges_4: 13.0% wasted, 10.0% before'] and report['paired'] == {}
    assert len(calls) == 6 and 'no merge base with origin/main apart from itself' in capsys.readouterr().out


def _run(seed, waste, story=(), stall=None, errors=0):
    return dict(_result('badges_6', waste=waste, errors=errors, stall=stall, story=story), seed=seed, frames=108000,
                pipeline={'decisions': 4, 'agreed': 3, 'frames': 100, 'frames_agreed': 90})


def test_a_rung_on_three_seeds_keeps_the_mean_and_counts_its_stalls():
    result = stage_ladder.mean_result([_run(7, 10.0, ['fog', 'storm']), _run(8, 13.0, ['storm'], stall='quiet'),
                                       _run(9, 11.0, ['fog', 'storm', 'mineral'], errors=1)])
    assert {key: result[key] for key in ('seeds', 'frames', 'errors', 'stalls', 'waste', 'milestones', 'story')} == {
        'seeds': [7, 8, 9], 'frames': 324000, 'errors': 0.33, 'stalls': 1, 'waste': 11.33, 'milestones': 2,
        'story': ['fog', 'storm', 'mineral']}
    assert result['stall']['reason'] == 'quiet' and [run['seed'] for run in result['runs']] == [7, 8, 9]
    assert result['pipeline'] == {'decisions': 12, 'agreed': 9, 'frames': 300, 'frames_agreed': 270}
    failed = stage_ladder.mean_result([_run(7, 10.0), {'ladder': 'gold', 'rung': 'badges_6', 'seed': 8,
                                                       'failed': 'exit 1'}, _run(9, 10.0)])
    assert failed == {'ladder': 'gold', 'rung': 'badges_6', 'seeds': [7, 8, 9], 'failed': 'seed 8: exit 1'}


def test_a_rung_on_three_seeds_fails_on_more_stalls_fewer_milestones_or_a_higher_mean_waste():
    baseline = {'gold/badges_6': {'stall': 'quiet', 'stalls': 1, 'errors': 0.33, 'waste': 10.0, 'milestones': 2.67,
                                  'story': ['fog', 'storm', 'mineral']}}
    level = [_run(7, 9.0, ['fog', 'storm', 'mineral'], stall='quiet'), _run(8, 12.0, ['fog', 'storm', 'mineral']),
             _run(9, 14.0, ['fog', 'storm'], errors=1)]
    assert stage_ladder.compare([stage_ladder.mean_result(level)], baseline) == []
    worse = [_run(7, 9.0, ['fog', 'storm', 'mineral'], stall='quiet'), _run(8, 12.0, ['fog', 'storm'], stall='quiet'),
             _run(9, 16.0, ['fog', 'storm'], errors=1)]
    assert stage_ladder.compare([stage_ladder.mean_result(worse)], baseline) == [
        'gold/badges_6: a new stall, quiet, 2 of 3 seeds, 1 before',
        'gold/badges_6: 2.33 story milestones a seed, 2.67 before']
    wasteful = [_run(seed, 12.5, ['fog', 'storm', 'mineral']) for seed in (7, 8)] + [_run(9, 12.5, ['fog', 'storm'])]
    assert stage_ladder.compare([stage_ladder.mean_result(wasteful)], baseline) == [
        'gold/badges_6: 12.5% wasted, 10.0% before']
    further = [_run(seed, 15.0, ['fog', 'storm', 'mineral']) for seed in (7, 8)] + [_run(9, 15.0, ['fog', 'storm', 'rising'])]
    result = stage_ladder.mean_result(further)
    assert stage_ladder.compare([result], baseline) == []
    assert stage_ladder.past_baseline([result], baseline) == [
        "gold/badges_6: 3 story milestones a seed past the baseline's 2.67, newly earned rising, at 15.0% wasted, "
        '10.0% before. Rewrite its baseline in a reviewed change.']


def test_the_tracked_baseline_is_the_default_and_names_every_rung_once():
    # The baseline moves only in a pull request, so it lives in the checkout beside the gate.
    assert stage_ladder.GATE_BASELINE == stage_ladder.ROOT / 'tools' / 'ladder' / 'gate-baseline.json'
    stored = json.loads(stage_ladder.GATE_BASELINE.read_text(encoding='utf-8'))
    assert stored['frames'] == stage_ladder.GATE_FRAMES and stored['commit'] and stored['taken']
    assert stored['seeds'] == list(stage_ladder.GATE_SEEDS)
    rungs = {'1': stage_ladder.GEN1_RUNGS, '2': stage_ladder.GEN2_RUNGS}
    for name, rung in stored['rungs'].items():
        ladder, stage = name.split('/')
        allowed = stage_ladder.RANDOMIZED_RUNGS if ladder.endswith('-randomized') else \
            rungs['2' if ladder.split('-')[0] in ('gold', 'silver', 'crystal') else '1']
        assert stage in allowed, name
        assert set(rung) == {'stall', 'stalls', 'errors', 'waste', 'restock', 'milestones', 'story'}, name
        assert 0 <= rung['waste'] <= 100 and 0 <= rung['stalls'] <= len(stored['seeds']), name
        assert all(isinstance(key, str) for key in rung.get('story', [])), name


@pytest.mark.skipif(shutil.which('flock') is None, reason='needs flock')
def test_a_load_gate_inside_a_heavy_run_runs_at_once(tmp_path, monkeypatch):
    # A gate run under the heavy lock once waited 14 hours on the lock its own parent held.
    monkeypatch.setenv('POKESIM_LOAD_GATE', str(tmp_path))
    monkeypatch.setenv('POKESIM_LOAD_GATE_SLICE', '')
    monkeypatch.delenv('POKESIM_LOAD_GATE_HEAVY', raising=False)
    gate = str(stage_ladder.ROOT / 'tools' / 'load_gate.sh')
    nested = ['sh', gate, 'heavy', 'sh', gate, 'heavy', 'sh', gate, 'pytest', 'echo', 'ran']
    done = subprocess.run(nested, capture_output=True, text=True, timeout=30, check=True)
    assert done.stdout == 'ran\n'


@pytest.mark.skipif(shutil.which('flock') is None, reason='needs flock')
@pytest.mark.parametrize('mode', ['pytest', 'heavy'])
def test_a_load_gate_runs_its_command_at_nice_10_or_lower_priority(tmp_path, monkeypatch, mode):
    # The local runs rule asked agents to add nice -n 10 by hand, and a full suite once ran at nice 0.
    monkeypatch.setenv('POKESIM_LOAD_GATE', str(tmp_path))
    monkeypatch.setenv('POKESIM_LOAD_GATE_SLICE', '')
    monkeypatch.delenv('POKESIM_LOAD_GATE_HEAVY', raising=False)
    gate = str(stage_ladder.ROOT / 'tools' / 'load_gate.sh')
    probe = [gate, mode, 'sh', '-c', 'ps -o nice= -p $$']
    own = os.nice(0)
    for prefix, expected in (([], max(own, 10)), (['nice', '-n', '12'], min(own + 12, 19))):
        done = subprocess.run(prefix + ['sh', *probe], capture_output=True, text=True, timeout=30, check=True)
        assert int(done.stdout) == expected


def fake_systemd(tmp_path, fragment):
    """Put a systemctl that reports the slice's unit file, or fails like a missing user manager when
    `fragment` is None, and a systemd-run that logs and runs its command on PATH."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'systemd-run.log'
    answer = 'exit 1' if fragment is None else f"echo '{fragment}'"
    (bin_dir / 'systemctl').write_text(f'#!/bin/sh\n{answer}\n', encoding='utf-8')
    (bin_dir / 'systemd-run').write_text(
        '#!/bin/sh\necho "$@" >> "$FAKE_SYSTEMD_RUN_LOG"\n'
        'while [ $# -gt 0 ]; do case $1 in --*) shift ;; *) break ;; esac; done\nexec "$@"\n',
        encoding='utf-8')
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    return bin_dir, log


@pytest.mark.skipif(shutil.which('flock') is None, reason='needs flock')
@pytest.mark.parametrize('mode', ['pytest', 'heavy'])
def test_a_load_gate_runs_its_command_in_the_tests_slice_once(tmp_path, monkeypatch, mode):
    # The owner caps all local PokeSim work at 12 cores, so test runs go in the slice the sims share.
    bin_dir, log = fake_systemd(tmp_path, '/units/pokesim-tests.slice')
    monkeypatch.setenv('PATH', f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv('FAKE_SYSTEMD_RUN_LOG', str(log))
    monkeypatch.setenv('POKESIM_LOAD_GATE', str(tmp_path))
    monkeypatch.delenv('POKESIM_LOAD_GATE_SLICE', raising=False)
    monkeypatch.delenv('POKESIM_LOAD_GATE_HEAVY', raising=False)
    gate = str(stage_ladder.ROOT / 'tools' / 'load_gate.sh')
    done = subprocess.run(['sh', gate, mode, 'sh', gate, 'pytest', 'echo', 'ran'],
                          capture_output=True, text=True, timeout=30, check=True)
    assert done.stdout == 'ran\n'
    scopes = log.read_text(encoding='utf-8').splitlines()
    # A gate inside a heavy run runs at once, inside its parent's scope.
    assert len(scopes) == (1 if mode == 'heavy' else 2)
    assert scopes[0].startswith('--user --scope --quiet --collect --slice=pokesim-tests.slice sh ')


@pytest.mark.skipif(shutil.which('flock') is None, reason='needs flock')
@pytest.mark.parametrize('fragment', ['', None])
def test_a_load_gate_without_the_slices_runs_uncapped(tmp_path, monkeypatch, fragment):
    # systemd calls a slice with no unit file loaded too, so the gate looks for the file. A machine
    # with a user manager but no slices hears about it, and one with no user manager (CI) does not.
    bin_dir, log = fake_systemd(tmp_path, fragment)
    monkeypatch.setenv('PATH', f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv('FAKE_SYSTEMD_RUN_LOG', str(log))
    monkeypatch.setenv('POKESIM_LOAD_GATE', str(tmp_path))
    monkeypatch.delenv('POKESIM_LOAD_GATE_SLICE', raising=False)
    monkeypatch.delenv('POKESIM_LOAD_GATE_HEAVY', raising=False)
    gate = str(stage_ladder.ROOT / 'tools' / 'load_gate.sh')
    done = subprocess.run(['sh', gate, 'pytest', 'echo', 'ran'], capture_output=True, text=True, timeout=30, check=True)
    assert done.stdout == 'ran\n'
    warned = 'pokesim-tests.slice is not installed' in done.stderr and 'local_sims.sh install' in done.stderr
    assert warned is (fragment == '')
    assert not log.exists()
