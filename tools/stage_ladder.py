"""Keep a ladder of saves, one per stage of the game, for replaying every stage after a change.

  snapshot  play one fresh game headless and keep a save the first time it reaches each rung
  adopt     keep an existing checkpoint as a rung, so a covered stage needs no fresh run, and with
            --adventure the walked steps, returns and offers of the adventure's store, and a Gen I one's
            Pokédex goals
  show      list the rungs a ladder folder holds and the ones it still lacks
  check     read each rung's save with pokecore and fail when its stage is not the rung's
  gate      play a short batch from every rung and fail on a new stall, an error or more waste

Rungs, in order. Every game has new_game, badges_2, badges_4, badges_6, badges_8, league_first (the
Elite Four's first room before any Hall of Fame) and post_game. Gold, Silver and Crystal count Johto
badges for the badge rungs and add champion_first (back in the world after the first Hall of Fame),
kanto_entry (off the S.S. Aqua in Vermilion), red (first arrival outside Mt. Silver before Red is
beaten) and post_game after Red. A randomized ladder keeps new_game, badges_4, badges_8 and league_first.

Each rung is a scenario folder (scenario.json, start.state, start.json) under LADDER/<rung>, written
compressed, so ``python -m pokesim.replay stuck-scenarios`` and the ladder batch replay it. LADDER/ladder.json names the
game and the share code of a randomized ladder. A rung already present is kept unless --refresh names it.

``snapshot`` plays as the headless runners do and watches for stalls the way the scenarios do: nothing
achieved for --quiet game minutes, or one goal standing down more than three times in a row. Each stall
keeps a bundle (before.state, noticed.state, report.json) under LADDER/stalls and the run goes back to
the save from before it, as the application reloads. A run gives up after --max-stalls stalls. Its
report, LADDER/snapshot-report.json, lists the game minute each rung was reached, every stall and the
errors the policy raised.

``check`` needs a folder of clean cartridges, found by the checksum each ladder.json names. A rung's
state is mostly out of reach of the game's Save menu, so its cartridge save is built from the WRAM it
holds, the way pokecore's own ladder test does, and pokecore.save_summary names the stage.

``gate`` plays 108000 frames (30 game minutes) from every rung under ROOT with the replay audit, once on
each of the goal seeds 7, 8 and 9, ten runs at once at niceness 10, and takes the load gate's heavy lock
first. A randomized ladder plays on its own share code. Goals are reseeded as in
``python -m pokesim.replay audit run --reseed-goals``, so two code versions meet the same rolls on each seed.
A run ends at its first stall, nothing achieved for 20 game minutes, one battle running 20 game minutes
or a retry loop, and keeps a bundle. The gate judges each rung on its three runs together and compares
how many stalled and the mean errors, story milestones and wasted share with the tracked
tools/ladder/gate-baseline.json. It exits 1 on more stalls than the baseline, more errors, fewer story
milestones, a wasted share more than two points higher, or a baseline rung with no save. A rung that earns more story milestones
passes while its wasted share is at most ten points higher, and the gate lists it under past_baseline,
since its baseline then wants a reviewed rewrite. The report also keeps each rung's share of frames under
restock, heal and PC goals, and each gate line shows the restock share and its move from the baseline.
A long walk that buys one ball counts as progress and never as waste, so only that share sees it. None of
the three is judged, since each moves more from seed to seed than the paired limit.

A rung whose one problem is that wasted share plays seeds 7 to 29 on the merge base with origin/main,
checked out in a temporary worktree with its own environment, and on the head, whose three runs stand
for their seeds. It passes when the head wastes at most one point more on the mean of the 23 pairs, and
keeps its baseline. A paired failure prints the pairs and the frames under each goal on both trees. With
more than five such rungs, or on main, where the merge base is the head, the screen's verdict stands.
The story milestones are the ones the policy keeps in story order, ``progression.milestones`` in Red,
Blue and Yellow and the checkpoints the Gold, Silver and Crystal story notes as it passes them. The gate
counts the ones a rung earned in its window. ``--write-baseline`` stores the run there, for a pull
request that names the play change it accepts. The runs, bundles and gate-report.json go under
ROOT/gate/<time>.

Red, Blue and Yellow pick their game data from the cartridge, so no POKESIM_GEN1_VARIANT is needed.
Gold, Silver and Crystal need --data-root or GEN2_DATA_DIR. Ladder folders hold private game data and
must stay outside the checkout or under data/.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Policy modules load after ``prepare``, once the cartridge has set the Gen I variant and the randomizer.
# The gate's rung runner and its comparison live in pokesim.replay.rung, which the replay bisect shares.
from pokesim.replay.rung import (GATE_FRAMES, GATE_PAIRED_POINTS, GATE_PAIRED_RUNGS, GATE_PAIRED_SEEDS, GATE_QUIET,
                                 GATE_SEEDS, GATE_TIMEOUT, GATE_WASTE_POINTS, PIPELINE_BAR, _bundle, _cartridges,
                                 agreement, compare, gate_rung, mean_result, paired, past_baseline, prepare, share,
                                 waste_only)

GEN1_RUNGS = ('new_game', 'badges_2', 'badges_4', 'badges_6', 'badges_8', 'league_first', 'post_game')
GEN2_RUNGS = ('new_game', 'badges_2', 'badges_4', 'badges_6', 'badges_8', 'league_first', 'champion_first',
              'kanto_entry', 'red', 'post_game')
RANDOMIZED_RUNGS = ('new_game', 'badges_4', 'badges_8', 'league_first')
# Lorelei's room. Every Gen I map from Victory Road to the Hall of Fame, where a post-game save would
# still be part of a League run.
GEN1_LORELEI = 0xF5
GEN1_LEAGUE = frozenset({0x6C, 0xC2, 0xC6, 0xAE, 0xF5, 0xF6, 0xF7, 0x71, 0x78, 0x76})
GEN2_LEAGUE = frozenset({'WILLS_ROOM', 'KOGAS_ROOM', 'BRUNOS_ROOM', 'KARENS_ROOM', 'LANCES_ROOM', 'HALL_OF_FAME'})
# The pokecore.save_summary stage each rung stands for. Gen II's red rung stands before the fight, so
# Red is not beaten yet, and only the credits after him set the Hall of Fame count that means beaten.
GEN1_STAGES = {'new_game': 'new game', 'league_first': 'league entered', 'post_game': 'post-game'}
GEN2_STAGES = {'new_game': 'new game', 'league_first': 'league entered', 'champion_first': 'champion',
               'kanto_entry': 'kanto entered', 'red': 'kanto entered', 'post_game': 'red beaten'}
# The end of Gen I wMainData, where the active box starts in WRAM.
GEN1_MAIN_END = 0xDA80
# Saves the run keeps while it plays, for a stall's before.state and the reload after it.
ROLLING_GAME_MINUTES = 10
REPLAY_GAME_MINUTES = 120
REPLAY_QUIET_MINUTES = 90
# The gate plays ten rungs at once. The environment variable marks a gate that already holds the load
# gate's heavy lock.
GATE_JOBS = 10
GATE_HELD = 'POKESIM_LADDER_GATE_HELD'
# The baseline is tracked, so it moves only in a pull request, and a branch compares with its own base.
GATE_BASELINE = ROOT / 'tools' / 'ladder' / 'gate-baseline.json'


def private(path):
    path = path.resolve()
    return not path.is_relative_to(ROOT) or path.is_relative_to(ROOT / 'data')


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
    from pokesim.runtime.headless import HeadlessRun
    from pokesim.scenarios import Gen1Watch, Gen2Watch, gen2_data_root
    if generation == 2:
        data_root = data_root or gen2_data_root()
    run = HeadlessRun(rom, seed=seed, rng=random.Random(seed), data_root=data_root)
    return run, (Gen2Watch if generation == 2 else Gen1Watch)(run), run.read


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
        path = rolling.pop(0)[1]
        path.unlink(missing_ok=True)
        path.with_suffix('.json').unlink(missing_ok=True)


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
    if args.adventure:
        from pokesim.state import schema
        from pokesim.store_observe import rows
        db = schema.connect(args.adventure / 'pokesim.sqlite', read_only=True)
        try:
            manifest = dict(manifest, store_rows=rows(db, ladder['generation']))
        finally:
            db.close()
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


def expected_stage(generation, rung):
    if rung.startswith('badges_'):
        return f'{rung.removeprefix("badges_")} badges'
    return (GEN2_STAGES if generation == 2 else GEN1_STAGES)[rung]


def _gen1_image(memory, raw_memory):
    """What the Save menu would write for this WRAM, with the boxes as SRAM holds them now."""
    from pokecore import save_summary as ss
    from pokecore.gen1 import W_DEX_OWNED, W_PARTY_COUNT, W_PLAYER_NAME
    image = bytearray(ss.SAVE_SIZE)
    for bank in (2, 3):
        image[bank * 0x2000:(bank + 1) * 0x2000] = bytes(raw_memory[bank, 0xA000:0xC000])
    image[ss.GEN1_PLAYER_NAME:ss.GEN1_PLAYER_NAME + 11] = bytes(memory[W_PLAYER_NAME:W_PLAYER_NAME + 11])
    image[W_DEX_OWNED - ss.GEN1_MAIN:GEN1_MAIN_END - ss.GEN1_MAIN] = bytes(memory[W_DEX_OWNED:GEN1_MAIN_END])
    image[ss.GEN1_PARTY:ss.GEN1_ACTIVE_BOX] = bytes(memory[W_PARTY_COUNT:W_PARTY_COUNT + 0x194])
    box = slice(ss.GEN1_ACTIVE_BOX, ss.GEN1_ACTIVE_BOX + ss.GEN1_BOX_SIZE)
    image[box] = bytes(memory[GEN1_MAIN_END:GEN1_MAIN_END + ss.GEN1_BOX_SIZE])
    image[ss.GEN1_CHECKSUM] = ~sum(image[ss.GEN1_PLAYER_NAME:ss.GEN1_CHECKSUM]) & 0xFF
    return bytes(image)


def _gen2_image(version, memory):
    from pokecore import save_summary as ss
    from pokecore.gen2.memory_map import symbols
    _, delta, end = ss.GEN2_LAYOUTS['crystal' if version == 'crystal' else None]
    image = bytearray(ss.SAVE_SIZE)
    for bank in (1, 2, 3):
        image[bank * 0x2000:(bank + 1) * 0x2000] = bytes(memory[bank, 0xA000:0xC000])
    image[ss.GEN2_CHECK_1] = ss.GEN2_CHECK_1_VALUE
    image[ss.GEN2_DATA:end] = bytes(memory[1, ss.GEN2_DATA + delta:end + delta])
    at = symbols(version)['sChecksum'][1] - 0xA000 + 0x2000
    image[at:at + 2] = (sum(image[ss.GEN2_DATA:end]) & 0xFFFF).to_bytes(2, 'little')
    image[at + 2] = ss.GEN2_CHECK_2_VALUE
    return bytes(image)


def rung_save(rom, info, state):
    """The cartridge save a rung's state stands for, built from its WRAM. The emulator is stopped after."""
    import io
    if info['generation'] == 1:
        from pokecore.yellow import open_emulator
        emulator = open_emulator(io.BytesIO(rom), ram_file=io.BytesIO(bytes(0x8000)), window='null',
                                 sound_emulated=False, log_level='ERROR')
        try:
            emulator.load_state(io.BytesIO(state))
            return _gen1_image(emulator.memory, getattr(emulator, '_emulator', emulator).memory)
        finally:
            emulator.stop(save=False)
    from pokecore.gen2 import clock
    emulator = clock.boot(rom, sound=False)
    try:
        emulator.load_state(io.BytesIO(state))
        return _gen2_image(info['game'], emulator.memory)
    finally:
        emulator.stop(save=False)


