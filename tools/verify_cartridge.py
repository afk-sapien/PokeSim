"""Exercise real cartridges, cable sessions and Gen II saves on disposable copies.

Each subcommand is one check. Run python tools/verify_cartridge.py SUBCOMMAND --help for its options.

  managed-app     the real manager coordinator, three workers, and committed recovery
  managed-cable   private worker processes and real cartridge trading
  cable-session   the real cartridge cable matrix against private, disposable test fixtures
  cable-fixtures  prepare disposable, explicitly synthetic party fixtures for Cable Club testing
  gen2-probe      boot owner-supplied Gen II ROMs and check input, observation and checkpoints
  gen2-clock      simulate elapsed cartridge clock time in an isolated format 15 checkpoint
  gen2-save       verify a late-campaign portable save after dismissing the ending credits
  gen2-trading    exercise managed Gen II PC preparation on a disposable adventure copy

Only the standard library loads at import. Each check imports what it needs when it runs.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace


# managed-app: the real manager coordinator, three workers, and committed recovery.

def exercise_app(root, fixtures, roms, game_data, progress=print):
    from pokesim import state
    from pokesim.app.manager import Manager
    from pokesim.app.registry import identifier
    from pokesim.checkpoints import CheckpointStore
    from pokesim.interactions.cable import checked
    from pokesim.state import kv
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
        with closing(state.connect(root / 'adventures' / aid / 'pokesim.sqlite', read_only=True)) as db:
            count = len(kv.starting(db, 'managed_journal:'))
        checked(count == (0 if aid == ids[2] else 1), 'Managed trade journal count is incorrect')
    for edition, expected in source_hashes.items():
        checked(hashlib.sha256((Path(fixtures) / f'{edition}.state').read_bytes()).hexdigest() == expected,
                'Original fixture was changed')
    report['journal_exactly_once'] = True
    report['source_fixtures_unchanged'] = True
    (root / 'integration-result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def managed_app(args):
    print(json.dumps(exercise_app(args.out, args.fixtures, args.roms, args.game_data), indent=2))


# managed-cable: private worker processes and real cartridge trading on disposable copies.

A = 'a' * 32
B = 'b' * 32


def exercise_cable(root, fixtures, roms, game_data, abort=False, progress=print):
    from pokesim.app.supervisor import Child
    from pokesim.state import kv, schema
    from pokesim.checkpoints import CheckpointStore
    from pokesim.interactions.cable import checked
    from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan
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
            children[aid].request('POST', '/internal/speed', {'speed': 0})
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
        (root / 'link.stdout.log').write_text(result.stdout, encoding='utf-8')
        (root / 'link.stderr.log').write_text(result.stderr, encoding='utf-8')
        checked(result.returncode == 0, 'Link subprocess failed: ' + result.stderr[-1200:])
        manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
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
                children[aid].request('POST', '/internal/speed', {'speed': 0.1})
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
                children[aid].request('POST', '/internal/speed', {'speed': 0.1})
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
            (root / f'{aid}.worker.log').write_text('\n'.join(child.logs), encoding='utf-8')
        raise
    finally:
        for child in children.values():
            child.stop()
    for aid in children:
        with closing(schema.connect(root / 'adventures' / aid / 'pokesim.sqlite', read_only=True)) as db:
            count = int(kv.exists(db, 'managed_journal:' + tid))
            checked(count == (0 if abort else 1), 'Trade journal was duplicated or lost')
    report['journal_once' if not abort else 'no_committed_journal'] = True
    (root / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def managed_cable(args):
    print(json.dumps(exercise_cable(args.out, args.fixtures, args.roms, args.game_data, args.abort), indent=2))


# cable-session: the real cartridge cable matrix against private, disposable test fixtures.

def cable_session(args):
    from pokesim.interactions.cable import CableError, CableSide, checked
    from pokesim.interactions.cable_driver import CableDriver
    from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan, run_session
    from pokesim.interactions.verification import party
    args.out.mkdir(parents=True, exist_ok=False)
    def side(name, edition, slot=0):
        return CableParticipant(name, str(args.roms / f'poke{edition}.gbc'),
            str(args.fixtures / f'{edition}.state'), str(args.fixtures / f'{edition}.sav'), party_slot=slot)
    cases = []
    for left, right in [('red', 'blue'), ('red', 'red'), ('blue', 'blue')]:
        for reverse in (False, True):
            cases.append((f'{left}-{right}-{int(reverse)}', left, right, 0, 0, reverse))
    for slot in range(6):
        cases.append((f'slots-{slot}-{5-slot}', 'red', 'blue', slot, 5-slot, False))
    report = {'status': 'passed', 'cases': {}}
    for name, left, right, left_slot, right_slot, reverse in cases:
        started = time.monotonic()
        plan = CableSessionPlan(name, 'attempt-1', side('left', left, left_slot),
            side('right', right, right_slot), external_left=reverse, speed=0, timeout_seconds=60)
        result = run_session(plan, args.out / name)
        report['cases'][name] = {'status': result['status'],
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'adapter_id': result['adapter_id'],
            'sides': {key: row['evidence'] for key, row in result['participants'].items()}}
        print(name, 'passed', flush=True)
    plan = CableSessionPlan('no-cable', 'attempt-1', side('left', 'red'), side('right', 'blue'),
                             speed=0, timeout_seconds=60, max_steps=200)
    sides = [CableSide(plan.left), CableSide(plan.right)]
    try:
        sides[0].peer, sides[1].peer = sides[1], sides[0]
        before = [party(endpoint.pb, endpoint.sym) for endpoint in sides]
        for i, endpoint in enumerate(sides):
            endpoint.attach(i + 1, enabled=False)
        driver = CableDriver(sides, plan)
        driver.enter()
        try:
            driver.exchange()
        except CableError:
            pass
        else:
            raise CableError('Trade incorrectly succeeded with disconnected cable')
        checked(all(not endpoint.counts['TradeCenter_Trade'] and party(endpoint.pb, endpoint.sym) == old
                    for endpoint, old in zip(sides, before)), 'Disconnected cable changed party')
        report['negative_control'] = {'status': 'passed', 'parties_unchanged': True, 'trades': 0}
    finally:
        for endpoint in sides:
            endpoint.stop()
    (args.out / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'cases': len(cases), 'negative_control': 'passed'}))


# cable-fixtures: disposable, explicitly synthetic party fixtures for Cable Club testing.

def symbols(path):
    result = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{2}):([0-9a-fA-F]{4}) (.+)', line)
        if match:
            result[match[3]] = (int(match[1], 16), int(match[2], 16))
    return result


def press(pb, button, frames=8, after=24):
    pb.button_press(button)
    pb.tick(frames)
    pb.button_release(button)
    pb.tick(after)


def prepare_fixture(rom, sym, state, out, name, species, default_name=False):
    from pokecore.emulator import Emulator as PyBoy
    from pokesim.screen import Screen
    from pokesim.strategy_data import MOVES, SPECIES
    from pokesim.trade.boxes import encode_text
    pb = PyBoy(str(rom), window='null', sound_emulated=False, log_level='ERROR')
    pb.set_emulation_speed(0)
    with state.open('rb') as f:
        pb.load_state(f)
    syms = symbols(sym)
    def put(key, data):
        addr = syms[key][1]
        pb.memory[addr:addr + len(data)] = data
    put('wPlayerName', encode_text(name))
    put('wPlayerID', [0x12, 0x34] if name == 'RED' else [0x56, 0x78])
    level = 30
    row = SPECIES[species]
    stats = [((base + 10) * 2 * level // 100) + (level + 10 if i == 0 else 5)
             for i, base in enumerate(row['stats'])]
    mon = bytearray(44)
    mon[0] = species
    mon[1:3] = stats[0].to_bytes(2, 'big')
    mon[3] = level
    mon[5:7] = bytes(row['types'])
    mon[7] = row['catch_rate']
    moves = (row['initial_moves'] + [move for learned, move in row['learnset'] if learned <= level])[-4:]
    moves += [0] * (4 - len(moves))
    mon[8:12] = bytes(moves)
    mon[12:14] = bytes([0x12, 0x34] if name == 'RED' else [0x56, 0x78])
    assert row['growth'] == 'MEDIUM_SLOW'
    experience = 6 * level ** 3 // 5 - 15 * level ** 2 + 100 * level - 140
    mon[14:17] = experience.to_bytes(3, 'big')
    mon[27:29] = bytes([0xaa, 0xaa])
    mon[29:33] = bytes(MOVES[move]['pp'] if move else 0 for move in moves)
    mon[33] = level
    for i, stat in enumerate(stats):
        mon[34 + i * 2:36 + i * 2] = stat.to_bytes(2, 'big')
    put('wPartyMon1', mon)
    put('wPartySpecies', [species])
    put('wPartyMon1Nick', encode_text(row['name'].upper() if default_name else 'SPOOKY' if name == 'RED' else 'SPOON'))
    put('wPartyMon1OT', encode_text(name))
    press(pb, 'start')
    for _ in range(20):
        screen = Screen(pb.memory)
        row = next((i for i, line in enumerate(screen.rows) if 'SAVE' in line), None)
        if row is not None and screen.cursor:
            if screen.cursor[1] == row:
                press(pb, 'a')
                break
            press(pb, 'down' if screen.cursor[1] < row else 'up')
        else:
            pb.tick(30)
    saved = False
    for _ in range(60):
        screen = Screen(pb.memory)
        if 'SAVED' in screen.text.upper():
            saved = True
            pb.tick(120)
            break
        press(pb, 'a')
    assert saved, Screen(pb.memory).text
    ram = io.BytesIO()
    pb.stop(ram_file=ram)
    (out / f'{name.lower()}.sav').write_bytes(ram.getvalue())
    print(name, 'saved synthetic fixture', flush=True)


def cold_boot(rom, save, output):
    from pokecore.emulator import Emulator as PyBoy
    from pokesim.ram import read_snapshot
    from pokesim.screen import Screen
    pb = PyBoy(str(rom), ram_file=io.BytesIO(save.read_bytes()), window='null', sound_emulated=False, log_level='ERROR')
    pb.set_emulation_speed(0)
    pb.tick(180)
    for i in range(160):
        if 'CONTINUE' in Screen(pb.memory).text:
            press(pb, 'a', after=240)
            press(pb, 'a', after=240)
            assert 'CONTINUE' not in Screen(pb.memory).text
            s = read_snapshot(pb.memory, 0)
            assert s.valid and s.started and s.map == 89
            # Save data contains ROM map pointers. Reenter through a real warp
            # so the recipient version rebuilds its map header from its own ROM.
            for _ in range(8):
                press(pb, 'down', after=120)
                if read_snapshot(pb.memory, 0).map != 89:
                    break
            assert read_snapshot(pb.memory, 0).map != 89
            for _ in range(8):
                press(pb, 'up', after=120)
                if read_snapshot(pb.memory, 0).map == 89:
                    break
            assert read_snapshot(pb.memory, 0).map == 89
            with output.open('wb') as f:
                pb.save_state(f)
            print(rom.name, 'cold boot', [(m.nick, m.species) for m in read_snapshot(pb.memory,0).party], flush=True)
            pb.stop(save=False)
            return
        press(pb, 'start' if i % 3 == 0 else 'a')
    raise RuntimeError(Screen(pb.memory).text)


def cable_fixtures(args):
    args.out.mkdir(parents=True, exist_ok=False)
    for name, species in [('RED', args.left_species), ('BLUE', args.right_species)]:
        prepare_fixture(args.reference / 'pokered.gbc', args.reference / 'pokered.sym',
                        args.state, args.out, name, species, args.default_names)
        cold_boot(args.reference / ('pokered.gbc' if name == 'RED' else 'pokeblue.gbc'),
                  args.out / f'{name.lower()}.sav', args.out / f'{name.lower()}.state')


# gen2-probe: boot owner-supplied Gen II ROMs and check input, observation and checkpoints.
# This experiment never starts the Red/Blue adventure runtime.

def ram_digest(pb):
    """Hash fixed WRAM and bank 1, independent of the bank selected by the CPU."""
    raw = bytearray()
    for bank in (0, 1):
        # Upstream PyBoy 2.7.0 rejected a banked slice ending exactly at the bank boundary.
        start = 0xC000 + bank * 0x1000
        raw.extend(pb.memory[bank, start:start + 0xFFF])
        raw.append(pb.memory[bank, start + 0xFFF])
    return hashlib.sha256(raw).hexdigest()


def probe(source: Path, output: Path) -> dict:
    from pokecore.gen2.clock import FIXED_CLOCK_EPOCH, boot, lock_clock
    from pokecore.emulator_state import runtime_provenance
    from pokesim.experimental.gen2 import load_rom, read_snapshot
    profile, raw = load_rom(source)
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='pokesim-gen2-') as temporary:
        rom = Path(temporary) / 'probe.gbc'
        rom.write_bytes(raw)

        def start():
            pb = boot(str(rom), sound=True)
            # Set before the first tick so a test's clock cannot move backwards. The clock reads zero
            # elapsed time at the fixed instant and stays there, as the PyBoy exploration's lock did.
            lock_clock(pb, True, at=FIXED_CLOCK_EPOCH, rebase=True)
            return pb

        def tap(pb, button, frames):
            # Core exposes press/release only; hold for the requested frames.
            pb.press(button)
            pb.tick(frames, True)
            pb.release(button)

        def walk(pb):
            tap(pb, 'right', 16)
            pb.tick(60, True)
            return read_snapshot(pb.memory, profile), ram_digest(pb), pb.screen.image.tobytes()

        pb = start()
        try:
            pb.tick(1200, True)
            pb.screen.image.save(output / 'opening.png')
            tap(pb, 'start', 8)
            pb.tick(120, True)
            # Bounded input replay for the English opening, not a general policy.
            for _ in range(110):
                tap(pb, 'a', 8)
                pb.tick(60, True)
            before = read_snapshot(pb.memory, profile)
            if (before.map_group, before.map_number, before.x, before.y) != (24, 7, 3, 3):
                pb.screen.image.save(output / 'failure.png')
                raise RuntimeError(f'Opening did not reach the bedroom: {before}')
            pb.screen.image.save(output / 'bedroom.png')
            checkpoint = io.BytesIO()
            pb.save_state(checkpoint)
            state = checkpoint.getvalue()
            (output / 'bedroom.state').write_bytes(state)
            before_ram = ram_digest(pb)
            after, after_ram, after_pixels = walk(pb)
            if (after.map_group, after.map_number, after.x, after.y) != (24, 7, 4, 3):
                raise RuntimeError(f'Right input did not move one tile: {after}')
            pb.screen.image.save(output / 'walk.png')
            pb.load_state(io.BytesIO(state))
            if read_snapshot(pb.memory, profile) != before or ram_digest(pb) != before_ram:
                raise RuntimeError('Checkpoint failed to restore observed state and WRAM')
            if walk(pb) != (after, after_ram, after_pixels):
                raise RuntimeError('Checkpoint replay diverged')
            title = pb.cartridge_title
        finally:
            pb.stop(save=False)

        restored = start()
        try:
            restored.load_state(io.BytesIO(state))
            if read_snapshot(restored.memory, profile) != before or ram_digest(restored) != before_ram:
                raise RuntimeError('Fresh emulator did not restore the checkpoint')
            if walk(restored) != (after, after_ram, after_pixels):
                raise RuntimeError('Fresh emulator checkpoint replay diverged')
        finally:
            restored.stop(save=False)

    result = {
        'game': profile.game, 'revision': profile.revision, 'sha1': profile.sha1,
        'cartridge_title': title, 'emulator': dict(runtime_provenance()),
        'mode': 'CGB', 'rtc': 'locked before first tick', 'opening_frames': 7920,
        'checks': {'bedroom_reached': True, 'walked_one_tile': True,
                   'checkpoint_restores_wram': True, 'checkpoint_replays_pixels_and_wram': True,
                   'fresh_emulator_replays_pixels_and_wram': True},
        'before_walk': asdict(before), 'after_walk': asdict(after),
        'checkpoint_bytes': len(state), 'production_support': False,
    }
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def gen2_probe(args):
    from pokesim.experimental.gen2 import load_rom
    # Validate all inputs before starting any emulator or creating output.
    profiles = [load_rom(path)[0] for path in args.roms]
    if len({profile.game for profile in profiles}) != len(profiles):
        args.error('Supply each game only once')
    args.output.mkdir(parents=True, exist_ok=False)
    reports = []
    for source, profile in zip(args.roms, profiles):
        report = probe(source, args.output / profile.game)
        reports.append(report)
        print(f'{profile.game}: bedroom, movement and both checkpoint replays passed', flush=True)
    (args.output / 'report.json').write_text(json.dumps(reports, indent=2) + '\n', encoding='utf-8')


# gen2-clock: simulate elapsed cartridge clock time in an isolated format 15 checkpoint.

def advance(raw, hours):
    if raw[0] != 15 or len(raw) < 100000:
        raise ValueError('Clock simulation requires a format 15 checkpoint')
    if not math.isfinite(hours) or not 0 < hours <= 24 * 7:
        raise ValueError('Advance the clock by at most seven days per simulation step')
    # On an MBC3 clock cartridge the format 15 state ends with the base timestamp (the .rtc file's
    # first eight bytes), the halt and carry bytes, two joypad bytes, then 36 serial-port bytes.
    # Verified against PyBoy RS state writer and Core's export_rtc on Gold, Silver and Crystal.
    offset = len(raw) - 48
    epoch = struct.unpack_from('d', raw, offset)[0]
    if not math.isfinite(epoch) or not 946684800 <= epoch <= 4102444800 or raw[offset + 8] > 1 or raw[offset + 9] > 1:
        raise ValueError('The checkpoint does not have the expected RTC timestamp')
    result = bytearray(raw)
    struct.pack_into('d', result, offset, epoch - hours * 3600)
    return bytes(result)


def gen2_clock(args):
    raw = args.source.read_bytes()
    result = advance(raw, args.hours)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    metadata = args.source.with_suffix('.policy.json')
    if metadata.exists():
        shutil.copyfile(metadata, args.output.with_suffix('.policy.json'))
    args.output.with_suffix('.clock.json').write_text(json.dumps({
        'source': str(args.source.resolve()), 'hours_elapsed': args.hours,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'result_sha256': hashlib.sha256(result).hexdigest(),
        'changed': 'Only the emulator RTC epoch. No cartridge RAM or Pokémon data was changed.'}, indent=2), encoding='utf-8')


# gen2-save: verify a late-campaign portable save after dismissing the ending credits.

def gen2_save(args):
    from pokecore.gen2.clock import boot
    from pokecore.gen2.ram import read_snapshot
    from pokesim.gen2.data import GameData
    from pokesim.gen2.save import export_with_clock, press
    data = GameData.load(args.data, args.game)
    pb = boot(str(args.rom), sound=True)
    pb.set_emulation_speed(0)
    try:
        pb.load_state(io.BytesIO(args.state.read_bytes()))
        for step in range(1000):
            press(pb, 'start' if step % 3 == 0 else 'a', 60)
            snapshot = read_snapshot(pb.memory, data)
            if snapshot.map == data.map_ids['SILVER_CAVE_OUTSIDE'] and '┌' not in snapshot.tiles[12]:
                break
        else:
            raise AssertionError('The ending did not return the trainer to Mt. Silver')
        press(pb, wait=120)
        state = io.BytesIO()
        pb.save_state(state)
        save, clock = export_with_clock(args.rom, state.getvalue(), data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(save)
        args.output.with_suffix('.rtc').write_bytes(clock)
        print(f'{args.game}: {len(save)} bytes and {len(clock)} clock bytes verified by a fresh cartridge Continue with its clock')
    finally:
        pb.stop(save=False)


# gen2-trading: exercise managed Gen II PC preparation on a disposable adventure copy.

def gen2_trading(args):
    if args.evolve and args.time_capsule:
        args.error('--evolve requires a Gen II Cable Club trade')
    if (args.output / 'store').exists():
        args.error(f'{args.output / "store"} already exists. Use a fresh --output so no earlier preparation is resumed')
    from pokecore.gen2.ram import read_snapshot
    from pokesim.gen2.emulator import Emulator
    from pokesim.gen2.trading import Participant
    from pokesim.runtime.game_loop import GEN2_WAIT, Decider, GameLoop, play
    from pokesim.runtime.policy import Action
    from pokesim.runtime.settings import SimulationSettings
    from pokesim.store import Store
    args.output.mkdir(parents=True, exist_ok=True)
    rom = args.rom or Path(os.environ.get('GEN2_CARTRIDGE_DIR', '.release-local/gen2')) / f'{args.game}.gbc'
    data = args.data or Path(os.environ.get('GEN2_DATA_DIR', '.release-local/gen2-data'))
    settings = SimulationSettings(rom_path=str(rom.resolve()),
        data_dir=str((args.output / 'store').resolve()), game_data_dir=str(data.resolve()),
        starter='random', speed=0)
    settings.install(managed=True)
    store = Store(Path(settings.data_dir))
    emu = Emulator(store)

    def tick(count):
        if count > 0:
            emu.pb.tick(count, True)
            emu.frame += count
            emu.play_clock.advance(count)

    try:
        with args.load.open('rb') as source:
            emu.pb.load_state(source)
        metadata = args.load.with_suffix('.policy.json')
        if metadata.exists():
            emu.policy.load_state_dict(json.loads(metadata.read_text(encoding='utf-8')))
        for _ in range(12):
            # Close any open text before the policy starts. These presses are not game time.
            play(emu.pb, Action('b', 8, 32), lambda count: emu.pb.tick(count, True))
        emu.snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
        # The policy and the preparation count their waits on the PlayClock, as the managed worker does.
        emu.play_clock.seed(emu.snapshot.playtime_seconds)
        loop = GameLoop(emu, Decider(lambda: emu.play_clock.frames, wait=GEN2_WAIT), tick)
        for _ in range(6000):
            from pokecore.gen2.ram import Memory
            snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
            if (snapshot.started and not snapshot.in_battle and not emu.policy.in_league(snapshot)
                    and not Memory(emu.pb.memory, emu.data).byte('wScriptRunning')):
                break
            loop.step(snapshot)
        emu.snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
        runtime = SimpleNamespace(store=store, emulator=emu, settings=settings)
        participant = Participant(runtime, SimpleNamespace(adventure_id=args.game, generation=1))
        if args.offer_trained:
            from pokesim.gen2.views import state_view
            from pokesim.gen2.web import live_status
            from pokesim.trade.preferences import apply, update
            payload = apply(live_status(state_view(emu.snapshot, egg_view=True)), store.trade_preferences())
            for mon in payload['storage']['pokemon']:
                if mon['species'] == args.species and not mon['trade_ambiguous'] and tuple(mon['dvs']) != (15,) * 5:
                    update(store, payload, mon['trade_key'], 'offered')
        inventory = participant.inventory()
        assert inventory['offers'], 'No eligible boxed Pokémon in this scenario'
        offer = next((mon for mon in inventory['offers']
                      if (args.species is None or mon['species'] == args.species)
                      and (args.trade_key is None or mon['trade_key'] == args.trade_key)), None)
        assert offer, 'The requested species is not an eligible boxed offer'
        if args.evolve:
            from pokesim.gen2.cable_verification import available_trade_item, evolved_species
            item = available_trade_item(emu.data, offer['species'], offer['held_item'],
                                        dict(emu.snapshot.items), replace_held=True)
            if item is None and evolved_species(bytes((offer['species'], offer['held_item'])), emu.data) == offer['species']:
                raise ValueError('No evolution item is available for this partner')
        key = offer['trade_key']
        request = {'id': '0123456789abcdef0123456789abcdef', 'plan_digest': 'test', 'selected_key': key,
                   'time_capsule': args.time_capsule}
        receipt = participant.prepare(request)
        if args.evolve:
            emu.preparation.state['replace_held'] = True
        for step in range(4000):
            snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
            loop.pending = [emu.preparation.step(snapshot)]
            action = loop.act()
            emu.snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
            if step % 50 == 0:
                print(step, emu.snapshot.map_name, emu.snapshot.x, emu.snapshot.y, action,
                      vars(emu.preparation.menu) if emu.preparation.menu else None, flush=True)
            if emu.preparation.state['phase'] in {'ready', 'failed'}:
                receipt = participant.prepare(request)
                break
        assert receipt['phase'] == 'prepared', receipt
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print('Prepared boxed offer through the cartridge PC', receipt['source'], flush=True)
    finally:
        emu.pb.screen.image.save(args.output / 'final.png')
        with (args.output / 'final.state').open('wb') as output:
            emu.pb.save_state(output)
        emu.pb.stop(save=False)
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True, metavar='SUBCOMMAND')

    def command(name, run, description):
        sub = commands.add_parser(name, help=description, description=description)
        sub.set_defaults(run=run, error=sub.error)
        return sub

    for name, run, description in (
            ('managed-app', managed_app, 'Verify the real manager coordinator, three workers, and committed recovery.'),
            ('managed-cable', managed_cable,
             'Exercise private worker processes and real cartridge trading on disposable copies.')):
        sub = command(name, run, description)
        sub.add_argument('--fixtures', type=Path, required=True)
        sub.add_argument('--roms', type=Path, required=True)
        sub.add_argument('--game-data', type=Path, required=True)
        sub.add_argument('--out', type=Path, required=True)
        if name == 'managed-cable':
            sub.add_argument('--abort', action='store_true')

    sub = command('cable-session', cable_session,
                  'Run the real cartridge cable matrix against private, disposable test fixtures.')
    sub.add_argument('--roms', type=Path, required=True)
    sub.add_argument('--fixtures', type=Path, required=True)
    sub.add_argument('--out', type=Path, required=True)

    sub = command('cable-fixtures', cable_fixtures,
                  'Prepare disposable, explicitly synthetic party fixtures for Cable Club testing.')
    sub.add_argument('--reference', type=Path, required=True)
    sub.add_argument('--state', type=Path, required=True)
    sub.add_argument('--out', type=Path, required=True)
    sub.add_argument('--default-names', action='store_true')
    sub.add_argument('--left-species', type=int, default=147)
    sub.add_argument('--right-species', type=int, default=38)

    sub = command('gen2-probe', gen2_probe,
                  'Boot owner-supplied Gen II ROMs and check input, observation and checkpoints. '
                  'This experiment never starts the Red/Blue adventure runtime.')
    sub.add_argument('roms', type=Path, nargs='+')
    sub.add_argument('--output', type=Path, required=True, help='New output directory')

    sub = command('gen2-clock', gen2_clock, 'Simulate elapsed cartridge clock time in an isolated format 15 checkpoint.')
    sub.add_argument('source', type=Path)
    sub.add_argument('output', type=Path)
    sub.add_argument('--hours', type=float, required=True)

    sub = command('gen2-save', gen2_save, 'Verify a late-campaign portable save after dismissing the ending credits.')
    sub.add_argument('rom', type=Path)
    sub.add_argument('state', type=Path)
    sub.add_argument('--game', required=True, choices=('gold', 'silver', 'crystal'))
    sub.add_argument('--data', type=Path, default=Path(os.environ.get('GEN2_DATA_DIR', '.release-local/gen2-data')))
    sub.add_argument('--output', type=Path, required=True)

    sub = command('gen2-trading', gen2_trading, 'Exercise managed Gen II PC preparation on a disposable adventure copy.')
    sub.add_argument('--game', required=True)
    sub.add_argument('--rom', type=Path, help='Cartridge file (default: $GEN2_CARTRIDGE_DIR/<game>.gbc, else .release-local/gen2/<game>.gbc)')
    sub.add_argument('--data', type=Path, help='Generated Gen II data folder (default: $GEN2_DATA_DIR, else .release-local/gen2-data)')
    sub.add_argument('--load', type=Path, required=True)
    sub.add_argument('--output', type=Path, required=True)
    sub.add_argument('--species', type=int)
    sub.add_argument('--trade-key', help='Select one exact boxed individual')
    sub.add_argument('--time-capsule', action='store_true')
    sub.add_argument('--offer-trained', action='store_true')
    sub.add_argument('--evolve', action='store_true', help='Swap the held item for an available evolution item through native menus')

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == '__main__':
    main()
