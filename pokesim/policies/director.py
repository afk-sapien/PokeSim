"""Persist postgame priorities and outcomes across expeditions and restarts."""
from copy import deepcopy


def category(project):
    if project.get('legendary'):
        return 'legendary'
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


def new_entry(project):
    """True when finishing the project registers a species the Pokédex does not have yet."""
    kind = category(project)
    if kind == 'legendary':
        return True
    if kind == 'evolution':
        return not project.get('upgrade_evolution')
    return kind == 'collection' and (not project.get('repeat') or bool(project.get('needed_capture')))


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
        # Completing the Pokédex comes first, not merely more often. Weighting it let DV hunts,
        # rematches and the variety rule take two turns in three, and both adventures reached 1,500
        # game hours with Dragonite one evolution away.
        if not (urgent and any(category(p) == 'supplies' for _, p in candidates)):
            candidates = [(w, p) for w, p in candidates if new_entry(p)] or candidates
        groups = {}
        for weight, project in candidates:
            groups.setdefault(category(project), []).append((weight, project))
        if urgent and 'supplies' in groups:
            chosen = 'supplies'
        else:
            kinds = list(groups)
            recent_kinds = [entry['category'] for entry in self.recent]
            # A new Pokédex entry comes before a level milestone. Training to level 100 used to weigh 12
            # whatever else was on offer, and wild Pokémon stop near level 45, so two adventures spent
            # most of 400 game hours in Pokémon Mansion while 27 entries they could have had went missing.
            discovering = any(new_entry(p) for _, p in candidates)
            limit = 2
            if len(kinds) > 1 and len(recent_kinds) >= limit and len(set(recent_kinds[-limit:])) == 1:
                kinds = [kind for kind in kinds if kind != recent_kinds[-1]]
            priorities = {'legendary': 8, 'collection': 8 if discovering else 5, 'evolution': 8 if discovering else 4,
                          'training': 3 if discovering else 12, 'exploration': 1, 'supplies': 1}
            if groups.get('collection') and all(p.get('repeat') and not p.get('needed_capture') for _, p in groups['collection']):
                priorities['collection'] = 8 if any(p.get('dv_hunt') for _, p in groups['collection']) else 1
            # Training used to be exempt from this decay, so once it started it kept winning.
            # Now a finished ten level step lowers its odds and something else gets a turn.
            weights = [priorities[kind] / (1 + recent_kinds.count(kind)) for kind in kinds]
            chosen = rng.choices(kinds, weights=weights)[0]
        rows = groups[chosen]
        if chosen in ('training', 'evolution') and any(p.get('perfect_partner') for _, p in rows):
            rows = [(weight, p) for weight, p in rows if p.get('perfect_partner')]
        elif chosen == 'training' and any(p.get('mastery_needed') for _, p in rows):
            rows = [(weight, p) for weight, p in rows if p.get('mastery_needed')]
        if chosen == 'training':
            # Finish the closest partners before spreading experience to lower levels.
            highest = max(p.get('initial_level', 0) for _, p in rows)
            rows = [(weight, p) for weight, p in rows if p.get('initial_level', 0) >= highest - 5]
        if chosen == 'collection' and all(p.get('dv_hunt') for _, p in rows):
            # Rotate through reachable species, then choose a route for that species.
            # Many encounter locations must not buy a species more turns.
            oldest = min(p.get('last_hunt', -1) for _, p in rows)
            rows = [(weight, p) for weight, p in rows if p.get('last_hunt', -1) == oldest]
            species = list(dict.fromkeys(p['species'] for _, p in rows))
            priorities = [max(p.get('capture_priority', 1) for _, p in rows if p['species'] == sid) for sid in species]
            target = rng.choices(species, weights=priorities)[0]
            rows = [(weight, p) for weight, p in rows if p['species'] == target]
        recent_keys = [entry['key'] for entry in self.recent]
        weights = [weight / (1 if chosen == 'training' else 1 + 4 * recent_keys.count(project['key'])) for weight, project in rows]
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
            retry = 0 if success or new_entry(project) else elapsed + 60000
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
            'timing': {key: project['training_session'][key] for key in ('preparation_frames', 'active_frames')}
                      if project.get('training_session') else None,
        }])[-24:]
        return retry
