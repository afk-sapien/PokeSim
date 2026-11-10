"""Generate the Gen I map facts from a pret/pokered or pret/pokeyellow checkout.

Usage: python tools/gen1_map_facts.py /path/to/pokered > pokesim/mapfacts/gen1.py

A block swap is a map script that redraws one block of its map when the map loads, picking the
block by an event flag: the Elite Four doors, the Victory Road switch gates and the Rocket Hideout
B1F door. The tool follows each script's instructions from every routine, so a swap is read from
the code that makes it and never copied by hand. tests/test_gen1_map_facts.py regenerates the
facts whenever a checkout is present and fails when the checked-in file has drifted.

The same walk lists every flag-gated swap in the scripts. Each one is a fact or sits on a map in
ALLOWED with the reason the facts leave it out, which is the coverage check of the map audit.
"""
import itertools
import re
import subprocess
import sys
from pathlib import Path

# The maps whose block swaps the facts leave out, with the reason.
ALLOWED = {
    'GAME_CORNER': 'Reading the poster opens the hideout stairs. Progression reads the poster as a story step.',
    'LANCES_ROOM': 'The entrance shuts behind the player. Nothing routes back out of the room.',
    'ROCKET_HIDEOUT_B4F': 'The door to Giovanni opens once both guards are beaten. Two flags decide it, and '
                          'navigation does not read it yet.',
    'VERMILION_GYM': 'The trash can locks open the door. The gym policy solves them before it walks in.',
    **{f'SILPH_CO_{floor}F': 'Card key doors. locked_doors reads them from the same script.'
       for floor in range(2, 12)},
    **{f'POKEMON_MANSION_{floor}': 'Switch gates. switch_blocks in data_tools/strategy.py lists them by hand.'
       for floor in ('1F', '2F', '3F', 'B1F')},
}
# Red only. The Yellow script has no door there.
RED_ONLY = {'ROCKET_HIDEOUT_B4F'}
# Ops that leave the a register and the flags as they were.
QUIET = {'ld', 'lb', 'res', 'set', 'nop', 'push', 'pop'}
LIMIT = 200_000
DEPTH = 8


def _read(src, path):
    return (Path(src) / path).read_text(encoding='utf-8')


def _code(text):
    """The source without comments."""
    return '\n'.join(line.split(chr(59))[0].rstrip() for line in text.splitlines())


def _map_name(src, script):
    header = _read(src, f'data/maps/headers/{script.stem}.asm')
    return re.search(r'map_header\s+\w+,\s*(\w+)', header)[1]


def _value(text):
    if re.fullmatch(r'\$[\da-fA-F]+', text):
        return int(text[1:], 16)
    return int(text) if text.isdigit() else None


def _link(src):
    """(instructions, labels, routines) of every map script as one program.

    A local label is named under the routine it sits in. routines maps each script to its global
    labels. A script that calls a routine in another script follows it there.
    """
    code, labels, routines = [], {}, {}
    for script in sorted((Path(src) / 'scripts').glob('*.asm')):
        scope, routines[script] = '', []
        for line in _code(script.read_text(encoding='utf-8')).splitlines():
            if not line.strip():
                continue
            if not line[0].isspace():
                name = line.strip().rstrip(':')
                if name.startswith('.'):
                    name = scope + name
                else:
                    scope = name
                    routines[script].append(name)
                labels[name] = len(code)
                continue
            op, _, rest = line.strip().partition(' ')
            code.append((op, [part.strip() for part in rest.split(',')] if rest.strip() else [], scope))
        code.append(('end', [], scope))
    return code, labels, routines


