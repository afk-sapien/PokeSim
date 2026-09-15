"""Benchmark identical private decision inputs and verify fixed-frame gameplay traces.

Capture and trace read fixture.json with settings, checkpoint.state and checkpoint.json
beside it. Outputs contain private game data and must remain outside the checkout.
Replay accepts only a locally generated, explicitly trusted pickle workload.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import gzip
import hashlib
import io
import importlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import pickle
import platform
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def summary(values):
    ordered = sorted(values)
    return {'calls': len(values), 'total_ms': sum(values),
            'mean_ms': statistics.mean(values) if values else None,
            'p95_ms': ordered[math.ceil(len(ordered) * .95) - 1] if ordered else None,
            'max_ms': max(values, default=None)}


def peak_rss_mib():
    try:
        import resource
    except ImportError:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 ** 2 if sys.platform == 'darwin' else 1024)


def dependency_versions():
    result = {}
    for name in ('pyboy', 'numpy', 'numba', 'llvmlite'):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def numba_cache_state():
    directory = os.environ.get('NUMBA_CACHE_DIR')
    if not directory:
        return {'directory': None, 'files': None}
    path = Path(directory).resolve()
    files = sorted(str(item.relative_to(path)) for item in path.rglob('*')
                   if item.is_file() and item.suffix in {'.nbi', '.nbc'})
    return {'directory': str(path), 'files': files}


def cache_size(policy):
    nav = getattr(policy, 'nav', None)
    names = ('_world_indices', '_graph_signature', '_map_signatures', '_neighbor_cache', '_compiled_graph')
    roots = {name: getattr(nav, name) for name in names if hasattr(nav, name)}
    seen = set()
    numpy = sys.modules.get('numpy')
    numpy_arrays = numpy_bytes = numpy_headers = 0

    def size(value):
        nonlocal numpy_arrays, numpy_bytes, numpy_headers
        if id(value) in seen:
            return 0
        seen.add(id(value))
        total = sys.getsizeof(value)
        if numpy is not None and isinstance(value, numpy.ndarray):
            numpy_arrays += 1
            # Owned buffers are already included in ndarray.__sizeof__.
            # Views account only for their header, then follow the shared owner.
            owned = value.nbytes if value.flags.owndata else 0
            numpy_bytes += owned
            numpy_headers += total - owned
            return total + (size(value.base) if value.base is not None else 0)
        if isinstance(value, memoryview):
            return total + size(value.obj)
        if isinstance(value, dict):
            return total + sum(size(key) + size(item) for key, item in value.items())
        if isinstance(value, (tuple, list, set, frozenset)):
            return total + sum(size(item) for item in value)
        if type(value).__module__ == 'pokesim.policies.navigation_numba' and hasattr(value, '__dict__'):
            # Dispatcher machine code and compiler internals belong to process RSS.
            return total + size({key: item for key, item in vars(value).items() if key != 'run'})
        return total

    total = size(roots) if roots else 0
    graph = getattr(nav, '_compiled_graph', None)
    return {'reachable_bytes_estimate': total,
            'numpy_owned_buffer_bytes': numpy_bytes, 'numpy_header_bytes': numpy_headers,
            'numpy_array_objects': numpy_arrays,
            'compiled_graph_nodes': len(getattr(graph, 'positions', ())),
            'neighbor_cells': sum(len(rows) for rows in getattr(nav, '_neighbor_cache', {}).values()),
            'note': 'Shared Python objects and NumPy owners counted once. Includes retained graph arrays, not temporary search buffers or compiler code. Not exclusive allocation size.'}


def source_info(source):
    files = sorted((source / 'pokesim').rglob('*.py'))
    return {'root': str(source), 'sha256': digest([
        (str(path.relative_to(source)), hashlib.sha256(path.read_bytes()).hexdigest()) for path in files]),
        'navigation_sha256': hashlib.sha256((source / 'pokesim/policies/navigation.py').read_bytes()).hexdigest(),
        'python': platform.python_version()}


def configure(fixture, data_dir):
    from pokesim.runtime.settings import SimulationSettings
    settings = SimulationSettings.from_dict({**fixture['settings'], 'data_dir': str(data_dir),
        'speed': 0, 'ntfy_url': '', 'league_rewards': False, 'mew_event': False})
    settings.install(managed=True)
    return settings


def policy_start(fixture, metadata):
    from pokesim import config
    from pokesim.policies import make_policy
    policy = make_policy(config.POLICY, config.SEED)
    preferences = fixture.get('trade_preferences', {})
    policy.trade_preferences = lambda: preferences
    known = config.KNOWN_ROM_SHA1.get(metadata['rom_sha1'], '')
    if hasattr(policy, 'nav'):
        policy.nav.use_world = bool(known)
    if hasattr(policy, 'collection'):
        policy.collection.version = 'blue' if 'Blue' in known else 'red'
    policy.load_state_dict(metadata['policy_state'])
    policy.on_restore()
    return policy


class Timings:
    def __init__(self):
        self.decision_wall = []
        self.decision_cpu = []
        self.route_wall = []
        self.route_cpu = []
        self.backend = {'requested': os.environ.get('POKESIM_NAVIGATION_BACKEND', 'auto'),
                        'module_available': False, 'graph_route_calls': 0,
                        'jit_graph_route_calls': 0, 'graph_route_errors': 0,
                        'kernel_initializations': []}

    @contextmanager
    def routes(self):
        from pokesim.policies.navigation import Navigator
        original = Navigator.route
        module = None
        imported = time.perf_counter_ns()
        try:
            module = importlib.import_module('pokesim.policies.navigation_numba')
        except ModuleNotFoundError as error:
            if error.name != 'pokesim.policies.navigation_numba':
                raise
        self.backend['module_import_ms'] = (time.perf_counter_ns() - imported) / 1e6
        if module is not None:
            self.backend['module_available'] = True
            original_graph_route, original_kernel = module.SearchGraph.route, module.kernel

            def graph_route(graph, *args, **kwargs):
                self.backend['graph_route_calls'] += 1
                if getattr(graph.run, 'nopython_signatures', ()):
                    self.backend['jit_graph_route_calls'] += 1
                try:
                    return original_graph_route(graph, *args, **kwargs)
                except Exception:
                    self.backend['graph_route_errors'] += 1
                    raise

            def initialize_kernel():
                first = (getattr(module, '_kernel', None) is None
                         and not getattr(module, '_unavailable', False)
                         and os.environ.get('POKESIM_NAVIGATION_BACKEND') != 'python')
                started = time.perf_counter_ns()
                result = original_kernel()
                if first:
                    self.backend['kernel_initializations'].append({
                        'wall_ms': (time.perf_counter_ns() - started) / 1e6,
                        'available': result is not None,
                        'nopython_signatures': [str(item) for item in getattr(result, 'nopython_signatures', ())]})
                return result

            module.SearchGraph.route, module.kernel = graph_route, initialize_kernel

        def measured(*args, **kwargs):
            wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
            try:
                return original(*args, **kwargs)
            finally:
                self.route_wall.append((time.perf_counter_ns() - wall) / 1e6)
                self.route_cpu.append((time.thread_time_ns() - cpu) / 1e6)

        Navigator.route = measured
        try:
            yield
        finally:
            Navigator.route = original
            if module is not None:
                module.SearchGraph.route, module.kernel = original_graph_route, original_kernel
                self.backend['unavailable'] = bool(getattr(module, '_unavailable', False))
                self.backend['nopython_signatures'] = [str(item) for item in getattr(
                    getattr(module, '_kernel', None), 'nopython_signatures', ())]

    def step(self, policy, ctx):
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            return list(policy.step(ctx))
        finally:
            self.decision_wall.append((time.perf_counter_ns() - wall) / 1e6)
            self.decision_cpu.append((time.thread_time_ns() - cpu) / 1e6)

    def report(self):
        return {**{name: summary(getattr(self, name)) for name in
                ('decision_wall', 'decision_cpu', 'route_wall', 'route_cpu')},
                'backend': self.backend,
                'first_decision_wall_ms': self.decision_wall[0] if self.decision_wall else None,
                'first_route_wall_ms': self.route_wall[0] if self.route_wall else None}


def simulate(fixture_path, frames, capture):
    fixture = json.loads(fixture_path.read_text())
    metadata_path = fixture_path.with_name('checkpoint.json')
    checkpoint = fixture_path.with_name('checkpoint.state')
    metadata = json.loads(metadata_path.read_text())
    checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if metadata.get('sha256') != checkpoint_sha256:
        raise ValueError('Fixture checkpoint failed its metadata SHA256 check')
    workload, trace = [], []
    timings = Timings()
    with tempfile.TemporaryDirectory(prefix='pokesim-decisions-') as temporary:
        settings = configure(fixture, Path(temporary))
        from importlib.metadata import version
        from pyboy import PyBoy
        from pokesim.policies.base import Action, PolicyContext
        from pokesim.ram import read_snapshot
        from pokesim.screen import W_OPTIONS
        if hashlib.sha1(Path(settings.rom_path).read_bytes()).hexdigest() != metadata['rom_sha1']:
            raise ValueError('Fixture ROM does not match its checkpoint')
        if metadata['pyboy_version'] != version('pyboy'):
            raise ValueError('Fixture checkpoint needs a different PyBoy version')
        policy = policy_start(fixture, metadata)
        pb = PyBoy(settings.rom_path, window='null', sound_emulated=False, ram_file=io.BytesIO(bytes(32768)))
        pb.set_emulation_speed(0)
        start_frame = metadata.get('frame', 0)
        frame = start_frame
        stop_frame = start_frame + frames
        last_pos = None
        stuck_frame = frame
        action_count = 0
        try:
            with checkpoint.open('rb') as stream:
                pb.load_state(stream)
            with timings.routes():
                while frame < stop_frame:
                    snap = read_snapshot(pb.memory, frame)
                    pos = (snap.map, snap.x, snap.y)
                    if pos != last_pos or snap.in_battle or not snap.started:
                        stuck_frame = frame
                        last_pos = pos
                    # Decision time comes only from emulated frames, never CPU speed.
                    ctx = PolicyContext(snap, (frame - stuck_frame) / 60, frame / 60, pb.memory)
                    memory = bytes(pb.memory[0:65536]) if capture else None
                    routes_before = len(timings.route_wall)
                    actions = timings.step(policy, ctx)
                    row = {'frame': frame, 'snapshot': digest(snap.to_dict()),
                           'actions': [asdict(action) for action in actions],
                           'policy_state': digest(policy.state_dict()),
                           'route_calls': len(timings.route_wall) - routes_before}
                    trace.append(row)
                    if capture:
                        workload.append({'snapshot': snap, 'memory': memory,
                            'stuck_seconds': ctx.stuck_seconds, 'real_time': ctx.real_time, 'expected': row})
                    for action in actions or [Action(None, 0, 12)]:
                        if frame >= stop_frame:
                            break
                        if action.hold + action.gap <= 0:
                            raise ValueError('A policy action did not advance emulated time')
                        action_count += 1
                        if action.button is not None:
                            pb.button_press(action.button)
                        try:
                            for part in (action.hold, action.gap):
                                remaining = min(part, stop_frame - frame)
                                while remaining:
                                    chunk = min(remaining, 4)
                                    pb.tick(chunk, render=False)
                                    frame += chunk
                                    remaining -= chunk
                                    if frame // 30 != (frame - chunk) // 30:
                                        current = read_snapshot(pb.memory, frame)
                                        if current.started:
                                            if settings.fast_text:
                                                pb.memory[W_OPTIONS] = (pb.memory[W_OPTIONS] & ~7) | 1
                                            if not settings.battle_animations:
                                                pb.memory[W_OPTIONS] |= 128
                                if action.button is not None:
                                    pb.button_release(action.button)
                        finally:
                            if action.button is not None:
                                pb.button_release(action.button)
            final = read_snapshot(pb.memory, frame)
            state = io.BytesIO()
            pb.save_state(state)
            report = {'schema': 1, 'name': fixture.get('name'), 'frame_budget': frames,
                'start_frame': start_frame, 'end_frame': frame, 'actions_executed': action_count,
                'decisions': len(trace), 'checkpoint_sha256': checkpoint_sha256,
                'metadata_sha256': hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                'trace_sha256': digest(trace), 'trace': trace, 'final_snapshot_sha256': digest(final.to_dict()),
                'final_state_sha256': hashlib.sha256(state.getvalue()).hexdigest(), 'timings': timings.report(),
                'clock': 'emulated frames divided by 60',
                'scope': 'Policy decisions and ordinary input only. No runtime pacing, rendering, events or recovery guards.',
                'navigation_cache': cache_size(policy)}
            corpus = {'schema': 1, 'fixture': fixture, 'metadata': metadata,
                      'workload': workload, 'capture_report': report}
            return report, corpus
        finally:
            pb.stop(save=False)


def replay(path, repeats, warmups, decisions):
    runs = []
    warmup_runs = []
    pooled = Timings()
    fixture = json.loads(path.with_name('fixture.json').read_text())
    with tempfile.TemporaryDirectory(prefix='pokesim-decision-replay-') as temporary:
        configure(fixture, Path(temporary))
        with gzip.open(path, 'rb') as stream:
            corpus = pickle.load(stream)
        if corpus['schema'] != 1 or corpus['fixture'] != fixture:
            raise ValueError('Unsupported or mismatched workload metadata')
        workload = corpus['workload'][:decisions] if decisions else corpus['workload']
        from pokesim.policies.base import PolicyContext
        for trial in range(warmups + repeats):
            policy = policy_start(corpus['fixture'], corpus['metadata'])
            timings = Timings()
            with timings.routes():
                for number, record in enumerate(workload):
                    # Restore each original input. Policy and RNG evolve sequentially.
                    memory = bytearray(record['memory'])
                    ctx = PolicyContext(record['snapshot'], record['stuck_seconds'], record['real_time'], memory)
                    before = len(timings.route_wall)
                    actions = timings.step(policy, ctx)
                    expected = record['expected']
                    actual = {'actions': [asdict(action) for action in actions],
                              'policy_state': digest(policy.state_dict()),
                              'route_calls': len(timings.route_wall) - before}
                    if any(actual[key] != expected[key] for key in actual):
                        raise ValueError(f'Decision trace differs at decision {number}, frame {ctx.snapshot.frame}')
                    if bytes(memory) != record['memory']:
                        raise ValueError(f'Policy modified the captured RAM at decision {number}')
            if trial >= warmups:
                runs.append({**timings.report(), 'navigation_cache': cache_size(policy)})
                for name in ('decision_wall', 'decision_cpu', 'route_wall', 'route_cpu'):
                    getattr(pooled, name).extend(getattr(timings, name))
            else:
                warmup_runs.append({**timings.report(), 'navigation_cache': cache_size(policy)})
    return {'schema': 1, 'mode': 'decision-only', 'workload_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'decisions_per_run': len(workload), 'repeats': repeats, 'warmups': warmups,
            'trace_equivalent': True, 'runs': runs, 'warmup_runs': warmup_runs,
            'aggregate': {key: value for key, value in pooled.report().items() if key in
                          ('decision_wall', 'decision_cpu', 'route_wall', 'route_cpu')},
            'mean_run_decision_total_ms': statistics.mean(run['decision_wall']['total_ms'] for run in runs),
            'mean_run_route_total_ms': statistics.mean(run['route_wall']['total_ms'] for run in runs)}


def startup(fixture_path):
    fixture = json.loads(fixture_path.read_text())
    with tempfile.TemporaryDirectory(prefix='pokesim-compiled-startup-') as temporary:
        configure(fixture, Path(temporary))
        imported = time.perf_counter_ns()
        module = importlib.import_module('pokesim.policies.navigation_numba')
        import_ms = (time.perf_counter_ns() - imported) / 1e6
        started, cpu = time.perf_counter_ns(), time.thread_time_ns()
        run = module.kernel()
        return {'schema': 1, 'mode': 'kernel-startup', 'module_import_ms': import_ms,
                'kernel_initialize_wall_ms': (time.perf_counter_ns() - started) / 1e6,
                'kernel_initialize_cpu_ms': (time.thread_time_ns() - cpu) / 1e6,
                'available': run is not None,
                'nopython_signatures': [str(item) for item in getattr(run, 'nopython_signatures', ())],
                'scope': 'Fresh-process source import and explicit kernel initialization, excluding interpreter startup and game simulation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT, help='Checkout or exported source to import')
    sub = parser.add_subparsers(dest='mode', required=True)
    for mode in ('capture', 'trace'):
        command = sub.add_parser(mode)
        command.add_argument('fixture', type=Path)
        command.add_argument('--frames', type=int, default=12000)
        command.add_argument('--output', type=Path, required=True, help='New private directory outside the checkout')
        if mode == 'trace':
            command.add_argument('--compare', type=Path, required=True, help='Baseline capture result.json')
    command = sub.add_parser('startup')
    command.add_argument('fixture', type=Path)
    command.add_argument('--output', type=Path, required=True)
    command = sub.add_parser('replay')
    command.add_argument('workload', type=Path)
    command.add_argument('--trust-local-workload', action='store_true', required=True)
    command.add_argument('--decisions', type=int, default=0, help='Fixed input prefix, zero replays the whole corpus')
    command.add_argument('--repeats', type=int, default=3)
    command.add_argument('--warmups', type=int, default=1)
    command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    sys.path.insert(0, str(source))
    output = args.output.resolve()
    if output.is_relative_to(ROOT) or output.is_relative_to(source):
        parser.error('Private benchmark output must be outside the source checkout')
    if output.exists():
        parser.error('Choose a new output directory')
    output.mkdir(parents=True, mode=0o700)
    source_before = source_info(source)
    cache_before = numba_cache_state()
    if args.mode == 'replay':
        if args.repeats < 1 or args.warmups < 0 or args.decisions < 0:
            parser.error('Use positive repeats and nonnegative warmups')
        # These files contain Python objects. Never load workloads from another party.
        report = replay(args.workload, args.repeats, args.warmups, args.decisions)
    elif args.mode == 'startup':
        report = startup(args.fixture.resolve())
    else:
        if args.frames < 1:
            parser.error('Use a positive frame budget')
        report, corpus = simulate(args.fixture.resolve(), args.frames, args.mode == 'capture')
        if args.mode == 'capture':
            (output / 'fixture.json').write_text(json.dumps(corpus['fixture']) + '\n')
            with gzip.open(output / 'workload.pickle.gz', 'wb') as stream:
                pickle.dump(corpus, stream, protocol=5)
        else:
            baseline = json.loads(args.compare.read_text())
            compared = ('frame_budget', 'start_frame', 'end_frame', 'actions_executed', 'decisions',
                        'checkpoint_sha256', 'metadata_sha256', 'trace_sha256',
                        'final_snapshot_sha256', 'final_state_sha256')
            differences = {key: {'baseline': baseline[key], 'candidate': report[key]} for key in compared
                           if baseline[key] != report[key]}
            report['trace_equivalent'] = not differences
            report['differences'] = differences
    report['dependencies'] = dependency_versions()
    report['numba_cache_before'] = cache_before
    report['numba_cache_after'] = numba_cache_state()
    report['source'] = source_before
    report['source_unchanged'] = source_before == source_info(source)
    report['peak_rss_mib'] = peak_rss_mib()
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'trace'}))
    if not report['source_unchanged']:
        raise SystemExit('Production source changed during the benchmark')
    if report.get('trace_equivalent') is False:
        raise SystemExit('Fixed-frame gameplay trace changed')


if __name__ == '__main__':
    main()