def check(args):
    from pokecore.save_summary import SaveError, summarize_save
    from pokesim.checkpoints import open_state
    roms = _cartridges(args.roms)
    failures = checked = 0
    for ladder in sorted(path.parent for path in args.root.glob('*/ladder.json')):
        info = json.loads((ladder / 'ladder.json').read_text(encoding='utf-8'))
        rom = roms.get(info['rom_sha1'])
        if rom is None:
            print(f'{ladder.name}: no cartridge in {args.roms} has SHA-1 {info["rom_sha1"]}')
            failures += 1
            continue
        rom = rom.read_bytes()
        for rung in rungs_for(info['generation'], bool(info['randomizer'])):
            path = ladder / rung / 'start.state'
            if not path.exists():
                continue
            with open_state(path) as handle:
                state = handle.read()
            wanted = expected_stage(info['generation'], rung)
            try:
                stage = summarize_save(rung_save(rom, info, state)).stage
            except SaveError as error:
                stage = f'unreadable ({error})'
            checked += 1
            if stage != wanted:
                failures += 1
                print(f'{ladder.name}/{rung}: the save reads as {stage}, not {wanted}')
    print(f'checked {checked} rungs, {failures} problems')
    return 1 if failures else 0


def _gate_line(result, base):
    name = f'{result["ladder"]}/{result["rung"]}'
    if result.get('failed'):
        return f'{name:<30} failed: {result["failed"]}'
    change = f'{result["waste"] - base["waste"]:+5.1f}' if base else '  new'
    restock = ''
    if 'restock' in result:
        moved = f' ({result["restock"] - base["restock"]:+.1f})' if base and 'restock' in base else ''
        restock = f', {result["restock"]:.1f}% restock{moved}'
    seeds = len(result.get('seeds', ()))
    stall = (f', stall: {result["stall"]["reason"]}' + (f' ({result["stalls"]} of {seeds} seeds)' if seeds else '')
             if result['stall'] else '')
    story = f', earned {", ".join(result["story"])}' if result.get('story') else ''
    story += f' ({result["milestones"]:g} a seed)' if story and seeds else ''
    pipeline = result.get('pipeline')
    agrees = (f', pipeline agrees {share(pipeline["agreed"], pipeline["decisions"]):.1f}% of '
              f'{pipeline["decisions"]} decisions, {share(pipeline["frames_agreed"], pipeline["frames"]):.1f}% '
              'of frames' if pipeline else '')
    return (f'{name:<30} {result["waste"]:5.1f}% wasted ({change}){restock}, {result["errors"]:g} errors{story}{stall}'
            f'{agrees}')


