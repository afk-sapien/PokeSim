"""First achievements kept independently of journal retention and save rewinds."""
import time

from .milestones import status as goals_status
from .shiny import status as shiny_status

KEY = 'adventure-records-v1'
MILESTONES = (
    ('first_badge', 'First badge'), ('all_badges', 'All eight badges'),
    ('champion', 'First Champion victory'), ('pokedex', 'All 151 registered'),
    ('level100', 'First level 100'), ('shiny', 'First shiny acquired'),
    ('perfect', 'First perfect acquired'),
)


def status(store):
    value = store.get(KEY) or {}
    records = value.get('records', {})
    return {'started_at': value.get('started_at'), 'milestones': [
        {'key': key, 'label': label, **records.get(key, {}), 'achieved': key in records}
        for key, label in MILESTONES]}


class RecordTracker:
    def __init__(self, store):
        self.store = store
        self.previous = None
        self.value = store.get(KEY)
        if self.value is None:
            records = {}
            # Dates in legacy progress are observations, not proof of the first achievement time.
            thresholds = {'first_badge': ('badges', 1), 'all_badges': ('badges', 8),
                          'champion': ('league', 1), 'pokedex': ('owned', 151),
                          'level100': ('level100', 1), 'perfect': ('perfect', 1)}
            with store.lock:
                for key, (column, threshold) in thresholds.items():
                    row = store.db.execute(f'SELECT ts FROM progress WHERE {column} >= ? ORDER BY rowid LIMIT 1',
                                           (threshold,)).fetchone()
                    if row:
                        records[key] = {'at': row[0], 'seconds': None, 'source': 'first_recorded'}
                        event = store.db.execute('SELECT playtime FROM events WHERE ts=? ORDER BY id LIMIT 1', (row[0],)).fetchone()
                        if event:
                            try:
                                hours, minutes, seconds = map(int, event[0].split(':'))
                                if 0 <= hours < 255 and 0 <= minutes < 60 and 0 <= seconds < 60:
                                    records[key].update(seconds=hours * 3600 + minutes * 60 + seconds,
                                                        clock_source='cartridge')
                            except (ValueError, AttributeError):
                                pass
            self.value = {'records': records, 'baseline_pending': True, 'started_at': time.time()}
            store.set(KEY, self.value)

    def reset(self, *, now=None):
        self.value = {'records': {}, 'baseline_pending': False, 'started_at': now or time.time()}
        self.previous = None
        self.store.set(KEY, self.value)

    def observe(self, snapshot, clock=None, *, now=None):
        if not snapshot.valid or not snapshot.started or self.store.get('trade_hold'):
            self.previous = None
            return
        goals = goals_status(self.store)
        shiny = shiny_status(self.store)
        conditions = (bool(snapshot.badges), snapshot.badges == 255,
                      snapshot.hall_of_fame_count > 0, len(snapshot.owned) >= 151,
                      bool(goals['level_100']), bool(goals.get('shiny_species') or shiny['acquired']),
                      bool(goals['perfect_found']))
        if self.previous != conditions:
            self.previous = conditions
            return
        pending = self.value['baseline_pending']
        records = dict(self.value['records'])
        clock = clock or {}
        for (key, _), achieved in zip(MILESTONES, conditions):
            if achieved and key not in records:
                records[key] = {'at': time.time() if now is None else now,
                                'seconds': None if pending else clock.get('seconds'),
                                'lower_bound': bool(clock.get('lower_bound')),
                                'source': 'first_recorded' if pending else 'tracked'}
        if pending or records != self.value['records']:
            value = {**self.value, 'records': records, 'baseline_pending': False}
            self.store.set(KEY, value)
            self.value = value
