"""Generate the Gen II map facts from pret/pokecrystal and pret/pokegold checkouts.

Usage: python tools/gen2_map_facts.py /path/to/pokecrystal /path/to/pokegold \\
    > packages/pokecore/src/pokecore/gen2/mapfacts.py

A block swap is a map callback that redraws one block of its map when the map loads, picking the
block by an event flag: the Elite Four doors, the Team Rocket Base doors, the Goldenrod Underground
switch room and the rest. The tool expands each map script's macros and loops, then follows its
callbacks along every branch, so a swap is read from the code that makes it and never copied by
hand. tests/test_gen2_map_facts.py regenerates the facts whenever the checkouts are present and
fails when the checked-in file has drifted.

The same walk lists every flag-gated swap in the callbacks. Each one is a fact or sits on a map or
block in ALLOWED with the reason the facts leave it out, which is the coverage check of the map audit.

The warp carpets come from the collision constants, with the direction that steps off each one.
"""
import ast
import heapq
import itertools
import operator
import re
import subprocess
import sys
from pathlib import Path

# The maps, or (map, x, y) blocks, whose block swaps the facts leave out, with the reason.
ALLOWED = {
    **{f'RUINS_OF_ALPH_{name}_CHAMBER': 'The Unown puzzle opens the floor holes and the back wall. Its goal '
                                        'is walked on the loaded chamber, whose live blocks show them.'
       for name in ('AERODACTYL', 'HO_OH', 'KABUTO', 'OMANYTE')},
    'BURNED_TOWER_1F': 'Crystal only, and the facts are one table for all three games. The hole and the '
                       'ladder down change during the Burned Tower story, whose goals are walked on the '
                       'loaded floor.',
    'BURNED_TOWER_B1F': 'Crystal only, and the facts are one table for all three games. The ladder up goes '
                        'once the beasts are released, and the beasts goal is walked on the loaded floor.',
    'TIN_TOWER_1F': 'Crystal only, and the facts are one table for all three games. The stairs up stay '
                    'hidden until the player has the Rainbow Wing.',
    'GOLDENROD_DEPT_STORE_ROOF': 'Crystal only, and the sale opens the roof on an engine flag, which a '
                                 'snapshot does not read.',
    'ROUTE_19': 'travel_collision in pokecore.gen2.maps raises the rocks until the Cinnabar eruption is '
                'cleared, on every map, loaded or not.',
    **{('GOLDENROD_DEPT_STORE_B1F', x, y): 'Two flags pick one of three box layouts, and a fact reads one flag.'
       for x, y in ((10, 8), (4, 10), (10, 12))},
}
# Maps only Crystal has a swap on.
CRYSTAL_ONLY = {'BURNED_TOWER_1F', 'BURNED_TOWER_B1F', 'TIN_TOWER_1F', 'GOLDENROD_DEPT_STORE_ROOF'}
# Script commands that end a callback, or return from a routine it called.
ENDS = {'end', 'endcallback', 'endall', 'return'}
# Script commands that branch on the last check, and those that branch on a value.
IFS = {'iftrue': True, 'iffalse': False}
VALUE_IFS = {'ifequal', 'ifnotequal', 'ifgreater', 'ifless'}
# Script commands that test a flag, and the kind of flag each tests.
CHECKS = {'checkevent': 'EVENT_', 'checkflag': 'ENGINE_'}
LIMIT = 100_000
DEPTH = 8
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.floordiv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}


def _read(src, path):
    return (Path(src) / path).read_text(encoding='utf-8')


def _code(text):
    """The source lines without comments."""
    return [line.split(chr(59))[0].rstrip() for line in text.splitlines()]


