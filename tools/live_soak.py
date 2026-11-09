"""Play a copy of the live adventures on a candidate commit and on the deployed one, and gate the deploy.

    python tools/live_soak.py prepare BACKUP --roms DIR
    python tools/live_soak.py run --candidate SHA --deployed SHA --roms DIR
    python tools/live_soak.py check SHA

``prepare`` takes a cold backup of the managed app (a pre-*.tar.gz from tools/deploy_host.sh) and keeps
each running adventure's latest autosaves and its pokesim.sqlite, with notifications and trades taken
out of the copy. It adds three post-game ladder rungs with every box full and a backlog of League gifts,
and hashes every input into manifest.json.

``run`` builds each commit from a git archive of it, so each plays its own code, and plays identical
copies of the inputs through the real Manager and worker processes for two game hours each, at a fixed
seed, with League gifts and the Mew event on and the coordinator, offers and notifications off. It then
holds the candidate to the deployed commit per adventure and per game hour (see ``invariants``) and
writes reports/<candidate>.json. tools/deploy_host.sh refuses a commit without a passing report.

A commit whose data schema is older than the backup's is refused, since its Manager refuses newer data.
A newer one migrates its own copy. The inputs are hashed before and after, so a run never edits them.

The private inputs and reports live under LIVE_SOAK_ROOT, by default data/live-soak in this checkout.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]

FRAMES_PER_HOUR = 216000
FRAMES = 2 * FRAMES_PER_HOUR
# Adventures played at once by each commit, so the pair plays six.
PARALLEL = 3
POLL_SECONDS = 2
ADVENTURE_TIMEOUT = 40 * 60
SEED = 7
# Catches under one goal in a row with no improvement that count as churn. Live, Yellow caught 1518
# and released 1498 in a day with no new best copy and no new entry.
CHURN_CATCHES = 10
# Gifts the seeded rungs are owed.
BACKLOG = 30
RUNGS = ('red', 'yellow', 'crystal')
RUNG = 'post_game'
# A journal or key-value store may always grow this much a game hour, so a quiet baseline is no trap.
BYTES_FLOOR = 16 * 1024
# Events a gift and release loop cannot fake, as in pokesim/stalls.py.
REAL_PROGRESS = ('badge', 'catch', 'event_return', 'evolve', 'hatch', 'champion', 'trainer', 'level', 'map')
RECEIVED = re.compile(r'^Received (?:[^(]+ \()?(.+?)\)? (?:from|for) ')
RELEASED = re.compile(r'^Said goodbye to a spare (.+?)(?: Lv \d+)?$')
RELOADING = re.compile(r'reloading (\S+)\s*$')
# Settings that reach the network or another adventure. The copy drops them.
PRIVATE_SETTINGS = ('notifications', 'trade_requests', 'manual_trades')


def soak_root():
    return Path(os.environ.get('LIVE_SOAK_ROOT') or ROOT / 'data' / 'live-soak')


def reports_dir():
    return Path(os.environ.get('LIVE_SOAK_REPORTS') or soak_root() / 'reports')


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def hashes(folder):
    folder = Path(folder)
    return {str(path.relative_to(folder)): checksum(path) for path in sorted(folder.rglob('*'))
            if path.is_file() and path.name != 'manifest.json'}


def species_key(name):
    """One key per species for every spelling: SQUIRTLE, MR_MIME, NIDORAN_F, Mr. Mime, Nidoran♀."""
    return re.sub(r"[\s.'’_]", '', str(name).casefold().replace('♀', 'f').replace('♂', 'm'))


# Prepare -------------------------------------------------------------------------------------------

def _keep(member, running):
    """Whether a backup member belongs in the slim copy: the registry, cartridges, game data, and each
    running adventure without its screenshots, sprites, journal saves, logs and stall bundles."""
    name = member.name.removeprefix('./')
    if name in ('app/app.sqlite', 'app/manager.json'):
        return True
    if name.startswith(('app/assets/roms/', 'app/assets/reference/')):
        return True
    parts = name.split('/')
    if len(parts) < 4 or parts[:2] != ['app', 'adventures'] or parts[2] not in running:
        return False
    if parts[3] in ('shots', 'sprites', 'logs', 'stalls', 'runtime.lock'):
        return False
    return not (parts[3] == 'states' and len(parts) > 4 and parts[4].startswith('event-'))


def _trim_autosaves(states, keep=3):
    """Keep the newest autosaves, by the order CheckpointStore resumes from, and the named saves."""
    def order(path):
        stamp = path.stem.removeprefix('auto-v1-')
        return path.stat().st_mtime_ns, int(stamp) if stamp.isdecimal() else 0, path.name
    saves = sorted(states.glob('auto-*.state'), key=order)
    for path in saves[:-keep]:
        path.unlink()
        path.with_suffix('.json').unlink(missing_ok=True)


def scrub_registry(path, running):
    """Take notifications, trades and the stopped adventures out of the copied registry."""
    with sqlite3.connect(path) as db:
        db.executemany('DELETE FROM settings WHERE key=?', [(key,) for key in PRIVATE_SETTINGS])
        marks = ','.join('?' * len(running))
        db.execute(f'DELETE FROM adventures WHERE id NOT IN ({marks})', tuple(running))
        for table in ('interactions', 'trade_offers'):
            db.execute(f'DELETE FROM {table}')
    db.close()


def prepare(args):
    backup = args.backup.resolve()
    out = (args.out or soak_root() / 'inputs' / backup.name.removesuffix('.tar.gz')).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists, remove it or pass --out')
    backup_hash = checksum(backup)
    with tarfile.open(backup) as archive:
        registry = next(member for member in archive if member.name.removeprefix('./') == 'app/app.sqlite')
        scratch = out.parent / f'.{out.name}-registry'
        scratch.mkdir(parents=True, exist_ok=False)
        archive.extract(registry, scratch, filter='data')
        with sqlite3.connect(scratch / 'app' / 'app.sqlite') as db:
            running = sorted(row[0] for row in db.execute(
                "SELECT id FROM adventures WHERE desired_state='running' AND archived=0"))
            schema = db.execute('PRAGMA user_version').fetchone()[0]
        db.close()
        shutil.rmtree(scratch)
    with tarfile.open(backup) as archive:
        archive.extractall(out, members=(member for member in archive if _keep(member, set(running))), filter='data')
    for aid in running:
        _trim_autosaves(out / 'app' / 'adventures' / aid / 'states')
    scrub_registry(out / 'app' / 'app.sqlite', running)
    # The backup's own game data seeds the Gen II rung, so prepare needs no other copy of it.
    reference = max((out / 'app' / 'assets' / 'reference').iterdir(), key=lambda path: path.stat().st_mtime)
    rungs = {}
    for ladder in RUNGS:
        rungs[ladder] = seed_rung(args.ladders / ladder, out / 'rungs' / ladder, args.roms, reference)
    manifest = {'backup': backup.name, 'backup_sha256': backup_hash, 'schema': schema, 'adventures': running,
                'rungs': rungs, 'files': hashes(out)}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    print(f'{len(running)} adventures and {len(rungs)} rungs in {out}, {len(manifest["files"])} files hashed')
    return 0


def _cartridges(folder):
    return {hashlib.sha1(path.read_bytes()).hexdigest(): path for path in sorted(Path(folder).iterdir())
            if path.is_file() and path.stat().st_size <= 0x800000}


def seed_rung(ladder, out, roms, reference):
    """Copy a post-game rung with every box full of seeded copies of species it already owns."""
    info = json.loads((ladder / 'ladder.json').read_text(encoding='utf-8'))
    rom = _cartridges(roms).get(info['rom_sha1'])
    if rom is None:
        raise SystemExit(f'no cartridge in {roms} has SHA-1 {info["rom_sha1"]}')
    out.mkdir(parents=True)
    env = dict(os.environ, POKESIM_GEN1_VARIANT='yellow' if info['game'] == 'yellow' else 'red',
               GEN2_DATA_DIR=str(reference))
    subprocess.run([sys.executable, str(Path(__file__).resolve()), 'seed-rung', str(ladder / RUNG), str(rom),
                    str(info['generation']), info['game'], str(out)], env=env, check=True)
    return {'game': info['game'], 'generation': info['generation'], 'rom_sha1': info['rom_sha1'], 'backlog': BACKLOG}


def seed_rung_state(args):
    """Fill every box of the rung's state. Runs in its own process, since Gen I data depends on the variant."""
    import gzip
    import io
    from pokesim.checkpoints import open_state
    with open_state(args.rung / 'start.state') as handle:
        raw = handle.read()
    rom = args.rom.read_bytes()
    if args.generation == 1:
        from pokecore.emulator import Emulator as CoreEmulator
        from pokesim.ram import BOX_CAPACITY, BOX_COUNT, read_snapshot
        from pokesim.strategy_data import SPECIES
        from pokesim.trade.boxes import write_slot
        from pokesim.trade.event import gift_slot
        from pokesim.yellow import open_emulator
        internal = {entry['dex']: species for species, entry in SPECIES.items() if entry.get('dex')}
        pb = open_emulator(io.BytesIO(rom), default=CoreEmulator, yellow=args.game == 'yellow', window='null',
                           sound_emulated=False)
        try:
            pb.load_state(io.BytesIO(raw))
            snap = read_snapshot(pb.memory, 0)
            owned = sorted(dex for dex in snap.owned if dex in internal)
            for box in range(1, BOX_COUNT + 1):
                for position in range(snap.box_counts[box - 1] + 1, BOX_CAPACITY + 1):
                    dex = owned[(box * BOX_CAPACITY + position) % len(owned)]
                    write_slot(pb.memory, box, position, gift_slot(f'live-soak:{args.game}:{box}:{position}', internal[dex]))
            filled = read_snapshot(pb.memory, 0).box_counts
            output = io.BytesIO()
            pb.save_state(output)
        finally:
            pb.stop(save=False)
    else:
        from pokecore.gen2 import clock
        from pokecore.gen2.ram import read_snapshot
        from pokecore.gen2.resets import box_gift
        from pokesim.gen2.data import GameData
        from pokesim.scenarios import gen2_data_root
        data = GameData.load(gen2_data_root(), args.game)
        pb = clock.boot(str(args.rom), sound=False)
        try:
            pb.load_state(io.BytesIO(raw))
            snap = read_snapshot(pb.memory, data, 0)
            owned = sorted(snap.owned)
            for box, count in enumerate(snap.box_counts):
                for position in range(count, 20):
                    dex = owned[(box * 20 + position) % len(owned)]
                    box_gift(pb.memory, data, dex, f'live-soak:{args.game}:{box}:{position}', box, position)
            filled = read_snapshot(pb.memory, data, 0).box_counts
            output = io.BytesIO()
            pb.save_state(output)
        finally:
            pb.stop(save=False)
    with gzip.open(args.rung / 'start.json') as handle:
        metadata = json.load(handle)
    metadata.pop('sha256', None)
    (args.out / 'start.state').write_bytes(output.getvalue())
    (args.out / 'start.json').write_text(json.dumps(metadata) + '\n', encoding='utf-8')
    print(f'{args.game}: boxes now hold {list(filled)}')
    return 0


