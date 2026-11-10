"""Play one ladder rung at any commit with a trace recorder attached.

The replay tool runs this file with the commit's own environment, from the commit's checkout:

    <env>/bin/python shim.py TRACE_PY OUT FIELDS_JSON STAGE_LADDER -- gate-rung ARGS...

``TRACE_PY`` is the trace module of the checkout that runs the tool. It is loaded by path, so a
commit whose pokecore has no trace module, or an older one, still writes the current format.
``FIELDS_JSON`` goes into the segment header. The shim runs the commit's ``STAGE_LADDER`` as
the gate does, and writes ``OUT/trace/0001.jsonl.gz`` with its start state, and ``OUT/shim.json``.

A recorder attaches to every Core emulator built while ``HeadlessRun.__init__`` runs, so hooks
the run registers there are known. Once the run is built, the recorder of ``run.pb`` begins the
segment and the others detach. Each policy step logs a decide record with its goal key and
position before the step's inputs, and each goal reseed logs an input record. Only the standard
library is imported before the commit's code, since Gen I modules read their tables at import.
"""
import importlib.util
import json
import os
import runpy
import sys
import traceback
from pathlib import Path

SEGMENT = '0001.jsonl.gz'


class State:
    def __init__(self, trace, out, fields):
        self.trace = trace
        self.out = out
        self.fields = fields
        self.building = None  # Recorders built while a HeadlessRun.__init__ runs, else None.
        self.recorder = None
        self.runs = 0
        self.decides = 0
        self.inputs = 0


STATE = None


def _wrapped(owner, name):
    return getattr(getattr(owner, name, None), '_replay_wrapped', False)


def _mark(function):
    function._replay_wrapped = True
    return function


def wrap_emulator(cls):
    """Attach a recorder to each Core emulator built while a run is being built."""
    if _wrapped(cls, '__init__'):
        return
    original = cls.__init__

    @_mark
    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if STATE.building is not None:
            STATE.building.append(STATE.trace.Recorder(self))

    cls.__init__ = __init__


def _keep(run, built):
    STATE.runs += 1
    mine = None
    for recorder in built:
        if mine is None and STATE.recorder is None and recorder.emulator is run.pb:
            mine = recorder
        else:
            recorder.detach()
    if mine is not None:
        STATE.recorder = mine
        segment = STATE.trace.Segment(STATE.out / 'trace' / SEGMENT, keep_start=True)
        # The run counts its own frames from the save's, and run files name frames that way.
        mine.begin(segment, **STATE.fields, run_frame=getattr(run, 'frame', None))


def _follow_policy(run):
    """Log a decide record after each policy step, before the run presses what it chose."""
    recorder = STATE.recorder
    policy = getattr(run, 'policy', None)
    if recorder is None or policy is None or run.pb is not recorder.emulator or _wrapped(policy, 'step'):
        return
    step = policy.step

    @_mark
    def traced(*args, **kwargs):
        result = step(*args, **kwargs)
        snapshot = getattr(args[0], 'snapshot', args[0]) if args else None
        goal = getattr(policy, 'goal', None)
        key = None if goal is None else getattr(goal, 'key', None)
        if goal is not None and not isinstance(key, str):
            key = type(goal).__name__
        recorder.decide(key, getattr(snapshot, 'map', None), getattr(snapshot, 'x', None),
                        getattr(snapshot, 'y', None))
        STATE.decides += 1
        return result

    policy.step = traced


def wrap_run(module):
    cls = getattr(module, 'HeadlessRun', None)
    if cls is None or _wrapped(cls, '__init__'):
        return
    init, step = cls.__init__, cls.step

    @_mark
    def __init__(self, *args, **kwargs):
        outer, STATE.building = STATE.building, []
        try:
            init(self, *args, **kwargs)
        finally:
            built, STATE.building = STATE.building, outer
        _keep(self, built)

    @_mark
    def traced_step(self, *args, **kwargs):
        _follow_policy(self)
        return step(self, *args, **kwargs)

    cls.__init__ = __init__
    cls.step = traced_step