def _number(text, symbols):
    """The value of an assembler expression over numbers, $hex, %binary and defined symbols."""
    text = re.sub(r'\$([\da-fA-F]+)', lambda found: str(int(found[1], 16)), text.strip())
    text = re.sub(r'%([01]+)', lambda found: str(int(found[1], 2)), text)

    def value(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name) and node.id in symbols:
            return symbols[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](value(node.left), value(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -value(node.operand)
        raise ValueError(f'cannot read {text!r}')
    return value(ast.parse(text, mode='eval').body)


def _split(text):
    return [part.strip() for part in text.split(',')] if text.strip() else []


def _expand(lines):
    """The script lines with the assembler's DEF, MACRO, for and {d:symbol} worked out.

    It knows the few directives the map scripts use and fails on a macro it cannot follow.
    """
    symbols, macros, out = {}, {}, []

    def interpolate(line):
        return re.sub(r'\{d:(\w+)\}', lambda found: str(symbols[found[1]]), line)

    def block(lines, start, opener, closer):
        """The index of the line that closes the block opened at start."""
        depth = 0
        for index in range(start, len(lines)):
            word = lines[index].strip().partition(' ')[0]
            depth += word == opener
            depth -= word == closer
            if depth == 0:
                return index
        raise ValueError(f'{opener} at line {start} is not closed')

    def run(lines, frame):
        index = 0
        while index < len(lines):
            raw = lines[index]
            if frame is not None:
                raw = re.sub(r'\\(\d)', lambda found: frame['args'][frame['shift'] + int(found[1]) - 1], raw)
                raw = raw.replace('_NARG', str(len(frame['args']) - frame['shift']))
            line = interpolate(raw)
            word, _, rest = line.strip().partition(' ')
            if word == 'MACRO':
                end = block(lines, index, 'MACRO', 'ENDM')
                macros[rest.strip()] = lines[index + 1:end]
                index = end
            elif word == 'DEF':
                found = re.fullmatch(r'(\w+)\s*(=|\+=|-=|EQU)\s*(.+)', rest.strip())
                if not found:
                    raise ValueError(f'cannot read {line.strip()!r}')
                name, op, expression = found.groups()
                number = _number(expression, symbols)
                symbols[name] = {'+=': symbols.get(name, 0) + number,
                                 '-=': symbols.get(name, 0) - number}.get(op, number)
            elif word == 'for':
                end = block(lines, index, 'for', 'endr')
                name, *bounds = _split(rest)
                numbers = [_number(bound, symbols) for bound in bounds]
                start, stop, step = (0, *numbers, 1)[:3] if len(numbers) == 1 else (*numbers, 1)[:3]
                for value in range(start, stop, step):
                    symbols[name] = value
                    run(lines[index + 1:end], frame)
                index = end
            elif word == 'shift' and frame is not None:
                frame['shift'] += int(rest or 1)
            elif word in macros:
                run(macros[word], {'args': _split(rest), 'shift': 0})
            elif word in ('ENDM', 'endr', 'REPT', 'IF', 'ELIF', 'ELSE', 'ENDC'):
                raise ValueError(f'cannot follow {word} in a map script')
            else:
                out.append((line, dict(symbols)))
            index += 1
    run(lines, None)
    return out


def _program(path):
    """(instructions, labels, callbacks) of one map script.

    An instruction is (command, arguments, symbols, scope). A local label is named under the
    global label it sits in.
    """
    code, labels, callbacks, scope = [], {}, [], ''
    for line, symbols in _expand(_code(path.read_text(encoding='utf-8'))):
        if not line.strip():
            continue
        if not line[0].isspace():
            name = line.strip().rstrip(':')
            if name.startswith('.'):
                name = scope + name
            else:
                scope = name
            labels[name] = len(code)
            continue
        command, _, rest = line.strip().partition(' ')
        if command == 'callback':
            callbacks.append(_split(rest)[1])
        code.append((command, _split(rest), symbols, scope))
    code.append(('end', [], {}, scope))
    return code, labels, callbacks


def _simplify(terms):
    """The same set of flag states with fewer terms.

    A term is a frozenset of (flag, set) that all hold. Two terms that differ only in one flag
    become one without it, and a term that another covers goes.
    """
    terms = set(terms)
    while True:
        merged = {term - {(flag, value)} for term in terms for flag, value in term
                  if term - {(flag, value)} | {(flag, not value)} in terms}
        every = terms | merged
        kept = {term for term in every if not any(other < term for other in every)}
        if kept == terms:
            return terms
        terms = kept


def _walk(code, labels, starts):
    """{(x, y, block): terms} for each block swap the callbacks at starts make, with the flag states that make it.

    The walk goes forward through the script, so both sides of a flag test meet where they rejoin
    and drop that flag, and each swap keeps only the flags that decide it. Branches on anything
    other than an event or engine flag are followed both ways with no condition.
    """
    found, states, done, heap, order = {}, {}, {}, [], itertools.count()

    def push(pc, flag, calls, term):
        key = (pc, flag, calls)
        terms = states.get(key, set())
        if any(other <= term for other in terms):
            return
        states[key] = _simplify(terms | {term})
        heapq.heappush(heap, (pc, next(order), key))

    for name in starts:
        push(labels[name], None, (), frozenset())
    steps = 0
    while heap:
        pc, _, key = heapq.heappop(heap)
        _, flag, calls = key
        for term in states[key] - done.setdefault(key, set()):
            done[key].add(term)
            steps += 1
            if steps > LIMIT:
                raise ValueError('a map script has too many paths to follow')
            command, args, symbols, scope = code[pc]

            def label(name):
                return labels[scope + name if name.startswith('.') else name]

            if command in ENDS:
                if calls:
                    push(calls[-1], flag, calls[:-1], term)
            elif command in CHECKS and args and args[0].startswith(CHECKS[command]):
                push(pc + 1, args[0], calls, term)
            elif command in IFS:
                for taken in (False, True):
                    state = IFS[command] == taken
                    if flag is not None and (flag, not state) in term:
                        continue
                    after = term if flag is None else term | {(flag, state)}
                    push(label(args[-1]) if taken else pc + 1, flag, calls, after)
            elif command in VALUE_IFS:
                push(label(args[-1]), None, calls, term)
                push(pc + 1, None, calls, term)
            elif command in ('sjump', 'farsjump'):
                push(label(args[-1]), flag, calls, term)
            elif command in ('scall', 'farscall'):
                if len(calls) < DEPTH:
                    push(label(args[-1]), flag, calls + (pc + 1,), term)
            elif command == 'changeblock':
                site = tuple(_number(arg, symbols) for arg in args)
                found[site] = _simplify(found.get(site, set()) | {term})
                push(pc + 1, flag, calls, term)
            else:
                push(pc + 1, None, calls, term)
    return found


def _constants(src):
    """Map script file stem -> map constant, read from the map attributes."""
    out = {}
    for line in _code(_read(src, 'data/maps/attributes.asm')):
        if found := re.match(r'\s*map_attributes (\w+), (\w+),', line):
            out[found[1]] = found[2]
    return out


def swaps(src):
    """map constant -> {(x, y): [(block, conditions)]} for every flag-gated block swap."""
    names = _constants(src)
    out = {}
    for path in sorted((Path(src) / 'maps').glob('*.asm')):
        if 'changeblock' not in path.read_text(encoding='utf-8'):
            continue
        code, labels, callbacks = _program(path)
        sites = {}
        for (x, y, block), terms in _walk(code, labels, callbacks).items():
            sites.setdefault((x, y), set()).update((block, term) for term in terms)
        sites = {site: sorted(cases, key=repr) for site, cases in sites.items() if any(term for _, term in cases)}
        if sites:
            out[names[path.stem]] = sites
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


def _allowed(name, x, y):
    return name in ALLOWED or (name, x, y) in ALLOWED


def facts(src):
    """Rows of (map, x, y, flag, block once set, block until set), one per swapped block.

    x and y are walking tiles, as changeblock takes them. None means the callback draws nothing
    in that state, so the map file's block stays.
    """
    return tuple((name, x, y, *_decide(name, (x, y), cases))
                 for name, sites in sorted(swaps(src).items())
                 for (x, y), cases in sorted(sites.items(), key=lambda item: item[0][::-1])
                 if not _allowed(name, x, y))


def carpets(src):
    """{collision byte: direction} for each warp carpet, from the collision constants."""
    text = '\n'.join(_code(_read(src, 'constants/collision_constants.asm')))
    return {int(value, 16): direction.lower() for direction, value in
            re.findall(r'DEF COLL_WARP_CARPET_(DOWN|UP|LEFT|RIGHT)\s+EQU \$([\da-fA-F]+)', text)}


def uncovered(src, rows):
    """The coverage check: flag-gated swaps with no fact and no allowed entry, and allowed entries with no swap."""
    found = swaps(src)
    have = {(name, x, y) for name, x, y, *_ in rows}
    missing = [f'{name} block ({x}, {y}) swaps on a flag and has no fact'
               for name, sites in sorted(found.items())
               for x, y in sorted(sites) if not _allowed(name, x, y) and (name, x, y) not in have]
    crystal = source(src)[0] == 'pokecrystal'
    sites = {(name, x, y) for name, places in found.items() for x, y in places}
    stale = [f'{key} is allowed but no callback swaps a block there on a flag' for key in ALLOWED
             if (key not in found if isinstance(key, str) else key not in sites)
             and (crystal or (key if isinstance(key, str) else key[0]) not in CRYSTAL_ONLY)]
    return missing + stale


def source(src):
    """(repository, commit) of a checkout, or of a GitHub archive named repository-commit."""
    path = Path(src).resolve()
    try:
        commit = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = path.name.rsplit('-', 1)[-1]
    repository = 'pokegold' if 'pokegold.gbc' in _read(path, 'roms.sha1') else 'pokecrystal'
    return repository, commit


def _row(row):
    name, x, y, flag, *blocks = row
    once, until = ('None' if block is None else f'0x{block:02X}' for block in blocks)
    return f'    ({name!r}, {x}, {y}, {flag!r}, {once}, {until}),'


def body(src):
    """The facts without their header, the same for every source that agrees on them."""
    lines = [
        '# (map, x, y, flag, block once set, block until set): when the map loads, its callback redraws',
        '# the block at walking tile (x, y) by the flag. None draws nothing, so the map file block stays.',
        'SWAPS = (',
        *(_row(row) for row in facts(src)),
        ')',
        '',
        '# The collision byte of each warp carpet and the direction that steps off it.',
        'CARPETS = {',
        *(f'    0x{tile:02X}: {direction!r},' for tile, direction in sorted(carpets(src).items())),
        '}',
    ]
    return '\n'.join(lines) + '\n'


def render(*sources):
    texts = {body(src) for src in sources}
    if len(texts) != 1:
        raise ValueError('the sources disagree on the facts')
    names = '\nand '.join('pret/{} {}'.format(*source(src)) for src in sources)
    return '\n'.join((
        f'"""Gen II map facts, generated by tools/gen2_map_facts.py from\n{names}.',
        '',
        'Generated, not written by hand. Regenerate with the tool. tests/test_gen2_map_facts.py checks it.',
        '"""',
        '',
    )) + texts.pop()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.write(render(*sys.argv[1:]))
