"""Verify both sides of a mixed generation exchange before publishing artifacts."""
from dataclasses import asdict
import io
import json
import os
from pathlib import Path

from ..cartridges import identify
from ..interactions import verification as gen1
from ..interactions.cable import CableSide, checked, sha256
from ..interactions.cable_driver import CableDriver
from ..interactions.link_worker import _write
from . import cable_verification as gen2
from .data import GameData
from .ram import Memory, read_snapshot
from .timecapsule import ADAPTER_ID, MixedDriver, TimeCapsuleSide, compatible, unlocked
from .timecapsule_conversion import convert


def run_session(plan, output_dir, progress=None, cancelled=None):
    plan.validate()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    sides = []
    try:
        specs = (plan.left, plan.right)
        versions = [identify(Path(spec.rom_path).read_bytes()) for spec in specs]
        checked(all(versions) and {version.generation for version in versions} == {1, 2},
                'The Time Capsule requires one Generation I and one Generation II cartridge')
        second = next(i for i, version in enumerate(versions) if version.generation == 2)
        from ..game_data import directory
        data = GameData.load(specs[second].game_data_dir or directory(), versions[second].version)
        for i, spec in enumerate(specs):
            sides.append(TimeCapsuleSide(spec, data) if i == second else CableSide(spec))
        sides[0].peer, sides[1].peer = sides[1], sides[0]
        modern, classic = sides[second], sides[1 - second]
        snapshot = read_snapshot(modern.pb.memory, data)
        checked(unlocked(snapshot, Memory(modern.pb.memory, data)), 'The Time Capsule opens the day after meeting Bill')
        checked(all(compatible(mon, data) for mon in snapshot.party), 'The prepared party is not Time Capsule compatible')
        checked(snapshot.map == data.map_ids['POKECENTER_2F'] and (snapshot.x, snapshot.y) == (3, 4)
                and not snapshot.in_battle, 'The trainer is not at the prepared Time Capsule position')
        before = [gen2.party(side.pb, data) if i == second else gen1.party(side.pb, side.sym)
                  for i, side in enumerate(sides)]
        boxes = gen1.boxed_inventory(classic.pb, classic.sym)
        for i, side in enumerate(sides):
            checked(side.spec.party_slot < len(before[i]), 'Negotiated party slot no longer exists')
            key = gen2.individual_key if i == second else gen1.individual_key
            selected = key(before[i][side.spec.party_slot])
            checked(side.spec.selected_key is None or side.spec.selected_key == selected,
                    'Negotiated individual no longer occupies the selected slot')
            checked(sum(key(row) == selected for row in before[i]) == 1, 'The selected individual is ambiguous')
        driver = CableDriver([classic], plan, cancelled=cancelled)
        driver.enter()
        classic.attach(1)
        modern.attach(2)
        def preview(value):
            for i, side in enumerate(sides):
                prefix = 'left' if i == 0 else 'right'
                output = io.BytesIO()
                side.pb.screen.image.convert('RGB').save(output, format='JPEG', quality=80)
                pending = out / f'.{prefix}.jpg.pending'
                pending.write_bytes(output.getvalue())
                os.replace(pending, out / f'{prefix}.jpg')
                value['sides'][side.spec.adventure_id].update(side=prefix,
                    preview_path=str((out / f'{prefix}.jpg').resolve()))
            if progress:
                progress(value)
        MixedDriver(classic, modern, plan, preview, cancelled).run()
        checked(modern.counts['SaveAfterLinkTrade'] == 1 and modern.counts['Gen2ToGen1LinkComms'] == 2,
                'The Time Capsule did not complete exactly one exchange')
        driver.return_to_center()
        results = {}
        for i, side in enumerate(sides):
            peer = sides[1 - i]
            incoming = convert(before[1 - i][peer.spec.party_slot], versions[i].generation, data)
            if i == second:
                encode = lambda rows: [{key: value.hex() for key, value in row.items()} for row in rows]
                _write(out / 'modern-party-evidence.json', json.dumps({
                    'before': encode(before[i]), 'after': encode(gen2.party(side.pb, data)),
                    'slot': side.spec.party_slot}, indent=2).encode())
                expected, evidence = gen2.verify_exchange(side, before[i], incoming, side.spec.party_slot,
                                                          snapshot, time_capsule=True)
            else:
                expected, evidence = gen1.verify_exchange(side, before[i], incoming, side.spec.party_slot, boxes)
            save_stream = io.BytesIO()
            clock_stream = io.BytesIO()
            state_stream = io.BytesIO()
            if i != second:
                side.pb.save_state(state_stream)
            side.pb.stop(ram_file=save_stream, rtc_file=clock_stream)
            side.stopped = True
            save = save_stream.getvalue()
            checked(len(save) == 32768, 'Unexpected cartridge save size')
            if i == second:
                restarted = gen2.continue_save(side.rom_bytes, save, data, rtc=clock_stream.getvalue())
                try:
                    resumed = gen2.party(restarted, data)
                    if resumed != expected:
                        encode = lambda rows: [{key: value.hex() for key, value in row.items()} for row in rows]
                        _write(out / 'restart-party-mismatch.json', json.dumps({
                            'expected': encode(expected), 'continued': encode(resumed)}, indent=2).encode())
                        _write(out / 'rejected.sav', save)
                    checked(resumed == expected, 'Time Capsule Continue changed the party')
                    side.pb = restarted
                    gen2.verify_exchange(side, before[i], incoming, side.spec.party_slot, snapshot, time_capsule=True)
                    restarted.save_state(state_stream)
                    restarted.load_state(io.BytesIO(state_stream.getvalue()))
                    checked(gen2.party(restarted, data) == expected, 'Time Capsule checkpoint changed the party')
                finally:
                    restarted.stop(save=False)
                evidence.update(cartridge_restart=True, checkpoint_restart=True)
            else:
                evidence.update(gen1.verify_restarts(side, state_stream.getvalue(), save, expected))
            state = state_stream.getvalue()
            prefix = 'left' if i == 0 else 'right'
            state_path, save_path = out / f'{prefix}.state', out / f'{prefix}.sav'
            _write(state_path, state)
            _write(save_path, save)
            if i == second:
                _write(out / f'{prefix}.rtc', clock_stream.getvalue())
            evidence.update(time_capsule=True, cartridge_generation=versions[i].generation, transport=dict(side.counts))
            key = gen2.individual_key if i == second else gen1.individual_key
            results[side.spec.adventure_id] = {'adventure_id': side.spec.adventure_id, 'side': prefix,
                'version': side.build['version'], 'rom_sha1': side.rom_sha1, 'source': side.input_hashes,
                'selected_key': key(before[i][side.spec.party_slot]),
                'state_path': str(state_path.resolve()), 'cartridge_save_path': str(save_path.resolve()),
                'checkpoint_sha256': sha256(state), 'cartridge_sha256': sha256(save), 'evidence': evidence}
        canonical = json.dumps(asdict(plan), sort_keys=True, separators=(',', ':')).encode()
        manifest = {'schema_version': 1, 'status': 'verified', 'adapter_id': ADAPTER_ID,
            'interaction_id': plan.interaction_id, 'attempt_id': plan.attempt_id,
            'plan_sha256': sha256(canonical), 'participants': results,
            'return_method': 'cartridge_soft_reset_continue'}
        checked(cancelled is None or not cancelled.is_set(), 'Time Capsule cancelled before publication')
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
