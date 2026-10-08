"""Generate local Gen II data from verified pret source archives."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import operator
from pathlib import Path
import re
import tarfile
import tempfile
from urllib.request import urlopen

from ..downloads import retrying
from ..experimental.gen2 import PROFILES

SCHEMA = 6
SOURCES = {
    'gold': ('pokegold', '62388c7204e5d13aa05b4231e220b6760584d1b5'),
    'silver': ('pokegold', '62388c7204e5d13aa05b4231e220b6760584d1b5'),
    'crystal': ('pokecrystal', '5beda23ffa505f62e1dad7e3d7c214d1737b3358'),
}
SYMBOLS = {
    'gold': ('521550d5d988faf9371bc51caed4cf696bfa07b4', '95ce3c7455cc5c1a42acdd52ef529df363b74d83f7f07b2af239607ec93908f9'),
    'silver': ('521550d5d988faf9371bc51caed4cf696bfa07b4', 'fdaa1a22e513db5103b1ebd459792f360720b866ded59866106c5fe21107d5a6'),
    'crystal': ('87b0d7436e43c3717cfc416d38a99162191bb714', '915e46c9df40a016d530b70979a002b44b301b8c4fc548a30ed249042d7a11a5'),
}


def download(url, limit, game, report=lambda message: None, sleep=None):
    """Read a pinned URL, retrying brief network failures a bounded number of times."""
    def read():
        with urlopen(url, timeout=30) as response:
            return response.read(limit + 1)
    return retrying(read, f'Pokémon {game.title()}', report, sleep)


def lines(path):
    return [line.split(chr(59), 1)[0].strip() for line in Path(path).read_text().splitlines()]


def number(expression, constants=None):
    """Evaluate only integer assembly constant expressions."""
    constants = constants or {}
    expression = re.sub(r'\$([\da-fA-F]+)', r'0x\1', expression)
    expression = re.sub(r'%([01]+)', r'0b\1', expression)
    tree = ast.parse(expression, mode='eval')
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.FloorDiv: operator.floordiv, ast.Div: operator.floordiv,
           ast.LShift: operator.lshift, ast.RShift: operator.rshift,
           ast.BitOr: operator.or_, ast.BitAnd: operator.and_}

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name):
            return constants[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -evaluate(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError(f'Unsupported assembly expression: {expression}')

    return evaluate(tree.body)


def constants(path):
    result = {}
    value = 0
    machines = {'TM': 0, 'HM': 0}
    macro = False
    for line in lines(path):
        if line.startswith('MACRO '):
            macro = True
        if line == 'ENDM':
            macro = False
            continue
        if macro:
            continue
        parts = line.split(None, 1)
        if not parts:
            continue
        command, arg = parts[0], parts[1] if len(parts) > 1 else ''
        try:
            if command == 'const_def':
                value = number(arg.split(',')[0], result) if arg else 0
            elif command == 'const_next':
                value = number(arg, result)
            elif command == 'const_skip':
                value += number(arg, result) if arg else 1
            elif command == 'const':
                result[arg] = value
                value += 1
            elif command in {'add_tm', 'add_hm'}:
                prefix = 'TM' if command == 'add_tm' else 'HM'
                machines[prefix] += 1
                index = machines[prefix]
                result[f'{prefix}{index:02d}'] = value
                result[f'{prefix}_{arg}'] = value
                value += 1
            else:
                match = re.match(r'(?:DEF|REDEF) (\w+)\s+(?:EQU|=)\s+(.+)', line)
                if match:
                    result[match[1]] = number(match[2], {**result, 'const_value': value})
        except (ValueError, KeyError, SyntaxError):
            continue
    return result


def pretty(name):
    return name.replace('_', ' ').title().replace('Pokemon', 'Pokémon').replace('Pokecenter', 'Pokémon Center')


def _aliases(path, suffix, directive):
    result, pending = {}, []
    for line in lines(path):
        match = re.match(r'(\w+)' + re.escape(suffix) + r'::?$', line)
        if match:
            pending.append(match[1])
        match = re.match(directive + r' "([^"]+)"', line)
        if match:
            result.update({name: match[1] for name in pending})
            pending.clear()
    return result


def world(source):
    maps, identifiers = {}, {}
    group = index = 0
    for line in lines(source / 'constants/map_constants.asm'):
        if line.startswith('newgroup '):
            group += 1
            index = 0
        match = re.match(r'map_const (\w+),\s*(\d+),\s*(\d+)', line)
        if match:
            index += 1
            mid = group * 256 + index
            identifiers[match[1]] = mid
            maps[mid] = {'id': mid, 'constant': match[1], 'group': group, 'number': index,
                         'width': int(match[2]) * 2, 'height': int(match[3]) * 2,
                         'name': pretty(match[1]), 'warps': [], 'objects': [], 'connections': []}
    rows = [line[4:].split(',') for line in lines(source / 'data/maps/maps.asm') if line.startswith('map ')]
    if len(rows) != len(maps):
        raise ValueError('Map header count does not match map constants')
    block_files = _aliases(source / 'data/maps/blocks.asm', '_Blocks', 'INCBIN')
    coll_files = {name.lower(): path for name, path in _aliases(source / 'gfx/tilesets.asm', 'Coll', 'INCLUDE').items()}
    coll_constants = constants(source / 'constants/collision_constants.asm')
    landmarks = constants(source / 'constants/landmark_constants.asm')
    for (mid, entry), row in zip(maps.items(), rows):
        label, tileset = [part.strip() for part in row[:2]]
        entry['label'] = label
        entry['tileset'] = tileset
        entry['environment'] = row[2].strip()
        entry['landmark'] = landmarks[row[3].strip()]
        entry['region'] = 'kanto' if entry['landmark'] >= landmarks['KANTO_LANDMARK'] else 'johto'
        entry['fishing_group'] = row[7].strip()
        coll_label = 'Tileset' + ''.join(word.title() for word in tileset.removeprefix('TILESET_').split('_'))
        coll = []
        for line in lines(source / coll_files[coll_label.lower()]):
            if line.startswith('tilecoll '):
                coll.append([coll_constants['COLL_' + token.strip()] for token in line[9:].split(',')])
        blocks = (source / block_files[label]).read_bytes()
        width, height = entry['width'], entry['height']
        if len(blocks) != width * height // 4:
            raise ValueError(f'Map block size mismatch for {label}')
        entry['blocks'] = list(blocks)
        entry['block_collision'] = coll
        entry['collision'] = [coll[blocks[(y // 2) * (width // 2) + x // 2]][(y % 2) * 2 + x % 2]
                              for y in range(height) for x in range(width)]
        entry['shops'] = []
        script = None
        for line in lines(source / f'maps/{label}.asm'):
            if re.fullmatch(r'\w+:', line):
                script = line[:-1]
            if line.startswith('pokemart MARTTYPE_STANDARD, '):
                entry['shops'].append({'script': script, 'mart': line.split(',')[1].strip()})
            if line.startswith('warp_event '):
                x, y, target, target_warp = [part.strip() for part in line[11:].split(',')]
                entry['warps'].append({'x': int(x), 'y': int(y), 'map': identifiers[target], 'warp': int(target_warp)})
            elif line.startswith('object_event '):
                parts = [part.strip() for part in line[13:].split(',')]
                entry['objects'].append({'x': int(parts[0]), 'y': int(parts[1]), 'sprite': parts[2],
                                         'movement': parts[3], 'kind': parts[9], 'script': parts[11], 'event': parts[12]})
    current = None
    for line in lines(source / 'data/maps/attributes.asm'):
        if line.startswith('map_attributes '):
            parts = [part.strip() for part in line[15:].split(',')]
            current = maps[identifiers[parts[1]]]
        elif line.startswith('connection ') and current is not None:
            parts = [part.strip() for part in line[11:].split(',')]
            current['connections'].append({'direction': parts[0], 'map': identifiers[parts[2]], 'offset': int(parts[3])})
    return identifiers, maps


def version_lines(path, game):
    stack = []
    for line in lines(path):
        if line.startswith('IF DEF('):
            stack.append(line == f'IF DEF(_{game.upper()})')
        elif line.startswith('ELIF DEF('):
            stack[-1] = line == f'ELIF DEF(_{game.upper()})'
        elif line == 'ELSE':
            stack[-1] = not stack[-1]
        elif line == 'ENDC':
            stack.pop()
        elif all(stack):
            yield line


def wild_encounters(source, game, map_ids, pokemon):
    result = []
    for region in ('johto', 'kanto'):
        for kind in ('grass', 'water'):
            current, slots = None, []
            for line in version_lines(source / f'data/wild/{region}_{kind}.asm', game):
                if line.startswith(f'def_{kind}_wildmons '):
                    current = map_ids[line.split()[1]]
                    slots = []
                elif line.startswith(f'end_{kind}_wildmons'):
                    expected = 21 if kind == 'grass' else 3
                    if len(slots) != expected:
                        raise ValueError(f'Incomplete encounter table for {current}')
                    for index, (level, species) in enumerate(slots):
                        probabilities = (30, 30, 20, 10, 5, 4, 1) if kind == 'grass' else (60, 30, 10)
                        result.append({'map': current, 'species': species, 'level': level,
                                       'method': 'grass' if kind == 'grass' else 'surf',
                                       'time': ('morning', 'day', 'night')[index // 7] if kind == 'grass' else 'any',
                                       'chance': probabilities[index % len(probabilities)]})
                    current = None
                elif current is not None:
                    match = re.fullmatch(r'db (\d+),\s*(\w+)', line)
                    if match:
                        slots.append((int(match[1]), pokemon[match[2]]))
    return result


def fishing_encounters(source, game, maps, pokemon):
    groups = constants(source / 'constants/map_data_constants.asm')
    rows = list(version_lines(source / 'data/wild/fish.asm', game))
    tables, pending, current, references, timed = {}, [], None, [], []
    for row in rows:
        if row.startswith('fishgroup '):
            references.append([part.strip() for part in row.split(',')[1:]])
        elif row.startswith('.') and row.endswith(':'):
            if current:
                pending = []
            pending.append(row[:-1])
            current = []
        elif row == 'TimeFishGroups:':
            current = None
            pending = []
        elif row.startswith('db ') and pending:
            if not current:
                for name in pending:
                    tables[name] = current
            current.append([part.strip() for part in row[3:].split(',')])
        elif row.startswith('db ') and row.split(',')[0][3:].strip() in pokemon:
            timed.append([part.strip() for part in row[3:].split(',')])
    result = []
    for mid, entry in maps.items():
        if not any(tile in (0x21, 0x29) for tile in entry['collision']):
            continue
        group = groups.get(entry['fishing_group'], 0)
        if not 1 <= group <= len(references):
            continue
        for rod, label in zip(('old rod', 'good rod', 'super rod'), references[group - 1]):
            previous = 0
            for row in tables[label]:
                threshold = int(row[0].split()[0])
                chance, previous = threshold - previous, threshold
                if row[1].startswith('time_group '):
                    slots = timed[int(row[1].split()[1])]
                    encounters = [('morning/day', slots[0], int(slots[1])), ('night', slots[2], int(slots[3]))]
                else:
                    encounters = [('any', row[1], int(row[2]))]
                for time, species, level in encounters:
                    result.append({'map': mid, 'species': pokemon[species], 'level': level,
                                   'method': rod, 'time': time, 'chance': chance})
    return result


def tree_encounters(source, game, map_ids, pokemon):
    rows = version_lines(source / 'data/wild/treemons.asm', game)
    tables, current, rare = {}, None, False
    for row in rows:
        if row.startswith('TreeMonSet_') and row.endswith(':'):
            current, rare = row[:-1], False
            tables[current] = []
        elif current and row == 'db -1':
            rare = True
        elif current and row.startswith('db '):
            parts = [part.strip() for part in row[3:].split(',')]
            if len(parts) == 3:
                tables[current].append((int(parts[0]), pokemon[parts[1]], int(parts[2]), rare))
    result = []
    for row in version_lines(source / 'data/wild/treemon_maps.asm', game):
        if not row.startswith('treemon_map '):
            continue
        name, group = [part.strip() for part in row[12:].split(',')]
        label = 'TreeMonSet_' + ''.join(part.title() for part in group.removeprefix('TREEMON_SET_').split('_'))
        for chance, species, level, rare in tables[label]:
            result.append({'map': map_ids[name], 'species': species, 'level': level,
                           'method': 'rock smash' if group == 'TREEMON_SET_ROCK' else 'headbutt',
                           'time': 'rare trees' if rare else 'any', 'chance': chance})
    return result


def generate(source, symbols, game):
    source = Path(source)
    pokemon = constants(source / 'constants/pokemon_constants.asm')
    items = constants(source / 'constants/item_constants.asm')
    type_constants = constants(source / 'constants/type_constants.asm')
    types = {line[6:]: type_constants[line[6:]]
             for line in lines(source / 'constants/type_constants.asm') if line.startswith('const ')}
    move_ids = constants(source / 'constants/move_constants.asm')
    events = constants(source / 'constants/event_flags.asm')
    species_names = [row.split('"')[1].replace('#', 'POKé') for row in lines(source / 'data/pokemon/names.asm') if row.startswith('dname ')]
    item_names = {index: row.split('"')[1].replace('#', 'POKé') for index, row in enumerate(
        (row for row in lines(source / 'data/items/names.asm') if row.startswith('li ')), 1)}
    species = {}
    for path in sorted((source / 'data/pokemon/base_stats').glob('*.asm')):
        rows = [line[3:].strip() for line in lines(path) if line.startswith('db ')]
        if not rows or rows[0] not in pokemon:
            continue
        name = rows[0]
        sid = pokemon[name]
        growth = next(row.removeprefix('GROWTH_') for row in rows if row.startswith('GROWTH_'))
        species[sid] = {'name': species_names[sid - 1].title(), 'constant': name, 'dex': sid,
                        'stats': [int(part) for part in rows[1].split(',')],
                        'types': [types[part.strip()] for part in rows[2].split(',')],
                        'gender_ratio': {'GENDER_F0': 0, 'GENDER_F12_5': 31, 'GENDER_F25': 63,
                                         'GENDER_F50': 127, 'GENDER_F75': 191, 'GENDER_F100': 254,
                                         'GENDER_UNKNOWN': 255}[rows[6]],
                        'egg_cycles': int(rows[8]),
                        'egg_groups': next([part.strip().removeprefix('EGG_') for part in row[3:].split(',')]
                                           for row in lines(path) if row.startswith('dn EGG_')),
                        'catch_rate': int(rows[3]), 'base_exp': int(rows[4]), 'growth': growth,
                        'machines': [move_ids[token.strip()] for row in lines(path)
                                     if row.startswith('tmhm ') for token in row[5:].split(',')],
                        'learnset': [], 'evolutions': []}
    moves = {}
    pictures = [line[9:].split(',')[0].strip() if line.startswith('dba_pics ') else 'UnownAFrontpic'
                for line in lines(source / 'data/pokemon/pic_pointers.asm')
                if line.startswith('dba_pics ') or line == 'dba_pics']
    for sid, picture in enumerate(pictures[:251], 1):
        species[sid]['front_symbol'] = picture
    for line in lines(source / 'data/moves/moves.asm'):
        if line.startswith('move '):
            name, effect, power, type_name, accuracy, pp, chance = [part.strip() for part in line[5:].split(',')]
            moves[move_ids[name]] = {'name': pretty(name), 'constant': name, 'effect': effect,
                                    'power': int(power), 'type': types[type_name], 'accuracy': int(accuracy),
                                    'pp': int(pp), 'chance': int(chance)}
    aliases = {name.replace('_', '').lower(): sid for name, sid in pokemon.items() if sid in species}
    current = None
    for line in lines(source / 'data/pokemon/evos_attacks.asm'):
        match = re.match(r'(\w+)EvosAttacks:', line)
        if match:
            current = species.get(aliases.get(match[1].lower()))
        elif current is not None and line.startswith('db '):
            parts = [part.strip() for part in line[3:].split(',')]
            if parts[0].startswith('EVOLVE_'):
                current['evolutions'].append({'method': parts[0].removeprefix('EVOLVE_').lower(),
                                               'requirements': parts[1:-1], 'species': pokemon[parts[-1]]})
            elif len(parts) == 2 and parts[0].isdigit():
                current['learnset'].append([int(parts[0]), move_ids[parts[1]]])
    map_ids, maps = world(source)
    map_constants = constants(source / 'constants/map_data_constants.asm')
    spawns = [[part.strip() for part in row[6:].split(',')]
              for row in lines(source / 'data/maps/spawn_points.asm') if row.startswith('spawn ')]
    fly_points = []
    for row in lines(source / 'data/maps/flypoints.asm'):
        if not row.startswith('db LANDMARK_'):
            continue
        spawn = map_constants[row.split(',')[1].strip()]
        name, x, y = spawns[spawn]
        fly_points.append({'map': map_ids[name], 'x': int(x), 'y': int(y), 'spawn': spawn})
    encounters = wild_encounters(source, game, map_ids, pokemon)
    encounters.extend(fishing_encounters(source, game, maps, pokemon))
    encounters.extend(tree_encounters(source, game, map_ids, pokemon))
    mart_ids = constants(source / 'constants/mart_constants.asm')
    mart_rows = lines(source / 'data/items/marts.asm')
    labels = [row[3:] for row in mart_rows if row.startswith('dw Mart')]
    inventories, current = {}, None
    for row in mart_rows:
        if re.fullmatch(r'Mart\w+:', row):
            current = row[:-1]
            inventories[current] = []
        elif current and row.startswith('db ') and row[3:] in items:
            inventories[current].append(items[row[3:]])
    for entry in maps.values():
        for shop in entry['shops']:
            shop['items'] = inventories[labels[mart_ids[shop['mart']]]]
    attributes = {}
    for index, row in enumerate((row for row in lines(source / 'data/items/attributes.asm')
                                 if row.startswith('item_attribute ')), 1):
        parts = [part.strip() for part in row[15:].split(',')]
        attributes[index] = {'price': number(parts[0]), 'held_effect': parts[1], 'pocket': parts[4]}

    matchups = []
    for line in lines(source / 'data/types/type_matchups.asm'):
        if line.startswith('db '):
            parts = [part.strip() for part in line[3:].split(',')]
            if len(parts) == 3 and parts[0] in types:
                matchups.append([types[parts[0]], types[parts[1]],
                                 {'NO_EFFECT': 0, 'NOT_VERY_EFFECTIVE': 0.5, 'SUPER_EFFECTIVE': 2}[parts[2]]])
    collisions = constants(source / 'constants/collision_constants.asm')
    permissions = [number(line[3:], collisions) for line in lines(source / 'data/collision/collision_permissions.asm')
                   if line.startswith('db ')]
    parsed_symbols = {}
    for line in Path(symbols).read_text().splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]+):([0-9a-fA-F]+) (\w+)', line)
        if match:
            parsed_symbols[match[3]] = [int(match[1], 16), int(match[2], 16)]
    charmap = {}
    for line in lines(source / 'constants/charmap.asm'):
        match = re.fullmatch(r'charmap "(.*)",\s*\$([0-9a-fA-F]+)', line)
        if match:
            charmap.setdefault(int(match[2], 16), match[1])
    if len(species) != 251 or len(moves) != 251:
        raise ValueError(f'Incomplete Gen II data: {len(species)} species and {len(moves)} moves')
    return {'schema': SCHEMA, 'game': game, 'source_revision': SOURCES[game][1],
            'species': species, 'moves': moves, 'items': items, 'item_names': item_names, 'types': types, 'events': events,
            'maps': maps, 'map_ids': map_ids, 'fly_points': fly_points, 'symbols': parsed_symbols, 'charmap': charmap,
            'collisions': collisions, 'permissions': permissions, 'encounters': encounters, 'matchups': matchups, 'item_attributes': attributes}


class GameData:
    def __init__(self, raw):
        self.raw = raw
        self.game = raw['game']
        for name in ('species', 'moves', 'maps', 'charmap', 'item_attributes'):
            setattr(self, name, {int(key): value for key, value in raw[name].items()})
        for name in ('items', 'types', 'events', 'map_ids', 'symbols', 'collisions', 'permissions'):
            setattr(self, name, raw[name])
        self.item_names = {int(key): value.title() for key, value in raw.get('item_names', {}).items()}
        for name, value in self.items.items():
            if name not in {'NO_ITEM', 'NUM_ITEMS', 'NUM_TMS', 'NUM_HMS'} and not name.startswith(('TM_', 'HM_')):
                self.item_names.setdefault(value, pretty(name))
        self.matchups = {(a, b): factor for a, b, factor in raw.get('matchups', [])}
        self.encounters = raw.get('encounters', [])
        self.fly_points = raw.get('fly_points', [])
        self.type_names = {value: pretty(name.removesuffix('_TYPE')) for name, value in self.types.items()}

    def text(self, raw):
        return ''.join(self.charmap.get(value, '') for value in bytes(raw).split(bytes([0x50]), 1)[0]).strip()

    @classmethod
    def load(cls, root, game):
        directory = Path(root) / 'gen2' / game
        manifest = json.loads((directory / 'manifest.json').read_text())
        raw = (directory / 'data.json').read_bytes()
        if manifest != {'schema': SCHEMA, 'game': game, 'source_revision': SOURCES[game][1],
                        'sha256': hashlib.sha256(raw).hexdigest()}:
            raise ValueError('Gen II game data verification failed')
        return cls(json.loads(raw))


def write_bundle(root, game, data):
    from ..checkpoints import CheckpointStore
    directory = Path(root) / 'gen2' / game
    directory.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(',', ':')).encode()
    manifest = {'schema': SCHEMA, 'game': game, 'source_revision': SOURCES[game][1],
                'sha256': hashlib.sha256(raw).hexdigest()}
    CheckpointStore.atomic_write(directory / 'data.json', raw)
    CheckpointStore.atomic_write(directory / 'manifest.json', json.dumps(manifest).encode())


def ensure(root, game, report=lambda message: None):
    try:
        return GameData.load(root, game)
    except (OSError, ValueError, KeyError):
        pass
    repo, revision = SOURCES[game]
    symbol_revision, symbol_hash = SYMBOLS[game]
    profile = next(profile for profile in PROFILES if profile.game == game)
    report(f'Preparing Pokémon {game.title()} maps and game data')
    with tempfile.TemporaryDirectory(prefix='pokesim-gen2-data-') as temporary:
        temporary = Path(temporary)
        archive = download(f'https://codeload.github.com/pret/{repo}/tar.gz/{revision}',
                           16 * 1024 * 1024, game, report)
        if len(archive) > 16 * 1024 * 1024:
            raise ValueError('Gen II reference archive is too large')
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            members = tar.getmembers()
            if sum(member.size for member in members) > 64 * 1024 * 1024:
                raise ValueError('Gen II reference contents are too large')
            tar.extractall(temporary, filter='data')
        url = f'https://raw.githubusercontent.com/pret/{repo}/{symbol_revision}/{profile.symbols}'
        symbols = download(url, 8 * 1024 * 1024, game, report)
        if hashlib.sha256(symbols).hexdigest() != symbol_hash:
            raise ValueError('Gen II symbols failed verification')
        symbol_path = temporary / profile.symbols
        symbol_path.write_bytes(symbols)
        data = generate(temporary / f'{repo}-{revision}', symbol_path, game)
        write_bundle(root, game, data)
    return GameData.load(root, game)
