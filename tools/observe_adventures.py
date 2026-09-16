"""Record one read-only observation of a running adventure library."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from pokesim.app.cli import RunningApplication


def observe(root, output):
    root = Path(root).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    previous = json.loads(output.read_text()) if output.exists() else {}
    prior = {row['id']: row for row in previous.get('adventures', [])}
    now = time.time()
    report = {'observed_at': now, 'utc': datetime.now(timezone.utc).isoformat(),
              'adventures': [], 'concerns': []}
    app = RunningApplication(root)
    app.client.timeout = 10.0
    try:
        rows = app.request('GET', '/api/v1/adventures')['adventures']
        for row in rows:
            if row['archived']:
                continue
            aid = row['id']
            sample = {'id': aid, 'name': row['name'], 'state': row['state'],
                      'desired_state': row['desired_state'], 'generation': row.get('generation'),
                      'error': row.get('error')}
            report['adventures'].append(sample)
            if row['error']:
                report['concerns'].append(f"{row['name']}: {row['error']}")
            if row['state'] != 'running':
                if row['desired_state'] == 'running':
                    report['concerns'].append(f"{row['name']}: expected running, currently {row['state']}")
                continue
            try:
                state = app.request('GET', f'/games/{aid}/api/state')
                events = app.request('GET', f'/games/{aid}/api/events', params={'limit': 5, 'all': 1})
                game = state.get('game') or {}
                strategy = state.get('strategy') or {}
                sample.update(frame=state.get('frame'), paused=state.get('paused'),
                              health=state.get('health'), stuck_seconds=state.get('stuck_seconds'),
                              glitched=state.get('glitched'), reloads=state.get('reloads'),
                              map=game.get('map_name'), position=[game.get('x'), game.get('y')],
                              badges=game.get('badges'), owned=len(game.get('dex_owned', [])),
                              goal=strategy.get('objective') or strategy.get('goal'),
                              policy_recoveries=strategy.get('recoveries'),
                              policy_action=strategy.get('action'),
                              milestones=strategy.get('milestones'),
                              party=[{'name': p.get('name'), 'level': p.get('level'), 'hp': p.get('hp')}
                                     for p in game.get('party', [])],
                              recent_events=[{k: event.get(k) for k in ('id', 'ts', 'type', 'title')}
                                             for event in events])
                before = prior.get(aid, {})
                if before.get('frame') is not None:
                    sample['frame_change'] = sample['frame'] - before['frame']
                    sample['generation_changed'] = before.get('generation') != sample['generation']
                    if sample['frame_change'] <= 0 and not sample['paused'] and now - previous['observed_at'] >= 30:
                        report['concerns'].append(f"{row['name']}: no frame advance since previous observation")
                if not (sample['health'] or {}).get('ok') or sample['glitched']:
                    report['concerns'].append(f"{row['name']}: emulator health needs inspection")
                if (sample['stuck_seconds'] or 0) > 120:
                    report['concerns'].append(f"{row['name']}: prolonged time in one position, inspect gameplay before declaring a stall")
                states = list((root / 'adventures' / aid / 'states').glob('auto*.state'))
                newest = max(states, key=lambda p: p.stat().st_mtime) if states else None
                sample['latest_autosave'] = newest.name if newest else None
                sample['autosave_age_seconds'] = round(now - newest.stat().st_mtime, 1) if newest else None
            except Exception as error:
                sample['observation_error'] = str(error)
                report['concerns'].append(f"{row['name']}: observation failed: {error}")
        report['interactions'] = app.request('GET', '/api/v1/interactions')
    finally:
        app.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_suffix('.pending')
    pending.write_text(json.dumps(report, indent=2) + '\n')
    pending.replace(output)
    with output.with_suffix('.jsonl').open('a') as history:
        history.write(json.dumps(report) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(observe(args.data_dir, args.output), indent=2))


if __name__ == '__main__':
    main()
