"""Prepare a boxed Gen II offer with ordinary travel and PC controls."""
import time

from ..trade.preferences import identity
from .menus import ChangeBox, Give, Storage
from .policy import Action
from .ram import Memory, read_snapshot
from .world import update as update_world

KEY = 'interaction_preparation'


def selected(snapshot, preferences, key):
    matches = [('party', index, mon) for index, mon in enumerate(snapshot.party)
               if identity(mon.to_dict()) == key]
    matches += [('box', mon.position, mon) for mon in snapshot.stored if identity(mon.to_dict()) == key]
    if len(matches) != 1 or matches[0][2].egg:
        raise ValueError('The selected individual is missing or ambiguous')
    if preferences.get(key, {}).get('state') in {'locked', 'withdrawn'}:
        raise ValueError('The selected Pokémon is protected or withdrawn')
    return matches[0]


def begin(emu, key, tid, *, time_capsule=False):
    saved = emu.store.get(KEY)
    if saved and saved['id'] == tid:
        if saved.get('trade_key') != key:
            raise ValueError('The preparation ID already names another Pokémon')
        if saved.get('phase') == 'travelling' and emu.preparation is None:
            raise ValueError('Trade preparation was interrupted. Release the reservation and retry')
        return saved
    if emu.store.get('trade_hold') or saved:
        raise ValueError('Another exchange reserves this adventure')
    if emu.paused or emu.manual_mode:
        raise ValueError('Resume autonomous play before preparing a trade')
    snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
    if selected(snapshot, emu.store.trade_preferences(), key)[0] != 'box':
        raise ValueError('Choose a boxed offer. Active party members are protected')
    if time_capsule:
        from .timecapsule import compatible, unlocked
        if not unlocked(snapshot, Memory(emu.pb.memory, emu.data)):
            raise ValueError('The Time Capsule opens the day after meeting Bill')
        if not compatible(selected(snapshot, emu.store.trade_preferences(), key)[2], emu.data):
            raise ValueError('The selected Pokémon cannot enter the Time Capsule')
    state = {'id': tid, 'trade_key': key, 'phase': 'travelling', 'started_frame': emu.frame,
             'deadline': time.time() + 1800, 'party_slot': None, 'time_capsule': time_capsule}
    if time_capsule:
        state['original_party'] = [identity(mon.to_dict()) for mon in snapshot.party]
    emu.store.set(KEY, state)
    emu.preparation = Preparation(emu, state)
    return state