# Runner, inside each commit's own tree and environment ---------------------------------------------

def _readonly(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=30)


def _kv_bytes(db):
    return db.execute('SELECT COALESCE(SUM(LENGTH(k) + LENGTH(v)), 0) FROM kv').fetchone()[0]


def _goal(db):
    """The collection project the policy works on, by its key, from the copy each autosave keeps."""
    row = db.execute("SELECT v FROM kv WHERE k='policy_state'").fetchone()
    try:
        project = (json.loads(row[0]) or {}).get('collection', {}).get('project') if row else None
    except (TypeError, ValueError, AttributeError):
        return 'unknown'
    if not project:
        return 'none'
    return str(project.get('key') or project.get('method') or 'unknown')


def _held(game, dex_of):
    """The best DV tail kept of each species, lower is better, and every species held."""
    from pokesim.investment import assessment
    best = {}
    for mon in [*(game or {}).get('party', []), *((game or {}).get('storage') or {}).get('pokemon', [])]:
        if mon.get('egg'):
            continue
        dex = dex_of(mon)
        if not dex:
            continue
        tail = assessment(mon)['dv_top_percent']
        tail = 100.0 if tail is None else tail
        best[dex] = min(best.get(dex, 100.0), tail)
    return best


class Catches:
    """Each catch from capture_receipts, with the goal it ran under and whether it improved the PC.

    A catch improves the PC when it becomes the best kept copy of its species by DV tail, or is the
    first one kept, which covers a new Pokédex entry. The worker reports a catch a moment after it
    writes the receipt, so a catch seen at one poll is judged at the next, against the poll before it.
    """

    def __init__(self):
        self.rows, self.waiting, self.goal, self.credited = [], [], 'none', {}
        self.older = self.latest = None

    def poll(self, receipts, goal, best):
        if self.latest is None:
            # Catches before the first poll are judged against the PC as first seen.
            self.latest = best
        older = self.older if self.older is not None else self.latest
        for fingerprint, dex, recorded_at in self.waiting:
            # One better copy is credited to one catch, though the next catch is judged against the same poll.
            bar = min(older.get(dex, float('inf')), self.credited.get(dex, float('inf')))
            improved = dex in best and best[dex] < bar - 1e-9
            if improved:
                self.credited[dex] = best[dex]
            self.rows.append({'at': recorded_at, 'dex': dex, 'goal': self.goal, 'improved': improved,
                              'gift': fingerprint.startswith('gift-event:')})
        self.waiting, self.goal = list(receipts), goal
        self.older, self.latest = self.latest, best

    def finish(self, best):
        self.poll([], self.goal, best)
        return self.rows


