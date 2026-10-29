"""How fast an adventure catches, for both generations.

Catches per hour divides the catches counted by the simulated playtime. Wild encounters per
catch divides the wild battles the activity ledger counted by the catches it counted.
"""
import json

from .activity_ledger import KEY


def per_catch(wild, caught):
    return round(wild / caught, 1) if wild is not None and caught else None


def status(store, catches, play_clock):
    """``catches`` is the catch counter the Stats page shows and ``play_clock`` the app clock."""
    with store.lock:
        row = store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
        started = bool(row) and json.loads(row[0]).get('started_at') is not None
        wild, caught = (0, 0) if not started else store.db.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='wild' THEN total END), 0), "
            "COALESCE(SUM(CASE WHEN kind='caught' THEN total END), 0) FROM activity_counts").fetchone()
    total = catches.get('total') if catches.get('available') or catches.get('started_at') else None
    seconds = (play_clock or {}).get('seconds')
    hours = seconds / 3600 if seconds else None
    return {'catches_per_hour': round(total / hours, 2) if total is not None and hours else None,
            'encounters_per_catch': per_catch(wild if started else None, caught),
            # Catches counted from part way through are set against all of the playtime.
            'partial': not catches.get('complete_history', False)}
