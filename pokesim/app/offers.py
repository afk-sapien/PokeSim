"""Trade offers: one adventure asks another for a trade, across owners.

An offer names the sender's adventure and Pokémon, the receiver's adventure and, when the
sender has one in mind, the Pokémon it would like. It waits until the receiver accepts,
declines or the sender cancels it, and expires after 24 hours. Accepting checks both
Pokémon again and queues a manual trade. An accepted offer whose trade has not started
within 6 hours expires and its trade leaves the line. Offers live in the library registry
and survive restarts.

An adventure takes offers from other people only when its owner turns on Open to offers.
A Pokémon automatic trading would never give away, such as a protected species or a
field-move partner, can be offered or given only by its owner, even when a manager sends
or accepts the offer.
"""
from __future__ import annotations

import logging
import threading
import time

from pokecore.identity import find

from . import inbox
from .policy import adventure_role
from .registry import LIBRARY_OWNER, identifier, validate_id
from .trade_builder import Gone, HardLimit, TradeBuilder, ViewOnlyError

PENDING, ACCEPTED = 'pending', 'accepted'
OPEN = (PENDING, ACCEPTED)
STATUSES = ('pending', 'accepted', 'declined', 'withdrawn', 'expired', 'failed', 'completed')
EXPIRE_SECONDS = 86400
# An accepted offer whose trade is still in line after this long expires.
ACCEPTED_EXPIRE = 6 * 3600
KEEP_FINISHED = 200
SHOW_FINISHED = 20
# Open offers one person may have sent, offers waiting for one owner, and offers one person may send a day.
MAX_PENDING = 20
MAX_INCOMING = 20
DAILY = 50
WAITING = {'queued', 'starting'}
log = logging.getLogger(__name__)


class OwnerOnly(PermissionError):
    """Only the owner of the adventure may trade this Pokémon away."""


class LimitReached(ValueError):
    """Too many offers are open or were sent today."""


class Changed(ValueError):
    """A Pokémon in the offer changed since it was made. The receiver confirms the new one."""

    def __init__(self, message, offer):
        super().__init__(message)
        self.offer = offer


def owner_of(game):
    return game.get('owner_id') or LIBRARY_OWNER