def _names(manager, adventure):
    """Every spelling of each species name, by its key, for the version."""
    if adventure['version'] in ('gold', 'silver', 'crystal'):
        from pokesim.gen2.data import GameData
        data = GameData.load(manager.assets.game_data_dir, adventure['version'])
        return {species_key(entry['name']): entry['dex'] for entry in data.species.values()
                if 1 <= entry.get('dex', 0) <= 251}
    return gen1_names()


def gen1_names():
    """Gen I gifts spell a species as strategy data does, SQUIRTLE or MR_MIME, and releases as RAM does."""
    from pokesim.ram import SPECIES_NAMES
    from pokesim.strategy_data import SPECIES
    names = {species_key(entry['name']): entry['dex'] for entry in SPECIES.values() if entry.get('dex')}
    names.update({species_key(name): SPECIES[species]['dex'] for species, name in SPECIES_NAMES.items()
                  if species in SPECIES and SPECIES[species].get('dex')})
    return names


def _dex_of(version):
    if version in ('gold', 'silver', 'crystal'):
        return lambda mon: mon.get('dex') or mon.get('species')
    from pokesim.strategy_data import SPECIES
    return lambda mon: mon.get('dex') or SPECIES.get(mon.get('species'), {}).get('dex')


def _worker_log(folder):
    lines = []
    for name in ('worker.previous.log', 'worker.log'):
        path = folder / 'logs' / name
        if path.exists():
            lines += path.read_text(encoding='utf-8', errors='replace').splitlines()
    reloads, errors = {}, []
    for line in lines:
        if match := RELOADING.search(line):
            reloads[match.group(1)] = reloads.get(match.group(1), 0) + 1
        if ' ERROR ' in line or line.startswith('Traceback'):
            errors.append(line[:300])
    return reloads, errors


