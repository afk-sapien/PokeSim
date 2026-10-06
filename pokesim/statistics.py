"""Durable adventure totals and compact collection trends."""
from dataclasses import asdict
import json
import time


KEY = 'adventure-statistics-v1'
INTERVAL = 30
DAY = 86400
COUNTERS = ('steps', 'battles', 'damage_dealt', 'damage_taken', 'active_frames')
GAUGES = ('held', 'collection_power', 'strongest_six_power', 'average_power',
          'average_dv', 'average_level', 'high_quality_held')


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS statistics_history '
               '(bucket INTEGER PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL)')
    db.execute("CREATE INDEX IF NOT EXISTS statistics_marathons ON events(id) "
               "WHERE type='marathon' AND title='Kanto Marathon finished!'")


def collection(snapshot):
    from .pokemon import dv_rating, stored_strength
    rows = [asdict(mon) for mon in snapshot.party] + snapshot.storage_entries()
    powers = [stored_strength(mon)['power'] for mon in rows]
    dvs = [dv_rating(mon)['dv_percent'] for mon in rows]
    complete = all(power is not None for power in powers)
    return {
        'held': len(rows),
        'collection_power': sum(powers) if complete else None,
        'strongest_six_power': sum(sorted(powers, reverse=True)[:6]) if complete else None,
        'average_power': round(sum(powers) / len(rows), 1) if rows and complete else None,
        'average_dv': round(sum(dvs) / len(rows), 1) if rows and all(v is not None for v in dvs) else None,
        'average_level': round(sum(mon['level'] for mon in rows) / len(rows), 1) if rows else None,
        'high_quality_held': (sum((dv_rating(mon)['dv_stars'] or 0) >= 3 for mon in rows)
                              if all(v is not None for v in dvs) else None),
    }


def history(db, limit=600):
    # Select in SQL so an old adventure never sends an unbounded history to the browser.
    bounds = db.execute('SELECT MIN(ts), MAX(ts) FROM statistics_history').fetchone()
    if bounds[0] is None:
        return []
    width = max(1, (bounds[1] - bounds[0]) / (limit - 2))
    rows = db.execute('SELECT ts, data FROM statistics_history WHERE bucket IN ('
                      'SELECT MAX(bucket) FROM statistics_history GROUP BY CAST((ts - ?) / ? AS INTEGER)'
                      ' UNION SELECT MIN(bucket) FROM statistics_history) ORDER BY ts', (bounds[0], width))
    return [{'ts': row[0], **json.loads(row[1])} for row in rows]


def status(store):
    with store.lock:
        row = store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
        value = json.loads(row[0]) if row else {}
        rows = history(store.db, limit=599)
        baseline = value.get('baseline')
        if baseline and rows and baseline['ts'] < rows[0]['ts']:
            rows.insert(0, baseline)
        return {'started_at': value.get('started_at'), 'updated_at': value.get('updated_at'),
                'current': value.get('current', {}), 'history': rows}


