"""Trade requests: automatic trades that wait for the owner to approve them.

With Ask me first on, automatic trading suggests its best exchanges here instead of
starting them. Accepting one queues it like a trade picked by hand. Dismissing one keeps
that pair from being suggested again for a while. A request expires as soon as either
Pokémon stops being available for automatic trading.

Not wired into the app in 0.5.0: automatic trades always start on their own. No route reads
or answers requests, the coordinator never builds TradeRequests, and the stored
'trade_requests' value and the Ask me first switch in 'trade_auto_library' are ignored.
To bring it back, build TradeRequests as coordinator.requests, call review() from
Coordinator.schedule_once where it picks the best candidate, return ask_first from adventure_status,
and restore the trade-requests routes, the Ask me first switch and the suggested-trade
cards from the commit that removed them (git log -S trade-requests -- pokesim/app/manager.py).
"""
from __future__ import annotations

import threading
import time

from . import trade_settings
from .registry import identifier, validate_id
from ..individual import find

KEY = 'trade_requests'
MAX_PENDING = 3
DISMISS_SECONDS = 7 * 86400
KEEP_FINISHED = 30
PENDING = 'pending'
WAITING = 'A suggested trade is waiting for you on the Trading page.'
IDLE = 'Your adventures are playing. They will suggest a trade when a useful exchange is ready.'


def _pair(left_id, left_key, right_id, right_key):
    """One name for a pair of Pokémon, whichever side it is read from."""
    return '|'.join(sorted([f'{left_id}:{left_key}', f'{right_id}:{right_key}']))


def _sides(row):
    return {(row['left_id'], row['left_key']), (row['right_id'], row['right_key'])}


