"""One record per goal: what the goal is, and what it has done since it started.

A goal's spec is what the offers draw built for it: its kind, its params and its key. Its run is the
record the save keeps, the spec's params beside everything written after the goal started. The kind's
rules name those run fields, and the split follows one rule: a field set before the start is a param,
and a field set after it is run state. A write to a param once the goal is under way raises, so the
split stays true.

``GoalRun`` is a dict, so the save shape does not change, and an older build loads a newer save. The
design is in docs/design/typed-goals.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class GoalSpec:
    """What a goal is. ``kind`` is the method, ``params`` the offers draw's fields and ``key`` the
    monitor key its stand-downs and spent frames are kept under."""
    kind: str
    params: Mapping
    key: str

    @classmethod
    def make(cls, kind, params, key):
        return cls(kind, MappingProxyType(dict(params)), key)

    def __reduce__(self):
        return GoalSpec.make, (self.kind, dict(self.params), self.key)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


@dataclass(frozen=True)
class Abandon:
    """A goal that cannot go on, with the reason the journal gives."""
    reason: str


class ParamWrite(TypeError):
    """A write to a goal's param after the goal started."""


class Rules:
    """A goal kind's rules. Each Gen I method has one subclass (policies/kinds.py), and so has each Gen II
    goal record (gen2/kinds.py)."""
    kind = ''
    # Fields written after the goal starts. Every other field is a param.
    run = frozenset()
    # Fields the spec keeps as its kind and key rather than as params. A Gen I project names its kind
    # in ``method`` and may carry its own ``key``.
    spec_fields = frozenset({'key', 'method'})

    def spec_kind(self, record):
        """The kind of the goal ``record``. A kind with no rules of its own goes by the record's method."""
        return self.kind or record['method']

    def spec_key(self, record):
        """The monitor key the goal ``record`` is kept under."""
        return record.get('key', self.spec_kind(record))

    # One rules object serves every goal of its kind, so a copied goal keeps it.
    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def _restore(spec, rules, record):
    run = GoalRun(record)
    run.spec, run.rules = spec, rules
    return run


class GoalRun(dict):
    """A goal under way: its spec's params, its key and method, and its run fields, as one flat dict."""
    __slots__ = ('spec', 'rules')

    @classmethod
    def start(cls, offer, rules):
        """A run of ``offer``, a dict the offers draw built. The run has its own copy of it."""
        return cls.from_dict(offer, rules)

    @classmethod
    def from_dict(cls, record, rules):
        """The run a save or an offer kept as ``record``. Its params are every field but the run fields
        and those the spec keeps as its kind and key."""
        params = {name: value for name, value in record.items()
                  if name not in rules.run and name not in rules.spec_fields}
        spec = GoalSpec.make(rules.spec_kind(record), params, rules.spec_key(record))
        return _restore(spec, rules, dict(record))

    def __reduce__(self):
        return _restore, (self.spec, self.rules, dict(self))

    def _writes(self, name):
        if name not in self.rules.run:
            raise ParamWrite(f'{name} is a param of the goal {self.spec.key}, so it was set before it started')

    def __setitem__(self, name, value):
        self._writes(name)
        super().__setitem__(name, value)

    def __delitem__(self, name):
        self._writes(name)
        super().__delitem__(name)

    def setdefault(self, name, default=None):
        if name not in self:
            self._writes(name)
        return super().setdefault(name, default)

    _missing = object()

    def pop(self, name, default=_missing):
        if name not in self:
            if default is GoalRun._missing:
                raise KeyError(name)
            return default
        self._writes(name)
        return super().pop(name)

    def update(self, *args, **fields):
        changes = dict(*args, **fields)
        for name in changes:
            self._writes(name)
        super().update(changes)

    def __ior__(self, other):
        self.update(other)
        return self

    def popitem(self):
        raise ParamWrite('a goal keeps its params while it runs')

    def clear(self):
        raise ParamWrite('a goal keeps its params while it runs')