def play_one(manager, aid, frames, progress):
    from pokesim.app.registry import identifier
    adventure = manager.registry.adventure(aid)
    folder = manager.registry.root / 'adventures' / aid
    settings = {**adventure['settings'], 'speed': 0, 'seed': SEED, 'league_rewards': True, 'mew_event': True,
                'auto_start': False}
    manager.registry.update(aid, settings=settings)
    database = folder / 'pokesim.sqlite'
    with _readonly(database) as db:
        first_event = db.execute('SELECT COALESCE(MAX(id), 0) FROM events').fetchone()[0]
        receipts_before = {row[0] for row in db.execute('SELECT fingerprint FROM capture_receipts')} if db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='capture_receipts'").fetchone() else set()
        kv_before = _kv_bytes(db)
    db.close()
    result = {'id': aid, 'name': adventure['name'], 'version': adventure['version'], 'failed': None}
    names, dex_of, catches = _names(manager, adventure), _dex_of(adventure['version']), Catches()
    began = time.monotonic()
    manager.registry.request_lifecycle(aid, 'start', identifier())
    manager.start_adventure(aid)
    start = end = None
    held_start = held_end = None
    help_reason = None
    seen = set(receipts_before)
    best = {}
    try:
        while True:
            if time.monotonic() - began > ADVENTURE_TIMEOUT:
                result['failed'] = f'under {frames} frames in {ADVENTURE_TIMEOUT} seconds'
                break
            try:
                status = manager.supervisor.child(aid).request('GET', '/api/state?storage=1')
            except RuntimeError:
                row = manager.registry.adventure(aid)
                if row['state'] == 'failed':
                    result['failed'] = f'the worker failed, {row.get("error")}'
                    break
                time.sleep(POLL_SECONDS)
                continue
            frame, game = status.get('frame') or 0, status.get('game')
            if start is None:
                if not game:
                    time.sleep(POLL_SECONDS)
                    continue
                start, held_start = frame, len(game.get('party', [])) + len(((game.get('storage') or {}).get('pokemon')) or [])
                # A new adventure writes its whole store on boot, which is not growth.
                with _readonly(database) as db:
                    kv_before = _kv_bytes(db)
                db.close()
                result['status_keys'] = sorted(status)
                result['sample_mon'] = next(iter(((game.get('storage') or {}).get('pokemon')) or game.get('party') or [{}]), {})
            best = _held(game, dex_of)
            with _readonly(database) as db:
                fresh = [row for row in db.execute('SELECT fingerprint, dex, recorded_at FROM capture_receipts '
                                                   'ORDER BY recorded_at') if row[0] not in seen]
                goal = _goal(db)
            db.close()
            seen.update(row[0] for row in fresh)
            catches.poll(fresh, goal, best)
            help_reason = (status.get('help_request') or {}).get('reason')
            end = frame
            held_end = len(game.get('party', [])) + len(((game.get('storage') or {}).get('pokemon')) or []) if game else held_end
            if frame - start >= frames:
                break
            time.sleep(POLL_SECONDS)
    finally:
        manager.registry.request_lifecycle(aid, 'stop', identifier())
        manager.supervisor.stop(aid)
    with _readonly(database) as db:
        events = db.execute('SELECT id, ts, type, title, LENGTH(title) + LENGTH(COALESCE(body, \'\')) FROM events '
                            'WHERE id > ? ORDER BY id', (first_event,)).fetchall()
        receipts = [row for row in db.execute('SELECT fingerprint, dex, recorded_at FROM capture_receipts ORDER BY recorded_at')
                    if row[0] not in receipts_before]
        kv_after = _kv_bytes(db)
        ledger = db.execute("SELECT v FROM kv WHERE k='league-rewards-v1'").fetchone()
    db.close()
    reloads, errors = _worker_log(folder)
    result.update(frames=(end or 0) - (start or 0), wall_seconds=round(time.monotonic() - began, 1),
                  events=[[row[0], row[1], row[2], row[3]] for row in events],
                  journal_bytes=sum(row[4] for row in events), kv_bytes=kv_after - kv_before,
                  receipts=[list(row) for row in receipts], catches=catches.finish(best),
                  held_start=held_start, held_end=held_end, reloads=reloads, errors=len(errors),
                  error_lines=errors[:5], help=help_reason, names=names,
                  ledger=json.loads(ledger[0]) if ledger else None)
    progress(f'{adventure["name"]}: {result["frames"]} frames in {result["wall_seconds"]}s'
             + (f', failed: {result["failed"]}' if result['failed'] else ''))
    return result