class TradeRequests:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.guard = threading.Lock()

    @property
    def registry(self):
        return self.coordinator.registry

    def ask_first(self):
        return trade_settings.ask_first(self.registry)

    # Storage

    def _load(self):
        value = self.registry.setting(KEY, {})
        value = value if isinstance(value, dict) else {}
        now = time.time()
        dismissed = {pair: until for pair, until in (value.get('dismissed') or {}).items()
                     if isinstance(until, (int, float)) and until > now}
        return {'requests': [row for row in value.get('requests') or [] if isinstance(row, dict)],
                'dismissed': dismissed}

    def _save(self, state):
        finished = [row['id'] for row in state['requests'] if row['status'] != PENDING]
        dropped = set(finished[:-KEEP_FINISHED]) if len(finished) > KEEP_FINISHED else set()
        state['requests'] = [row for row in state['requests'] if row['id'] not in dropped]
        self.registry.set_setting(KEY, state)

    @staticmethod
    def _close(row, status, reason=None, **fields):
        row.update(status=status, status_reason=reason, updated_at=time.time(), **fields)
        return row

    # Scheduling

    def review(self, candidates, readable, inventories, settings, reserved, wishes):
        """Expire requests that went stale, then suggest the best new pairs up to the limit.

        readable holds every adventure read this round, before the cooldown, so a game that
        only waits out its cooldown keeps its requests. inventories holds those that may trade now.
        """
        now = time.time()
        with self.guard:
            state = self._load()
            pending = [row for row in state['requests'] if row['status'] == PENDING]
            for row in pending:
                reason = self._stale(row, readable, settings, reserved)
                if reason:
                    self._close(row, 'expired', reason)
            pending = [row for row in pending if row['status'] == PENDING]
            busy = set().union(*(_sides(row) for row in pending)) if pending else set()
            for rank, left_id, right_id, left_key, right_key in sorted(candidates, key=lambda item: item[0], reverse=True):
                if len(pending) >= MAX_PENDING:
                    break
                sides = {(left_id, left_key), (right_id, right_key)}
                if sides & busy or _pair(left_id, left_key, right_id, right_key) in state['dismissed']:
                    continue
                row = self._suggest(left_id, right_id, left_key, right_key, inventories, wishes, now)
                if row is None:
                    continue
                state['requests'].append(row)
                pending.append(row)
                busy |= sides
            self._save(state)
        self.coordinator.last_message = WAITING if pending else IDLE
        return None

    def _stale(self, row, readable, settings, reserved):
        """Why a pending request can no longer go ahead, or '' while it still can."""
        for side in ('left', 'right'):
            aid, key = row[side + '_id'], row[side + '_key']
            try:
                game = self.registry.adventure(aid)
            except KeyError:
                return 'An adventure in this trade was deleted'
            if game['archived']:
                return f'{game["name"]} was archived'
            if aid not in readable:
                # A stopped or busy game was not read this round, which says nothing about its Pokémon.
                continue
            name = (row.get(side) or {}).get('nickname') or (row.get(side) or {}).get('name') or 'A Pokémon'
            if not settings.get(aid, {}).get('enabled', True):
                return f'Automatic trading was turned off for {game["name"]}'
            _, eligible = self.coordinator._auto_offers(aid, readable[aid], reserved)
            mon = find(eligible.get('offers') or [], key)
            if mon is None:
                return f'{name} is no longer available for automatic trading in {game["name"]}'
            if (row.get(side) or {}).get('dex') not in (None, mon.get('dex')):
                return f'{name} evolved in {game["name"]}'
        return ''

    def _suggest(self, left_id, right_id, left_key, right_key, inventories, wishes, now):
        left, right = inventories.get(left_id), inventories.get(right_id)
        if left is None or right is None:
            return None
        give, take = find(left.get('offers') or [], left_key), find(right.get('offers') or [], right_key)
        if give is None or take is None:
            return None
        coordinator = self.coordinator
        give, take = coordinator._offer_for(give, right), coordinator._offer_for(take, left)
        names = {aid: self.registry.adventure(aid)['name'] for aid in (left_id, right_id)}
        left_display, right_display = coordinator._mon_display(give) or {}, coordinator._mon_display(take) or {}
        # Each game's reason names what it gets, so the owner sees why both sides gain.
        reasons = [self._why(names[left_id], left, take, right_display, wishes.get(left_id, set())),
                   self._why(names[right_id], right, give, left_display, wishes.get(right_id, set()))]
        preferred = [display for mon, display in ((give, left_display), (take, right_display))
                     if mon.get('trade_preference') == 'offered']
        for display in preferred:
            reasons.append(f'{display.get("nickname") or display.get("name") or "A Pokémon"} is set to Prefer to trade')
        return {'id': identifier(), 'left_id': left_id, 'left_key': left_key, 'right_id': right_id,
                'right_key': right_key, 'left': left_display, 'right': right_display,
                'reasons': [reason for reason in reasons if reason], 'status': PENDING, 'status_reason': None,
                'manual_id': None, 'created_at': now, 'updated_at': now}

    def _why(self, game, inventory, incoming, display, wished):
        species = display.get('name') or 'this Pokémon'
        dex = incoming.get('arrived_dex', incoming.get('dex'))
        if dex in wished:
            return f'{game} wished for {species}'
        benefit = self.coordinator._benefit(inventory, incoming)
        if benefit >= 100:
            return f'New Pokédex entry for {game}: {species}'
        if benefit >= 20:
            return f'{game} has no {species} right now'
        if benefit >= 10:
            return f'A higher level {species} for {game}'
        if benefit >= 5:
            return f'A {species} with better stats for {game}'
        return ''

    def clear(self, reason='Ask me first was turned off'):
        """Expire every pending request, for example when automatic trades no longer ask."""
        with self.guard:
            state = self._load()
            for row in state['requests']:
                if row['status'] == PENDING:
                    self._close(row, 'expired', reason)
            self._save(state)

    # Owner actions

    def _pending(self, state, rid):
        row = next((row for row in state['requests'] if row['id'] == rid), None)
        if row is None:
            raise KeyError('This suggested trade is no longer available')
        if row['status'] != PENDING:
            raise ValueError(f'This suggested trade is already {row["status"]}')
        return row

    def _check(self, row):
        """Read both Pokémon again. A request whose Pokémon left automatic trading expires."""
        coordinator = self.coordinator
        reserved = coordinator.hand_picked_keys()
        readable, settings = {}, {}
        for aid in (row['left_id'], row['right_id']):
            game = self.registry.adventure(aid)
            reason = coordinator.manual_game_reason(game)
            if reason:
                raise ValueError(f'{game["name"]}: {reason}')
            try:
                readable[aid] = coordinator.inventory(aid)
            except (RuntimeError, OSError) as error:
                raise ValueError(f'{game["name"]} did not answer. Try again in a moment') from error
            settings[aid] = {'enabled': True}
        return self._stale(row, readable, settings, reserved)

    def accept(self, rid):
        validate_id(rid)
        with self.guard:
            state = self._load()
            row = self._pending(state, rid)
            reason = self._check(row)
            if reason:
                self._close(row, 'expired', reason)
                self._save(state)
                return self.public(row)
            entry = self.coordinator.enqueue_manual({'left_id': row['left_id'], 'left_key': row['left_key'],
                                                     'right_id': row['right_id'], 'right_key': row['right_key'],
                                                     'request_id': identifier()})
            self._close(row, 'accepted', manual_id=entry['id'])
            self._save(state)
        return self.public(row)

    def dismiss(self, rid):
        validate_id(rid)
        with self.guard:
            state = self._load()
            row = self._pending(state, rid)
            self._close(row, 'dismissed')
            pair = _pair(row['left_id'], row['left_key'], row['right_id'], row['right_key'])
            state['dismissed'][pair] = time.time() + DISMISS_SECONDS
            self._save(state)
        return self.public(row)

    # Status

    def public(self, row, games=None):
        if games is None:
            games = {game['id']: game for game in self.registry.adventures()}

        def side(prefix):
            aid = row[prefix + '_id']
            display = row.get(prefix) or {}
            dex = display.get('dex')
            game = games.get(aid) or {}
            return {**display, 'adventure_id': aid, 'adventure_name': game.get('name') or 'A deleted adventure',
                    'version': game.get('version'), 'key': row[prefix + '_key'],
                    'sprite_url': f'/games/{aid}/sprites/{dex}.png?v=rom-portraits-1'
                    if type(dex) is int and 1 <= dex <= 251 else None}
        return {'id': row['id'], 'status': row['status'], 'reason': row.get('status_reason'),
                'reasons': list(row.get('reasons') or []), 'created_at': row['created_at'],
                'updated_at': row['updated_at'], 'manual_id': row.get('manual_id'),
                'left': side('left'), 'right': side('right')}

    def for_adventure(self, aid=None):
        """Pending requests, those of one adventure when aid is given, with that adventure first."""
        if aid is not None:
            validate_id(aid)
            self.registry.adventure(aid)
        games = {game['id']: game for game in self.registry.adventures()}
        rows = [row for row in self._load()['requests'] if row['status'] == PENDING
                and (aid is None or aid in (row['left_id'], row['right_id']))]
        result = []
        for row in rows:
            public = self.public(row, games)
            if aid is not None and public['right']['adventure_id'] == aid:
                public['left'], public['right'] = public['right'], public['left']
            result.append(public)
        return {'ask_first': self.ask_first(), 'requests': result}
