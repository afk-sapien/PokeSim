"""Incremental travel and PC work using game inputs before a Cable Club session."""
from __future__ import annotations

import time

from ..policies.base import Action
from ..interactions.centers import CENTERS
from ..policies.navigation import Navigator
from ..policies.collection import LEAGUE
from ..policies.team import reserve_to_deposit
from ..ram import read_snapshot
from ..screen import Screen
from ..trade.preferences import identity
from ..web.pokedex import live_status

KEY = 'interaction_preparation'
ACTIVE = {'travelling', 'storage', 'rendezvous'}
CENTER = 89
RENDEZVOUS = (CENTER, 11, 3)
PC = (CENTER, 13, 4)


def selection(snapshot, preferences, key):
    payload = live_status(snapshot.to_dict())
    party = payload['party']
    stored = (payload.get('storage') or {}).get('pokemon', [])
    matches = [('party', i, mon) for i, mon in enumerate(party) if identity(mon) == key]
    matches += [('box', mon['position'] - 1, {**mon, 'box': mon['box'] - 1})
                for mon in stored if identity(mon) == key]
    if len(matches) != 1:
        raise ValueError('The selected Pokémon cannot be identified uniquely')
    if preferences.get(key, {}).get('state') in {'locked', 'withdrawn'}:
        raise ValueError('The selected Pokémon is protected or withdrawn')
    return matches[0]


def begin(emu, trade_key, transaction_id, max_frames=108000):
    previous = emu.store.get(KEY)
    if previous and previous.get('id') == transaction_id:
        if previous.get('trade_key') != trade_key:
            raise ValueError('The preparation ID already names another Pokémon')
        return previous
    if emu.store.get('trade_hold') or previous and previous.get('phase') in ACTIVE:
        raise ValueError('Another interaction has reserved this adventure')
    if emu.paused or emu.manual_mode:
        raise ValueError('Resume autonomous play before preparing a trade')
    snapshot = read_snapshot(emu.pb.memory, emu.frame)
    if not snapshot.valid or not snapshot.started:
        raise ValueError('Wait for a valid started adventure')
    if not isinstance(trade_key, str) or len(trade_key) != 24:
        raise ValueError('Choose an identifiable Pokémon')
    location, _, _ = selection(snapshot, emu.store.trade_preferences(), trade_key)
    if location != 'box':
        raise ValueError('Choose a boxed spare. Active party members are protected')
    if type(max_frames) is not int or not 60 <= max_frames <= 216000:
        raise ValueError('Invalid preparation frame budget')
    state = {'id': transaction_id, 'trade_key': trade_key, 'phase': 'travelling',
             'started_at': time.time(), 'deadline': time.time() + 1800,
             'elapsed_frames': 0, 'max_frames': max_frames, 'party_slot': None, 'selected_key': trade_key}
    if not overworld_ready(snapshot, Screen(emu.pb.memory).kind(snapshot)):
        state.update(waiting_for='overworld',
                     waiting_reason=('Finishing the League run before travelling to the Cable Club'
                                     if snapshot.map in LEAGUE else
                                     'Finishing the current battle or menu before travelling to the Cable Club'))
    emu.store.set(KEY, state)
    emu.preparation = Preparation(emu, state)
    if not state.get('waiting_for'):
        emu.input_epoch += 1
    return state


def overworld_ready(snapshot, kind):
    return (snapshot.valid and snapshot.started and not snapshot.in_battle
            and snapshot.map not in LEAGUE and not snapshot.textbox
            and not snapshot.start_menu and kind == 'overworld')


def restore(emu):
    state = emu.store.get(KEY)
    if state and state.get('phase') in ACTIVE and not emu.store.get('trade_hold'):
        emu.paused = True
        emu.preparation = None