def _walk(code, labels, starts):
    """(block x, block y, block, conditions) for each block swap a path from the starts makes.

    A condition is (flag, set). Branches that hang on anything other than an event flag are
    followed both ways with no condition.
    """
    found, seen = set(), set()
    todo = [(labels[name], None, None, None, None, None, (), (), frozenset()) for name in starts]
    while todo:
        state = todo.pop()
        if state in seen:
            continue
        if len(seen) > LIMIT:
            raise ValueError('a script has too many paths to follow')
        seen.add(state)
        pc, a, b, c, block, zf, stack, calls, conds = state
        op, args, scope = code[pc]
        if op == 'end':
            continue

        def go(target, **change):
            values = dict(pc=target, a=a, b=b, c=c, block=block, zf=zf, stack=stack, calls=calls, conds=conds)
            values.update(change)
            todo.append(tuple(values.values()))

        def back(**change):
            if calls:
                go(calls[-1], calls=calls[:-1], **change)

        def label(name):
            return labels.get(scope + name if name.startswith('.') else name)

        def ways(cond):
            """(taken, conditions) for each way a conditional op can go."""
            if cond not in ('z', 'nz') or zf is None:
                return [(True, conds), (False, conds)]
            out = []
            for value in (False, True):
                if (zf, not value) not in conds:
                    out.append(((cond == 'nz') == value, conds | {(zf, value)}))
            return out

        if op.startswith('CheckEvent') and args and args[0].startswith('EVENT_'):
            go(pc + 1, zf=args[0])
        elif op in ('jr', 'jp', 'call', 'ret'):
            cond = args[0] if op == 'ret' and args else (args[0] if len(args) == 2 else None)
            target = None if op == 'ret' else label(args[-1])
            for taken, after in ways(cond) if cond else [(True, conds)]:
                if not taken:
                    go(pc + 1, conds=after)
                elif op == 'ret':
                    back(conds=after)
                elif op == 'call' and target is not None and len(calls) < DEPTH:
                    go(target, calls=calls + (pc + 1,), conds=after)
                elif op == 'call':
                    go(pc + 1, a=None, zf=None, conds=after)
                elif target is not None:
                    go(target, conds=after)
        elif op in ('predef', 'predef_jump'):
            if args == ['ReplaceTileBlock'] and None not in (block, b, c):
                found.add((c, b, block, conds))
            (back if op == 'predef_jump' else lambda **change: go(pc + 1, **change))(a=None, zf=None)
        elif op == 'ld' and args == ['[wNewTileBlockID]', 'a']:
            go(pc + 1, block=a)
        elif op == 'ld' and args[0] in ('a', 'b', 'c'):
            value = {'a': a, 'b': b, 'c': c}.get(args[1], _value(args[1]))
            go(pc + 1, **{args[0]: value})
        elif op == 'lb' and args[0] == 'bc':
            go(pc + 1, b=_value(args[1]), c=_value(args[2]))
        elif op == 'push':
            go(pc + 1, stack=stack + ((args[0], (a, zf) if args[0] == 'af' else (b, c)),))
        elif op == 'pop' and stack:
            reg, saved = stack[-1]
            restore = {'af': dict(a=saved[0], zf=saved[1]), 'bc': dict(b=saved[0], c=saved[1])}.get(args[0], {})
            go(pc + 1, stack=stack[:-1], **restore)
        elif op in QUIET:
            go(pc + 1)
        else:
            go(pc + 1, a=0 if args == ['a'] and op == 'xor' else None, zf=None)
    return found


def _settable(src):
    """Every flag some code can set. A flag that only ever appears in a CheckEvent test stays unset."""
    order = re.findall(r'^\s*const\s+(EVENT_\w+)', _code(_read(src, 'constants/event_constants.asm')), re.M)
    out = set()
    for path in sorted(Path(src).rglob('*.asm')):
        if path.relative_to(src).parts[0] == 'constants':
            continue
        for line in _code(path.read_text(encoding='utf-8')).splitlines():
            names = re.findall(r'\bEVENT_\w+', line)
            op = line.strip().partition(' ')[0]
            if 'EventRange' in op and len(names) == 2 and set(names) <= set(order):
                out.update(order[order.index(names[0]):order.index(names[1]) + 1])
            elif names and not op.startswith('CheckEvent'):
                out.update(names)
    return out


