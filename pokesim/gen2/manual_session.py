"""An owner-driven Gen II Cable Club session on disposable cartridge copies.

The worker walks both trainers into the Trade Center with the scripted driver, then hands
the controllers to the owner. Both emulators tick in lockstep while button presses arrive
on standard input as JSON lines. Finishing walks both trainers out, saves through the
cartridge, restarts each save with Continue and checks that the cable only moved Pokémon
between the two parties. Nothing here touches either adventure: the coordinator decides
whether to adopt the verified outputs or roll both adventures back to their Center saves.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

from ..interactions.cable import CableError, checked, sha256
from .cable_metadata import BUILDS

BUTTONS = ('a', 'b', 'start', 'select', 'up', 'down', 'left', 'right')
LINK = 'Gen2ToGen2LinkComms'
HOLD_FRAMES = 8
PREVIEW_FRAMES = 4
FRAME_SECONDS = 1 / 60
SIDES = ('left', 'right')


def fingerprint(row):
    """What a trade never changes: moves, ID, experience, DVs, PP, Pokérus, caught data and the original trainer."""
    raw = bytes(row['struct'])
    return raw[2:27].hex() + raw[28:32].hex() + bytes(row['trainer']).hex()


def verify_parties(before, after, trades, evolve=None):
    """Check that two parties only exchanged Pokémon with each other.

    ``before`` and ``after`` are pairs of party lists (left, right) of rows with ``struct``,
    ``nickname`` and ``trainer`` bytes. ``trades`` is the number of completed cartridge saves
    after a trade on each side. Returns per-side evidence or raises CableError.
    """
    checked(len(before) == len(after) == len(trades) == 2, 'A cable session has exactly two sides')
    checked(trades[0] == trades[1], 'The two cartridges saved a different number of trades')
    for index in (0, 1):
        checked(len(after[index]) == len(before[index]), 'A trade changed the party size')
    counts = [[Counter(fingerprint(row) for row in rows) for rows in pair] for pair in (before, after)]
    total_before = counts[0][0] + counts[0][1]
    total_after = counts[1][0] + counts[1][1]
    checked(total_before == total_after, 'The two adventures did not keep the same Pokémon between them')
    lost = [counts[0][i] - counts[1][i] for i in (0, 1)]
    gained = [counts[1][i] - counts[0][i] for i in (0, 1)]
    checked(lost[0] == gained[1] and lost[1] == gained[0], 'The Pokémon each side lost did not reach the other side')
    for index in (0, 1):
        checked(sum(lost[index].values()) <= trades[index], 'A side lost more Pokémon than it traded')
        checked(sum(gained[index].values()) == sum(lost[index].values()), 'A side gained a different number of Pokémon than it lost')
    checked(trades[0] > 0 or not any(lost), 'Pokémon moved without a saved trade')
    originals = [{fingerprint(row): row for row in rows} for rows in before]
    evidence = []
    for index in (0, 1):
        peer = 1 - index
        received = []
        for row in after[index]:
            key = fingerprint(row)
            if key not in gained[index]:
                continue
            source = originals[peer][key]
            species = evolve(bytes(source['struct'])) if evolve else source['struct'][0]
            checked(row['struct'][0] in {source['struct'][0], species}, 'A trade produced an unexpected species')
            received.append({'species': row['struct'][0], 'incoming_species': source['struct'][0]})
        sent = [row['struct'][0] for row in before[index] if fingerprint(row) in lost[index]]
        evidence.append({'trades': trades[index], 'sent_species': sent, 'received': received,
                         'received_species': received[0]['species'] if received else None,
                         'incoming_species': received[0]['incoming_species'] if received else None,
                         'conserved': True, 'party_preserved': True})
    return evidence


def verify_progress(before, after):
    """Check that a session changed nothing but the party. Takes two read_snapshot results."""
    checked(after.event_flags == before.event_flags, 'The session changed story events')
    checked(after.stored == before.stored and after.active_box == before.active_box, 'The session changed boxed Pokémon')
    checked((after.badges, after.money, after.items) == (before.badges, before.money, before.items),
            'The session changed adventure progress')


class Session:
    """Two linked cartridges driven by the scripted driver at the edges and the owner in between."""

    def __init__(self, plan, output_dir, progress=None, cancelled=None):
        self.plan = plan
        self.out = Path(output_dir)
        self.progress_callback = progress
        self.cancelled = cancelled
        self.sides = []
        self.held = {}
        self.phase = 'connecting'
        self.last_report = 0
        self.frames = 0

    # Setup and the scripted edges.

    def open(self):
        from ..game_data import directory
        from .cable import CableSide
        from .cable_verification import party
        from .data import GameData
        from .ram import read_snapshot
        self.plan.validate()
        self.out.mkdir(parents=True, exist_ok=False)
        for spec in (self.plan.left, self.plan.right):
            build = BUILDS.get(hashlib.sha1(Path(spec.rom_path).read_bytes()).hexdigest())
            checked(build is not None, 'Manual Cable Club sessions need two compatible Gen II cartridges')
            data = GameData.load(spec.game_data_dir or directory(), build['version'])
            self.sides.append(CableSide(spec, data))
        self.sides[0].peer, self.sides[1].peer = self.sides[1], self.sides[0]
        self.before = [party(side.pb, side.data) for side in self.sides]
        self.snapshots = [read_snapshot(side.pb.memory, side.data) for side in self.sides]
        for index, side in enumerate(self.sides):
            snapshot = self.snapshots[index]
            checked(snapshot.started and not snapshot.in_battle
                    and snapshot.map == side.data.map_ids['POKECENTER_2F']
                    and (snapshot.x, snapshot.y) == (3, 4), 'The trainer is not at the prepared Cable Club position')
            side.attach(index + 1)
        from .cable_driver import CableDriver
        self.driver = CableDriver(self.sides, self.plan)

    def check_running(self):
        checked(self.cancelled is None or not self.cancelled.is_set(), 'Cable session cancelled')

    def ready(self, side):
        """True when this side shows the trade party list, waiting for the owner."""
        from .ram import read_snapshot
        if not side.counts[LINK]:
            return False
        s = read_snapshot(side.pb.memory, side.data, side.frame)
        if 'STATS' in s.text or 'EXP POINTS' in s.text:
            return False
        return 'CANCEL' in s.text and any(mon.name.upper() in s.text.upper() for mon in s.party)

    def scripted(self, choose_button, done, budget, phase):
        """Press scripted buttons on both sides every 40 frames until done() or the budget runs out."""
        self.phase = phase
        for _ in range(budget):
            self.check_running()
            if done():
                return
            for side in self.sides:
                button = choose_button(side)
                if button:
                    side.pb.button_press(button)
            for frame in range(40):
                if frame == HOLD_FRAMES:
                    for side in self.sides:
                        side.release_buttons()
                self.tick(paced=False)
        raise CableError(f'The Cable Club did not finish {phase} in time')

    def enter(self, budget=600):
        entered = set()
        def button(side):
            if self.ready(side):
                entered.add(id(side))
            return None if id(side) in entered else self.driver.button(side)
        self.scripted(button, lambda: len(entered) == 2 and all(self.ready(side) for side in self.sides),
                      budget, 'connecting')
        self.phase = 'in_session'
        self.report(force=True)

    def leave_button(self, side):
        from .menus import choose
        from .ram import read_snapshot
        if side.counts['ExitLinkCommunications']:
            return None
        s = read_snapshot(side.pb.memory, side.data, side.frame)
        if 'STATS' in s.text and 'TRADE' in s.text or 'EXP POINTS' in s.text:
            return 'b'
        if 'CANCEL' in s.text and 'TRADE' in s.text:
            return choose(s.tiles, 'CANCEL') or 'b'
        if 'CANCEL' in s.text and any(mon.name.upper() in s.text.upper() for mon in s.party):
            return 'a' if any('▶' in row and 'CANCEL' in row for row in s.tiles) else 'down'
        return 'a'

    def leave(self, budget=400):
        self.release_all()
        self.scripted(self.leave_button, lambda: all(side.counts['ExitLinkCommunications'] for side in self.sides),
                      budget, 'leaving')
        for _ in range(120):
            self.tick(paced=False)
        for side in self.sides:
            side.detach()

    # The owner's controllers.

    def press(self, side_name, button):
        checked(side_name in SIDES, 'Choose the left or right controller')
        checked(button in BUTTONS, 'Unknown button')
        checked(self.phase == 'in_session', 'The controllers are not live')
        side = self.sides[SIDES.index(side_name)]
        side.pb.button_press(button)
        self.held[(side_name, button)] = self.frames + HOLD_FRAMES

    def release_all(self):
        for side in self.sides:
            side.release_buttons()
        self.held.clear()

    def tick(self, paced=True):
        for (name, button), until in list(self.held.items()):
            if self.frames >= until:
                self.sides[SIDES.index(name)].pb.button_release(button)
                del self.held[(name, button)]
        moved = [side.tick() for side in self.sides]
        checked(any(moved), 'Both cable endpoints are parked')
        self.frames += 1
        if self.frames % PREVIEW_FRAMES == 0:
            self.preview()
        if paced and self.plan.speed:
            target = self.started + (self.frames - self.paced_from) * FRAME_SECONDS / self.plan.speed
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.5:
                self.started -= delay    # Do not race to catch up after a stall.

    def trades(self):
        return [side.counts['SaveAfterLinkTrade'] for side in self.sides]

    def preview(self):
        for index, side in enumerate(self.sides):
            prefix = SIDES[index]
            output = io.BytesIO()
            side.pb.screen.image.convert('RGB').save(output, format='JPEG', quality=80)
            pending = self.out / f'.{prefix}.jpg.pending'
            pending.write_bytes(output.getvalue())
            os.replace(pending, self.out / f'{prefix}.jpg')
        self.report()

    def report(self, force=False):
        now = time.monotonic()
        if not self.progress_callback or not force and now - self.last_report < 1:
            return
        self.last_report = now
        self.progress_callback({'phase': self.phase, 'frames': self.frames, 'trades': min(self.trades()),
            'sides': {side.spec.adventure_id: {'side': SIDES[index], 'frame': side.frame,
                      'preview_path': str((self.out / f'{SIDES[index]}.jpg').resolve())}
                      for index, side in enumerate(self.sides)}})

    def run(self, commands):
        """Hand the controllers to the owner until a finish or cancel command arrives."""
        self.started = time.monotonic()
        self.paced_from = self.frames    # Pace from here, not from the scripted walk into the club.
        deadline = self.started + self.plan.timeout_seconds
        while True:
            self.check_running()
            checked(time.monotonic() < deadline, 'Cable session deadline exceeded')
            while True:
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break
                if command.get('cancel'):
                    raise CableError('Cable session cancelled')
                if command.get('finish'):
                    return
                try:
                    self.press(command.get('side'), command.get('button'))
                except CableError:
                    pass
            self.tick()

    # Verification and publication.

    def finish(self):
        from ..interactions.link_worker import _write
        from .cable_metadata import ADAPTER_ID
        from .cable_verification import continue_save, evolved_species, party
        from .core import stop_with_clock
        from .ram import read_snapshot
        self.leave()
        self.phase = 'verifying'
        self.report(force=True)
        trades = self.trades()
        checked(min(trades) > 0, 'Finished without a trade')
        after = [party(side.pb, side.data) for side in self.sides]
        evidence = verify_parties(self.before, after, trades,
                                  lambda raw: evolved_species(raw, self.sides[0].data))
        results = {}
        for index, side in enumerate(self.sides):
            snapshot = read_snapshot(side.pb.memory, side.data, side.frame)
            verify_progress(self.snapshots[index], snapshot)
            save_stream, clock_stream = io.BytesIO(), io.BytesIO()
            stop_with_clock(side.pb, save_stream, clock_stream)
            side.stopped = True
            save = save_stream.getvalue()
            checked(len(save) == 32768, 'Unexpected cartridge save size')
            restarted = continue_save(side.rom_bytes, save, side.data, rtc=clock_stream.getvalue())
            try:
                checked(party(restarted, side.data) == after[index], 'Cartridge Continue changed the traded party')
                verify_progress(self.snapshots[index], read_snapshot(restarted.memory, side.data))
                state_stream = io.BytesIO()
                restarted.save_state(state_stream)
                state = state_stream.getvalue()
            finally:
                restarted.stop(save=False)
            prefix = SIDES[index]
            state_path, save_path = self.out / f'{prefix}.state', self.out / f'{prefix}.sav'
            _write(state_path, state)
            _write(save_path, save)
            _write(self.out / f'{prefix}.rtc', clock_stream.getvalue())
            evidence[index].update(cartridge_restart=True, checkpoint_restart=True, transport=dict(side.counts),
                                   storage_preserved=True, manual_session=True)
            results[side.spec.adventure_id] = {
                'adventure_id': side.spec.adventure_id, 'side': prefix, 'version': side.build['version'],
                'rom_sha1': side.rom_sha1, 'source': side.input_hashes, 'selected_key': None,
                'state_path': str(state_path.resolve()), 'cartridge_save_path': str(save_path.resolve()),
                'checkpoint_sha256': sha256(state), 'cartridge_sha256': sha256(save), 'evidence': evidence[index],
                'party_before': [{key: value.hex() for key, value in row.items()} for row in self.before[index]],
                'party_after': [{key: value.hex() for key, value in row.items()} for row in after[index]]}
        canonical = json.dumps(asdict(self.plan), sort_keys=True, separators=(',', ':')).encode()
        manifest = {'schema_version': 1, 'status': 'verified', 'adapter_id': ADAPTER_ID, 'kind': 'cable_session',
                    'interaction_id': self.plan.interaction_id, 'attempt_id': self.plan.attempt_id,
                    'plan_sha256': sha256(canonical), 'participants': results, 'trades': trades[0],
                    'return_method': 'cartridge_soft_reset_continue'}
        self.check_running()
        _write(self.out / 'manifest.pending', json.dumps(manifest, indent=2, sort_keys=True).encode())
        os.replace(self.out / 'manifest.pending', self.out / 'manifest.json')
        from ..platform_io import sync_directory
        sync_directory(self.out)
        self.phase = 'verified'
        self.report(force=True)
        return manifest

    def close(self):
        for side in self.sides:
            side.stop()


def run_session(plan, output_dir, commands, progress=None, cancelled=None):
    session = Session(plan, output_dir, progress, cancelled)
    try:
        session.open()
        session.enter()
        session.run(commands)
        return session.finish()
    except BaseException as error:
        from ..interactions.link_worker import _write
        if session.out.is_dir():
            _write(session.out / 'failure.json', json.dumps({'status': 'failed', 'error': str(error),
                   'sides': {side.spec.adventure_id: dict(side.counts) for side in session.sides}}).encode())
        raise
    finally:
        session.close()


def read_commands(stream, cancelled):
    """Queue the owner's JSON commands from ``stream`` on a thread.

    Standard input doubles as the parent liveness pipe, so its end sets ``cancelled``.
    """
    commands = queue.Queue()

    def read():
        try:
            for line in stream:
                try:
                    command = json.loads(line)
                except ValueError:
                    continue
                if isinstance(command, dict):
                    commands.put(command)
        finally:
            cancelled.set()

    threading.Thread(target=read, name='cable-session-commands', daemon=True).start()
    return commands


def main(argv=None):
    from ..interactions.link_worker import CableSessionPlan
    from ..runtime.worker import restore_worker_streams
    restore_worker_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    cancelled = threading.Event()
    commands = read_commands(sys.stdin, cancelled)
    try:
        plan = CableSessionPlan.from_dict(json.loads(args.plan.read_text()))
        run_session(plan, args.out, commands, lambda value: print(json.dumps(value), flush=True), cancelled)
    except (CableError, ValueError, OSError, TypeError) as error:
        parser.exit(1, f'Cable session failed: {error}\n')


if __name__ == '__main__':
    main()