def add_rung(manager, rung, info, rom):
    """Create a seeded rung as a new adventure with its gift backlog, as the create route would."""
    from pokesim import rewards
    from pokesim.app.registry import identifier
    from pokesim.checkpoints import CheckpointStore
    from pokesim.store import Store
    asset = manager.assets.install_rom(rom.read_bytes())
    settings = manager.validate_adventure_settings({'league_rewards': True, 'mew_event': True, 'seed': SEED})
    adventure = manager.registry.create(f'Soak {rung.name}', asset['id'], settings, identifier())
    folder = manager.registry.root / 'adventures' / adventure['id']
    metadata = json.loads((rung / 'start.json').read_text(encoding='utf-8'))
    CheckpointStore(folder / 'states').write_checkpoint((rung / 'start.state').read_bytes(), metadata)
    store = Store(folder)
    try:
        with store.lock, store.db:
            # A version 2 ledger, so the worker's upgrade of an old one does not settle the backlog as skipped.
            ledger = rewards.ledger(store.db)
            delivered = ledger.get('delivered', 0)
            rewards.save(store.db, {**ledger, 'version': 2, 'seed': f'live-soak:{rung.name}', 'delivered': delivered,
                                    'earned': delivered + info['backlog'], 'observed': ledger.get('observed', 0),
                                    'skipped': ledger.get('skipped', 0)})
    finally:
        store.close()
    return adventure['id']


def runner(args):
    from pokesim.app.manager import Manager
    manifest = json.loads((args.inputs / 'manifest.json').read_text(encoding='utf-8'))
    manager = Manager(args.work / 'app', game_data_dir=args.game_data)
    results = []
    try:
        manager.registry.set_setting('max_running', args.parallel)
        roms = _cartridges(args.roms)
        ids = list(manifest['adventures'])
        for name, info in manifest['rungs'].items():
            ids.append(add_rung(manager, args.work / 'rungs' / name, info, roms[info['rom_sha1']]))

        def play(aid):
            return play_one(manager, aid, args.frames, lambda line: print(line, flush=True))
        with ThreadPoolExecutor(args.parallel) as pool:
            results = list(pool.map(play, ids))
    finally:
        manager.close()
    (args.work / 'results.json').write_text(json.dumps(results) + '\n', encoding='utf-8')
    return 0


# Invariants ----------------------------------------------------------------------------------------

def repeated_sequence(titles, times=5, longest=20):
    """The shortest run of 2 to ``longest`` titles that repeats ``times`` times in a row, or None."""
    for length in range(2, longest + 1):
        span = length * times
        for start in range(0, len(titles) - span + 1):
            window = titles[start:start + length]
            if len(set(window)) > 1 and all(titles[start + k * length:start + (k + 1) * length] == window
                                            for k in range(1, times)):
                return window
    return None


def churned_species(result, limit=3):
    """Species received and released ``limit`` times with no real progress between, by Pokédex number.

    Receipts are gifts in the journal and catches in capture_receipts, since a catch of a species
    already registered writes no journal entry.
    """
    names = result['names']
    timeline = [(row[1], row[2], row[3]) for row in result['events']]
    timeline += [(at, 'caught', dex) for fingerprint, dex, at in result['receipts'] if not fingerprint.startswith('gift-event:')]
    timeline += [(row['at'], 'improved', row['dex']) for row in result['catches'] if row['improved']]
    received, cycles, worst = {}, {}, {}
    for _, kind, subject in sorted(timeline, key=lambda row: row[0]):
        if kind in REAL_PROGRESS or kind == 'improved':
            received, cycles = {}, {}
            continue
        dex = subject if kind == 'caught' else None
        if kind in ('obtain', 'release'):
            match = (RECEIVED if kind == 'obtain' else RELEASED).match(subject)
            dex = names.get(species_key(match.group(1))) if match else None
        if dex is None:
            continue
        if kind == 'release':
            if received.get(dex):
                received[dex] -= 1
                cycles[dex] = cycles.get(dex, 0) + 1
                worst[dex] = max(worst.get(dex, 0), cycles[dex])
        else:
            received[dex] = received.get(dex, 0) + 1
    return {dex: count for dex, count in sorted(worst.items()) if count >= limit}


def goal_churn(catches, limit=CHURN_CATCHES):
    """Per goal: catches, improvements, their ratio and the longest run of catches with no improvement.
    Gifts are left out, since the goal did not choose them."""
    goals = {}
    for row in catches:
        if row['gift']:
            continue
        goal = goals.setdefault(row['goal'], {'catches': 0, 'improvements': 0, 'flat': 0, 'longest_flat': 0})
        goal['catches'] += 1
        if row['improved']:
            goal['improvements'] += 1
            goal['flat'] = 0
        else:
            goal['flat'] += 1
            goal['longest_flat'] = max(goal['longest_flat'], goal['flat'])
    for goal in goals.values():
        goal.pop('flat')
        goal['catches_per_improvement'] = round(goal['catches'] / goal['improvements'], 2) if goal['improvements'] else None
        goal['churn'] = goal['longest_flat'] >= limit
    return goals


