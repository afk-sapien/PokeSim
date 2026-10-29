"""Money earned and spent, by where it came from or went, for both generations.

Each change in the purse between two continuous observations is counted once. A rise during a
battle is prize money, Pay Day included. Any other rise is a sale, a gift or a withdrawal. A drop
soon after the whole party fainted is the blackout penalty. Any other drop is a shop or a fee.
The counts live with the adventure statistics, so they start when this version first runs.
"""
import json

# The adventure statistics record both generations keep.
KEY = 'adventure-statistics-v1'
SOURCES = ('battles', 'other', 'shops', 'blackouts')
EARNED, SPENT = ('battles', 'other'), ('shops', 'blackouts')
# Both generations halve the purse within a few seconds of the last Pokémon fainting.
BLACKOUT_FRAMES = 1800


class MoneyFlow:
    def __init__(self):
        self.fainted = None

    def reset(self):
        self.fainted = None

    def observe(self, value, before, after, now):
        """Count into the statistics ``value``. ``before`` and ``after`` are continuous observations."""
        flow = value.get('money')
        if flow is None:
            flow = value['money'] = {'since': now, **dict.fromkeys(SOURCES, 0)}
        for snapshot in (before, after):
            if snapshot.all_fainted:
                self.fainted = snapshot.frame
        change = after.money - before.money
        if change > 0:
            flow['battles' if after.in_battle or before.in_battle else 'other'] += change
        elif change < 0:
            blackout = self.fainted is not None and 0 <= after.frame - self.fainted <= BLACKOUT_FRAMES
            flow['blackouts' if blackout else 'shops'] -= change


def status(store):
    with store.lock:
        row = store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    value = json.loads(row[0]) if row else {}
    flow = value.get('money')
    if not flow:
        return {'available': False, 'since': None, 'complete_history': False, 'earned': None, 'spent': None,
                'net': None, 'sources': dict.fromkeys(SOURCES)}
    earned, spent = sum(flow[key] for key in EARNED), sum(flow[key] for key in SPENT)
    started = value.get('started_at')
    return {'available': True, 'since': flow['since'],
            # Counting began with the statistics, so nothing before it was missed.
            'complete_history': started is not None and flow['since'] - started < 60,
            'earned': earned, 'spent': spent, 'net': earned - spent,
            'sources': {key: flow[key] for key in SOURCES}}
