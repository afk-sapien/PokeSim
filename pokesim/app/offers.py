"""Trade offers: one adventure asks another for a Pokémon in exchange for one of its own.

An offer waits until the other adventure accepts, declines or the sender withdraws it.
Accepting checks both Pokémon again and queues a manual trade, so only hard cable limits
can stop it. Offers live in the library registry and survive restarts.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time

from .. import config
from .coordinator import LINKABLE
from .registry import identifier, validate_id

PENDING, ACCEPTED = 'pending', 'accepted'
OPEN = (PENDING, ACCEPTED)
STATUSES = ('pending', 'accepted', 'declined', 'withdrawn', 'expired', 'failed', 'completed')
EXPIRE_SECONDS = 7 * 86400
KEEP_FINISHED = 200
MAX_PENDING = 25
SHOW_FINISHED = 20
FIELDS = ('from_id', 'from_key', 'to_id', 'to_key')


class ViewOnlyError(Exception):
    """The adventure that would act is view-only."""


class Gone(ValueError):
    """A Pokémon or adventure in the offer no longer exists, so the offer expires."""


class HardLimit(ValueError):
    """The cable cannot carry this pair, so the offer fails."""


def _name(display, fallback='The Pokémon'):
    display = display or {}
    nickname, name = display.get('nickname'), display.get('name')
    if nickname and name and nickname.lower() != name.lower():
        return f'{nickname} ({name})'
    return name or nickname or fallback


class TradeOffers:
    def __init__(self, manager):
        self.manager = manager
        self.guard = threading.Lock()

    @property
    def registry(self):
        return self.manager.registry

    @property
    def coordinator(self):
        return self.manager.coordinator

    # Checks

    def viewer_only(self, aid):
        try:
            game = self.registry.adventure(aid)
        except KeyError:
            return bool(config.VIEWER_ONLY)
        return bool(config.VIEWER_ONLY or game['settings'].get('viewer_only'))

    def _writer(self, aid):
        if self.viewer_only(aid):
            raise ViewOnlyError('This adventure is view-only')

    def _adventure(self, aid, *, accepting=False):
        try:
            game = self.registry.adventure(aid)
        except KeyError as error:
            raise Gone('An adventure in this offer was deleted') from error
        if game['archived']:
            raise (Gone if accepting else ValueError)(f'{game["name"]} was archived')
        reason = self.coordinator.manual_game_reason(game)
        if not reason:
            return game
        permanent = game['version'] not in LINKABLE or (game.get('provenance') or {}).get('trading_blocked')
        # A stopped adventure only delays an answer. Start it and try again.
        raise (HardLimit if accepting and permanent else ValueError)(f'{game["name"]}: {reason}')

    def _inventories(self, *aids):
        def load(aid):
            inventory = self.coordinator.manual_inventory(aid)
            if inventory.get('reason'):
                raise ValueError(f'{self.registry.adventure(aid)["name"]}: {inventory["reason"]}')
            return inventory
        with ThreadPoolExecutor(max_workers=len(aids)) as pool:
            return list(pool.map(load, aids))

    @staticmethod
    def _find(inventory, key, game, display=None):
        row = next((mon for mon in inventory.get('pokemon') or [] if mon.get('trade_key') == key), None)
        if row is None:
            raise Gone(f'{_name(display)} is no longer in {game["name"]}')
        if row.get('blocked'):
            raise HardLimit(f'{_name(row)}: {row["blocked"]}')
        return dict(row)

    def _pair_reason(self, give_inventory, take_inventory, give, take):
        coordinator = self.coordinator
        if coordinator._compatible_pair(give_inventory, take_inventory, coordinator._offer_for(give, take_inventory),
                                        coordinator._offer_for(take, give_inventory)):
            return ''
        return coordinator._capsule_reason(give_inventory, take_inventory, give, take)

    def _check(self, offer, *, accepting=False):
        """Both Pokémon, read from their adventures now, or the reason the pair cannot trade."""
        sender = self._adventure(offer['from_id'], accepting=accepting)
        receiver = self._adventure(offer['to_id'], accepting=accepting)
        give_inventory, take_inventory = self._inventories(offer['from_id'], offer['to_id'])
        display = offer.get('display') or {}
        give = self._find(give_inventory, offer['from_key'], sender, display.get('from'))
        take = self._find(take_inventory, offer['to_key'], receiver, display.get('to'))
        reason = self._pair_reason(give_inventory, take_inventory, give, take)
        if reason:
            raise HardLimit(reason)
        return give, take

    @staticmethod
    def _snapshot(row):
        keys = ('name', 'nickname', 'dex', 'species', 'level', 'power', 'battle_power', 'shiny',
                'location', 'box', 'slot', 'cartridge_generation')
        return {key: row.get(key) for key in keys}

    # Picker

    def targets(self, from_id):
        """Every other adventure, with the reason it cannot take an offer right now."""
        validate_id(from_id)
        self.registry.adventure(from_id)
        rows = []
        for game in self.registry.adventures():
            if game['id'] == from_id or game['archived']:
                continue
            reason = self.coordinator.manual_game_reason(game)
            rows.append({'id': game['id'], 'name': game['name'], 'version': game['version'],
                         'generation': 2 if game['version'] in {'gold', 'silver', 'crystal'} else 1,
                         'available': not reason, 'reason': reason})
        return {'adventures': rows, 'viewer_only': self.viewer_only(from_id)}

    def limits(self, from_id, from_key, to_id):
        """Hard limits for offering one Pokémon to each Pokémon in another adventure."""
        for aid in (from_id, to_id):
            validate_id(aid)
        if from_id == to_id:
            raise ValueError('Choose another adventure')
        sender, receiver = self._adventure(from_id), self._adventure(to_id)
        give_inventory, take_inventory = self._inventories(from_id, to_id)
        give = next((mon for mon in give_inventory.get('pokemon') or [] if mon.get('trade_key') == from_key), None)
        if give is None:
            raise ValueError(f'That Pokémon is no longer in {sender["name"]}')
        blocked = {}
        for take in take_inventory.get('pokemon') or []:
            if not take.get('trade_key'):
                continue
            reason = take.get('blocked') or give.get('blocked') or self._pair_reason(give_inventory, take_inventory, give, take)
            if reason:
                blocked[take['trade_key']] = reason
        return {'from': {**self._side(from_id, sender['name'], sender['version'], self._snapshot(give)),
                         'key': from_key, 'blocked': give.get('blocked') or ''},
                'to': {'adventure_id': to_id, 'adventure_name': receiver['name'], 'version': receiver['version']},
                'blocked': blocked, 'viewer_only': self.viewer_only(from_id)}

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

    def _side(self, aid, name, version, display):
        dex = display.get('dex')
        return {'adventure_id': aid, 'adventure_name': name, 'version': version, **display,
                'sprite_url': f'/games/{aid}/sprites/{dex}.png?v=rom-portraits-1' if type(dex) is int and 1 <= dex <= 251 else None}

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