class TradeOffers(TradeBuilder):
    # An offer between two adventures of one owner has nobody else to ask, so it starts at once.
    auto_accept = True

    def __init__(self, manager):
        super().__init__(manager)
        self.guard = threading.Lock()
        self.stop = threading.Event()
        self.clock = time.time

    # Checks

    def _protected(self, aid, key):
        """Whether automatic trading would keep this Pokémon. A game that cannot say keeps it."""
        try:
            inventory = self.coordinator.inventory(aid)
        except Exception:
            return True
        return find((inventory or {}).get('offers') or [], key) is None

    def _owner_check(self, actor, aid, key):
        if actor is None or adventure_role(actor, self.registry.adventure(aid)) == 'owner':
            return
        if self._protected(aid, key):
            raise OwnerOnly('Only the owner can trade this Pokémon away')

    def _limits(self, sender_id, to_id):
        now = self.clock()
        if self.registry.count_trade_offers(sender_id=sender_id, statuses=OPEN) >= MAX_PENDING:
            raise LimitReached(f'You already have {MAX_PENDING} offers open. Cancel one first')
        if self.registry.count_trade_offers(sender_id=sender_id, since=now - 86400) >= DAILY:
            raise LimitReached(f'You can send {DAILY} offers a day. Try again tomorrow')
        owner = owner_of(self.registry.adventure(to_id))
        theirs = [game['id'] for game in self.registry.adventures() if owner_of(game) == owner]
        if self.registry.count_trade_offers(to_ids=theirs, statuses=[PENDING]) >= MAX_INCOMING:
            raise LimitReached('This trainer has too many offers waiting. Try again later')

    @staticmethod
    def _changes(display, row):
        """What changed about one Pokémon since its offer was made, or an empty string."""
        if not display:
            return ''
        if display.get('dex') != row.get('dex'):
            return f'{display.get("name") or "The Pokémon"} is now {row.get("name") or "another Pokémon"}'
        if display.get('level') != row.get('level'):
            return f'{row.get("name") or "The Pokémon"} is now level {row.get("level")}'
        return ''

    # Lifecycle

    def create(self, data, actor=None):
        names = ('from_id', 'from_key', 'to_id')
        if not isinstance(data, dict) or not set(names) <= set(data) or set(data) - set(names) - {'to_key', 'request_id'}:
            raise ValueError('Choose a Pokémon to offer and an adventure to offer it to')
        selection = {name: data[name] for name in names}
        selection['to_key'] = data.get('to_key') or ''
        for name in ('from_id', 'to_id'):
            validate_id(selection[name])
        if not isinstance(selection['from_key'], str) or not 1 <= len(selection['from_key']) <= 256:
            raise ValueError('Choose a Pokémon to offer')
        if not isinstance(selection['to_key'], str) or len(selection['to_key']) > 256:
            raise ValueError('Choose a Pokémon to ask for, or none')
        if selection['from_id'] == selection['to_id']:
            raise ValueError('Choose another adventure to trade with')
        oid = validate_id(data.get('request_id') or identifier())
        sender = self.registry.adventure(selection['from_id'])
        receiver = self.registry.adventure(selection['to_id'])
        self._writer(selection['from_id'])
        try:
            existing = self.registry.trade_offer(oid)
        except KeyError:
            existing = None
        if existing:
            if any(existing[name] != value for name, value in selection.items()):
                raise ValueError('This request ID already belongs to another offer')
            return self.public(existing)
        self._owner_check(actor, selection['from_id'], selection['from_key'])
        sender_id = (actor.id if actor is not None else None) or LIBRARY_OWNER
        give, take = self._sides(selection)
        with self.guard:
            pending = self.registry.trade_offers(selection['from_id'], statuses=[PENDING])
            if any(all(row[name] == value for name, value in selection.items()) for row in pending):
                raise ValueError('You already offered this trade')
            self._limits(sender_id, selection['to_id'])
            display = {'from': self._snapshot(give), 'to': self._snapshot(take) if take else {}}
            row = self.registry.create_trade_offer({'id': oid, **selection, 'sender_id': sender_id, 'display': display})
        if (self.auto_accept and selection['to_key'] and owner_of(sender) == owner_of(receiver)
                and not self.viewer_only(selection['to_id'])):
            # When the trade cannot start yet, the offer simply waits like any other.
            try:
                return self.accept(oid, actor)
            except (ValueError, ViewOnlyError, PermissionError):
                row = self.registry.trade_offer(oid)
        inbox.offer_received(self.manager, row, actor)
        return self.public(row)

    def _sides(self, offer, *, accepting=False):
        """Both Pokémon read now, or only the offered one when none was asked for yet."""
        if offer['to_key']:
            return self._check(offer, accepting=accepting)
        sender = self._adventure(offer['from_id'], accepting=accepting)
        receiver = self._adventure(offer['to_id'], accepting=accepting)
        give_inventory, _ = self._inventories(offer['from_id'], offer['to_id'])
        give = self._find(give_inventory, offer['from_key'], sender, (offer.get('display') or {}).get('from'))
        if receiver['archived']:
            raise Gone(f'{receiver["name"]} was archived')
        return give, None

    def accept(self, oid, actor=None, to_key=None, confirm=False):
        offer = self.registry.trade_offer(validate_id(oid))
        self._writer(offer['to_id'])
        if to_key is not None and (not isinstance(to_key, str) or not 1 <= len(to_key) <= 256):
            raise ValueError('Choose a Pokémon to give')
        with self.guard:
            offer = self._settle(self.registry.trade_offer(oid))
            if offer['status'] != PENDING:
                raise ValueError(f'This offer is already {offer["status"]}')
            chosen = to_key or offer['to_key']
            if not chosen:
                raise ValueError('Choose a Pokémon to give in return')
            self._owner_check(actor, offer['to_id'], chosen)
            trade = {**offer, 'to_key': chosen}
            busy = [row for row in self.registry.trade_offers(statuses=[ACCEPTED])
                    if {(row['from_id'], row['from_key']), (row['to_id'], row['to_key'])}
                    & {(trade['from_id'], trade['from_key']), (trade['to_id'], trade['to_key'])}]
            if busy:
                raise ValueError('One of these Pokémon is already in another accepted trade. Try again when it finishes')
            try:
                give, take = self._check(trade, accepting=True)
            except Gone as error:
                return self.public(self._announce(self.registry.update_trade_offer(oid, status='expired', reason=str(error)), actor))
            except HardLimit as error:
                if to_key and to_key != offer['to_key']:
                    raise
                return self.public(self._announce(self.registry.update_trade_offer(oid, status='failed', reason=str(error)), actor))
            display = offer.get('display') or {}
            changes = [text for text in (self._changes(display.get('from'), give),
                                         self._changes(display.get('to') if chosen == offer['to_key'] else None, take))
                       if text]
            if changes and not confirm:
                raise Changed('. '.join(changes) + '. Accept again to trade anyway', self.public(offer))
            entry = self.coordinator.enqueue_manual({'left_id': trade['from_id'], 'left_key': trade['from_key'],
                                                     'right_id': trade['to_id'], 'right_key': chosen,
                                                     'request_id': identifier()})
            row = self.registry.update_trade_offer(oid, expect=(PENDING,), status=ACCEPTED, reason=None,
                                                   manual_id=entry['id'], to_key=chosen,
                                                   display={'from': self._snapshot(give), 'to': self._snapshot(take)})
        return self.public(self._announce(row, actor) or self.registry.trade_offer(oid))

    def _announce(self, row, actor=None):
        """Tell the sender in their inbox that their offer moved on. Returns the row."""
        if row is not None:
            inbox.offer_answered(self.manager, row, actor)
        return row

    def _answer(self, oid, side, status, actor=None):
        offer = self.registry.trade_offer(validate_id(oid))
        self._writer(offer[side])
        with self.guard:
            row = self.registry.update_trade_offer(oid, expect=(PENDING,), status=status, reason=None)
        if row is None:
            raise ValueError(f'This offer is already {self.registry.trade_offer(oid)["status"]}')
        return self.public(self._announce(row, actor) if status == 'declined' else row)

    def decline(self, oid, actor=None):
        return self._answer(oid, 'to_id', 'declined', actor)

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

    def _stale(self, offer, now):
        """Whether an accepted offer's trade waited in line too long. It leaves the line if so."""
        if now - offer['updated_at'] <= ACCEPTED_EXPIRE:
            return False
        try:
            if self.coordinator.manual_status(offer['manual_id'])['state'] not in WAITING:
                return False
            self.coordinator.cancel_queued(offer['manual_id'])
        except (KeyError, ValueError):
            return False
        return True

    def _settle(self, offer, now=None):
        """Move an open offer on when its time ran out, an adventure left, or its trade finished."""
        now = self.clock() if now is None else now
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
                status, reason = 'expired', 'No answer within 24 hours'
        elif offer['status'] == ACCEPTED and offer['manual_id']:
            result = self._manual_result(offer['manual_id'])
            if result:
                status, reason = result
            elif self._stale(offer, now):
                status, reason = 'expired', 'The trade did not start within 6 hours'
        if status is None:
            return offer
        row = self.registry.update_trade_offer(offer['id'], expect=(offer['status'],), status=status, reason=reason)
        # Only the sweep that moved the offer tells the sender. A finished trade reaches both
        # inboxes from the coordinator instead.
        if row is not None and status != 'completed':
            self._announce(row)
        return row or self.registry.trade_offer(offer['id'])

    def refresh(self):
        for offer in self.registry.trade_offers(statuses=OPEN):
            self._settle(offer)
        self.registry.prune_trade_offers(KEEP_FINISHED)

    def run(self, interval=300):
        # The first sweep runs at once, so offers that ran out while the app was stopped free their Pokémon.
        def loop():
            while True:
                try:
                    self.refresh()
                except Exception:
                    log.exception('The trade offer sweep failed')
                if self.stop.wait(interval):
                    return
        threading.Thread(target=loop, name='trade-offers', daemon=True).start()

    def close(self):
        self.stop.set()

    def _owner_name(self, game, names):
        owner = owner_of(game)
        if owner not in names:
            auth = getattr(self.manager, 'auth', None)
            user = auth.user(owner) if auth else None
            names[owner] = (user['display_name'] or user['username']) if user and not user['placeholder'] else None
        return names[owner]

    def public(self, offer, games=None, names=None):
        if games is None:
            games = {game['id']: game for game in self.registry.adventures()}
        names = {} if names is None else names
        display = offer.get('display') or {}

        def side(prefix):
            game = games.get(offer[prefix + '_id']) or {}
            return {**self._side(offer[prefix + '_id'], game.get('name') or 'A deleted adventure', game.get('version'),
                                 display.get(prefix) or {}), 'key': offer[prefix + '_key'] or None,
                    'owner_id': owner_of(game) if game else None,
                    'owner_name': self._owner_name(game, names) if game else None}
        trade = None
        if offer['manual_id']:
            try:
                trade = self.coordinator.manual_status(offer['manual_id'])
            except KeyError:
                trade = None
        expires = {PENDING: offer['created_at'] + EXPIRE_SECONDS, ACCEPTED: offer['updated_at'] + ACCEPTED_EXPIRE}
        return {'id': offer['id'], 'status': offer['status'], 'reason': offer['reason'],
                'created_at': offer['created_at'], 'updated_at': offer['updated_at'],
                'expires_at': expires.get(offer['status']) if not trade or trade.get('state') in WAITING else None,
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
        names = {}

        def pick(direction):
            rows = [row for row in offers if row[direction] == aid]
            shown = [row for row in rows if row['status'] in OPEN]
            shown += [row for row in rows if row['status'] not in OPEN][:SHOW_FINISHED]
            return [self.public(row, games, names) for row in shown]
        return {'adventure_id': aid, 'incoming': pick('to_id'), 'outgoing': pick('from_id'),
                'viewer_only': self.viewer_only(aid)}