def attempt(folder, commit):
    """Which try at the gate this is for ``commit``: one more than the reports already under ``folder``.
    A pass on the third try reads differently from a pass on the first."""
    earlier = 0
    for path in Path(folder).glob('*/gate-report.json'):
        try:
            earlier += json.loads(path.read_text(encoding='utf-8')).get('commit') == commit
        except (OSError, ValueError):
            continue
    return earlier + 1


def _play(args, env, folder, ladder, rung, seed, python=sys.executable, script=Path(__file__).resolve()):
    """Play one rung on one seed with ``gate-rung`` in its own process, and return its summary or its failure."""
    folder.mkdir(parents=True, exist_ok=True)
    command = ['nice', '-n', str(args.nice), str(python), str(script), 'gate-rung', str(ladder), rung, str(folder),
               str(args.roms), '--frames', str(args.frames), '--quiet', str(args.quiet), '--battle-minutes',
               str(args.battle_minutes), '--seed', str(seed)]
    if args.data_root:
        command += ['--data-root', str(args.data_root)]
    with open(folder / 'log.txt', 'w', encoding='utf-8') as log:
        try:
            code = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=False,
                                  timeout=GATE_TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            code = f'no result in {GATE_TIMEOUT} seconds'
    summary = folder / 'summary.json'
    if code == 0 and summary.exists():
        return dict(json.loads(summary.read_text(encoding='utf-8')), seed=seed)
    return {'ladder': ladder.name, 'rung': rung, 'seed': seed, 'failed': f'exit {code}, see {folder / "log.txt"}'}


