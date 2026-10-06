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

    def observe(self, snapshot, memory):
        data = snapshot.data
        delta = min(120, max(0, snapshot.frame - self.previous)) if self.previous is not None else 0
        self.previous = snapshot.frame
        if not snapshot.valid or not snapshot.started or snapshot.in_battle:
            return []
        encounters = [(249, 'WHIRL_ISLAND_LUGIA_CHAMBER', 'LUGIA', 'EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA'),
                      (250, 'TIN_TOWER_ROOF', 'HO_OH', 'EVENT_TIN_TOWER_ROOF_HO_OH')]
        if data.game == 'crystal':
            encounters.append((245, 'TIN_TOWER_1F', 'SUICUNE', 'EVENT_TIN_TOWER_1F_SUICUNE'))
        mem, events = Memory(memory, data), []
        for species, room, flag, hidden in encounters:
            key = str(species)
            if species in snapshot.owned:
                self.pending.pop(key, None)
                continue
            if not snapshot.event('EVENT_FOUGHT_' + flag):
                self.pending.pop(key, None)
                continue
            if key not in self.pending:
                self.attempts[key] = self.attempts.get(key, 0) + 1
                self.pending[key] = min(180000, 36000 * self.attempts[key])
            self.pending[key] = max(0, self.pending[key] - delta)
            if (self.pending[key] or snapshot.map == data.map_ids[room]
                    or mem.byte('wScriptRunning') or '┌' in snapshot.tiles[12]):
                continue
            bank, address = data.symbols['wEventFlags']
            for event in ('EVENT_FOUGHT_' + flag, hidden):
                index = data.events[event]
                offset, bit = divmod(index, 8)
                memory[bank, address + offset] = mem.byte('wEventFlags', offset) & ~(1 << bit)
            if species == 245:
                bank, address = data.symbols['wTinTower1FSceneID']
                memory[bank, address] = 0
            self.pending.pop(key)
            events.append(species)
        return events
