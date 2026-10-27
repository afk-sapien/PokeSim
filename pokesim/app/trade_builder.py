"""The trade builder: the owner picks a Pokémon in two of their adventures and trades them.

Both Pokémon are read from their adventures again before the trade is queued, so only
hard cable limits can stop it. A game busy with another trade is no limit: the trade waits
in line and both Pokémon are checked again when its turn comes. A view-only adventure
cannot trade by hand.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .. import config
from pokecore.identity import find
from .coordinator import BUSY_NOTE, LINKABLE
from .assets import portrait_url
from .registry import identifier, validate_id

FIELDS = ('from_id', 'from_key', 'to_id', 'to_key')
VIEW_ONLY = 'This adventure is view-only, so it cannot trade'


class ViewOnlyError(Exception):
    """The adventure that would act is view-only."""


class Gone(ValueError):
    """A Pokémon or adventure in the trade no longer exists."""


class HardLimit(ValueError):
    """The cable cannot carry this pair."""


def _name(display, fallback='The Pokémon'):
    display = display or {}
    nickname, name = display.get('nickname'), display.get('name')
    if nickname and name and nickname.lower() != name.lower():
        return f'{nickname} ({name})'
    return name or nickname or fallback


class TradeBuilder:
    def __init__(self, manager):
        self.manager = manager

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
            raise Gone('An adventure in this trade was deleted') from error
        if game['archived']:
            raise (Gone if accepting else ValueError)(f'{game["name"]} was archived')
        reason = self.coordinator.manual_game_reason(game)
        if not reason:
            return game
        permanent = game['version'] not in LINKABLE or (game.get('provenance') or {}).get('trading_blocked')
        # A stopped adventure only delays a trade. Start it and try again.
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
        row = find(inventory.get('pokemon') or [], key)
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

    def _check(self, trade, *, accepting=False):
        """Both Pokémon, read from their adventures now, or the reason the pair cannot trade."""
        sender = self._adventure(trade['from_id'], accepting=accepting)
        receiver = self._adventure(trade['to_id'], accepting=accepting)
        give_inventory, take_inventory = self._inventories(trade['from_id'], trade['to_id'])
        display = trade.get('display') or {}
        give = self._find(give_inventory, trade['from_key'], sender, display.get('from'))
        take = self._find(take_inventory, trade['to_key'], receiver, display.get('to'))
        reason = self._pair_reason(give_inventory, take_inventory, give, take)
        if reason:
            raise HardLimit(reason)
        return give, take

    @staticmethod
    def _snapshot(row):
        keys = ('name', 'nickname', 'dex', 'species', 'level', 'power', 'battle_power', 'shiny',
                'location', 'box', 'slot', 'cartridge_generation', 'type_names', 'dv_stars',
                'dv_total', 'dv_percent', 'perfect_dvs')
        return {key: row.get(key) for key in keys}

    def _side(self, aid, name, version, display):
        dex = display.get('dex')
        return {'adventure_id': aid, 'adventure_name': name, 'version': version, **display,
                'sprite_url': portrait_url(aid, dex, bool(display.get('shiny')))}

    # Picker

    def _give_reason(self, give_inventory, take_inventory, give):
        """Why the chosen Pokémon itself cannot go to the other adventure, whatever it is traded for."""
        if give.get('blocked'):
            return give['blocked']
        old = give_inventory.get('cartridge_generation', 1)
        if old == take_inventory.get('cartridge_generation', 1):
            return ''
        modern = give_inventory if old == 2 else take_inventory
        if modern.get('time_capsule_ready') and (give.get('time_capsule_compatible') if old == 2
                                                 else give.get('time_capsule_compatible') is not False):
            return ''
        return self.coordinator._capsule_reason(give_inventory, take_inventory, give, give)

    def _target_reason(self, give_inventory, give, game):
        """Why one adventure cannot take this Pokémon, read from its PC now, or an empty string."""
        try:
            take_inventory = self.coordinator.manual_inventory(game['id'])
        except (RuntimeError, OSError, KeyError, ValueError) as error:
            return f'This adventure did not answer: {error}'
        if take_inventory.get('reason'):
            return take_inventory['reason']
        reason = self._give_reason(give_inventory, take_inventory, give)
        if reason:
            return reason
        reasons = []
        for take in take_inventory.get('pokemon') or []:
            if not take.get('trade_key'):
                continue
            reason = take.get('blocked') or self._pair_reason(give_inventory, take_inventory, give, take)
            if not reason:
                return ''
            reasons.append(reason)
        if len(set(reasons)) == 1:
            return reasons[0]
        return f'Nothing in {game["name"]} can be traded for {_name(give)}'

    def targets(self, from_id, from_key=None):
        """Every other adventure, with the reason it cannot trade right now.

        A view-only adventure is listed but cannot be chosen. With from_key, each adventure
        is also checked against that Pokémon, so one that cannot take it is greyed out
        before the owner opens its PC.
        """
        validate_id(from_id)
        sender = self.registry.adventure(from_id)
        games = [game for game in self.registry.adventures() if game['id'] != from_id and not game['archived']]
        reasons = {game['id']: (VIEW_ONLY if self.viewer_only(game['id']) else '')
                   or self.coordinator.manual_game_reason(game) for game in games}
        busy = self.coordinator.busy_adventures()
        if from_key is not None:
            if not isinstance(from_key, str) or not 1 <= len(from_key) <= 256:
                raise ValueError('Choose a Pokémon to trade')
            try:
                give_inventory = self.coordinator.manual_inventory(from_id)
            except (RuntimeError, OSError, KeyError) as error:
                raise ValueError(f'{sender["name"]} did not answer: {error}') from error
            sender_reason = give_inventory.get('reason') or ''
            give = find(give_inventory.get('pokemon') or [], from_key)
            if give is None and not sender_reason:
                raise ValueError(f'That Pokémon is no longer in {sender["name"]}')
            open_games = [game for game in games if not reasons[game['id']]]
            if sender_reason or give.get('blocked'):
                for game in open_games:
                    reasons[game['id']] = sender_reason or give['blocked']
            elif open_games:
                with ThreadPoolExecutor(max_workers=min(8, len(open_games))) as pool:
                    found = pool.map(lambda game: self._target_reason(give_inventory, give, game), open_games)
                    reasons.update(zip([game['id'] for game in open_games], found))
        rows = [{'id': game['id'], 'name': game['name'], 'version': game['version'],
                 'generation': 2 if game['version'] in {'gold', 'silver', 'crystal'} else 1,
                 'available': not reasons[game['id']], 'reason': reasons[game['id']],
                 'busy': BUSY_NOTE if game['id'] in busy and not reasons[game['id']] else ''} for game in games]
        return {'adventures': rows, 'from_key': from_key, 'viewer_only': self.viewer_only(from_id)}

    def limits(self, from_id, from_key, to_id):
        """Hard limits for trading one Pokémon for each Pokémon in another adventure.

        A limit of the chosen Pokémon itself is reported once, as from.blocked, and not
        repeated for every Pokémon it could be traded for.
        """
        for aid in (from_id, to_id):
            validate_id(aid)
        if from_id == to_id:
            raise ValueError('Choose another adventure')
        sender, receiver = self._adventure(from_id), self._adventure(to_id)
        give_inventory, take_inventory = self._inventories(from_id, to_id)
        give = find(give_inventory.get('pokemon') or [], from_key)
        if give is None:
            raise ValueError(f'That Pokémon is no longer in {sender["name"]}')
        give_reason = self._give_reason(give_inventory, take_inventory, give)
        blocked = {}
        takes = [] if give_reason else take_inventory.get('pokemon') or []
        for take in takes:
            if not take.get('trade_key'):
                continue
            reason = take.get('blocked') or self._pair_reason(give_inventory, take_inventory, give, take)
            if reason:
                blocked[take['trade_key']] = reason
        pokemon = [{**self._side(to_id, receiver['name'], receiver['version'], self._snapshot(take)),
                    'key': take['trade_key'], 'blocked': give_reason or blocked.get(take['trade_key'], '')}
                   for take in take_inventory.get('pokemon') or [] if take.get('trade_key')]
        return {'from': {**self._side(from_id, sender['name'], sender['version'], self._snapshot(give)),
                         'key': from_key, 'blocked': give_reason},
                'to': {'adventure_id': to_id, 'adventure_name': receiver['name'], 'version': receiver['version'],
                       'viewer_only': self.viewer_only(to_id)},
                'blocked': blocked, 'pokemon': pokemon, 'viewer_only': self.viewer_only(from_id),
                'busy': give_inventory.get('busy') or take_inventory.get('busy') or '',
                'starts_now': not self.viewer_only(from_id) and not self.viewer_only(to_id)}

    def pokemon(self, aid):
        """Every Pokémon one adventure could trade by hand, with only hard limits marked."""
        validate_id(aid)
        game = self.registry.adventure(aid)
        reason = self.coordinator.manual_game_reason(game)
        inventory = {}
        if not reason:
            try:
                inventory = self.coordinator.manual_inventory(aid)
            except (RuntimeError, OSError, KeyError, ValueError) as error:
                reason = f'This adventure did not answer: {error}'
        reason = reason or inventory.get('reason') or ''
        rows = [{**self._side(aid, game['name'], game['version'], self._snapshot(mon)),
                 'key': mon['trade_key'], 'blocked': mon.get('blocked') or ''}
                for mon in inventory.get('pokemon') or [] if mon.get('trade_key')]
        return {'adventure_id': aid, 'adventure_name': game['name'], 'version': game['version'],
                'reason': reason, 'busy': '' if reason else inventory.get('busy') or '', 'pokemon': rows,
                'viewer_only': self.viewer_only(aid)}

    # Trade

    def create(self, data):
        """Check both Pokémon now and queue the trade. It starts when the Cable Club and both games are free."""
        if not isinstance(data, dict) or not set(FIELDS) <= set(data) or set(data) - set(FIELDS) - {'request_id'}:
            raise ValueError('Choose a Pokémon to trade and one to receive')
        selection = {name: data[name] for name in FIELDS}
        for name in ('from_id', 'to_id'):
            validate_id(selection[name])
        for name in ('from_key', 'to_key'):
            if not isinstance(selection[name], str) or not 1 <= len(selection[name]) <= 256:
                raise ValueError('Choose a Pokémon on each side')
        if selection['from_id'] == selection['to_id']:
            raise ValueError('Choose another adventure to trade with')
        request_id = validate_id(data.get('request_id') or identifier())
        try:
            # Sending the same request again returns the trade it already queued.
            return self.coordinator.manual_status(request_id)
        except KeyError:
            pass
        for name in ('from_id', 'to_id'):
            self.registry.adventure(selection[name])
            self._writer(selection[name])
        give, take = self._check(selection)
        entry = self.coordinator.enqueue_manual({'left_id': selection['from_id'], 'left_key': selection['from_key'],
                                                 'right_id': selection['to_id'], 'right_key': selection['to_key'],
                                                 'request_id': request_id, 'names': {'left': _name(give), 'right': _name(take)}})
        return self.coordinator.manual_status(entry['id'])

    def cancel(self, mid):
        """Take a trade that still waits for the Cable Club out of line. A started trade cannot be cancelled here."""
        trade = self.coordinator.manual_status(validate_id(mid))
        for aid in (trade['left_id'], trade['right_id']):
            self._writer(aid)
        return self.coordinator.cancel_queued(mid)
