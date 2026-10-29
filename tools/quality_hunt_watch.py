"""Check that a Gold, Silver or Crystal adventure goes back to better-DV hunts once its training runs out.

    ssh HOST "docker exec -i CONTAINER python - collect SITE" < tools/quality_hunt_watch.py \\
        | python3 tools/quality_hunt_watch.py judge STATE_JSON

``collect`` runs inside the app container and only reads. For each running Gen II adventure it prints
the trainees left, the play clock, the policy's decision count, its better-DV hunt counts and the
current hunt from the saved policy, and the capture receipts. ``judge`` runs on the watch host. Once an
adventure has no trainee left, a better-DV hunt must start within its next 6 game hours. The state
file keeps the game hour, wall time, decision count and hunt counts at which each adventure was first
seen without a trainee, so the check carries across nights.

A trainee follows ``trainee()`` in pokesim/gen2/postgame.py: the best copy of each held species by
potential, below level 100, not about matched by a level 100 copy, not standing down, and not boxed
while a full party meets full boxes. The wait for better-DV hunts below level 80 is left out, so a run
whose last trainees wait on their hunts is not counted yet. The watch runs once a night, so a hunt
start is placed from the policy's decisions, or from its first catch for a hunt that already ended,
both spread evenly between the first sighting and now.
"""
import json
import sys
import time
from pathlib import Path

GEN2 = {'gold', 'silver', 'crystal'}
LIMIT_HOURS = 6
FRAMES_PER_HOUR = 60 * 60 * 60
SHOWN = 3
# MIN_UPGRADE of pokesim/investment.py, which needs Gen I game data the container keeps elsewhere.
MIN_UPGRADE = 0.02


def trainees(mons, standing_down, sealed, min_upgrade):
    """Names and levels of the copies the postgame would still train, per ``trainee()``."""
    groups = {}
    for mon in mons:
        if not mon.get('egg'):
            groups.setdefault(mon['species'], []).append(mon)
    left = []
    for copies in groups.values():
        best = max(copies, key=lambda mon: (mon.get('potential_power') or 0, mon['level']))
        if best['level'] >= 100 or best.get('box') is not None and sealed:
            continue
        top = max((mon.get('potential_power') or 0 for mon in copies if mon['level'] >= 100), default=None)
        if top is not None and not best.get('perfect_dvs') and (best.get('potential_power') or 0) <= top * (1 + min_upgrade):
            continue
        if standing_down([best['trainer_id'], list(best['dvs'])]):
            continue
        left.append([best['name'], best['level']])
    return sorted(left, key=lambda row: -row[1])


def collect(site):
    """One row per Gen II adventure, read from its saved policy and the app's own pages."""
    import os
    import sqlite3
    import urllib.request

    from pokesim.gen2.standdown import BACKOFF, train_key
    from pokesim.planning.monitor import Monitor

    root, port = Path(os.environ.get('DATA_DIR', '/data')), os.environ.get('PORT', '8000')

    def page(aid, path):
        request = urllib.request.Request(f'http://localhost:{port}/games/{aid}{path}',
                                         headers={'Host': site, 'X-Forwarded-Proto': 'https'})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    rows = []
    for path in sorted(root.glob('adventures/*/adventure.json')):
        meta = json.loads(path.read_text(encoding='utf-8'))
        if meta.get('version') not in GEN2 or meta.get('archived'):
            continue
        row = {'id': meta['id'], 'name': meta.get('name'), 'version': meta['version'], 'state': meta.get('state')}
        rows.append(row)
        if row['state'] != 'running':
            continue
        db = sqlite3.connect(f'file:{path.parent / "pokesim.sqlite"}?mode=ro', uri=True)
        try:
            saved = json.loads(db.execute("SELECT v FROM kv WHERE k='policy_state'").fetchone()[0])
            captures = db.execute('SELECT dex, recorded_at FROM capture_receipts').fetchall()
        finally:
            db.close()
        state, pc = page(meta['id'], '/api/state'), page(meta['id'], '/api/pokedex/status?view=pc')
        collection, decisions = saved.get('collection') or {}, saved.get('decisions') or 0
        monitor = Monitor(collection, backoff=BACKOFF)
        storage = pc.get('storage') or {}
        party = pc.get('party') or []
        # The same test as the policy's no_room, less the release visit it may still find.
        sealed = (len(party) >= 6 and not storage.get('can_catch')
                  and all(count >= 20 for count in storage.get('box_counts') or [20]))
        postgame = collection.get('postgame') or {}
        activity = postgame.get('activity') or {}
        row.update(hours=(state.get('play_clock') or {}).get('seconds', 0) / 3600, wall=time.time(),
                   decisions=decisions, can_catch=bool(storage.get('can_catch')),
                   trainees=trainees(party + (storage.get('pokemon') or []),
                                     lambda identity: monitor.standing_down(train_key(identity), decisions),
                                     sealed, MIN_UPGRADE),
                   searches=postgame.get('searches') or {},
                   hunt={'species': activity['species'], 'started': activity.get('started', decisions)}
                   if activity.get('kind') == 'quality' else None,
                   captures=[[dex, at] for dex, at in captures])
    json.dump(rows, sys.stdout)


