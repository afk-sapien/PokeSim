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
def mon(name, level, moves=(33,), trainer_id=None):
    return SimpleNamespace(species=sid(name), level=level, hp=100, max_hp=100, status=0, trainer_id=trainer_id,
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


def test_traded_pikachu_can_leave_the_party():
    # The live Yellow party that failed every incoming trade: four sole HM holders, the starter
    # and a Pikachu traded in from Red. Only the traded Pikachu is free to go to the PC.
    out = run_yellow(PARTY, '''
        from pokesim.policies.team import development_candidate, reserve_to_deposit, stays_in_party
        from pokesim.policies.league_rotation import deposit_target
        from dataclasses import asdict
        party = [mon('DUGTRIO', 100, (15,), 35926), mon('FEAROW', 100, (19,), 7726),
                 mon('PIKACHU', 100, (84,), 35926), mon('BLASTOISE', 52, (57,), 32086),
                 mon('CLEFAIRY', 100, (70,), 39503), mon('PIKACHU', 20, (84,), 20897)]
        s = SimpleNamespace(party=party, player_id=35926)
        assert stays_in_party(s, party[2]) and not stays_in_party(s, party[5])
        assert stays_in_party(s, vars(party[2])) and not stays_in_party(s, vars(party[5]))
        assert reserve_to_deposit(s) == 5
        # Without a player ID, as in an older snapshot, every Pikachu stays.
        assert reserve_to_deposit(SimpleNamespace(party=party)) is None
        assert stays_in_party(SimpleNamespace(party=party), party[5])
        print('ok')
    ''')
    assert out.strip() == 'ok'


def test_yellow_preparation_keeps_pikachu_out_of_storage():
    source = (ROOT / 'pokesim/runtime/preparation.py').read_text()
    assert 'not stays_in_party(snap, mon)' in source


OBJECTS_AND_EVENTS = '''
import json
import re
from pathlib import Path
from pokesim.strategy_data import EVENTS, MAPS, WORLD
labels = {f'{room} {i}': WORLD[MAPS[room]]['objects'][i][4] for room, i in (
    ('GAME_CORNER', 10), ('FIGHTING_DOJO', 5), ('FIGHTING_DOJO', 6),
    ('CELADON_MANSION_ROOF_HOUSE', 1), ('MUSEUM_1F', 4))}
used = set()
import pokesim
for path in Path(pokesim.__file__).parent.rglob('*.py'):
    if not path.name.startswith('jev'):
        used |= set(re.findall(r"['\\"](EVENT_[A-Z0-9_]+)['\\"]", path.read_text()))
print(json.dumps({'labels': labels, 'known': sorted(used & set(EVENTS)),
                  'numbers': [EVENTS[n] for n in ('EVENT_GOT_DOME_FOSSIL', 'EVENT_GOT_HELIX_FOSSIL',
                                                  'EVENT_GOT_POKEDEX', 'EVENT_BEAT_CHAMPION_RIVAL')]}))
'''
FIXED_OBJECTS = {'GAME_CORNER 10': 'ROCKET', 'FIGHTING_DOJO 5': 'HITMONLEE', 'FIGHTING_DOJO 6': 'HITMONCHAN',
                 'CELADON_MANSION_ROOF_HOUSE 1': 'EEVEE', 'MUSEUM_1F 4': 'OLD_AMBER'}


def test_fixed_object_indices_and_story_events_hold_in_yellow():
    import contextlib
    import io
    import json
    red = io.StringIO()
    with contextlib.redirect_stdout(red):
        exec(OBJECTS_AND_EVENTS, {})
    known = {}
    for game, out in (('red', red.getvalue()), ('yellow', run_yellow(OBJECTS_AND_EVENTS))):
        data = json.loads(out)
        known[game] = set(data['known'])
        assert all(FIXED_OBJECTS[key] in label for key, label in data['labels'].items()), game
        # Yellow numbers Mt. Moon's events differently, so the Dome Fossil flag moves.
        assert data['numbers'] == ([1406, 1407, 37, 2305] if game == 'red' else [1400, 1407, 37, 2305])
    # Every Gen I story event the code names also exists in Yellow.
    assert len(known['red']) > 40 and known['red'] <= known['yellow']


def test_pokedex_reference_describes_yellow():
    out = run_yellow('''
        from pokesim.web import pokedex
        assert pokedex.VERSIONS == ('yellow',) and pokedex.DEFAULT_VERSION == 'yellow'
        reference = pokedex.reference()
        entries = {row['dex']: row for row in reference['entries']}
        assert reference['version'] == 'yellow' and len(entries) == 151
        # Pikachu is never wild in Yellow, and the Kanto starters become gifts.
        assert entries[25]['locations'] == []
        for dex in (1, 4, 7):
            assert [row['method'] for row in entries[dex]['locations']] == ['gift'], dex
        print('ok')
    ''')
    assert out.strip() == 'ok'