def _merge_base():
    """The merge base of HEAD with a fresh origin/main, or None outside a checkout or when HEAD is that
    commit, as on main, since a tree paired with itself always passes."""
    if not (ROOT / '.git').exists():
        return None
    subprocess.run(['git', '-C', str(ROOT), 'fetch', '--quiet', 'origin', 'main'], check=False)
    head, base = (subprocess.run(['git', '-C', str(ROOT), *command], check=True, capture_output=True,
                                 text=True).stdout.strip()
                  for command in (['rev-parse', 'HEAD'], ['merge-base', 'HEAD', 'origin/main']))
    return None if base == head else base


@contextmanager
def merge_base(commit):
    """``commit`` checked out in a temporary worktree with an environment of its own, as (python, script).
    The environment takes the acceleration extra when this one has it, as the image does. The worktree
    goes when the paired stage ends."""
    folder = Path(tempfile.mkdtemp(prefix='gate-base-'))
    tree = folder / 'tree'
    subprocess.run(['git', '-C', str(ROOT), 'worktree', 'add', '--quiet', '--detach', str(tree), commit], check=True)
    try:
        extras = ['--extra', 'acceleration'] if importlib.util.find_spec('numba') else []
        # uv must build the tree's own .venv, never this environment.
        env = {key: value for key, value in os.environ.items() if key not in ('VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT')}
        subprocess.run(['uv', 'sync', '--quiet', '--locked', *extras], cwd=tree, env=env, check=True)
        yield tree / '.venv' / 'bin' / 'python', tree / 'tools' / 'stage_ladder.py'
    finally:
        subprocess.run(['git', '-C', str(ROOT), 'worktree', 'remove', '--force', str(tree)], check=False)
        shutil.rmtree(folder, ignore_errors=True)


