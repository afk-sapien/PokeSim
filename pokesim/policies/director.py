"""Persist postgame priorities and outcomes across expeditions and restarts."""
from copy import deepcopy


def category(project):
    method = project['method']
    if method == 'evolve':
        return 'evolution'
    if method == 'train':
        return 'training'
    if method in ('trainer', 'explore'):
        return 'exploration'
    if method in ('rematch', 'rod'):
        return 'supplies'
    return 'collection'


class AdventureDirector:
    def __init__(self):
        self.recent = []
        self.outcomes = []
        self.failures = {}
        self.completed = {}

    def state_dict(self):
        return deepcopy({key: getattr(self, key) for key in
                         ('recent', 'outcomes', 'failures', 'completed')})

    def load(self, data):
        self.recent = list(data.get('recent', []))[-8:]
        self.outcomes = deepcopy(data.get('outcomes', []))[-24:]
        self.failures = dict(list(data.get('failures', {}).items())[-128:])
        self.completed = dict(data.get('completed', {}))

    def select(self, candidates, rng, urgent=False):
        groups = {}
        for weight, project in candidates:
            groups.setdefault(category(project), []).append((weight, project))
        if urgent and 'supplies' in groups:
            chosen = 'supplies'
        else:
            kinds = list(groups)
            recent_kinds = [entry['category'] for entry in self.recent]
            if len(kinds) > 1 and len(recent_kinds) >= 2 and recent_kinds[-1] == recent_kinds[-2]:
                kinds = [kind for kind in kinds if kind != recent_kinds[-1]]
            priorities = {'collection': 5, 'evolution': 4, 'training': 2, 'exploration': 1, 'supplies': 1}
            weights = [priorities[kind] / (1 + recent_kinds.count(kind)) for kind in kinds]
            chosen = rng.choices(kinds, weights=weights)[0]
        rows = groups[chosen]
        recent_keys = [entry['key'] for entry in self.recent]
        weights = [weight / (1 + 4 * recent_keys.count(project['key'])) for weight, project in rows]
        project = rng.choices([project for weight, project in rows], weights=weights)[0]
        self.recent = (self.recent + [{'category': chosen, 'key': project['key']}])[-8:]
        return project

    def finish(self, project, elapsed, success, reason, progressed=False):
        key = project.get('key', project['method'])
        kind = category(project)
        if success or progressed:
            self.failures.pop(key, None)
            if success:
                self.completed[kind] = self.completed.get(kind, 0) + 1
            retry = 0 if success else elapsed + 60000
        else:
            count = min(4, self.failures.pop(key, 0) + 1)
            self.failures[key] = count
            self.failures = dict(list(self.failures.items())[-128:])
            retry = elapsed + 60000 * 2 ** (count - 1)
        self.outcomes = (self.outcomes + [{
            'key': key, 'category': kind, 'status': 'completed' if success else 'advanced' if progressed else 'deferred',
            'reason': reason, 'elapsed': elapsed, 'retry_at': retry,
            'target': project.get('target_level', project.get('species')),
            'gains': deepcopy(project.get('gains', {})),
        }])[-24:]
        return retry
