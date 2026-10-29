"""Replay copied checkpoints forward and audit where the frames go.

    replay_audit.py run ROM STATE FRAMES OUT_JSON [--data-root DIR] [--seed N] [--reseed-goals] [--lead-in N]
    replay_audit.py report BEFORE_DIR AFTER_DIR

``run`` plays one checkpoint headless with the checkout's own policy, from the working directory, and
writes the frame share per goal from ``Monitor.shares()``, the stand-downs, and the frames spent in goal
spans that ended without a progress event. Trainee experience counts as progress for a training goal.
Red, Blue and Yellow need POKESIM_GEN1_VARIANT set to match the cartridge, and Gold, Silver and Crystal
need ``--data-root``. AUDIT_PARTNERS lists the trainer ids of linked adventures, comma separated, as the
coordinator's broker would send them. Gold, Silver and Crystal runs list each Pokémon a release visit let go.

Use ``--reseed-goals`` whenever two code versions are compared. Without it a few frames saved early on
shift the game's random numbers, so a later hunt meets its Pokémon sooner or later by luck alone. With it,
each time the audit sees a goal start it reseeds the policy's own generator, restarts the divider register
the game mixes into its rolls, and from then on writes the next number of a seeded stream into the game's
random bytes (hRandomAdd and hRandomSub) at every VBlank. The seed comes from the save name, the goal key
and how many times that goal started before, so the same goal on the same save meets the same rolls frame
for frame in both versions. Rolls still differ once the two policies act differently, and an encounter
at another frame meets another roll. ``--lead-in`` idles that many frames
before the policy starts, which fakes a timing change for checking how well the seeds hold. Both options
exist only in this tool, so the application never reseeds a game.

``report`` adds up the runs in two folders per game and goal and prints them side by side. A goal is
flagged when its share or its wasted share grows by more than two points, or when it takes more than
15% of a game's frames. A hunt gets one row per hunt kind and target, such as ``collection_hunt quality
Larvitar`` or ``collection_hunt shiny``, and a training goal one row per trainee, since one goal key
covers many hunts or trainees. Run files written before these rows existed keep each such goal in one
row marked ``(all)``.

The headless runner has no reload watchdog, so a stall here is a stand-down. Screen recoveries are
counted on their own.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.getcwd())

from pokesim.planning.monitor import Monitor, ProgressEvent  # noqa: E402
from pokesim.planning.progress import _held, events  # noqa: E402

LIMIT_POINTS = 2.0
LARGE_SHARE = 0.15
# hRandomAdd and hRandomSub in pret/pokered, which Yellow keeps. Gold, Silver and Crystal read theirs from the symbols.
GEN1_RANDOM = (0xFFD3, 0xFFD4)
DIVIDER = 0xFF04  # Any write restarts the divider at zero.
VBLANK = 0x0040  # The VBlank interrupt vector, the same in all six games.
HUNTS = frozenset({'collection_hunt', 'collection_fish', 'collection_field', 'collect_hunt'})
TRAINING = frozenset({'collection_train', 'collect_train'})
# The reason a Red, Blue or Yellow hunt gives for its trip, and the hunt kind it stands for.
GEN1_PURPOSES = {'a partner another adventure needs': 'partner', 'more chances to find high DV partners': 'quality',
                 'another partner for the collection': 'repeat', 'a missing Pokédex entry': 'completion'}
ALL_TARGETS = 'every target, the run file predates split rows'


def describe(goal):
    """A goal's description: the Gold, Silver or Crystal label, or the Red, Blue or Yellow title and reason."""
    if goal is None:
        return ''
    label = getattr(goal, 'label', None)
    if label is not None:
        return label
    title, reason = getattr(goal, 'title', ''), getattr(goal, 'reason', '')
    return f'{title}. {reason}' if title and reason else title or reason


def _hunt(description):
    """The hunt kind, its target and a title without the place, or None for a description it cannot read."""
    if re.fullmatch(r'Search for a shiny in .+', description):
        return 'shiny', None, 'Search for a shiny'
    if match := re.fullmatch(r'Search for a stronger (.+?) in .+', description):
        return 'quality', match[1], f'Search for a stronger {match[1]}'
    if match := re.fullmatch(r'Search for (.+?)( holding .+?)? in .+', description):
        return ('item' if match[2] else 'completion'), match[1], f'Search for {match[1]}{match[2] or ""}'
    if match := re.fullmatch(r'Find (.+?)\. Search .+? for (.+)', description):
        kind = GEN1_PURPOSES.get(match[2], 'other')
        return kind, match[1], f'Find {match[1]} for {match[2]}'
    return None