class StatisticsTracker:
    def __init__(self, store):
        self.store = store
        self.value = store.get(KEY) or {'started_at': None, 'current': {}, 'counters': dict.fromkeys(COUNTERS, 0)}
        self.previous = None
        self.enemy = None
        self.gauges = {key: self.value['current'][key] for key in GAUGES if key in self.value['current']} or None
        self.candidate = None
        self.last_collection = self.last_flush = 0

    def reset_baseline(self):
        self.previous = self.enemy = self.candidate = None
        self.last_collection = 0

    def observe(self, snapshot, memory=None, *, now=None):
        from .screen import W_ENEMY_HP, W_ENEMY_MAX_HP, W_PLAYER_MON_NUMBER
        now = time.time() if now is None else now
        if not snapshot.valid or not snapshot.started or self.store.get('trade_hold'):
            self.reset_baseline()
            return
        if self.value['started_at'] is None:
            self.value['started_at'] = now
        previous = self.previous
        counters = self.value['counters']
        continuous = previous is not None and 0 < snapshot.frame - previous.frame <= 120
        if continuous:
            counters['active_frames'] += snapshot.frame - previous.frame
            walking = (not snapshot.in_battle and not previous.in_battle
                       and not snapshot.start_menu and not previous.start_menu
                       and snapshot.map == previous.map)
            if walking and abs(snapshot.x - previous.x) + abs(snapshot.y - previous.y) == 1:
                counters['steps'] += 1
            if snapshot.in_battle in (1, 2) and not previous.in_battle:
                counters['battles'] += 1
            if snapshot.in_battle in (1, 2) and snapshot.in_battle == previous.in_battle:
                # Identity and slot must match. Switching, healing and box writes are not damage.
                for before, after in zip(previous.party, snapshot.party):
                    identity = lambda mon: (mon.species, mon.nick, mon.trainer_id, mon.dvs, mon.max_hp)
                    if identity(before) == identity(after):
                        counters['damage_taken'] += max(0, before.hp - after.hp)
        enemy = None
        if memory is not None and snapshot.in_battle in (1, 2):
            hp = memory[W_ENEMY_HP] * 256 + memory[W_ENEMY_HP + 1]
            maximum = memory[W_ENEMY_MAX_HP] * 256 + memory[W_ENEMY_MAX_HP + 1]
            if 0 <= hp <= maximum <= 999 and maximum:
                token = (snapshot.in_battle, snapshot.opponent, snapshot.enemy_species,
                         snapshot.enemy_level, maximum, memory[W_PLAYER_MON_NUMBER])
                enemy = (token, hp)
                if continuous and self.enemy and self.enemy[0] == token:
                    counters['damage_dealt'] += max(0, self.enemy[1] - hp)
        self.previous, self.enemy = snapshot, enemy
        if now - self.last_collection >= INTERVAL or self.gauges is None:
            # Two matching observations avoid reporting a half-written PC transfer.
            candidate = collection(snapshot)
            if candidate == self.candidate:
                self.gauges = candidate
                self.last_collection = now
            self.candidate = candidate
        if self.gauges is not None and now - self.last_flush >= INTERVAL:
            self.flush(now=now)

    def flush(self, *, now=None):
        if self.value['started_at'] is None:
            return
        now = time.time() if now is None else now
        from .catches import status as catches
        captures = catches(self.store)
        # Receipts predate this tracker. Preserve their verified total through a fresh run too.
        value = {**self.value, 'counters': dict(self.value['counters'])}
        total = captures['total']
        previous = value.get('capture_baseline', 0)
        value['captures'] = value.get('captures', 0) + (total - previous if total >= previous else total)
        value['capture_baseline'] = total
        current = {**value['counters'], **(self.gauges or {}),
                   'recorded_hours': round(value['counters']['active_frames'] / 216000, 3),
                   'captures': value['captures'] if captures['available'] else None}
        with self.store.lock, self.store.db:
            # The journal is durable across checkpoint restores and includes pre-upgrade races.
            current['marathons'] = self.store.db.execute(
                "SELECT COUNT(*) FROM events WHERE type='marathon' AND title='Kanto Marathon finished!'").fetchone()[0]
            value.setdefault('baseline', {'ts': now, **current})
            value.update(current=current, updated_at=now)
            self.store.db.execute('INSERT OR REPLACE INTO statistics_history VALUES (?, ?, ?)',
                                  (int(now // 3600), now, json.dumps(current)))
            if int(now // DAY) != value.get('compacted_day'):
                # Retain hourly endpoints for 30 days, then one endpoint per day indefinitely.
                self.store.db.execute('DELETE FROM statistics_history WHERE ts < ? AND bucket NOT IN ('
                                      'SELECT MAX(bucket) FROM statistics_history GROUP BY CAST(ts / ? AS INTEGER))',
                                      (now - 30 * DAY, DAY))
                value['compacted_day'] = int(now // DAY)
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))
        self.value = value
        self.last_flush = now