def measure(result):
    """The numbers the invariants compare, per game hour where a rate makes sense."""
    hours = max(result.get('frames') or 0, 1) / FRAMES_PER_HOUR
    kinds = {}
    for row in result['events']:
        kinds[row[2]] = kinds.get(row[2], 0) + 1
    caught = sum(not fingerprint.startswith('gift-event:') for fingerprint, _, _ in result['receipts'])
    releases = kinds.get('release', 0)
    journaled = kinds.get('obtain', 0) + caught
    # A Pokémon that came in without a receipt or an entry still shows in the count held.
    inferred = (result['held_end'] or 0) - (result['held_start'] or 0) + releases
    obtains = max(journaled, len(result['receipts']), inferred)
    improvements = sum(row['improved'] for row in result['catches'] if not row['gift'])
    progress = sum(kinds.get(kind, 0) for kind in REAL_PROGRESS) + improvements
    return {'game_hours': round(hours, 3), 'releases': round(releases / hours, 2), 'obtains': round(obtains / hours, 2),
            'catches': caught, 'improvements': improvements, 'progress': round(progress / hours, 2),
            'reloads': round(sum(result['reloads'].values()) / hours, 2),
            'most_reloaded': max(result['reloads'].items(), key=lambda item: item[1], default=(None, 0)),
            'bytes': round((result['journal_bytes'] + max(result['kv_bytes'], 0)) / hours),
            'repeated_titles': repeated_sequence([row[3] for row in result['events']]),
            'churned_species': churned_species(result), 'goals': goal_churn(result['catches'])}


def invariants(candidate, baseline):
    """What the candidate did worse than the deployed commit on one adventure, or absolutely wrong."""
    problems = []
    name = candidate['name']
    if candidate.get('failed'):
        return [f'{name}: the run failed, {candidate["failed"]}']
    c, b = measure(candidate), measure(baseline) if baseline and not baseline.get('failed') else None
    for key in ('releases', 'obtains'):
        if b is not None and c[key] > max(2 * b[key], b[key] + 5):
            problems.append(f'{name}: {c[key]} {key} a game hour, {b[key]} on the deployed commit')
    for dex, count in c['churned_species'].items():
        problems.append(f'{name}: received and released #{dex} {count} times with no real progress between')
    if b is not None and c['progress'] < 0.5 * b['progress']:
        problems.append(f'{name}: {c["progress"]} real progress a game hour, {b["progress"]} on the deployed commit')
    if b is not None and c['reloads'] > b['reloads'] + 2:
        problems.append(f'{name}: {c["reloads"]} reloads a game hour, {b["reloads"]} on the deployed commit')
    save, count = c['most_reloaded']
    if count >= 3:
        problems.append(f'{name}: reloaded {save} {count} times')
    if b is not None and c['bytes'] > max(2 * b['bytes'], BYTES_FLOOR):
        problems.append(f'{name}: the journal and store grew {c["bytes"]} bytes a game hour, {b["bytes"]} on the deployed commit')
    if c['repeated_titles']:
        problems.append(f'{name}: the journal repeated {c["repeated_titles"]} 5 times in a row')
    for goal, row in c['goals'].items():
        if row['churn']:
            problems.append(f'{name}: {row["longest_flat"]} catches in a row under {goal} with no better copy or new entry')
    return problems


def gate_shape(result):
    """One result in the shape stage_ladder.compare reads."""
    if result.get('failed'):
        return {'ladder': 'soak', 'rung': result['name'], 'failed': result['failed']}
    return {'ladder': 'soak', 'rung': result['name'], 'stall': {'reason': result['help']} if result['help'] else None,
            'errors': result['errors'], 'waste': 0}


def judge(candidate, deployed):
    from tools.stage_ladder import compare
    base = {item['id']: item for item in deployed}
    problems = compare([gate_shape(item) for item in candidate],
                       {f'soak/{item["name"]}': gate_shape(item) for item in deployed if not item.get('failed')})
    rows = []
    for item in candidate:
        problems += invariants(item, base.get(item['id']) or next(
            (other for other in deployed if other['name'] == item['name']), None))
        rows.append({'id': item['id'], 'name': item['name'], 'version': item['version'], 'failed': item.get('failed'),
                     'candidate': None if item.get('failed') else measure(item),
                     'deployed': (lambda other: None if not other or other.get('failed') else measure(other))(
                         base.get(item['id']) or next((o for o in deployed if o['name'] == item['name']), None))})
    return problems, rows


# Run -----------------------------------------------------------------------------------------------