def goal_frames(folders):
    """The frames under each goal key over the runs in ``folders``, from each run's run.json."""
    total = Counter()
    for folder in folders:
        for line, frames in json.loads((folder / 'run.json').read_text(encoding='utf-8'))['frames_by_goal'].items():
            total[line.split(' ', 1)[0]] += frames
    return dict(total)


def pair(rungs, args, out, env, commit):
    """Play each rung that failed on its wasted share alone on the paired seeds, on the merge base
    ``commit`` and on the head, and return each rung's judgment by name. The head's screen runs stand for
    their own seeds, and the merge base's runs go under OUT/merge-base."""
    def folder(tree, result, seed):
        return (out / 'merge-base' if tree == 'base' else out) / result['ladder'] / result['rung'] / f'seed-{seed}'

    with merge_base(commit) as (python, script):
        jobs = [(result, 'base', seed) for result in rungs for seed in GATE_PAIRED_SEEDS]
        jobs += [(result, 'head', seed) for result in rungs for seed in GATE_PAIRED_SEEDS if seed not in result['seeds']]

        def play(job):
            result, tree, seed = job
            where = (python, script) if tree == 'base' else ()
            return _play(args, env, folder(tree, result, seed), args.root / result['ladder'], result['rung'], seed,
                         *where)

        with ThreadPoolExecutor(args.jobs) as pool:
            played = list(zip(jobs, pool.map(play, jobs)))
    verdicts = {}
    for result in rungs:
        runs = {'base': {}, 'head': {run['seed']: run for run in result['runs']}}
        for (owner, tree, seed), run in played:
            if owner is result:
                runs[tree][seed] = run
        name = f'{result["ladder"]}/{result["rung"]}'
        failed = [f'seed {seed} on the {tree}: {run["failed"]}' for tree in runs for seed, run in runs[tree].items()
                  if run.get('failed')]
        if failed:
            verdicts[name] = {'base': commit, 'passed': False, 'failed': ', '.join(failed)}
            continue
        verdict = dict(paired([(seed, runs['base'][seed]['waste'], runs['head'][seed]['waste'])
                               for seed in GATE_PAIRED_SEEDS]), base=commit)
        if not verdict['passed']:
            verdict['goals'] = {tree: goal_frames(folder(tree, result, seed) for seed in GATE_PAIRED_SEEDS)
                                for tree in runs}
        verdicts[name] = verdict
    return verdicts