def wrap_seeds(module):
    """Log each goal reseed as an input record, before the writes it makes."""
    cls = module.__dict__.get('GoalSeeds')
    if cls is None or getattr(cls, '__module__', None) != module.__name__ or _wrapped(cls, 'start'):
        return
    start = cls.start

    @_mark
    def traced_start(self, run, key, *args, **kwargs):
        recorder = STATE.recorder
        if recorder is not None and getattr(run, 'pb', None) is recorder.emulator:
            occurrence = getattr(self, 'starts', {}).get(key, 0)
            payload = {'key': key, 'occurrence': occurrence}
            seed = getattr(self, 'seed', None)
            if seed is not None:
                payload['digest'] = seed(key, occurrence).hex()
            recorder.input('goal_seed', payload)
            STATE.inputs += 1
        return start(self, run, key, *args, **kwargs)

    cls.start = traced_start


AFTER = {'pokesim.headless': wrap_run, 'pokesim.gen2.headless': wrap_run,
         'pokesim.replay.rung': wrap_seeds, 'tools.replay_audit': wrap_seeds}


class Finder:
    """Patch a module named in AFTER as soon as its code has run, before anything uses it."""

    def find_spec(self, name, path=None, target=None):
        after = AFTER.get(name)
        if after is None:
            return None
        for finder in sys.meta_path:
            find = getattr(finder, 'find_spec', None)
            if finder is self or find is None:
                continue
            spec = find(name, path, target)
            if spec is not None:
                break
        else:
            return None
        loader = spec.loader
        exec_module = getattr(loader, 'exec_module', None)
        if exec_module is None:
            return spec

        def run_then_patch(module):
            exec_module(module)
            after(module)

        loader.exec_module = run_then_patch
        return spec


def _load_trace(path):
    spec = importlib.util.spec_from_file_location('_replay_trace', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv):
    global STATE
    if len(argv) < 6 or argv[5] != '--':
        print('usage: shim.py TRACE_PY OUT FIELDS_JSON STAGE_LADDER -- ARGS...', file=sys.stderr)
        return 2
    trace_py, out, fields, stage = argv[1:5]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    STATE = State(_load_trace(trace_py), out, json.loads(fields))
    sys.meta_path.insert(0, Finder())
    import pokecore.emulator
    wrap_emulator(pokecore.emulator.Emulator)
    sys.argv = [stage, *argv[6:]]
    code, error = 0, None
    try:
        runpy.run_path(stage, run_name='__main__')
    except SystemExit as exit:
        if isinstance(exit.code, int) or exit.code is None:
            code = exit.code or 0
        else:
            code, error = 1, str(exit.code)
    except BaseException:  # Keep the report. The traceback goes to the log.
        code, error = 1, traceback.format_exc()
    recorder = STATE.recorder
    report = {'code': code, 'attached': recorder is not None, 'runs': STATE.runs, 'decides': STATE.decides,
              'inputs': STATE.inputs}
    if recorder is not None:
        report.update(head=recorder.head, records=recorder.index, frames=recorder.frames,
                      segment=f'trace/{SEGMENT}')
        recorder.detach()
    if error:
        print(error, file=sys.stderr)
        report['error'] = error.strip().splitlines()[-1]
    partial = out / f'.shim.{os.getpid()}.json'
    partial.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    os.replace(partial, out / 'shim.json')
    if recorder is None:
        print('no run attached a recorder', file=sys.stderr)
        return 2
    return code


if __name__ == '__main__':
    # Drop this file's folder, so its neighbours never shadow the commit's modules.
    if sys.path and Path(sys.path[0] or '.').resolve() == Path(__file__).resolve().parent:
        del sys.path[0]
    raise SystemExit(main(sys.argv))
