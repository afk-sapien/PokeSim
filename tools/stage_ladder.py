"""Keep a ladder of saves, one per stage of the game, for replaying every stage after a change.

  snapshot  play one fresh game headless and keep a save the first time it reaches each rung
  adopt     keep an existing checkpoint as a rung, so a covered stage needs no fresh run
  show      list the rungs a ladder folder holds and the ones it still lacks

Rungs, in order. Every game has new_game, badges_2, badges_4, badges_6, badges_8, league_first (the
Elite Four's first room before any Hall of Fame) and post_game. Gold, Silver and Crystal count Johto
badges for the badge rungs and add champion_first (back in the world after the first Hall of Fame),
kanto_entry (off the S.S. Aqua in Vermilion), red (first arrival outside Mt. Silver before Red is
beaten) and post_game after Red. A randomized ladder keeps new_game, badges_4, badges_8 and league_first.

Each rung is a scenario folder (scenario.json, start.state, start.json) under LADDER/<rung>, written
compressed, so tools/stuck_scenarios.py and the ladder batch replay it. LADDER/ladder.json names the
game and the share code of a randomized ladder. A rung already present is kept unless --refresh names it.

``snapshot`` plays as the headless runners do and watches for stalls the way the scenarios do: nothing
achieved for --quiet game minutes, or one goal standing down more than three times in a row. Each stall
keeps a bundle (before.state, noticed.state, report.json) under LADDER/stalls and the run goes back to
the save from before it, as the application reloads. A run gives up after --max-stalls stalls. Its
report, LADDER/snapshot-report.json, lists the game minute each rung was reached, every stall and the
errors the policy raised.

Red, Blue and Yellow pick their game data from the cartridge, so no POKESIM_GEN1_VARIANT is needed.
Gold, Silver and Crystal need --data-root or GEN2_DATA_DIR. Ladder folders hold private game data and
must stay outside the checkout or under data/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Policy modules load in ``prepare``, after the cartridge has set the Gen I variant and the randomizer.

GEN1_RUNGS = ('new_game', 'badges_2', 'badges_4', 'badges_6', 'badges_8', 'league_first', 'post_game')
GEN2_RUNGS = ('new_game', 'badges_2', 'badges_4', 'badges_6', 'badges_8', 'league_first', 'champion_first',
              'kanto_entry', 'red', 'post_game')
RANDOMIZED_RUNGS = ('new_game', 'badges_4', 'badges_8', 'league_first')
# Lorelei's room. Every Gen I map from Victory Road to the Hall of Fame, where a post-game save would
# still be part of a League run.
GEN1_LORELEI = 0xF5
GEN1_LEAGUE = frozenset({0x6C, 0xC2, 0xC6, 0xAE, 0xF5, 0xF6, 0xF7, 0x71, 0x78, 0x76})
GEN2_LEAGUE = frozenset({'WILLS_ROOM', 'KOGAS_ROOM', 'BRUNOS_ROOM', 'KARENS_ROOM', 'LANCES_ROOM', 'HALL_OF_FAME'})
# Saves the run keeps while it plays, for a stall's before.state and the reload after it.
ROLLING_GAME_MINUTES = 10
REPLAY_GAME_MINUTES = 120
REPLAY_QUIET_MINUTES = 90


def private(path):
    path = path.resolve()
    return not path.is_relative_to(ROOT) or path.is_relative_to(ROOT / 'data')


def prepare(rom, code):
    """Set the environment the policy modules read at import and return (cartridge, share code)."""
    from pokesim.cartridges import identify
    cartridge = identify(Path(rom).read_bytes())
    if cartridge is None:
        raise SystemExit(f'{rom} is not a verified cartridge')
    if cartridge.generation == 1:
        from pokesim.game_data import VARIANT_ENV
        wanted = 'yellow' if cartridge.version == 'yellow' else 'red'
        if os.environ.get(VARIANT_ENV, wanted) != wanted or 'pokesim.policies' in sys.modules:
            raise SystemExit(f'{cartridge.version} needs {VARIANT_ENV}={wanted}')
        os.environ[VARIANT_ENV] = wanted
    if code:
        from pokesim.randomized import ENV, validate
        code = validate(code, cartridge.version)
        os.environ[ENV] = code
        os.environ['ROM_PATH'] = str(Path(rom).resolve())
    return cartridge, code or ''


def rungs_for(generation, randomized):
    if randomized:
        return RANDOMIZED_RUNGS
    return GEN2_RUNGS if generation == 2 else GEN1_RUNGS


def reached(generation, snapshot, completed):
    """The rungs this moment counts for, ignoring whether they were kept already."""
    found = {'new_game'}
    if generation == 2:
        badges = (snapshot.badges & 0xFF).bit_count()
        constant = snapshot.data.maps.get(snapshot.map, {}).get('constant', '')
        league = constant in GEN2_LEAGUE
        if constant == 'WILLS_ROOM' and not snapshot.hall_of_fame_count:
            found.add('league_first')
        if snapshot.hall_of_fame_count and not league and 'red' not in completed:
            found.add('champion_first')
        if 'kanto' in completed and 'red' not in completed:
            found.add('kanto_entry')
        if constant == 'SILVER_CAVE_OUTSIDE' and 'red' not in completed:
            found.add('red')
        if 'red' in completed and not league:
            found.add('post_game')
    else:
        badges = snapshot.badges.bit_count()
        if snapshot.map == GEN1_LORELEI and not snapshot.hall_of_fame_count:
            found.add('league_first')
        if snapshot.hall_of_fame_count and snapshot.map not in GEN1_LEAGUE:
            found.add('post_game')
    found.update(f'badges_{count}' for count in (2, 4, 6, 8) if badges >= count)
    return found


def settled(run, snapshot):
    """Whether a save now would replay from the overworld rather than inside a battle or a menu."""
    if not snapshot.valid or snapshot.in_battle:
        return False
    if run.generation == 2:
        return snapshot.started and run.policy.menu is None and not getattr(run.policy, 'backing_out', False)
    return not snapshot.textbox and not snapshot.start_menu


def keep_rung(run, folder, ladder, rung, game_minutes):
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    run.save(folder / 'start.state', compress=True)
    scenario = {'name': f'ladder-{ladder}-{rung}', 'description': f'Stage ladder {ladder}: {rung.replace("_", " ")}',
                'checkpoint': 'start.state', 'edits': {}, 'budget_game_minutes': REPLAY_GAME_MINUTES,
                'max_quiet_game_minutes': REPLAY_QUIET_MINUTES, 'seed': 7}
    (folder / 'scenario.json').write_text(json.dumps(scenario, indent=2) + '\n', encoding='utf-8')
    return {'rung': rung, 'game_minute': game_minutes}


def write_ladder(folder, cartridge, code):
    path = folder / 'ladder.json'
    info = {'game': cartridge.version, 'generation': cartridge.generation, 'rom_sha1': cartridge.sha1,
            'randomizer': code}
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if {key: existing.get(key) for key in info} != info:
            raise SystemExit(f'{folder} holds a different ladder: {existing}')
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')


def open_fresh(rom, generation, seed, data_root):
    if generation == 2:
        from pokesim.gen2.headless import HeadlessRun
        from pokesim.scenarios import Gen2Watch, gen2_data_root
        run = HeadlessRun(rom, None, seed=seed, rng=random.Random(seed), data_root=data_root or gen2_data_root())
        return run, Gen2Watch(run), run.read
    from pokesim.headless import HeadlessRun
    from pokesim.ram import read_snapshot
    from pokesim.scenarios import Gen1Watch
    run = HeadlessRun(rom, seed=seed, rng=random.Random(seed))
    return run, Gen1Watch(run), lambda: read_snapshot(run.pb.memory, run.frame)


def snapshot(args):
    folder = args.ladder
    if not private(folder):
        raise SystemExit('Ladders contain private game data. Choose a folder outside the checkout or under data/.')
    cartridge, code = prepare(args.rom, args.randomizer)
    write_ladder(folder, cartridge, code)
    from pokesim.stalls import FRAMES_PER_GAME_MINUTE as MINUTE
    wanted = list(rungs_for(cartridge.generation, bool(code)))
    refresh = set(args.refresh or ())
    unknown = refresh - set(wanted)
    if unknown:
        raise SystemExit(f'Unknown rung {", ".join(sorted(unknown))}. This ladder has {", ".join(wanted)}.')
    missing = [rung for rung in wanted if rung in refresh or not (folder / rung / 'start.state').exists()]
    report = {'ladder': folder.name, 'game': cartridge.version, 'randomizer': code, 'seed': args.seed,
              'commit': _commit(), 'wanted': missing, 'kept': [], 'stalls': [], 'battle_reloads': 0, 'errors': 0, 'error_samples': [],
              'game_minutes': 0, 'wall_seconds': 0, 'finished': False}
    if not missing:
        print(f'{folder.name}: every rung is kept already')
        return 0
    run, watch, read = open_fresh(Path(args.rom), cartridge.generation, args.seed, args.data_root)
    work = folder / '.work'
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    rolling = []  # (frame, path) of the saves kept while playing, oldest first.
    began = time.monotonic()
    end = args.game_hours * 60 * MINUTE
    progress_frame, last_rolling = run.frame, None
    battle_frame = None
    stall_count = reloads = 0
    try:
        snap = read()
        while run.frame < end and missing:
            completed = getattr(run.policy, 'completed', {}) or {}
            if settled(run, snap):
                for rung in [rung for rung in missing if rung in reached(cartridge.generation, snap, completed)]:
                    report['kept'].append(keep_rung(run, folder / rung, folder.name, rung, run.frame // MINUTE))
                    missing.remove(rung)
                    print(f'{folder.name}: {rung} at game minute {run.frame // MINUTE}', flush=True)
                # The first settled moment is saved at once, so even an early stall has a save to go back to.
                if last_rolling is None or run.frame - last_rolling >= ROLLING_GAME_MINUTES * MINUTE:
                    path = work / f'rolling-{run.frame}.state'
                    run.save(path, compress=True)
                    rolling.append((run.frame, path))
                    last_rolling = run.frame
                    _prune(rolling, progress_frame)
            gained, earned = watch.observe(snap)
            if gained or earned or cartridge.generation == 2 and snap.started and run.waiting(snap):
                progress_frame = run.frame
                if gained or earned:
                    reloads = 0
            marks = watch.marks(snap)
            battle_frame = watch.battle_clock(snap, battle_frame, run.frame)
            quiet = run.frame - progress_frame >= args.quiet * MINUTE
            hung = battle_frame is not None and run.frame - battle_frame >= args.battle_minutes * MINUTE
            if quiet or hung or watch.loop:
                before = _before(rolling, progress_frame)
                if hung and not quiet and not watch.loop:
                    # The application reloads a save from before a battle that never ends. Only a battle
                    # that keeps coming back is a stall.
                    report['battle_reloads'] += 1
                    reloads += 1
                    hung = reloads > args.max_battle_reloads
                if quiet or hung or watch.loop:
                    reason = (f'a retry loop: {watch.loop}' if watch.loop else
                              f'nothing achieved for {args.quiet} game minutes' if quiet else
                              f'a battle could not end after {args.max_battle_reloads} reloads')
                    stall_count += 1
                    report['stalls'].append(_bundle(run, snap, folder, before, reason, missing, run.frame // MINUTE,
                                                    marks))
                    print(f'{folder.name}: stall {stall_count} at game minute {run.frame // MINUTE}: {reason}',
                          flush=True)
                    reloads = 0
                if stall_count >= args.max_stalls or before is None:
                    report['gave_up'] = 'too many stalls' if before is not None else 'a stall with no save before it'
                    break
                run.reload(before[1])
                watch.reset()
                battle_frame = None
                progress_frame = last_rolling = run.frame
                snap = read()
                continue
            try:
                run.step(snap)
            except Exception as error:  # noqa: BLE001  count it and go on, as the managed loop does
                report['errors'] += 1
                if len(report['error_samples']) < 5:
                    report['error_samples'].append({'game_minute': run.frame // MINUTE, 'error': repr(error)[:300]})
                if report['errors'] > args.max_errors:
                    report['gave_up'] = f'more than {args.max_errors} errors'
                    break
                run.pb.tick(60, render=False)
                run.frame += 60
            try:
                snap = read()
            except Exception:  # noqa: BLE001  a read can fail mid transition, the next one counts
                pass
        report['finished'] = not missing
    finally:
        report.update(missing=missing, game_minutes=run.frame // MINUTE,
                      wall_seconds=round(time.monotonic() - began, 1))
        run.stop()
        (folder / 'snapshot-report.json').write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
        shutil.rmtree(work, ignore_errors=True)
    print(f'{folder.name}: kept {len(report["kept"])}, missing {", ".join(missing) or "none"}, '
          f'{len(report["stalls"])} stalls, {report["errors"]} errors, {report["game_minutes"]} game minutes '
          f'in {report["wall_seconds"]}s')
    return 0 if report['finished'] else 1


def _commit():
    try:
        return (ROOT / '.git').exists() and os.popen(f'git -C {ROOT} rev-parse --short HEAD').read().strip() or None
    except OSError:
        return None


def _before(rolling, progress_frame):
    """The newest rolling save from before the quiet stretch began, or the oldest one left."""
    earlier = [entry for entry in rolling if entry[0] <= progress_frame]
    return earlier[-1] if earlier else (rolling[0] if rolling else None)


def _prune(rolling, progress_frame):
    """Keep the newest save at or before the last progress and everything after it."""
    keep = _before(rolling, progress_frame)
    while rolling and rolling[0] is not keep and rolling[0][0] < (keep or rolling[-1])[0]:
        rolling.pop(0)[1].unlink(missing_ok=True)


def _bundle(run, snap, folder, before, reason, missing, game_minute, marks):
    """Keep a stall the way the application does, in a folder tools/stuck_scenarios.py add accepts."""
    bundle = folder / 'stalls' / f'stall-{game_minute:05d}m'
    bundle.mkdir(parents=True, exist_ok=True)
    run.save(bundle / 'noticed.state', compress=True)
    if before is not None:
        for suffix in ('.state', '.json'):
            shutil.copyfile(before[1].with_suffix(suffix), bundle / f'before{suffix}')
    goal = getattr(run.policy, 'goal', None)
    details = run.policy.details()
    report = {'reason': reason, 'game_minute': game_minute, 'next_rungs': missing[:2],
              'map': getattr(snap, 'map_name', None) or hex(snap.map), 'goal': getattr(goal, 'key', None),
              'objective': (details.get('objective') or {}).get('title'), 'policy_reason': details.get('reason'),
              'marks': [title for _, _, title in marks][-5:], 'has_before': before is not None}
    (bundle / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return {'bundle': str(bundle.relative_to(folder)), **report}


def adopt(args):
    folder = args.ladder
    if not private(folder):
        raise SystemExit('Ladders contain private game data. Choose a folder outside the checkout or under data/.')
    from pokesim.checkpoints import compress_state, open_state, pack_manifest, read_manifest
    manifest = read_manifest(args.checkpoint.with_suffix('.json'))
    if not isinstance(manifest, dict) or 'rom_sha1' not in manifest:
        raise SystemExit(f'{args.checkpoint} has no manifest beside it')
    ladder = json.loads((folder / 'ladder.json').read_text(encoding='utf-8')) if (folder / 'ladder.json').exists() else None
    if ladder and ladder['rom_sha1'] != manifest['rom_sha1']:
        raise SystemExit(f'{args.checkpoint} is from another cartridge than {folder.name}')
    if ladder is None:
        raise SystemExit(f'{folder} has no ladder.json. Run snapshot first, or write one for this cartridge.')
    if args.rung not in rungs_for(ladder['generation'], bool(ladder['randomizer'])):
        raise SystemExit(f'{folder.name} has no rung {args.rung}')
    target = folder / args.rung
    if target.exists() and not args.force:
        raise SystemExit(f'{target} exists. Pass --force to replace it.')
    with open_state(args.checkpoint) as source:
        state = compress_state(source.read())
    target.mkdir(parents=True, exist_ok=True)
    (target / 'start.state').write_bytes(state)
    (target / 'start.json').write_bytes(pack_manifest(dict(manifest, sha256=hashlib.sha256(state).hexdigest())))
    scenario = {'name': f'ladder-{folder.name}-{args.rung}', 'checkpoint': 'start.state', 'edits': {},
                'description': f'Stage ladder {folder.name}: {args.rung.replace("_", " ")}, adopted from {args.checkpoint.name}',
                'budget_game_minutes': REPLAY_GAME_MINUTES, 'max_quiet_game_minutes': REPLAY_QUIET_MINUTES, 'seed': 7}
    (target / 'scenario.json').write_text(json.dumps(scenario, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {target}')
    return 0


def show(args):
    for ladder in sorted(path.parent for path in args.root.glob('*/ladder.json')):
        info = json.loads((ladder / 'ladder.json').read_text(encoding='utf-8'))
        wanted = rungs_for(info['generation'], bool(info['randomizer']))
        have = [rung for rung in wanted if (ladder / rung / 'start.state').exists()]
        size = sum(path.stat().st_size for path in ladder.rglob('*') if path.is_file())
        print(f'{ladder.name:<20} {len(have)}/{len(wanted)} rungs, {size / 1e6:.1f} MB, '
              f'missing {", ".join(rung for rung in wanted if rung not in have) or "none"}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    taking = commands.add_parser('snapshot', help='play a fresh game and keep a save at each rung')
    taking.add_argument('rom', type=Path)
    taking.add_argument('ladder', type=Path, help='the ladder folder, such as data/ladder/red')
    taking.add_argument('--randomizer', default='', help='share code of a randomized ladder, such as PSR1-RED-WS-1')
    taking.add_argument('--refresh', action='append', help='a rung to take again even if it is kept, repeatable')
    taking.add_argument('--game-hours', type=float, default=200, help='game hours to play before giving up')
    taking.add_argument('--quiet', type=int, default=120, help='game minutes without an achievement that count as a stall')
    taking.add_argument('--battle-minutes', type=int, default=30, help='game minutes one battle may run')
    taking.add_argument('--max-battle-reloads', type=int, default=3,
                        help='reloads after hung battles in a row before one counts as a stall')
    taking.add_argument('--max-stalls', type=int, default=6)
    taking.add_argument('--max-errors', type=int, default=200)
    taking.add_argument('--seed', type=int, default=7)
    taking.add_argument('--data-root', type=Path, help='Gen II game data, by default GEN2_DATA_DIR')
    taking.set_defaults(action=snapshot)
    adopting = commands.add_parser('adopt', help='keep an existing checkpoint as a rung')
    adopting.add_argument('ladder', type=Path)
    adopting.add_argument('rung')
    adopting.add_argument('checkpoint', type=Path)
    adopting.add_argument('--force', action='store_true')
    adopting.set_defaults(action=adopt)
    showing = commands.add_parser('show', help='list the ladders under a folder')
    showing.add_argument('root', type=Path, nargs='?', default=ROOT / 'data' / 'ladder')
    showing.set_defaults(action=show)
    args = parser.parse_args(argv)
    return args.action(args)


if __name__ == '__main__':
    raise SystemExit(main())
