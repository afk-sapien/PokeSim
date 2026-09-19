"""Restore missed static encounters without rewinding the adventure or its resources."""
from copy import deepcopy

from .events import Event, LOW
from .ram import W_EVENT_FLAGS, W_TOGGLE_OBJECT_FLAGS
from .strategy_data import DATA, EVENTS, MAPS, SPECIES, WORLD, event_set, object_hidden

RETRY_FRAMES = 36000
MAX_RETRY_FRAMES = 180000


def encounters():
    for dex, room, fragment in (
        (144, 'SEAFOAM_ISLANDS_B4F', 'ARTICUNO'),
        (145, 'POWER_PLANT', 'ZAPDOS'),
        (146, 'VICTORY_ROAD_2F', 'MOLTRES'),
        (150, 'CERULEAN_CAVE_B1F', 'MEWTWO'),
    ):
        map_id = MAPS[room]
        obj = next(i for i, row in enumerate(WORLD[map_id]['objects']) if fragment in row[4])
        yield dex, map_id, obj, 'EVENT_BEAT_' + fragment


ENCOUNTERS = tuple(encounters())


class LegendaryRecovery:
    def __init__(self, state=None):
        state = state or {}
        self.pending = deepcopy(state.get('pending', {}))
        self.attempts = deepcopy(state.get('attempts', {}))
        self.last_frame = None

    def state_dict(self):
        return deepcopy({'pending': self.pending, 'attempts': self.attempts})

    def observe(self, snapshot, memory):
        """Only change flags for an unloaded room, after a bounded retry delay."""
        s = snapshot
        delta = max(0, min(120, s.frame - self.last_frame)) if self.last_frame is not None else 0
        self.last_frame = s.frame
        if not s.valid or not s.started:
            return [], False
        events = []
        changed = False
        for dex, room, obj, flag in ENCOUNTERS:
            key = str(dex)
            # The owned bit stays set after a trade or release. This is not a source of duplicates.
            if dex in s.owned:
                self.pending.pop(key, None)
                continue
            resolved = event_set(s.event_flags, flag) or object_hidden(s, room, obj)
            if not resolved or s.in_battle:
                continue
            name = next(row['name'].title() for row in SPECIES.values() if row['dex'] == dex)
            if key not in self.pending:
                count = self.attempts.get(key, 0) + 1
                self.attempts[key] = count
                self.pending[key] = min(MAX_RETRY_FRAMES, RETRY_FRAMES * count)
                events.append(Event('legendary_retry', f'{name} will have another encounter',
                    'The encounter ended without a catch. Leave the area and prepare another attempt. '
                    'Used items, damage, and adventure progress are preserved.', priority=LOW))
                continue
            self.pending[key] = max(0, self.pending[key] - delta)
            if self.pending[key] or s.map == room or s.textbox or s.start_menu:
                continue
            # EndTrainerBattle sets the event and hides the sprite. Clear both, leaving the
            # current map script alone. The cartridge reloads the sprite on the next visit.
            for base, bit in ((W_EVENT_FLAGS, EVENTS[flag]),
                              (W_TOGGLE_OBJECT_FLAGS, DATA['toggle_objects'].index([room, obj]))):
                address = base + bit // 8
                memory[address] &= ~(1 << (bit % 8))
            del self.pending[key]
            changed = True
            events.append(Event('legendary_retry', f'{name} can be encountered again',
                'The next expedition will prepare capture supplies and storage before returning. '
                'No save was reloaded and no resources were refunded.', priority=LOW))
        return events, changed
