"""Play one ladder rung or checkpoint headless and audit where its frames go.

``run_one`` is the runner behind ``tools/replay_audit.py run``, and ``gate_rung`` the one behind
``tools/stage_ladder.py gate-rung``, which the ladder gate and ``python -m pokesim.replay`` start in a
process of their own. The policy modules load inside ``run_one``, after ``randomize`` or ``prepare`` has
set the worker's environment, since Gen I modules read their tables at import time. Only the standard
library loads with this module.
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

# hRandomAdd and hRandomSub in pret/pokered, which Yellow keeps. Gold, Silver and Crystal read theirs from the symbols.
GEN1_RANDOM = (0xFFD3, 0xFFD4)
DIVIDER = 0xFF04  # Any write restarts the divider at zero.
VBLANK = 0x0040  # The VBlank interrupt vector, the same in all six games.
HUNTS = frozenset({'collection_hunt', 'collection_fish', 'collection_field', 'collect_hunt'})
TRAINING = frozenset({'collection_train', 'collect_train'})
# The reason a Red, Blue or Yellow hunt gives for its trip, and the hunt kind it stands for.
GEN1_PURPOSES = {'a partner another adventure needs': 'partner', 'more chances to find high DV partners': 'quality',
                 'another partner for the collection': 'repeat', 'a missing Pokédex entry': 'completion'}
# The gate plays 30 game minutes from every rung and fails on a new stall, more errors, or a wasted
# share up by more than two points. Its stall watch is shorter than the snapshot's to fit the batch.
GATE_FRAMES = 108000
GATE_QUIET = 20
GATE_WASTE_POINTS = 2.0
GATE_TIMEOUT = 1800


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


def _open(rom, state, data_root, seed, fair_wild_dvs=None):
    if rom.suffix == '.gbc':
        if fair_wild_dvs:
            raise ValueError('Fair wild DVs is only for Red, Blue and Yellow')
        from pokesim.gen2.headless import HeadlessRun
        run = _partners(HeadlessRun(rom, state, seed=seed, data_root=Path(data_root) if data_root else None))
        return run, run.read, run.game
    from pokesim.headless import HeadlessRun
    from pokesim.ram import read_snapshot
    run = _partners(HeadlessRun(rom, state, seed=seed, reseed=True, fair_wild_dvs=fair_wild_dvs))
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

    def __init__(self, save, seed=7):
        # Seed 7, the default, keeps the save name alone, so runs made before the seed joined the key
        # still compare with new ones.
        self.save = save if seed == 7 else f'{save}\nseed {seed}'
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
    """The progress events of ``current`` for goal ``key``. Any goal also progresses on experience. A level
    can take many battles, and a training detour fights its battles while the policy reports the goal it
    detoured from, so a span that gained experience was not wasted."""
    from pokesim.planning.monitor import ProgressEvent
    from pokesim.planning.progress import _held, events
    found = events(previous, current)
    # A Pokémon let go frees a slot. The tree under test may predate that event, so the audit reads it
    # here too and every tree it compares is measured the same way.
    if found == [] and previous is not None and current is not None and getattr(current, 'valid', True) \
            and getattr(previous, 'valid', True) and _held(current) < _held(previous):
        found.append(ProgressEvent('room', _held(previous) - _held(current)))
    if previous is not None and current is not None and not found and getattr(current, 'valid', True) \
            and getattr(previous, 'valid', True):
        gained = sum(after.experience - before.experience for before, after in zip(previous.party, current.party)
                     if before.species == after.species and after.experience > before.experience)
        if gained:
            found.append(ProgressEvent('experience', gained))
    # A heal that restores HP, status or PP was needed, so its trip is support for the goal behind it.
    # A heal that loops or repeats with nothing to restore gains nothing and stays wasted.
    if key == 'heal' and previous is not None and current is not None and not found \
            and getattr(current, 'valid', True) and getattr(previous, 'valid', True):
        restored = sum(1 for before, after in zip(previous.party, current.party) if before.species == after.species
                       and (after.hp > before.hp or before.status and not after.status
                            or sum(getattr(after, 'pp', ())) > sum(getattr(before, 'pp', ()))))
        if restored:
            found.append(ProgressEvent('healed', restored))
    # A PC visit that makes another box the current one keeps the held count, so no other event shows it,
    # yet a full current box stops every catch until that visit.
    box_before, box_after = getattr(previous, 'active_box', None), getattr(current, 'active_box', None)
    if not found and box_before is not None and box_after is not None and box_after != box_before \
            and getattr(current, 'valid', True) and getattr(previous, 'valid', True):
        found.append(ProgressEvent('box', box_after))
    # A restock sells only to free an entry in a crowded bag or to raise cash it lacks. A full bag picks up
    # no item ball and a short purse buys nothing, so a sale is support for the goal behind it, though it
    # gains no item. A Yellow restock after the Silph Scope sold one item at the Lavender Mart on the way
    # to the tower. The entry and the cash can change on different reads, so either one counts.
    if key == 'restock' and previous is not None and current is not None and not found \
            and getattr(current, 'valid', True) and getattr(previous, 'valid', True):
        freed = len(previous.items) - len(current.items)
        if freed > 0 or getattr(current, 'money', 0) > getattr(previous, 'money', 0):
            found.append(ProgressEvent('sold', max(freed, 0)))
    # A gift for a full party waits on a deposit, which keeps the held count, so no other event shows it,
    # yet it is the whole of the goal. In Red's postgame a better Dugtrio copy filled the party, and the
    # Eevee gift then waited on a deposit at the Vermilion Pokémon Center.
    if key == 'party_collection_space' and previous is not None and current is not None and not found \
            and getattr(current, 'valid', True) and getattr(previous, 'valid', True) \
            and len(current.party) < len(previous.party):
        found.append(ProgressEvent('deposit', len(previous.party) - len(current.party)))
    # A PC visit that swaps the trainee into the party keeps the held count, so no other event shows it,
    # yet it is the whole of the preparation goal. A goal cut short between the deposit and the withdrawal
    # leaves two spans, so each half of the swap counts.
    if key == 'collection_train_pc' and previous is not None and current is not None and not found \
            and getattr(current, 'valid', True) and getattr(previous, 'valid', True) and previous.party and current.party:
        before, after = Counter(map(_identity, previous.party)), Counter(map(_identity, current.party))
        moved = sum((after - before).values()) or sum((before - after).values())
        if moved:
            found.append(ProgressEvent('trainee', moved))
    return found


def _identity(mon):
    return mon.species, getattr(mon, 'trainer_id', None), tuple(getattr(mon, 'dvs', ()))


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


def randomize(code, rom):
    """Set the environment a randomized adventure's worker runs in and return the canonical share code,
    or '' for a clean cartridge. Call it before any policy module loads."""
    if not code:
        return ''
    from pokesim.cartridges import identify
    from pokesim.randomized import ENV, validate
    cartridge = identify(Path(rom).read_bytes())
    if cartridge is None:
        raise ValueError('Only a verified cartridge can be randomized')
    code = validate(code, cartridge.version)
    os.environ[ENV] = code
    os.environ['ROM_PATH'] = str(Path(rom).resolve())
    return code


def run_one(args, watch=None):
    """Play one checkpoint and write its run file. ``watch``, called with the run and each snapshot, ends
    the run early when it returns true, as the ladder gate does on a stall."""
    randomizer = randomize(args.randomizer, args.rom)
    from pokesim.planning.monitor import Monitor
    run, read, game = _open(Path(args.rom), Path(args.state), args.data_root, args.seed, args.fair_wild_dvs)
    idle(run, args.lead_in)
    seeds = GoalSeeds(Path(args.state).name, args.seed) if args.reseed_goals else None
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
    # Run attempts the battle stance made and the ones that failed, per row (planner design S5).
    flees = defaultdict(Counter)
    counted = Counter(getattr(run.policy, 'flees', None) or {})
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
        now = Counter(getattr(run.policy, 'flees', None) or {})
        if now != counted:
            flees[line].update(now - counted)
            counted = now
        for stood in _stand_downs(run, seen):
            stand_downs.append({'key': stood, 'goal': line, 'frame': run.frame})
        if current is not None and run.generation == 2 and key == 'collection_release':
            released += _released(snapshot, current, run.frame)
        if current is not None:
            snapshot = current
        if watch is not None and watch(run, snapshot):
            break
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
        'flees': {line: dict(counts) for line, counts in flees.items()}, 'randomizer': randomizer,
        'fair_wild_dvs': bool(args.fair_wild_dvs),
    }
    if shadow is not None:
        result['shadow'] = {**shadow.summary(), 'frames_by_pick': dict(would)}
    Path(args.out).write_text(json.dumps(result, indent=1), encoding='utf-8')
    return result


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


def _bundle(run, snap, folder, before, reason, missing, game_minute, marks, kind='ladder'):
    """Keep a stall the way the application does, with the shared capture that ``python -m pokesim.replay
    capture`` turns into a scenario. A stall noticed again in the same game minute after a reload gets its
    own folder."""
    from pokesim.runtime.capture import keep_run
    goal = getattr(run.policy, 'goal', None)
    details = run.policy.details()
    report = {'kind': kind, 'reason': reason, 'game_minute': game_minute, 'next_rungs': missing[:2],
              'map': getattr(snap, 'map_name', None) or hex(snap.map), 'goal': getattr(goal, 'key', None),
              'objective': (details.get('objective') or {}).get('title'), 'policy_reason': details.get('reason'),
              'marks': [title for _, _, title in marks][-5:]}
    bundle = keep_run(run, folder / 'stalls' / f'stall-{game_minute:05d}m', report,
                      before=None if before is None else before[1], compress=True)
    return {'bundle': bundle.relative_to(folder).as_posix(), **report, 'has_before': before is not None}


def _cartridges(folder):
    """Every file in a folder by its SHA-1, so a ladder finds its clean cartridge whatever it is named."""
    return {hashlib.sha1(path.read_bytes()).hexdigest(): path for path in sorted(folder.iterdir())
            if path.is_file() and path.stat().st_size <= 0x800000}


class GateWatch:
    """Ends a gate run at its first stall: nothing achieved for ``quiet`` game minutes, one battle running
    ``battle`` game minutes, or a retry loop. The stall keeps a bundle under ``folder`` whose save from
    before is the rung itself, so the bundle replays the whole run."""

    def __init__(self, folder, rung_state, quiet, battle):
        from pokesim.scenarios import Gen1Watch, Gen2Watch
        from pokesim.stalls import FRAMES_PER_GAME_MINUTE
        self.kinds, self.minute = (Gen1Watch, Gen2Watch), FRAMES_PER_GAME_MINUTE
        self.folder, self.before, self.quiet, self.battle = folder, (0, rung_state), quiet, battle
        self.watch = self.progress = self.since = self.stall = None

    def __call__(self, run, snap):
        if self.watch is None:
            self.watch, self.progress = self.kinds[run.generation - 1](run), run.frame
        gained, earned = self.watch.observe(snap)
        if gained or earned or run.generation == 2 and snap.started and run.waiting(snap):
            self.progress = run.frame
        marks = self.watch.marks(snap)
        self.since = self.watch.battle_clock(snap, self.since, run.frame)
        quiet = run.frame - self.progress >= self.quiet * self.minute
        hung = self.since is not None and run.frame - self.since >= self.battle * self.minute
        if not (quiet or hung or self.watch.loop):
            return False
        reason = (f'a retry loop: {self.watch.loop}' if self.watch.loop else
                  f'nothing achieved for {self.quiet} game minutes' if quiet else
                  f'a battle ran for {self.battle} game minutes')
        self.stall = _bundle(run, snap, self.folder, self.before, reason, [], run.frame // self.minute, marks,
                             kind='gate')
        return True


def gate_rung(args):
    """Play one rung for the gate. Each rung runs in its own process, since the cartridge and the share
    code pick the policy modules' tables at import."""
    info = json.loads((args.ladder / 'ladder.json').read_text(encoding='utf-8'))
    rom = _cartridges(args.roms).get(info['rom_sha1'])
    if rom is None:
        raise SystemExit(f'no cartridge in {args.roms} has SHA-1 {info["rom_sha1"]}')
    _, code = prepare(rom, info['randomizer'])
    from pokesim.scenarios import gen2_data_root
    args.out.mkdir(parents=True, exist_ok=True)
    state = args.ladder / args.rung / 'start.state'
    data_root = args.data_root or (gen2_data_root() if info['generation'] == 2 else None)
    watch = GateWatch(args.out, state, args.quiet, args.battle_minutes)
    audit = argparse.Namespace(rom=rom, state=state, frames=args.frames, out=args.out / 'run.json', data_root=data_root,
                               seed=7, reseed_goals=True, lead_in=0, randomizer=code, fair_wild_dvs=None)
    result = run_one(audit, watch)
    summary = {'ladder': args.ladder.name, 'rung': args.rung, 'randomizer': code, 'frames': result['frames'],
               'errors': result['errors'], 'stall': watch.stall,
               'waste': round(100 * sum(result['wasted'].values()) / max(result['frames'], 1), 2)}
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=1) + '\n', encoding='utf-8')
    return 0


def compare(results, baseline, points=GATE_WASTE_POINTS):
    """What a gate run did worse than the baseline: a run that failed, a stall on a rung that had none, more
    errors, or a wasted share up by more than ``points``. A rung the baseline lacks is only reported."""
    problems = []
    for result in results:
        name = f'{result["ladder"]}/{result["rung"]}'
        base = baseline.get(name)
        if result.get('failed'):
            problems.append(f'{name}: the run failed, {result["failed"]}')
        elif base is not None:
            if result['stall'] and not base['stall']:
                problems.append(f'{name}: a new stall, {result["stall"]["reason"]}')
            if result['errors'] > base['errors']:
                problems.append(f'{name}: {result["errors"]} errors, {base["errors"]} before')
            if result['waste'] - base['waste'] > points:
                problems.append(f'{name}: {result["waste"]:.1f}% wasted, {base["waste"]:.1f}% before')
    return problems
