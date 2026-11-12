"""``python -m pokesim.replay capture``: keep a stall bundle as a stuck scenario and list it in scenarios/index.toml.

The save goes to the private scenarios folder that ``stuck-scenarios`` replays. The tracked index row
names it by its cartridge and save hash, with the frames from that save to the moment the stall was noticed,
what the replay is expected to do and the issue or pull request. A scenario for an open stall expects
``stuck``. The fix flips it to ``passes``, and from then on the preflight fails when it gets stuck again.
docs/design/replayable-bugs.md section 4.8.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tomllib

from ..checkpoints import CheckpointStore, open_state, read_manifest
from .envs import ROOT

DEFAULT_ROOT = ROOT / 'data' / 'scenarios'
INDEX = ROOT / 'scenarios' / 'index.toml'
EXPECTS = ('stuck', 'passes')
NAME = re.compile(r'[a-z0-9][a-z0-9._-]*')
HEADER = """\
# Stuck scenarios kept from stall captures, one [[scenario]] row each. python -m pokesim.replay capture
# writes a row and rewrites the rows below this comment, so keep notes in the issue.
#
# name          the scenario folder under the private scenarios folder
# rom_sha1      the cartridge it plays
# state_sha256  the save it starts from, unpacked, as a trace names it
# frames        the frame of that save and the frame the stall was noticed at
# expect        stuck while the stall is open, passes once a fix lands
# kind          what noticed the stall: quiet, give_up, loop, gate or ladder
# issue         the issue or pull request
#
# The saves are private and stay out of the repository. The preflight replays every scenario it has a
# save for, and a row that expects stuck is a known failure there.
"""


def private(path):
    """Scenario folders hold private game data, so they stay outside the checkout or under its data/."""
    path = Path(path).resolve()
    return not path.is_relative_to(ROOT) or path.is_relative_to(ROOT / 'data')


def parse_party(values):
    """slot:key=value,key=value, for example 0:status=frozen,hp=12 or all:pp=0."""
    from ..scenarios import STATUS
    changes = []
    for value in values or ():
        slot, _, fields = value.partition(':')
        change = {'slot': 'all' if slot == 'all' else int(slot)}
        for pair in fields.split(','):
            key, _, raw = pair.partition('=')
            if key == 'status':
                if raw not in STATUS:
                    raise SystemExit(f'Unknown status {raw}. Choose from {", ".join(STATUS)}.')
                change[key] = raw
            elif key == 'hp':
                change[key] = float(raw) if '.' in raw else int(raw)
            elif key == 'pp':
                change[key] = int(raw)
            else:
                raise SystemExit(f'Unknown party field {key}. Use status, hp or pp.')
        changes.append(change)
    return changes


def state_sha256(path):
    """The SHA-256 of a save state's bytes, unpacked when it is kept gzipped, as a trace names its start."""
    with open_state(path) as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def source(path):
    """The save a scenario starts from, the bundle's report, and the frames from that save to the notice.

    A bundle starts from its save from before the stall, or from the noticed moment when it has none.
    A plain save is its own window."""
    path = Path(path)
    report, noticed, start = {}, None, path
    if path.is_dir():
        if (path / 'report.json').exists():
            report = json.loads((path / 'report.json').read_text(encoding='utf-8'))
        noticed = path / 'noticed.state'
        start = path / 'before.state' if (path / 'before.state').exists() else noticed
    if not start.with_suffix('.json').exists():
        raise SystemExit(f'{start} has no manifest beside it')
    first = read_manifest(start.with_suffix('.json')).get('frame', 0)
    last = report.get('frame')
    if last is None and noticed is not None and noticed.with_suffix('.json').exists():
        last = read_manifest(noticed.with_suffix('.json')).get('frame')
    return start, report, [first, first if last is None else last]


def rows(index=INDEX):
    """The index's scenario rows, none when it does not exist."""
    index = Path(index)
    return tomllib.loads(index.read_text(encoding='utf-8')).get('scenario', []) if index.exists() else []


