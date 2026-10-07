"""Verified Gen II paired sessions on disposable cartridge copies."""
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path

from ..interactions.cable import checked, sha256
from ..interactions.link_worker import _write
from .cable import CableSide
from .cable_driver import CableDriver
from .cable_metadata import ADAPTER_ID, BUILDS
from .core import stop_with_clock
from .cable_verification import continue_save, individual_key, party, verify_exchange
from .data import GameData
from .ram import read_snapshot


def run_session(plan, output_dir, progress=None, cancelled=None):
    plan.validate()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    sides = []
    try:
        for spec in (plan.left, plan.right):
            build = BUILDS.get(hashlib.sha1(Path(spec.rom_path).read_bytes()).hexdigest())
            checked(build is not None, 'The Gen II cable requires two compatible Gen II cartridges')
            from ..game_data import directory
            data = GameData.load(spec.game_data_dir or directory(), build['version'])
            sides.append(CableSide(spec, data))
        sides[0].peer, sides[1].peer = sides[1], sides[0]
        before = [party(side.pb, side.data) for side in sides]
        snapshots = [read_snapshot(side.pb.memory, side.data) for side in sides]
        for index, side in enumerate(sides):
            checked(side.spec.party_slot < len(before[index]), 'Negotiated party slot no longer exists')
            selected = before[index][side.spec.party_slot]
            checked(not snapshots[index].party[side.spec.party_slot].egg, 'Eggs cannot be offered by this coordinator')
            checked(side.spec.selected_key is None or individual_key(selected) == side.spec.selected_key,
                    'Negotiated individual no longer occupies selected slot')
            snapshot = snapshots[index]
            checked(snapshot.started and not snapshot.in_battle
                    and snapshot.map == side.data.map_ids['POKECENTER_2F']
                    and (snapshot.x, snapshot.y) == (3, 4), 'The trainer is not at the prepared Cable Club position')
            checked(sum(individual_key(row) == individual_key(selected) for row in before[index]) == 1,
                    'The selected individual is ambiguous in the prepared party')
            side.attach(index + 1)
        def preview(value):
            for index, side in enumerate(sides):
                prefix = 'left' if index == 0 else 'right'
                output = io.BytesIO()
                side.pb.screen.image.convert('RGB').save(output, format='JPEG', quality=80)
                pending = out / f'.{prefix}.jpg.pending'
                pending.write_bytes(output.getvalue())
                os.replace(pending, out / f'{prefix}.jpg')
                snapshot = read_snapshot(side.pb.memory, side.data, side.frame)
                value['sides'][side.spec.adventure_id].update(side=prefix, map=snapshot.map, x=snapshot.x,
                    y=snapshot.y, preview_path=str((out / f'{prefix}.jpg').resolve()))
            if progress:
                progress(value)
        CableDriver(sides, plan, preview, cancelled).run()
        results = {}
        for index, side in enumerate(sides):
            peer = sides[1 - index]
            checked(side.counts['SaveAfterLinkTrade'] == 1, 'Cartridge did not save exactly one exchange')
            checked(side.counts['byte_exchanged'] > 0 and side.counts['nybble_exchanged'] > 0,
                    'Trade has no verified transport evidence')
            expected, evidence = verify_exchange(side, before[index], before[1 - index][peer.spec.party_slot],
                                                 side.spec.party_slot, snapshots[index])
            save_stream = io.BytesIO()
            clock_stream = io.BytesIO()
            stop_with_clock(side.pb, save_stream, clock_stream)
            side.stopped = True
            save = save_stream.getvalue()
            checked(len(save) == 32768, 'Unexpected cartridge save size')
            restarted = continue_save(side.rom_bytes, save, side.data, rtc=clock_stream.getvalue())
            try:
                checked(party(restarted, side.data) == expected, 'Cartridge Continue changed the traded party')
                side.pb = restarted
                verify_exchange(side, before[index], before[1 - index][peer.spec.party_slot],
                                side.spec.party_slot, snapshots[index])
                state_stream = io.BytesIO()
                restarted.save_state(state_stream)
                state = state_stream.getvalue()
                restarted.load_state(io.BytesIO(state))
                checked(party(restarted, side.data) == expected, 'Checkpoint restart changed the traded party')
            finally:
                restarted.stop(save=False)
            prefix = 'left' if index == 0 else 'right'
            state_path, save_path = out / f'{prefix}.state', out / f'{prefix}.sav'
            _write(state_path, state)
            _write(save_path, save)
            _write(out / f'{prefix}.rtc', clock_stream.getvalue())
            evidence.update(cartridge_restart=True, checkpoint_restart=True, transport=dict(side.counts))
            results[side.spec.adventure_id] = {
                'adventure_id': side.spec.adventure_id, 'side': prefix, 'version': side.build['version'],
                'rom_sha1': side.rom_sha1, 'source': side.input_hashes,
                'selected_key': individual_key(before[index][side.spec.party_slot]),
                'state_path': str(state_path.resolve()), 'cartridge_save_path': str(save_path.resolve()),
                'checkpoint_sha256': sha256(state), 'cartridge_sha256': sha256(save), 'evidence': evidence}
        canonical = json.dumps(asdict(plan), sort_keys=True, separators=(',', ':')).encode()
        manifest = {'schema_version': 1, 'status': 'verified', 'adapter_id': ADAPTER_ID,
                    'interaction_id': plan.interaction_id, 'attempt_id': plan.attempt_id,
                    'plan_sha256': sha256(canonical), 'participants': results,
                    'return_method': 'cartridge_soft_reset_continue'}
        checked(cancelled is None or not cancelled.is_set(), 'Cable session cancelled before publication')
        _write(out / 'manifest.pending', json.dumps(manifest, indent=2, sort_keys=True).encode())
        os.replace(out / 'manifest.pending', out / 'manifest.json')
        from ..platform_io import sync_directory
        sync_directory(out)
        return manifest
    except BaseException as error:
        _write(out / 'failure.json', json.dumps({'status': 'failed', 'error': str(error),
               'sides': {side.spec.adventure_id: dict(side.counts) for side in sides}}).encode())
        raise
    finally:
        for side in sides:
            side.stop()
