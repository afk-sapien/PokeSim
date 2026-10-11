"""Trade offers: one adventure asks another for a Pokémon in exchange for one of its own.

Not wired into the app in 0.5.0: trading is automatic or built by hand in the trade
builder, so no route creates or answers offers and stored offers are ignored. The code is
kept so offers can come back later: build TradeOffers on the manager and restore its routes
and the Offers tab from the commit that removed them
(git log -S trade-offers -- pokesim/app/manager.py).

An offer waits until the other adventure accepts, declines or the sender withdraws it.
Accepting checks both Pokémon again and queues a manual trade, so only hard cable limits
can stop it. Offers live in the library registry and survive restarts.
"""
from __future__ import annotations

import threading
import time

from .registry import identifier, validate_id
from .trade_builder import FIELDS, Gone, HardLimit, TradeBuilder, ViewOnlyError

PENDING, ACCEPTED = 'pending', 'accepted'
OPEN = (PENDING, ACCEPTED)
STATUSES = ('pending', 'accepted', 'declined', 'withdrawn', 'expired', 'failed', 'completed')
EXPIRE_SECONDS = 7 * 86400
KEEP_FINISHED = 200
MAX_PENDING = 25
SHOW_FINISHED = 20


class TradeOffers(TradeBuilder):
    # One library owner controls every adventure that is not view-only, so an offer to such
    # an adventure has nobody else to ask and starts at once.
    auto_accept = True

    def __init__(self, manager):
        super().__init__(manager)
        self.guard = threading.Lock()

    # Lifecycle

    def create(self, data):
        if not isinstance(data, dict) or not set(FIELDS) <= set(data) or set(data) - set(FIELDS) - {'request_id'}:
            raise ValueError('Choose a Pokémon to offer and one to ask for')
        selection = {name: data[name] for name in FIELDS}
        for name in ('from_id', 'to_id'):
            validate_id(selection[name])
        for name in ('from_key', 'to_key'):
            if not isinstance(selection[name], str) or not 1 <= len(selection[name]) <= 256:
                raise ValueError('Choose a Pokémon on each side')
        if selection['from_id'] == selection['to_id']:
            raise ValueError('Choose another adventure to trade with')
        oid = validate_id(data.get('request_id') or identifier())
        self.registry.adventure(selection['from_id'])
        self.registry.adventure(selection['to_id'])
        self._writer(selection['from_id'])
        try:
            existing = self.registry.trade_offer(oid)
        except KeyError:
            existing = None
        if existing:
            if any(existing[name] != value for name, value in selection.items()):
                raise ValueError('This request ID already belongs to another offer')
            return self.public(existing)
        give, take = self._check(selection)
        with self.guard:
            pending = self.registry.trade_offers(selection['from_id'], statuses=[PENDING])
            if any(all(row[name] == value for name, value in selection.items()) for row in pending):
                raise ValueError('You already offered this trade')
            if sum(row['from_id'] == selection['from_id'] for row in pending) >= MAX_PENDING:
                raise ValueError(f'This adventure already has {MAX_PENDING} offers waiting. Withdraw one first')
            row = self.registry.create_trade_offer({'id': oid, **selection,
                                                    'display': {'from': self._snapshot(give), 'to': self._snapshot(take)}})
        if self.auto_accept and not self.viewer_only(selection['to_id']):
            # The owner controls both adventures, so there is nobody else to ask: the trade
            # starts now. When it cannot start yet, the offer simply waits like any other.
            try:
                return self.accept(oid)
            except (ValueError, ViewOnlyError):
                row = self.registry.trade_offer(oid)
        return self.public(row)

    def accept(self, oid):
        offer = self.registry.trade_offer(validate_id(oid))
        self._writer(offer['to_id'])
        with self.guard:
            offer = self._settle(self.registry.trade_offer(oid))
            if offer['status'] != PENDING:
                raise ValueError(f'This offer is already {offer["status"]}')
            busy = [row for row in self.registry.trade_offers(statuses=[ACCEPTED])
                    if {(row['from_id'], row['from_key']), (row['to_id'], row['to_key'])}
                    & {(offer['from_id'], offer['from_key']), (offer['to_id'], offer['to_key'])}]
            if busy:
                raise ValueError('One of these Pokémon is already in another accepted trade. Try again when it finishes')
            try:
                self._check(offer, accepting=True)
            except Gone as error:
                return self.public(self.registry.update_trade_offer(oid, status='expired', reason=str(error)))
            except HardLimit as error:
                return self.public(self.registry.update_trade_offer(oid, status='failed', reason=str(error)))
            entry = self.coordinator.enqueue_manual({'left_id': offer['from_id'], 'left_key': offer['from_key'],
                                                     'right_id': offer['to_id'], 'right_key': offer['to_key'],
                                                     'request_id': identifier()})
            row = self.registry.update_trade_offer(oid, expect=(PENDING,), status=ACCEPTED, reason=None,
                                                   manual_id=entry['id'])
        return self.public(row or self.registry.trade_offer(oid))

    def _answer(self, oid, actor, status):
        offer = self.registry.trade_offer(validate_id(oid))
        self._writer(offer[actor])
        with self.guard:
            row = self.registry.update_trade_offer(oid, expect=(PENDING,), status=status, reason=None)
        if row is None:
            raise ValueError(f'This offer is already {self.registry.trade_offer(oid)["status"]}')
        return self.public(row)

    def decline(self, oid):
        return self._answer(oid, 'to_id', 'declined')

    def withdraw(self, oid):
        return self._answer(oid, 'from_id', 'withdrawn')

    # Status

    def _manual_result(self, mid):
        """The finished status of an accepted offer's manual trade, or None while it runs."""
        try:
            trade = self.coordinator.manual_status(mid)
        except KeyError:
            try:
                row = self.registry.transaction(mid)
            except KeyError:
                return 'failed', 'The queued trade record is no longer available'
            trade = {'state': 'started', 'phase': row['phase'], 'decision': row['decision'],
                     'failure_reason': self.coordinator._failure_reason(row) if row['phase'] == 'aborted' else None}
        if trade['state'] == 'rejected':
            return 'failed', trade.get('error') or 'The trade could not start'
        if trade['state'] == 'cancelled':
            return 'failed', 'The trade was cancelled before it started'
        if trade.get('phase') == 'completed' and trade.get('decision') == 'COMMIT':
            return 'completed', None
        if trade.get('phase') == 'aborted':
            return 'failed', trade.get('failure_reason') or 'The trade did not complete'
        return None

    def _settle(self, offer, now=None):
        """Move an open offer on when its time ran out, an adventure left, or its trade finished."""
        now = time.time() if now is None else now
        status, reason = None, None
        if offer['status'] == PENDING:
            for aid in (offer['from_id'], offer['to_id']):
                try:
                    game = self.registry.adventure(aid)
                except KeyError:
                    status, reason = 'expired', 'An adventure in this offer was deleted'
                    break
                if game['archived']:
                    status, reason = 'expired', f'{game["name"]} was archived'
                    break
            if status is None and now - offer['created_at'] > EXPIRE_SECONDS:
                status, reason = 'expired', f'No answer within {EXPIRE_SECONDS // 86400} days'
        elif offer['status'] == ACCEPTED and offer['manual_id']:
            result = self._manual_result(offer['manual_id'])
            if result:
                status, reason = result
        if status is None:
            return offer
        return self.registry.update_trade_offer(offer['id'], expect=(offer['status'],), status=status,
                                                reason=reason) or self.registry.trade_offer(offer['id'])

    def refresh(self):
        for offer in self.registry.trade_offers(statuses=OPEN):
            self._settle(offer)
        self.registry.prune_trade_offers(KEEP_FINISHED)

    def public(self, offer, games=None):
        if games is None:
            games = {game['id']: game for game in self.registry.adventures()}
        display = offer.get('display') or {}
        def side(prefix):
            game = games.get(offer[prefix + '_id']) or {}
            return {**self._side(offer[prefix + '_id'], game.get('name') or 'A deleted adventure', game.get('version'),
                                 display.get(prefix) or {}), 'key': offer[prefix + '_key']}
        trade = None
        if offer['manual_id']:
            try:
                trade = self.coordinator.manual_status(offer['manual_id'])
            except KeyError:
                trade = None
        return {'id': offer['id'], 'status': offer['status'], 'reason': offer['reason'],
                'created_at': offer['created_at'], 'updated_at': offer['updated_at'],
                'expires_at': offer['created_at'] + EXPIRE_SECONDS if offer['status'] == PENDING else None,
                'from': side('from'), 'to': side('to'), 'manual_id': offer['manual_id'], 'trade': trade}

    def status(self, oid):
        return self.public(self._settle(self.registry.trade_offer(validate_id(oid))))

    def for_adventure(self, aid):
        """Offers this adventure received and sent: every open one and the latest finished ones."""
        validate_id(aid)
        self.registry.adventure(aid)
        self.refresh()
        games = {game['id']: game for game in self.registry.adventures()}
        offers = self.registry.trade_offers(aid)

        def pick(direction):
            rows = [row for row in offers if row[direction] == aid]
            shown = [row for row in rows if row['status'] in OPEN]
            shown += [row for row in rows if row['status'] not in OPEN][:SHOW_FINISHED]
            return [self.public(row, games) for row in shown]
        return {'adventure_id': aid, 'incoming': pick('to_id'), 'outgoing': pick('from_id'),
                'viewer_only': self.viewer_only(aid)}
