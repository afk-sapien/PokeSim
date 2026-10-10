"""Exercise a prepared Time Capsule pair and both participant-side verifiers."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from pokesim.gen2.data import GameData
from pokesim.gen2.timecapsule import TimeCapsuleSide
from pokesim.gen2.trading import Participant as Gen2Participant
from pokesim.gen2.cable_verification import party as gen2_party
from pokesim.interactions.cable import CableSide
from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan, run_session
from pokesim.interactions.verification import party as gen1_party
from pokesim.runtime.participant import Participant as Gen1Participant


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gen1-rom', type=Path, required=True)
    parser.add_argument('--gen1-state', type=Path, required=True)
    parser.add_argument('--gen1-slot', type=int, default=0)
    parser.add_argument('--gen2-receipt', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.gen2_receipt.read_text())
    classic = CableParticipant('classic', str(args.gen1_rom.resolve()), str(args.gen1_state.resolve()), party_slot=args.gen1_slot)
    modern = CableParticipant(**receipt['source'])
    from pokesim.cartridges import identify
    data = GameData.load(args.data, identify(Path(modern.rom_path).read_bytes()).version)
    old, new = CableSide(classic), TimeCapsuleSide(modern, data)
    try:
        outgoing = [gen1_party(old.pb, old.sym)[classic.party_slot], gen2_party(new.pb, data)[modern.party_slot]]
        hashes = [old.input_hashes['checkpoint_sha256'], new.input_hashes['checkpoint_sha256']]
        roms = [old.rom_sha1, new.rom_sha1]
    finally:
        old.stop()
        new.stop()
    plan = CableSessionPlan('timecapsule-check', 'verify', classic, modern, speed=0)
    manifest = run_session(plan, args.output)
    for i, (spec, participant) in enumerate(((classic, Gen1Participant), (modern, Gen2Participant))):
        instance = SimpleNamespace(emu=SimpleNamespace(rom_sha1=roms[i], data=data),
            runtime=SimpleNamespace(settings=SimpleNamespace(rom_path=spec.rom_path, game_data_dir=str(args.data))))
        record = {'time_capsule': True, 'source': {'checkpoint_path': spec.checkpoint_path,
                  'checkpoint_sha256': hashes[i], 'party_slot': spec.party_slot}}
        result = manifest['participants'][spec.adventure_id]
        incoming = {key: value.hex() for key, value in outgoing[1 - i].items()}
        participant.verify_result(instance, record, result, Path(result['state_path']).read_bytes(),
                                  Path(result['cartridge_save_path']).read_bytes(), incoming)
        participant.incoming_record(instance, record, {'incoming': incoming, 'incoming_league_record': None})
    print('Both cartridge exchanges, restart checks and participant verifiers passed')


if __name__ == '__main__':
    main()
