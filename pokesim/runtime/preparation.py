"""Incremental travel and PC work using game inputs before a Cable Club session."""
from __future__ import annotations

import time

from ..policies.base import Action
from ..policies.navigation import Navigator
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
    if not snapshot.valid or not snapshot.started or snapshot.in_battle or snapshot.textbox or snapshot.start_menu:
        raise ValueError('Wait for an overworld safe point')
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
    emu.store.set(KEY, state)
    emu.preparation = Preparation(emu, state)
    emu.input_epoch += 1
    return state


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
        self.last_frame = emu.frame
        self.persist_frame = emu.frame
        self.last_progress = emu.frame
        self.signature = None
        self.operation = None
        self.target_box = None
        self.deposit_key = None
        self.invalid_since = None

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
            raise ValueError('No supported walking route to the Cable Club is available yet')
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
        signature = (snap.map, snap.x, snap.y, kind, screen.text, screen.menu_index, screen.scroll)
        if signature != self.signature:
            self.signature = signature
            self.last_progress = snap.frame
        if snap.frame - self.last_progress > 3600:
            raise ValueError('Cable Club preparation stopped making progress')
        if snap.frame - self.persist_frame > 300:
            self._save()
        if not snap.valid:
            self.invalid_since = self.invalid_since or snap.frame
            if snap.frame - self.invalid_since > 180:
                raise ValueError('The game state remained invalid during preparation')
            return [Action(None, 0, 12)]
        self.invalid_since = None
        if snap.in_battle:
            return list(self.emu.policy.step(ctx))
        location, index, mon = selection(snap, self.emu.store.trade_preferences(), self.state['trade_key'])
        pos = (snap.map, snap.x, snap.y)
        if location == 'party':
            self._phase('rendezvous')
            if kind != 'overworld' or snap.textbox or snap.start_menu:
                return [Action('b', 6, 18)]
            if pos != RENDEZVOUS:
                return self._walk(ctx, (RENDEZVOUS,))
            if ctx.mem[0xD12B] != 0:
                raise ValueError('The game is already in an incompatible link state')
            self.state['party_slot'] = index
            self.emu._trade('prepare', self.state['id'])
            self.state['phase'] = 'ready'
            self._save()
            self.emu.preparation = None
            return []
        if pos[0] != CENTER:
            self._phase('travelling')
            if kind != 'overworld':
                return [Action('b', 6, 18)]
            return self._walk(ctx, (PC,))
        self._phase('storage')
        self.target_box = mon['box']
        if len(snap.party) >= 6:
            if snap.box_full:
                raise ValueError('The active PC box needs a free slot before preparing this trade')
            candidate = reserve_to_deposit(snap)
            party = live_status(snap.to_dict())['party']
            if candidate is None:
                raise ValueError('No safe reserve can leave the party for this trade')
            candidate_key = identity(party[candidate])
            if not candidate_key or self.emu.store.trade_preferences().get(candidate_key, {}).get('state') in {'locked', 'offered'}:
                raise ValueError('The reserve needed for this trade is protected')
            self.deposit_key = candidate_key
        if kind == 'overworld':
            if pos != PC:
                return self._walk(ctx, (PC,))
            if ctx.mem[0xC109] != 4:
                return [Action('up', 4, 8)]
            return [Action('a', 6, 18)]
        if kind == 'pc_root':
            return self._select(screen, 0)
        if kind == 'change_box':
            return self._select(screen, self.target_box)
        if kind == 'yes_no':
            if 'GONE FOREVER' in screen.text or 'RELEASED' in screen.text:
                raise ValueError('Unexpected destructive PC menu during preparation')
            return self._select(screen, 0)
        if kind == 'pc':
            if screen.cursor and screen.cursor[0] == 10:
                return self._select(screen, 0)
            if len(snap.party) >= 6:
                self.operation = 'deposit'
                return self._select(screen, 1)
            if snap.active_box != self.target_box:
                self.operation = 'change_box'
                return self._select(screen, 3)
            self.operation = 'withdraw'
            return self._select(screen, 0)
        if kind in {'list', 'party'}:
            if self.operation == 'withdraw':
                return self._select(screen, index, scroll=True)
            if self.operation == 'deposit':
                party = live_status(snap.to_dict())['party']
                slots = [i for i, partner in enumerate(party) if identity(partner) == self.deposit_key]
                if len(slots) != 1 or len(snap.party) < 6:
                    return [Action('b', 6, 18)]
                if self.emu.store.trade_preferences().get(self.deposit_key, {}).get('state') in {'locked', 'offered'}:
                    raise ValueError('The reserve became protected during preparation')
                return self._select(screen, slots[0], scroll=True)
            return [Action('b', 6, 18)]
        if kind == 'dialogue':
            return [Action('a', 6, 24)]
        return [Action('b', 6, 18)]
