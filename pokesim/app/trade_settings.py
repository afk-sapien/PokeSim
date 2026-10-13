"""Library-wide automatic trading settings: one on/off switch per adventure.

Earlier 0.5.0 builds also stored a wish list per adventure. It is no longer read or offered,
but a stored one is left in place, so an older release still finds it after a downgrade.

The library-wide Ask me first switch below is kept for the unwired trade_requests module.
Nothing in 0.5.0 reads it, so automatic trades always start on their own.

They live in the library registry, not in each adventure's settings, so an older release
that validates adventure settings still opens the library after a downgrade.
"""
from __future__ import annotations

import threading

from .registry import validate_id

KEY = 'trade_auto'
# Settings that cover every adventure at once. Only the unwired Ask me first switch lives here.
LIBRARY_KEY = 'trade_auto_library'
# Every adventure's settings share one registry value, so each change reads and writes it whole.
_write = threading.Lock()


def _all(registry):
    value = registry.setting(KEY, {})
    return value if isinstance(value, dict) else {}


def _clean(entry):
    entry = entry if isinstance(entry, dict) else {}
    return {'enabled': entry.get('enabled', True) is not False}


def get(registry, aid):
    """The automatic trading settings of one adventure. New adventures trade automatically."""
    validate_id(aid)
    return _clean(_all(registry).get(aid))


def update(registry, aid, *, enabled=None):
    validate_id(aid)
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError('Auto trading is either on or off')
    with _write:
        settings = _all(registry)
        stored = settings.get(aid)
        # Other stored keys, such as an old wish list, stay as they were.
        stored = dict(stored) if isinstance(stored, dict) else {}
        if enabled is not None:
            stored['enabled'] = enabled
        settings[aid] = stored
        registry.set_setting(KEY, settings)
        return _clean(stored)


def ask_first(registry):
    """Whether automatic trading would suggest exchanges for the owner to approve. Unused in 0.5.0."""
    value = registry.setting(LIBRARY_KEY, {})
    return not isinstance(value, dict) or value.get('ask_first', True) is not False


def set_ask_first(registry, value):
    if not isinstance(value, bool):
        raise ValueError('Ask me first is either on or off')
    with _write:
        current = registry.setting(LIBRARY_KEY, {})
        current = dict(current) if isinstance(current, dict) else {}
        current['ask_first'] = value
        registry.set_setting(LIBRARY_KEY, current)
    return value
