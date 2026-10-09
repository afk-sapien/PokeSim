"""First achievements kept independently of journal retention and save rewinds."""
import time

from .milestones import status as goals_status
from .shiny import status as shiny_status

KEY = 'adventure-records-v1'
GEN2_GOALS = 'pokedex-milestones-v1'
MILESTONES = (
    ('first_badge', 'First badge'), ('all_badges', 'All eight badges'),
    ('champion', 'First Champion victory'), ('pokedex', 'All 151 registered'),
    ('level100', 'First level 100'), ('shiny', 'First shiny acquired'),
    ('perfect', 'First perfect acquired'),
)
# Gold, Silver and Crystal: sixteen badges across two regions and a 251-species Pokédex.
MILESTONES_GEN2 = (
    ('first_badge', 'First badge'), ('all_badges', 'All sixteen badges'),
    ('champion', 'First Champion victory'), ('pokedex', 'All 251 registered'),
    ('level100', 'First level 100'), ('shiny', 'First shiny acquired'),
    ('perfect', 'First perfect acquired'),
)
# (badges, Pokédex size) that complete a generation's badge and registration goals.
TARGETS = {1: (8, 151), 2: (16, 251)}


def milestones(generation=1):
    return MILESTONES_GEN2 if generation == 2 else MILESTONES


def status(store, generation=1):
    value = store.get(KEY) or {}
    records = value.get('records', {})
    return {'started_at': value.get('started_at'), 'milestones': [
        {'key': key, 'label': label, **records.get(key, {}), 'achieved': key in records}
        for key, label in milestones(generation)]}


class RecordTracker:
    def __init__(self, store, *, generation=1):
        self.store = store
        self.generation = generation
        badges, dex = TARGETS[generation]
        self.previous = None
        self.value = store.get(KEY)
        if self.value is None:
            records = {}
            # Dates in legacy progress are observations, not proof of the first achievement time.
            thresholds = {'first_badge': ('badges', 1), 'all_badges': ('badges', badges),
                          'champion': ('league', 1), 'pokedex': ('owned', dex),
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
        conditions = self.conditions(snapshot)
        if self.previous != conditions:
            self.previous = conditions
            return
        pending = self.value['baseline_pending']
        records = dict(self.value['records'])
        clock = clock or {}
        for (key, _), achieved in zip(milestones(self.generation), conditions):
            if achieved and key not in records:
                records[key] = {'at': time.time() if now is None else now,
                                'seconds': None if pending else clock.get('seconds'),
                                'lower_bound': bool(clock.get('lower_bound')),
                                'source': 'first_recorded' if pending else 'tracked'}
        if pending or records != self.value['records']:
            value = {**self.value, 'records': records, 'baseline_pending': False}
            self.store.set(KEY, value)
            self.value = value

    def conditions(self, snapshot):
        """Whether each milestone currently holds, in milestone order."""
        if self.generation == 2:
            goals = self.store.get(GEN2_GOALS) or {}
            rows = [mon for mon in tuple(snapshot.party) + tuple(snapshot.stored) if not mon.egg]
            perfect = max(goals.get('perfect_catches', 0), sum((goals.get('perfect_groups') or {}).values()))
            return (bool(snapshot.badges), snapshot.badges & 0xFFFF == 0xFFFF,
                    snapshot.hall_of_fame_count > 0, len(snapshot.owned) >= 251,
                    bool(goals.get('level_100')), any(mon.shiny for mon in rows), bool(perfect))
        goals = goals_status(self.store)
        shiny = shiny_status(self.store)
        return (bool(snapshot.badges), snapshot.badges == 255,
                snapshot.hall_of_fame_count > 0, len(snapshot.owned) >= 151,
                bool(goals['level_100']), bool(goals.get('shiny_species') or shiny['acquired']),
                bool(goals['perfect_found']))
