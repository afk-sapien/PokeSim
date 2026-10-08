"""Yellow starts with Oak's Pikachu, keeps it in the party and never evolves it.

Gen I modules load their tables when imported, so each check runs in a fresh
interpreter that selects Yellow data first.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pokesim import game_data

ROOT = Path(__file__).resolve().parents[1]


def run_yellow(*parts):
    try:
        game_data.bundle_path(variant='yellow')
        game_data.bundle_path(variant='red')
    except RuntimeError:
        pytest.skip('Yellow game data is not prepared')
    env = dict(os.environ, **{game_data.VARIANT_ENV: 'yellow'})
    result = subprocess.run([sys.executable, '-c', ''.join(map(textwrap.dedent, parts))], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


PARTY = '''
from types import SimpleNamespace
from pokesim.strategy_data import SPECIES, MOVES
sid = lambda name: next(k for k, v in SPECIES.items() if v['name'] == name)
def mon(name, level, moves=(33,)):
    return SimpleNamespace(species=sid(name), level=level, hp=100, max_hp=100, status=0,
                           moves=list(moves) + [0] * (4 - len(moves)), pp=[30, 0, 0, 0], nick='', name=name)
'''


def test_oak_gives_pikachu_from_the_last_ball():
    out = run_yellow('''
        from types import SimpleNamespace
        from pokesim.policies import progression
        from pokesim.policies.strategic import StrategicPolicy
        assert progression.YELLOW and progression.GAME_STARTERS == ('pikachu',)
        s = SimpleNamespace(event_flags=b'\\0' * 320, items=[], party=[], map=0, x=10, y=5)
        goal = progression.story_goal(s)
        assert goal.key == 'meet_oak' and goal.targets[0][1:] == (10, 0), goal.targets
        policy = StrategicPolicy(seed=3, starter='random')
        assert policy.starter == 'pikachu'
        print('ok')
    ''')
    assert out.strip() == 'ok'


def test_pikachu_stays_in_party_and_trains_first():
    out = run_yellow(PARTY, '''
        from pokesim.policies.team import STAYS_IN_PARTY, development_candidate, reserve_to_deposit
        assert STAYS_IN_PARTY == {sid('PIKACHU')}
        party = [mon('PIDGEOTTO', 30), mon('PIKACHU', 11, (84,)), mon('RATTATA', 12)]
        s = SimpleNamespace(party=party)
        assert reserve_to_deposit(s) == 2
        s.party = party[:2]
        assert reserve_to_deposit(s) is None
        s.party = party
        assert development_candidate(s, 20) == 1
        print('ok')
    ''')
    assert out.strip() == 'ok'


def test_pikachu_never_evolves_and_gifts_follow_happiness_and_badges():
    out = run_yellow(PARTY, '''
        from pokesim.policies import collection
        from pokesim.game_data import load
        assert collection.REFUSES_EVOLUTION == {25}
        rows = load('collection.json')['versions']['yellow']
        gifts = {r['fragment']: r for v in rows.values() for r in v if r['method'] == 'gift'}
        policy = collection.Collection.__new__(collection.Collection)
        s = SimpleNamespace(items=[], party=[mon('PIKACHU', 20)], event_flags=bytes(320),
                            hidden_objects=bytes(32), toggle_flags=bytes(32), badges=0, pikachu_happiness=90)
        assert not policy.available(s, gifts['MELANIE'])
        assert not policy.available(s, gifts['OFFICER_JENNY'])
        s.pikachu_happiness, s.badges = 147, 4
        assert policy.available(s, gifts['MELANIE'])
        assert policy.available(s, gifts['OFFICER_JENNY'])
        from pokesim import step_events
        assert step_events.TRADES == ((1, 122, 'ROUTE_2_TRADE_HOUSE'),)
        from pokesim.policies.progression import GYMS
        assert {g[0]: g[5] for g in GYMS}[128] == 52
        print('ok')
    ''')
    assert out.strip() == 'ok'


def test_yellow_preparation_keeps_pikachu_out_of_storage():
    source = (ROOT / 'pokesim/runtime/preparation.py').read_text()
    assert 'mon.species not in STAYS_IN_PARTY' in source
