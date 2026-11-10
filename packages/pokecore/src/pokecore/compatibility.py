"""Offline compatibility traces and isolated performance measurements.

Manifests are trusted local configuration. Private files are never copied into
the package. Baseline capture is explicit and refuses to overwrite a file.
"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time


CATEGORIES = ('movement', 'menus', 'battles', 'storage', 'save_load', 'audio', 'trading')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(emulator):
    return {'hardware': digest(emulator.save()), 'screen': digest(bytes(emulator.screen.raw_buffer)),
            'audio': digest(emulator.audio_samples()), 'wram': digest(emulator.memory.read_bytes(0xc000, 0xe000))}


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f'{name} must be a positive integer')
    return value


def _assert_memory(emulator, expected):
    for row in expected:
        start = row['address']
        data = bytes.fromhex(row['hex'])
        if emulator.memory.read_bytes(start, start + len(data)) != data:
            raise AssertionError(f'Fixture assertion failed at {start:#06x}')


def trace(case, base):
    from .emulator import Emulator, demo_rom
    from .emulator_state import runtime_provenance
    rom = demo_rom().read_bytes() if case['rom'] == 'demo' else (base / case['rom']).read_bytes()
    state = (base / case['state']).read_bytes() if case.get('state') else None
    steps = case['steps']
    interval = _positive(case.get('check_interval', 60), 'check_interval')
    frames = sum(_positive(step[1], 'step frames') for step in steps)
    if not steps or frames > 1_000_000:
        raise ValueError('Trace must contain between 1 and 1000000 frames')
    restores = case.get('restore_at', [])
    if any(type(offset) is not int or not 1 <= offset <= frames for offset in restores) or len(set(restores)) != len(restores):
        raise ValueError('Restore offsets must be unique frame positions within the trace')
    for buttons, _ in steps:
        if not isinstance(buttons, list) or len(set(buttons)) != len(buttons):
            raise ValueError('Trace buttons must be distinct')
        if any(button not in ('a', 'b', 'start', 'select', 'up', 'down', 'left', 'right') for button in buttons):
            raise ValueError('Unknown trace button')
    render, sound = case.get('render', False), case.get('sound', False)
    if type(render) is not bool or type(sound) is not bool:
        raise ValueError('Render and sound flags must be booleans')
    if case.get('rom_sha256', digest(rom)) != digest(rom):
        raise ValueError('Private fixture ROM checksum mismatch')
    with Emulator(io.BytesIO(rom)) as emulator:
        if state is not None:
            emulator.load(state)
        else:
            emulator.tick(_positive(case.get('warmup_frames', 90), 'warmup_frames'))
        _assert_memory(emulator, case.get('initial_memory', []))
        points = [{'offset': 0, **fingerprint(emulator)}]
        start = time.perf_counter()
        advanced = 0
        for buttons, count in steps:
            for button in ('a', 'b', 'start', 'select', 'up', 'down', 'left', 'right'):
                emulator.release(button)
            for button in buttons:
                emulator.press(button)
            for _ in range(count):
                emulator.tick(1, render=render, sound=sound)
                advanced += 1
                if advanced in case.get('restore_at', []):
                    checkpoint = emulator.checkpoint()
                    emulator.tick(1, render=render, sound=sound)
                    emulator.restore_checkpoint(checkpoint)
                if advanced % interval == 0 or advanced == frames:
                    points.append({'offset': advanced, **fingerprint(emulator)})
        seconds = time.perf_counter() - start
        _assert_memory(emulator, case.get('final_memory', []))
        return {'status': 'passed', 'fingerprint': points, 'frames': frames, 'seconds': seconds,
                'frames_per_second': frames / seconds, 'emulator': runtime_provenance(),
                'rom_sha256': digest(rom), 'state_sha256': digest(state) if state is not None else None}


def contracts(case, base):
    import pytest
    class Results:
        def __init__(self):
            self.passed = 0
            self.skipped = 0
            self.failed = 0

        def pytest_runtest_logreport(self, report):
            self.passed += report.when == 'call' and report.passed
            self.skipped += report.skipped
            self.failed += report.failed
    if case.get('cwd'):
        os.chdir(base / case['cwd'])
    results = Results()
    targets = []
    for node in case['tests']:
        path, separator, selector = node.partition('::')
        targets.append(str((base / path).resolve()) + (separator + selector if separator else ''))
    buffer = io.StringIO()
    start = time.perf_counter()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        code = pytest.main(['-q', '-p', 'no:cacheprovider', *targets], plugins=[results])
    status = 'failed' if code or results.failed else ('missing' if results.skipped or not results.passed else 'passed')
    return {'status': status, 'seconds': time.perf_counter() - start,
            'fingerprint': {'passed': results.passed, 'skipped': results.skipped, 'failed': results.failed},
            'log': buffer.getvalue()[-12000:]}


def worker(manifest, index):
    path = Path(manifest).resolve()
    case = json.loads(path.read_text())['cases'][index]
    try:
        if case['kind'] == 'trace':
            row = trace(case, path.parent)
        elif case['kind'] == 'contracts':
            row = contracts(case, path.parent)
        else:
            raise ValueError('Unknown case kind')
    except FileNotFoundError as error:
        row = {'status': 'missing', 'error': str(error)}
    except Exception as error:
        row = {'status': 'failed', 'error': f'{type(error).__name__}: {error}'}
    row['peak_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == 'darwin' else 1024)
    print(json.dumps(row))


def compare_result(current, baseline, *, max_slowdown=None, max_memory_growth=None):
    failures = []
    if current.get('manifest_sha256') != baseline.get('manifest_sha256'):
        return ['Manifest differs from the baseline']
    before = {row['id']: row for row in baseline['cases']}
    for row in current['cases']:
        previous = before.get(row['id'])
        if previous is None or row['status'] != 'passed' or previous['status'] != 'passed':
            failures.append(f"{row['id']}: missing passing baseline or result")
            continue
        for key in ('rom_sha256', 'state_sha256', 'fingerprint'):
            if row.get(key) != previous.get(key):
                failure = f"{row['id']}: {key} changed"
                if key == 'fingerprint' and isinstance(row.get(key), list):
                    for old, new in zip(previous[key], row[key]):
                        if old != new:
                            failure += f" at checkpoint {new['offset']}"
                            break
                failures.append(failure)
        row['time_change_percent'] = 100 * (row['seconds'] / previous['seconds'] - 1)
        row['memory_change_percent'] = 100 * (row['peak_rss_mib'] / previous['peak_rss_mib'] - 1)
        if max_slowdown is not None and row['time_change_percent'] > max_slowdown:
            failures.append(f"{row['id']}: slowdown exceeds threshold")
        if max_memory_growth is not None and row['memory_change_percent'] > max_memory_growth:
            failures.append(f"{row['id']}: memory growth exceeds threshold")
    return failures


def run_suite(manifest, repeats=3, require_private=False):
    path = Path(manifest).resolve()
    specification = json.loads(path.read_text())
    if specification.get('format') != 1:
        raise ValueError('Unsupported suite format')
    _positive(repeats, 'repeats')
    ids = [case['id'] for case in specification['cases']]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Suite requires unique case IDs')
    result = {'format': 1, 'manifest_sha256': digest(path.read_bytes()), 'cases': [], 'coverage': {}}
    for index, case in enumerate(specification['cases']):
        if case['scope'] not in ('synthetic', 'private') or not set(case['categories']) <= set(CATEGORIES):
            raise ValueError('Invalid case scope or category')
        runs = []
        for _ in range(repeats):
            try:
                completed = subprocess.run([sys.executable, '-m', 'pokecore.compatibility',
                                            '--worker', str(path), str(index)],
                                           capture_output=True, text=True, timeout=case.get('timeout_seconds', 180))
                if completed.returncode:
                    raise RuntimeError(completed.stderr[-4000:])
                runs.append(json.loads(completed.stdout))
            except (subprocess.TimeoutExpired, ValueError, RuntimeError) as error:
                runs.append({'status': 'failed', 'error': str(error)})
        row = dict(runs[0], id=case['id'], scope=case['scope'], categories=case['categories'])
        row['runs'] = runs
        if any(run['status'] != 'passed' for run in runs):
            row['status'] = 'failed' if any(run['status'] == 'failed' for run in runs) else 'missing'
        elif any(run['fingerprint'] != runs[0]['fingerprint'] for run in runs):
            row.update(status='failed', error='Nondeterministic repetitions')
        else:
            row['seconds'] = statistics.median(run['seconds'] for run in runs)
            if row.get('frames'):
                row['frames_per_second'] = row['frames'] / row['seconds']
            row['peak_rss_mib'] = statistics.median(run['peak_rss_mib'] for run in runs)
        result['cases'].append(row)
    for category in CATEGORIES:
        result['coverage'][category] = {scope: [row['id'] for row in result['cases']
                                               if row['scope'] == scope and category in row['categories']
                                               and row['status'] == 'passed'] for scope in ('synthetic', 'private')}
    result['missing_categories'] = [category for category in (CATEGORIES if require_private else specification.get('required_categories', CATEGORIES))
                                    if not result['coverage'][category]['private'] and
                                    (require_private or not result['coverage'][category]['synthetic'])]
    result['status'] = ('passed' if not result['missing_categories'] and
                        all(row['status'] == 'passed' for row in result['cases']) else 'incomplete')
    return result


def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--worker':
        worker(sys.argv[2], int(sys.argv[3]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--capture', type=Path)
    group.add_argument('--baseline', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--require-private', action='store_true')
    parser.add_argument('--max-slowdown', type=float)
    parser.add_argument('--max-memory-growth', type=float)
    args = parser.parse_args()
    if args.output.exists() or (args.capture is not None and args.capture.exists()):
        parser.error('Output and capture paths must be new files')
    result = run_suite(args.manifest, args.repeats, args.require_private)
    result['failures'] = []
    if args.baseline is not None:
        result['failures'] = compare_result(result, json.loads(args.baseline.read_text()),
                                            max_slowdown=args.max_slowdown,
                                            max_memory_growth=args.max_memory_growth)
        if result['failures']:
            result['status'] = 'failed'
    data = json.dumps(result, indent=2) + '\n'
    with args.output.open('x') as stream:
        stream.write(data)
    if args.capture is not None and result['status'] == 'passed':
        with args.capture.open('x') as stream:
            stream.write(data)
    print(json.dumps({'status': result['status'], 'missing_categories': result['missing_categories'],
                      'failures': result['failures'], 'output': str(args.output)}))
    raise SystemExit(0 if result['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
