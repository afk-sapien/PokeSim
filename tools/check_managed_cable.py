"""Exercise private worker processes and real cartridge trading on disposable copies."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time

from pokesim.app.supervisor import Child
from pokesim.checkpoints import CheckpointStore
from pokesim.interactions.cable import checked
from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan

A = 'a' * 32
B = 'b' * 32


def exercise(root, fixtures, roms, game_data, abort=False, progress=print):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    children = {}
    bootstraps = {}
    tid, attempt, plan_digest = 'c' * 32, 'd' * 32, 'integration-plan-v1'
    report = {'mode': 'abort' if abort else 'commit', 'status': 'running'}
    for aid, edition in ((A, 'red'), (B, 'blue')):
        data = root / 'adventures' / aid
        states = CheckpointStore(data / 'states')
        rom = Path(roms) / f'poke{edition}.gbc'
        states.write_checkpoint((Path(fixtures) / f'{edition}.state').read_bytes(), {
            'rom_sha1': hashlib.sha1(rom.read_bytes()).hexdigest(), 'pyboy_version': '2.7.0',
            'policy': 'strategic', 'policy_state': {}, 'run_memory': {}, 'frame': 0, 'trade_id': None})
        bootstraps[aid] = {'protocol': 1, 'adventure_id': aid, 'generation': secrets.token_hex(8),
            'token': secrets.token_urlsafe(32), 'settings': {
                'rom_path': str(rom.resolve()), 'data_dir': str(data.resolve()),
                'game_data_dir': str(Path(game_data).resolve()), 'speed': 0.1,
                'autosave_seconds': 3600, 'stuck_reload_seconds': 3600}}
    def request(aid, operation, payload=None):
        return children[aid].request('POST', '/internal/participant/' + operation,
                                    {'id': tid, **(payload or {})}, timeout=60)
    def start(aid):
        children[aid] = Child(bootstraps[aid])
        children[aid].start()
    try:
        for aid in bootstraps:
            start(aid)
        progress('Two independent workers ready')
        choices = {}
        for index, aid in enumerate(children):
            inventory = children[aid].request('GET', '/internal/participant/inventory', timeout=60)
            checked(len(inventory['offers']) > index, 'Fixtures need eligible boxed spares')
            choices[aid] = inventory['offers'][index]['trade_key']
            request(aid, 'prepare', {'plan_digest': plan_digest, 'selected_key': choices[aid]})
            children[aid].request('POST', '/api/control', {'action': 'speed', 'value': 0})
        prepared = {}
        deadline = time.monotonic() + 120
        while len(prepared) < 2:
            checked(time.monotonic() < deadline, 'Managed gameplay preparation timed out')
            for aid in children:
                if aid in prepared:
                    continue
                state = request(aid, 'prepare', {'plan_digest': plan_digest, 'selected_key': choices[aid]})
                if state['phase'] == 'prepared':
                    prepared[aid] = state
                    progress(aid + ' prepared through gameplay')
            if len(prepared) < 2:
                time.sleep(0.1)
        baseline_parties = {aid: children[aid].request('GET', '/internal/participant/inventory')['party']
                            for aid in children}
        plan = CableSessionPlan(tid, attempt, CableParticipant(**prepared[A]['source']),
            CableParticipant(**prepared[B]['source']), speed=0, timeout_seconds=60)
        out = root / 'interactions' / tid / 'attempts' / attempt / 'outputs'
        result = subprocess.run([sys.executable, '-m', 'pokesim.interactions.link_worker', '--out', str(out)],
            input=json.dumps(asdict(plan)), text=True, capture_output=True, timeout=90)
        (root / 'link.stdout.log').write_text(result.stdout)
        (root / 'link.stderr.log').write_text(result.stderr)
        checked(result.returncode == 0, 'Link subprocess failed: ' + result.stderr[-1200:])
        manifest = json.loads((out / 'manifest.json').read_text())
        progress('Temporary link subprocess verified both cartridges')
        stages = {}
        for aid, other in ((A, B), (B, A)):
            entry = manifest['participants'][aid]
            payload = {'attempt_id': attempt, 'plan_digest': plan_digest, 'result': entry,
                       'incoming': prepared[other]['outgoing']}
            if abort and aid == B:
                damaged = {**payload, 'result': {**entry, 'checkpoint_sha256': '0' * 64}}
                try:
                    request(aid, 'stage', damaged)
                except RuntimeError:
                    report['second_stage_rejected'] = True
                else:
                    raise RuntimeError('Damaged second stage was accepted')
                break
            stages[aid] = request(aid, 'stage', payload)
            checked(request(aid, 'stage', payload)['phase'] == 'staged', 'Duplicate stage failed')
        if abort:
            for aid in children:
                children[aid].request('POST', '/api/control', {'action': 'speed', 'value': 0.1})
                request(aid, 'abort')
                checked(request(aid, 'abort')['phase'] == 'aborted', 'Duplicate abort failed')
            for aid in children:
                inventory = children[aid].request('GET', '/internal/participant/inventory')
                checked(inventory['party'] == baseline_parties[aid], 'Abort changed prepared party ownership')
                children[aid].stop()
                bootstraps[aid]['generation'] = secrets.token_hex(8)
                start(aid)
                inventory = children[aid].request('GET', '/internal/participant/inventory')
                checked(inventory['party'] == baseline_parties[aid], 'Abort restart changed party ownership')
            report.update(status='passed', both_aborted=True, prepared_parties_preserved=True,
                          abort_restart_preserved=True)
        else:
            def apply(aid):
                payload = {'attempt_id': attempt, 'plan_digest': plan_digest,
                           'checkpoint_sha256': manifest['participants'][aid]['checkpoint_sha256']}
                checked(request(aid, 'apply', payload)['phase'] == 'applied', 'Apply failed')
                checked(request(aid, 'apply', payload)['phase'] == 'applied', 'Duplicate apply failed')
            for aid in children:
                apply(aid)
                children[aid].request('POST', '/api/control', {'action': 'speed', 'value': 0.1})
            children[A].stop()
            bootstraps[A]['generation'] = secrets.token_hex(8)
            start(A)
            checked(children[A].request('GET', '/api/state')['paused'], 'Committed restart lost hold')
            apply(A)
            for aid in children:
                checked(request(aid, 'release')['phase'] == 'released', 'Release failed')
                checked(request(aid, 'release')['phase'] == 'released', 'Duplicate release failed')
            progress('Both applied and released, including restart while committed')
            for aid in list(children):
                children[aid].stop()
                bootstraps[aid]['generation'] = secrets.token_hex(8)
                start(aid)
                inv = children[aid].request('GET', '/internal/participant/inventory', timeout=60)
                incoming_key = manifest['participants'][aid]['evidence']['received_key']
                checked(any(mon['trade_key'] == incoming_key for mon in inv['party']),
                        'Restart lost the incoming party member')
                status = children[aid].request('GET', '/internal/participant/status/' + tid)
                checked(status['phase'] == 'released', 'Released receipt was not retained')
            report.update(status='passed', duplicate_stage=True, duplicate_apply=True,
                          duplicate_release=True, committed_restart_held=True,
                          released_restart_preserved=True)
        report['selected_keys'] = choices
        report['link_manifest'] = str((out / 'manifest.json').resolve())
    except BaseException:
        for aid, child in children.items():
            (root / f'{aid}.worker.log').write_text('\n'.join(child.logs))
        raise
    finally:
        for child in children.values():
            child.stop()
    for aid in children:
        with sqlite3.connect(root / 'adventures' / aid / 'pokesim.sqlite') as db:
            count = db.execute('SELECT COUNT(*) FROM kv WHERE k=?', ('managed_journal:' + tid,)).fetchone()[0]
            checked(count == (0 if abort else 1), 'Trade journal was duplicated or lost')
    report['journal_once' if not abort else 'no_committed_journal'] = True
    (root / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--roms', type=Path, required=True)
    parser.add_argument('--game-data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--abort', action='store_true')
    args = parser.parse_args()
    print(json.dumps(exercise(args.out, args.fixtures, args.roms, args.game_data, args.abort), indent=2))


if __name__ == '__main__':
    main()
