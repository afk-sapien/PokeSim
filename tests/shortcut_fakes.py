"""Record the Core shortcuts a policy starts, without running them on synthetic memory."""
from types import SimpleNamespace

from pokesim.policies.base import Action
from pokesim.shortcuts import ShortcutRunner

PRESS = Action('a', 8, 36)


class Recorder:
    """Replace ``runner.start`` so a test sees each machine and can finish it by hand."""

    def __init__(self, runner, refuse=()):
        self.runner = runner
        self.started = []
        self.refuse = set(refuse)
        runner.start = self.start

    @classmethod
    def on(cls, policy, refuse=()):
        if getattr(policy, 'mem', None) is None:
            policy.mem = bytearray(65536)
        return cls(policy.shortcut, refuse)

    def start(self, machine, key, frame, memory, ui=None, purpose='', on_done=None):
        if self.runner.blocked(key, frame):
            return None
        self.started.append(machine)
        runner = self.runner
        runner.machine, runner.key, runner.purpose, runner.on_done = machine, key, purpose, on_done
        if machine.kind in self.refuse:
            self.finish(False, 'refused', frame)
            return None
        return [PRESS]

    @property
    def last(self):
        return self.started[-1] if self.started else None

    def kinds(self):
        return [machine.kind for machine in self.started]

    def finish(self, completed=True, outcome='done', frame=0):
        runner = self.runner
        machine, callback = runner.machine, runner.on_done
        runner.cancel()
        result = SimpleNamespace(outcome=outcome, completed=completed, settled=True, details={})
        if not completed:
            runner.failures[runner.key] = frame + 3600
        if callback is not None:
            callback(result, machine)


def record_all(monkeypatch):
    """Record shortcuts on every runner, including ones built inside the code under test."""
    recorders = {}

    def start(runner, *args, **kwargs):
        if id(runner) not in recorders:
            recorders[id(runner)] = Recorder(runner)
        return recorders[id(runner)].start(*args, **kwargs)

    monkeypatch.setattr(ShortcutRunner, 'start', start)
    return lambda runner: recorders[id(runner)]


class Scripted:
    """A stand-in machine that returns scripted buttons, waits and a final ``Done``."""
    inputs = 1

    def __init__(self, kind, results):
        self.kind, self.results = kind, list(results)

    def step(self, memory, ui):
        return self.results.pop(0)