def schema_of(tree):
    text = (tree / 'pokesim' / 'app' / 'registry.py').read_text(encoding='utf-8')
    match = re.search(r'^SCHEMA = (\d+)$', text, re.M)
    if not match:
        raise SystemExit(f'no SCHEMA in {tree}/pokesim/app/registry.py')
    return int(match.group(1))


def reference_revision(tree):
    text = (tree / 'pokesim' / 'game_data.py').read_text(encoding='utf-8')
    return re.search(r"^SOURCE_REVISION = '([0-9a-f]+)'$", text, re.M).group(1)


def build_tree(sha, folder):
    folder.mkdir(parents=True)
    archive = subprocess.run(['git', '-C', str(ROOT), 'archive', sha], check=True, capture_output=True).stdout
    subprocess.run(['tar', 'x', '-C', str(folder)], input=archive, check=True)
    return folder


def full_sha(sha):
    return subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', f'{sha}^{{commit}}'], check=True,
                          capture_output=True, text=True).stdout.strip()


def run(args):
    if os.environ.get('POKESIM_LOAD_GATE_HEAVY') != '1':
        # The pair plays six workers at once, so nothing else may run beside it.
        command = ['sh', str(ROOT / 'tools' / 'load_gate.sh'), 'heavy', sys.executable, str(Path(__file__).resolve()),
                   *args.argv]
        return subprocess.run(command, check=False).returncode
    inputs = (args.inputs or max((soak_root() / 'inputs').glob('*/manifest.json'), key=os.path.getmtime).parent).resolve()
    manifest = json.loads((inputs / 'manifest.json').read_text(encoding='utf-8'))
    before = hashes(inputs)
    if before != manifest['files']:
        raise SystemExit(f'{inputs} no longer matches its manifest, prepare it again')
    candidate, deployed = full_sha(args.candidate), full_sha(args.deployed)
    work = (args.work or soak_root() / 'runs' / f'{candidate[:12]}-{time.strftime("%Y%m%d-%H%M%S")}').resolve()
    work.mkdir(parents=True)
    began = time.monotonic()
    roles = {'candidate': candidate, 'deployed': deployed}
    for role, sha in roles.items():
        tree = build_tree(sha, work / role / 'tree')
        schema = schema_of(tree)
        if schema < manifest['schema']:
            raise SystemExit(f'{sha[:7]} has data schema {schema}, older than the backup\'s {manifest["schema"]}, refusing')
        shutil.copytree(inputs / 'app', work / role / 'app')
        shutil.copytree(inputs / 'rungs', work / role / 'rungs')
    env = {key: value for key, value in os.environ.items()
           if key not in ('VIRTUAL_ENV', 'POKESIM_GEN1_VARIANT', 'RANDOMIZER', 'ROM_PATH', 'TRADING_URL', 'NTFY_URL')}

    def play(role):
        folder = work / role
        reference = folder / 'app' / 'assets' / 'reference' / reference_revision(folder / 'tree')
        role_env = dict(env, UV_PROJECT_ENVIRONMENT=str(folder / 'env'), POKESIM_REVISION=roles[role],
                        GAME_DATA_DIR=str(reference))
        subprocess.run(['uv', 'sync', '--locked', '--no-dev', '--project', str(folder / 'tree'), '-q'],
                       env=role_env, cwd=folder / 'tree', check=True)
        command = ['nice', '-n', str(args.nice), 'uv', 'run', '--locked', '--no-dev', '--no-sync', '--project',
                   str(folder / 'tree'), 'python', str(Path(__file__).resolve()), 'runner', str(inputs), str(folder),
                   str(args.roms), '--frames', str(args.frames), '--parallel', str(args.parallel)]
        if args.game_data:
            command += ['--game-data', str(args.game_data)]
        with open(folder / 'runner.log', 'w', encoding='utf-8') as log:
            code = subprocess.run(command, env=role_env, cwd=folder / 'tree', stdout=log, stderr=subprocess.STDOUT,
                                  check=False).returncode
        if code or not (folder / 'results.json').exists():
            raise SystemExit(f'the {role} runner exited {code}, see {folder / "runner.log"}')
        return json.loads((folder / 'results.json').read_text(encoding='utf-8'))

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(play, roles))
    run_info = {'candidate': candidate, 'deployed': deployed, 'frames': args.frames,
                'wall_seconds': round(time.monotonic() - began, 1), 'inputs_unchanged': hashes(inputs) == before,
                'inputs': {'folder': str(inputs), 'backup_sha256': manifest['backup_sha256'],
                           'manifest_sha256': checksum(inputs / 'manifest.json')}}
    (work / 'run.json').write_text(json.dumps(run_info, indent=1) + '\n', encoding='utf-8')
    return write_report(work)


def rejudge(args):
    """Judge a finished run again, after a change to the invariants, without playing it again."""
    return write_report(args.work.resolve())