def _paired_lines(name, verdict, points=GATE_PAIRED_POINTS):
    """What the gate prints for a rung judged on paired seeds: one line, and on a failure the pairs and the
    frames under each goal on both trees, the goal the head spent most more on first."""
    if 'pairs' not in verdict:
        return [f'{name}: no paired judgment against the merge base {verdict["base"][:8]}, {verdict["failed"]}']
    seeds = len(verdict['pairs'])
    line = (f'{name}: {verdict["mean"]:+.2f} points wasted on the mean of {seeds} paired seeds against the merge '
            f'base {verdict["base"][:8]}, standard error {verdict["error"]:.2f}, median {verdict["median"]:+.2f}')
    if verdict['passed']:
        return [f'{line}, within the {points:.1f} point limit']
    lines = [f'{line}, over the {points:.1f} point limit', '  seed   base   head  difference']
    lines += [f'  {seed:4d} {base:6.2f} {head:6.2f} {head - base:+11.2f}' for seed, base, head in verdict['pairs']]
    base, head = verdict['goals']['base'], verdict['goals']['head']
    lines.append(f'  frames under each goal over the {seeds} seeds: base, head, difference')
    for key in sorted(set(base) | set(head), key=lambda key: base.get(key, 0) - head.get(key, 0)):
        lines.append(f'  {key:<28} {base.get(key, 0):9d} {head.get(key, 0):9d} {head.get(key, 0) - base.get(key, 0):+10d}')
    return lines


