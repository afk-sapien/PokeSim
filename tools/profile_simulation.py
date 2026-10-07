"""Profile the complete simulation loop against a private copy of an adventure.

Capture never writes to the source. Keep fixtures and results outside Git.
The run includes policies, observations, hooks, events, saves, and optional
frame/audio production. HTTP and browser costs are measured separately.
"""
from __future__ import annotations

import argparse
import cProfile
from collections import defaultdict
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import pstats
import shutil
import sqlite3
import tempfile
import threading
import time


def capture(source, output, rom, game_data):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    target = output / 'adventure'
    target.mkdir()
    (target / 'states').mkdir()
    # Autosaves are immutable after their metadata has been published.
    for state in sorted((source / 'states').glob('auto-*.state'), reverse=True):
        try:
            metadata_raw = state.with_suffix('.json').read_bytes()
            metadata = json.loads(metadata_raw)
            raw = state.read_bytes()
            if hashlib.sha256(raw).hexdigest() != metadata['sha256']:
                continue
            (target / 'states' / state.name).write_bytes(raw)
            (target / 'states' / state.with_suffix('.json').name).write_bytes(metadata_raw)
            break
        except (OSError, ValueError, KeyError):
            continue
    else:
        raise ValueError('No complete, verified autosave was available')
    with sqlite3.connect(f'file:{source / "pokesim.sqlite"}?mode=ro', uri=True) as src:
        with sqlite3.connect(target / 'pokesim.sqlite') as dest:
            src.backup(dest)
    for directory in ('shots',):
        if (source / directory).exists():
            shutil.copytree(source / directory, target / directory)
    settings = json.loads((source / 'adventure.json').read_text())['settings']
    settings.pop('auto_start', None)
    shutil.copy2(rom, output / 'rom.gb')
    shutil.copytree(game_data, output / 'game-data')
    record = {'settings': settings, 'checkpoint': state.name,
              'checkpoint_sha256': metadata['sha256'], 'start_frame': metadata['frame'],
              'note': 'Database backup and latest complete autosave are separate snapshots, not an atomic application backup'}
    (output / 'fixture.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: value for key, value in record.items() if key != 'settings'}, indent=2))


def run(args):
    fixture = args.fixture.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    meta = json.loads((fixture / 'fixture.json').read_text())
    if args.cpu is not None:
        os.sched_setaffinity(0, {args.cpu})
    import psutil
    from pokesim.runtime import SimulationRuntime, SimulationSettings
    with tempfile.TemporaryDirectory(prefix='simulation-', dir=output) as temporary:
        data = Path(temporary) / 'adventure'
        shutil.copytree(fixture / 'adventure', data)
        settings = SimulationSettings.from_dict({**meta['settings'],
            'rom_path': str(fixture / 'rom.gb'), 'data_dir': str(data),
            'game_data_dir': str(fixture / 'game-data'), 'speed': 0,
            'ntfy_url': '', 'ntfy_token': '', 'seed': 12345})
        settings.install()
        from pokesim.emulator import Emulator
        from pokesim.policies.strategic import StrategicPolicy
        from pokesim_core.emulator import Emulator as CoreEmulator
        timings = defaultdict(lambda: {'calls': 0, 'wall': 0.0, 'cpu': 0.0,
                                       'exclusive_wall': 0.0, 'exclusive_cpu': 0.0})
        stack = []

        def measure(cls, name, label):
            original = getattr(cls, name)

            @functools.wraps(original)
            def measured(*pos, **kwargs):
                if threading.current_thread().name != 'emulator':
                    return original(*pos, **kwargs)
                entry = [time.perf_counter(), time.thread_time(), 0.0, 0.0]
                stack.append(entry)
                try:
                    return original(*pos, **kwargs)
                finally:
                    wall, cpu = time.perf_counter() - entry[0], time.thread_time() - entry[1]
                    stack.pop()
                    if stack:
                        stack[-1][2] += wall
                        stack[-1][3] += cpu
                    row = timings[label]
                    row['calls'] += 1
                    row['wall'] += wall
                    row['cpu'] += cpu
                    row['exclusive_wall'] += wall - entry[2]
                    row['exclusive_cpu'] += cpu - entry[3]
            descriptor = inspect.getattr_static(cls, name)
            setattr(cls, name, staticmethod(measured) if isinstance(descriptor, staticmethod) else measured)

        if args.profiler in {'timers', 'detailed'}:
            for cls, name, label in (
                (CoreEmulator, 'tick', 'emulator_and_hooks'),
                (StrategicPolicy, 'step', 'policy'),
                (Emulator, '_observe', 'observations_events_storage'),
                (Emulator, '_publish_frame', 'live_png'),
                (Emulator, '_autosave', 'autosave'),
                (Emulator, '_pace', 'pacing'),
                (Emulator, '_check_guards', 'recovery_guards'),
            ):
                measure(cls, name, label)
        if args.profiler == 'detailed':
            import pokesim.emulator as app_emulator
            from pokesim.policies.collection import Collection
            from pokesim.policies.navigation import Navigator
            from pokesim.store import Store
            for cls, name, label in (
                (Collection, 'partner_matches', 'partner_matching'),
                (Navigator, 'update_story', 'navigation_state'),
                (Navigator, 'route', 'route_search'),
                (app_emulator, 'read_snapshot', 'snapshot_decode'),
                (Store, 'get', 'database_reads'),
                (Store, 'set', 'database_writes'),
            ):
                measure(cls, name, label)

        original_run = Emulator._run
        original_tick = Emulator._tick
        result = {}
        profiler = cProfile.Profile() if args.profiler == 'cprofile' else None

        def bounded_tick(emu, count):
            original_tick(emu, min(count, args.frames - emu.executed_frames))
            if emu.executed_frames >= args.frames:
                emu.stopping = True

        def profiled_run(emu):
            start_wall, start_cpu = time.perf_counter(), time.thread_time()
            start_frame = emu.frame
            if profiler:
                profiler.enable()
            try:
                original_run(emu)
            finally:
                if profiler:
                    profiler.disable()
                    profiler.dump_stats(str(output / 'simulation.prof'))
                result.update(wall_seconds=time.perf_counter() - start_wall,
                              thread_cpu_seconds=time.thread_time() - start_cpu,
                              start_frame=start_frame, end_frame=emu.frame,
                              executed_frames=emu.executed_frames)

        Emulator._tick, Emulator._run = bounded_tick, profiled_run
        runtime = SimulationRuntime(settings)
        process = psutil.Process()
        started = time.perf_counter()
        runtime.start()
        result['startup_seconds'] = time.perf_counter() - started
        emu = runtime.emulator
        deadline = time.monotonic() + 300
        audio_sequence = -1
        while emu.thread.is_alive():
            if args.mode != 'headless':
                emu.watch()
            if args.mode == 'audio':
                _, audio_sequence, _, _ = emu.audio_packet(audio_sequence)
            if time.monotonic() > deadline:
                emu.stop()
                raise TimeoutError('Simulation exceeded five minutes')
            emu.thread.join(timeout=1 / 30)
        if emu.fatal_error or emu.executed_frames != args.frames:
            raise RuntimeError(emu.fatal_error or 'Simulation stopped before its frame budget')
        snapshot = emu.snapshot
        final_state = emu.store.latest_state()
        result.update(mode=args.mode, profiler=args.profiler, cpu=args.cpu,
                      frames_per_second=emu.executed_frames / result['wall_seconds'],
                      speed_multiplier=emu.executed_frames / result['wall_seconds'] / 60,
                      rss_mib=process.memory_info().rss / 2**20,
                      timings=dict(timings), checkpoint_sha256=meta['checkpoint_sha256'],
                      final_state_sha256=hashlib.sha256(final_state.read_bytes()).hexdigest(),
                      final_snapshot={'map': snapshot.map, 'x': snapshot.x, 'y': snapshot.y,
                                      'in_battle': snapshot.in_battle},
                      scope='Complete autonomous loop plus final save, startup excluded. No HTTP or manager. Frame budget is exact, wall-clock-dependent behavior is not frozen.')
        runtime.close()
        if profiler:
            rows = []
            for (filename, line, name), (primitive, calls, own, cumulative, callers) in pstats.Stats(profiler).stats.items():
                rows.append({'file': filename, 'line': line, 'name': name, 'calls': calls,
                             'self_seconds': own, 'cumulative_seconds': cumulative})
            result['functions'] = sorted(rows, key=lambda row: row['self_seconds'], reverse=True)
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({key: value for key, value in result.items() if key not in {'functions', 'timings'}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    cap = commands.add_parser('capture')
    cap.add_argument('--source', type=Path, required=True)
    cap.add_argument('--output', type=Path, required=True)
    cap.add_argument('--rom', type=Path, required=True)
    cap.add_argument('--game-data', type=Path, required=True)
    replay = commands.add_parser('run')
    replay.add_argument('--fixture', type=Path, required=True)
    replay.add_argument('--output', type=Path, required=True)
    replay.add_argument('--frames', type=int, default=120000)
    replay.add_argument('--mode', choices=['headless', 'viewer', 'audio'], default='headless')
    replay.add_argument('--profiler', choices=['none', 'timers', 'detailed', 'cprofile'], default='none')
    replay.add_argument('--cpu', type=int)
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[1]
    if args.output.resolve().is_relative_to(checkout):
        parser.error('Keep private profiling outputs outside the source checkout')
    if args.command == 'capture':
        if args.output.resolve().is_relative_to(args.source.resolve()):
            parser.error('The capture destination must be separate from the source adventure')
        capture(args.source.resolve(), args.output.resolve(), args.rom.resolve(), args.game_data.resolve())
    else:
        if args.output.resolve().is_relative_to(args.fixture.resolve()):
            parser.error('The run output must be separate from the immutable fixture')
        if args.frames < 1:
            parser.error('Frames must be positive')
        run(args)


if __name__ == '__main__':
    main()
