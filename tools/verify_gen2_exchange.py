"""Verify preparation receipts, paired transport and durable Gen II adoption."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from pokesim.gen2.emulator import Emulator
from pokesim.gen2.trading import Participant
from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan, run_session
from pokesim.runtime.participant import recover_storage
from pokesim.runtime.settings import SimulationSettings
from pokesim.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    args = parser.parse_args()
    receipts = [json.loads((directory / 'receipt.json').read_text()) for directory in (args.left, args.right)]
    tid = receipts[0]['id']
    attempt = uuid.uuid4().hex
    output = args.left.resolve().parent / 'interactions' / tid / 'attempts' / attempt / 'outputs'
    plan = CableSessionPlan(tid, attempt, *(CableParticipant(**row['source']) for row in receipts), speed=0)
    manifest = run_session(plan, output, print)
    participants = []
    try:
        for directory, receipt in zip((args.left, args.right), receipts):
            aid = receipt['source']['adventure_id']
            settings = SimulationSettings(rom_path=receipt['source']['rom_path'], data_dir=str((directory / 'store').resolve()),
                game_data_dir=receipt['source']['game_data_dir'], speed=0, starter='random')
            settings.install(managed=True)
            store = Store(Path(settings.data_dir))
            emu = Emulator(store)
            emu._load_state_file(store.state_path(receipt['source_name']))
            runtime = SimpleNamespace(emulator=emu, store=store, settings=settings)
            participant = Participant(runtime, SimpleNamespace(adventure_id=aid, generation=1))
            participants.append(participant)
        for index, participant in enumerate(participants):
            aid = participant.bootstrap.adventure_id
            receipt = participant.stage({'id': tid, 'attempt_id': attempt, 'plan_digest': 'test',
                'result': manifest['participants'][aid], 'incoming': receipts[1 - index]['outgoing'],
                'incoming_league_record': receipts[1 - index].get('outgoing_league_record')})
            assert receipt['phase'] == 'staged'
        for participant in participants:
            aid = participant.bootstrap.adventure_id
            result = manifest['participants'][aid]
            participant.apply({'id': tid, 'attempt_id': attempt, 'plan_digest': 'test',
                               'checkpoint_sha256': result['checkpoint_sha256']})
            recover_storage(participant.store)
            assert participant.store.get('trade_hold')
        for participant in participants:
            receipt = participant.release({'id': tid})
            assert receipt['phase'] == 'released'
            assert not participant.store.get('trade_hold')
            assert participant.store.events(types=['trade'], limit=10)
        (output.parent / 'adoption.json').write_text(json.dumps({'status': 'passed', 'participants': list(manifest['participants'])}))
        print('BOTH EXCHANGES STAGED, COMMITTED, RECOVERED AND RELEASED', flush=True)
    finally:
        for participant in participants:
            participant.emu.pb.stop(save=False)
            participant.store.close()


if __name__ == '__main__':
    main()
