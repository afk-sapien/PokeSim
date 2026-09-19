"""Verify the real manager coordinator, three workers, and committed recovery."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from pokesim.app.manager import Manager
from pokesim.app.registry import identifier
from pokesim.checkpoints import CheckpointStore
from pokesim.interactions.cable import checked


def exercise_app(root, fixtures, roms, game_data, progress=print):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    manager = Manager(root, game_data_dir=game_data)
    source_hashes = {name: hashlib.sha256((Path(fixtures) / f'{name}.state').read_bytes()).hexdigest()
                     for name in ('red', 'blue')}
    ids = []
    report = {'status': 'running'}
    try:
        manager.registry.set_setting('max_running', 3)
        manager.registry.set_setting('speed', 0.1)
        for index, edition in enumerate(('red', 'blue', 'red')):
            rom = Path(roms) / f'poke{edition}.gbc'
            asset = manager.assets.install_rom(rom.read_bytes())
            settings = manager.validate_adventure_settings({'autosave_seconds': 3600})
            adventure = manager.registry.create(f'Integration {index}', asset['id'], settings, identifier())
            aid = adventure['id']
            ids.append(aid)
            CheckpointStore(root / 'adventures' / aid / 'states').write_checkpoint(
                (Path(fixtures) / f'{edition}.state').read_bytes(), {
                    'rom_sha1': hashlib.sha1(rom.read_bytes()).hexdigest(), 'pyboy_version': '2.7.0',
                    'policy': 'strategic', 'policy_state': {}, 'run_memory': {}, 'frame': 0, 'trade_id': None})
            manager.registry.request_lifecycle(aid, 'start', identifier())
            manager.start_adventure(aid)
        left, right, unrelated = ids
        progress('Manager started three independent worker processes')
        third = manager.supervisor.child(unrelated)
        unrelated_pid = third.process.pid
        before_frame = third.request('GET', '/api/state')['frame']
        left_inventory = manager.coordinator.inventory(left)
        right_inventory = manager.coordinator.inventory(right)
        checked(left_inventory['offers'] and len(right_inventory['offers']) > 1, 'Fixtures need eligible boxed offers')
        proposal = {'left_id': left, 'right_id': right,
            'left_key': left_inventory['offers'][0]['trade_key'],
            'right_key': right_inventory['offers'][1]['trade_key'], 'request_id': identifier()}
        row = manager.coordinator.propose(proposal)
        checked(manager.coordinator.propose(proposal)['id'] == row['id'], 'Proposal retry changed interaction identity')
        session_plan = manager.coordinator._session_plan
        manager.coordinator._session_plan = lambda row, prepared: {**session_plan(row, prepared), 'speed': 0}
        manager.coordinator.prepare_poll = 0.1
        request = manager.coordinator._request
        def inject_fault(aid, operation, data=None, recovery=False):
            if operation == 'apply' and aid == right:
                raise RuntimeError('Injected unavailable participant after durable COMMIT')
            receipt = request(aid, operation, data, recovery)
            if operation == 'prepare' and receipt['phase'] == 'preparing':
                manager.supervisor.child(aid).request('POST', '/internal/speed', {'speed': 0})
            if operation == 'apply':
                manager.supervisor.child(aid).request('POST', '/internal/speed', {'speed': 0.1})
            return receipt
        manager.coordinator._request = inject_fault
        result = manager.coordinator.execute(row['id'])
        checked(result['decision'] == 'COMMIT' and result['phase'] == 'recovering',
                'Injected post-commit interruption did not preserve committed recovery')
        manifest = result['result']
        checked(manifest['status'] == 'verified', 'Coordinator did not preserve paired verified manifest')
        from PIL import Image
        for participant in manifest['participants'].values():
            image_path = Path(participant['state_path']).with_name(participant['side'] + '.jpg')
            with Image.open(image_path) as image:
                checked(image.size == (160, 144), 'Session did not publish its current preview')
                image.verify()
        after_frame = third.request('GET', '/api/state')['frame']
        checked(third.process.pid == unrelated_pid and after_frame > before_frame,
                'Unselected adventure did not continue independently')
        checked(not manager.coordinator.reserved(unrelated), 'Unselected adventure was reserved')
        progress('Coordinator committed real cable results, unrelated worker kept running')
        manager.close()
        manager = Manager(root, game_data_dir=game_data)
        manager.start()
        recovered = manager.registry.transaction(row['id'])
        checked(recovered['phase'] == 'completed' and recovered['decision'] == 'COMMIT',
                'Manager restart did not finish its durable decision')
        checked(manager.coordinator.execute(row['id'])['phase'] == 'completed',
                'Completed execution was not idempotent')
        history = manager.coordinator.status()['history']
        checked(sum(entry['id'] == row['id'] for entry in history) == 1, 'Coordinator history duplicated transaction')
        for aid in (left, right):
            inventory = manager.coordinator.inventory(aid)
            key = manifest['participants'][aid]['evidence']['received_key']
            checked(any(mon['trade_key'] == key for mon in inventory['party']), 'Recovered owner lost incoming individual')
            checked(not inventory['holding'], 'Recovered owner remained held')
        checked(manager.supervisor.child(unrelated).request('GET', '/internal/health')['running'],
                'Unselected adventure did not resume after manager restart')
        report.update(status='passed', interaction_id=row['id'], participants=[left, right], unrelated_id=unrelated,
            three_distinct_worker_processes=True, paired_manifest_bound_to_commit=True,
            unselected_worker_continued=True, unrelated_frames_advanced=after_frame-before_frame,
            committed_recovery_survived_manager_restart=True, completed_retry_idempotent=True,
            coordinator_history_once=True, original_fixture_hashes=source_hashes,
            automatic_scheduler='Not exercised with shared-origin identical boxed collections')
        progress('Manager restart recovered both participants and retained one completed history entry')
    finally:
        manager.close()
    for aid in ids:
        with sqlite3.connect(root / 'adventures' / aid / 'pokesim.sqlite') as db:
            count = db.execute('SELECT COUNT(*) FROM kv WHERE k LIKE ?', ('managed_journal:%',)).fetchone()[0]
        checked(count == (0 if aid == ids[2] else 1), 'Managed trade journal count is incorrect')
    for edition, expected in source_hashes.items():
        checked(hashlib.sha256((Path(fixtures) / f'{edition}.state').read_bytes()).hexdigest() == expected,
                'Original fixture was changed')
    report['journal_exactly_once'] = True
    report['source_fixtures_unchanged'] = True
    (root / 'integration-result.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--roms', type=Path, required=True)
    parser.add_argument('--game-data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(exercise_app(args.out, args.fixtures, args.roms, args.game_data), indent=2))


if __name__ == '__main__':
    main()