class Preparation:
    def __init__(self, emu, state):
        self.emu, self.state = emu, state
        self.menu = None
        self.center = None

    def step(self, snapshot):
        try:
            return self.advance(snapshot)
        except (ValueError, StopIteration) as error:
            self.state.update(phase='failed', error=str(error) or 'No safe PC storage operation is available')
            self.emu.store.set(KEY, self.state)
            self.emu.paused = True
            return Action(None, 0, 1)

    def advance(self, snapshot):
        emu, state = self.emu, self.state
        if time.time() > state['deadline'] or emu.frame - state['started_frame'] > 108000:
            raise ValueError('The trainer did not reach the Cable Club before the preparation deadline')
        policy, data = emu.policy, emu.data
        mem = Memory(emu.pb.memory, data)
        if snapshot.in_battle or policy.in_league(snapshot):
            return policy.step(snapshot, emu.pb.memory)
        update_world(policy.nav.regions, snapshot)
        policy.nav.regions.observe(snapshot.map, policy.nav.collision(snapshot, emu.pb.memory))
        policy.nav.observe(snapshot)
        if self.menu:
            button = self.menu.step(snapshot, mem)
            if button:
                return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
            self.menu = None
        if 'TURN OFF' in snapshot.text:
            return Action('b', 8, 32)
        if 'CHANGE BOX' in snapshot.text or 'Choose a' in snapshot.text or 'CANCEL' in snapshot.text:
            return Action('b', 8, 32)
        if '┌' in snapshot.tiles[12] or mem.byte('wScriptRunning'):
            return Action('a', 8, 32)
        if any(member.status for member in snapshot.party if not member.egg):
            goal = policy.healing(snapshot)
            if goal is None:
                raise ValueError('The party needs a Pokémon Center before link preparation')
            surf = any(57 in member.moves for member in snapshot.party) and bool(snapshot.badges & 8)
            path = policy.nav.toward(snapshot, data.map_ids[goal.map_name], [(goal.x, goal.y)], emu.pb.memory, surf=surf)
            policy.mode = 'Heal the party before the Cable Club exchange'
            if path:
                return policy.walk(snapshot, emu.pb.memory, path)
            if path is None:
                return Action(None, 0, 24)
            return Action('up' if mem.byte('wPlayerDirection') & 12 != 4 else 'a', 8, 32)
        location, slot, mon = selected(snapshot, emu.store.trade_preferences(), state['trade_key'])
        from .timecapsule import compatible
        incompatible = next((i for i, member in enumerate(snapshot.party) if not compatible(member, data)), None)
        needs_storage = location != 'party' or state.get('time_capsule') and incompatible is not None
        if location == 'party' and not state.get('time_capsule'):
            from .cable_verification import available_trade_item
            item = available_trade_item(data, mon.species, mon.held_item, dict(snapshot.items),
                                        replace_held=state.get('replace_held', False))
            if item:
                self.menu = Give(item, slot)
                return Action(None, 0, 24)
        surf = any(57 in mon.moves for mon in snapshot.party) and bool(snapshot.badges & 8)
        if needs_storage and snapshot.map == data.map_ids['POKECENTER_2F']:
            path = policy.nav.toward(snapshot, snapshot.map, [(0, 7)], emu.pb.memory, surf=surf)
            policy.mode = 'Return downstairs for the next boxed exchange'
            return policy.walk(snapshot, emu.pb.memory, path) if path else Action(None, 0, 24)
        if not needs_storage:
            target, point = data.map_ids['POKECENTER_2F'], (3, 4)
        else:
            if self.center is None:
                choices = []
                for mid, entry in data.maps.items():
                    if entry['constant'].endswith('POKECENTER_1F'):
                        computers = [(i % entry['width'], i // entry['width'] + 1)
                                     for i, tile in enumerate(entry['collision']) if tile == 0x93]
                        if not computers:
                            continue
                        route = policy.nav.regions.route(snapshot, mid, computers, cut=bool(snapshot.badges & 2), surf=surf)
                        if route is not None:
                            choices.append((len(route), mid, computers[0]))
                if not choices:
                    raise ValueError('No reachable Pokémon Center for this offer')
                self.center = min(choices)[1:]
            target, point = self.center
        path = policy.nav.toward(snapshot, target, [point], emu.pb.memory, surf=surf)
        policy.mode = 'Prepare the Cable Club exchange'
        if path:
            return policy.walk(snapshot, emu.pb.memory, path)
        if path is None:
            return Action(None, 0, 24)
        if not needs_storage:
            state.update(phase='ready', party_slot=slot)
            emu.snapshot = snapshot
            if state.get('original_party'):
                policy.collection['time_capsule_restore'] = state['original_party']
            source = emu._autosave(trade_prepare=True)
            if source is None:
                raise ValueError('Cannot checkpoint the prepared adventure')
            emu.store.set('trade_hold', {'id': state['id'], 'source': source.name, 'phase': 'prepared'})
            emu.store.set(KEY, state)
            emu.paused = True
            return Action(None, 0, 0)
        if mem.byte('wPlayerDirection') & 12 != 4:
            return Action('up', 8, 16)
        if state.get('time_capsule') and incompatible is not None and len(snapshot.party) > 1:
            if snapshot.box_counts[snapshot.active_box] >= 20:
                box = next(i for i, count in enumerate(snapshot.box_counts) if count < 20)
                self.menu = ChangeBox(box)
            else:
                self.menu = Storage('DEPOSIT', incompatible, len(snapshot.party))
        elif len(snapshot.party) == 6:
            if snapshot.box_counts[snapshot.active_box] >= 20:
                box = next(i for i, count in enumerate(snapshot.box_counts) if count < 20)
                self.menu = ChangeBox(box)
            else:
                protected = {15, 19, 57, 70, 148, 250, 127}
                candidates = [i for i, member in enumerate(snapshot.party) if i and not protected.intersection(member.moves)]
                if not candidates:
                    raise ValueError('The party has no safe reserve to deposit for this exchange')
                self.menu = Storage('DEPOSIT', min(candidates, key=lambda i: snapshot.party[i].level), 6)
        elif mon.box != snapshot.active_box:
            self.menu = ChangeBox(mon.box)
        else:
            self.menu = Storage('WITHDRAW', slot, len(snapshot.party))
        return Action('a', 8, 32)
