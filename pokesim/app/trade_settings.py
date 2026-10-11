"""Library-wide automatic trading settings: one on/off switch and one wish list per adventure.

They live in the library registry, not in each adventure's settings, so an older release
that validates adventure settings still opens the library after a downgrade.
"""
from __future__ import annotations

import threading

from .registry import validate_id

KEY = 'trade_auto'
MAX_WISHES = 50
# Every adventure's settings share one registry value, so each change reads and writes it whole.
_write = threading.Lock()


def _all(registry):
    value = registry.setting(KEY, {})
    return value if isinstance(value, dict) else {}


def _clean(entry):
    entry = entry if isinstance(entry, dict) else {}
    wishes = []
    for dex in entry.get('wishlist') or []:
        if type(dex) is int and 1 <= dex <= 251 and dex not in wishes:
            wishes.append(dex)
    return {'enabled': entry.get('enabled', True) is not False, 'wishlist': wishes[:MAX_WISHES]}


def get(registry, aid):
    """The automatic trading settings of one adventure. New adventures trade automatically."""
    validate_id(aid)
    return _clean(_all(registry).get(aid))


def wished(registry):
    """Every species on any adventure's wish list."""
    return sorted({dex for entry in _all(registry).values() for dex in _clean(entry)['wishlist']})


def update(registry, aid, *, enabled=None, wishlist=None, dex_total=251):
    validate_id(aid)
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError('Auto trading is either on or off')
    with _write:
        return _update(registry, aid, enabled, wishlist, dex_total)


def _update(registry, aid, enabled, wishlist, dex_total):
    current = get(registry, aid)
    if enabled is not None:
        current['enabled'] = enabled
    if wishlist is not None:
        if not isinstance(wishlist, list) or len(wishlist) > MAX_WISHES:
            raise ValueError(f'A wish list holds up to {MAX_WISHES} species')
        for dex in wishlist:
            if type(dex) is not int or not 1 <= dex <= dex_total:
                raise ValueError('Choose a species this game can hold')
        current['wishlist'] = list(dict.fromkeys(wishlist))
    settings = _all(registry)
    settings[aid] = current
    registry.set_setting(KEY, settings)
    return current


def wanted(settings, inventory):
    """Wished species this adventure holds none of right now."""
    held = {mon.get('dex') for mon in list(inventory.get('party') or [])
            + list((inventory.get('storage') or {}).get('pokemon') or [])}
    return set(settings['wishlist']) - held
