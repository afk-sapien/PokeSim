"""Prepare a boxed Gen II offer with ordinary travel and PC controls."""
import time

from pokecore.identity import same
from ..trade.preferences import identity
from .teams import key as team_key
from .menus import PROTECTED_MOVES, ChangeBox, Give, Release, Storage
from .policy import Action
from pokecore.gen2.ram import Memory, read_snapshot
from .world import update as update_world

KEY = 'interaction_preparation'
FULL = 'Every PC box is full and no spare duplicate can be safely released to make room for this trade'


def reserves(party):
    """Party slots an automatic trade may deposit, never the lead or the party's only user of a field move."""
    found = []
    for index, member in enumerate(party):
        if not index:
            continue
        others = {move for other, mate in enumerate(party) if other != index for move in getattr(mate, 'moves', ())}
        if PROTECTED_MOVES.intersection(getattr(member, 'moves', ())) <= others:
            found.append(index)
    return found


def selected(snapshot, preferences, key):
    matches = [('party', index, mon) for index, mon in enumerate(snapshot.party)
               if same(identity(mon.to_dict(egg_view=True)), key)]
    matches += [('box', mon.position, mon) for mon in snapshot.stored if same(identity(mon.to_dict(egg_view=True)), key)]
    if len(matches) != 1 or matches[0][2].egg:
        raise ValueError('The selected individual is missing or ambiguous')
    if (preferences.get(identity(matches[0][2].to_dict(egg_view=True))) or preferences.get(key) or {}).get('state') in {'locked', 'withdrawn'}:
        raise ValueError('The selected Pokémon is protected or withdrawn')
    return matches[0]


def begin(emu, key, tid, *, time_capsule=False, manual=False, session=False, protect=(), wished=()):
    """Start walking to the Cable Club. A session (key None) brings the party as it is."""
    saved = emu.store.get(KEY)
    if saved and saved['id'] == tid:
        if saved.get('trade_key') != key:
            raise ValueError('The preparation ID already names another Pokémon')
        if saved.get('phase') == 'travelling' and emu.preparation is None:
            raise ValueError('Trade preparation was interrupted. Release the reservation and retry')
        return saved
    if emu.store.get('trade_hold') or saved and saved.get('phase') not in ('failed', 'cancelled'):
        raise ValueError('Another exchange reserves this adventure')
    if emu.paused or emu.manual_mode:
        raise ValueError('Resume autonomous play before preparing a trade')
    snapshot = read_snapshot(emu.pb.memory, emu.data, emu.frame)
    # A manual trade is the owner's own choice, so trade preferences and party protection do not apply.
    preferences = {} if manual else emu.store.trade_preferences()
    if session:
        if key is not None or time_capsule:
            raise ValueError('A Cable Club session brings the whole party and no selected Pokémon')
    elif selected(snapshot, preferences, key)[0] != 'box' and not manual:
        raise ValueError('Choose a boxed offer. Active party members are protected')
    if time_capsule:
        from .timecapsule import compatible, unlocked
        if not unlocked(snapshot, Memory(emu.pb.memory, emu.data)):
            raise ValueError('The Time Capsule opens the day after meeting Bill')
        if not compatible(selected(snapshot, preferences, key)[2], emu.data):
            raise ValueError('The selected Pokémon cannot enter the Time Capsule')
    state = {'id': tid, 'trade_key': key, 'phase': 'travelling', 'started_frame': emu.frame,
             'deadline': time.time() + 1800, 'party_slot': None, 'time_capsule': time_capsule}
    if manual:
        state['manual'] = True
    if session:
        state['session'] = True
    # Hand-picked Pokémon and wished species the PC must keep if it has to release one to make room.
    state['protect'] = sorted({key, *protect} - {None})
    state['wished'] = sorted(set(wished))
    if time_capsule:
        state['original_party'] = [team_key(mon) for mon in snapshot.party]
    emu.store.set(KEY, state)
    emu.preparation = Preparation(emu, state)
    return state


