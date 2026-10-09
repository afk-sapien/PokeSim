"""Retry missed static encounters with the same resource preservation as Gen I."""
from copy import deepcopy

from .ram import Memory


class Recovery:
    def __init__(self, state=None):
        state = state or {}
        self.pending = deepcopy(state.get('pending', {}))
        self.attempts = deepcopy(state.get('attempts', {}))
        self.previous = None

    def state_dict(self):
        return deepcopy({'pending': self.pending, 'attempts': self.attempts})

    def observe(self, snapshot, memory, *, repeat=frozenset(), blocked=frozenset()):
        """Reopen a missed encounter. `repeat` holds walking returns that are owned but not yet caught again."""
        from .returns import encounter, roaming
        data = snapshot.data
        delta = min(120, max(0, snapshot.frame - self.previous)) if self.previous is not None else 0
        self.previous = snapshot.frame
        if not snapshot.valid or not snapshot.started or snapshot.in_battle:
            return []
        encounters = [(249, 'WHIRL_ISLAND_LUGIA_CHAMBER', 'LUGIA'), (250, 'TIN_TOWER_ROOF', 'HO_OH')]
        if data.game == 'crystal':
            encounters.append((245, 'TIN_TOWER_1F', 'SUICUNE'))
        beasts = snapshot.event('EVENT_RELEASED_THE_BEASTS')
        roamers = {row['species'] for row in getattr(snapshot, 'roamers', ())}
        encounters += [(dex, None, None) for dex in (243, 244, 245) if roaming(data, dex)]
        mem, events = Memory(memory, data), []
        for species, room, flag in encounters:
            key = str(species)
            if species in snapshot.owned and species not in repeat or species in blocked:
                self.pending.pop(key, None)
                continue
            unresolved = (not snapshot.event('EVENT_FOUGHT_' + flag) if room
                          else not beasts or species in roamers)
            if unresolved:
                self.pending.pop(key, None)
                continue
            if key not in self.pending:
                self.attempts[key] = self.attempts.get(key, 0) + 1
                self.pending[key] = min(180000, 36000 * self.attempts[key])
            self.pending[key] = max(0, self.pending[key] - delta)
            if (self.pending[key] or room and snapshot.map == data.map_ids[room]
                    or mem.byte('wScriptRunning') or '┌' in snapshot.tiles[12]):
                continue
            encounter(memory, data, species, present=True)
            self.pending.pop(key)
            events.append(species)
        return events
