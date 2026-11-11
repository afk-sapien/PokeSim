"""Restore missed static encounters without rewinding the adventure or its resources."""
from pokecore.resets import Flag, update_flags

from .events import Event, LOW
from .ram import W_EVENT_FLAGS, W_TOGGLE_OBJECT_FLAGS
from .runtime.supervision import LegendaryRetries
from .strategy_data import DATA, EVENTS, MAPS, SPECIES, WORLD, event_set, object_hidden


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


class LegendaryRecovery(LegendaryRetries):
    def observe(self, snapshot, memory, now, *, repeat=(), blocked=()):
        """Only change flags for an unloaded room, once the retry wait has passed at PlayClock frame ``now``."""
        s = snapshot
        self.count_from(now)
        if not s.valid or not s.started:
            return [], False
        events = []
        changed = False
        for dex, room, obj, flag in ENCOUNTERS:
            key = str(dex)
            # The owned bit stays set after a trade or release. This is not a source of duplicates.
            if dex in blocked or dex in s.owned and dex not in repeat:
                self.pending.pop(key, None)
                continue
            resolved = event_set(s.event_flags, flag) or object_hidden(s, room, obj)
            if not resolved or s.in_battle:
                continue
            name = next(row['name'].title() for row in SPECIES.values() if row['dex'] == dex)
            if key not in self.pending:
                self.miss(key, now)
                events.append(Event('legendary_retry', f'{name} will have another encounter',
                    'The encounter ended without a catch. Leave the area and prepare another attempt. '
                    'Used items, damage, and adventure progress are preserved.', priority=LOW))
                continue
            if now < self.pending[key] or s.map == room or s.textbox or s.start_menu:
                continue
            # EndTrainerBattle sets the event and hides the sprite. Clear both, leaving the
            # current map script alone. The cartridge reloads the sprite on the next visit.
            update_flags(memory, (
                (Flag(W_EVENT_FLAGS, EVENTS[flag]), False),
                (Flag(W_TOGGLE_OBJECT_FLAGS, DATA['toggle_objects'].index([room, obj])), False),
            ))
            del self.pending[key]
            changed = True
            events.append(Event('legendary_retry', f'{name} can be encountered again',
                'The next expedition will prepare capture supplies and storage before returning. '
                'No save was reloaded and no resources were refunded.', priority=LOW))
        return events, changed