def _toml(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return '[' + ', '.join(_toml(item) for item in value) + ']'
    # A JSON string with its escapes is a TOML basic string.
    return json.dumps(str(value), ensure_ascii=False)


def write_index(index, entries):
    """Rewrite the index with ``entries``, keeping the comment above its first row."""
    index = Path(index)
    header = HEADER
    if index.exists():
        text = index.read_text(encoding='utf-8')
        found = re.search(r'^\[\[scenario\]\]', text, re.MULTILINE)
        header = (text[:found.start()] if found else text).rstrip('\n') + '\n'
    body = ''.join('\n[[scenario]]\n' + ''.join(f'{key} = {_toml(value)}\n' for key, value in row.items())
                   for row in entries)
    index.parent.mkdir(parents=True, exist_ok=True)
    CheckpointStore.atomic_write(index, (header + body).encode())


def capture(args):
    if not NAME.fullmatch(args.name):
        raise SystemExit('A scenario name is lower case letters, digits, dots, dashes and underscores, '
                         'such as seafoam-boulders.')
    folder = args.root / args.name
    if not private(folder):
        raise SystemExit('Scenarios contain private game data. Choose a folder outside the checkout or under data/.')
    entries = rows(args.index)
    if any(row.get('name') == args.name for row in entries) and not args.force:
        raise SystemExit(f'{args.name} already has a row in {args.index}. Pass --force to replace it.')
    start, report, frames = source(args.capture)
    folder.mkdir(parents=True, exist_ok=args.force)
    for suffix in ('.state', '.json'):
        shutil.copyfile(start.with_suffix(suffix), folder / f'start{suffix}')
    edits = {}
    if args.party:
        edits['party'] = parse_party(args.party)
    if args.item:
        edits['items'] = {name: int(quantity) for name, _, quantity in (value.partition('=') for value in args.item)}
    if args.money is not None:
        edits['money'] = args.money
    if args.returned:
        edits['returned'] = args.returned
    scenario = {'name': args.name, 'description': args.description, 'checkpoint': 'start.state', 'edits': edits,
                'budget_game_minutes': args.budget, 'max_quiet_game_minutes': args.quiet, 'seed': args.seed}
    if args.until:
        scenario['until'] = args.until
    if args.fallback:
        for suffix in ('.state', '.json'):
            shutil.copyfile(args.fallback.with_suffix(suffix), folder / f'fallback{suffix}')
        scenario['fallback'] = 'fallback.state'
    (folder / 'scenario.json').write_text(json.dumps(scenario, indent=2) + '\n', encoding='utf-8')
    row = {'name': args.name, 'rom_sha1': read_manifest(start.with_suffix('.json')).get('rom_sha1', ''),
           'state_sha256': state_sha256(folder / 'start.state'), 'frames': frames, 'expect': args.expect}
    if report.get('kind'):
        row['kind'] = report['kind']
    if args.issue:
        row['issue'] = args.issue
    write_index(args.index, [entry for entry in entries if entry.get('name') != args.name] + [row])
    print(f'wrote {folder} and its row in {args.index}. python -m pokesim.replay stuck-scenarios show {folder} describes it.')
    return 0


def arguments(parser):
    parser.add_argument('capture', type=Path, help='a stall bundle folder, or a .state file with its manifest')
    parser.add_argument('--name', required=True, help='the scenario name, such as seafoam-boulders')
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('POKESIM_SCENARIOS') or DEFAULT_ROOT),
                        help='the private scenarios folder, by default POKESIM_SCENARIOS or data/scenarios')
    parser.add_argument('--index', type=Path, default=INDEX, help='the tracked index, by default scenarios/index.toml')
    parser.add_argument('--expect', choices=EXPECTS, default='stuck',
                        help='stuck while the stall is open, passes once a fix lands')
    parser.add_argument('--issue', type=lambda value: int(value.lstrip('#')), help='the issue or pull request number')
    parser.add_argument('--description', default='')
    parser.add_argument('--party', action='append', help='slot:status=frozen,hp=12,pp=0 (slot may be all)')
    parser.add_argument('--item', action='append', help='FULL_HEAL=0 removes an item, REVIVE=3 sets its quantity')
    parser.add_argument('--money', type=int)
    parser.add_argument('--returned', type=int, action='append',
                        help='the Pokédex number of a legendary that has come back (Red, Blue and Yellow)')
    parser.add_argument('--until', help='an event type that must happen, such as badge, trainer or champion')
    parser.add_argument('--fallback', type=Path, help='unedited save the second reload goes to, such as league-entry.state')
    parser.add_argument('--budget', type=int, default=240, help='game minutes to play')
    parser.add_argument('--quiet', type=int, default=90, help='game minutes without an achievement that count as stuck')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--force', action='store_true', help='replace an existing scenario and its row')
    parser.set_defaults(action=capture)