def write_report(work):
    run_info = json.loads((work / 'run.json').read_text(encoding='utf-8'))
    played = {role: json.loads((work / role / 'results.json').read_text(encoding='utf-8'))
              for role in ('candidate', 'deployed')}
    candidate, deployed = run_info['candidate'], run_info['deployed']
    problems, rows = judge(played['candidate'], played['deployed'])
    if not run_info['inputs_unchanged']:
        problems.append(f'the run changed its inputs in {run_info["inputs"]["folder"]}')
    reports = reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f'{candidate}.json'
    # A rejudge of the same run keeps its attempt. A new run of the same commit is the next attempt.
    attempt = run_info.get('attempt')
    if attempt is None:
        attempt = 1
        if path.exists():
            attempt = json.loads(path.read_text(encoding='utf-8')).get('attempt', 0) + 1
        run_info['attempt'] = attempt
        (work / 'run.json').write_text(json.dumps(run_info, indent=1) + '\n', encoding='utf-8')
    report = {'commit': candidate, 'deployed': deployed, 'frames': run_info['frames'], 'attempt': attempt,
              'wall_seconds': run_info['wall_seconds'], 'baseline': deployed, 'passed': not problems,
              'inputs': {**run_info['inputs'], 'folder': Path(run_info['inputs']['folder']).name},
              'schema': 'each commit runs from a git archive of itself, and one older than the data is refused',
              'churn_catches': CHURN_CATCHES, 'problems': problems, 'results': rows, 'work': str(work)}
    path.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    (work / 'gate-report.json').write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    for row in rows:
        c = row['candidate']
        if c:
            print(f'{row["name"]:<28} {c["releases"]:7.1f} rel/h {c["obtains"]:7.1f} obt/h {c["progress"]:6.1f} prog/h '
                  f'{c["reloads"]:5.1f} rel/h {c["bytes"]:8d} B/h {c["catches"]:4d} caught {c["improvements"]:3d} better')
    for problem in problems:
        print(problem)
    print(f'{"passed" if not problems else "failed"} in {report["wall_seconds"]}s, attempt {attempt}, report in {path}')
    return 0 if not problems else 1


def check(args):
    """Exit 0 when a passing report names this commit. tools/deploy_host.sh runs this with no dependencies."""
    path = (args.reports or reports_dir()) / f'{args.sha}.json'
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        print(f'live soak: no report for {args.sha[:7]} in {path.parent}', file=sys.stderr)
        return 1
    if report.get('commit') != args.sha or report.get('passed') is not True:
        print(f'live soak: the report for {args.sha[:7]} did not pass ({len(report.get("problems") or [])} problems)',
              file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    preparing = commands.add_parser('prepare', help='keep a slim, hashed copy of a cold backup and seeded rungs')
    preparing.add_argument('backup', type=Path)
    preparing.add_argument('--roms', type=Path, required=True, help='a folder holding the clean cartridges')
    preparing.add_argument('--ladders', type=Path, default=ROOT / 'data' / 'ladder')
    preparing.add_argument('--out', type=Path)
    preparing.set_defaults(action=prepare)
    seeding = commands.add_parser('seed-rung', help=argparse.SUPPRESS)
    seeding.add_argument('rung', type=Path)
    seeding.add_argument('rom', type=Path)
    seeding.add_argument('generation', type=int)
    seeding.add_argument('game')
    seeding.add_argument('out', type=Path)
    seeding.set_defaults(action=seed_rung_state)
    running = commands.add_parser('run', help='play the inputs on both commits and write the report')
    running.add_argument('--candidate', required=True)
    running.add_argument('--deployed', required=True)
    running.add_argument('--roms', type=Path, required=True)
    running.add_argument('--inputs', type=Path, help='a prepared folder, by default the newest')
    running.add_argument('--game-data', type=Path, help='game data to install when a commit wants a revision the '
                         'backup does not hold')
    running.add_argument('--frames', type=int, default=FRAMES)
    running.add_argument('--parallel', type=int, default=PARALLEL, help='adventures each commit plays at once')
    running.add_argument('--nice', type=int, default=10)
    running.add_argument('--work', type=Path)
    running.set_defaults(action=run)
    inner = commands.add_parser('runner', help=argparse.SUPPRESS)
    inner.add_argument('inputs', type=Path)
    inner.add_argument('work', type=Path)
    inner.add_argument('roms', type=Path)
    inner.add_argument('--game-data', type=Path)
    inner.add_argument('--frames', type=int, default=FRAMES)
    inner.add_argument('--parallel', type=int, default=PARALLEL)
    inner.set_defaults(action=runner)
    judging = commands.add_parser('rejudge', help='judge a finished run folder again and rewrite its report')
    judging.add_argument('work', type=Path)
    judging.set_defaults(action=rejudge)
    checking = commands.add_parser('check', help='exit 0 when a passing report names the commit')
    checking.add_argument('sha')
    checking.add_argument('--reports', type=Path)
    checking.set_defaults(action=check)
    args = parser.parse_args(argv)
    args.argv = list(sys.argv[1:] if argv is None else argv)
    return args.action(args)


if __name__ == '__main__':
    if __package__ in (None, '') and sys.argv[1:2] in (['run'], ['prepare'], ['rejudge']):
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
