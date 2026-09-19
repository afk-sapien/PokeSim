"""Transaction-scoped paired cartridge executor. Results are provisional until adopted."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import threading

from .cable import CableError, CableSide, checked, sha256
from .cable_driver import CableDriver
from .cable_metadata import ADAPTER_ID
from .verification import boxed_inventory, individual_key, party, verify_exchange, verify_restarts


@dataclass(frozen=True)
class CableParticipant:
    adventure_id: str
    rom_path: str
    checkpoint_path: str
    cartridge_save_path: str | None = None
    party_slot: int = 0
    checkpoint_sha256: str | None = None
    cartridge_sha256: str | None = None
    selected_key: str | None = None


@dataclass(frozen=True)
class CableSessionPlan:
    interaction_id: str
    attempt_id: str
    left: CableParticipant
    right: CableParticipant
    external_left: bool = False
    max_steps: int = 1800
    timeout_seconds: float = 900
    speed: float = 1

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value['left'] = CableParticipant(**value['left'])
        value['right'] = CableParticipant(**value['right'])
        return cls(**value)

    def validate(self):
        for value in (self.interaction_id, self.attempt_id, self.left.adventure_id, self.right.adventure_id):
            checked(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value)
                    and value not in ('.', '..'), 'Invalid interaction or participant identifier')
        checked(self.left.adventure_id != self.right.adventure_id, 'Cable requires two distinct adventures')
        checked(type(self.max_steps) is int and 1 <= self.max_steps <= 10000, 'Invalid step budget')
        checked(math.isfinite(self.timeout_seconds) and 0 < self.timeout_seconds <= 3600,
                'Invalid session deadline')
        checked(math.isfinite(self.speed) and 0 <= self.speed <= 120, 'Invalid session speed')
        for side in (self.left, self.right):
            checked(type(side.party_slot) is int and 0 <= side.party_slot < 6, 'Invalid party slot')


def _write(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def run_session(plan: CableSessionPlan, output_dir, progress=None, cancelled=None):
    """Run one authentic trade on disposable copies and publish a verified paired manifest.

    No participant database or authoritative checkpoint is written. The caller must
    fence this attempt and stage both verified outputs before deciding to commit.
    """
    plan.validate()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    sides = []
    try:
        checked(cancelled is None or not cancelled.is_set(), 'Cable session cancelled')
        for participant in (plan.left, plan.right):
            sides.append(CableSide(participant))
        left, right = sides
        left.peer, right.peer = right, left
        before = [party(side.pb, side.sym) for side in sides]
        boxes = [boxed_inventory(side.pb, side.sym) for side in sides]
        for index, side in enumerate(sides):
            checked(side.spec.party_slot < len(before[index]), 'Negotiated party slot no longer exists')
            selected = before[index][side.spec.party_slot]
            checked(side.spec.selected_key is None or side.spec.selected_key == individual_key(selected),
                    'Negotiated individual no longer occupies selected slot')
            if side.spec.selected_key is not None:
                from dataclasses import asdict as record_dict
                from pokesim.ram import read_snapshot
                from pokesim.trade.preferences import identity
                snapshot = read_snapshot(side.pb.memory, 0)
                entries = [record_dict(mon) for mon in snapshot.party] + list(snapshot.storage_entries())
                checked(sum(identity(mon) == side.spec.selected_key for mon in entries) == 1,
                        'Negotiated individual identity is ambiguous')
            side.attach(1 if (index == 0) == plan.external_left else 2)
        driver = CableDriver(sides, plan, progress, cancelled)
        def preview(phase, steps):
            states = {}
            for index, side in enumerate(sides):
                prefix = 'left' if index == 0 else 'right'
                image = io.BytesIO()
                side.pb.screen.image.convert('RGB').save(image, format='JPEG', quality=80)
                pending = out / f'.{prefix}.jpg.pending'
                pending.write_bytes(image.getvalue())
                os.replace(pending, out / f'{prefix}.jpg')
                snap = driver.snapshot(side)
                states[side.spec.adventure_id] = {
                    'side': prefix, 'frame': side.frame,
                    'map': snap.map, 'x': snap.x, 'y': snap.y,
                    'preview_path': str((out / f'{prefix}.jpg').resolve()),
                    'transport': dict(side.counts)}
            if progress:
                progress({'phase': phase, 'steps': steps, 'sides': states})
        driver.preview = preview
        driver.enter()
        driver.exchange()
        driver.leave()
        driver.return_to_center()
        driver.report('verifying')
        results = {}
        for index, side in enumerate(sides):
            peer = sides[1 - index]
            expected, evidence = verify_exchange(side, before[index],
                before[1 - index][peer.spec.party_slot], side.spec.party_slot, boxes[index])
            state_stream = io.BytesIO()
            side.pb.save_state(state_stream)
            state = state_stream.getvalue()
            save_stream = io.BytesIO()
            side.pb.stop(ram_file=save_stream)
            side.stopped = True
            save = save_stream.getvalue()
            evidence.update(verify_restarts(side, state, save, expected))
            prefix = 'left' if index == 0 else 'right'
            state_path, save_path = out / f'{prefix}.state', out / f'{prefix}.sav'
            _write(state_path, state)
            _write(save_path, save)
            results[side.spec.adventure_id] = {
                'adventure_id': side.spec.adventure_id, 'side': prefix,
                'version': side.build['version'], 'rom_sha1': side.rom_sha1,
                'source': side.input_hashes,
                'selected_key': individual_key(before[index][side.spec.party_slot]),
                'state_path': str(state_path.resolve()), 'cartridge_save_path': str(save_path.resolve()),
                'checkpoint_sha256': sha256(state), 'cartridge_sha256': sha256(save),
                'evidence': evidence,
            }
        canonical = json.dumps(asdict(plan), sort_keys=True, separators=(',', ':')).encode()
        manifest = {'schema_version': 1, 'status': 'verified', 'adapter_id': ADAPTER_ID,
                    'interaction_id': plan.interaction_id, 'attempt_id': plan.attempt_id,
                    'plan_sha256': sha256(canonical), 'participants': results,
                    'return_method': 'cartridge_soft_reset_continue'}
        driver.report('verified')
        checked(cancelled is None or not cancelled.is_set(), 'Cable session cancelled before publication')
        _write(out / 'manifest.pending', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
        os.replace(out / 'manifest.pending', out / 'manifest.json')
        from pokesim.platform_io import sync_directory
        sync_directory(out)
        return manifest
    except BaseException as error:
        failure = {'status': 'failed', 'interaction_id': plan.interaction_id,
                   'attempt_id': plan.attempt_id, 'error': str(error),
                   'sides': {side.spec.adventure_id: dict(side.counts) for side in sides}}
        _write(out / 'failure.json', (json.dumps(failure, indent=2) + '\n').encode())
        raise
    finally:
        for side in sides:
            side.stop()


def main(argv=None):
    from pokesim.runtime.worker import restore_worker_streams
    restore_worker_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', default='-', help='JSON plan file, or - for standard input')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--watch-parent', action='store_true',
                        help='Cancel when the inherited stdin liveness pipe closes')
    args = parser.parse_args(argv)
    if args.watch_parent and args.plan == '-':
        parser.error('--watch-parent requires a plan file')
    cancelled, finished = threading.Event(), threading.Event()
    def watch_parent():
        try:
            while sys.stdin.read(1):
                pass
        finally:
            cancelled.set()
            if not finished.wait(45):
                os._exit(2)
    if args.watch_parent:
        threading.Thread(target=watch_parent, name='link-parent-liveness', daemon=True).start()
    try:
        raw = sys.stdin.read() if args.plan == '-' else Path(args.plan).read_text()
        plan = CableSessionPlan.from_dict(json.loads(raw))
        run_session(plan, args.out, lambda value: print(json.dumps(value), flush=True), cancelled)
    except (CableError, ValueError, OSError, TypeError) as error:
        parser.exit(1, f'Cable session failed: {error}\n')
    finally:
        finished.set()


if __name__ == '__main__':
    main()