def gate(args):
    if os.environ.get(GATE_HELD) != '1':
        # Take the heavy lock of the shared load gate, so no test or other batch runs beside the gate.
        command = ['sh', str(ROOT / 'tools' / 'load_gate.sh'), 'heavy', sys.executable, str(Path(__file__).resolve()),
                   *args.argv]
        return subprocess.run(command, env=dict(os.environ, **{GATE_HELD: '1'}), check=False).returncode
    baseline_path = args.baseline or GATE_BASELINE
    stored = json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.exists() else None
    if stored is not None and stored['frames'] != args.frames and not args.write_baseline:
        raise SystemExit(f'{baseline_path} was taken at {stored["frames"]} frames a rung, not {args.frames}')
    # A baseline from before the gate played several seeds was taken on seed 7 alone.
    if stored is not None and stored.get('seeds', [7]) != list(args.seeds) and not args.write_baseline:
        raise SystemExit(f'{baseline_path} was taken on seeds {", ".join(map(str, stored.get("seeds", [7])))}, '
                         f'not {", ".join(map(str, args.seeds))}')
    baseline = (stored or {}).get('rungs', {})
    jobs = [(ladder, rung, seed) for ladder in sorted(path.parent for path in args.root.glob('*/ladder.json'))
            for rung in rungs_for(*_ladder_kind(ladder)) if (ladder / rung / 'start.state').exists()
            and (not args.ladder or ladder.name in args.ladder) for seed in args.seeds]
    if not jobs:
        raise SystemExit(f'no rungs under {args.root}')
    # A baseline rung with no save fails, so a lost save cannot pass the gate by playing fewer rungs.
    played = {f'{ladder.name}/{rung}' for ladder, rung, _ in jobs}
    missing = [f'{name}: in the baseline, but {args.root / name / "start.state"} is missing' for name in baseline
               if name not in played and (not args.ladder or name.split('/')[0] in args.ladder)]
    out = args.out or args.root / 'gate' / time.strftime('%Y%m%d-%H%M%S')
    # Each rung sets its own Gen I variant and share code.
    env = {key: value for key, value in os.environ.items() if key not in ('POKESIM_GEN1_VARIANT', 'RANDOMIZER', 'ROM_PATH')}
    began = time.monotonic()

    def play(job):
        ladder, rung, seed = job
        return _play(args, env, out / ladder.name / rung / f'seed-{seed}', ladder, rung, seed)

    # The jobs keep each rung's seeds together, so a rung's line prints once its last seed is in.
    results, runs = [], []
    with ThreadPoolExecutor(args.jobs) as pool:
        for run in pool.map(play, jobs):
            runs.append(run)
            if len(runs) == len(args.seeds):
                result = mean_result(runs)
                print(_gate_line(result, baseline.get(f'{result["ladder"]}/{result["rung"]}')), flush=True)
                results.append(result)
                runs = []
    problems = compare(results, baseline, args.waste_points)
    wasteful = [] if args.write_baseline else waste_only(results, baseline, args.waste_points)
    judged = {}
    base = wasteful and len(wasteful) <= GATE_PAIRED_RUNGS and _merge_base()
    if len(wasteful) > GATE_PAIRED_RUNGS:
        print(f'{len(wasteful)} rungs failed on their wasted share alone, more than {GATE_PAIRED_RUNGS}, so none '
              'plays paired seeds')
    elif wasteful and not base:
        print(f'{len(wasteful)} rungs failed on their wasted share alone, and this tree has no merge base with '
              'origin/main apart from itself, so none plays paired seeds')
    elif wasteful:
        print(f'{len(wasteful)} rungs failed on their wasted share alone and play seeds {GATE_PAIRED_SEEDS[0]} to '
              f'{GATE_PAIRED_SEEDS[-1]} on the merge base {base[:8]} and on the head', flush=True)
        judged = pair(wasteful, args, out, env, base)
        problems = compare([result for result in results if f'{result["ladder"]}/{result["rung"]}' not in judged],
                           baseline, args.waste_points)
        for name, verdict in judged.items():
            lines = _paired_lines(name, verdict)
            print('\n'.join(lines), flush=True)
            if not verdict['passed']:
                problems.append(lines[0])
    problems += missing
    further = past_baseline(results, baseline)
    commit = _commit()
    report = {'commit': commit, 'attempt': attempt(args.root / 'gate', commit), 'frames': args.frames,
              'seeds': list(args.seeds), 'wall_seconds': round(time.monotonic() - began, 1),
              'baseline': str(baseline_path) if stored else None, 'problems': problems,
              'past_baseline': further, 'paired': judged, 'results': results}
    out.mkdir(parents=True, exist_ok=True)
    (out / 'gate-report.json').write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    stalls = [result for result in results if result.get('stall')]
    print(f'{len(results)} rungs in {report["wall_seconds"]}s, {len(stalls)} stalls, attempt {report["attempt"]}, '
          f'report in {out}')
    total, low = agreement(results)
    if total:
        print(f'decide pipeline: agrees on {share(total["agreed"], total["decisions"]):.1f}% of '
              f'{total["decisions"]} decisions and {share(total["frames_agreed"], total["frames"]):.1f}% of frames')
        if low:
            print(f'decide pipeline under {100 * PIPELINE_BAR:g}% of frames: {", ".join(low)}')
    if args.write_baseline:
        failed = [result for result in results if result.get('failed')]
        if failed:
            print(f'not writing a baseline: {len(failed)} rungs failed')
            return 1
        rungs = {f'{result["ladder"]}/{result["rung"]}': {
            'stall': result['stall'] and result['stall']['reason'], 'stalls': result['stalls'],
            'errors': result['errors'], 'waste': result['waste'], 'restock': result['restock'],
            'milestones': result['milestones'], 'story': result['story']} for result in results}
        baseline_path.write_text(json.dumps({'commit': report['commit'], 'attempt': report['attempt'],
                                             'taken': time.strftime('%Y-%m-%d'), 'frames': args.frames,
                                             'seeds': list(args.seeds), 'rungs': rungs}, indent=1) + '\n',
                                 encoding='utf-8')
        print(f'wrote {baseline_path}')
        return 0
    if stored is None:
        print(f'no baseline at {baseline_path}. Take one on main with --write-baseline.')
        return 1
    for line in further:
        print(line)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def _ladder_kind(ladder):
    info = json.loads((ladder / 'ladder.json').read_text(encoding='utf-8'))
    return info['generation'], bool(info['randomizer'])


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
    adopting.add_argument('--adventure', type=Path,
                          help="an adventure's folder, whose walked steps, returns and Champion counter offers "
                               "the rung's run starts with, and for Red, Blue or Yellow its Pokédex goals")
    adopting.set_defaults(action=adopt)
    showing = commands.add_parser('show', help='list the ladders under a folder')
    showing.add_argument('root', type=Path, nargs='?', default=ROOT / 'data' / 'ladder')
    showing.set_defaults(action=show)
    checking = commands.add_parser('check', help="fail when a rung's save is not at the rung's stage")
    checking.add_argument('roms', type=Path, help='a folder holding the clean cartridges the ladders were taken on')
    checking.add_argument('root', type=Path, nargs='?', default=ROOT / 'data' / 'ladder')
    checking.set_defaults(action=check)
    gating = commands.add_parser('gate', help='play a short batch from every rung and compare it with the baseline')
    gating.add_argument('roms', type=Path, help='a folder holding the clean cartridges the ladders were taken on')
    gating.add_argument('root', type=Path, nargs='?', default=ROOT / 'data' / 'ladder')
    gating.add_argument('--ladder', action='append', help='play only this ladder, such as gold, repeatable')
    gating.add_argument('--frames', type=int, default=GATE_FRAMES, help='frames to play from each rung')
    gating.add_argument('--jobs', '-n', type=int, default=GATE_JOBS, help='rungs played at once')
    gating.add_argument('--nice', type=int, default=10, help='the niceness each rung plays at')
    gating.add_argument('--quiet', type=int, default=GATE_QUIET, help='game minutes without an achievement that count as a stall')
    gating.add_argument('--battle-minutes', type=int, default=GATE_QUIET, help='game minutes one battle may run')
    gating.add_argument('--waste-points', type=float, default=GATE_WASTE_POINTS,
                        help='how many points a rung\'s wasted share may grow before the gate fails')
    gating.add_argument('--seeds', type=lambda text: tuple(int(seed) for seed in text.split(',')), default=GATE_SEEDS,
                        help='the goal seeds each rung plays on, comma separated, by default 7,8,9')
    gating.add_argument('--baseline', type=Path, help='the baseline file, by default tools/ladder/gate-baseline.json')
    gating.add_argument('--write-baseline', action='store_true', help='store this run as the baseline')
    gating.add_argument('--out', type=Path, help='where the runs and stall bundles go, by default ROOT/gate/<time>')
    gating.add_argument('--data-root', type=Path, help='Gen II game data, by default GEN2_DATA_DIR')
    gating.set_defaults(action=gate)
    one = commands.add_parser('gate-rung', help='play one rung for gate, in its own process')
    one.add_argument('ladder', type=Path)
    one.add_argument('rung')
    one.add_argument('out', type=Path)
    one.add_argument('roms', type=Path)
    one.add_argument('--frames', type=int, default=GATE_FRAMES)
    one.add_argument('--quiet', type=int, default=GATE_QUIET)
    one.add_argument('--battle-minutes', type=int, default=GATE_QUIET)
    one.add_argument('--seed', type=int, default=7)
    one.add_argument('--data-root', type=Path)
    one.set_defaults(action=gate_rung)
    args = parser.parse_args(argv)
    args.argv = list(sys.argv[1:] if argv is None else argv)
    return args.action(args)


if __name__ == '__main__':
    raise SystemExit(main())