def swaps(src):
    """map constant -> {(block x, block y): [(block, conditions)]} for every flag-gated block swap."""
    settable = _settable(src)
    code, labels, routines = _link(src)
    owner = {name: script for script, names in routines.items() for name in names}
    # Walk the scripts that swap a block themselves or call a routine of one that does.
    walk, uses = set(), {}
    for op, args, scope in code:
        if op in ('predef', 'predef_jump') and args == ['ReplaceTileBlock']:
            walk.add(owner.get(scope))
        elif op in ('call', 'jp', 'jr') and args and args[-1] in owner:
            uses.setdefault(owner.get(scope), set()).add(owner[args[-1]])
    while more := {script for script, used in uses.items() if script not in walk and used & walk}:
        walk |= more
    out = {}
    for script in sorted(walk - {None}):
        sites = {}
        for x, y, block, conds in _walk(code, labels, routines[script]):
            if all(value is False or flag in settable for flag, value in conds):
                kept = frozenset((flag, value) for flag, value in conds if flag in settable)
                sites.setdefault((x, y), set()).add((block, kept))
        sites = {site: sorted(cases, key=repr) for site, cases in sites.items() if any(conds for _, conds in cases)}
        if sites:
            out[_map_name(src, script)] = sites
    return out


def _decide(name, site, cases):
    """(flag, block once set, block until set) for a site one flag decides. None draws nothing."""
    flags = sorted({flag for _, conds in cases for flag, _ in conds})

    def outcome(state):
        blocks = {block for block, conds in cases if all(state[flag] == value for flag, value in conds)}
        if len(blocks) > 1:
            raise ValueError(f'{name} {site} draws {sorted(blocks)} under the same flags')
        return next(iter(blocks), None)

    states = [dict(zip(flags, values)) for values in itertools.product((False, True), repeat=len(flags))]
    deciding = [flag for flag in flags if any(outcome(state) != outcome({**state, flag: not state[flag]})
                                              for state in states)]
    if len(deciding) != 1:
        raise ValueError(f'{name} {site} depends on {deciding}, not on one flag')
    flag = deciding[0]
    rest = {other: False for other in flags}
    return flag, outcome({**rest, flag: True}), outcome({**rest, flag: False})


def facts(src):
    """Rows of (map, block x, block y, flag, block once set, block until set), one per swapped block.

    None means the script draws nothing in that state, so the map file's block stays.
    """
    return tuple((name, x, y, *_decide(name, (x, y), cases))
                 for name, sites in swaps(src).items() if name not in ALLOWED
                 for (x, y), cases in sorted(sites.items()))


def uncovered(src, rows):
    """The coverage check: flag-gated swaps with no fact and no allowed map, and allowed maps with no swap."""
    found = swaps(src)
    have = {(name, x, y) for name, x, y, *_ in rows}
    missing = [f'{name} block ({x}, {y}) swaps on a flag and has no fact'
               for name, sites in found.items() if name not in ALLOWED
               for x, y in sorted(sites) if (name, x, y) not in have]
    red = source(src)[0] == 'pokered'
    stale = [f'{name} is allowed but no script swaps a block there on a flag' for name in ALLOWED
             if name not in found and (red or name not in RED_ONLY)]
    return missing + stale


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


def _row(row):
    name, x, y, flag, *blocks = row
    once, until = ('None' if block is None else f'0x{block:02X}' for block in blocks)
    return f'    ({name!r}, {x}, {y}, {flag!r}, {once}, {until}),'


def body(src):
    """The facts without their header, the same for every source that agrees on them."""
    lines = [
        '# (map, block x, block y, flag, block once set, block until set): when the map loads, its script',
        '# redraws the block by the flag. None draws nothing, so the map file block stays.',
        'SWAPS = (',
        *(_row(row) for row in facts(src)),
        ')',
    ]
    return '\n'.join(lines) + '\n'


def render(src):
    repository, commit = source(src)
    return '\n'.join((
        f'"""Gen I map facts, generated by tools/gen1_map_facts.py from pret/{repository} {commit}.',
        '',
        'Generated, not written by hand. Regenerate with the tool. tests/test_gen1_map_facts.py checks it.',
        '"""',
        '',
    )) + body(src)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.write(render(sys.argv[1]))
