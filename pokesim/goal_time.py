"""What the bot is working on: its current goal, its share of play per goal and its recent stand-downs.

Both generations keep the stand-downs in one table of the progress monitor (planning/monitor.py),
saved with the policy. This only reads that table and the current goal, so it never changes a decision.
Frames are counted between observations and written at most once a minute, so a restart loses less than
a minute of counting.
"""
import json
import time

from .planning.monitor import STAND_DOWNS, STOOD_DOWN

KEY = 'goal-time-v1'
FLUSH_SECONDS = 60
# A longer gap between two observations is a reload or a pause, not time spent on the goal.
LONGEST_GAP = 600
# Goals kept with their frame counts, the smallest dropped first, and stand-downs kept, oldest dropped first.
KEPT_GOALS = 200
KEPT_STAND_DOWNS = 12
SHOWN_GOALS = 8


def gen1_view(policy):
    """The current goal and the stand-down record of Red, Blue and Yellow."""
    goal = getattr(policy, 'goal', None)
    director = getattr(getattr(policy, 'collection', None), 'director', None)
    record = getattr(director, 'progress', None)
    return (goal.key, goal.title) if goal else None, record if isinstance(record, dict) else {}


def gen2_view(policy):
    """The current goal and the stand-down record of Gold, Silver and Crystal."""
    goal = getattr(policy, 'goal', None)
    record = getattr(policy, 'collection', None)
    return (goal.key, goal.label) if goal else None, record if isinstance(record, dict) else {}


class GoalTime:
    def __init__(self, store):
        self.store = store
        saved = store.get(KEY)
        self.value = saved if isinstance(saved, dict) else {'since': None, 'current': None, 'goals': {},
                                                             'stand_downs': []}
        self.frame = self.goal = None
        self.seen = None
        self.last_flush = 0

    def observe(self, goal, record, frame, now=None):
        """Count the frames since the last call against the goal that was running, and note new stand-downs."""
        now = time.time() if now is None else now
        value = self.value
        if value['since'] is None:
            value['since'] = now
        if self.goal is not None and self.frame is not None and 0 < frame - self.frame <= LONGEST_GAP:
            key, label = self.goal
            entry = value['goals'].setdefault(key, {'label': label, 'frames': 0})
            entry['label'] = label
            entry['frames'] += frame - self.frame
        self._stand_downs(record, now)
        self.frame = frame
        if goal is not None:
            key, label = goal
            current = value.get('current') or {}
            if current.get('key') != key:
                value['current'] = {'key': key, 'label': label, 'since': now}
            self.goal = (key, label)
        if now - self.last_flush >= FLUSH_SECONDS:
            self.flush(now)

    def _stand_downs(self, record, now):
        stood, counts = record.get(STOOD_DOWN) or {}, record.get(STAND_DOWNS) or {}
        seen = {key: (when, counts.get(key, 0)) for key, when in stood.items()}
        if self.seen is not None:
            for key, (when, count) in seen.items():
                earlier = self.seen.get(key)
                # A reload rewinds the times, so only a later time or a higher count is a new stand-down.
                if earlier is None or when > earlier[0] or count > earlier[1]:
                    label = self.goal[1] if self.goal else None
                    self.value['stand_downs'].append({'key': key, 'label': label, 'at': now, 'in_a_row': count})
            del self.value['stand_downs'][:-KEPT_STAND_DOWNS]
            for key, earlier in self.seen.items():
                seen.setdefault(key, earlier)
        self.seen = seen

    def flush(self, now=None):
        self.last_flush = time.time() if now is None else now
        goals = self.value['goals']
        if len(goals) > KEPT_GOALS:
            kept = sorted(goals, key=lambda key: goals[key]['frames'], reverse=True)[:KEPT_GOALS]
            self.value['goals'] = {key: goals[key] for key in kept}
        self.store.set(KEY, self.value)


def status(store):
    with store.lock:
        row = store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    value = json.loads(row[0]) if row else {}
    goals = value.get('goals') or {}
    total = sum(entry['frames'] for entry in goals.values())
    ranked = sorted(goals.items(), key=lambda item: item[1]['frames'], reverse=True)
    shares = [{'key': key, 'label': entry['label'], 'frames': entry['frames'],
               'share': round(entry['frames'] / total, 4)} for key, entry in ranked[:SHOWN_GOALS]] if total else []
    rest = total - sum(row['frames'] for row in shares)
    return {'available': bool(row), 'since': value.get('since'), 'current': value.get('current'),
            'frames': total, 'shares': shares, 'other_frames': rest,
            'stand_downs': list(reversed(value.get('stand_downs') or []))}