def spread(since, now, key, value):
    """The game hour at ``value`` of ``key``, spread evenly between the first sighting and now."""
    span = now[key] - since[key]
    if span <= 0:
        return now['hours']
    return since['hours'] + (now['hours'] - since['hours']) * min(1, max(0, (value - since[key]) / span))


def first_hunt(since, row):
    """The game hour the first better-DV hunt since ``since`` started, True when one ran at an unknown hour, or None."""
    starts = []
    if row.get('hunt'):
        starts.append(spread(since, row, 'decisions', row['hunt']['started']))
    grown = {int(sid) for sid, count in (row.get('searches') or {}).items()
             if count > (since.get('searches') or {}).get(sid, 0)}
    if grown:
        caught = [at for dex, at in row.get('captures') or () if dex in grown and at > since['wall']]
        if caught:
            starts.append(spread(since, row, 'wall', min(caught)))
    if starts:
        return min(starts)
    return True if grown else None


def judge(rows, saved):
    """Lines to print, whether the check failed, and the state to keep."""
    lines, failed, kept, qualified = [], False, {}, 0
    for row in rows:
        title = f'{row.get("name")} ({row["version"].title()})'
        if row.get('state') != 'running':
            lines.append(f'{title}: {row.get("state")}, skipped')
            if row['id'] in saved:
                kept[row['id']] = saved[row['id']]
            continue
        if row['trainees']:
            shown = ', '.join(f'{name} {level}' for name, level in row['trainees'][:SHOWN])
            lines.append(f'{title}: {len(row["trainees"])} trainees left, such as {shown}')
            continue
        qualified += 1
        since = saved.get(row['id']) or {key: row[key] for key in ('hours', 'wall', 'decisions', 'searches')}
        kept[row['id']] = since
        elapsed = row['hours'] - since['hours']
        start = since.get('proven')
        if start is None:
            start = first_hunt(since, row)
            if start is True:
                # A hunt that ended without a catch. Its start is only known to be before now.
                start = row['hours']
        when = f'training ran out by game hour {since["hours"]:.1f}'
        if start is None and elapsed < LIMIT_HOURS:
            lines.append(f'{title}: {when}, no quality hunt yet after {elapsed:.1f} of {LIMIT_HOURS} game hours')
        elif start is None:
            reason = '' if row.get('can_catch') else ', and its boxes are full so it cannot catch'
            lines.append(f'{title}: FAILED, {when} and no quality hunt started in {elapsed:.1f} game hours{reason}')
            failed = True
        elif start - since['hours'] <= LIMIT_HOURS:
            since['proven'] = start
            lines.append(f'{title}: {when}, quality hunt started {start - since["hours"]:.1f} game hours later')
        else:
            lines.append(f'{title}: FAILED, {when} and the first quality hunt started '
                         f'{start - since["hours"]:.1f} game hours later, past the {LIMIT_HOURS} hour limit')
            failed = True
    if not qualified:
        lines.append('no Gen 2 adventure has run out of trainees yet')
    return lines, failed, kept


def main(argv):
    if argv[1:2] == ['collect']:
        collect(argv[2])
        return 0
    if argv[1:2] != ['judge']:
        print(__doc__)
        return 2
    path = Path(argv[2])
    saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    lines, failed, kept = judge(json.load(sys.stdin), saved)
    print('\n'.join(lines))
    path.write_text(json.dumps(kept, indent=1, sort_keys=True), encoding='utf-8')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
