"""Persist postgame priorities and outcomes across expeditions and restarts."""
from copy import deepcopy

from ..planning.monitor import SPENT, STAND_DOWNS, STOOD_DOWN, Backoff, Monitor


def category(project):
    if project.get('legendary'):
        return 'legendary'
    method = project['method']
    if method == 'marathon':
        return 'recreation'
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


# A project that stood down waits a minute of play, 60000 elapsed frames, doubled for each stand-down
# in a row and three times at most. A project that made some progress waits the minute only.
RETRY = Backoff(60000, doublings=3)
# Keys the monitor remembers, oldest dropped first.
REMEMBERED = 128


class AdventureDirector:
    def __init__(self):
        self.recent = []
        self.outcomes = []
        self.completed = {}
        self.progress = {}
        self.monitor = Monitor(self.progress, RETRY)

    @property
    def failures(self):
        """Stand-downs in a row per project key."""
        return self.monitor._table(STAND_DOWNS)

    def state_dict(self):
        saved = deepcopy({key: getattr(self, key) for key in ('recent', 'outcomes', 'completed')})
        saved['progress'] = {name: dict(table) for name, table in self.progress.items() if table}
        return saved

    def load(self, data):
        self.recent = list(data.get('recent', []))[-8:]
        self.outcomes = deepcopy(data.get('outcomes', []))[-24:]
        self.completed = dict(data.get('completed', {}))
        progress = data.get('progress')
        if not isinstance(progress, dict):
            # An older save kept only the failure counts. Its retry times are in the collection.
            progress = {STAND_DOWNS: dict(data.get('failures', {}))}
        self.progress = deepcopy(progress)
        self.monitor = Monitor(self.progress, RETRY)
        self.trim()

    def trim(self):
        for name in (STOOD_DOWN, STAND_DOWNS, SPENT):
            table = self.monitor._table(name)
            for key in list(table)[:-REMEMBERED]:
                del table[key]

    def waiting(self, key, elapsed):
        """Whether the project ``key`` stood down and its wait has not run out at ``elapsed``."""
        return self.monitor.standing_down(key, elapsed)

    def forget_expired(self, elapsed):
        """Drop retry times that have passed. The counts stay, so the next stand-down still doubles."""
        stood = self.monitor._table(STOOD_DOWN)
        for key in [key for key in stood if not self.waiting(key, elapsed)]:
            del stood[key]

    def resume(self, key, deadline, elapsed):
        """Carry an older save's retry time for ``key`` over to the monitor."""
        if deadline > elapsed:
            self.monitor._table(STOOD_DOWN)[key] = deadline - RETRY.wait(self.failures.get(key, 0))

    def select(self, candidates, rng, urgent=False):
        # Completing the Pokédex comes first, not merely more often. Weighting it let DV hunts,
        # rematches and the variety rule take two turns in three, and both adventures reached 1,500
        # game hours with Dragonite one evolution away.
        if not (urgent and any(category(p) == 'supplies' for _, p in candidates)):
            candidates = [(w, p) for w, p in candidates if new_entry(p)] or candidates
            # A rematch is the fallback once nothing else is left. The variety rule kept handing it
            # every third turn, and Blue spent 46% of its frames rematching with money at the cap.
            candidates = [(w, p) for w, p in candidates if p['method'] != 'rematch'] or candidates
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
                          'training': 3 if discovering else 12, 'exploration': 1, 'supplies': 1, 'recreation': 1}
            if groups.get('collection') and all(p.get('repeat') and not p.get('needed_capture') for _, p in groups['collection']):
                priorities['collection'] = 8 if any(p.get('dv_hunt') for _, p in groups['collection']) else 1
            # Training used to be exempt from this decay, so once it started it kept winning.
            # Now a finished ten level step lowers its odds and something else gets a turn.
            weights = [priorities[kind] / (1 + recent_kinds.count(kind)) for kind in kinds]
            chosen = rng.choices(kinds, weights=weights)[0]
        rows = groups[chosen]
        if chosen in ('training', 'evolution') and any(p.get('perfect_partner') for _, p in rows):
            rows = [(weight, p) for weight, p in rows if p.get('perfect_partner')]
        if chosen == 'training':
            if any('investment_priority' in p for _, p in rows):
                highest = max(p.get('investment_priority', 1) for _, p in rows)
                rows = [(weight, p) for weight, p in rows if p.get('investment_priority', 1) == highest]
                if any(p.get('mastery_needed') for _, p in rows):
                    rows = [(weight, p) for weight, p in rows if p.get('mastery_needed')]
            else:
                # Preserve selection for legacy candidates without individual assessment.
                if not any(p.get('perfect_partner') for _, p in rows) and any(p.get('mastery_needed') for _, p in rows):
                    rows = [(weight, p) for weight, p in rows if p.get('mastery_needed')]
                highest = max(p.get('initial_level', 0) for _, p in rows)
                rows = [(weight, p) for weight, p in rows if p.get('initial_level', 0) >= highest - 5]
        if chosen == 'collection' and all(p.get('dv_hunt') for _, p in rows):
            if any(p.get('quality_search_needed') for _, p in rows):
                rows = [(weight, p) for weight, p in rows if p.get('quality_search_needed')]
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
        if success:
            self.completed[kind] = self.completed.get(kind, 0) + 1
        if success or progressed and new_entry(project):
            self.monitor.clear(key)
            retry = 0
        else:
            # Move the key to the newest end so trimming drops the projects left alone longest.
            count = self.failures.pop(key, None)
            if count is not None:
                self.failures[key] = count
            retry = self.monitor.stand_down(key, elapsed, progressed=progressed)
            if key in self.failures:
                self.failures[key] = min(self.failures[key], RETRY.doublings + 1)
            self.trim()
        self.outcomes = (self.outcomes + [{
            'key': key, 'category': kind, 'status': 'completed' if success else 'advanced' if progressed else 'deferred',
            'reason': reason, 'elapsed': elapsed, 'retry_at': retry,
            'target': project.get('target_level', project.get('species')),
            'gains': deepcopy(project.get('gains', {})),
            'timing': {key: project['training_session'][key] for key in ('preparation_frames', 'active_frames')}
                      if project.get('training_session') else None,
        }])[-24:]
        return retry
