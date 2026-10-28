"""Replay copied checkpoints forward and audit where the frames go.

    replay_audit.py run ROM STATE FRAMES OUT_JSON [--data-root DIR] [--seed N]
    replay_audit.py report BEFORE_DIR AFTER_DIR

``run`` plays one checkpoint headless with the checkout's own policy, from the working directory, and
writes the frame share per goal from ``Monitor.shares()``, the stand-downs, and the frames spent in goal
spans that ended without a progress event. Trainee experience counts as progress for a training goal. Red, Blue and Yellow need POKESIM_GEN1_VARIANT set to match
the cartridge, and Gold, Silver and Crystal need ``--data-root``.

``report`` adds up the runs in two folders per game and goal and prints them side by side. A goal is
flagged when its share or its wasted share grows by more than two points, or when it takes more than
15% of a game's frames.

The headless runner has no reload watchdog, so a stall here is a stand-down. Screen recoveries are
counted on their own.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.getcwd())

from pokesim.planning.monitor import Monitor, ProgressEvent  # noqa: E402
from pokesim.planning.progress import _held, events  # noqa: E402

LIMIT_POINTS = 2.0
LARGE_SHARE = 0.15


def _open(rom, state, data_root, seed):
    if rom.suffix == '.gbc':
        from pokesim.gen2.headless import HeadlessRun
        run = HeadlessRun(rom, state, seed=seed, data_root=Path(data_root) if data_root else None)
        return run, run.read, run.game
    from pokesim.headless import HeadlessRun
    from pokesim.ram import read_snapshot
    run = HeadlessRun(rom, state, seed=seed, reseed=True)
    return run, lambda: read_snapshot(run.pb.memory, run.frame), run.policy.collection.version


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


def run_one(args):
    run, read, game = _open(Path(args.rom), Path(args.state), args.data_root, args.seed)
    monitor = Monitor()
    start = run.frame
    titles, spans, wasted = {}, Counter(), Counter()
    stand_downs, seen = [], {}
    _stand_downs(run, seen)
    errors = 0
    recoveries = getattr(run.policy, 'recoveries', 0)
    snapshot = read()
    party = [_levels(snapshot)]
    span = None  # [key, frames, progressed]
    while run.frame - start < args.frames:
        before = run.frame
        try:
            run.step(snapshot)
        except Exception as error:  # Count it and go on, as the managed loop does.
            errors += 1
            if errors > 50:
                print('too many errors', repr(error), file=sys.stderr)
                break
            if run.generation == 2:
                run.tick(60)
            else:
                run.pb.tick(60, render=False)
                run.frame += 60
        try:
            current = read()
        except Exception:  # A snapshot read can fail mid transition. The next one counts.
            current = None
        goal = run.policy.goal
        key = goal.key if goal is not None else 'none'
        titles.setdefault(key, getattr(goal, 'label', '') if goal is not None else '')
        found = _goal_events(key, snapshot, current)
        if span is None or span[0] != key:
            if span is not None:
                spans[span[0]] += 1
                if not span[2]:
                    wasted[span[0]] += span[1]
            monitor.start(key)
            span = [key, 0, False]
        spent = run.frame - before
        monitor.observe(key, spent, found)
        span[1] += spent
        span[2] = span[2] or bool(found)
        for stood in _stand_downs(run, seen):
            stand_downs.append({'key': stood, 'goal': key, 'frame': run.frame})
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
    }
    Path(args.out).write_text(json.dumps(result, indent=1), encoding='utf-8')


def load(folder):
    """Totals per game: frames, frames per goal, wasted per goal and stand-downs per goal."""
    games = defaultdict(lambda: {'frames': 0, 'goals': Counter(), 'wasted': Counter(), 'stalls': Counter(),
                                 'titles': {}, 'runs': 0, 'errors': 0, 'recoveries': 0})
    for path in sorted(Path(folder).glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        game = games[data['game']]
        game['runs'] += 1
        game['frames'] += data['frames']
        game['errors'] += data['errors']
        game['recoveries'] += data['recoveries']
        game['goals'].update(data['frames_by_goal'])
        game['wasted'].update(data['wasted'])
        game['titles'].update(data['titles'])
        game['stalls'].update(entry['goal'] for entry in data['stand_downs'])
        game['stalls']['(reloads)'] += data.get('reloads', 0)
    return games


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
    both = commands.add_parser('report')
    both.add_argument('before')
    both.add_argument('after')
    args = parser.parse_args(argv)
    run_one(args) if args.command == 'run' else report(args)


if __name__ == '__main__':
    main()