def cancel(emu, transaction_id):
    state = emu.store.get(KEY)
    if not state or state.get('id') != transaction_id:
        raise ValueError('Unknown preparation')
    if emu.store.get('trade_hold'):
        raise ValueError('Abort the prepared interaction through its coordinator')
    if state['phase'] in ACTIVE:
        state = {**state, 'phase': 'cancelled'}
        emu.store.set(KEY, state)
        emu.preparation = None
        emu.input_epoch += 1
        emu.policy.on_restore()
        emu.paused = False
    return state


class Preparation:
    def __init__(self, emu, state):
        self.emu = emu
        self.state = dict(state)
        self.nav = Navigator()
        from ..policies.travel import TravelPolicy
        self.traveller = TravelPolicy(tuple(center['pc'] for center in CENTERS.values()))
        self.traveller.trade_preferences = emu.store.trade_preferences
        self.last_frame = emu.frame
        self.persist_frame = emu.frame
        self.last_progress = emu.frame
        self.signature = None
        self.operation = None
        self.target_box = None
        self.deposit_key = None
        self.invalid_since = None
        self.selection_wait_since = None
        self.walk_wait_since = None
        self.storage_cleanup = None

    def _save(self):
        self.emu.store.set(KEY, self.state)
        self.persist_frame = self.emu.frame

    def _phase(self, phase):
        if phase != self.state['phase']:
            self.state['phase'] = phase
            self._save()

    def _fail(self, error):
        self.state.update(phase='failed', error=str(error))
        self._save()
        self.emu.preparation = None
        self.emu.input_epoch += 1
        self.emu.policy.on_restore()
        return [Action(None, 0, 12)]

    @staticmethod
    def _select(screen, index, scroll=False):
        current = screen.menu_index + (screen.scroll if scroll else 0)
        return [Action('a' if current == index else 'down' if current < index else 'up', 6, 12)]

    def _walk(self, ctx, targets):
        snap = ctx.snapshot
        pos = (snap.map, snap.x, snap.y)
        moving = bool(ctx.mem[0xCFC5])
        self.nav.observe(pos, snap.frame, moving, interrupted=bool(snap.in_battle or snap.textbox or snap.start_menu))
        if moving:
            return [Action(None, 0, 4)]
        self.nav.update_story(snap)
        # This controller handles walking and PC menus. Avoid choosing a water
        # or Cut shortcut until field-move choreography is supported here.
        self.nav.can_surf = False
        self.nav.can_cut = False
        self.nav.update_live(snap, ctx.mem)
        direction = self.nav.route(pos, targets, snap.frame)
        if direction is None:
            if self.walk_wait_since is None:
                self.walk_wait_since = snap.frame
            if snap.frame - self.walk_wait_since < 600:
                return [Action(None, 0, 12)]
            raise ValueError(f'No supported walking route to the Cable Club is available yet at {pos}')
        self.walk_wait_since = None
        self.nav.issued(pos, direction, snap.frame)
        return [Action(direction, 8, 12)]

    def step(self, ctx):
        try:
            return self._step(ctx)
        except ValueError as error:
            return self._fail(error)

    def _step(self, ctx):
        snap = ctx.snapshot
        self.state['elapsed_frames'] += max(0, snap.frame - self.last_frame)
        self.last_frame = snap.frame
        if self.state['elapsed_frames'] > self.state['max_frames'] or time.time() > self.state['deadline']:
            raise ValueError('Cable Club preparation exceeded its travel deadline')
        screen = Screen(ctx.mem)
        kind = screen.kind(snap)
        signature = (snap.map, snap.x, snap.y, kind, screen.text, screen.menu_index, screen.scroll,
                     snap.in_battle, tuple((mon.hp, mon.status, mon.pp) for mon in snap.party))
        if signature != self.signature:
            self.signature = signature
            self.last_progress = snap.frame
        if not self.state.get('waiting_for') and snap.frame - self.last_progress > 3600:
            raise ValueError('Cable Club preparation stopped making progress')
        if snap.frame - self.persist_frame > 300:
            self._save()
        if not snap.valid:
            self.invalid_since = self.invalid_since or snap.frame
            if snap.frame - self.invalid_since > 180:
                raise ValueError('The game state remained invalid during preparation')
            return [Action(None, 0, 12)]
        self.invalid_since = None
        if self.state.get('waiting_for'):
            location, _, _ = selection(snap, self.emu.store.trade_preferences(), self.state['trade_key'])
            if location != 'box':
                raise ValueError('The selected boxed spare moved before Cable Club preparation began')
            if not overworld_ready(snap, kind):
                return list(self.emu.policy.step(ctx))
            self.state.pop('waiting_for')
            self.state.pop('waiting_reason', None)
            self.last_progress = snap.frame
            self._save()
        if snap.in_battle:
            return list(self.traveller.step(ctx))
        try:
            location, index, mon = selection(snap, self.emu.store.trade_preferences(), self.state['trade_key'])
        except ValueError as error:
            # Cartridge PC transfers update party and box records on different frames.
            # Let an in-flight operation settle without sending another menu input.
            if (str(error) != 'The selected Pokémon cannot be identified uniquely'
                    or self.operation not in {'deposit', 'withdraw', 'change_box'}
                    or snap.map not in CENTERS or kind == 'overworld'):
                raise
            if self.selection_wait_since is None:
                self.selection_wait_since = snap.frame
            if snap.frame - self.selection_wait_since >= 180:
                raise
            return [Action(None, 0, 12)]
        self.selection_wait_since = None
        pos = (snap.map, snap.x, snap.y)
        if location == 'party':
            self._phase('rendezvous')
            if kind != 'overworld' or snap.textbox or snap.start_menu:
                return [Action('b', 6, 18)]
            if snap.map not in CENTERS:
                raise ValueError('The prepared partner left its Cable Club center')
            rendezvous = CENTERS[snap.map]['rendezvous']
            if pos != rendezvous:
                return self._walk(ctx, (rendezvous,))
            if ctx.mem[0xD12B] != 0:
                raise ValueError('The game is already in an incompatible link state')
            self.state['party_slot'] = index
            self.emu._trade('prepare', self.state['id'])
            self.state['phase'] = 'ready'
            self._save()
            self.emu.preparation = None
            return []
        if pos[0] not in CENTERS:
            self._phase('travelling')
            return list(self.traveller.step(ctx))
        self._phase('storage')
        if len(snap.party) >= 6:
            self._storage_reserve(snap)
        cleanup = self._storage_make_room(ctx, screen, kind)
        if cleanup is not None:
            return cleanup
        self.target_box = mon['box']
        if len(snap.party) >= 6:
            if snap.box_full:
                self.target_box = snap.next_free_box
                if self.target_box is None:
                    raise ValueError('Every PC box is full. A free slot is needed to prepare this trade')
            else:
                self.target_box = snap.active_box
        if kind == 'overworld':
            pc = CENTERS[snap.map]['pc']
            if pos != pc:
                return self._walk(ctx, (pc,))
            if ctx.mem[0xC109] != 4:
                return [Action('up', 4, 8)]
            return [Action('a', 6, 18)]
        if kind == 'pc_root':
            return self._select(screen, 0)
        if kind == 'change_box':
            if self.operation != 'change_box':
                return [Action('b', 6, 18)]
            if snap.active_box == self.target_box:
                return [Action(None, 0, 12)]
            return self._select(screen, self.target_box)
        if kind == 'yes_no':
            if 'GONE FOREVER' in screen.text or 'RELEASED' in screen.text:
                raise ValueError('Unexpected destructive PC menu during preparation')
            if self.operation != 'change_box':
                return [Action('b', 6, 18)]
            return self._select(screen, 0)
        if kind == 'pc':
            if screen.cursor and screen.cursor[0] == 10:
                if not self._storage_operation_ready(snap, mon):
                    return [Action('b', 6, 18)]
                return self._select(screen, 0)
            if snap.active_box != self.target_box:
                self.operation = 'change_box'
                return self._select(screen, 3)
            self.operation = 'deposit' if len(snap.party) >= 6 else 'withdraw'
            return self._select(screen, 1 if self.operation == 'deposit' else 0)
        if kind in {'list', 'party'}:
            if not self._storage_operation_ready(snap, mon):
                return [Action('b', 6, 18)]
            if self.operation == 'withdraw':
                return self._select(screen, index, scroll=True)
            if self.operation == 'deposit':
                return self._select(screen, self._storage_reserve(snap), scroll=True)
            return [Action('b', 6, 18)]
        if kind == 'dialogue':
            if self.operation and 'WITHDRAW' in screen.text and 'What' in screen.text:
                return [Action(None, 0, 12)]
            return [Action('a', 6, 24)]
        return [Action('b', 6, 18)]

    def _storage_make_room(self, ctx, screen, kind):
        snap = ctx.snapshot
        full = len(snap.party) >= 6 and snap.box_full and snap.next_free_box is None
        if not full:
            if self.storage_cleanup is not None:
                if kind != 'overworld' or snap.textbox or snap.start_menu:
                    return [Action('b', 6, 18)]
                self.storage_cleanup = None
                self.operation = None
            return None
        if self.storage_cleanup is None:
            from ..policies.strategic import StrategicPolicy
            self.storage_cleanup = StrategicPolicy()
            self.storage_cleanup.trade_preferences = self._storage_preferences
        if self.storage_cleanup._release_target(snap) is None:
            raise ValueError('Every PC box is full and no unprotected spare duplicate can make room for this trade')
        pc = CENTERS[snap.map]['pc']
        if kind == 'overworld':
            if (snap.map, snap.x, snap.y) != pc:
                return self._walk(ctx, (pc,))
            if ctx.mem[0xC109] != 4:
                return [Action('up', 4, 8)]
            return [Action('a', 6, 18)]
        from ..policies.progression import Goal
        self.storage_cleanup.goal = Goal('party_release', 'Make room for the trade',
                                         'Release one unprotected spare duplicate to free a party slot',
                                         (pc,), 'up', True)
        self.storage_cleanup.menu_context = 'pc'
        return list(self.storage_cleanup._dispatch(snap, screen, kind, ctx.mem))

    def _storage_preferences(self):
        preferences = dict(self.emu.store.trade_preferences())
        preferences[self.state['trade_key']] = {'state': 'offered'}
        return preferences

    def _storage_operation_ready(self, snap, offered):
        if self.operation == 'deposit':
            return len(snap.party) >= 6 and not snap.box_full
        if self.operation == 'withdraw':
            return len(snap.party) < 6 and snap.active_box == offered['box']
        return False

    def _storage_reserve(self, snap):
        party = live_status(snap.to_dict())['party']
        keys = [identity(mon) for mon in party]
        preferences = self.emu.store.trade_preferences()
        protected = {'locked', 'offered', 'withdrawn'}
        strongest = max(range(len(snap.party)), key=lambda i: snap.party[i].level)
        safe = [i for i, mon in enumerate(snap.party)
                if i != strongest and keys[i] and keys.count(keys[i]) == 1
                and preferences.get(keys[i], {}).get('state') not in protected
                and not any(move in (15, 19, 57, 70, 148)
                            and not any(move in other.moves for j, other in enumerate(snap.party) if j != i)
                            for move in mon.moves)]
        if self.deposit_key is not None:
            slots = [i for i in safe if keys[i] == self.deposit_key]
            if len(slots) != 1:
                raise ValueError('The reserve needed for this trade moved or became protected')
            return slots[0]
        preferred = reserve_to_deposit(snap)
        candidate = preferred if preferred in safe else min(safe, key=lambda i: snap.party[i].level, default=None)
        if candidate is None:
            raise ValueError('No safe unprotected reserve can leave the party for this trade')
        self.deposit_key = keys[candidate]
        return candidate
