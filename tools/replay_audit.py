"""Replay copied checkpoints forward and audit where the frames go.

    replay_audit.py run ROM STATE FRAMES OUT_JSON [--data-root DIR] [--seed N] [--reseed-goals] [--lead-in N]
                        [--randomizer CODE] [--fair-wild-dvs [KEY]]
    replay_audit.py report BEFORE_DIR AFTER_DIR

``run`` plays one checkpoint headless with the checkout's own policy, from the working directory, and
writes the frame share per goal from ``Monitor.shares()``, the stand-downs, and the frames spent in goal
spans that ended without a progress event. The runner is ``pokesim.replay.rung.run_one``, so the working
directory must be a checkout that has it. ``python -m pokesim.replay record`` plays a ladder rung at any
older commit. Battle experience counts as progress for any goal, a heal that
restores HP, status or PP counts for the heal, and a PC visit that brings the trainee into the party counts
for its preparation.
Red, Blue and Yellow need POKESIM_GEN1_VARIANT set to match the cartridge, and Gold, Silver and Crystal
need ``--data-root``. ``--randomizer`` takes a share code such as ``PSR1-RED-WS-12345`` and plays the
save on that randomized cartridge, as a randomized adventure's worker does. The code must be for the
cartridge's own game, and the run file records it. ``--fair-wild-dvs`` plays a Red, Blue or Yellow save
with Fair wild DVs on, as an adventure with that setting does. Its rerolls are keyed by the seed, or by
KEY, the hex seed under ``fair-wild-dvs-v1`` in an adventure's store, which replays that adventure's own
encounters. AUDIT_PARTNERS lists the trainer ids of linked adventures, comma separated, as the
coordinator's broker would send them. Gold, Silver and Crystal runs list each Pokémon a release visit let go.

Use ``--reseed-goals`` whenever two code versions are compared. Without it a few frames saved early on
shift the game's random numbers, so a later hunt meets its Pokémon sooner or later by luck alone. With it,
each time the audit sees a goal start it reseeds the policy's own generator, restarts the divider register
the game mixes into its rolls, and from then on writes the next number of a seeded stream into the game's
random bytes (hRandomAdd and hRandomSub) at every VBlank. The seed comes from the save name, ``--seed``,
the goal key and how many times that goal started before, so the same goal on the same save and seed meets
the same rolls frame for frame in both versions, and another ``--seed`` meets other rolls. Rolls still differ once the two policies act differently, and an encounter
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
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.getcwd())

# The policy modules load inside ``run_one``, after ``--randomizer`` has set the worker's environment.
# Gen I modules read their tables at import time.
from pokesim.replay.rung import HUNTS, TRAINING, run_one

LIMIT_POINTS = 2.0
LARGE_SHARE = 0.15
ALL_TARGETS = 'every target, the run file predates split rows'


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
        # Run files from before --randomizer played clean cartridges.
        game.setdefault('randomizers', set()).add(data.get('randomizer') or 'off')
        game['goals'].update({name(key): value for key, value in data['frames_by_goal'].items()})
        game['wasted'].update({name(key): value for key, value in data['wasted'].items()})
        for key, title in data['titles'].items():
            game['titles'].setdefault(name(key), ALL_TARGETS if name(key) != key else title)
        game['stalls'].update(name(entry['goal']) for entry in data['stand_downs'])
        game['stalls']['(reloads)'] += data.get('reloads', 0)
        # Run files from before the battle stance count no run attempts.
        for key, counts in data.get('flees', {}).items():
            game.setdefault('flees', defaultdict(Counter))[name(key)].update(counts)
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


def flee_lines(old, new):
    """Run attempts, failed runs and wasted share for each row where the battle stance ran."""
    rows = sorted({key for game in (old, new) if game for key in game.get('flees', {})})
    if not rows:
        return []
    lines = ['| goal | attempts | failures | wasted before | wasted after |', '|---|---|---|---|---|']
    for key in rows:
        counts = (new or {}).get('flees', {}).get(key, Counter())
        lines.append(f'| {key} | {counts["attempts"]} | {counts["failures"]} | '
                     f'{_row(old, key)[2]:.1f} | {_row(new, key)[2]:.1f} |')
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
                      f'{game["errors"]} errors, {game["recoveries"]} recoveries, '
                      f'randomizer {", ".join(sorted(game["randomizers"]))}')
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
        lines = flee_lines(old, new)
        if lines:
            print('\n### Battle stance runs')
            print('\n'.join(lines))
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
    one.add_argument('--randomizer', default='', help='share code of a randomized run, such as PSR1-RED-WS-12345')
    one.add_argument('--fair-wild-dvs', nargs='?', const=True, type=bytes.fromhex, metavar='KEY',
                     help='play Fair wild DVs, keyed by the seed or by an adventure\'s hex key')
    both = commands.add_parser('report')
    both.add_argument('before')
    both.add_argument('after')
    args = parser.parse_args(argv)
    run_one(args) if args.command == 'run' else report(args)


if __name__ == '__main__':
    main()
