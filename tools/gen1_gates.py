"""Generate the Gen I gate table from a pret/pokered or pret/pokeyellow checkout.

Usage: python tools/gen1_gates.py /path/to/pokered > pokesim/policies/gates.py

A gate is a script that walks the player back until a condition holds: the Cycling Road guards
without a Bicycle, the Saffron guards without a drink, the Route 23 badge guards and the Cinnabar
Gym doors. Each one is read from the script that runs it, so the table is generated and never
written by hand. tests/test_gen1_gates.py regenerates it whenever a checkout is present and fails
when the checked-in table has drifted.
"""
import re
import subprocess
import sys
from pathlib import Path

COORD_CHECK = re.compile(r'ld hl, (\.?\w+)\s*\n\s*call ArePlayerCoordsInArray')
# A guard row may check only the tiles west of a column: cp <row>, a jump past the column test,
# then cp <x> and ret nc.
ROW_LIMIT = re.compile(r'cp (\d+)\s*\n\s*jr nz, \.\w+\s*\n\s*ld a, \[wXCoord\]\s*\n\s*cp (\d+)\s*\n\s*ret nc')


def _read(src, path):
    return (Path(src) / path).read_text(encoding='utf-8')


def _code(text):
    """The source without comments."""
    return '\n'.join(line.split(chr(59))[0].rstrip() for line in text.splitlines())


def _block(text, label):
    """The lines under ``label`` up to the next label."""
    match = re.search(rf'^{re.escape(label)}:+\n(.*?)(?=^\S|\Z)', text, re.M | re.S)
    if not match:
        raise ValueError(f'no {label} block')
    return match[1]


def _coords(text, label):
    return tuple((int(x), int(y)) for x, y in re.findall(r'dbmapcoord\s+(\d+),\s*(\d+)', _block(text, label)))


def _map_name(src, script):
    header = _read(src, f'data/maps/headers/{script.stem}.asm')
    return re.search(r'map_header\s+\w+,\s*(\w+)', header)[1]


def _guarded(src, marker):
    """(map, tiles) for each map script that tests ``marker`` before it checks the player's tile."""
    found = []
    for script in sorted((Path(src) / 'scripts').glob('*.asm')):
        text = _code(script.read_text(encoding='utf-8'))
        default = re.search(r'^\w+DefaultScript:\n(.*?)(?=^\w+Script:|\Z)', text, re.M | re.S)
        if not default or marker not in default[1]:
            continue
        found.append((_map_name(src, script), _coords(text, COORD_CHECK.search(default[1])[1])))
    if not found:
        raise ValueError(f'no script tests {marker}')
    return tuple(found)


def _constants(src, path):
    return re.findall(r'^\s*const\s+(\w+)', _code(_read(src, path)), re.M)


def route_23(src):
    """(row, badge bit, last x the guard checks or None) from north to south."""
    text = _code(_read(src, 'scripts/Route23.asm'))
    rows = [int(row) for row in re.findall(r'db\s+(\d+)', _block(text, 'Route23GuardsYCoords'))]
    checks = [name.removeprefix('EVENT_PASSED_').removesuffix('_CHECK')
              for name in _constants(src, 'constants/event_constants.asm')
              if name.startswith('EVENT_PASSED_') and name.endswith('BADGE_CHECK')]
    bits = [name.removeprefix('BIT_') for name in _constants(src, 'constants/ram_constants.asm')
            if name.startswith('BIT_') and name.endswith('BADGE')]
    # The script counts down from the Earth Badge check, so the first row checks the last badge.
    badges = [1 << bits.index(name) for name in reversed(checks)]
    if len(badges) != len(rows):
        raise ValueError('Route 23 rows and badge checks differ in number')
    limits = {int(row): int(x) - 1 for row, x in ROW_LIMIT.findall(text)}
    return tuple((row, badge, limits.get(row)) for row, badge in zip(rows, badges))


def cinnabar_gym(src):
    """(block x, block y, vertical) for each door, in the order of its EVENT_CINNABAR_GYM_GATE flag."""
    text = _code(_read(src, 'engine/events/hidden_events/cinnabar_gym_quiz.asm'))
    return tuple((int(x), int(y), block == 'VERTICAL_GATE_BLOCK') for x, y, block in re.findall(
        r'gym_gate_coord\s+(\d+),\s*(\d+),\s*(\w+)', _block(text, 'CinnabarGymGateCoords')))


def drinks(src):
    text = _code(_read(src, 'data/items/guard_drink_items.asm'))
    return tuple(re.findall(r'db\s+([A-Z_]+)', _block(text, 'GuardDrinksList')))


def source(src):
    """(repository, commit) of a checkout, or of a GitHub archive named repository-commit."""
    path = Path(src).resolve()
    try:
        commit = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = path.name.rsplit('-', 1)[-1]
    repository = path.name.split('-', 1)[0] if path.name.startswith('poke') else 'pokered'
    return repository, commit


def _rows(name, rows):
    pad = ' ' * (len(name) + 4)
    lines = [f'{name} = ({rows[0]!r},'] + [f'{pad}{row!r},' for row in rows[1:]]
    if len(rows) > 1:
        lines[-1] = lines[-1][:-1] + ')'
    else:
        lines[-1] += ')'
    return lines


def body(src):
    """The table without its header, the same for every source that agrees on the gates."""
    lines = [
        '# (map, tiles) where a guard walks the player back without a Bicycle.',
        *_rows('CYCLING_ROAD', _guarded(src, 'IsBicycleInBagScript')),
        '# (map, tiles) where a guard walks the player back until one of DRINKS is given.',
        *_rows('SAFFRON_GATES', _guarded(src, 'BIT_GAVE_SAFFRON_GUARDS_DRINK')),
        *_rows('DRINKS', drinks(src)),
        '# (row, badge bit, last x the guard checks or None for the whole row), from north to south.',
        *_rows('ROUTE_23_GUARDS', route_23(src)),
        '# (block x, block y, vertical) per door. Door n opens with EVENT_CINNABAR_GYM_GATE<n>_UNLOCKED, from 1.',
        *_rows('CINNABAR_GYM_DOORS', cinnabar_gym(src)),
    ]
    return '\n'.join(lines) + '\n'


def render(src):
    repository, commit = source(src)
    return '\n'.join((
        f'"""Gen I gates, generated by tools/gen1_gates.py from pret/{repository} {commit}.',
        '',
        'Generated, not written by hand. Regenerate with the tool. tests/test_gen1_gates.py checks it.',
        '"""',
        '',
        '',
    )) + body(src)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.write(render(sys.argv[1]))
