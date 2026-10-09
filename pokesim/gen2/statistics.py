"""Observed Gen II activity and collection trends in the shared statistics schema."""
import json
import time

KEY = 'adventure-statistics-v1'


class Statistics:
    def __init__(self, store, clock=None):
        from ..adventure_records import RecordTracker
        self.store = store
        # First achievements, timed on the app play clock like Gen I.
        self.records = RecordTracker(store, generation=2)
        self.clock = clock
        self.value = store.get(KEY) or {'started_at': None, 'counters': dict.fromkeys(
            ('steps', 'battles', 'damage_dealt', 'damage_taken', 'active_frames'), 0)}
        self.previous = None
        self.last_flush = 0

    def observe(self, snapshot):
        if not snapshot.started or not snapshot.valid or self.store.get('trade_hold'):
            self.previous = None
            return
        now = time.time()
        if self.value['started_at'] is None:
            self.value['started_at'] = now
        self.records.observe(snapshot, self.clock() if self.clock else None, now=now)
        before, counters = self.previous, self.value['counters']
        if before and 0 < snapshot.frame - before.frame <= 120:
            counters['active_frames'] += snapshot.frame - before.frame
            if snapshot.in_battle and not before.in_battle:
                counters['battles'] += 1
            if snapshot.in_battle and snapshot.in_battle == before.in_battle:
                if (snapshot.enemy_species, snapshot.enemy_level, snapshot.enemy_max_hp) == (
                        before.enemy_species, before.enemy_level, before.enemy_max_hp):
                    counters['damage_dealt'] += max(0, before.enemy_hp - snapshot.enemy_hp)
                for old, mon in zip(before.party, snapshot.party):
                    if (old.species, old.trainer_id, old.dvs) == (mon.species, mon.trainer_id, mon.dvs):
                        counters['damage_taken'] += max(0, old.hp - mon.hp)
        self.previous = snapshot
        if now - self.last_flush < 30:
            return
        self.flush(snapshot, now)

    def flush(self, snapshot, now=None):
        if snapshot is None or not snapshot.started:
            return
        now = time.time() if now is None else now
        rows = [mon for mon in snapshot.party + snapshot.stored if not mon.egg]
        powers = sorted((sum(mon.stats) for mon in rows), reverse=True)
        captures = self.store.get('capture-statistics-v1') or {}
        self.value['counters']['steps'] = (self.store.get('cartridge-steps-v1') or {}).get('total', 0)
        current = {**self.value['counters'], 'held': len(rows), 'collection_power': sum(powers),
                   'strongest_six_power': sum(powers[:6]), 'average_power': round(sum(powers) / len(rows), 1) if rows else None,
                   'average_dv': round(sum(sum(mon.dvs) * 100 / 75 for mon in rows) / len(rows), 1) if rows else None,
                   'average_level': round(sum(mon.level for mon in rows) / len(rows), 1) if rows else None,
                   'high_quality_held': sum(sum(mon.dvs) >= 60 for mon in rows),
                   'recorded_hours': round(self.value['counters']['active_frames'] / 216000, 3),
                   'captures': captures.get('total', 0), 'marathons': 0}
        self.value.setdefault('baseline', {'ts': now, **current})
        self.value.update(current=current, updated_at=now)
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO statistics_history VALUES (?, ?, ?)',
                                  (int(now // 3600), now, json.dumps(current)))
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(self.value)))
        self.last_flush = now
