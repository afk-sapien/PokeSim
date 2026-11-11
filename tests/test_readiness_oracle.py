"""One definition of a ready team, for both generations (planning/readiness.py)."""
import ast
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.planning import readiness as oracle
from pokesim.planning.losses import Losses

PACKAGE = Path(__file__).resolve().parents[1] / 'pokesim'
ORACLE = 'planning/readiness.py'
THRESHOLDS = {'READY', 'LEAGUE_READY', 'MARGIN', 'CEILING', 'REGROWTH', 'DEPTH_REGROWTH', 'READY_HP', 'READY_PP'}
JUDGES = {'judge', 'loss_bar', 'matched'}
# The rules the oracle replaced, by the names they went by: the Gen II League's level and PP gate, its
# regrowth and ceiling after a loss, the Gen II matchup walk, and the Gen I League's training rule.
GONE = {'league_ready', 'league_unready', 'unready', 'LEAGUE_LEVEL', 'LEAGUE_OPPONENTS', 'LEAGUE_REGROWTH',
        'league_strength', 'league_ceiling', 'matchup_training'}
TACKLE = 33


def modules():
    for path in sorted(PACKAGE.rglob('*.py')):
        yield path.relative_to(PACKAGE).as_posix(), ast.parse(path.read_text(encoding='utf-8'))


def numbers(node):
    """The names an assignment binds to a number."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target in targets:
        pairs = (zip(target.elts, node.value.elts) if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple)
                 else [(target, node.value)])
        for name, value in pairs:
            if (isinstance(name, ast.Name) and isinstance(value, ast.Constant)
                    and isinstance(value.value, (int, float)) and not isinstance(value.value, bool)):
                yield name.id


def names(node):
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.alias):
        return {node.name, node.asname}
    return set()


def test_only_the_oracle_keeps_a_readiness_threshold():
    found = {(path, name) for path, tree in modules() for node in ast.walk(tree)
             if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
             for name in numbers(node) if name in THRESHOLDS}
    assert found == {(ORACLE, name) for name in THRESHOLDS}


def test_only_the_oracle_judges_a_team():
    found = {(path, node.name) for path, tree in modules() for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef) and node.name in JUDGES}
    assert found == {(ORACLE, name) for name in JUDGES}


def test_the_rules_the_oracle_replaced_are_gone():
    left = sorted((path, node.lineno if hasattr(node, 'lineno') else 0, name)
                  for path, tree in modules() for node in ast.walk(tree) for name in names(node) & GONE)
    assert left == []
    # The losses no longer keep a bar of their own, and the old Brock key lives on only as a rename.
    assert not hasattr(Losses, 'bar')
    old = sorted(path for path, tree in modules() for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and node.value == 'train_brock')
    assert old == ['planning/losses.py']


@pytest.fixture(scope='module')
def cartridge():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    data = GameData.load(directory, 'gold')
    # Without the trainer tables each boss keeps the ace in the policy's own table.
    data.boss_parties = {}
    return data


@pytest.fixture
def verdicts(cartridge, monkeypatch):
    """Every verdict the oracle gives, with the boss and the team it judged, as each generation asks."""
    from pokesim.gen2 import training
    from pokesim.policies import progression
    monkeypatch.setattr(training, 'walk_points', lambda policy, snapshot, mid: [(10, 10, 0)])
    seen, real = [], oracle.judge

    def judge(boss, team, losses=None):
        seen.append((boss, team, real(boss, team, losses)))
        return seen[-1][2]
    monkeypatch.setattr(oracle, 'judge', judge)
    monkeypatch.setattr(progression, 'judge', judge)
    return seen


def gold_mon(data, level):
    from pokecore.gen2.ram import calculated_stats
    stats = calculated_stats(data.species[155]['stats'], level, (8, 8, 8, 8, 8), (0,) * 5)
    return SimpleNamespace(species=155, level=level, egg=False, max_hp=stats[0], hp=stats[0], stats=stats,
                           status=0, moves=(TACKLE, 0, 0, 0))


@pytest.mark.parametrize('league', [False, True])
@pytest.mark.parametrize('best', [0, 74, 75])
@pytest.mark.parametrize('over', [-1, 0, 9, 10])
@pytest.mark.parametrize('lost', [None, 3])
def test_both_generations_get_one_verdict_from_the_same_facts(cartridge, verdicts, monkeypatch, league, best, over, lost):
    # Misty in Red and Bugsy in Gold, or each League from its lobby: the same matchup score, the same
    # best fighter level over the ace, and the same loss there give the same verdict.
    from pokesim.gen2 import readiness as gen2_readiness
    from pokesim.gen2.policy import Goal, Policy
    from pokesim.policies import progression
    from pokesim.strategy_data import MAPS
    from test_events import snap
    from test_strategy import mon
    monkeypatch.setattr(progression, 'readiness', lambda s, bit=None: {'score': best})
    monkeypatch.setattr(gen2_readiness, 'readiness', lambda policy, party, key: best)
    gold = Policy(cartridge)
    if league:
        red_ace, red_goal, red_map, badges = progression.LEAGUE_ACE, 'league_lorelei', 'INDIGO_PLATEAU_LOBBY', 255
        gold_goal, gold_map = Goal('league_will', 'Challenge Will', 'WILLS_ROOM', 5, 5), 'INDIGO_PLATEAU_POKECENTER_1F'
    else:
        red_ace = next(gym[5] for gym in progression.GYMS if gym[1] == 'cascade')
        red_goal, red_map, badges = 'cascade', 'CERULEAN_CITY', 1
        gold_goal, gold_map = Goal('hive', 'Challenge Bugsy', 'AZALEA_GYM', 5, 8, 'up'), 'AZALEA_TOWN'
    gold_ace, red_losses = gold.boss_ace(gold_goal.key), Losses()
    if lost is not None:
        red_losses.note(progression.boss_key(red_goal), red_ace + lost)
        gold.losses.note(gold.boss_key(gold_goal.key), gold_ace + lost)
    red = progression.boss_training(snap(map=MAPS[red_map], badges=badges, party=(mon(level=red_ace + over),)),
                                    SimpleNamespace(key=red_goal), red_losses)
    party = (gold_mon(cartridge, gold_ace + over),)
    at = SimpleNamespace(map=cartridge.map_ids[gold_map], x=5, y=5, frame=1000, badges=badges, party=party,
                         event=lambda name: True)
    walk = gold.boss_training(at, gold_goal)
    (red_boss, red_team, red_verdict), (gold_boss, gold_team, gold_verdict) = verdicts
    # Each generation reads the same facts: only the boss's name, its ace and the levels set from it differ.
    assert replace(red_boss, key='', ace=0) == replace(gold_boss, key='', ace=0)
    assert replace(red_team, level=red_team.level - red_ace) == replace(gold_team, level=gold_team.level - gold_ace)
    assert (red_verdict is None) == (gold_verdict is None) == (red is None) == (walk is None)
    if red_verdict:
        assert red_verdict.reason == gold_verdict.reason
        assert red_verdict.target - red_ace == gold_verdict.target - gold_ace