def row(key, description):
    """The report row of a goal and its title. Hunts split by kind and target, training by trainee."""
    if key in HUNTS and (hunt := _hunt(description)):
        kind, target, title = hunt
        return ' '.join(part for part in (key, kind, target) if part), title
    if key in TRAINING and (match := re.match(r'Train (.+?) (?:toward|to) ', description)):
        return f'{key} {match[1]}', f'Train {match[1]}'
    return key, description


def _partners(run):
    # AUDIT_PARTNERS lists the linked adventures' trainer ids, as the coordinator's broker would send them.
    ids = frozenset(int(value) for value in os.environ.get('AUDIT_PARTNERS', '').split(',') if value.strip())
    if ids:
        run.policy.trade_partners = lambda: ids
    return run


def _open(rom, state, data_root, seed):
    if rom.suffix == '.gbc':
        from pokesim.gen2.headless import HeadlessRun
        run = _partners(HeadlessRun(rom, state, seed=seed, data_root=Path(data_root) if data_root else None))
        return run, run.read, run.game
    from pokesim.headless import HeadlessRun
    from pokesim.ram import read_snapshot
    run = _partners(HeadlessRun(rom, state, seed=seed, reseed=True))
    return run, lambda: read_snapshot(run.pb.memory, run.frame), run.policy.collection.version


def random_bytes(run):
    """The addresses of hRandomAdd and hRandomSub for the run's cartridge."""
    if run.generation == 2:
        return tuple(run.data.symbols[name][1] for name in ('hRandomAdd', 'hRandomSub'))
    return GEN1_RANDOM


class GoalSeeds:
    """Give every goal start on one save the same random numbers in every code version.

    A goal start picks a stream of seeds, and every VBlank interrupt after it writes the one for that
    frame into the game's random bytes before the game's own update adds the divider to them. A single write at
    the goal start is not enough. The divider read inside each update lands a few cycles apart when
    the music or the people on screen differ, so the two games would drift one apart now and then and
    stay apart for the rest of the goal. Writing each frame keeps any such difference inside one frame.
    """

    def __init__(self, save):
        self.save = save
        self.starts = Counter()
        self.stream = None
        self.hooked = None

    def seed(self, key, occurrence):
        return hashlib.sha256(f'{self.save}\n{key}\n{occurrence}'.encode()).digest()

    def start(self, run, key):
        """Reseed the policy now and the game from its next VBlank on, for the next start of ``key``."""
        digest = self.seed(key, self.starts[key])
        self.starts[key] += 1
        run.policy.rng.seed(int.from_bytes(digest[:8], 'big'))
        self.stream = digest, run.pb.frame_count
        if self.hooked is not run:
            run.pb.hook_register(0, VBLANK, self._write, run)
            self.hooked = run
        run.pb.memory[DIVIDER] = 0

    def _write(self, run):
        # The number follows the frames since the goal start, so a frame with the screen off and no
        # interrupt does not shift every number after it.
        digest, started = self.stream
        frame = (run.pb.frame_count - started).to_bytes(8, 'big', signed=True)
        memory = run.pb.memory
        for address, value in zip(random_bytes(run), hashlib.blake2b(digest + frame, digest_size=2).digest()):
            memory[address] = value


def idle(run, frames):
    if frames <= 0:
        return
    if run.generation == 2:
        run.tick(frames)
    else:
        run.pb.tick(frames, render=False)
        run.frame += frames


def _stand_downs(run, seen):
    """Stand-downs since the last call, as goal keys. ``seen`` carries what was already counted."""
    collection = run.policy.collection
    if run.generation == 2:
        stood = dict(collection.get('stood_down') or {})
        found = [key for key, when in stood.items() if seen.get(key) != when]
        seen.clear()
        seen.update(stood)
        return found
    outcomes = collection.director.outcomes
    last = outcomes[-1] if outcomes else None
    if last is None or seen.get('last') is last:
        return []
    seen['last'] = last
    return [last['key']] if last['status'] == 'deferred' else []


def _goal_events(key, previous, current):
    """The progress events of ``current`` for goal ``key``. A training goal also progresses on experience,
    since a level can take many battles and a span that gained experience was not wasted."""
    found = events(previous, current)
    # A Pokémon let go frees a slot. The tree under test may predate that event, so the audit reads it
    # here too and every tree it compares is measured the same way.
    if found == [] and previous is not None and current is not None and getattr(current, 'valid', True) \
            and getattr(previous, 'valid', True) and _held(current) < _held(previous):
        found.append(ProgressEvent('room', _held(previous) - _held(current)))
    if 'train' in key and previous is not None and current is not None and not found:
        gained = sum(after.experience - before.experience for before, after in zip(previous.party, current.party)
                     if before.species == after.species and after.experience > before.experience)
        if gained:
            found.append(ProgressEvent('experience', gained))
    return found


def _levels(snapshot):
    """Species and level of each party member, so a report can tell training that gains from training that idles."""
    return [[mon.species, mon.level] for mon in getattr(snapshot, 'party', ()) if not getattr(mon, 'egg', False)]


