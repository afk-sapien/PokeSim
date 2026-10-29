"""Generate the Gen I wild table from pret/pokered and pret/pokeyellow checkouts.

Usage: python tools/gen1_wild.py /path/to/pokered /path/to/pokeyellow > pokesim/policies/wild.py

Each map that has wild Pokémon gets its grass and water encounter rates and its ten slots, read from
the map's file under data/wild/maps in the order of WildDataPointers. Red and Blue share pokered and
differ only inside its IF DEF(_RED) and IF DEF(_BLUE) blocks, so pokered gives both tables. The
table is generated and never written by hand. tests/test_gen1_wild.py regenerates it whenever a
checkout is present and fails when the checked-in table has drifted.
"""
import importlib.util
import re
import sys
from pathlib import Path

# The gate tool already reads which commit a checkout is at.
_spec = importlib.util.spec_from_file_location('gen1_gates_tool', Path(__file__).with_name('gen1_gates.py'))
_gates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gates)
source = _gates.source

VERSION_BLOCK = re.compile(r'^IF DEF\(_(\w+)\)\n(.*?)^ENDC\n', re.M | re.S)
SLOT = re.compile(r'^\s*db\s+(\d+),\s*(\w+)', re.M)


def _read(src, path):
    return (Path(src) / path).read_text(encoding='utf-8')


def _code(text):
    """The source without comments."""
    return '\n'.join(line.split(chr(59))[0].rstrip() for line in text.splitlines()) + '\n'


def _version(text, version):
    """The source as ``version`` builds it, keeping only its own IF DEF blocks."""
    return VERSION_BLOCK.sub(lambda m: m[2] if m[1] == version else '', text)


def chances(src):
    """Each slot's share out of 256, from slot 0 to slot 9."""
    text = _code(_read(src, 'data/wild/probabilities.asm'))
    found = tuple(int(n) for n in re.findall(r'^\s*wild_chance\s+(\d+)', text, re.M))
    if len(found) != 10 or sum(found) != 256:
        raise ValueError('wild slot chances are not ten slots out of 256')
    return found


def _part(text, kind):
    """(rate, slots) between def_<kind>_wildmons and end_<kind>_wildmons."""
    match = re.search(rf'def_{kind}_wildmons\s+(\d+)\n(.*?)end_{kind}_wildmons', text, re.S)
    if not match:
        raise ValueError(f'no {kind} data')
    rate, slots = int(match[1]), tuple((int(level), name) for level, name in SLOT.findall(match[2]))
    if len(slots) != (10 if rate else 0):
        raise ValueError(f'{kind} rate {rate} with {len(slots)} slots')
    return rate, slots


def _labels(src, version):
    """(grass, water) for each WildMons label, as ``version`` builds it."""
    found = {}
    for path in sorted((Path(src) / 'data/wild/maps').glob('*.asm')):
        text = _version(_code(path.read_text(encoding='utf-8')), version)
        for label, part in re.findall(r'^(\w+WildMons):\n(.*?)(?=^\w+:|\Z)', text, re.M | re.S):
            found[label] = (_part(part, 'grass'), _part(part, 'water'))
    return found


def _maps(src):
    return re.findall(r'^\s*map_const\s+(\w+),', _code(_read(src, 'constants/map_constants.asm')), re.M)


def table(src, version):
    """{map: ((grass rate, grass slots), (water rate, water slots))} for each map with wild Pokémon."""
    text = _code(_read(src, 'data/wild/grass_water.asm'))
    pointers = re.search(r'^WildDataPointers:\n(.*?)^\s*dw -1', text, re.M | re.S)[1]
    labels = re.findall(r'^\s*dw\s+(\w+)', pointers, re.M)
    maps = _maps(src)
    if len(labels) != len(maps):
        raise ValueError(f'{len(labels)} wild pointers for {len(maps)} maps')
    data = _labels(src, version)
    return {name: data[label] for name, label in zip(maps, labels) if data[label] != ((0, ()), (0, ()))}


def _dict(name, rows):
    pad = ' ' * (len(name) + 4)
    lines = [f'{pad}{key!r}: {value!r},' for key, value in rows.items()]
    lines[0] = f'{name} = {{' + lines[0].lstrip()
    lines[-1] = lines[-1][:-1] + '}'
    return lines


def red_body(src):
    """The Red and Blue tables, from a pokered checkout. Blue lists only the maps it changes."""
    red, blue = table(src, 'RED'), table(src, 'BLUE')
    if red.keys() != blue.keys():
        raise ValueError('Red and Blue have wild Pokémon on different maps')
    return '\n'.join([
        '# Each slot\'s share of 256 wild encounters, from slot 0 to slot 9. Yellow uses the same shares.',
        f'SLOT_CHANCES = {chances(src)!r}',
        '# Map: ((grass rate, grass slots), (water rate, water slots)). A rate is the chance out of 256 that',
        '# a step on grass, a cave floor or water meets a wild Pokémon, and a slot is (level, species).',
        *_dict('RED', red),
        '# Blue is Red with its own slots on these maps.',
        *_dict('BLUE', {name: slots for name, slots in blue.items() if slots != red[name]}),
        'BLUE = RED | BLUE',
    ]) + '\n'


def yellow_body(src):
    """The Yellow table, from a pokeyellow checkout."""
    return '\n'.join(_dict('YELLOW', table(src, 'YELLOW'))) + '\n'


def render(red, yellow):
    if chances(yellow) != chances(red):
        raise ValueError('Yellow slot chances differ from Red')
    return '\n'.join((
        f'"""Gen I wild Pokémon, generated by tools/gen1_wild.py from pret/pokered {source(red)[1]}',
        f'and pret/pokeyellow {source(yellow)[1]}.',
        '',
        'Generated, not written by hand. Regenerate with the tool. tests/test_gen1_wild.py checks it.',
        '"""',
        '',
        '',
    )) + red_body(red) + yellow_body(yellow) + "BY_GAME = {'red': RED, 'blue': BLUE, 'yellow': YELLOW}\n"


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.stdout.write(render(sys.argv[1], sys.argv[2]))