def stranded(party, slot):
    """Whether depositing ``slot`` leaves no party Pokémon able to battle, which Gen II refuses."""
    return not any(mon.hp and not mon.egg for i, mon in enumerate(party) if i != slot)


class Preparation:
    def __init__(self, emu, state):
        self.emu, self.state = emu, state
        self.menu = None
        self.center = None
        self.claimed = False
        self.released = None
        self.reviving = False

    def step(self, snapshot):
        if not self.claimed:
            # Preparation owns the screen and the party until it hands the adventure back. A
            # policy menu left half finished here would resume later with stale party slots.
            self.emu.policy.menu = None
            self.claimed = True
        try:
            return self.advance(snapshot)
        except (ValueError, StopIteration) as error:
            # Give the adventure back to the policy, as Gen 1 does, so a failed
            # preparation never leaves the run paused with nothing to resume it.
            self.state.update(phase='failed', error=str(error) or 'No safe PC storage operation is available')
            self.emu.store.set(KEY, self.state)
            self.emu.preparation = None
            self.menu = None
            self.emu.policy.on_restore()
            return Action(None, 0, 1)

    def make_room(self, snapshot):
        """A menu that opens a box with a free slot, or releases one safe spare when every box is full."""
        box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
        if box is not None:
            return ChangeBox(box)
        spare = self.emu.policy.trade_spare(snapshot, self.state.get('protect', ()), self.state.get('wished', ()))
        if spare is None:
            raise ValueError(FULL)
        if spare.box != snapshot.active_box:
            return ChangeBox(spare.box)
        self.released = spare
        return Release(spare.box, spare.position, [spare.species, spare.trainer_id, list(spare.dvs)])

    def announce(self, snapshot):
        """Log the spare the PC let go once it has left its box."""
        spare, self.released = self.released, None
        if spare is None or any(mon.box == spare.box and mon.position == spare.position
                                and [mon.species, mon.trainer_id, mon.dvs] == [spare.species, spare.trainer_id, spare.dvs]
                                for mon in snapshot.stored):
            return
        name = self.emu.data.species.get(spare.species, {}).get('name', f'#{spare.species}')
        title = f'Released {spare.nick or name} ({name} Lv {spare.level}) to make room for a trade'
        body = f'Every PC box was full, so a spare {name} was let go to make room for a trade.'
        released = self.state.setdefault('released', [])
        released.append({'species': spare.species, 'level': spare.level, 'nick': spare.nick, 'box': spare.box,
                         'position': spare.position, 'trainer_id': spare.trainer_id, 'dvs': list(spare.dvs)})
        self.emu.store.set(KEY, self.state)
        log = getattr(self.emu, '_event', None)
        if log is not None:
            from .emulator import Event
            log(Event('release', title, body, priority=3), snapshot)

    def heal(self, snapshot, mem):
        """Walk to the nurse and talk to her until the party is healed."""
        policy, data = self.emu.policy, self.emu.data
        goal = policy.healing(snapshot)
        if goal is None:
            raise ValueError('The party needs a Pokémon Center before link preparation')
        surf = any(57 in member.moves for member in snapshot.party) and bool(snapshot.badges & 8)
        path = policy.nav.toward(snapshot, data.map_ids[goal.map_name], [(goal.x, goal.y)], self.emu.pb.memory, surf=surf)
        policy.mode = 'Heal the party before the Cable Club exchange'
        if path:
            return policy.walk(snapshot, self.emu.pb.memory, path)
        if path is None:
            return Action(None, 0, 24)
        return Action('up' if mem.byte('wPlayerDirection') & 12 != 4 else 'a', 8, 32)

    def advance(self, snapshot):
        emu, state = self.emu, self.state
        if time.time() > state['deadline'] or emu.frame - state['started_frame'] > 108000:
            raise ValueError('The trainer did not reach the Cable Club before the preparation deadline')
        policy, data = emu.policy, emu.data
        mem = Memory(emu.pb.memory, data)
        if snapshot.in_battle or policy.in_league(snapshot):
            return policy.step(snapshot, emu.pb.memory)
        # A battle shortcut the policy started during that battle is never stepped again here.
        # Left in place, it would resume after an abort, wait on the open PC and freeze the screen.
        policy.menu = None
        update_world(policy.nav.regions, snapshot)
        # A reset back to the opening reads map 0, which has no layout. Looking up its collision
        # crashed a live Crystal run during a Cable Club walk. The policy presses through the opening.
        if snapshot.map not in data.maps:
            return policy.step(snapshot, emu.pb.memory)
        policy.nav.regions.observe(snapshot.map, policy.nav.collision(snapshot, emu.pb.memory))
        policy.nav.observe(snapshot)
        if self.menu:
            button = self.menu.step(snapshot, mem)
            if button:
                return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
            self.menu = None
            self.announce(snapshot)
        if 'TURN OFF' in snapshot.text:
            return Action('b', 8, 32)
        if 'CHANGE BOX' in snapshot.text or 'Choose a' in snapshot.text or 'CANCEL' in snapshot.text:
            return Action('b', 8, 32)
        if '┌' in snapshot.tiles[12] or mem.byte('wScriptRunning'):
            return Action('a', 8, 32)
        if any(member.status for member in snapshot.party if not member.egg):
            return self.heal(snapshot, mem)
        if self.reviving:
            # Once a deposit was found to strand the party, the walk to the nurse continues away
            # from the PC until every fainted Pokémon is revived.
            if any(not member.hp for member in snapshot.party if not member.egg):
                return self.heal(snapshot, mem)
            # The nurse can be in another town, past ledges that never lead back to the old PC.
            self.reviving, self.center = False, None
        if state.get('session'):
            location, slot, mon, incompatible, needs_storage = 'party', 0, None, None, False
        else:
            location, slot, mon = selected(snapshot, {} if state.get('manual') else emu.store.trade_preferences(), state['trade_key'])
            from .timecapsule import compatible
            incompatible = next((i for i, member in enumerate(snapshot.party) if not compatible(member, data)), None)
            needs_storage = location != 'party' or state.get('time_capsule') and incompatible is not None
        if location == 'party' and not state.get('time_capsule') and mon is not None:
            from .cable_verification import available_trade_item
            held = {member.species for member in [*snapshot.party, *snapshot.stored] if not member.egg}
            item = available_trade_item(data, mon.species, mon.held_item, dict(snapshot.items),
                                        replace_held=state.get('replace_held', False), held_species=held)
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
            if stranded(snapshot.party, incompatible):
                # The game refuses to deposit the last Pokémon that can battle, and the PC would
                # open and close forever. A nurse revives the fainted ones first.
                self.reviving = True
                return self.heal(snapshot, mem)
            if snapshot.box_counts[snapshot.active_box] >= 20:
                self.menu = self.make_room(snapshot)
            else:
                self.menu = Storage('DEPOSIT', incompatible, len(snapshot.party))
        elif len(snapshot.party) == 6:
            if snapshot.box_counts[snapshot.active_box] >= 20:
                self.menu = self.make_room(snapshot)
            else:
                candidates = reserves(snapshot.party)
                if not candidates and state.get('manual'):
                    # A manual trade may send any reserve except the lead to the PC.
                    candidates = list(range(1, len(snapshot.party)))
                if not candidates:
                    raise ValueError('The party has no safe reserve to deposit for this exchange')
                if all(stranded(snapshot.party, i) for i in candidates):
                    self.reviving = True
                    return self.heal(snapshot, mem)
                candidates = [i for i in candidates if not stranded(snapshot.party, i)]
                # An egg only hatches in the party, so it goes to the PC last, after any other egg if it was
                # brought out to hatch.
                from .breeding import carried
                self.menu = Storage('DEPOSIT', min(candidates, key=lambda i: (
                    carried(self.emu.policy, snapshot, snapshot.party[i]), snapshot.party[i].egg, snapshot.party[i].level)), 6)
        elif mon.box != snapshot.active_box:
            self.menu = ChangeBox(mon.box)
        else:
            self.menu = Storage('WITHDRAW', slot, len(snapshot.party))
        return Action('a', 8, 32)