def _released(previous, current, frame):
    """Pokémon a Gen II release visit let go between two reads.

    A withdrawal shows the copy in the party one read before it leaves the box, so this compares sets of
    Pokémon by species, trainer and DVs, and reads the held item from the copy that left.
    """
    if len(current.stored) >= len(previous.stored):
        return []
    ident = lambda m: (m.species, m.dvs, m.trainer_id)  # noqa: E731
    now = {ident(m) for m in current.stored + current.party if not m.egg}
    before = {ident(m): m.held_item for m in previous.stored + previous.party if not m.egg}
    return [{'species': species, 'trainer_id': trainer, 'item': item, 'frame': frame}
            for (species, _dvs, trainer), item in before.items() if (species, _dvs, trainer) not in now]


def run_one(args):
    run, read, game = _open(Path(args.rom), Path(args.state), args.data_root, args.seed)
    idle(run, args.lead_in)
    seeds = GoalSeeds(Path(args.state).name) if args.reseed_goals else None
    monitor = Monitor()
    start = run.frame
    titles, spans, wasted = {}, Counter(), Counter()
    stand_downs, seen = [], {}
    _stand_downs(run, seen)
    errors = 0
    recoveries = getattr(run.policy, 'recoveries', 0)
    snapshot = read()
    party = [_levels(snapshot)]
    span = None  # [row, frames, progressed]
    seeded = None  # The goal key the last reseed was for. Seeds follow goal keys, not rows.
    released = []
    # The shadow arbiter's picks, read only (planner design S3): frames by the kind it would have chosen.
    shadow = getattr(run.policy, 'shadow', None)
    would = Counter()
    while run.frame - start < args.frames:
        before = run.frame
        try:
            run.step(snapshot)
        except Exception as error:  # Count it and go on, as the managed loop does.
            errors += 1
            if errors > 50:
                print('too many errors', repr(error), file=sys.stderr)
                break
            idle(run, 60)
        try:
            current = read()
        except Exception:  # A snapshot read can fail mid transition. The next one counts.
            current = None
        goal = run.policy.goal
        key = goal.key if goal is not None else 'none'
        line, title = row(key, describe(goal))
        titles.setdefault(line, title)
        found = _goal_events(key, snapshot, current)
        if span is None or span[0] != line:
            if span is not None:
                spans[span[0]] += 1
                if not span[2]:
                    wasted[span[0]] += span[1]
            monitor.start(line)
            span = [line, 0, False]
        if seeds is not None and seeded != key:
            seeds.start(run, key)
        seeded = key
        spent = run.frame - before
        monitor.observe(line, spent, found)
        span[1] += spent
        span[2] = span[2] or bool(found)
        if shadow is not None:
            would[shadow.pick or 'none'] += spent
        for stood in _stand_downs(run, seen):
            stand_downs.append({'key': stood, 'goal': line, 'frame': run.frame})
        if current is not None and run.generation == 2 and key == 'collection_release':
            released += _released(snapshot, current, run.frame)
        if current is not None:
            snapshot = current
    run.stop()
    party.append(_levels(snapshot))
    frames = dict(monitor.frames)
    result = {
        'state': str(args.state), 'game': game, 'frames': sum(frames.values()), 'errors': errors,
        'shares': monitor.shares(), 'frames_by_goal': frames, 'titles': titles,
        'spans': dict(spans), 'wasted': dict(wasted), 'open_span': span,
        'stand_downs': stand_downs, 'reloads': 0, 'party_levels': party,
        'recoveries': getattr(run.policy, 'recoveries', 0) - recoveries,
        'released': released, 'reseed_goals': bool(seeds), 'lead_in': args.lead_in, 'rows': True,
    }
    if shadow is not None:
        result['shadow'] = {**shadow.summary(), 'frames_by_pick': dict(would)}
    Path(args.out).write_text(json.dumps(result, indent=1), encoding='utf-8')


def load(folder):
    """Totals per game: frames, frames per goal, wasted per goal and stand-downs per goal."""
    games = defaultdict(lambda: {'frames': 0, 'goals': Counter(), 'wasted': Counter(), 'stalls': Counter(),
                                 'titles': {}, 'runs': 0, 'errors': 0, 'recoveries': 0})
    for path in sorted(Path(folder).glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        name = _older if not data.get('rows') else lambda key: key
        game = games[data['game']]
        game['runs'] += 1
        game['frames'] += data['frames']
        game['errors'] += data['errors']
        game['recoveries'] += data['recoveries']
        game['goals'].update({name(key): value for key, value in data['frames_by_goal'].items()})
        game['wasted'].update({name(key): value for key, value in data['wasted'].items()})
        for key, title in data['titles'].items():
            game['titles'].setdefault(name(key), ALL_TARGETS if name(key) != key else title)
        game['stalls'].update(name(entry['goal']) for entry in data['stand_downs'])
        game['stalls']['(reloads)'] += data.get('reloads', 0)
        # Run files from before shadow mode have no shadow section.
        for field, counts in data.get('shadow', {}).items():
            if isinstance(counts, dict):
                game.setdefault('shadow', defaultdict(Counter))[field].update(counts)
    return games


def shadow_lines(game):
    """The shadow arbiter's agreement per point, frame share by would-have-chosen kind, difference
    counts and top three disagreements per point, or no lines for a game without shadow data."""
    shadow = game.get('shadow') if game else None
    if not shadow:
        return []
    lines = ['| point | decisions | agreed |', '|---|---|---|']
    for point, count in sorted(shadow['decisions'].items()):
        agreed = shadow['agreed'][point]
        lines.append(f'| {point} | {count} | {100 * agreed / max(count, 1):.1f}% |')
    total = sum(shadow['frames_by_pick'].values())
    shares = ', '.join(f'{kind} {100 * frames / max(total, 1):.1f}%'
                       for kind, frames in shadow['frames_by_pick'].most_common(8))
    lines.append(f'would have chosen: {shares or "none"}')
    differences = ', '.join(f'{key} {count}' for key, count in sorted(shadow['differences'].items()))
    lines.append(f'differences: {differences or "none"}')
    for point in sorted(shadow['decisions']):
        top = [(key, count) for key, count in shadow['disagreements'].most_common() if key.startswith(f'{point}: ')][:3]
        if top:
            lines.append(f'top {point} disagreements: ' + ', '.join(f'{key[len(point) + 2:]} {count}' for key, count in top))
    return lines


def _older(key):
    """The row of a goal key in a run file from before split rows, which kept all hunts or trainees together."""
    return f'{key} (all)' if key in HUNTS | TRAINING else key


def _row(game, key):
    if not game or not game['frames']:
        return 0.0, 0, 0.0
    frames = game['frames']
    return 100 * game['goals'][key] / frames, game['stalls'][key], 100 * game['wasted'][key] / frames


def report(args):
    before, after = load(args.before), load(args.after)
    flags = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        keys = set()
        for game in (old, new):
            if game:
                keys |= {key for key, value in game['goals'].items() if value >= 0.01 * game['frames']}
                keys |= {key for key in game['stalls'] if game['stalls'][key]}
        print(f'\n## {name}')
        for label, game in (('before', old), ('after', new)):
            if game:
                stalls = sum(game['stalls'].values())
                wasted = 100 * sum(game['wasted'].values()) / max(game['frames'], 1)
                print(f'{label}: {game["runs"]} runs, {game["frames"]} frames, {stalls} stalls, {wasted:.1f}% wasted, '
                      f'{game["errors"]} errors, {game["recoveries"]} recoveries')
        print('| goal | share before | share after | stalls before | stalls after | wasted before | wasted after |')
        print('|---|---|---|---|---|---|---|')
        rank = new or old
        for key in sorted(keys, key=lambda k: -rank['goals'][k]):
            share0, stalls0, waste0 = _row(old, key)
            share1, stalls1, waste1 = _row(new, key)
            title = (new or old)['titles'].get(key) or (old or new)['titles'].get(key) or ''
            print(f'| {key} {title} | {share0:.1f} | {share1:.1f} | {stalls0} | {stalls1} | {waste0:.1f} | {waste1:.1f} |')
            if share1 - share0 > LIMIT_POINTS or waste1 - waste0 > LIMIT_POINTS:
                flags.append(f'{name} {key}: share {share0:.1f} to {share1:.1f}, wasted {waste0:.1f} to {waste1:.1f}')
            if share1 > 100 * LARGE_SHARE:
                flags.append(f'{name} {key}: {share1:.1f}% of frames ({title})')
        lines = shadow_lines(new)
        if lines:
            print('\n### Shadow arbiter (after)')
            print('\n'.join(lines))
    print('\n## Flags')
    for line in flags or ['none']:
        print('-', line)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('run')
    one.add_argument('rom')
    one.add_argument('state')
    one.add_argument('frames', type=int)
    one.add_argument('out')
    one.add_argument('--data-root')
    one.add_argument('--seed', type=int, default=7)
    one.add_argument('--reseed-goals', action='store_true',
                     help='seed the game random numbers at each goal start, for comparing code versions')
    one.add_argument('--lead-in', type=int, default=0, help='frames to idle before the policy starts')
    both = commands.add_parser('report')
    both.add_argument('before')
    both.add_argument('after')
    args = parser.parse_args(argv)
    run_one(args) if args.command == 'run' else report(args)


if __name__ == '__main__':
    main()
